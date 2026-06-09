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

  D4.6 业务层复用 (D4.5 范本扩展 — EmailClassifierAdapter):
    - 复用 SyncPolicyAdapter 4 依赖可注入范本 (event_store / engine / heartbeat / board)
    - EmailClassifier.classify() → 类别 + 置信度 → 喂 PolicyEngine.evaluate
    - lane_entry_id 命名 "classify:<source>:<run_id>"(与 sync: 区分)
    - 便于 mmx policy history --lane 跨次分类查询决策历史

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

EmailClassifierAdapter 是 D4.6 业务层接入点:
  - `build_packet()` — 邮件上下文 → TaskPacket (8 必含字段, model=classifier_used)
  - `build_context()` — ClassificationResult → PolicyEngine context (12 字段, 严判)
  - `classify_and_emit()` — 主入口: classify() + PolicyEngine.evaluate() + 落 1 条事件

D4.6 v1.0.2 修复(D4.6 6/9 复检 P1-1 + P1-2 + P2-5):
  - P1-1: 拆 classify_and_emit 为成功入口(classification 必填, 失败计数器
    强制归零) + 失败入口 record_classify_failure_and_emit(last_error + cf 必填,
    last_classify_failed 隐式 True),从根上断绝"成功结果 + last_classify_failed=True
    → retry_available+merge_required" 状态耦合
  - P1-2: classify_and_emit 严判 category ∈ 5 类 + latency_ms >= 0
  - P2-5: build_classify_packet 加 math.isfinite() 拒 NaN/Inf(与 _parse_classification_response 对齐)

D4.6 v1.0.2 二次复检修复(D4.6 6/9 早晨第二次复检 4 项):
  - 严判下沉(P1):category/isfinite/latency_ms 校验下沉到 2 个公共 helper
    (compute_classification_acceptance + build_classify_policy_context),
    防止 Adapter 重构后绕过严判(D3.3.3 教训:窄化异常范围 + 公共 API 严判)
  - 失败报告契约(P2-2):新增 ClassifyFailureDecisionReport 区分成功/失败报告,
    失败入口不再用空 category 违反 ClassifyDecisionReport "category: 5 类枚举" 契约
  - 顶层导出(P2-3):build_classify_failure_packet + ClassifyFailureDecisionReport
    顶层暴露(top-level import 不再失败)
  - 文档同步(P3):ai 46 / adapter 50 / 全量 592 测试数 + uv build 通过 + v1.0.2 段补完

D4.6 v1.0.2 第三次复检修复(D4.6 6/9 早晨第三次复检 4 项):
  - 公共构造器严判(P1):build_classify_packet 复用 _validate_classify_category
    公共 helper, 防止构造器直接绕过 5 类枚举(此前仅 type() 严判, 缺 5 类校验)
  - 失败报告 Literal[True] + 字段自洽(P2):ClassifyFailureDecisionReport.failed
    字段从 bool 升级为 Literal[True](类型层面固化), __post_init__ 校验
    last_error 非空 + consecutive_classify_failures >= 1(D3.3.3 教训)
  - 异常统一 ValueError(P2):classify_and_emit 走 _validate_classify_category
    公共 helper(此前内联 `if x not in frozenset` 与 build_classify_packet 不一致)
  - 文档同步(P3):classify_and_emit 用例 docstring 移除已删除的
    consecutive_classify_failures 参数; record_classify_failure_and_emit 返回值
    docstring 从 ClassifyDecisionReport 改为 ClassifyFailureDecisionReport
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

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


# 5 类分类枚举常量(D4.6 v1.0.2 P1-2 严判入口)
# 与 ai/classifier.py::EmailCategory 严格 1:1 对齐(避免循环 import,内联)
_VALID_CLASSIFY_CATEGORIES: frozenset[str] = frozenset(
    {"URGENT", "TODO", "FYI", "SPAM", "PERSONAL"}
)


# ===== 公共严判 helper(D4.6 v1.0.2 二次复检 P1 修复)=====
# 设计: category / confidence / latency_ms 三类业务字段的严判下沉到 helper 层,
# 防止 Adapter 重构后绕过严判(D3.3.3 教训:窄化异常范围 + 公共 API 必须自防御)。
# 3 个 helper 都是纯函数 + raise ValueError,可在 factory / public 入口复用。


def _validate_classify_category(category_value: Any) -> str:
    """严判 category_value 必须是 5 类枚举之一(D4.6 业务契约).

    Args:
        category_value: 任意类型,内部 type() 严判

    Returns:
        原值(校验通过)

    Raises:
        ValueError: type 错 / 不在 5 类枚举
    """
    if type(category_value) is not str:
        raise ValueError(
            f"category_value 必须是原生 str, 实际 {type(category_value).__name__}={category_value!r}"
        )
    if category_value not in _VALID_CLASSIFY_CATEGORIES:
        raise ValueError(
            f"category_value 必须是 5 类之一 ({sorted(_VALID_CLASSIFY_CATEGORIES)}), "
            f"实际 {category_value!r}"
        )
    return category_value


