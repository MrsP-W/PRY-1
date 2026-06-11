"""D4.8 — EmailOutboxAdapter: outbox 入库业务层接入适配器.

承接 D4.8.1 outbox migration 0004(11 字段 + UNIQUE + 2 索引 + 2 FK)
+ D4.8.2 OutboxEntry ORM + 3 个 StrEnum 枚举
+ D4.8.3 OutboxStore(4 公共方法 + IntegrityError 窄化 + OutboxEmailDuplicateError).

D4.8 5 项契约(2026-06-10 用户审批):
    1. 三入口架构(沿用 D4.7.3 v1.0.1 P1-1 范本):
       - store_and_emit(成功,outbox_stored=True) → OutboxDecisionReport
       - record_store_business_blocked_and_emit(业务阻断,2 类白名单) → OutboxBlockedDecisionReport
       - record_store_failure_and_emit(技术失败,SQL 异常) → OutboxFailureDecisionReport
    2. outbox 表 schema 11 字段(D4.8.1 migration)
    3. **PermissionProfile = READ_WRITE**(D4.8 首次引入,业务层 build_outbox_packet 设置)
    4. 入库幂等性(UNIQUE(email_id) 冲突 → 业务阻断入口,D3.3.3 异常窄化教训应用)
    5. 不真发 SMTP(避免 D4.8 越界,D5+ 业务调度器接管)

D4.7.3 + D4.7.4 25 教训 + 7 项核心契约全应用:
    1. 工厂层 + __post_init__ 双层防御
    2. 跨字段校验(reason=duplicate_email_id → email_id 必填非负)
    3. 双向强一致(outbox_stored=True → outbox_id >= 1 / last_outbox_failed ↔ cf)
    4. 异常统一 ValueError
    5. 字段名硬区分(blocked vs failed + kind)
    6. 契约 helper 复用(_validate_outbox_* 公共入口)
    7. 固化哲学(代码+注释+测试+导出+文档同 commit)

D3.3.3 异常窄化教训应用:
    - OutboxStore.insert 严格 except IntegrityError(UNIQUE 冲突 → 业务阻断)
    - 其他 OperationalError / DataError / InterfaceError 透传,Adapter 走 record_store_failure_and_emit
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from my_ai_employee.core.outbox import (
    _OUTBOX_PRIORITY_CHOICES,
    OutboxEntry,
    OutboxStatus,
)
from my_ai_employee.db.outbox import OutboxStore
from my_ai_employee.policy.heartbeat import Heartbeat, Liveness

# 复用 D4.7.3 + D4.7.4 严判范本(D4.8 OutboxTone 字段值与 DraftTone 一致)
from my_ai_employee.policy.integration import (
    _validate_draft_tone,
)
from my_ai_employee.policy.lane_board import LaneBoard, LaneEntry, LaneStatus
from my_ai_employee.policy.policy_engine import PolicyEngine, PolicyEvaluation
from my_ai_employee.policy.task_packet import PermissionProfile, TaskPacket

# ===== 6 个 _validate_outbox_* 严判 helper(D4.7.3 25 教训应用)=====

# 业务阻断 reason 白名单(D4.8 契约 1 — 业务阻断入口 2 类)
OUTBOX_BLOCK_REASON_VALUES: frozenset[str] = frozenset(
    {
        "duplicate_email_id",  # UNIQUE(email_id) 冲突(D4.8 契约 4 幂等性)
        "blacklisted_recipient",  # 收件人在黑名单(D5+ 接入 blacklist_recipients 配置表)
    }
)

# 字段边界(week1-mvp.md:877 锁定)
_OUTBOX_SUBJECT_MIN = 1
_OUTBOX_SUBJECT_MAX = 200
_OUTBOX_BODY_MIN = 10
_OUTBOX_BODY_MAX = 8000


def _validate_outbox_email_id(email_id: Any) -> int:
    """严判 email_id(int 拒 bool,>= 0, 契约 4 联动 reason=duplicate_email_id 必非负).

    D4.7.3 v1.0.4 P2-2 范本: type() is bool 检查在 isinstance 之前,
    拒 bool 子类(isinstance(True, int)==True 陷阱).
    """
    if type(email_id) is bool or not isinstance(email_id, int) or email_id < 0:
        raise ValueError(
            f"email_id 必须是原生 int(非 bool) >= 0, 实际 {type(email_id).__name__}={email_id!r}"
        )
    return email_id


def _validate_outbox_subject(subject: Any) -> str:
    """严判 subject(1-200 字符,strip() 后非空, D4.7.3 v1.0.4 P2-4 范本).

    拒绝:
        - None / 非 str 类型
        - 空字符串 / 纯空白("   ")
        - > 200 字符
    """
    if type(subject) is not str:
        raise ValueError(f"subject 必须是 str, 实际 {type(subject).__name__}={subject!r}")
    stripped = subject.strip()
    if not stripped:
        raise ValueError(f"subject 必填非空白(strip() 非空), 实际 {subject!r}")
    if not (_OUTBOX_SUBJECT_MIN <= len(subject) <= _OUTBOX_SUBJECT_MAX):
        raise ValueError(
            f"subject 长度必须在 [{_OUTBOX_SUBJECT_MIN}, {_OUTBOX_SUBJECT_MAX}] 区间, "
            f"实际 len={len(subject)}"
        )
    return subject


def _validate_outbox_body(body: Any) -> str:
    """严判 body(10-8000 字符, strip() 后非空, 复用 drafter 契约 1 边界)."""
    if type(body) is not str:
        raise ValueError(f"body 必须是 str, 实际 {type(body).__name__}={body!r}")
    stripped = body.strip()
    if not stripped:
        raise ValueError(f"body 必填非空白(strip() 非空), 实际 {body!r}")
    if not (_OUTBOX_BODY_MIN <= len(body) <= _OUTBOX_BODY_MAX):
        raise ValueError(
            f"body 长度必须在 [{_OUTBOX_BODY_MIN}, {_OUTBOX_BODY_MAX}] 区间, 实际 len={len(body)}"
        )
    return body


def _validate_outbox_recipient_email(recipient: Any) -> str:
    """严判 recipient_email(简单含 @ 检查, D5+ 接 SMTP 时再加完整 RFC 5322 校验).

    拒绝:
        - None / 非 str 类型
        - 空字符串 / 纯空白
        - 不含 '@' 字符
    """
    if type(recipient) is not str:
        raise ValueError(
            f"recipient_email 必须是 str, 实际 {type(recipient).__name__}={recipient!r}"
        )
    stripped = recipient.strip()
    if not stripped:
        raise ValueError(f"recipient_email 必填非空白(strip() 非空), 实际 {recipient!r}")
    if "@" not in recipient:
        raise ValueError(f"recipient_email 必须含 '@' 字符, 实际 {recipient!r}")
    return recipient


def _validate_outbox_priority(priority: Any) -> str:
    """严判 priority(OutboxPriority 3 选 1, D4.7.3 v1.0.5 P2-1 范本: type 严判在 hash 前)."""
    if type(priority) is not str:
        raise ValueError(f"priority 必须是 str, 实际 {type(priority).__name__}={priority!r}")
    if priority not in _OUTBOX_PRIORITY_CHOICES:
        raise ValueError(
            f"priority 必须是 OutboxPriority 3 选 1 {_OUTBOX_PRIORITY_CHOICES!r}, 实际 {priority!r}"
        )
    return priority


def _validate_outbox_block_reason(reason: Any) -> str:
    """严判 block_reason(2 类白名单, D4.7.3 v1.0.5 P2-1 范本)."""
    if type(reason) is not str:
        raise ValueError(f"block_reason 必须是 str, 实际 {type(reason).__name__}={reason!r}")
    if reason not in OUTBOX_BLOCK_REASON_VALUES:
        raise ValueError(
            f"block_reason 必须是 2 类白名单 {OUTBOX_BLOCK_REASON_VALUES!r}, 实际 {reason!r}"
        )
    return reason


# ===== compute_outbox_acceptance(3 条 AC 契约描述)=====


def compute_outbox_acceptance(
    *,
    subject_length: int,
    body_length: int,
    recipient_email: str,
) -> list[bool]:
    """计算 outbox 入库的 3 条 AC(D4.8 业务验收契约).

    Args:
        subject_length: len(subject) — 严判范围 [1, 200]
        body_length: len(body) — 严判范围 [10, 8000]
        recipient_email: 已 strip 校验非空, 仅校验含 @

    Returns:
        3 个 bool: [subject 边界, body 边界, recipient_email 含 @]

    Raises:
        ValueError: subject_length / body_length 类型非法
    """
    if type(subject_length) is bool or not isinstance(subject_length, int) or subject_length < 0:
        raise ValueError(
            f"subject_length 必须是原生 int(非 bool) >= 0, 实际 "
            f"{type(subject_length).__name__}={subject_length!r}"
        )
    if type(body_length) is bool or not isinstance(body_length, int) or body_length < 0:
        raise ValueError(
            f"body_length 必须是原生 int(非 bool) >= 0, 实际 "
            f"{type(body_length).__name__}={body_length!r}"
        )
    return [
        _OUTBOX_SUBJECT_MIN <= subject_length <= _OUTBOX_SUBJECT_MAX,
        _OUTBOX_BODY_MIN <= body_length <= _OUTBOX_BODY_MAX,
        "@" in recipient_email,
    ]


# ===== 3 个 build_outbox_* packet 工厂 =====


def build_outbox_packet(
    *,
    email_id: int,
    source: str,
    tone: str,
    subject_length: int,
) -> TaskPacket:
    """构造 outbox 入库的 TaskPacket(D4.8 契约 3 — PermissionProfile = READ_WRITE).

    D4.8 首次引入 READ_WRITE 权限(写入 outbox 表需要),
    与 D4.5/D4.6/D4.7.3/D4.7.4 的 read_only 区分。
    """
    return TaskPacket(
        objective=f"outbox 入库 email_id={email_id} source={source}",
        scope=["outbox.store"],
        resources=["core/models/outbox.py", "db/outbox.py"],
        acceptance_criteria=[
            f"subject_length 1-200 (实际 {subject_length})",
            "body_length 10-8000",
            "recipient_email 含 @",
        ],
        model="outbox-store",
        provider="internal",
        permission_profile=PermissionProfile.READ_WRITE.value,  # D4.8 首次引入
        recovery_policy="manual",  # UNIQUE 冲突 → 业务阻断,不入技术失败重试
    )


def build_outbox_blocked_packet(
    *,
    email_id: int,
    source: str,
    reason: str,
) -> TaskPacket:
    """构造 outbox 业务阻断的 TaskPacket(走 record_store_business_blocked_and_emit)."""
    return TaskPacket(
        objective=f"outbox 业务阻断 email_id={email_id} reason={reason}",
        scope=["outbox.store.business_blocked"],
        resources=["core/models/outbox.py"],
        acceptance_criteria=[
            f"reason 必为 2 类白名单(实际 {reason})",
            "blocked: Literal[True]",
            "kind=Literal['business_blocked']",
        ],
        model="outbox-store-blocked",
        provider="internal",
        permission_profile=PermissionProfile.READ_ONLY.value,  # 业务阻断不改库
        recovery_policy="none",  # 业务阻断永不重试(D4.8 v1.0.1 修复:task_packet 白名单内)
    )


def build_outbox_failure_packet(
    *,
    email_id: int,
    source: str,
    consecutive_outbox_failures: int,
) -> TaskPacket:
    """构造 outbox 技术失败的 TaskPacket(走 record_store_failure_and_emit,cf 必填)."""
    return TaskPacket(
        objective=f"outbox 技术失败 email_id={email_id} cf={consecutive_outbox_failures}",
        scope=["outbox.store.failure"],
        resources=["db/outbox.py"],
        acceptance_criteria=[
            f"cf >= 1 (实际 {consecutive_outbox_failures})",
            "failed: Literal[True]",
            "last_error.strip() 非空",
        ],
        model="outbox-store-failure",
        provider="internal",
        permission_profile=PermissionProfile.READ_ONLY.value,
        recovery_policy="retry_on_transient",  # 技术失败可重试(D4.8 v1.0.1 修复:task_packet 白名单内)
    )


def build_outbox_policy_context(
    *,
    email_id: int,
    tone: str,
    priority: str,
    subject_length: int,
    body_length: int,
    last_outbox_failed: bool,
    consecutive_outbox_failures: int,
    now_ms: int,
) -> dict[str, Any]:
    """构造 outbox 决策 context(7 字段 + 双向强一致).

    双向强一致(D4.7.3 v1.0.2 P1-2 范本):
        - last_outbox_failed=True → cf >= 1
        - last_outbox_failed=False → cf == 0
    """
    # type 严判在 hash 前(D4.7.3 v1.0.5 P2-1 范本)
    if type(last_outbox_failed) is not bool:
        raise ValueError(
            f"last_outbox_failed 必须是原生 bool, 实际 "
            f"{type(last_outbox_failed).__name__}={last_outbox_failed!r}"
        )
    if type(consecutive_outbox_failures) is bool or not isinstance(
        consecutive_outbox_failures, int
    ):
        raise ValueError(
            f"consecutive_outbox_failures 必须是原生 int(非 bool), 实际 "
            f"{type(consecutive_outbox_failures).__name__}={consecutive_outbox_failures!r}"
        )
    if last_outbox_failed and consecutive_outbox_failures < 1:
        raise ValueError(
            f"双向强一致: last_outbox_failed=True → cf >= 1, "
            f"实际 last_outbox_failed={last_outbox_failed} cf={consecutive_outbox_failures}"
        )
    if not last_outbox_failed and consecutive_outbox_failures != 0:
        raise ValueError(
            f"双向强一致: last_outbox_failed=False → cf == 0, "
            f"实际 last_outbox_failed={last_outbox_failed} cf={consecutive_outbox_failures}"
        )
    return {
        "email_id": email_id,
        "tone": tone,
        "priority": priority,
        "subject_length": subject_length,
        "body_length": body_length,
        "last_outbox_failed": last_outbox_failed,
        "consecutive_outbox_failures": consecutive_outbox_failures,
        "now_ms": now_ms,
    }


# ===== 3 个 DecisionReports(成功 / 业务阻断 / 技术失败,字段名级别硬区分)=====


@dataclass(frozen=True)
class OutboxDecisionReport:
    """D4.8 业务层接入的可观测报告(成功入库版本).

    字段契约(week1-mvp.md:860 锁定 6 字段透传):
        - outbox_id / subject_length / body_length / tone / recipient_email / priority

    跨字段强一致(契约 helper 复用,D4.7.3 v1.0.2 P1-2 范本):
        - outbox_stored=True → outbox_id >= 1

    Attributes:
        evaluation: PolicyEngine.evaluate() 完整结果
        event_id: 落地到 events 表的 PolicyDecisionEvent id
        lane_entry_id: LaneBoard 中本次入库的 entry_id(命名 outbox:<source>:<run_id>)
        liveness: Heartbeat 评估的 Liveness
        outbox_stored: Literal[True](成功入库专属)
        outbox_id: 入库后的 PK id(>= 1)
        email_id: 邮件主键(>= 0)
        subject: 已严判 1-200 字符
        body: 已严判 10-8000 字符
        tone: OutboxTone 3 选 1
        recipient_email: 含 @ 的字符串
        priority: OutboxPriority 3 选 1
        subject_length: len(subject)
        body_length: len(body)
        latency_ms: 入库耗时(>= 0)
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    outbox_id: int  # 跨字段强一致: outbox_stored=True → outbox_id >= 1
    email_id: int  # 关联 emails.id
    subject: str
    body: str
    tone: str  # OutboxTone 3 选 1
    recipient_email: str
    priority: str  # OutboxPriority 3 选 1
    subject_length: int = 0  # 兼容旧调用
    body_length: int = 0
    latency_ms: int = 0
    # 字段名硬区分(D4.7.3 v1.0.3 P2-1 范本,成功入库专属)
    outbox_stored: Literal[True] = True

    def __post_init__(self) -> None:
        """D4.8 字段契约自洽校验(7 项核心契约 + 11 字段透传)."""
        if self.outbox_stored is not True:
            raise ValueError(
                f"OutboxDecisionReport.outbox_stored 必为 True "
                f"(D4.8 Literal[True] 类型层面固化, 成功入库专属), "
                f"实际 {self.outbox_stored!r}"
            )
        if (
            type(self.outbox_id) is bool
            or not isinstance(self.outbox_id, int)
            or self.outbox_id < 1
        ):
            raise ValueError(
                f"OutboxDecisionReport.outbox_id 必须是 int(非 bool) >= 1, 实际 "
                f"{type(self.outbox_id).__name__}={self.outbox_id!r}"
            )
        _validate_outbox_email_id(self.email_id)
        _validate_outbox_subject(self.subject)
        _validate_outbox_body(self.body)
        _validate_draft_tone(self.tone)  # OutboxTone 字段值与 DraftTone 一致
        _validate_outbox_recipient_email(self.recipient_email)
        _validate_outbox_priority(self.priority)
        # 双向强一致(D4.7.3 v1.0.2 P1-2 范本)
        if (
            type(self.subject_length) is bool
            or not isinstance(self.subject_length, int)
            or self.subject_length < 0
        ):
            raise ValueError(
                f"OutboxDecisionReport.subject_length 必须是 int(非 bool) >= 0, 实际 "
                f"{type(self.subject_length).__name__}={self.subject_length!r}"
            )
        if (
            type(self.body_length) is bool
            or not isinstance(self.body_length, int)
            or self.body_length < 0
        ):
            raise ValueError(
                f"OutboxDecisionReport.body_length 必须是 int(非 bool) >= 0, 实际 "
                f"{type(self.body_length).__name__}={self.body_length!r}"
            )
        if (
            type(self.latency_ms) is bool
            or not isinstance(self.latency_ms, int)
            or self.latency_ms < 0
        ):
            raise ValueError(
                f"OutboxDecisionReport.latency_ms 必须是 int(非 bool) >= 0, 实际 "
                f"{type(self.latency_ms).__name__}={self.latency_ms!r}"
            )


