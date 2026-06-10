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

D4.7.3 业务层接入(D4.7 草稿生成器下游, 6/10 起始):
  - EmailDrafterAdapter 沿用 D4.6 EmailClassifierAdapter 三入口架构:
      - draft_and_emit(成功) + record_draft_business_blocked_and_emit(业务阻断)
        + record_draft_failure_and_emit(技术失败, D4.7.3 v1.0.2 P1-1 拆分)
      - lane_entry_id 命名 "draft:<source>:<run_id>"(与 sync / classify 区分)
      - 4 依赖可注入(event_store / engine / heartbeat / board, None = 跳过)
  - 业务 payload 透传 spam_reply_authorized + spam_reply_intent 双字段
    (D4.7.2 v1.0.8 强一致契约就绪, Adapter 必透传以 audit 信任)
  - 三类报告独立数据类: DraftDecisionReport(成功) + DraftBlockedDecisionReport
    (业务阻断, kind="business_blocked") + DraftFailureDecisionReport(技术失败)
    (沿用 D4.6 v1.0.2 二次复检 P2-2 范本, failed: Literal[True] 类型层面固化)
  - 双层防御: 入口段严判 + 数据类 __post_init__ 兜底
    (D4.7.2 v1.0.8 P1-2 范本)
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
    from my_ai_employee.ai.drafter import (
        DraftResult,
        DraftSpamReplyIntent,
        DraftTone,
    )
    from my_ai_employee.core.sync import SyncResult

from my_ai_employee.ai.drafter import (
    DraftSpamReplyIntent as _DraftSpamReplyIntent,  # noqa: E402  # D4.7.3 运行时导入(数据类 __post_init__ 严判要看到此名)
)
from my_ai_employee.ai.drafter import (
    _validate_draft_body,  # noqa: E402  # D4.7.3 v1.0.3 P1-1 复用契约 helper, 严判 body 长度+strip
    _validate_draft_subject,  # noqa: E402  # D4.7.3 v1.0.3 P1-1 复用契约 helper, 严判 subject 1-200+strip
)

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
        # D4.7.3 v1.0.3 P2-2 修复: 用 `is None` 范式而非 `or`, 保留合法 falsey 替身
        # (测试替身 / 自定义实例如果 __bool__() 返回 False 会被 or 错误替换为默认实例)
        self._engine = engine if engine is not None else PolicyEngine()
        self._heartbeat = (
            heartbeat if heartbeat is not None else Heartbeat(idle_threshold_ms=30_000)
        )
        self._board = board if board is not None else LaneBoard(idle_threshold_ms=60_000)

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
        # D4.7.3 v1.0.3 P2-2 修复: 用 `is None` 范式而非 `or`, 保留合法 falsey 替身
        # (测试替身 / 自定义实例如果 __bool__() 返回 False 会被 or 错误替换为默认实例)
        self._engine = engine if engine is not None else PolicyEngine()
        self._heartbeat = (
            heartbeat if heartbeat is not None else Heartbeat(idle_threshold_ms=30_000)
        )
        self._board = board if board is not None else LaneBoard(idle_threshold_ms=60_000)

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


# =====================================================================
# D4.7.3 — EmailDrafterAdapter(草稿生成器业务层接入)
# =====================================================================
#
# 设计要点(沿用 D4.6 EmailClassifierAdapter 三入口架构 + D4.5 SyncPolicyAdapter
# 4 依赖可注入范本):
#   - 4 依赖: event_store / engine / heartbeat / board(均可选, None = 跳过)
#   - 三入口: draft_and_emit(成功) + record_draft_business_blocked_and_emit(业务阻断)
#     + record_draft_failure_and_emit(技术失败, D4.7.3 v1.0.2 P1-1 拆分)
#   - lane_entry_id 命名: "draft:<source>:<run_id>"(与 sync / classify 区分)
#   - 3 条 AC: tone ∈ 3 类 + latency_ms < 5000 + 10 <= body_length <= 8000
#     (D4.7.3 v1.0.4 P1-2 契约 1, build_draft_packet 严判 10-8000 区间)
#   - 业务 payload 透传: spam_reply_authorized + spam_reply_intent 双字段
#     (D4.7.2 v1.0.8 强一致契约就绪, Adapter 必透传以 audit 信任)
#   - 失败入口产出 DraftFailureDecisionReport(技术失败: failed=True + last_error + cf)
#     + 业务阻断入口产出 DraftBlockedDecisionReport(blocked=True + kind=business_blocked)
#     (D4.7.3 v1.0.2 P1-1 拆分 + v1.0.3 P2-1 字段名级别硬区分)

# ===== 公共严判 helper(D4.7.3, 与 D4.6 v1.0.2 二次复检 P1 范本对齐)=====
# 设计: tone / body_length / latency_ms 三类业务字段的严判下沉到 helper 层,
# 防止 Adapter 重构后绕过严判(D3.3.3 教训:窄化异常范围 + 公共 API 必须自防御)。
# 3 个 helper 都是纯函数 + raise ValueError,可在 factory / public 入口复用。

_VALID_DRAFT_TONES: frozenset[str] = frozenset({"FORMAL", "FRIENDLY", "CONCISE"})

# 草稿生成业务最低 body 长度(草稿要 < 10 字符 = 模型空响应或截断, 应阻断)
_DRAFT_MIN_BODY_CHARS: int = 10
# D4.7.3 v1.0.2 P2-3 新增: 草稿 body 上限, 与 _validate_draft_body 锁定契约 10-8000 对齐
# (v1.0.1 仅严判下限, 上限默认 2000, 但实际 _validate_draft_body 8000, 漏严判导致
# 8001 字符 body 仍通过 draft_and_emit 触发 merge_required)
_DRAFT_MAX_BODY_CHARS: int = 8000
# 草稿生成业务最高 latency 阈值(与 D4.6 一致, 5 秒)
_DRAFT_MAX_LATENCY_MS: int = 5000


def _validate_draft_tone(tone_value: Any) -> str:
    """严判草稿 tone ∈ 3 类枚举(D4.7.3 公共 helper).

    接受 DraftTone 枚举 / 字符串, 统一返回字符串(便于后续 frozenset 校验)。

    D4.7.3 沿用 D4.6 _validate_classify_category 范本(异常统一 ValueError,
    不抛 TypeError, 防止列表/字典等不可哈希类型绕过 `in` 操作)。
    """
    if tone_value is None:
        raise ValueError("tone 不能为 None")
    if isinstance(tone_value, bool):
        raise ValueError("tone 不能是 bool, 实际 True/False")
    # DraftTone 是 StrEnum, isinstance(x, str) 为 True
    if not isinstance(tone_value, str):
        raise ValueError(
            f"tone 必须是 DraftTone 枚举或 str, 实际 {type(tone_value).__name__}={tone_value!r}"
        )
    if tone_value not in _VALID_DRAFT_TONES:
        raise ValueError(f"tone 必须在 {sorted(_VALID_DRAFT_TONES)} 之一, 实际 {tone_value!r}")
    return tone_value


def _validate_draft_body_length(body_length: Any) -> int:
    """严判草稿 body 长度: int >= 0.

    D4.7.3 范本: 与 D4.6 _validate_classify_latency_ms 对齐, int(非 bool) + >= 0。

    D4.7.3 v1.0.4 P1-2 修复: 新增 _validate_draft_body_length_range(10-8000 严格),
    build_draft_packet 改用 range 严判(契约 1), _validate_draft_body_length
    仅作为低层 type 校验保留给 compute_draft_acceptance 等场景(那里只校验下界)。
    """
    if type(body_length) is bool or not isinstance(body_length, int):
        raise ValueError(
            f"body_length 必须是 int(非 bool), 实际 {type(body_length).__name__}={body_length!r}"
        )
    if body_length < 0:
        raise ValueError(f"body_length 必须 >= 0, 实际 {body_length}")
    return body_length


def _validate_draft_body_length_range(body_length: Any) -> int:
    """D4.7.3 v1.0.4 P1-2 新增: 严判草稿 body 长度 10-8000 区间(契约 1).

    复用 drafter 模块的 EmailDrafter.MIN_DRAFT_BODY_CHARS / MAX_DRAFT_BODY_CHARS 常量,
    契约升级(如 10-3000 → 10-5000)只改 drafter.py 一处, Adapter 自动跟随。
    与 _validate_draft_body 的 10-8000 边界对齐, 但本函数只校验长度不校验语义(strip())。

    D4.7.3 v1.0.3 P1-1 范本: 复用契约 helper, 不要自造严判逻辑。

    Raises:
        ValueError: type 错 / 长度越界
    """
    _validate_draft_body_length(body_length)
    from my_ai_employee.ai.drafter import EmailDrafter

    if body_length < EmailDrafter.MIN_DRAFT_BODY_CHARS:
        raise ValueError(
            f"body_length 必须 >= {EmailDrafter.MIN_DRAFT_BODY_CHARS} "
            f"(D4.7.3 v1.0.4 P1-2 契约 1), 实际 {body_length}"
        )
    if body_length > EmailDrafter.MAX_DRAFT_BODY_CHARS:
        raise ValueError(
            f"body_length 必须 <= {EmailDrafter.MAX_DRAFT_BODY_CHARS} "
            f"(D4.7.3 v1.0.4 P1-2 契约 1), 实际 {body_length}"
        )
    return int(body_length)


def _validate_draft_latency_ms(latency_ms: Any) -> int:
    """严判草稿生成延迟: int >= 0(沿用 D4.6 范本)."""
    if type(latency_ms) is bool or not isinstance(latency_ms, int):
        raise ValueError(
            f"latency_ms 必须是 int(非 bool), 实际 {type(latency_ms).__name__}={latency_ms!r}"
        )
    if latency_ms < 0:
        raise ValueError(f"latency_ms 必须 >= 0, 实际 {latency_ms}")
    return latency_ms


