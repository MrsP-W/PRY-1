"""D4.5 — 业务层接入: IMAP 同步 → PolicyEngine + LaneBoard + Heartbeat.

设计 (D4.5 v1.0 锁定, P0 业务语义修复后):

  D4.4 落地的 4 件套 (TaskPacket / PolicyEngine / LaneBoard / Heartbeat) 在 D4.4
  报告中明说"业务层 (classifier / drafter) 才真实调用 evaluate()". D4.5 第一个
  真实业务场景: D3.3 IMAP 同步 (D2 connectors/imap.py 拉邮件 + D3.3 sync.py
  入库到 SQLCipher DB) 接入决策引擎, 让 sync 流程具备:

    1. **可观测**: 每次 sync 落 1 条 PolicyDecisionEvent 到 events 表
    2. **可重试决策**: failed > 0 + consecutive_failures < 3 → 触发 RetryAvailable
    3. **可合并决策**: 全部 AC pass → 触发 MergeRequired
    4. **可升级决策**: failed > 0 + consecutive_failures >= 3 → 触发 EscalateRequired
    5. **可看**: LaneBoard 记录每次 sync 状态 (FINISHED if 全 AC pass, else BLOCKED)
    6. **可探活**: Heartbeat 记录 transport 状态 (全 AC pass = alive)

  D4.5 P0 业务语义修复 (D4.5 ready_for_review → v1.0 锁定):
    - 严判入口: branch_stale / now_ms / consecutive_failures 必须是原生 bool/int
      (与 D4.4 P1 修复对齐, 拒绝 type-coerce, 脏输入早失败)
    - escalate 语义: failed > 0 AND consecutive_failures >= 3 (达到阈值才升级)
    - lane/heartbeat 一致性: 全部 AC pass 才算"sync 成功", 否则 BLOCKED +
      transport_dead, 单一真相源 = acceptance_results

  D4.5 v1.0.1 反馈修复 (P0 文档/可观测性补完):
    - evaluate_and_emit 把 lane_entry_id + run_id 透传到 PolicyEngine.evaluate
    - PolicyEngine._emit_decision_event 把 lane_entry_id + run_id 写入 event_metadata
    - 便于 mmx policy history --lane 查询跨次 sync 的决策历史(反馈 #1 闭环)

依赖注入 (D3.3 → D4.5 兼容):
  - IMAPSync.__init__ 新增可选参数 `event_store` (D4.3) 和 `policy_engine` (D4.4)
  - 不传时 = D3.3 行为不变 (向后兼容)
  - scripts/sync_imap.py 默认不挂, 业务层调用方显式注入

SyncPolicyAdapter 是 D4.5 的核心:
  - `build_packet()` — IMAP 同步上下文 → TaskPacket (8 必含字段)
  - `build_context()` — SyncResult → PolicyEngine context (12 字段, 严判)
  - `record_to_lane()` — 同步结果 → LaneEntry.add() / .update()
  - `tick_heartbeat()` — IMAP healthcheck 成功 → Heartbeat.update()
  - `evaluate_and_emit()` — 主入口: evaluate() + EventStore 落地 1 条事件
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from my_ai_employee.events.store import EventStore
from my_ai_employee.policy.heartbeat import Heartbeat, Liveness
from my_ai_employee.policy.lane_board import LaneBoard, LaneEntry, LaneStatus
from my_ai_employee.policy.policy_engine import PolicyEngine, PolicyEvaluation
from my_ai_employee.policy.task_packet import (
    PermissionProfile,
    RecoveryPolicy,
    TaskPacket,
)

if TYPE_CHECKING:
    from my_ai_employee.core.sync import SyncResult


# ===== 同步专用 TaskPacket factory =====


def build_imap_sync_packet(
    *,
    source: str,
    inserted: int,
    failed: int,
    duration_seconds: float,
) -> TaskPacket:
    """D4.5 业务模板: IMAP 同步任务 → TaskPacket (8 必含字段).

    字段语义 (g006 §"Task packet schema" 对齐):
      - objective: 任务目标 (人类可读, ≤32 字符便于 subject_id 截断)
      - scope: 影响范围 (本次限定到 core/sync.py 1 个文件)
      - resources: 依赖资源 (IMAP + SQLCipher DB)
      - acceptance_criteria: 验收标准 (3 条, 与 SyncResult 字段一一对应)
      - model / provider: 调用方模型 (本场景 = "policy_engine" / "policy")
      - permission_profile: READ_ONLY (sync 不修改 IMAP, 只读后写本地 DB)
      - recovery_policy: RETRY_ON_TRANSIENT (网络/锁是 transient, 业务错不重试)

    验收标准 (与 PolicyEngine acceptance_results 对齐):
      [0] inserted > 0 (有进度, 哪怕 1 封)
      [1] failed == 0 (无失败隔离计数)
      [2] duration < 30s (D3.3 spike 1 万封 < 30s 是基线)
    """
    return TaskPacket(
        objective=f"imap_sync:{source}",
        scope=["core/sync.py"],
        resources=["imap:ssl:993", "db:sqlcipher"],
        acceptance_criteria=[
            "inserted>0",
            "failed=0",
            f"duration<30s (actual={duration_seconds:.2f}s)",
        ],
        model="policy_engine",
        provider="policy",
        permission_profile=PermissionProfile.READ_ONLY.value,
        recovery_policy=RecoveryPolicy.RETRY_ON_TRANSIENT.value,
    )


def compute_acceptance_results(
    *,
    inserted: int,
    failed: int,
    duration_seconds: float,
) -> list[bool]:
    """由 SyncResult 计算 3 条 acceptance_criteria 是否 pass.

    返回 list[bool] (PolicyEngine._rule_merge_required 严判 type() is bool).
    """
    return [
        bool(inserted > 0),
        bool(failed == 0),
        bool(duration_seconds < 30.0),
    ]


# ===== context 构造 (PolicyEngine 12 字段严判) =====


def build_sync_policy_context(
    *,
    result: SyncResult,
    consecutive_failures: int,
    branch_stale: bool = False,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """SyncResult → PolicyEngine context (12 字段, D4.4 严判类型).

    字段映射:
      - last_error_recoverable: failed > 0 AND consecutive_failures < 3
        (连续失败 < 3 = 可能是 transient, 应重试)
      - current_attempts: 1 (sync 自身不重试, 重试是 caller 决定)
      - max_attempts: 3 (与 consecutive_failures 阈值对齐)
      - branch_stale: 由 caller 决定 (默认 False — sync 不依赖 git)
      - last_heartbeat_ms / stale_threshold_ms / now_ms:
        Heartbeat 喂入, 默认 0 表示无心跳
      - action_sensitive: False (READ_ONLY 操作)
      - has_approval_token: True (IMAP 同步无需审批)
      - approval_token_id: "" (空 — 同步不需要)
      - acceptance_results: [inserted>0, failed=0, duration<30s]
      - policy_eval_failed: failed > 0 AND consecutive_failures >= 3
        (达到连续失败阈值 = 应升级, 修复 D4.5 ready_for_review 反馈的语义问题)

    ⚠️ 严判入口 (D4.5 P0 修复, 拒绝 type-coerce, 与 D4.4 P1 对齐):
      - consecutive_failures: type() is int (排除 bool 子类), >= 0
      - branch_stale: type() is bool (拒绝 "false"/"true" 字符串)
      - now_ms: type() is int 或 None (若传)

    失败抛 ValueError (D4.4 P1 + D3.3.3 异常窄化教训 — 编程错误透传, 不静默 coerce)
    """
    import time

    # 严判入口 (D4.5 P0 修复 1: 拒 type-coerce, 与 D4.4 P1 对齐)
    if type(consecutive_failures) is not int or consecutive_failures < 0:
        # 注意: bool 是 int 子类, type(True) is int=False → 排除
        raise ValueError(
            f"consecutive_failures 必须是原生 int >= 0, 实际 "
            f"{type(consecutive_failures).__name__}={consecutive_failures!r}"
        )
    if type(branch_stale) is not bool:
        raise ValueError(
            f"branch_stale 必须是原生 bool, 实际 {type(branch_stale).__name__}={branch_stale!r}"
        )
    if now_ms is not None and type(now_ms) is not int:
        raise ValueError(f"now_ms 必须是 int 或 None, 实际 {type(now_ms).__name__}={now_ms!r}")

    # 修复 2: escalate 语义 — 达到阈值才升级 (D4.5 P0 反馈)
    # 之前: failed > consecutive_failures > 0
    # 现在: result.failed > 0 AND consecutive_failures >= 3
    recoverable = bool(result.failed > 0 and consecutive_failures < 3)
    policy_eval_failed = bool(result.failed > 0 and consecutive_failures >= 3)

    return {
        "last_error_recoverable": recoverable,
        "current_attempts": 1,
        "max_attempts": 3,
        "branch_stale": branch_stale,  # 已严判, 直接用
        "last_heartbeat_ms": 0,  # Heartbeat 单独管理, sync context 不强制注入
        "stale_threshold_ms": 60_000,
        "now_ms": now_ms if now_ms is not None else int(time.time() * 1000),
        "action_sensitive": False,
        "has_approval_token": True,
        "approval_token_id": "",
        "acceptance_results": compute_acceptance_results(
            inserted=result.inserted,
            failed=result.failed,
            duration_seconds=result.duration_seconds,
        ),
        "policy_eval_failed": policy_eval_failed,
    }


# ===== 同步决策数据类 =====


@dataclass(frozen=True)
class SyncDecisionReport:
    """D4.5 业务层接入的可观测报告.

    Attributes:
        evaluation: PolicyEngine.evaluate() 完整结果 (含 status / decisions / event_id)
        event_id: 落地到 events 表的 PolicyDecisionEvent id (None = 未落地)
        lane_entry_id: LaneBoard 中本 sync 的 entry_id (e.g. "sync:qq:20260609T153000")
        liveness: Heartbeat 评估的 Liveness (HEALTHY / STALLED / TRANSPORT_DEAD)
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness


# ===== SyncPolicyAdapter 主类 =====


class SyncPolicyAdapter:
    """D4.5 业务层接入适配器.

    把 D3.3 IMAPSync 接入 D4.4 任务策略板:
      - Heartbeat (transport 探活)
      - LaneBoard (同步任务看板)
      - PolicyEngine (6 决策)
      - EventStore (事件落地, D4.3)

    用法 (生产):

        from my_ai_employee.events.store import EventStore
        from my_ai_employee.policy import (
            Heartbeat, LaneBoard, PolicyEngine,
            SyncPolicyAdapter,
        )

        adapter = SyncPolicyAdapter(
            source="qq",
            event_store=event_store,
            engine=PolicyEngine(),
            heartbeat=Heartbeat(idle_threshold_ms=30_000),
            board=LaneBoard(idle_threshold_ms=60_000),
        )
        # IMAP 同步完成后
        report = adapter.evaluate_and_emit(sync_result, consecutive_failures=0)
        print(f"event_id={report.event_id} decisions={len(report.evaluation.decisions)}")

    设计要点:
      - 4 个依赖都可注入 (None = 跳过该环节, 用于测试或纯评估)
      - 不修改 D3.3 IMAPSync 主体 (保留 D3.3 行为 + 可选挂载)
      - lane_entry_id 命名: "sync:<source>:<run_id>" — 唯一性由 caller 保证
    """

    def __init__(
        self,
        *,
        source: str,
        event_store: EventStore | None = None,
        engine: PolicyEngine | None = None,
        heartbeat: Heartbeat | None = None,
        board: LaneBoard | None = None,
    ) -> None:
        if not isinstance(source, str) or not source:
            raise ValueError(f"source 必填非空 str, 实际 {type(source).__name__}={source!r}")
        self._source = source
        self._event_store = event_store
        self._engine = engine or PolicyEngine()
        self._heartbeat = heartbeat or Heartbeat(idle_threshold_ms=30_000)
        self._board = board or LaneBoard(idle_threshold_ms=60_000)

    # ===== 公开 API =====

    def build_lane_entry_id(self, run_id: str) -> str:
        """生成 LaneBoard entry_id: 'sync:<source>:<run_id>'. run_id 必填."""
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"run_id 必填非空 str, 实际 {type(run_id).__name__}={run_id!r}")
        return f"sync:{self._source}:{run_id}"

    def record_to_lane(
        self,
        *,
        run_id: str,
        status: LaneStatus,
        objective: str = "",
        owner: str = "imap_sync",
    ) -> LaneEntry:
        """LaneBoard 记录: add (ACTIVE/BLOCKED) 或 update (FINISHED).

        Args:
            run_id: 唯一运行 ID (caller 提供, 便于跨次 sync 区分)
            status: 目标状态 (FINISHED 需先 ACTIVE, 不能直接 add)
            objective: 任务描述 (默认空 = 用 source 名)
            owner: 责任人 (默认 "imap_sync")

        Returns:
            写入或更新后的 LaneEntry
        """
        entry_id = self.build_lane_entry_id(run_id)
        if not objective:
            objective = f"IMAP sync source={self._source}"
        # 已存在 → update (caller 用 update 推进状态)
        existing: LaneEntry | None = None
        try:
            existing = self._board.get(entry_id)
        except Exception:
            existing = None
        if existing is None:
            # 不存在 → add (FINISHED 状态不允许 add, 需先 ACTIVE 再 update)
            if status == LaneStatus.FINISHED:
                self._board.add(
                    LaneEntry(
                        entry_id=entry_id,
                        objective=objective,
                        status=LaneStatus.ACTIVE,
                        owner=owner,
                    )
                )
                return self._board.update(entry_id, status=LaneStatus.FINISHED, owner=owner)
            self._board.add(
                LaneEntry(
                    entry_id=entry_id,
                    objective=objective,
                    status=status,
                    owner=owner,
                )
            )
            return self._board.get(entry_id)
        # 已存在 → update
        return self._board.update(entry_id, status=status, owner=owner)

    def tick_heartbeat(
        self,
        *,
        transport_alive: bool = True,
        now_ms: int | None = None,
    ) -> Liveness:
        """刷新心跳 (IMAP 连接成功 → alive=True).

        Returns:
            评估后的 Liveness
        """
        # D4.5 P0 修复: type() is bool 严判 (与 D4.4 P1 一致, 拒 "true" 字符串)
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 {type(transport_alive).__name__}={transport_alive!r}"
            )
        self._heartbeat.update(transport_alive=transport_alive, now_ms=now_ms)
        return self._heartbeat.evaluate(now_ms=now_ms)

    def evaluate_and_emit(
        self,
        result: SyncResult,
        *,
        consecutive_failures: int = 0,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> SyncDecisionReport:
        """主入口: 评估 IMAP 同步结果 + 落 1 条 PolicyDecisionEvent.

        Args:
            result: D3.3 SyncResult (含 inserted / failed / duration 等)
            consecutive_failures: SyncState.consecutive_failures (喂 RetryAvailable)
            run_id: LaneBoard entry 唯一 ID (空 = 用 now_ms 字符串)
            now_ms: 注入时间 (默认 int(time.time() * 1000))

        Returns:
            SyncDecisionReport (含 evaluation / event_id / lane_entry_id / liveness)

        Raises:
            PolicyContractError: build_imap_sync_packet 失败 (8 字段不全)
            PolicyDecisionError: build_sync_policy_context 失败 (类型非法)
            ValueError: consecutive_failures / now_ms 严判失败 (D4.5 P0 严判入口)
            EventContractError / EventMetadataError: EventStore.insert 失败
        """
        import time as _time

        # 严判 consecutive_failures (D4.5 P0 修复 — type() is int 排除 bool 子类)
        if type(consecutive_failures) is not int or consecutive_failures < 0:
            raise ValueError(
                f"consecutive_failures 必须是原生 int >= 0, 实际 "
                f"{type(consecutive_failures).__name__}={consecutive_failures!r}"
            )

        # 1) 构造 TaskPacket
        packet = build_imap_sync_packet(
            source=self._source,
            inserted=result.inserted,
            failed=result.failed,
            duration_seconds=result.duration_seconds,
        )

        # 2) 构造 context (12 字段严判)
        context = build_sync_policy_context(
            result=result,
            consecutive_failures=consecutive_failures,
            now_ms=now_ms if now_ms is not None else int(_time.time() * 1000),
        )

        # 3) 计算 run_id + lane_entry_id (供后续 evaluate + lane + heartbeat 复用)
        #    D4.5 v1.0.1: run_id 透传到 event_metadata, 便于 mmx policy history --lane
        rid = run_id or str(int(_time.time() * 1000))
        lane_entry_id = self.build_lane_entry_id(rid)

        # 4) PolicyEngine.evaluate (落事件 + 透传 lane_entry_id / run_id)
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=self._event_store,  # None 时不落地 (纯评估)
            lane_entry_id=lane_entry_id,
            run_id=rid,
        )

        # 5) LaneBoard 记录 — 单一真相源: acceptance_results (D4.5 P0 修复 3)
        #    全部 AC pass → FINISHED + healthy; 否则 → BLOCKED + transport_dead
        #    (修复前: 只看 failed==0 AND inserted>0, 把空同步 + 慢同步误标)
        ac_results = compute_acceptance_results(
            inserted=result.inserted,
            failed=result.failed,
            duration_seconds=result.duration_seconds,
        )
        all_pass = bool(all(ac_results))  # 3 条 AC 全 True 才算成功
        self.record_to_lane(
            run_id=rid,
            status=LaneStatus.FINISHED if all_pass else LaneStatus.BLOCKED,
        )

        # 6) Heartbeat: 同步成功 → transport_alive=True
        liveness = self.tick_heartbeat(transport_alive=all_pass, now_ms=now_ms)

        return SyncDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
        )


# ===== 模块导出 =====


__all__ = [
    "SyncPolicyAdapter",
    "SyncDecisionReport",
    "build_imap_sync_packet",
    "build_sync_policy_context",
    "compute_acceptance_results",
]