def _validate_classify_confidence(confidence: Any) -> float:
    """严判 confidence 必须是 0-1 有限数字(D4.6 业务契约).

    Args:
        confidence: 任意类型,内部 type() 严判

    Returns:
        float 化的 confidence(校验通过)

    Raises:
        ValueError: type 错 / NaN / Inf / 越界 0-1
    """
    if type(confidence) is bool or not isinstance(confidence, (int, float)):
        raise ValueError(
            f"confidence 必须是数字(非 bool/str), 实际 {type(confidence).__name__}={confidence!r}"
        )
    confidence_float = float(confidence)
    if not math.isfinite(confidence_float):
        raise ValueError(f"confidence 必须是有限数字(非 NaN/Inf), 实际 {confidence_float}")
    if confidence_float < 0.0 or confidence_float > 1.0:
        raise ValueError(f"confidence 必须在 0-1 之间, 实际 {confidence_float}")
    return confidence_float


def _validate_classify_latency_ms(latency_ms: Any) -> int:
    """严判 latency_ms 必须是原生 int >= 0(D4.6 业务契约).

    Args:
        latency_ms: 任意类型,内部 type() 严判

    Returns:
        原值(校验通过)

    Raises:
        ValueError: type 错 / bool 子类 / 负数
    """
    if type(latency_ms) is bool or not isinstance(latency_ms, int):
        raise ValueError(
            f"latency_ms 必须是原生 int(非 bool/str), 实际 "
            f"{type(latency_ms).__name__}={latency_ms!r}"
        )
    if latency_ms < 0:
        raise ValueError(f"latency_ms 必须 >= 0, 实际 {latency_ms}")
    return latency_ms


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


# ===== D4.6 邮件分类适配器 =====


# 分类结果 → 验收标准(3 条 AC,D4.5 P0-3 单一真相源范本应用)
# AC[0] confidence >= 0.7 (高置信度,业务可用)
# AC[1] category 不是 SPAM(SPAM 后续单独处理,不进入主流程)
# AC[2] LLM 响应延迟 < 5000ms (5s 内必须有结果,超时就 BLOCKED)


def compute_classification_acceptance(
    *, category_value: str, confidence: float, latency_ms: int
) -> list[bool]:
    """由 ClassificationResult 计算 3 条 acceptance_criteria 是否 pass.

    3 条 AC(与 PolicyEngine 12 字段 acceptance_results 对齐):
      [0] confidence >= 0.7 (高置信度,业务可用)
      [1] category != SPAM (SPAM 单独走"低优先级"分支,不阻塞主决策)
      [2] latency_ms < 5000 (5s 内出结果)

    D4.6 v1.0.2 二次复检 P1 修复: 公共 helper 入口加 3 类严判(category ∈ 5 类
    + confidence 有限数 0-1 + latency_ms >= 0),防止 Adapter 重构后绕过严判
    (D3.3.3 教训:窄化异常范围 + 公共 API 必须自防御)。
    原 v1.0.2 写法只在校验前 field-access, 严判缺; 新版用 3 个 helper
    复用同一严判逻辑, classify_and_emit 主入口可省去重复严判。

    Returns:
        list[bool](PolicyEngine 严判 type() is bool,D4.4 P1 + D4.5 P0 教训应用)

    Raises:
        ValueError: category 不在 5 类 / confidence 非有限数 / latency_ms 负数
    """
    _validate_classify_category(category_value)
    _validate_classify_confidence(confidence)
    _validate_classify_latency_ms(latency_ms)
    return [
        bool(confidence >= 0.7),
        bool(category_value != "SPAM"),
        bool(latency_ms < 5000),
    ]


