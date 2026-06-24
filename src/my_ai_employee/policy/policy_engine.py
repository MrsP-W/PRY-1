"""D4.4 — PolicyEngine (g006 §"Executable policy decisions").

参考 g006-task-policy-board-verification-map.md:
  6 决策:
    1. RetryAvailable          — 可重试(recoverable error + attempts < max)
    2. RebaseRequired          — 需 rebase(branch stale)
    3. StaleCleanupRequired    — 需清 stale(心跳超时)
    4. ApprovalTokenRequired   — 需审批 token(敏感操作 / 高权限)
    5. MergeRequired           — 可合并(所有 acceptance 通过)
    6. EscalateRequired        — 需升级(policy 评估失败 / 不可恢复)

设计:
  - PolicyEngine 单例(get_engine())
  - evaluate(packet, context, store=None) → PolicyEvaluation
  - context: 决策信号 dict(last_error_recoverable, current_attempts, ...)
  - 每次 evaluate 可选地 emit 1 条 PolicyDecisionEvent 到 events 表
  - 编程错误透传(D3.3.3 教训)

事件名 (events 表):
  - policy.decision.made (succeeded)
  - policy.decision.degraded (degraded / 异常)

集成点 (D4.x 互操作):
  - D4.3 events/store.py: 复用 EventStore.insert() 落地决策事件
  - D4.1 router.py: 决策输入(capability / fallback 状态)
  - D4.2 mcp/discovery.py: 决策输入(required/optional/degraded report)
  - heartbeat.py: 提取 last_heartbeat_ms 喂给 StaleCleanupRequired rule
"""

from __future__ import annotations

import enum
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from my_ai_employee.events.models import (
    EventOwnership,
    EventProvenance,
    EventStatus,
    EventType,
)
from my_ai_employee.policy.exceptions import (
    PolicyDecisionError,
)
from my_ai_employee.policy.task_packet import (
    TaskPacket,
    assert_packet_contract,
)

# ===== 6 决策 kind 枚举 =====


class PolicyDecisionKind(enum.StrEnum):
    """6 决策 kind (g006 §"executable policy decisions").

    与 g006 verbatim 对齐:
      - retry_available / rebase_required / stale_cleanup_required /
        approval_token_required / merge_required / escalate_required
    """

    RETRY_AVAILABLE = "retry_available"
    REBASE_REQUIRED = "rebase_required"
    STALE_CLEANUP_REQUIRED = "stale_cleanup_required"
    APPROVAL_TOKEN_REQUIRED = "approval_token_required"
    MERGE_REQUIRED = "merge_required"
    ESCALATE_REQUIRED = "escalate_required"


# ===== PolicyDecision dataclass =====


@dataclass
class PolicyDecision:
    """单条决策 (g006 §"PolicyDecisionEvent 字段").

    Attributes:
        rule_name: 决策名(同 PolicyDecisionKind.value)
        priority: 优先级(0-100, 高优先级优先执行)
        kind: 决策 kind(PolicyDecisionKind)
        explanation: 人类可读解释(为什么这条决策)
        target_action: 推荐执行的动作(如 "retry", "rebase", "escalate")
        approval_token_id: 审批 token ID(若 kind == APPROVAL_TOKEN_REQUIRED, 可空)
    """

    rule_name: str
    priority: int
    kind: PolicyDecisionKind
    explanation: str
    target_action: str
    approval_token_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "priority": self.priority,
            "kind": self.kind.value,
            "explanation": self.explanation,
            "target_action": self.target_action,
            "approval_token_id": self.approval_token_id,
        }


# ===== PolicyEvaluation 顶层结果 =====


@dataclass
class PolicyEvaluation:
    """PolicyEngine.evaluate() 返回值.

    Attributes:
        status: 评估状态(succeeded / failed / degraded)
        decisions: 决策列表(可能为空, 即"没有决策需要执行")
        event_id: events 表中落地的 PolicyDecisionEvent id(若提供 store, 否则 None)
        packet: 评估的 TaskPacket(供 caller 追溯)
        context_snapshot: 评估时使用的 context(便于复现)
    """

    status: str
    decisions: list[PolicyDecision] = field(default_factory=list)
    event_id: int | None = None
    packet: TaskPacket | None = None
    context_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "decisions": [d.to_dict() for d in self.decisions],
            "event_id": self.event_id,
            "packet": self.packet.to_dict() if self.packet else None,
            "context_snapshot": dict(self.context_snapshot),
        }

    def has_decision(self, kind: PolicyDecisionKind) -> bool:
        """是否包含某 kind 决策."""
        return any(d.kind == kind for d in self.decisions)