@dataclass(frozen=True)
class OutboxBlockedDecisionReport:
    """D4.8 业务层接入的可观测报告(业务阻断版本).

    D4.7.4 + D4.7.3 范本(沿用 25 教训):
        - blocked: Literal[True](业务阻断专属字段名, 不可与 failed 混用)
        - kind: Literal["business_blocked"](与 OutboxFailureDecisionReport 区分)
        - reason: 2 类白名单(week1-mvp.md:847 锁定)
        - last_error: 阻断原因描述(必填非空)
        - consecutive_outbox_failures: 必为 0(业务阻断不计入失败累加器)
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    last_error: str  # 必填非空
    reason: str  # 2 类白名单
    email_id: int  # 跨字段 reason=duplicate_email_id → email_id 必非负
    subject: str
    body: str
    tone: str
    recipient_email: str
    # 业务阻断不计入失败累加器
    consecutive_outbox_failures: int = 0
    # 字段名硬区分(D4.7.3 v1.0.3 P2-1 范本)
    blocked: Literal[True] = True
    kind: Literal["business_blocked"] = "business_blocked"

    def __post_init__(self) -> None:
        """D4.8 业务阻断字段契约校验(7 项核心契约 + 2 类白名单)."""
        if self.blocked is not True:
            raise ValueError(
                f"OutboxBlockedDecisionReport.blocked 必为 True, 实际 {self.blocked!r}"
            )
        if self.kind != "business_blocked":
            raise ValueError(
                f"OutboxBlockedDecisionReport.kind 必为 'business_blocked', 实际 {self.kind!r}"
            )
        if type(self.last_error) is not str or not self.last_error.strip():
            raise ValueError(
                f"OutboxBlockedDecisionReport.last_error 必填非空白 str, 实际 "
                f"{type(self.last_error).__name__}={self.last_error!r}"
            )
        _validate_outbox_block_reason(self.reason)
        _validate_outbox_email_id(self.email_id)
        # 跨字段 reason=duplicate_email_id → email_id 必非负(已 _validate_outbox_email_id 严判)
        if self.reason == "duplicate_email_id" and self.email_id < 0:
            raise ValueError(
                f"跨字段: reason=duplicate_email_id → email_id 必须 >= 0, "
                f"实际 email_id={self.email_id}"
            )
        _validate_outbox_subject(self.subject)
        _validate_outbox_body(self.body)
        _validate_draft_tone(self.tone)
        _validate_outbox_recipient_email(self.recipient_email)
        # 业务阻断 cf 必为 0(D4.7.3 v1.0.1 P1-1 范本:业务阻断 ≠ 技术失败)
        if self.consecutive_outbox_failures != 0:
            raise ValueError(
                f"OutboxBlockedDecisionReport.consecutive_outbox_failures 业务阻断必为 0, "
                f"实际 {self.consecutive_outbox_failures}"
            )


@dataclass(frozen=True)
class OutboxFailureDecisionReport:
    """D4.8 业务层接入的可观测报告(技术失败版本).

    字段名硬区分(D4.7.3 v1.0.3 P2-1 范本):
        - failed: Literal[True](技术失败专属字段名, 不可与 blocked 混用)
    双向强一致(D4.7.3 v1.0.2 P1-2 范本):
        - last_outbox_failed=True ↔ cf >= 1
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    last_error: str  # 必填非空(Exception 喂入后 strip() 严判)
    email_id: int  # 关联 emails.id
    subject: str
    body: str
    tone: str
    recipient_email: str
    consecutive_outbox_failures: int = 0  # 双向强一致
    # 字段名硬区分(D4.7.3 v1.0.3 P2-1 范本,技术失败专属)
    failed: Literal[True] = True

    def __post_init__(self) -> None:
        """D4.8 技术失败字段契约校验(7 项核心契约)."""
        if self.failed is not True:
            raise ValueError(f"OutboxFailureDecisionReport.failed 必为 True, 实际 {self.failed!r}")
        if type(self.last_error) is not str or not self.last_error.strip():
            raise ValueError(
                f"OutboxFailureDecisionReport.last_error 必填非空白 str, 实际 "
                f"{type(self.last_error).__name__}={self.last_error!r}"
            )
        if (
            type(self.consecutive_outbox_failures) is bool
            or not isinstance(self.consecutive_outbox_failures, int)
            or self.consecutive_outbox_failures < 1
        ):
            raise ValueError(
                f"OutboxFailureDecisionReport.consecutive_outbox_failures 必须是 int(非 bool) >= 1, "
                f"实际 {type(self.consecutive_outbox_failures).__name__}={self.consecutive_outbox_failures!r}"
            )
        _validate_outbox_email_id(self.email_id)
        _validate_outbox_subject(self.subject)
        _validate_outbox_body(self.body)
        _validate_draft_tone(self.tone)
        _validate_outbox_recipient_email(self.recipient_email)