def build_classify_packet(
    *,
    email_id: int,
    source: str,
    category_value: str,
    model_full_id: str,
    confidence: float,
) -> TaskPacket:
    """D4.6 业务模板: 邮件分类任务 → TaskPacket (8 必含字段).

    Args:
        email_id: 邮件主键(emails.id, D3.2 ORM)
        source: 邮件来源 "qq" / "outlook" / "gmail"
        category_value: 5 类枚举值 (URGENT / TODO / FYI / SPAM / PERSONAL)
        model_full_id: 实际调用的 provider/model (如 "deepseek/deepseek-chat")
        confidence: 0-1 浮点

    Returns:
        TaskPacket(8 字段,与 SyncPolicyAdapter 范本对齐)
    """
    if type(email_id) is not int or isinstance(email_id, bool) or email_id < 0:
        raise ValueError(
            f"email_id 必须是原生 int >= 0, 实际 {type(email_id).__name__}={email_id!r}"
        )
    if type(source) is not str or not source:
        raise ValueError(f"source 必填非空 str, 实际 {type(source).__name__}")
    # D4.6 v1.0.2 第三次复检 P1 修复: category 严判下沉到 _validate_classify_category
    # 公共 helper(与 compute_classification_acceptance / build_classify_policy_context
    # 同一严判口径,防止 Adapter 重构后绕过)
    _validate_classify_category(category_value)
    if type(model_full_id) is not str or not model_full_id:
        raise ValueError(f"model_full_id 必填非空 str, 实际 {type(model_full_id).__name__}")
    if type(confidence) is bool or not isinstance(confidence, (int, float)):
        raise ValueError(f"confidence 必须是数字(非 bool), 实际 {type(confidence).__name__}")
    # D4.6 v1.0.2 P2-5 修复: 拒 NaN/Inf(NaN 任何比较返回 False,范围检查漏过)
    if not math.isfinite(confidence):
        raise ValueError(f"confidence 必须是有限数字(非 NaN/Inf), 实际 {confidence}")
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError(f"confidence 必须在 0-1 之间, 实际 {confidence}")

    return TaskPacket(
        objective=f"email_classify:source={source}:id={email_id}",
        scope=["ai/classifier.py", "core/models.py"],
        resources=["db:sqlcipher", "llm:router"],
        acceptance_criteria=[
            f"category={category_value}",
            f"confidence>={confidence:.2f}",
            "latency<5000ms",
        ],
        model=model_full_id,
        provider=model_full_id.split("/", 1)[0] if "/" in model_full_id else "unknown",
        permission_profile=PermissionProfile.READ_ONLY.value,
        recovery_policy=RecoveryPolicy.RETRY_ON_TRANSIENT.value,
    )


def build_classify_failure_packet(
    *,
    email_id: int,
    source: str,
    last_error_str: str,
    consecutive_classify_failures: int,
    model_full_id: str = "unknown",
) -> TaskPacket:
    """D4.6 v1.0.2 P1-1 新增: 分类失败专用 TaskPacket(8 必含字段).

    与 build_classify_packet 的差异:
      - objective: "email_classify_failed" 前缀(便于 lane 串联)
      - acceptance_criteria: 3 条失败相关(无 category / conf / latency 业务字段)
      - last_error_str 截断到 100 字符(防 prompt 撑爆)
      - consecutive_classify_failures 必填 >= 1(确为失败,不是首次)

    D3.3.3 教训应用: 严判入口, 拒 type-coerce。
    """
    if type(email_id) is not int or isinstance(email_id, bool) or email_id < 0:
        raise ValueError(
            f"email_id 必须是原生 int >= 0, 实际 {type(email_id).__name__}={email_id!r}"
        )
    if type(source) is not str or not source:
        raise ValueError(f"source 必填非空 str, 实际 {type(source).__name__}")
    if type(last_error_str) is not str or not last_error_str:
        raise ValueError(f"last_error_str 必填非空 str, 实际 {type(last_error_str).__name__}")
    if (
        type(consecutive_classify_failures) is not int
        or isinstance(consecutive_classify_failures, bool)
        or consecutive_classify_failures < 1
    ):
        raise ValueError(
            f"consecutive_classify_failures 必须是原生 int >= 1, 实际 "
            f"{type(consecutive_classify_failures).__name__}={consecutive_classify_failures!r}"
        )
    if type(model_full_id) is not str or not model_full_id:
        raise ValueError(f"model_full_id 必填非空 str, 实际 {type(model_full_id).__name__}")

    return TaskPacket(
        objective=f"email_classify_failed:source={source}:id={email_id}",
        scope=["ai/classifier.py", "core/models.py"],
        resources=["db:sqlcipher", "llm:router"],
        acceptance_criteria=[
            f"last_error={last_error_str[:100]}",
            f"consecutive_classify_failures={consecutive_classify_failures}",
            "retry_policy=retry_on_transient",
        ],
        model=model_full_id,
        provider=model_full_id.split("/", 1)[0] if "/" in model_full_id else "unknown",
        permission_profile=PermissionProfile.READ_ONLY.value,
        recovery_policy=RecoveryPolicy.RETRY_ON_TRANSIENT.value,
    )