# ===== Helper 函数(D4.7.3 工厂层,与 D4.6 build_*_packet 范本对齐)=====


def compute_draft_acceptance(
    *,
    tone: str | DraftTone,
    latency_ms: int,
    body_length: int,
) -> list[bool]:
    """由 DraftResult 计算 3 条 acceptance_criteria 是否 pass.

    3 条 AC:
      [0] tone ∈ 3 类枚举(必含 FORMAL/FRIENDLY/CONCISE, 业务可用)
      [1] 10 <= body_length <= 8000(D4.7.3 v1.0.4 P1-2 契约 1, 防 0/9/8001 绕过)
      [2] latency_ms < 5000(5s 内出结果)

    D4.7.3 范本: 与 D4.6 compute_classification_acceptance 一致,
    入口 3 类严判 + 返回 list[bool](PolicyEngine 严判 type() is bool)。

    Returns:
        list[bool](PolicyEngine 严判 type() is bool, D4.4 P1 + D4.5 P0 教训应用)

    Raises:
        ValueError: tone 不在 3 类 / body_length 负数 / latency_ms 负数
    """
    _validate_draft_tone(tone)
    _validate_draft_body_length(body_length)
    _validate_draft_latency_ms(latency_ms)
    return [
        bool(tone in _VALID_DRAFT_TONES),
        bool(_DRAFT_MIN_BODY_CHARS <= body_length <= _DRAFT_MAX_BODY_CHARS),
        bool(latency_ms < _DRAFT_MAX_LATENCY_MS),
    ]


def build_draft_packet(
    *,
    email_id: int,
    source: str,
    tone: str | DraftTone,
    model_full_id: str,
    body_length: int,
) -> TaskPacket:
    """D4.7.3 业务模板: 草稿生成任务 → TaskPacket (8 必含字段).

    与 D4.6 build_classify_packet 范本对齐, 仅业务字段不同:
      - acceptance_criteria: [tone, body_length, latency<5000ms]
      - objective: "email_draft:source=...:id=..."

    Args:
        email_id: 邮件主键(emails.id)
        source: 邮件来源 "qq" / "outlook" / "gmail"
        tone: 3 类枚举值 (FORMAL / FRIENDLY / CONCISE)
        model_full_id: 实际调用的 provider/model (如 "deepseek/deepseek-chat")
        body_length: 草稿正文长度(字符数)

    Returns:
        TaskPacket(8 字段, 与 SyncPolicyAdapter 范本对齐)
    """
    if type(email_id) is bool or not isinstance(email_id, int):
        raise ValueError(
            f"email_id 必须是 int(非 bool), 实际 {type(email_id).__name__}={email_id!r}"
        )
    if email_id < 0:
        raise ValueError(f"email_id 必须 >= 0, 实际 {email_id}")
    if type(source) is not str or not source.strip():
        # D4.7.3 v1.0.4 P2-4 修复: strip() 语义非空校验(防纯空白字符串通过)
        raise ValueError(
            f"source 必填非空白 str(strip() 非空), 实际 {type(source).__name__}={source!r}"
        )
    # D4.7.3 范本: tone 严判下沉到 _validate_draft_tone 公共 helper
    _validate_draft_tone(tone)
    if type(model_full_id) is not str or not model_full_id.strip():
        # D4.7.3 v1.0.4 P2-4 修复: strip() 语义非空校验(防纯空白字符串通过)
        raise ValueError(
            f"model_full_id 必填非空白 str(strip() 非空), 实际 "
            f"{type(model_full_id).__name__}={model_full_id!r}"
        )
    # D4.7.3 v1.0.4 P1-2 修复: body_length 严判 10-8000 区间(契约 1, 防 0/9/8001 绕过)
    _validate_draft_body_length_range(body_length)

    return TaskPacket(
        objective=f"email_draft:source={source}:id={email_id}",
        scope=["ai/drafter.py", "core/models.py"],
        resources=["db:sqlcipher", "llm:router"],
        # D4.7.3 v1.0.3 P2-3 修复: acceptance_criteria 固定契约描述 10-8000,
        # 不再写成 `body_length>={body_length}` 这种"自证式条件"(会变成
        # `body_length>=8001` 等荒唐描述, audit 把非法长度描述成验收标准)
        acceptance_criteria=[
            f"tone={tone}",
            "10<=body_length<=8000",
            "latency<5000ms",
        ],
        model=model_full_id,
        provider=model_full_id.split("/", 1)[0] if "/" in model_full_id else "unknown",
        permission_profile=PermissionProfile.READ_ONLY.value,  # D4.7.3: 草稿生成是调 LLM, READ_ONLY
        recovery_policy=RecoveryPolicy.RETRY_ON_TRANSIENT.value,
    )


def build_draft_blocked_packet(
    *,
    email_id: int,
    source: str,
    tone: str | DraftTone,
    reason: str,
    original_email_category: str,
) -> TaskPacket:
    """D4.7.3 业务模板: 阻断草稿任务 → TaskPacket (8 必含字段).

    与 D4.6 build_classify_failure_packet 范本对齐, 失败入口专用 factory:
      - objective: "email_draft_blocked:..." 前缀(便于 lane 串联)
      - acceptance_criteria: [tone, reason, original_email_category]
      - reason 锁定白名单(当前仅 spam_business_blocked, 与 _BLOCKED_REASON_VALUES 一致)
      - original_email_category 必 ∈ 5 类(URGENT/TODO/FYI/SPAM/PERSONAL)

    D3.3.3 教训应用: 严判入口, 拒 type-coerce。
    """
    if type(email_id) is bool or not isinstance(email_id, int):
        raise ValueError(
            f"email_id 必须是 int(非 bool), 实际 {type(email_id).__name__}={email_id!r}"
        )
    if email_id < 0:
        raise ValueError(f"email_id 必须 >= 0, 实际 {email_id}")
    if type(source) is not str or not source.strip():
        # D4.7.3 v1.0.4 P2-4 修复: strip() 语义非空校验
        raise ValueError(
            f"source 必填非空白 str(strip() 非空), 实际 {type(source).__name__}={source!r}"
        )
    _validate_draft_tone(tone)
    # reason 锁定白名单(防止"other" 等构造不一致状态, D4.7.2 v1.0.5 P2 范本)
    if type(reason) is not str or not reason:
        raise ValueError(f"reason 必填非空 str, 实际 {type(reason).__name__}")
    if reason not in {"spam_business_blocked"}:
        raise ValueError(f"reason 必须在 {sorted({'spam_business_blocked'})} 之一, 实际 {reason!r}")
    # original_email_category 严判 ∈ 5 类(与 D4.6 _validate_classify_category 对齐)
    if type(original_email_category) is not str or not original_email_category:
        raise ValueError(
            f"original_email_category 必填非空 str, 实际 {type(original_email_category).__name__}"
        )
    _validate_classify_category(original_email_category)
    # D4.7.3 v1.0.1 P2-2 修复: reason 与 original_email_category 强一致
    # 当前唯一阻断原因是 spam_business_blocked → 必配 SPAM 分类
    # 防止 URGENT/TODO/FYI/PERSONAL + spam_business_blocked 矛盾状态
    # (业务阻断原因只能由 SPAM 邮件触发, 其他分类不应走到该 reason)
    if original_email_category != "SPAM":
        raise ValueError(
            f"reason={reason!r} 时 original_email_category 必为 'SPAM'(业务阻断原因只能由 "
            f"SPAM 邮件触发), 实际 {original_email_category!r}"
        )

    return TaskPacket(
        objective=f"email_draft_blocked:source={source}:id={email_id}",
        scope=["ai/drafter.py", "core/models.py"],
        resources=["db:sqlcipher", "llm:router"],
        acceptance_criteria=[
            f"tone={tone}",
            f"reason={reason}",
            f"original_email_category={original_email_category}",
        ],
        model="unknown",  # 阻断路径无 LLM 调用, 标记 unknown(与 D4.6 范本对齐)
        provider="unknown",
        permission_profile=PermissionProfile.READ_ONLY.value,  # D4.7.3: 阻断路径不调 LLM, READ_ONLY
        recovery_policy=RecoveryPolicy.RETRY_ON_TRANSIENT.value,
    )