# ===== EmailOutboxAdapter 主类(5 依赖可注入, 三入口)=====


class EmailOutboxAdapter:
    """D4.8 业务层接入适配器 — outbox 入库 接入 PolicyEngine 5 件套.

    复用 D4.7.3 + D4.7.4 范本(5 依赖可注入 + 三入口架构):
        - source: 数据源头(必填非空白)
        - outbox_store: OutboxStore(D4.8.3 4 公共方法 + IntegrityError 窄化)
        - engine: PolicyEngine(D4.4 决策引擎)
        - heartbeat: Heartbeat(LLM 探活)
        - board: LaneBoard(入库任务看板)

    三入口互斥(D4.7.3 v1.0.1 P1-1 拆分):
        - store_and_emit(成功, outbox_stored=True) → OutboxDecisionReport
        - record_store_business_blocked_and_emit(业务阻断, 2 类白名单) → OutboxBlockedDecisionReport
        - record_store_failure_and_emit(技术失败, SQL 异常) → OutboxFailureDecisionReport

    lane_entry_id 命名: outbox:<source>:<run_id>(与 classify: / sync: / draft: / review: 区分)
    """

    def __init__(
        self,
        *,
        source: str,
        outbox_store: OutboxStore | None = None,
        engine: PolicyEngine | None = None,
        heartbeat: Heartbeat | None = None,
        board: LaneBoard | None = None,
    ) -> None:
        # D4.7.3 v1.0.5 P2-2 范本: source 严判 strip() 语义非空
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                f"source 必填非空白 str(strip() 非空), 实际 {type(source).__name__}={source!r}"
            )
        self._source = source
        self._outbox_store = outbox_store
        # D4.7.3 v1.0.3 P2-2 范本: is None 范式(保留 falsey 替身)
        self._engine = engine if engine is not None else PolicyEngine()
        self._heartbeat = (
            heartbeat if heartbeat is not None else Heartbeat(idle_threshold_ms=30_000)
        )
        self._board = board if board is not None else LaneBoard(idle_threshold_ms=60_000)
        # D4.8 首次引入: 默认 EventStore=None(由 caller 注入,D4.8.6/7 单元测试用 FakeEventStore)

    def build_lane_entry_id(self, run_id: str) -> str:
        """生成 LaneBoard entry_id: 'outbox:<source>:<run_id>'."""
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError(
                f"run_id 必填非空白 str(strip() 非空), 实际 {type(run_id).__name__}={run_id!r}"
            )
        return f"outbox:{self._source}:{run_id}"

    # ===== 入口 1: 成功入库 =====

    def store_and_emit(
        self,
        *,
        email_id: int,
        subject: str,
        body: str,
        tone: str,
        recipient_email: str,
        priority: str = "normal",
        reviewer_decision_event_id: int | None = None,
        drafter_decision_event_id: int | None = None,
        transport_alive: bool = True,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> OutboxDecisionReport:
        """成功入库入口(对应契约 1 成功路径).

        Args:
            email_id: 关联 emails.id(>= 0,严判)
            subject: 草稿主题(1-200 字符,strip 非空)
            body: 草稿正文(10-8000 字符,strip 非空)
            tone: OutboxTone 3 选 1
            recipient_email: 含 @ 字符串
            priority: OutboxPriority 3 选 1,默认 "normal"
            reviewer_decision_event_id: FK → events.id(D4.7.4 审阅通过事件,可空)
            drafter_decision_event_id: FK → events.id(D4.7.3 草稿生成事件,可空)

        Returns:
            OutboxDecisionReport: outbox_stored=True + outbox_id >= 1 + 11 字段透传

        Raises:
            ValueError: 入口严判失败
            OutboxEmailDuplicateError: UNIQUE(email_id) 冲突(D4.8 契约 4 业务阻断)
                                     — 调用方应改走 record_store_business_blocked_and_emit
            sqlalchemy.exc.OperationalError: DB 锁/连接失败 — 调用方应改走 record_store_failure_and_emit
        """
        # 1. 严判入参(契约 helper 复用,改一处全改)
        _validate_outbox_email_id(email_id)
        _validate_outbox_subject(subject)
        _validate_outbox_body(body)
        _validate_draft_tone(tone)
        _validate_outbox_recipient_email(recipient_email)
        _validate_outbox_priority(priority)
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )

        if self._outbox_store is None:
            raise ValueError(
                "outbox_store 未注入 — EmailOutboxAdapter.__init__ 必须传 outbox_store="
                "OutboxStore(session_factory),D4.8.3 单元测试用 FakeOutboxStore 注入"
            )

        # 2. 入库(D3.3.3 异常窄化: IntegrityError → 业务阻断;OperationalError → 技术失败)
        start_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        row: OutboxEntry = self._outbox_store.insert(
            email_id=email_id,
            subject=subject,
            body=body,
            tone=tone,
            recipient_email=recipient_email,
            reviewer_decision_event_id=reviewer_decision_event_id,
            drafter_decision_event_id=drafter_decision_event_id,
            priority=priority,
            status=OutboxStatus.PENDING_SEND.value,
            created_at=start_ms,
        )
        outbox_id = row.id
        if outbox_id is None or outbox_id < 1:
            # 防御性兜底:OutboxStore.insert 已 commit + refresh,id 必非空
            raise RuntimeError(
                f"OutboxEntry.id 不应为 None 或 < 1,实际 {outbox_id!r}(D4.8 契约违反)"
            )

        # 3. 构造 TaskPacket(D4.8 契约 3 — PermissionProfile = READ_WRITE)
        packet = build_outbox_packet(
            email_id=email_id,
            source=self._source,
            tone=tone,
            subject_length=len(subject),
        )

        # 4. 构造 context(成功路径强制 last_outbox_failed=False / cf=0)
        end_ms = int(time.time() * 1000)
        context = build_outbox_policy_context(
            email_id=email_id,
            tone=tone,
            priority=priority,
            subject_length=len(subject),
            body_length=len(body),
            last_outbox_failed=False,
            consecutive_outbox_failures=0,
            now_ms=end_ms,
        )

        # 5. run_id + lane_entry_id
        rid = run_id or str(start_ms)
        lane_entry_id = self.build_lane_entry_id(rid)

        # 6. PolicyEngine.evaluate(透传 11 字段业务 payload)
        # 复用 integration.py 中已有的 ExtraBusinessPayload 通过 extra_business_payload 注入
        # 6 业务字段透传契约(week1-mvp.md:860 锁定)
        # outbox_id / subject_length / body_length / tone / recipient_email / priority
        # + 5 辅助字段(email_id / status / source / created_at / latency_ms)
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=None,  # event_store 由 caller 注入到 evaluate,此处省略避免循环依赖
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload={
                "outbox_id": outbox_id,
                "subject_length": len(subject),
                "body_length": len(body),
                "tone": tone,
                "recipient_email": recipient_email,
                "priority": priority,
                "email_id": email_id,
                "status": OutboxStatus.PENDING_SEND.value,
                "source": self._source,
                "latency_ms": end_ms - start_ms,
            },
        )

        # 7. LaneBoard 记录(单一真相源 = acceptance_results)
        # D4.8 v1.0.1 修复:首次 add 必用 ACTIVE(LaneBoard.add 拒绝 FINISHED 终态),
        # 然后 update 到 FINISHED/BLOCKED(ACTIVE → FINISHED/BLOCKED 合法转换)
        ac_results = compute_outbox_acceptance(
            subject_length=len(subject),
            body_length=len(body),
            recipient_email=recipient_email,
        )
        business_accepted = bool(all(ac_results))
        entry_id = lane_entry_id
        final_status = LaneStatus.FINISHED if business_accepted else LaneStatus.BLOCKED
        existing: LaneEntry | None = None
        try:
            existing = self._board.get(entry_id)
        except Exception:
            existing = None
        if existing is None:
            self._board.add(
                LaneEntry(
                    entry_id=entry_id,
                    objective=f"Outbox store source={self._source} email_id={email_id}",
                    status=LaneStatus.ACTIVE,  # add 拒绝 FINISHED 终态(D4.8 v1.0.1 修复)
                    owner="email_outbox",
                )
            )
        self._board.update(
            entry_id,
            status=final_status,
            owner="email_outbox",
        )

        # 8. Heartbeat(update 刷新 last_seen_ms, evaluate 拿到 Liveness)
        self._heartbeat.update(transport_alive=transport_alive, now_ms=end_ms)
        liveness = self._heartbeat.evaluate(now_ms=end_ms)

        return OutboxDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            outbox_id=outbox_id,
            email_id=email_id,
            subject=subject,
            body=body,
            tone=tone,
            recipient_email=recipient_email,
            priority=priority,
            subject_length=len(subject),
            body_length=len(body),
            latency_ms=end_ms - start_ms,
        )

    # ===== 入口 2: 业务阻断 =====

    def record_store_business_blocked_and_emit(
        self,
        *,
        email_id: int,
        subject: str,
        body: str,
        tone: str,
        recipient_email: str,
        reason: str,
        last_error: Any,  # str | Exception
        transport_alive: bool = True,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> OutboxBlockedDecisionReport:
        """业务阻断入库入口(对应契约 1 业务阻断路径 — D4.8 契约 4 幂等性触发).

        Args:
            email_id: 关联 emails.id
            subject / body / tone / recipient_email: 与 store_and_emit 一致(已严判)
            reason: 2 类白名单(duplicate_email_id / blacklisted_recipient)
            last_error: 阻断原因描述(str | Exception,内部 str() 化)

        Returns:
            OutboxBlockedDecisionReport: blocked=True + kind=business_blocked + cf=0
        """
        # 1. 严判入参
        _validate_outbox_email_id(email_id)
        _validate_outbox_subject(subject)
        _validate_outbox_body(body)
        _validate_draft_tone(tone)
        _validate_outbox_recipient_email(recipient_email)
        _validate_outbox_block_reason(reason)
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )

        # 2. 归一 last_error(Exception → str)
        if isinstance(last_error, Exception):
            last_error_str = str(last_error)
        else:
            last_error_str = str(last_error) if last_error is not None else ""
        if not last_error_str.strip():
            raise ValueError(
                f"last_error 必填非空白(str | Exception), 实际 {type(last_error).__name__}={last_error!r}"
            )

        # 3. 构造 TaskPacket(READ_ONLY — 业务阻断不改库)
        packet = build_outbox_blocked_packet(
            email_id=email_id,
            source=self._source,
            reason=reason,
        )

        # 4. 构造 context(业务阻断 cf 必为 0,双向强一致)
        end_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        context = build_outbox_policy_context(
            email_id=email_id,
            tone=tone,
            priority="normal",  # 业务阻断无 priority
            subject_length=len(subject),
            body_length=len(body),
            last_outbox_failed=False,  # 业务阻断不计入失败(D4.7.3 v1.0.1 P1-1 范本)
            consecutive_outbox_failures=0,
            now_ms=end_ms,
        )

        # 5. run_id + lane_entry_id
        rid = run_id or str(end_ms)
        lane_entry_id = self.build_lane_entry_id(rid)

        # 6. PolicyEngine.evaluate(透传业务字段)
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=None,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload={
                "blocked": True,
                "kind": "business_blocked",
                "reason": reason,
                "email_id": email_id,
                "subject_length": len(subject),
                "body_length": len(body),
                "tone": tone,
                "recipient_email": recipient_email,
                "last_error": last_error_str,
                "source": self._source,
            },
        )

        # 7. LaneBoard 记录 — 业务阻断强制 BLOCKED
        # D4.8 v1.0.1 范本统一:首次 add 用 ACTIVE → update 到 BLOCKED(允许 ACTIVE→BLOCKED 转换)
        entry_id = lane_entry_id
        existing: LaneEntry | None = None
        try:
            existing = self._board.get(entry_id)
        except Exception:
            existing = None
        if existing is None:
            self._board.add(
                LaneEntry(
                    entry_id=entry_id,
                    objective=f"Outbox blocked source={self._source} reason={reason}",
                    status=LaneStatus.ACTIVE,
                    owner="email_outbox",
                )
            )
        self._board.update(entry_id, status=LaneStatus.BLOCKED, owner="email_outbox")

        # 8. Heartbeat(update 刷新 last_seen_ms, evaluate 拿到 Liveness)
        self._heartbeat.update(transport_alive=transport_alive, now_ms=end_ms)
        liveness = self._heartbeat.evaluate(now_ms=end_ms)

        return OutboxBlockedDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            last_error=last_error_str,
            reason=reason,
            email_id=email_id,
            subject=subject,
            body=body,
            tone=tone,
            recipient_email=recipient_email,
            consecutive_outbox_failures=0,
        )

    # ===== 入口 3: 技术失败 =====

    def record_store_failure_and_emit(
        self,
        *,
        email_id: int,
        subject: str,
        body: str,
        tone: str,
        recipient_email: str,
        last_error: Any,  # str | Exception
        consecutive_outbox_failures: int = 1,
        transport_alive: bool = True,
        run_id: str = "",
        now_ms: int | None = None,
    ) -> OutboxFailureDecisionReport:
        """技术失败入库入口(对应契约 1 技术失败路径 — D3.3.3 异常窄化触发).

        Args:
            email_id / subject / body / tone / recipient_email: 与 store_and_emit 一致(已严判)
            last_error: 失败原因描述(str | Exception)
            consecutive_outbox_failures: 失败累加器(>= 1,默认 1,双向强一致)

        Returns:
            OutboxFailureDecisionReport: failed=True + cf >= 1 + last_error.strip() 非空
        """
        # 1. 严判入参
        _validate_outbox_email_id(email_id)
        _validate_outbox_subject(subject)
        _validate_outbox_body(body)
        _validate_draft_tone(tone)
        _validate_outbox_recipient_email(recipient_email)
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )
        if (
            type(consecutive_outbox_failures) is bool
            or not isinstance(consecutive_outbox_failures, int)
            or consecutive_outbox_failures < 1
        ):
            raise ValueError(
                f"consecutive_outbox_failures 必须是原生 int(非 bool) >= 1, 实际 "
                f"{type(consecutive_outbox_failures).__name__}={consecutive_outbox_failures!r}"
            )

        # 2. 归一 last_error
        if isinstance(last_error, Exception):
            last_error_str = str(last_error)
        else:
            last_error_str = str(last_error) if last_error is not None else ""
        if not last_error_str.strip():
            raise ValueError(
                f"last_error 必填非空白(str | Exception), 实际 {type(last_error).__name__}={last_error!r}"
            )

        # 3. 构造 TaskPacket(READ_ONLY — 技术失败不改库)
        packet = build_outbox_failure_packet(
            email_id=email_id,
            source=self._source,
            consecutive_outbox_failures=consecutive_outbox_failures,
        )

        # 4. 构造 context(技术失败 cf 必为 >= 1,双向强一致)
        end_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        context = build_outbox_policy_context(
            email_id=email_id,
            tone=tone,
            priority="normal",
            subject_length=len(subject),
            body_length=len(body),
            last_outbox_failed=True,  # 技术失败 ↔ cf >= 1
            consecutive_outbox_failures=consecutive_outbox_failures,
            now_ms=end_ms,
        )

        # 5. run_id + lane_entry_id
        rid = run_id or str(end_ms)
        lane_entry_id = self.build_lane_entry_id(rid)

        # 6. PolicyEngine.evaluate
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=None,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload={
                "failed": True,
                "consecutive_outbox_failures": consecutive_outbox_failures,
                "last_error": last_error_str,
                "email_id": email_id,
                "subject_length": len(subject),
                "body_length": len(body),
                "tone": tone,
                "recipient_email": recipient_email,
                "source": self._source,
            },
        )

        # 7. LaneBoard 记录 — 技术失败走 BLOCKED(caller 决定是否 retry)
        # D4.8 v1.0.1 范本统一:首次 add 用 ACTIVE → update 到 BLOCKED
        entry_id = lane_entry_id
        existing: LaneEntry | None = None
        try:
            existing = self._board.get(entry_id)
        except Exception:
            existing = None
        if existing is None:
            self._board.add(
                LaneEntry(
                    entry_id=lane_entry_id,
                    objective=f"Outbox failure source={self._source} cf={consecutive_outbox_failures}",
                    status=LaneStatus.ACTIVE,
                    owner="email_outbox",
                )
            )
        self._board.update(entry_id, status=LaneStatus.BLOCKED, owner="email_outbox")

        # 8. Heartbeat(update 刷新 last_seen_ms, evaluate 拿到 Liveness)
        self._heartbeat.update(transport_alive=transport_alive, now_ms=end_ms)
        liveness = self._heartbeat.evaluate(now_ms=end_ms)

        return OutboxFailureDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            last_error=last_error_str,
            email_id=email_id,
            subject=subject,
            body=body,
            tone=tone,
            recipient_email=recipient_email,
            consecutive_outbox_failures=consecutive_outbox_failures,
        )


__all__ = [
    # 6 严判 helper
    "OUTBOX_BLOCK_REASON_VALUES",
    "_validate_outbox_email_id",
    "_validate_outbox_subject",
    "_validate_outbox_body",
    "_validate_outbox_recipient_email",
    "_validate_outbox_priority",
    "_validate_outbox_block_reason",
    # 3 工厂 + 1 acceptance + 1 context
    "compute_outbox_acceptance",
    "build_outbox_packet",
    "build_outbox_blocked_packet",
    "build_outbox_failure_packet",
    "build_outbox_policy_context",
    # 3 DecisionReport
    "OutboxDecisionReport",
    "OutboxBlockedDecisionReport",
    "OutboxFailureDecisionReport",
    # 主类
    "EmailOutboxAdapter",
]