def build_classify_policy_context(
    *,
    category_value: str,
    confidence: float,
    latency_ms: int,
    last_classify_failed: bool = False,
    consecutive_classify_failures: int = 0,
    branch_stale: bool = False,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """ClassificationResult → PolicyEngine context (12 字段严判).

    字段映射(对照 build_sync_policy_context 范本):
      - last_error_recoverable: last_classify_failed AND consecutive_classify_failures < 3
        (上次分类失败 + 未达阈值 = LLM 瞬时问题,可重试)
      - current_attempts: 1(分类不重试,重试由 caller)
      - max_attempts: 3
      - branch_stale: 由 caller 决定
      - last_heartbeat_ms / stale_threshold_ms / now_ms: 默认 0
      - action_sensitive: False(分类是 READ_ONLY,不发邮件)
      - has_approval_token: True(分类无需审批)
      - approval_token_id: ""
      - acceptance_results: [conf>=0.7, category!=SPAM, latency<5000]
      - policy_eval_failed: last_classify_failed AND consecutive_classify_failures >= 3
        (上次失败 + 达阈值 = 升级)

    ⚠️ 严判入口(D4.5 P0 教训应用 + D4.6 v1.0.1 P1-3 新增 last_classify_failed):
      - last_classify_failed: type() is bool(D4.6 v1.0.1 P1-3 新增,caller 显式告知)
      - consecutive_classify_failures: type() is int >= 0(排除 bool 子类)
      - branch_stale: type() is bool
      - now_ms: type() is int 或 None

    D4.6 v1.0.1 P1-3 修复(对照 D4.5 build_sync_policy_context 范本):
      - 旧版 `recoverable = bool(cf > 0 AND cf < 3)` 纯看 cf,导致上次失败后即使
        本次成功(recoverable 仍 True) → retry+merge 误触发
      - 新版引入 `last_classify_failed` 显式 bool,成功路径 caller 必传 False
        (adapter 不隐式推断 — D3.3.3 教训:不 catch-all 兜底)

    D4.6 v1.0.2 二次复检 P1 修复: category / confidence / latency_ms 3 类业务
    字段也走严判 helper,与 compute_classification_acceptance 同一严判口径
    (防止 Adapter 直接绕开 compute_classification_acceptance 调此函数时漏严判)。
    失败入口的 synthetic 值(category="URGENT" / confidence=0.0 / latency_ms=0)
    全部能通过严判(URGENT ∈ 5 类、0.0 有限且在 0-1、0 >= 0)。
    """
    import time

    # D4.6 v1.0.2 P1 修复: 业务字段走严判 helper(下沉到 helper 层,任何 caller 都受保护)
    _validate_classify_category(category_value)
    _validate_classify_confidence(confidence)
    _validate_classify_latency_ms(latency_ms)

    # 严判入口(D4.5 P0 修复 1 + D4.6 v1.0.1 P1-3 新增 last_classify_failed)
    if type(last_classify_failed) is not bool:
        raise ValueError(
            f"last_classify_failed 必须是原生 bool, 实际 "
            f"{type(last_classify_failed).__name__}={last_classify_failed!r}"
        )
    if type(consecutive_classify_failures) is not int or consecutive_classify_failures < 0:
        raise ValueError(
            f"consecutive_classify_failures 必须是原生 int >= 0, 实际 "
            f"{type(consecutive_classify_failures).__name__}={consecutive_classify_failures!r}"
        )
    if type(branch_stale) is not bool:
        raise ValueError(
            f"branch_stale 必须是原生 bool, 实际 {type(branch_stale).__name__}={branch_stale!r}"
        )
    if now_ms is not None and type(now_ms) is not int:
        raise ValueError(f"now_ms 必须是 int 或 None, 实际 {type(now_ms).__name__}={now_ms!r}")

    # D4.6 v1.0.1 P1-3 修复:与 D4.5 build_sync_policy_context 范本对齐
    # 用 `last_classify_failed` 显式 bool 替代纯 cf 推断
    # recoverable 需要 cf > 0 AND cf < 3(对应"曾经失败但未达阈值",纯 cf=0 不应触发)
    recoverable = bool(last_classify_failed and 0 < consecutive_classify_failures < 3)
    policy_eval_failed = bool(last_classify_failed and consecutive_classify_failures >= 3)

    return {
        "last_error_recoverable": recoverable,
        "current_attempts": 1,
        "max_attempts": 3,
        "branch_stale": branch_stale,
        "last_heartbeat_ms": 0,
        "stale_threshold_ms": 60_000,
        "now_ms": now_ms if now_ms is not None else int(time.time() * 1000),
        "action_sensitive": False,
        "has_approval_token": True,
        "approval_token_id": "",
        "acceptance_results": compute_classification_acceptance(
            category_value=category_value,
            confidence=confidence,
            latency_ms=latency_ms,
        ),
        "policy_eval_failed": policy_eval_failed,
    }


@dataclass(frozen=True)
class ClassifyDecisionReport:
    """D4.6 业务层接入的可观测报告(成功分类版本).

    Attributes:
        evaluation: PolicyEngine.evaluate() 完整结果
        event_id: 落地到 events 表的 PolicyDecisionEvent id
        lane_entry_id: LaneBoard 中本次分类的 entry_id
        liveness: Heartbeat 评估的 Liveness
        category: 5 类枚举(决策结果,EmailCategory.value)
        confidence: 置信度 [0.0, 1.0]
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    # 以下字段是 D4.6 业务侧关心的(与 SyncDecisionReport 差异)
    category: str  # EmailCategory.value, 必填 5 类之一
    confidence: float  # 0.0 ~ 1.0 有限数


@dataclass(frozen=True)
class ClassifyFailureDecisionReport:
    """D4.6 业务层接入的可观测报告(失败分类版本).

    D4.6 v1.0.2 二次复检 P2-2 新增: 旧版失败入口返回 ClassifyDecisionReport,
    用 `category=""` + `confidence=0.0` 强行填充,违反自身"category: 5 类"契约
    (D3.3.3 教训:数据类的字段约束必须自洽,不能用空串当占位符)。
    新版独立 dataclass 区分成功/失败,失败场景的字段语义不同:
      - failed: 永远 True(类型层面防止混入成功报告)
      - last_error: 截断到 200 字符的失败原因(便于人读)
      - consecutive_classify_failures: 连续失败计数(便于触发升级)

    D4.6 v1.0.2 第三次复检 P2 修复: failed 字段用 Literal[True] 类型层面固化,
    防止手动构造 ClassifyFailureDecisionReport(failed=False) 混入成功报告;
    __post_init__ 校验 last_error 非空 + consecutive_classify_failures >= 1,
    字段契约自洽(D3.3.3 教训:数据类的字段约束必须自洽)。

    Attributes:
        evaluation: PolicyEngine.evaluate() 完整结果
        event_id: 落地到 events 表的 PolicyDecisionEvent id
        lane_entry_id: LaneBoard 中本次分类的 entry_id
        liveness: Heartbeat 评估的 Liveness
        failed: Literal[True](类型层面与 ClassifyDecisionReport 区分,只可能为 True)
        last_error: 失败原因(必填非空,截断到 200 字符)
        consecutive_classify_failures: 连续失败次数(必填 >= 1)
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    failed: Literal[True]  # 必为 True(类型层面区分成功/失败)
    last_error: str  # 必填非空(>0 字符),截断到 200 字符
    consecutive_classify_failures: int  # 必填 >= 1

    def __post_init__(self) -> None:
        """D4.6 v1.0.2 第三次复检 P2 修复: 字段契约自洽校验.

        D3.3.3 教训: 数据类的字段约束必须自洽,不能依赖 caller 显式传对。
        失败报告若 last_error 为空 / consecutive_classify_failures < 1, 视为
        数据类构造错误, 早失败比静默接受更安全(避免日志/审计误以为成功)。
        Literal[True] 在运行时是 str 注解, mypy 阻拦但 Python 不阻拦,所以
        __post_init__ 也要显式校验 failed 必为 True(双层防御:静态 + 动态)。
        """
        if self.failed is not True:
            raise ValueError(
                f"ClassifyFailureDecisionReport.failed 必为 True "
                f"(Literal[True] 类型层面固化), 实际 {self.failed!r}"
            )
        if not isinstance(self.last_error, str) or not self.last_error:
            raise ValueError(
                f"ClassifyFailureDecisionReport.last_error 必填非空 str, "
                f"实际 {type(self.last_error).__name__}={self.last_error!r}"
            )
        if (
            not isinstance(self.consecutive_classify_failures, int)
            or isinstance(self.consecutive_classify_failures, bool)
            or self.consecutive_classify_failures < 1
        ):
            raise ValueError(
                f"ClassifyFailureDecisionReport.consecutive_classify_failures "
                f"必填原生 int >= 1, 实际 "
                f"{type(self.consecutive_classify_failures).__name__}="
                f"{self.consecutive_classify_failures!r}"
            )


class EmailClassifierAdapter:
    """D4.6 业务层接入适配器 — EmailClassifier 接入 PolicyEngine 4 件套.

    复用 SyncPolicyAdapter 4 依赖可注入范本:
      - event_store: 落 PolicyDecisionEvent(D4.3)
      - engine: PolicyEngine(D4.4 决策引擎)
      - heartbeat: Heartbeat(LLM 探活)
      - board: LaneBoard(分类任务看板)

    用法(生产):
        from my_ai_employee.ai.classifier import EmailClassifier
        from my_ai_employee.policy import (
            EmailClassifierAdapter, EventStore, PolicyEngine,
        )

        classifier = EmailClassifier()
        adapter = EmailClassifierAdapter(
            source="qq",
            event_store=event_store,
            engine=PolicyEngine(),
        )
        result = classifier.classify(
            subject="[紧急] 客户投诉",
            sender="client@example.com",
            body_excerpt="...",
        )
        report = adapter.classify_and_emit(
            email_id=123,
            classification=result,
        )

    设计要点(沿用 D4.5 P0 + v1.0.1):
      - EmailClassifier 在外层调(classify 决策独立可测)
      - 4 依赖可注入(None = 跳过该环节, 测试用)
      - lane_entry_id 命名 "classify:<source>:<run_id>"(与 sync: 区分)
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

    def build_lane_entry_id(self, run_id: str) -> str:
        """生成 LaneBoard entry_id: 'classify:<source>:<run_id>'."""
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"run_id 必填非空 str, 实际 {type(run_id).__name__}={run_id!r}")
        return f"classify:{self._source}:{run_id}"

    def record_to_lane(
        self,
        *,
        run_id: str,
        status: LaneStatus,
        objective: str = "",
        owner: str = "email_classifier",
    ) -> LaneEntry:
        """LaneBoard 记录: add (ACTIVE/BLOCKED) 或 update (FINISHED).

        与 SyncPolicyAdapter.record_to_lane 同逻辑(D4.5 范本复用)。
        """
        entry_id = self.build_lane_entry_id(run_id)
        if not objective:
            objective = f"Email classify source={self._source}"
        existing: LaneEntry | None = None
        try:
            existing = self._board.get(entry_id)
        except Exception:
            existing = None
        if existing is None:
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
        return self._board.update(entry_id, status=status, owner=owner)

    def tick_heartbeat(
        self,
        *,
        transport_alive: bool = True,
        now_ms: int | None = None,
    ) -> Liveness:
        """刷新心跳(LLM 路由成功 → alive=True)."""
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )
        self._heartbeat.update(transport_alive=transport_alive, now_ms=now_ms)
        return self._heartbeat.evaluate(now_ms=now_ms)

    def classify_and_emit(
        self,
        *,
        email_id: int,
        classification: Any,  # ClassificationResult(避免循环 import,用 duck type)
        transport_alive: bool = True,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> ClassifyDecisionReport:
        """成功分类主入口: 评估分类结果 + 落 1 条 PolicyDecisionEvent.

        D4.6 v1.0.2 P1-1 修复: 旧版 last_classify_failed / consecutive_classify_failures
        都可传,实际仍可能触发 `retry_available + merge_required`(状态耦合)。
        新版强制: 成功路径 = last_classify_failed=False + cf=0, 触发 merge_required
        (全部 AC pass) 或 BLOCKED (业务拒绝) — 永不触发 retry / escalate。
        失败请走 record_classify_failure_and_emit(last_error + cf 必填)。

        Args:
            email_id: 邮件主键(emails.id)
            classification: EmailClassifier.classify() 的返回(duck type, 严判字段)
            transport_alive: LLM 路由本次是否可用(D4.6 v1.0.1 P1-2 新增)
              - 默认 True(本次成功调用 router 必为 True,失败由 caller 在 try/except
                外层决定)
              - 与 business_accepted 解耦:SPAM/低置信度/慢响应 ≠ LLM 死了
            run_id: LaneBoard entry 唯一 ID(空 = 用 now_ms 字符串)
            now_ms: 注入时间(默认 int(time.time() * 1000))

        Returns:
            ClassifyDecisionReport

        Raises:
            ValueError: 参数 type 错(D4.5 P0 严判 + D4.6 v1.0.2 扩 category 5 类
                + latency_ms >= 0)
            PolicyContractError: build_classify_packet 8 字段不全
            PolicyDecisionError: build_classify_policy_context 类型非法
            EventContractError / EventMetadataError: EventStore.insert 失败

        D4.6 v1.0.2 修复汇总:
          - P1-1: 移除 last_classify_failed / consecutive_classify_failures 参数,
            强制成功路径 = cf=0 → 永不触发 retry / escalate
          - P1-2: 严判 category ∈ 5 类枚举, latency_ms >= 0
          - P1-2(v1.0.1): 拆分 business_accepted(Lane) vs transport_alive(Heartbeat)
          - P2-5(v1.0.1): 严判 classification duck type,拒 bool/str
        """
        import time as _time

        # 严判 email_id(D4.5 P0 严判入口范本)
        if type(email_id) is not int or isinstance(email_id, bool) or email_id < 0:
            raise ValueError(
                f"email_id 必须是原生 int >= 0, 实际 {type(email_id).__name__}={email_id!r}"
            )
        # D4.6 v1.0.1 P1-2 严判 transport_alive
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )

        # 严判 classification duck type — D4.6 v1.0.1 P2-5 + v1.0.2 P1-2 修复:
        # - v1.0.1: type() 严判,拒 bool 子类陷阱 + 字符串混入
        # - v1.0.2: 严判 category ∈ 5 类 + latency_ms >= 0
        # D4.6 v1.0.2 第三次复检 P2 修复: 用 _validate_classify_category 公共 helper
        # 统一 ValueError(防止后续用 frozenset / set / dict 等操作时漏走 TypeError 路径)
        if hasattr(classification, "category") and hasattr(classification.category, "value"):
            category_value = classification.category.value
        else:
            raise ValueError(
                f"classification.category.value 缺失, 实际 {type(classification).__name__}"
            )
        # D4.6 v1.0.2 第三次复检 P2 修复: 严判走公共 helper,与 build_classify_packet
        # / build_classify_policy_context 同一严判口径(防止列表/字典等不可哈希类型
        # 通过 frozenset `in` 后又漏严判)
        _validate_classify_category(category_value)
        if not isinstance(classification.confidence, (int, float)) or isinstance(
            classification.confidence, bool
        ):
            raise ValueError(
                f"classification.confidence 必须是数字(非 bool/str), 实际 "
                f"{type(classification.confidence).__name__}={classification.confidence!r}"
            )
        confidence = float(classification.confidence)
        if not math.isfinite(confidence):
            raise ValueError(
                f"classification.confidence 必须是有限数字(非 NaN/Inf), 实际 {confidence}"
            )
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence 必须在 0-1 之间, 实际 {confidence}")
        if not isinstance(classification.latency_ms, int) or isinstance(
            classification.latency_ms, bool
        ):
            raise ValueError(
                f"classification.latency_ms 必须是原生 int(非 bool), 实际 "
                f"{type(classification.latency_ms).__name__}={classification.latency_ms!r}"
            )
        # D4.6 v1.0.2 P1-2: 严判 latency_ms >= 0(防止外部 time.time() 异常 / 时钟回退)
        if classification.latency_ms < 0:
            raise ValueError(
                f"classification.latency_ms 必须 >= 0, 实际 {classification.latency_ms}"
            )
        latency_ms = classification.latency_ms
        if not isinstance(classification.model_full_id, str) or not classification.model_full_id:
            raise ValueError(
                f"classification.model_full_id 必填非空 str, 实际 "
                f"{type(classification.model_full_id).__name__}"
            )
        model_full_id = classification.model_full_id

        # 1) 构造 TaskPacket
        packet = build_classify_packet(
            email_id=email_id,
            source=self._source,
            category_value=category_value,
            model_full_id=model_full_id,
            confidence=confidence,
        )

        # 2) 构造 context (12 字段严判) — D4.6 v1.0.2 P1-1: 成功路径强制 cf=0
        context = build_classify_policy_context(
            category_value=category_value,
            confidence=confidence,
            latency_ms=latency_ms,
            last_classify_failed=False,  # P1-1 强制: 成功路径永不失败
            consecutive_classify_failures=0,  # P1-1 强制: 成功路径计数归零
            now_ms=now_ms if now_ms is not None else int(_time.time() * 1000),
        )

        # 3) run_id + lane_entry_id(D4.5 v1.0.1 透传范本)
        rid = run_id or str(int(_time.time() * 1000))
        lane_entry_id = self.build_lane_entry_id(rid)

        # 4) PolicyEngine.evaluate(落事件 + 透传 lane_entry_id / run_id + 业务 payload)
        #    D4.6 新增: 业务字段(category / confidence / model_full_id / email_id / source)
        #    透传到 event_metadata 顶层,便于 `mmx policy history` 跨业务类型查询
        extra_business_payload = {
            "category": category_value,
            "confidence": confidence,
            "model_full_id": model_full_id,
            "email_id": email_id,
            "source": self._source,
        }
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=self._event_store,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload=extra_business_payload,
        )

        # 5) LaneBoard 记录(单一真相源 = acceptance_results,D4.5 P0-3 范本)
        #    D4.6 v1.0.1 P1-2 修复: Lane 用 business_accepted,不耦合 transport
        ac_results = compute_classification_acceptance(
            category_value=category_value,
            confidence=confidence,
            latency_ms=latency_ms,
        )
        business_accepted = bool(all(ac_results))
        self.record_to_lane(
            run_id=rid,
            status=LaneStatus.FINISHED if business_accepted else LaneStatus.BLOCKED,
        )

        # 6) Heartbeat — D4.6 v1.0.1 P1-2 修复: 用 transport_alive,不耦合 business
        #    SPAM / 低置信度 / 慢响应 = business 拒绝,不是 LLM 死了
        liveness = self.tick_heartbeat(transport_alive=transport_alive, now_ms=now_ms)

        return ClassifyDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            category=category_value,
            confidence=confidence,
        )

    def record_classify_failure_and_emit(
        self,
        *,
        email_id: int,
        last_error: Any,  # str | LLMError | ClassifierResponseError | Exception
        consecutive_classify_failures: int,
        transport_alive: bool = True,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> ClassifyFailureDecisionReport:
        """失败分类入口: 分类失败,记录 last_error,触发 retry / escalate.

        D4.6 v1.0.2 P1-1 新增: 与 classify_and_emit 互斥, 防止状态耦合.
        旧版 classify_and_emit 接受 `last_classify_failed=True + 成功 classification`,
        实际仍会同时触发 `retry_available + merge_required`(P1-1 bug)。
        新版强制分离: 成功入口永不失败, 失败入口永不合并(AC 全 False → BLOCKED)。

        Args:
            email_id: 邮件主键(emails.id)
            last_error: 失败原因(任意类型,内部 str() 化喂 packet)
            consecutive_classify_failures: 连续分类失败次数(必填 >= 1)
              - < 3: 触发 RETRY_AVAILABLE
              - >= 3: 触发 ESCALATE_REQUIRED
            transport_alive: LLM 路由本次是否可用(失败不一定意味 LLM 死了,
              如 ClassifierResponseError 响应脏但 LLM 仍可达)
            run_id: LaneBoard entry 唯一 ID(空 = 用 now_ms 字符串)
            now_ms: 注入时间(默认 int(time.time() * 1000))

        Returns:
            ClassifyFailureDecisionReport(D4.6 v1.0.2 二次复检 P2-2 独立数据类,
                字段自洽: failed=True + last_error + consecutive_classify_failures,
                无 category / confidence)

        Raises:
            ValueError: 参数 type 错 / consecutive_classify_failures < 1
            PolicyContractError: build_classify_failure_packet 字段不全
            PolicyDecisionError: build_classify_policy_context 类型非法
            EventContractError / EventMetadataError: EventStore.insert 失败
        """
        import time as _time

        # 严判 email_id
        if type(email_id) is not int or isinstance(email_id, bool) or email_id < 0:
            raise ValueError(
                f"email_id 必须是原生 int >= 0, 实际 {type(email_id).__name__}={email_id!r}"
            )
        # 严判 consecutive_classify_failures(失败入口必填 >= 1)
        if (
            type(consecutive_classify_failures) is not int
            or isinstance(consecutive_classify_failures, bool)
            or consecutive_classify_failures < 1
        ):
            raise ValueError(
                f"consecutive_classify_failures 必须是原生 int >= 1, 实际 "
                f"{type(consecutive_classify_failures).__name__}="
                f"{consecutive_classify_failures!r}"
            )
        # 严判 transport_alive
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )
        # 严判 last_error(转 str 后非空)
        if last_error is None:
            raise ValueError("last_error 不能为 None, 失败必须带原因")
        last_error_str = str(last_error)
        if not last_error_str:
            raise ValueError(
                f"last_error 必填非空 (str() 后非空), 实际 {type(last_error).__name__}"
            )

        # 1) 构造 TaskPacket(失败专用 factory)
        packet = build_classify_failure_packet(
            email_id=email_id,
            source=self._source,
            last_error_str=last_error_str,
            consecutive_classify_failures=consecutive_classify_failures,
            model_full_id="unknown",  # 失败时无模型可用,标记 unknown
        )

        # 2) 构造 context — D4.6 v1.0.2 P1-1: 失败入口隐式 last_classify_failed=True
        #    用 synthetic category/conf/latency 让 AC[0] 自动 False → merge 不触发
        context = build_classify_policy_context(
            category_value="URGENT",  # synthetic, 仅用于 context 必填字段
            confidence=0.0,  # synthetic, AC[0] = (0.0 >= 0.7) = False → 不 merge
            latency_ms=0,  # synthetic, 失败无延迟
            last_classify_failed=True,  # P1-1 强制: 失败入口隐式 True
            consecutive_classify_failures=consecutive_classify_failures,
            now_ms=now_ms if now_ms is not None else int(_time.time() * 1000),
        )

        # 3) run_id + lane_entry_id
        rid = run_id or str(int(_time.time() * 1000))
        lane_entry_id = self.build_lane_entry_id(rid)

        # 4) PolicyEngine.evaluate — 业务 payload 标记为失败
        extra_business_payload = {
            "email_id": email_id,
            "source": self._source,
            "last_error": last_error_str[:200],  # 截断到 200 字符
            "consecutive_classify_failures": consecutive_classify_failures,
            "failed": True,  # 业务侧查询可用
        }
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=self._event_store,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload=extra_business_payload,
        )

        # 5) LaneBoard: 失败入口强制 BLOCKED(synthetic conf=0 → AC[0] False)
        self.record_to_lane(
            run_id=rid,
            status=LaneStatus.BLOCKED,
        )

        # 6) Heartbeat — 用 transport_alive(失败可能是响应脏,不是 LLM 死了)
        liveness = self.tick_heartbeat(transport_alive=transport_alive, now_ms=now_ms)

        return ClassifyFailureDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            failed=True,  # 必为 True(类型层面与成功报告区分)
            last_error=last_error_str[:200],  # 截断到 200 字符
            consecutive_classify_failures=consecutive_classify_failures,
        )


# ===== 模块导出 =====


__all__ = [
    "SyncPolicyAdapter",
    "SyncDecisionReport",
    "build_imap_sync_packet",
    "build_sync_policy_context",
    "compute_acceptance_results",
    "EmailClassifierAdapter",
    "ClassifyDecisionReport",
    "ClassifyFailureDecisionReport",
    "build_classify_packet",
    "build_classify_failure_packet",
    "build_classify_policy_context",
    "compute_classification_acceptance",
]