def build_draft_failure_packet(
    *,
    email_id: int,
    source: str,
    last_error_str: str,
    consecutive_draft_failures: int,
    model_full_id: str = "unknown",
) -> TaskPacket:
    """D4.7.3 v1.0.2 P1-1 新增: 技术失败专用 TaskPacket(独立类型, 不复用阻断 factory).

    与 build_draft_blocked_packet 差异(关键):
      - objective: "email_draft_failed:..." 前缀(便于 lane 串联)
      - acceptance_criteria: 3 条技术失败相关(无 original_email_category 业务字段,
        因技术失败与邮件分类无关)
      - last_error_str 截断到 100 字符(防 prompt 撑爆)
      - consecutive_draft_failures 必填 >= 1(确为失败, 不是首次)

    D4.6 v1.0.2-first 范本: 独立失败 packet factory + Literal[True] failed 字段。

    Raises:
        ValueError: 参数 type 错 / consecutive_draft_failures < 1
    """
    if type(email_id) is bool or not isinstance(email_id, int) or email_id < 0:
        raise ValueError(
            f"email_id 必须是原生 int >= 0, 实际 {type(email_id).__name__}={email_id!r}"
        )
    if type(source) is not str or not source.strip():
        # D4.7.3 v1.0.4 P2-4 修复: strip() 语义非空校验
        raise ValueError(
            f"source 必填非空白 str(strip() 非空), 实际 {type(source).__name__}={source!r}"
        )
    if type(last_error_str) is not str or not last_error_str.strip():
        # D4.7.3 v1.0.4 P2-4 修复: strip() 语义非空校验(技术失败报告也接受空白错误信息)
        raise ValueError(
            f"last_error_str 必填非空白 str(strip() 非空), 实际 "
            f"{type(last_error_str).__name__}={last_error_str!r}"
        )
    if (
        type(consecutive_draft_failures) is bool
        or not isinstance(consecutive_draft_failures, int)
        or consecutive_draft_failures < 1
    ):
        raise ValueError(
            f"consecutive_draft_failures 必须是原生 int >= 1, 实际 "
            f"{type(consecutive_draft_failures).__name__}={consecutive_draft_failures!r}"
        )
    if type(model_full_id) is not str or not model_full_id.strip():
        # D4.7.3 v1.0.4 P2-4 修复: strip() 语义非空校验
        raise ValueError(
            f"model_full_id 必填非空白 str(strip() 非空), 实际 "
            f"{type(model_full_id).__name__}={model_full_id!r}"
        )

    return TaskPacket(
        objective=f"email_draft_failed:source={source}:id={email_id}",
        scope=["ai/drafter.py", "core/models.py"],
        resources=["db:sqlcipher", "llm:router"],
        acceptance_criteria=[
            f"last_error={last_error_str[:100]}",
            f"consecutive_draft_failures={consecutive_draft_failures}",
            "retry_policy=retry_on_transient",
        ],
        model=model_full_id,
        provider=model_full_id.split("/", 1)[0] if "/" in model_full_id else "unknown",
        permission_profile=PermissionProfile.READ_ONLY.value,
        recovery_policy=RecoveryPolicy.RETRY_ON_TRANSIENT.value,
    )