# ===== PolicyEngine 主类 =====


class PolicyEngine:
    """策略引擎 (g006 §"executable policy engine").

    Usage:
        engine = PolicyEngine()
        packet = TaskPacket(...)
        context = {
            "last_error_recoverable": True,
            "current_attempts": 1,
            "max_attempts": 3,
            "branch_stale": False,
            "last_heartbeat_ms": now_ms,
            "stale_threshold_ms": 60_000,
            "action_sensitive": True,
            "has_approval_token": False,
            "acceptance_results": [True, True, True],  # 全部 pass
            "policy_eval_failed": False,
        }
        evaluation = engine.evaluate(packet, context)
        # 可选: 落 events 表
        evaluation_with_event = engine.evaluate(packet, context, store=event_store)
    """

    def evaluate(
        self,
        packet: TaskPacket,
        context: dict[str, Any] | None = None,
        store: Any | None = None,
        *,
        lane_entry_id: str = "",
        run_id: str = "",
        extra_business_payload: dict[str, Any] | None = None,
    ) -> PolicyEvaluation:
        """主入口: 评估 TaskPacket 的 6 决策.

        Args:
            packet: 8 必含字段 TaskPacket
            context: 决策信号 dict(缺字段有合理 default)
            store: 可选 EventStore, 提供则落地 PolicyDecisionEvent
            lane_entry_id: 可选 — LaneBoard 关联 entry id(写进 event_metadata
                便于 `mmx policy history --lane` 跨次评估串联,D4.5 v1.0.1 新增)
            run_id: 可选 — 单次评估 run id(写进 event_metadata,与 lane_entry_id 配对)
            extra_business_payload: 可选 — 业务层透传字段(D4.6 新增,EmailClassifierAdapter
                传 {category, confidence, model_full_id, email_id, source} 5 项,便于
                `mmx policy history` 跨业务类型查询时不只看到决策,还能反查业务结果)
                透传字段必须 key 是 str, value 是 JSON 可序列化(由 EventStore 严判)

        Returns:
            PolicyEvaluation(含 status / decisions / event_id)

        Raises:
            PolicyContractError: packet 不满足 8 字段不变量
            PolicyDecisionError: context 关键信号非法(严格解析, D4.4 P1 修复)
            EventContractError / EventMetadataError: 事件落地失败(events/store 透传)
        """
        # 1. 校验 packet 8 字段
        assert_packet_contract(packet)

        # 2. 归一 context(缺字段 → defaults)
        ctx = self._normalize_context(context or {})

        # 3. 跑 6 rule
        decisions: list[PolicyDecision]
        evaluation_status = EventStatus.SUCCEEDED.value
        try:
            decisions = self._run_all_rules(packet, ctx)
        except PolicyDecisionError as err:
            evaluation_status = EventStatus.FAILED.value
            decisions = [
                PolicyDecision(
                    rule_name=PolicyDecisionKind.ESCALATE_REQUIRED.value,
                    priority=100,
                    kind=PolicyDecisionKind.ESCALATE_REQUIRED,
                    explanation=f"policy 评估失败: {err}",
                    target_action="escalate",
                )
            ]

        # 4. 构造结果
        evaluation = PolicyEvaluation(
            status=evaluation_status,
            decisions=decisions,
            packet=packet,
            context_snapshot=ctx,
        )

        # 5. 可选: 落 events 表
        if store is not None:
            event_id = self._emit_decision_event(
                evaluation,
                store,
                lane_entry_id=lane_entry_id,
                run_id=run_id,
                extra_business_payload=extra_business_payload,
            )
            evaluation.event_id = event_id

        return evaluation

    # ===== 6 决策规则 =====

    def _run_all_rules(self, packet: TaskPacket, ctx: dict[str, Any]) -> list[PolicyDecision]:
        """跑 6 rule, 按 priority 降序排."""
        rules: list[Callable[[], PolicyDecision | None]] = [
            lambda: self._rule_retry_available(ctx),
            lambda: self._rule_rebase_required(ctx),
            lambda: self._rule_stale_cleanup_required(ctx),
            lambda: self._rule_approval_token_required(packet, ctx),
            lambda: self._rule_merge_required(ctx),
            lambda: self._rule_escalate_required(ctx),
        ]
        decisions: list[PolicyDecision] = []
        for rule in rules:
            decision = rule()
            if decision is not None:
                decisions.append(decision)
        # 按 priority 降序
        decisions.sort(key=lambda d: d.priority, reverse=True)
        return decisions

    def _rule_retry_available(self, ctx: dict[str, Any]) -> PolicyDecision | None:
        """Rule 1: RetryAvailable — recoverable error + attempts < max."""
        recoverable = ctx.get("last_error_recoverable", False)
        attempts = ctx.get("current_attempts", 0)
        max_attempts = ctx.get("max_attempts", 3)
        if recoverable and attempts < max_attempts:
            return PolicyDecision(
                rule_name=PolicyDecisionKind.RETRY_AVAILABLE.value,
                priority=70,
                kind=PolicyDecisionKind.RETRY_AVAILABLE,
                explanation=(
                    f"上次错误可恢复(recoverable=True), "
                    f"已重试 {attempts}/{max_attempts} 次, 可继续重试"
                ),
                target_action="retry",
            )
        return None

    def _rule_rebase_required(self, ctx: dict[str, Any]) -> PolicyDecision | None:
        """Rule 2: RebaseRequired — branch stale."""
        if ctx.get("branch_stale", False):
            return PolicyDecision(
                rule_name=PolicyDecisionKind.REBASE_REQUIRED.value,
                priority=60,
                kind=PolicyDecisionKind.REBASE_REQUIRED,
                explanation="branch 已 stale(落后 main), 需先 rebase 再继续",
                target_action="rebase",
            )
        return None

    def _rule_stale_cleanup_required(self, ctx: dict[str, Any]) -> PolicyDecision | None:
        """Rule 3: StaleCleanupRequired — heartbeat 超过阈值未更新."""
        last_hb = ctx.get("last_heartbeat_ms", 0)
        threshold = ctx.get("stale_threshold_ms", 60_000)
        now = ctx.get("now_ms", 0) or int(time.time() * 1000)
        if last_hb > 0 and (now - last_hb) > threshold:
            idle_seconds = (now - last_hb) // 1000
            threshold_seconds = threshold // 1000
            return PolicyDecision(
                rule_name=PolicyDecisionKind.STALE_CLEANUP_REQUIRED.value,
                priority=50,
                kind=PolicyDecisionKind.STALE_CLEANUP_REQUIRED,
                explanation=(
                    f"heartbeat 停滞 {idle_seconds}s (阈值 {threshold_seconds}s), 需清理 stale 状态"
                ),
                target_action="stale_cleanup",
            )
        return None

    def _rule_approval_token_required(
        self, packet: TaskPacket, ctx: dict[str, Any]
    ) -> PolicyDecision | None:
        """Rule 4: ApprovalTokenRequired — 敏感操作 / 高权限 + 缺 token."""
        sensitive = ctx.get("action_sensitive", False)
        has_token = ctx.get("has_approval_token", False)
        # 权限 ≥ READ_WRITE 的操作被视为潜在敏感(需审批)
        profile = packet.permission_profile
        high_privilege = profile in ("read_write", "admin")
        if (sensitive or high_privilege) and not has_token:
            return PolicyDecision(
                rule_name=PolicyDecisionKind.APPROVAL_TOKEN_REQUIRED.value,
                priority=80,
                kind=PolicyDecisionKind.APPROVAL_TOKEN_REQUIRED,
                explanation=(
                    f"操作需审批 token(permission_profile={profile}, "
                    f"action_sensitive={sensitive}), 当前 has_approval_token=False"
                ),
                target_action="request_approval",
                approval_token_id=ctx.get("approval_token_id", ""),
            )
        return None

    def _rule_merge_required(self, ctx: dict[str, Any]) -> PolicyDecision | None:
        """Rule 5: MergeRequired — 全部 acceptance criteria passed."""
        results = ctx.get("acceptance_results", [])
        if results and all(results):
            return PolicyDecision(
                rule_name=PolicyDecisionKind.MERGE_REQUIRED.value,
                priority=40,
                kind=PolicyDecisionKind.MERGE_REQUIRED,
                explanation=(f"全部 {len(results)} 个 acceptance criteria 通过, 可合并"),
                target_action="merge",
            )
        return None

    def _rule_escalate_required(self, ctx: dict[str, Any]) -> PolicyDecision | None:
        """Rule 6: EscalateRequired — 不可恢复 / 评估失败."""
        if ctx.get("policy_eval_failed", False):
            return PolicyDecision(
                rule_name=PolicyDecisionKind.ESCALATE_REQUIRED.value,
                priority=100,
                kind=PolicyDecisionKind.ESCALATE_REQUIRED,
                explanation="policy 评估失败 / 不可恢复错误, 需人工升级",
                target_action="escalate",
            )
        return None

    # ===== context 归一 =====

    def _normalize_context(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """归一 context, 缺字段填合理 defaults.

        严格化(D4.4 P1 修复): 拒绝 type-coerce 兜底(Python `bool("false")==True`,
        `all(["false"])` 也是 True, 会让字符串 JSON 输入触发错误决策). 严格解析:
          - bool 字段: 必须原生 `bool`, 拒绝 str/int/list
          - int 字段: 必须原生 `int` (排除 bool 子类), 拒绝 str/float
          - str 字段: 必须原生 `str`
          - list 字段: 必须 `list`, 元素必须 `bool`

        失败抛 `PolicyDecisionError` (透传, caller 责任 — D3.3.3 异常窄化教训).
        """
        if not isinstance(ctx, dict):
            raise PolicyDecisionError(f"context 必须是 dict, 实际 {type(ctx).__name__}")

        def _strict_bool(v: Any, field: str) -> bool:
            if type(v) is not bool:  # 排除 int 子类陷阱 (True is int=False)
                raise PolicyDecisionError(
                    f"context.{field} 必须是 bool, 得到 {type(v).__name__}={v!r}"
                )
            return v

        def _strict_int(v: Any, field: str, *, min_value: int = 0) -> int:
            if type(v) is not int:  # type() is int 排除 bool 子类 (True/False)
                raise PolicyDecisionError(
                    f"context.{field} 必须是 int, 得到 {type(v).__name__}={v!r}"
                )
            if v < min_value:
                raise PolicyDecisionError(f"context.{field} 必须 >= {min_value}, 得到 {v}")
            return v

        def _strict_str(v: Any, field: str) -> str:
            if type(v) is not str:
                raise PolicyDecisionError(
                    f"context.{field} 必须是 str, 得到 {type(v).__name__}={v!r}"
                )
            return v

        def _strict_list_bool(v: Any, field: str) -> list[bool]:
            if not isinstance(v, list):
                raise PolicyDecisionError(f"context.{field} 必须是 list, 得到 {type(v).__name__}")
            if not all(type(x) is bool for x in v):
                bad = [type(x).__name__ for x in v if type(x) is not bool]
                raise PolicyDecisionError(f"context.{field} 必须全为 bool, 收到非 bool 元素: {bad}")
            return v

        # 缺字段 sentinel 模式: ctx.get(k, _MISSING) → 走 strict 解析 (_MISSING 不通过严判)
        # (避免 `ctx[k] if k in ctx else default` 触发 ruff SIM401)
        missing_marker: Any = object()

        def _get_or(k: str, default: Any) -> Any:
            v = ctx.get(k, missing_marker)
            return default if v is missing_marker else v

        # 注意: 缺字段用 Python 字面量 default (False/0/3/60000/""/[]), 这些都通过严判
        return {
            "last_error_recoverable": _strict_bool(
                _get_or("last_error_recoverable", False),
                "last_error_recoverable",
            ),
            "current_attempts": _strict_int(
                _get_or("current_attempts", 0),
                "current_attempts",
                min_value=0,
            ),
            "max_attempts": _strict_int(
                _get_or("max_attempts", 3),
                "max_attempts",
                min_value=1,  # 防 attempts<max 永真
            ),
            "branch_stale": _strict_bool(
                _get_or("branch_stale", False),
                "branch_stale",
            ),
            "last_heartbeat_ms": _strict_int(
                _get_or("last_heartbeat_ms", 0),
                "last_heartbeat_ms",
                min_value=0,
            ),
            "stale_threshold_ms": _strict_int(
                _get_or("stale_threshold_ms", 60_000),
                "stale_threshold_ms",
                min_value=0,
            ),
            "now_ms": _strict_int(
                _get_or("now_ms", 0),
                "now_ms",
                min_value=0,
            ),
            "action_sensitive": _strict_bool(
                _get_or("action_sensitive", False),
                "action_sensitive",
            ),
            "has_approval_token": _strict_bool(
                _get_or("has_approval_token", False),
                "has_approval_token",
            ),
            "approval_token_id": _strict_str(
                _get_or("approval_token_id", ""),
                "approval_token_id",
            ),
            "acceptance_results": _strict_list_bool(
                _get_or("acceptance_results", []),
                "acceptance_results",
            ),
            "policy_eval_failed": _strict_bool(
                _get_or("policy_eval_failed", False),
                "policy_eval_failed",
            ),
        }

    # ===== 事件 emit =====

    def _emit_decision_event(
        self,
        evaluation: PolicyEvaluation,
        store: Any,
        *,
        lane_entry_id: str = "",
        run_id: str = "",
        extra_business_payload: dict[str, Any] | None = None,
    ) -> int:
        """落 1 条 PolicyDecisionEvent 到 events 表.

        Args:
            evaluation: 已计算好的 PolicyEvaluation
            store: EventStore 实例(D4.3 events/store.py)
            lane_entry_id: LaneBoard entry id(写进 event_metadata, 便于 history 串联)
            run_id: 单次评估 run id(写进 event_metadata, 与 lane_entry_id 配对)
            extra_business_payload: 可选 — 业务层透传字段(D4.6 新增),合并到
                event_metadata 顶层(与 lane_entry_id / run_id 同一级)。D4.3.2
                决策:`build_event_metadata` `meta.update(extra)`,所以业务字段
                也走"6 必含 + 业务 payload"扩展模式。EmailClassifierAdapter
                传 5 字段(category / confidence / model_full_id / email_id / source)。

        Returns:
            落地事件的 id(EventStore.insert() 返回)

        Raises:
            EventContractError / EventMetadataError: events/store 内部(透传)
            AttributeError: store 不是 EventStore(透传)
        """
        # 1. 构造 extra payload
        decisions_dict = [d.to_dict() for d in evaluation.decisions]
        primary = decisions_dict[0] if decisions_dict else None
        extra_payload: dict[str, Any] = {
            "rule_name": primary["rule_name"] if primary else "none",
            "priority": primary["priority"] if primary else 0,
            "kind": primary["kind"] if primary else "none",
            "explanation": primary["explanation"] if primary else "no decisions",
            "approval_token_id": primary["approval_token_id"] if primary else "",
            "all_decisions": decisions_dict,
            "context_snapshot": evaluation.context_snapshot,
            "lane_entry_id": lane_entry_id,  # D4.5 v1.0.1: 便于 mmx policy history --lane
            "run_id": run_id,  # D4.5 v1.0.1: 与 lane_entry_id 配对
        }
        # 1.5 业务层透传字段合并(D4.6 新增,EmailClassifierAdapter 透传
        #     category/confidence/model_full_id/email_id/source 5 项)。
        #     业务字段不覆盖 9 个 policy 标准字段(优先级 = 业务字段后写,
        #     但如果业务字段 key 冲突则记录 warning 并保留 policy 标准字段值)。
        if extra_business_payload:
            reserved = set(extra_payload.keys())
            for k, v in extra_business_payload.items():
                if k in reserved:
                    # 业务字段与 policy 标准字段冲突 → 保留 policy 值, 静默跳过
                    # (D3.3.3 教训: 不抛业务异常, 避免破坏 evaluate 主流程)
                    continue
                extra_payload[k] = v
        # 2. 选事件 type: succeeded → POLICY_DECISION_MADE, failed → POLICY_DECISION_DEGRADED
        event_type = (
            EventType.POLICY_DECISION_MADE
            if evaluation.status == EventStatus.SUCCEEDED.value
            else EventType.POLICY_DECISION_DEGRADED
        )
        # 3. 用 EventStore.insert 走 D4.3 完整契约
        event = store.insert(
            event=event_type,
            status=evaluation.status,
            source="policy_engine",
            subject_id=(evaluation.packet.objective[:32] if evaluation.packet else None),
            seq=0,
            session_id="policy_engine",
            ownership=EventOwnership.ACT,
            provenance=EventProvenance.LIVE,
            extra=extra_payload,
        )
        return event.id if event.id is not None else 0


# ===== Singleton =====


_engine: PolicyEngine | None = None


def get_engine() -> PolicyEngine:
    """获取单例 PolicyEngine(进程级)."""
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine


# ===== 模块导出 =====


__all__ = [
    "PolicyDecision",
    "PolicyDecisionKind",
    "PolicyEvaluation",
    "PolicyEngine",
    "get_engine",
]