def build_draft_policy_context(
    *,
    tone: str | DraftTone,
    latency_ms: int,
    body_length: int,
    last_draft_failed: bool = False,
    consecutive_draft_failures: int = 0,
    branch_stale: bool = False,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """DraftResult → PolicyEngine context (12 字段严判).

    字段映射(对照 D4.6 build_classify_policy_context 范本):
      - last_error_recoverable: last_draft_failed AND 0 < consecutive_draft_failures < 3
      - current_attempts: consecutive_draft_failures(透传 cf, D4.7.3 v1.0.4 P2-3 修复;
        草稿不重试由 caller 决定, 但 current_attempts 必须反映实际 cf 以 audit 信任)
      - max_attempts: 3
      - branch_stale: 由 caller 决定
      - last_heartbeat_ms / stale_threshold_ms / now_ms: 默认 0
      - action_sensitive: False(草稿是 READ_ONLY + 待人工审)
      - has_approval_token: True(草稿无需审批, 仅写入 drafts 表)
      - approval_token_id: ""
      - acceptance_results: [tone∈3 类, 10<=body_length<=8000, latency<5000]
        (D4.7.3 v1.0.4 P1-2 契约 1 固定, 与 build_draft_packet / _validate_draft_body_length_range
        严判 1:1 对齐)
      - policy_eval_failed: last_draft_failed AND consecutive_draft_failures >= 3

    ⚠️ 严判入口(D4.5 P0 教训应用 + D4.7.3 范本):
      - last_draft_failed: type() is bool(caller 显式告知, 与 D4.6 last_classify_failed 对齐)
      - consecutive_draft_failures: type() is int >= 0(排除 bool 子类)
      - branch_stale: type() is bool
      - now_ms: type() is int 或 None

    D4.7.3 范本: 与 D4.6 build_classify_policy_context 二次复检 P1 对齐,
    业务字段(tone / body_length / latency_ms)走严判 helper, 任何 caller 都受保护。
    """
    import time

    # D4.7.3 P1 修复: 业务字段走严判 helper(下沉到 helper 层, 任何 caller 都受保护)
    _validate_draft_tone(tone)
    _validate_draft_latency_ms(latency_ms)
    _validate_draft_body_length(body_length)

    # 严判入口(D4.5 P0 修复 1 + D4.6 v1.0.1 P1-3 范本)
    if type(last_draft_failed) is not bool:
        raise ValueError(
            f"last_draft_failed 必须是原生 bool, 实际 "
            f"{type(last_draft_failed).__name__}={last_draft_failed!r}"
        )
    if (
        type(consecutive_draft_failures) is bool
        or not isinstance(consecutive_draft_failures, int)
        or consecutive_draft_failures < 0
    ):
        raise ValueError(
            f"consecutive_draft_failures 必须是原生 int >= 0, 实际 "
            f"{type(consecutive_draft_failures).__name__}={consecutive_draft_failures!r}"
        )
    if type(branch_stale) is not bool:
        raise ValueError(
            f"branch_stale 必须是原生 bool, 实际 {type(branch_stale).__name__}={branch_stale!r}"
        )
    if now_ms is not None and type(now_ms) is not int:
        # D4.7.3 v1.0.1 P2-4 修复: 严判 type(now_ms) is int(不用 isinstance)
        # 否则 bool 子类(True/False)会被错误接受, 然后 PolicyEngine 内部报错
        raise ValueError(
            f"now_ms 必须是 int 或 None(非 bool), 实际 {type(now_ms).__name__}={now_ms!r}"
        )

    # D4.7.3 v1.0.5 P1-2 修复: last_draft_failed 与 consecutive_draft_failures
    # 双向强一致(防矛盾状态):
    #   - last_draft_failed=True → 必配 consecutive_draft_failures >= 1
    #     (True 意味着"上一次失败", 至少累计 1 次)
    #   - last_draft_failed=False → 必配 consecutive_draft_failures == 0
    #     (False 意味着"上一次未失败", 累计失败必为 0)
    # 与 D4.7.3 v1.0.2 P1-2 双向强一致范本对齐, 防生成错误的 recoverable /
    # policy_eval_failed / current_attempts 状态污染 PolicyEngine 决策。
    if last_draft_failed and consecutive_draft_failures < 1:
        raise ValueError(
            f"last_draft_failed=True 时 consecutive_draft_failures 必须 >= 1 "
            f"(D4.7.3 v1.0.5 P1-2 双向强一致: True → cf >= 1), "
            f"实际 last_draft_failed={last_draft_failed!r} "
            f"consecutive_draft_failures={consecutive_draft_failures!r}"
        )
    if not last_draft_failed and consecutive_draft_failures > 0:
        raise ValueError(
            f"last_draft_failed=False 时 consecutive_draft_failures 必须 == 0 "
            f"(D4.7.3 v1.0.5 P1-2 双向强一致: False → cf == 0), "
            f"实际 last_draft_failed={last_draft_failed!r} "
            f"consecutive_draft_failures={consecutive_draft_failures!r}"
        )

    # D4.7.3 范本: 与 D4.6 v1.0.1 P1-3 范本对齐, 用 last_draft_failed 显式 bool
    recoverable = bool(last_draft_failed and 0 < consecutive_draft_failures < 3)
    policy_eval_failed = bool(last_draft_failed and consecutive_draft_failures >= 3)

    return {
        "last_error_recoverable": recoverable,
        # D4.7.3 v1.0.4 P2-3 修复: current_attempts 用 consecutive_draft_failures
        # (PolicyEngine RetryableFailure 决策需要显示"已重试 cf/3 次",
        # 写死 1 导致 cf=2 时仍显示"已重试 1/3 次"误导 audit)
        "current_attempts": consecutive_draft_failures,
        "max_attempts": 3,
        "branch_stale": branch_stale,
        "last_heartbeat_ms": 0,
        "stale_threshold_ms": 60_000,
        "now_ms": now_ms if now_ms is not None else int(time.time() * 1000),
        "action_sensitive": False,  # 草稿写入 drafts 表, 待人工审
        "has_approval_token": True,
        "approval_token_id": "",
        "acceptance_results": compute_draft_acceptance(
            tone=tone,
            latency_ms=latency_ms,
            body_length=body_length,
        ),
        "policy_eval_failed": policy_eval_failed,
    }


# ===== D4.7.3 报告数据类(强一致 + 入口预校验双层防御)=====


@dataclass(frozen=True)
class DraftDecisionReport:
    """D4.7.3 业务层接入的可观测报告(成功草稿版本).

    与 D4.6 ClassifyDecisionReport 范本对齐:
      - evaluation / event_id / lane_entry_id / liveness
      - 业务侧字段: tone / model_full_id / email_id / latency_ms / body_length

    Attributes:
        evaluation: PolicyEngine.evaluate() 完整结果
        event_id: 落地到 events 表的 PolicyDecisionEvent id
        lane_entry_id: LaneBoard 中本次草稿的 entry_id
        liveness: Heartbeat 评估的 Liveness
        tone: 3 类枚举(DraftTone.value)
        model_full_id: 实际调用的 provider/model
        email_id: 邮件主键
        latency_ms: 草稿生成耗时
        body_length: 草稿正文长度
        spam_reply_authorized: 6/10 v1.0.7 强一致 bool(D4.7.2 P1-1 范本,
          True = SPAM 邮件 + allow_spam_reply=True 显式放行)
        spam_reply_intent: 6/10 v1.0.7 强一致 DraftSpamReplyIntent | None
          (D4.7.2 P1-2 范本: authorized=True → 必枚举; False → 必 None)
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    # 以下字段是 D4.7.3 业务侧关心的(与 ClassifyDecisionReport 差异)
    tone: str  # DraftTone.value, 必填 3 类之一
    model_full_id: str  # 非空
    email_id: int  # >= 0
    latency_ms: int  # >= 0
    body_length: int  # >= 0
    # D4.7.2 v1.0.8 强一致双字段(透传到 events audit)
    spam_reply_authorized: bool = False
    spam_reply_intent: DraftSpamReplyIntent | None = None

    def __post_init__(self) -> None:
        """D4.7.3 字段契约自洽校验(D3.3.3 教训应用).

        - tone 严判 ∈ 3 类
        - model_full_id 非空 str
        - email_id / latency_ms / body_length 严判 int(非 bool) + >= 0
        - spam_reply_authorized 严判 bool(拒 str 真值陷阱)
        - spam_reply_intent 严判 DraftSpamReplyIntent | None(拒 str 真值陷阱)
        - 强一致(spam_reply_authorized=True → spam_reply_intent 必枚举,
          False → 必 None, 与 DraftResult 同款, D4.7.2 v1.0.8 P1-2 范本)
        """
        _validate_draft_tone(self.tone)
        # D4.7.3 v1.0.5 P1-1 修复: model_full_id 严判 strip() 语义非空
        # (v1.0.4 P2-4 在 build_draft_packet 工厂层加了, 但 __post_init__
        # 仍是 `not self.model_full_id` 长度检查, 纯空白字符串绕过)
        if type(self.model_full_id) is not str or not self.model_full_id.strip():
            raise ValueError(
                f"DraftDecisionReport.model_full_id 必填非空白 str(strip() 非空), 实际 "
                f"{type(self.model_full_id).__name__}={self.model_full_id!r}"
            )
        if type(self.email_id) is bool or not isinstance(self.email_id, int) or self.email_id < 0:
            raise ValueError(
                f"DraftDecisionReport.email_id 必须是 int(非 bool) >= 0, 实际 "
                f"{type(self.email_id).__name__}={self.email_id!r}"
            )
        _validate_draft_latency_ms(self.latency_ms)
        # D4.7.3 v1.0.5 P1-1 修复: body_length 严判 10-8000 区间(契约 1)
        # (v1.0.4 P1-2 在 build_draft_packet 工厂层加了, 但 __post_init__
        # 仍用 _validate_draft_body_length 仅校验 >= 0, 0/9/8001 绕过)
        _validate_draft_body_length_range(self.body_length)
        if type(self.spam_reply_authorized) is not bool:
            raise ValueError(
                f"DraftDecisionReport.spam_reply_authorized 必须是 bool, 实际 "
                f"{type(self.spam_reply_authorized).__name__}={self.spam_reply_authorized!r}"
            )
        if self.spam_reply_intent is not None and not isinstance(
            self.spam_reply_intent, _DraftSpamReplyIntent
        ):
            # D4.7.3: 运行时严判 DraftSpamReplyIntent 枚举(运行时导入别名 _DraftSpamReplyIntent)
            raise ValueError(
                f"DraftDecisionReport.spam_reply_intent 必须是 DraftSpamReplyIntent "
                f"枚举或 None, 实际 {type(self.spam_reply_intent).__name__}={self.spam_reply_intent!r}"
            )
        if self.spam_reply_intent is not None and self.spam_reply_intent.value not in {
            "UNSUBSCRIBE",
            "REJECT",
        }:
            raise ValueError(
                f"DraftDecisionReport.spam_reply_intent 必须是 'UNSUBSCRIBE'/'REJECT' 或 None, "
                f"实际 {self.spam_reply_intent!r}"
            )
        # 强一致契约(D4.7.2 v1.0.8 P1-2 范本, 双层防御: 入口段预校验 + 数据类兜底)
        if self.spam_reply_authorized and self.spam_reply_intent is None:
            raise ValueError(
                "DraftDecisionReport.spam_reply_authorized=True 时 spam_reply_intent "
                "必为 DraftSpamReplyIntent 枚举 (D4.7.3 强一致契约, 透传到 audit 必须可信), 实际 None"
            )
        if not self.spam_reply_authorized and self.spam_reply_intent is not None:
            raise ValueError(
                "DraftDecisionReport.spam_reply_authorized=False 时 spam_reply_intent "
                "必为 None (D4.7.3 强一致契约, 防 audit 误读), "
                f"实际 {self.spam_reply_intent!r}"
            )


@dataclass(frozen=True)
class DraftBlockedDecisionReport:
    """D4.7.3 业务层接入的可观测报告(业务阻断版本).

    D4.7.3 v1.0.3 P2-1 真修: 字段名从 `failed=True` 改为 `blocked: Literal[True]`,
    防通用调用方执行 `if report.failed` 误计业务阻断为失败(业务阻断永不计入 cf 累加器)。
    旧 v1.0.1/v1.0.2 漏洞: `failed` 字段名同时被业务阻断(本类)与技术失败(DraftFailureDecisionReport)
    使用,调用方可能错误累加失败次数。
    v1.0.3 真修: DraftBlockedDecisionReport 用 `blocked` 命名空间(业务阻断专属),
    DraftFailureDecisionReport 仍用 `failed` 命名空间(技术失败专属), 字段名级别区分。

    Attributes:
        evaluation: PolicyEngine.evaluate() 完整结果
        event_id: 落地到 events 表的 PolicyDecisionEvent id
        lane_entry_id: LaneBoard 中本次阻断的 entry_id
        liveness: Heartbeat 评估的 Liveness
        blocked: Literal[True](v1.0.3 P2-1 新字段, 类型层面固化业务阻断语义, 替代 v1.0.2 的 failed)
        kind: Literal["business_blocked"](v1.0.2 P2-1 保留, 与 DraftFailureDecisionReport 区分)
        last_error: 阻断原因(必填非空, 截断到 200 字符)
        consecutive_draft_failures: 连续失败次数(>= 0, 业务阻断允许 0)
        tone: 3 类枚举(透传用户请求 tone)
        original_email_category: 触发阻断的邮件分类(5 类之一, 当前唯一阻断 reason 必配 SPAM)
        reason: 阻断原因(机器可读, 如 'spam_business_blocked')
        spam_reply_authorized: 6/10 v1.0.8 强一致 bool
        spam_reply_intent: 6/10 v1.0.8 强一致 DraftSpamReplyIntent | None
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    last_error: str  # 必填非空(>0 字符), 截断到 200 字符
    consecutive_draft_failures: int  # 必填 >= 0(业务阻断允许 0)
    # D4.7.3 业务侧字段(与 DraftDecisionReport 差异)
    tone: str  # DraftTone.value, 必填 3 类之一
    original_email_category: str  # 必填 5 类之一
    reason: str  # 阻断原因, 锁定白名单 "spam_business_blocked"
    # D4.7.2 v1.0.8 强一致双字段
    spam_reply_authorized: bool = False
    spam_reply_intent: DraftSpamReplyIntent | None = None
    # D4.7.3 v1.0.2 P2-1: kind 字段类型层面固化, 调用方可基于 kind 区分业务阻断 vs 技术失败
    # D4.7.3 v1.0.3 P2-1: blocked: Literal[True] 替代 v1.0.2 的 failed: Literal[True]
    # 字段名级别区分业务阻断 vs 技术失败, 防通用 `if report.failed` 误计业务阻断
    # (放在最后两个有默认值, 必须在所有无默认值字段后面)
    blocked: Literal[True] = True
    kind: Literal["business_blocked"] = "business_blocked"

    def __post_init__(self) -> None:
        """D4.7.3 字段契约自洽校验(D3.3.3 教训应用).

        D4.6 v1.0.2 第三次复检 P2 修复范本:
          - failed 必为 True(类型层面固化, Literal[True] 在运行时是 str 注解, 双层防御)
          - last_error 必填非空
          - consecutive_draft_failures 严判 int(非 bool) + >= 1
          - tone ∈ 3 类
          - original_email_category ∈ 5 类
          - reason 锁定白名单
          - spam_reply_authorized + spam_reply_intent 强一致(同 DraftDecisionReport)
        """
        # D4.7.3 v1.0.3 P2-1: blocked 字段类型层面固化(替代 v1.0.2 failed)
        if self.blocked is not True:
            raise ValueError(
                f"DraftBlockedDecisionReport.blocked 必为 True "
                f"(D4.7.3 v1.0.3 P2-1 Literal[True] 类型层面固化, 业务阻断专属字段名), "
                f"实际 {self.blocked!r}"
            )
        # D4.7.3 v1.0.2 P2-1: kind 字段类型层面固化校验
        # 调用方依据 kind 区分业务阻断(本类) vs 技术失败(DraftFailureDecisionReport)
        # 防 cf 累加器误把业务阻断 cf 计入失败计数
        if self.kind != "business_blocked":
            raise ValueError(
                f"DraftBlockedDecisionReport.kind 必为 'business_blocked' "
                f"(D4.7.3 v1.0.2 P2-1 类型层面固化, 与 DraftFailureDecisionReport 区分), "
                f"实际 {self.kind!r}"
            )
        if not isinstance(self.last_error, str) or not self.last_error.strip():
            # D4.7.3 v1.0.4 P1-1 修复: strip() 语义非空校验(防纯空白字符串通过)
            raise ValueError(
                f"DraftBlockedDecisionReport.last_error 必填非空白 str(strip() 非空), "
                f"实际 {type(self.last_error).__name__}={self.last_error!r}"
            )
        if (
            not isinstance(self.consecutive_draft_failures, int)
            or isinstance(self.consecutive_draft_failures, bool)
            or self.consecutive_draft_failures < 0
        ):
            # D4.7.3 v1.0.1 P1-1 修复: 业务阻断场景 cf=0(不计入失败计数器),
            # 所以下限从 >=1 改为 >=0, 与 record_draft_failure_and_emit(技术失败)
            # 的 >=1 区分(技术失败 cf 必填 >=1)
            raise ValueError(
                f"DraftBlockedDecisionReport.consecutive_draft_failures 必须是 int(非 bool) >= 0"
                f"(D4.7.3 v1.0.1 P1-1: 业务阻断允许 0, 技术失败必填 >=1), "
                f"实际 {type(self.consecutive_draft_failures).__name__}="
                f"{self.consecutive_draft_failures!r}"
            )
        # D4.7.3 v1.0.4 P1-1 修复: 业务阻断 cf 必为 0(阻断不计入失败累加器)
        # 业务阻断永不 retry, cf 累加器必须跳过, 因此阻断场景 cf 锁定 0
        if self.consecutive_draft_failures != 0:
            raise ValueError(
                f"DraftBlockedDecisionReport.consecutive_draft_failures 业务阻断必为 0 "
                f"(D4.7.3 v1.0.4 P1-1: 业务阻断不计入失败累加器, 与 DraftFailureDecisionReport "
                f"cf>=1 区分), 实际 {self.consecutive_draft_failures}"
            )
        _validate_draft_tone(self.tone)
        # D4.7.3 v1.0.4 P1-1 修复: 业务阻断 category 必为 SPAM
        # (唯一 reason='spam_business_blocked' 强制 SPAM, 阻断原因只能由 SPAM 触发)
        if self.original_email_category != "SPAM":
            raise ValueError(
                f"DraftBlockedDecisionReport.original_email_category 业务阻断必为 'SPAM' "
                f"(D4.7.3 v1.0.4 P1-1: 业务阻断仅由 SPAM 邮件触发, 防止 URGENT/TODO/FYI/PERSONAL "
                f"+ spam_business_blocked 矛盾状态), 实际 {self.original_email_category!r}"
            )
        _validate_classify_category(self.original_email_category)
        if type(self.reason) is not str or not self.reason:
            raise ValueError(
                f"DraftBlockedDecisionReport.reason 必填非空 str, 实际 {type(self.reason).__name__}"
            )
        if self.reason not in {"spam_business_blocked"}:
            raise ValueError(
                f"DraftBlockedDecisionReport.reason 必须在 {{'spam_business_blocked'}} 之一, "
                f"实际 {self.reason!r}"
            )
        if type(self.spam_reply_authorized) is not bool:
            raise ValueError(
                f"DraftBlockedDecisionReport.spam_reply_authorized 必须是 bool, 实际 "
                f"{type(self.spam_reply_authorized).__name__}={self.spam_reply_authorized!r}"
            )
        if self.spam_reply_intent is not None and not isinstance(
            self.spam_reply_intent, _DraftSpamReplyIntent
        ):
            raise ValueError(
                f"DraftBlockedDecisionReport.spam_reply_intent 必须是 DraftSpamReplyIntent "
                f"枚举或 None, 实际 {type(self.spam_reply_intent).__name__}={self.spam_reply_intent!r}"
            )
        if self.spam_reply_intent is not None and self.spam_reply_intent.value not in {
            "UNSUBSCRIBE",
            "REJECT",
        }:
            raise ValueError(
                f"DraftBlockedDecisionReport.spam_reply_intent 必须是 "
                f"'UNSUBSCRIBE'/'REJECT' 或 None, 实际 {self.spam_reply_intent!r}"
            )
        # 强一致契约(D4.7.2 v1.0.8 P1-2 范本, blocked 路径也必须强一致)
        if self.spam_reply_authorized and self.spam_reply_intent is None:
            raise ValueError(
                "DraftBlockedDecisionReport.spam_reply_authorized=True 时 spam_reply_intent "
                "必为 DraftSpamReplyIntent 枚举 (D4.7.3 强一致契约), 实际 None"
            )
        if not self.spam_reply_authorized and self.spam_reply_intent is not None:
            raise ValueError(
                "DraftBlockedDecisionReport.spam_reply_authorized=False 时 spam_reply_intent "
                "必为 None (D4.7.3 强一致契约), "
                f"实际 {self.spam_reply_intent!r}"
            )


@dataclass(frozen=True)
class DraftFailureDecisionReport:
    """D4.7.3 v1.0.2 P1-1 新增: 技术失败草稿报告(独立类型, 不复用 DraftBlockedDecisionReport).

    D4.7.3 v1.0.1 漏洞: record_draft_failure_and_emit 返回 DraftBlockedDecisionReport,
    伪造 SPAM + spam_business_blocked 构造技术失败, 与"业务阻断"语义混淆,
    调用方可能错误累加失败次数或误读 audit。
    v1.0.2 真修: 独立类型, failed: Literal[True] 类型层面固化, 字段语义清晰区分业务阻断。
    [week1-mvp.md:716](/Users/wei/Documents/DesktopOrganizer/我的AI员工/docs/week1-mvp.md:716)
    锁定契约: DraftFailureDecisionReport 独立类型 + Literal[True] + __post_init__ 三重校验。

    与 DraftBlockedDecisionReport 区别:
      - DraftBlockedDecisionReport: 业务阻断(SPAM 等), context 中 last_draft_failed=False,
        cf=0, 永不 retry/escalate, 业务层 cf 累加器跳过该次记录
      - DraftFailureDecisionReport: 技术失败(LLM 异常), context 中 last_draft_failed=True,
        cf >= 1, 触发 retry/escalate, 业务层 cf 累加器正常 +1

    Attributes:
        evaluation: PolicyEngine.evaluate() 完整结果
        event_id: 落地到 events 表的 PolicyDecisionEvent id
        lane_entry_id: LaneBoard 中本次失败的 entry_id
        liveness: Heartbeat 评估的 Liveness
        failed: Literal[True](类型层面与 DraftDecisionReport / DraftBlockedDecisionReport 区分)
        last_error: 失败原因(必填非空, 截断到 200 字符)
        consecutive_draft_failures: 连续失败次数(必填 >= 1)
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    failed: Literal[True]  # 必为 True(类型层面与成功 / 业务阻断区分)
    last_error: str  # 必填非空(>0 字符), 截断到 200 字符
    consecutive_draft_failures: int  # 必填 >= 1

    def __post_init__(self) -> None:
        """D4.7.3 v1.0.2 P1-1: 字段契约自洽校验(三重校验, [week1-mvp.md:716](/Users/wei/Documents/DesktopOrganizer/我的AI员工/docs/week1-mvp.md:716) 锁定).

        D4.6 v1.0.2 第三次复检 P2 范本: Literal[True] 在运行时是 str 注解,
        mypy 阻拦但 Python 不阻拦, 所以 __post_init__ 也要显式校验 failed 必为 True
        (双层防御:静态 + 动态)。
        """
        if self.failed is not True:
            raise ValueError(
                f"DraftFailureDecisionReport.failed 必为 True "
                f"(Literal[True] 类型层面固化, D4.7.3 v1.0.2 P1-1), 实际 {self.failed!r}"
            )
        # D4.7.3 v1.0.5 P2-2 修复: last_error 严判 strip() 语义非空
        # (v1.0.4 P1-1 在 record_draft_business_blocked_and_emit 入口段加了,
        # 但数据类 __post_init__ 仍用 `not self.last_error` 长度检查, 纯空白字符串绕过)
        if not isinstance(self.last_error, str) or not self.last_error.strip():
            raise ValueError(
                f"DraftFailureDecisionReport.last_error 必填非空白 str(strip() 非空), "
                f"实际 {type(self.last_error).__name__}={self.last_error!r}"
            )
        if (
            not isinstance(self.consecutive_draft_failures, int)
            or isinstance(self.consecutive_draft_failures, bool)
            or self.consecutive_draft_failures < 1
        ):
            raise ValueError(
                f"DraftFailureDecisionReport.consecutive_draft_failures 必须是 int(非 bool) >= 1"
                f"(D4.7.3 v1.0.2 P1-1: 技术失败必填 cf, 与业务阻断 cf=0 区分), "
                f"实际 {type(self.consecutive_draft_failures).__name__}="
                f"{self.consecutive_draft_failures!r}"
            )


# ===== D4.7.3 业务层适配器主类 =====


class EmailDrafterAdapter:
    """D4.7.3 业务层接入适配器 — EmailDrafter 接入 PolicyEngine 4 件套.

    复用 D4.6 EmailClassifierAdapter + D4.5 SyncPolicyAdapter 三入口架构:
      - event_store: 落 PolicyDecisionEvent(D4.3)
      - engine: PolicyEngine(D4.4 决策引擎)
      - heartbeat: Heartbeat(LLM 探活)
      - board: LaneBoard(草稿任务看板)

    用法(生产):
        from my_ai_employee.ai.drafter import EmailDrafter
        from my_ai_employee.policy import (
            EmailDrafterAdapter, EventStore, PolicyEngine,
        )

        drafter = EmailDrafter()
        adapter = EmailDrafterAdapter(
            source="qq",
            event_store=event_store,
            engine=PolicyEngine(),
        )
        result = drafter.draft(
            subject="客户投诉",
            sender="client@example.com",
            body_excerpt="...",
            email_category=EmailCategory.URGENT,
            tone=DraftTone.FORMAL,
        )
        report = adapter.draft_and_emit(
            email_id=123,
            email_category="URGENT",  # D4.7.3 v1.0.5 P3 修复: 补必填 category
            draft_result=result,
        )

    阻断场景(SPAM 业务硬阻断, 返回 DraftBlockedDecisionReport):
        from my_ai_employee.ai.drafter import SpamBlockedError

        try:
            drafter.draft(email_category=EmailCategory.SPAM)
        except SpamBlockedError as e:
            report = adapter.record_draft_business_blocked_and_emit(
                email_id=123,
                tone=DraftTone.FORMAL,
                original_email_category="SPAM",  # 必配 SPAM(reason=spam_business_blocked 锁定)
                reason="spam_business_blocked",
                last_error=str(e),
                consecutive_draft_failures=0,  # 业务阻断 cf=0(不计入失败累加器)
                spam_reply_authorized=False,
            )

    技术失败场景(LLM 异常, 返回 DraftFailureDecisionReport):
        import time

        try:
            drafter.draft(...)
        except (LLMTimeoutError, JSONParseError) as e:
            report = adapter.record_draft_failure_and_emit(
                email_id=123,
                last_error=str(e),
                consecutive_draft_failures=1,  # 必 >= 1(技术失败计入累加器)
            )

    设计要点(沿用 D4.6 v1.0.2 + D4.5 P0 + D4.7.3 v1.0.2 P1-1):
      - EmailDrafter 在外层调(draft 决策独立可测)
      - 4 依赖可注入(None = 跳过该环节, 测试用)
      - lane_entry_id 命名 "draft:<source>:<run_id>"(与 sync / classify 区分)
      - 三入口互斥: draft_and_emit(成功) + record_draft_business_blocked_and_emit
        (业务阻断, SPAM 硬阻断) + record_draft_failure_and_emit(技术失败, LLM 异常)
      - 业务 payload 透传 spam_reply_authorized + spam_reply_intent(D4.7.2 v1.0.8 强一致)
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
        # D4.7.3 v1.0.5 P2-2 修复: source 严判 strip() 语义非空
        # (v1.0.4 P2-4 在 build_draft_packet/build_draft_blocked_packet 工厂层加了,
        # 但 Adapter __init__ 仍用 `not source` 长度检查, 纯空白字符串绕过,
        # 后续 build_lane_entry_id("run-1") 会生成 "draft:   :run-1" 无效 lane_entry_id)
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                f"source 必填非空白 str(strip() 非空), 实际 {type(source).__name__}={source!r}"
            )
        self._source = source
        self._event_store = event_store
        # D4.7.3 v1.0.3 P2-2 修复: 用 `is None` 范式而非 `or`, 保留合法 falsey 替身
        # (测试替身 / 自定义实例如果 __bool__() 返回 False 会被 or 错误替换为默认实例)
        self._engine = engine if engine is not None else PolicyEngine()
        self._heartbeat = (
            heartbeat if heartbeat is not None else Heartbeat(idle_threshold_ms=30_000)
        )
        self._board = board if board is not None else LaneBoard(idle_threshold_ms=60_000)

    def build_lane_entry_id(self, run_id: str) -> str:
        """生成 LaneBoard entry_id: 'draft:<source>:<run_id>'."""
        # D4.7.3 v1.0.5 P2-2 修复: run_id 严判 strip() 语义非空
        # (纯空白 run_id 会生成 "draft:qq:   " 无效 lane_entry_id)
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError(
                f"run_id 必填非空白 str(strip() 非空), 实际 {type(run_id).__name__}={run_id!r}"
            )
        return f"draft:{self._source}:{run_id}"

    def record_to_lane(
        self,
        *,
        run_id: str,
        status: LaneStatus,
        objective: str = "",
        owner: str = "email_drafter",
    ) -> LaneEntry:
        """LaneBoard 记录: add (ACTIVE/BLOCKED) 或 update (FINISHED).

        与 EmailClassifierAdapter.record_to_lane 同逻辑(D4.6 范本复用)。
        """
        entry_id = self.build_lane_entry_id(run_id)
        if not objective:
            objective = f"Email draft source={self._source}"
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

    def draft_and_emit(
        self,
        *,
        email_id: int,
        draft_result: DraftResult,  # duck type(避免循环 import)
        category: str,  # D4.7.3 v1.0.1 P1-2 新增: 5 类邮件标签(week1-mvp.md 锁定)
        transport_alive: bool = True,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> DraftDecisionReport:
        """成功草稿主入口: 评估草稿结果 + 落 1 条 PolicyDecisionEvent.

        D4.7.3 范本(沿用 D4.6 v1.0.2 P1-1 三入口互斥):
          - 成功路径 = last_draft_failed=False + consecutive_draft_failures=0,
            触发 merge_required(全部 AC pass)或 BLOCKED(业务拒绝)— 永不触发 retry
          - 业务阻断请走 record_draft_business_blocked_and_emit(SPAM 硬阻断,
            返回 DraftBlockedDecisionReport, kind="business_blocked")
          - 技术失败请走 record_draft_failure_and_emit(LLM 异常,
            返回 DraftFailureDecisionReport, last_draft_failed=True + cf >= 1)

        D4.7.2 v1.0.8 强一致契约:
          - draft_result.spam_reply_authorized / spam_reply_intent 已是强一致
          - Adapter 透传到 extra_business_payload, 便于 events audit 信任

        Args:
            email_id: 邮件主键(emails.id)
            draft_result: EmailDrafter.draft() 的返回(duck type, 严判字段)
            transport_alive: LLM 路由本次是否可用(默认 True,失败由 caller 外层决定)
            run_id: LaneBoard entry 唯一 ID(空 = 用 now_ms 字符串)
            now_ms: 注入时间(默认 int(time.time() * 1000))

        Returns:
            DraftDecisionReport

        Raises:
            ValueError: 参数 type 错 / 字段越界 / spam_reply_authorized 与 intent 不一致
            PolicyContractError: build_draft_packet 8 字段不全
            PolicyDecisionError: build_draft_policy_context 类型非法
            EventContractError / EventMetadataError: EventStore.insert 失败
        """
        import time as _time

        # 严判 email_id(D4.5 P0 严判入口范本)
        if type(email_id) is bool or not isinstance(email_id, int) or email_id < 0:
            raise ValueError(
                f"email_id 必须是原生 int >= 0, 实际 {type(email_id).__name__}={email_id!r}"
            )
        # 严判 transport_alive(D4.6 v1.0.1 P1-2 范本)
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )

        # 严判 draft_result duck type(D4.6 v1.0.1 P2-5 范本, 拒 bool/str)
        # D4.7.3 v1.0.0 沿用, 严判必要字段 + spam_reply 双字段强一致
        for required in (
            "subject",
            "body",
            "tone",
            "model_full_id",
            "latency_ms",
            "spam_reply_authorized",
            "spam_reply_intent",
        ):
            if not hasattr(draft_result, required):
                raise ValueError(
                    f"draft_result.{required} 缺失, 实际 {type(draft_result).__name__}"
                )

        # D4.7.3 v1.0.3 P1-1 真修: 复用 drafter._validate_draft_subject / _validate_draft_body
        # 严判契约(1-200/10-8000 + strip 语义非空), 不再自造严判逻辑
        # v1.0.2 漏洞: 仅 strip() 严判语义非空, 但缺契约 helper 严判长度上下界 + type
        # → 201 字符 subject / 8001 字符 body / 空白 model_full_id 仍可通过
        try:
            _validate_draft_subject(draft_result.subject)
        except ValueError as e:
            # 增加 draft_result. 前缀便于 audit 追溯是 Adapter 入参
            raise ValueError(f"draft_result.subject 契约违反: {e}") from e
        try:
            _validate_draft_body(draft_result.body)
        except ValueError as e:
            raise ValueError(f"draft_result.body 契约违反: {e}") from e
        # D4.7.3 v1.0.3 P1-1 严判 model_full_id 非空 str(契约 1, 防空白/None 绕过)
        if type(draft_result.model_full_id) is not str or not draft_result.model_full_id.strip():
            raise ValueError(
                f"draft_result.model_full_id 必填非空白 str, 实际 "
                f"{type(draft_result.model_full_id).__name__}={draft_result.model_full_id!r}"
            )

        # D4.7.3 v1.0.1 P1-2 修复: 严判 category ∈ 5 类
        # week1-mvp.md:705 锁定 6 字段契约, category 是 D4.6 分类结果(上游必传入)
        _validate_classify_category(category)

        tone = draft_result.tone
        # duck type: tone 可能是 DraftTone 枚举或字符串, _validate_draft_tone 接受两者
        if hasattr(tone, "value"):
            tone_value = tone.value
        elif isinstance(tone, str):
            tone_value = tone
        else:
            raise ValueError(
                f"draft_result.tone 必须是 DraftTone 枚举或 str, 实际 "
                f"{type(tone).__name__}={tone!r}"
            )
        _validate_draft_tone(tone_value)

        if type(draft_result.latency_ms) is bool or not isinstance(draft_result.latency_ms, int):
            raise ValueError(
                f"draft_result.latency_ms 必须是 int(非 bool), 实际 "
                f"{type(draft_result.latency_ms).__name__}={draft_result.latency_ms!r}"
            )
        _validate_draft_latency_ms(draft_result.latency_ms)
        latency_ms = draft_result.latency_ms

        body_length = len(draft_result.body)
        _validate_draft_body_length(body_length)

        if type(draft_result.model_full_id) is not str or not draft_result.model_full_id:
            raise ValueError(
                f"draft_result.model_full_id 必填非空 str, 实际 "
                f"{type(draft_result.model_full_id).__name__}"
            )
        model_full_id = draft_result.model_full_id

        # D4.7.2 v1.0.7 P1-1 + v1.0.8 P1-2 强一致: spam_reply 双字段严判
        if type(draft_result.spam_reply_authorized) is not bool:
            raise ValueError(
                f"draft_result.spam_reply_authorized 必须是 bool, 实际 "
                f"{type(draft_result.spam_reply_authorized).__name__}"
            )
        spam_reply_authorized = draft_result.spam_reply_authorized

        # D4.7.3 v1.0.2 P1-2 强一致: category 与 spam_reply_authorized 绑定
        # (D4.7.2 v1.0.7 P1-1 已范本: spam_reply_authorized=True 必配 SPAM)
        # v1.0.2 反向补强: spam_reply_authorized=False + category=SPAM 也拒收
        # (SPAM 邮件不可能不授权 — 业务层 cf 应 +1)
        if spam_reply_authorized and category != "SPAM":
            raise ValueError(
                f"draft_result.spam_reply_authorized=True 时 category 必为 'SPAM'"
                f"(D4.7.2 v1.0.7 P1-1 范本, D4.7.3 v1.0.2 P1-2 反向补强), "
                f"实际 category={category!r}"
            )
        if not spam_reply_authorized and category == "SPAM":
            raise ValueError(
                f"draft_result.spam_reply_authorized=False 时 category 不能为 'SPAM'"
                f"(D4.7.3 v1.0.2 P1-2 反向补强: SPAM 邮件必须显式授权放行), "
                f"实际 category={category!r}"
            )

        # 入口预校验(D4.7.2 v1.0.8 P1-2 范本: 双层防御之一)
        if spam_reply_authorized and draft_result.spam_reply_intent is None:
            raise ValueError(
                "draft_result.spam_reply_authorized=True 时 spam_reply_intent "
                "必为 DraftSpamReplyIntent 枚举 (D4.7.2 v1.0.8 强一致契约), 实际 None"
            )
        if not spam_reply_authorized and draft_result.spam_reply_intent is not None:
            raise ValueError(
                "draft_result.spam_reply_authorized=False 时 spam_reply_intent "
                "必为 None (D4.7.2 v1.0.8 强一致契约), "
                f"实际 {draft_result.spam_reply_intent!r}"
            )
        # 严判 spam_reply_intent 类型(避免运行时 DraftSpamReplyIntent 引用, 用枚举值白名单)
        if draft_result.spam_reply_intent is not None:
            intent_value = (
                draft_result.spam_reply_intent.value
                if hasattr(draft_result.spam_reply_intent, "value")
                else draft_result.spam_reply_intent
            )
            if intent_value not in {"UNSUBSCRIBE", "REJECT"}:
                raise ValueError(
                    f"draft_result.spam_reply_intent 必须是 UNSUBSCRIBE/REJECT, 实际 {intent_value!r}"
                )
            spam_reply_intent_str = intent_value
        else:
            spam_reply_intent_str = None

        # 1) 构造 TaskPacket
        packet = build_draft_packet(
            email_id=email_id,
            source=self._source,
            tone=tone_value,
            model_full_id=model_full_id,
            body_length=body_length,
        )

        # 2) 构造 context(成功路径强制 cf=0, 永不失败, 与 D4.6 v1.0.2 P1-1 对齐)
        context = build_draft_policy_context(
            tone=tone_value,
            latency_ms=latency_ms,
            body_length=body_length,
            last_draft_failed=False,  # P1-1 强制: 成功路径永不失败
            consecutive_draft_failures=0,  # P1-1 强制: 成功路径计数归零
            now_ms=now_ms if now_ms is not None else int(_time.time() * 1000),
        )

        # 3) run_id + lane_entry_id
        rid = run_id or str(int(_time.time() * 1000))
        lane_entry_id = self.build_lane_entry_id(rid)

        # 4) PolicyEngine.evaluate(透传业务字段)
        # D4.7.3 新增: spam_reply_authorized + spam_reply_intent 双字段透传
        # (D4.7.2 v1.0.8 强一致契约, Adapter 必透传以 audit 信任)
        extra_business_payload = {
            # D4.7.3 v1.0.1 P1-2: week1-mvp.md:705 锁定 6 字段透传契约
            # draft_subject / draft_body / tone / model_full_id / email_id / category
            "draft_subject": draft_result.subject,
            "draft_body": draft_result.body,
            "tone": tone_value,
            "model_full_id": model_full_id,
            "body_length": body_length,
            "latency_ms": latency_ms,
            "email_id": email_id,
            "category": category,  # D4.7.3 v1.0.1 P1-2 新增(上游 D4.6 分类结果)
            "source": self._source,
            "spam_reply_authorized": spam_reply_authorized,
            "spam_reply_intent": spam_reply_intent_str,
        }
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=self._event_store,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload=extra_business_payload,
        )

        # 5) LaneBoard 记录(单一真相源 = acceptance_results, D4.5 P0-3 范本)
        ac_results = compute_draft_acceptance(
            tone=tone_value,
            latency_ms=latency_ms,
            body_length=body_length,
        )
        business_accepted = bool(all(ac_results))
        self.record_to_lane(
            run_id=rid,
            status=LaneStatus.FINISHED if business_accepted else LaneStatus.BLOCKED,
        )

        # 6) Heartbeat(D4.6 v1.0.1 P1-2 范本: 用 transport_alive, 不耦合 business)
        liveness = self.tick_heartbeat(transport_alive=transport_alive, now_ms=now_ms)

        return DraftDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            tone=tone_value,
            model_full_id=model_full_id,
            email_id=email_id,
            latency_ms=latency_ms,
            body_length=body_length,
            spam_reply_authorized=spam_reply_authorized,
            # D4.7.3: 转 DraftSpamReplyIntent 枚举实例, __post_init__ 强一致校验
            spam_reply_intent=(
                _DraftSpamReplyIntent(spam_reply_intent_str)
                if spam_reply_intent_str is not None
                else None
            ),
        )

    def record_draft_business_blocked_and_emit(
        self,
        *,
        email_id: int,
        tone: str | DraftTone,
        original_email_category: str,
        reason: str,
        last_error: Any,  # str | SpamBlockedError | Exception
        transport_alive: bool = True,
        spam_reply_authorized: bool = False,
        spam_reply_intent: DraftSpamReplyIntent | str | None = None,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> DraftBlockedDecisionReport:
        """业务阻断草稿入口: 记录阻断原因, 强制 BLOCKED, 不触发 retry / escalate.

        D4.7.3 v1.0.1 P1-1 真修(检查员反馈):
          - 业务阻断(SPAM 业务硬阻断)≠ 技术失败(DrafterResponseError / LLM 异常)
          - 旧 v1.0.0 混淆: 用 last_draft_failed=True, 触发 retry_available(cf<3) /
            escalate(cf>=3), 重复无意义调用, 达到 3 次还会升级
          - 真修: 业务阻断 last_draft_failed=False(等同成功路径), cf 隐式 0
            → context 12 字段无 retry / escalate 信号 → 直接 BLOCKED
          - 技术失败另设 record_draft_failure_and_emit(last_draft_failed=True +
            cf >= 1), 复用 D4.6 v1.0.2 record_classify_failure_and_emit 范本

        与 record_draft_failure_and_emit 区别(关键):
          - 业务阻断: SPAM 业务硬阻断, 邮件本身的语义就是"不回复", retry 毫无意义
          - 技术失败: LLM 响应解析失败 / 网络超时 / 锁失败, 重试可能成功
        """
        import time as _time

        # 严判 email_id
        if type(email_id) is bool or not isinstance(email_id, int) or email_id < 0:
            raise ValueError(
                f"email_id 必须是原生 int >= 0, 实际 {type(email_id).__name__}={email_id!r}"
            )
        # 严判 transport_alive
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )
        # 严判 last_error(转 str 后非空)
        if last_error is None:
            raise ValueError("last_error 不能为 None, 阻断必须带原因")
        last_error_str = str(last_error)
        if not last_error_str or not last_error_str.strip():
            # D4.7.3 v1.0.4 P1-1 修复: strip() 语义非空校验(防纯空白字符串通过,
            # 如 Exception("   ") str() 后是 "   ")
            raise ValueError(
                f"last_error 必填非空白 (str() 后 strip() 非空), 实际 "
                f"{type(last_error).__name__}={last_error_str!r}"
            )
        # 严判 tone(接受 DraftTone 枚举或 str)
        if hasattr(tone, "value"):
            tone_value = tone.value
        elif isinstance(tone, str):
            tone_value = tone
        else:
            raise ValueError(
                f"tone 必须是 DraftTone 枚举或 str, 实际 {type(tone).__name__}={tone!r}"
            )
        _validate_draft_tone(tone_value)
        # 严判 original_email_category ∈ 5 类
        _validate_classify_category(original_email_category)
        # 严判 reason 类型 + 锁定白名单
        # D4.7.3 v1.0.5 P2-1 修复: 必须先 isinstance 严判(否则 reason=[] 会抛
        # `TypeError: unhashable type: 'list'` 违反公开入口统一 ValueError 的契约)
        if type(reason) is not str or not reason:
            raise ValueError(f"reason 必填非空 str, 实际 {type(reason).__name__}={reason!r}")
        if reason not in {"spam_business_blocked"}:
            raise ValueError(f"reason 必须在 {{'spam_business_blocked'}} 之一, 实际 {reason!r}")
        # D4.7.3 v1.0.1 P2-2: reason 与 original_email_category 强一致
        if reason == "spam_business_blocked" and original_email_category != "SPAM":
            raise ValueError(
                f"reason={reason!r} 时 original_email_category 必为 'SPAM'"
                f"(业务阻断原因只能由 SPAM 邮件触发), 实际 {original_email_category!r}"
            )
        # 严判 spam_reply_authorized bool
        if type(spam_reply_authorized) is not bool:
            raise ValueError(
                f"spam_reply_authorized 必须是 bool, 实际 "
                f"{type(spam_reply_authorized).__name__}={spam_reply_authorized!r}"
            )
        # 严判 spam_reply_intent 类型 + 入口预校验(双层防御)
        if spam_reply_intent is not None:
            intent_value = (
                spam_reply_intent.value
                if hasattr(spam_reply_intent, "value")
                else spam_reply_intent
            )
            if intent_value not in {"UNSUBSCRIBE", "REJECT"}:
                raise ValueError(
                    f"spam_reply_intent 必须是 UNSUBSCRIBE/REJECT, 实际 {intent_value!r}"
                )
            spam_reply_intent_str: str | None = intent_value
        else:
            spam_reply_intent_str = None
        # D4.7.2 v1.0.8 P1-2 范本: 入口预校验 spam_reply 双字段强一致
        if spam_reply_authorized and spam_reply_intent_str is None:
            raise ValueError(
                "spam_reply_authorized=True 时 spam_reply_intent 必为 "
                "DraftSpamReplyIntent 枚举 (D4.7.2 v1.0.8 强一致契约), 实际 None"
            )
        if not spam_reply_authorized and spam_reply_intent_str is not None:
            raise ValueError(
                "spam_reply_authorized=False 时 spam_reply_intent 必为 None "
                "(D4.7.2 v1.0.8 强一致契约), "
                f"实际 {spam_reply_intent_str!r}"
            )

        # 1) 构造 TaskPacket(阻断专用 factory)
        packet = build_draft_blocked_packet(
            email_id=email_id,
            source=self._source,
            tone=tone_value,
            reason=reason,
            original_email_category=original_email_category,
        )

        # 2) 构造 context — D4.7.3 v1.0.1 P1-1 范本: 业务阻断 last_draft_failed=False
        # (等同成功路径), 永不 retry / escalate, 用 synthetic tone=FORMAL +
        # latency=0 + body_length=0 让 AC 全 False → BLOCKED(不 merge)
        # 业务阻断不计入失败计数器, cf 永远 = 0
        context = build_draft_policy_context(
            tone="FORMAL",  # synthetic, 仅用于 context 必填字段
            latency_ms=0,  # synthetic, 阻断无延迟
            body_length=0,  # synthetic, 阻断无 body
            last_draft_failed=False,  # D4.7.3 v1.0.1 P1-1: 业务阻断 ≠ 失败
            consecutive_draft_failures=0,  # 业务阻断不计入失败计数
            now_ms=now_ms if now_ms is not None else int(_time.time() * 1000),
        )

        # 3) run_id + lane_entry_id
        rid = run_id or str(int(_time.time() * 1000))
        lane_entry_id = self.build_lane_entry_id(rid)

        # 4) PolicyEngine.evaluate — 业务 payload 标记为业务阻断
        # D4.7.3 新增: spam_reply_authorized + spam_reply_intent 双字段透传
        extra_business_payload = {
            "tone": tone_value,
            "original_email_category": original_email_category,
            "reason": reason,
            "last_error": last_error_str[:200],
            "email_id": email_id,
            "source": self._source,
            "spam_reply_authorized": spam_reply_authorized,
            "spam_reply_intent": spam_reply_intent_str,
            "blocked": True,
            "blocked_kind": "business",  # D4.7.3 v1.0.1: 区分业务阻断 vs 技术失败
        }
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=self._event_store,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload=extra_business_payload,
        )

        # 5) LaneBoard: 阻断入口强制 BLOCKED
        self.record_to_lane(
            run_id=rid,
            status=LaneStatus.BLOCKED,
        )

        # 6) Heartbeat — 用 transport_alive
        liveness = self.tick_heartbeat(transport_alive=transport_alive, now_ms=now_ms)

        return DraftBlockedDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            # D4.7.3 v1.0.3 P2-1: blocked=True 替代 failed=True(业务阻断专属字段名)
            blocked=True,
            last_error=last_error_str[:200],
            consecutive_draft_failures=0,  # 业务阻断不计入失败计数
            tone=tone_value,
            original_email_category=original_email_category,
            reason=reason,
            spam_reply_authorized=spam_reply_authorized,
            spam_reply_intent=(
                _DraftSpamReplyIntent(spam_reply_intent_str)
                if spam_reply_intent_str is not None
                else None
            ),
        )

    def record_draft_blocked_and_emit(self, **kwargs) -> DraftBlockedDecisionReport:
        """向后兼容别名 → record_draft_business_blocked_and_emit(D4.7.3 v1.0.1 P1-1 拆分).

        旧 v1.0.0 入参 `consecutive_draft_failures` 不再需要(业务阻断不计入失败计数器),
        静默忽略多余 kwarg, 然后委托新方法。
        v1.0.2 再彻底删除旧 API(给业务层 1 周迁移窗口)。
        """
        kwargs.pop("consecutive_draft_failures", None)
        return self.record_draft_business_blocked_and_emit(**kwargs)

    def record_draft_failure_and_emit(
        self,
        *,
        email_id: int,
        last_error: Any,  # str | DrafterResponseError | LLMError | Exception
        consecutive_draft_failures: int,
        transport_alive: bool = True,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> DraftFailureDecisionReport:
        """技术失败草稿入口: DrafterResponseError / LLM 异常, 触发 retry / escalate.

        D4.7.3 v1.0.2 P1-1 真修(检查员第二轮反馈):
          - 返回 DraftFailureDecisionReport(独立类型), 不再伪装 SPAM + DraftBlockedDecisionReport
          - 用 build_draft_failure_packet(独立失败 factory), 不复用 build_draft_blocked_packet
            + synthetic 占位
          - 与业务阻断 record_draft_business_blocked_and_emit 完全分离
          - [week1-mvp.md:716](/Users/wei/Documents/DesktopOrganizer/我的AI员工/docs/week1-mvp.md:716)
            锁定契约: DraftFailureDecisionReport 独立类型 + Literal[True] + __post_init__ 三重校验
        """
        import time as _time

        # 严判 email_id
        if type(email_id) is bool or not isinstance(email_id, int) or email_id < 0:
            raise ValueError(
                f"email_id 必须是原生 int >= 0, 实际 {type(email_id).__name__}={email_id!r}"
            )
        # 严判 consecutive_draft_failures(技术失败入口必填 >= 1)
        if (
            type(consecutive_draft_failures) is bool
            or not isinstance(consecutive_draft_failures, int)
            or consecutive_draft_failures < 1
        ):
            raise ValueError(
                f"consecutive_draft_failures 必须是原生 int >= 1, 实际 "
                f"{type(consecutive_draft_failures).__name__}="
                f"{consecutive_draft_failures!r}"
            )
        # 严判 transport_alive
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )
        # 严判 last_error(转 str 后非空)
        if last_error is None:
            raise ValueError("last_error 不能为 None, 技术失败必须带原因")
        last_error_str = str(last_error)
        if not last_error_str:
            raise ValueError(
                f"last_error 必填非空 (str() 后非空), 实际 {type(last_error).__name__}"
            )

        # 1) 构造 TaskPacket: 用独立 build_draft_failure_packet(不再复用阻断 factory)
        # D4.7.3 v1.0.2 P1-1 真修: 不再用 SPAM + spam_business_blocked 伪装
        packet = build_draft_failure_packet(
            email_id=email_id,
            source=self._source,
            last_error_str=last_error_str,
            consecutive_draft_failures=consecutive_draft_failures,
        )

        # 2) 构造 context — 技术失败 last_draft_failed=True, 触发 retry/escalate
        context = build_draft_policy_context(
            tone="FORMAL",
            latency_ms=0,
            body_length=0,
            last_draft_failed=True,
            consecutive_draft_failures=consecutive_draft_failures,
            now_ms=now_ms if now_ms is not None else int(_time.time() * 1000),
        )

        # 3) run_id + lane_entry_id
        rid = run_id or str(int(_time.time() * 1000))
        lane_entry_id = self.build_lane_entry_id(rid)

        # 4) PolicyEngine.evaluate — 业务 payload 标记为技术失败
        extra_business_payload = {
            "email_id": email_id,
            "source": self._source,
            "last_error": last_error_str[:200],
            "consecutive_draft_failures": consecutive_draft_failures,
            "failed": True,
            "failed_kind": "technical",
        }
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=self._event_store,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload=extra_business_payload,
        )

        # 5) LaneBoard: 技术失败入口强制 BLOCKED
        self.record_to_lane(
            run_id=rid,
            status=LaneStatus.BLOCKED,
        )

        # 6) Heartbeat — 用 transport_alive
        liveness = self.tick_heartbeat(transport_alive=transport_alive, now_ms=now_ms)

        # D4.7.3 v1.0.2 P1-1 真修: 返回独立 DraftFailureDecisionReport, 不再返回 DraftBlockedDecisionReport
        return DraftFailureDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            failed=True,
            last_error=last_error_str[:200],
            consecutive_draft_failures=consecutive_draft_failures,
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
    # D4.7.3 邮件草稿适配器(D4.7 草稿生成器业务层接入点)
    "EmailDrafterAdapter",
    "DraftDecisionReport",
    "DraftBlockedDecisionReport",
    "build_draft_packet",
    "build_draft_blocked_packet",
    "build_draft_failure_packet",
    "build_draft_policy_context",
    "compute_draft_acceptance",
    "DraftFailureDecisionReport",
    # D4.7.3 v1.0.1 P1-1 拆分: 业务阻断 vs 技术失败
    # 注: 这两个方法是 EmailDrafterAdapter 类的成员方法, 不在模块顶层 __all__ 列出
    # 业务层调用: adapter.record_draft_business_blocked_and_emit(...) /
    # adapter.record_draft_failure_and_emit(...)
]
