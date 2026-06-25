"""D5.3 — EmailSendAdapter: outbox SMTP 发送业务层接入适配器.

承接 D5.1 SMTP transport(connectors/smtp.py:SmtpLibTransport + InMemorySmtpTransport)
+ D5.2 状态机扩值(0005_outbox_sending_state migration + ALLOWED_TRANSITIONS 6 状态白名单)
+ D5.1-fix transport 边界 + CLI provider 严判(commit 18284fa).

D5.3 5 项契约(2026-06-12 启动):
    1. 三入口架构(沿 D4.7.3 v1.0.1 P1-1 范本 + D4.7.3 v1.0.6 教训升级):
       - send_and_emit(成功, send_succeeded=True) → SendDecisionReport
         状态机推进: PENDING_SEND/APPROVED → SENDING → SENT
         event: email.send.sent
       - record_send_business_blocked_and_emit(业务阻断, 4 类白名单,v0.2 B4.3 扩 3→4) → SendBlockedDecisionReport
         触发: smtplib.SMTPRecipientsRefused / SMTPSenderRefused / SMTPDataError
         状态: PENDING_SEND/APPROVED → CANCELLED(永不 retry, recovery_policy="none")
         event: email.send.business_blocked
       - record_send_failure_and_emit(技术失败, 4 类异常) → SendFailureDecisionReport
         触发: smtplib.SMTPServerDisconnected / SMTPConnectError / socket.timeout / SSL 错误
         状态: PENDING_SEND/APPROVED → SENDING → FAILED(可 retry, recovery_policy="retry_on_transient")
         event: email.send.technical_failed
    2. 复用 D5.2 状态机严判(OutboxStore.update_status(*, from_status))
    3. 异常窄化(D3.3.3 范本): SMTPRecipientsRefused / SMTPSenderRefused → 业务阻断,
       SMTPServerDisconnected / SMTPConnectError / socket.timeout / SSL 错误 → 技术失败
    4. 业务阻断 vs 技术失败拆分(D4.7.3 v1.0.1 P1-1 范本):
       - 业务阻断: cf=0 永不 retry
       - 技术失败: cf>=1 触发指数退避
    5. 不直连 smtplib — 走 SMTPTransport 抽象(D5.1 Protocol + SmtpLibTransport 生产 +
       InMemorySmtpTransport 测试),便于 D5.4 OutboxDispatcher 注入测试替身

25 教训 + 7 项核心契约全应用:
    1. 工厂层 + __post_init__ 双层防御(3 DecisionReport)
    2. 跨字段校验(last_send_failed ↔ consecutive_send_failures 双向强一致)
    3. 双向强一致(成功 send_succeeded=True → outbox_id >= 1)
    4. 异常统一 ValueError / PolicyError(编程错误透传 ValueError/TypeError)
    5. 字段名硬区分(send_blocked vs send_failed + kind 区分)
    6. 契约 helper 复用(沿用 D4.8 _validate_outbox_* + _validate_draft_tone 公共入口)
    7. 固化哲学(代码+注释+测试+导出+文档同 commit)
    8. 依赖注入 is None 不用 or(D4.7.3 v1.0.3 P2-2 范本)
    9. bool 子类是 int 陷阱(type() is int 不用 isinstance,D4.7.3 v1.0.5 P2-2 范本)
    10. dataclass 默认值字段放最后(OutboxDecisionReport 范本)
    11. strip() 严判语义非空(D4.7.3 v1.0.4 P2-4 范本)
    12. type 严判在 hash 前(D4.7.3 v1.0.5 P2-1 范本)
    13. 业务阻断 reason 白名单(frozenset 强约束,D4.8 OUTBOX_BLOCK_REASON_VALUES 范本)

D3.3.3 异常窄化教训应用:
    - smtplib 异常**不**直接接 SMTPException / Exception 基类
    - 业务阻断: SMTPSendRecipientsRefusedError / SMTPSendSenderRefusedError(继承 PolicyError)
    - 技术失败: SMTPSendTransportError(继承 PolicyError)
    - 状态机: OutboxIllegalTransitionError 包装为 SMTPSendIllegalTransitionError
"""

from __future__ import annotations

import smtplib
import ssl
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from my_ai_employee.core.outbox import OutboxStatus
from my_ai_employee.db.blacklist import RecipientBlacklistStore
from my_ai_employee.db.outbox import OutboxIllegalTransitionError, OutboxStore
from my_ai_employee.policy.exceptions import (
    SMTPSendIllegalTransitionError,
    SMTPSendRecipientsRefusedError,
    SMTPSendSenderRefusedError,
    SMTPSendTransportError,
)
from my_ai_employee.policy.heartbeat import Heartbeat, Liveness
from my_ai_employee.policy.lane_board import LaneBoard, LaneEntry, LaneStatus

# 复用 D4.8 契约 helper(改一处全改 — D4.7.3 v1.0.3 P1-1 范本)
from my_ai_employee.policy.outbox_adapter import (
    _validate_draft_tone,  # noqa: F401  # OutboxTone 字段值与 DraftTone 一致
    _validate_outbox_blacklist_store,  # v0.2 B4.3 复用:send_and_emit hot-path 严判
    _validate_outbox_body,
    _validate_outbox_email_id,
    _validate_outbox_priority,
    _validate_outbox_recipient_email,
    _validate_outbox_subject,
)
from my_ai_employee.policy.policy_engine import PolicyEngine, PolicyEvaluation
from my_ai_employee.policy.task_packet import PermissionProfile, TaskPacket

# ===== SMTPTransport 抽象(D5.1 范本 — Protocol + duck type)=====
# 这里只声明局部 Protocol,避免 import SMTPTransport(SMTPTransport 在 connectors.smtp.py)
# D4.7.3 v1.0.3 范本: send_adapter 接受任何实现 send_message / connect / login / quit 的类


class _SMTPTransportLike(Protocol):
    """D5.3 局部 SMTP transport 协议(便于 D5.4 Dispatcher 注入任何兼容类).

    Attributes:
        connect(host, port, *, timeout): 建立 SMTP SSL 连接
        login(username, password): SMTP 登录(用授权码)
        send_message(message): 发送邮件(返回 SMTPSendResult 4 状态之一)
        quit(): 优雅退出 SMTP 会话
    """

    def connect(self, host: str, port: int, *, timeout: float = 30.0) -> Any: ...

    def login(self, username: str, password: str) -> Any: ...

    def send_message(self, message: Any) -> Any: ...

    def quit(self) -> Any: ...


# ===== 业务阻断 reason 白名单(D5.3 契约 1 — 业务阻断入口 4 类,v0.2 B4.3 扩 3→4)=====

SEND_BLOCK_REASON_VALUES: frozenset[str] = frozenset(
    {
        "recipients_refused",  # smtplib.SMTPRecipientsRefused(收件人 5xx)
        "sender_refused",  # smtplib.SMTPSenderRefused(发件人被拒)
        "data_error",  # smtplib.SMTPDataError(4xx 数据错误)
        # v0.2 B4.3:黑名单命中(审批通过 ≠ 拉黑解除,SMTP 发送前再调 is_blocked)
        "blacklisted_recipient",
    }
)

# 技术失败 error_category 白名单(D5.3 契约 1 — 技术失败入口 4 类)
SEND_FAILURE_ERROR_CATEGORIES: frozenset[str] = frozenset(
    {
        "transport_error",  # SMTPServerDisconnected / SMTPConnectError / OSError
        "ssl_error",  # ssl.SSLError(SSL 握手失败)
        "timeout",  # socket.timeout / TimeoutError
        "smtp_other",  # 兜底 — 兜底未识别 smtplib.SMTPException(非收件人/发件人)
    }
)

# 字段边界(沿 D4.8 _OUTBOX_*_MIN/MAX — D4.8 契约)
_SEND_SUBJECT_MIN = 1
_SEND_SUBJECT_MAX = 200
_SEND_BODY_MIN = 10
_SEND_BODY_MAX = 8000

# 路径常量(沿 D4.8 build_outbox_packet 范本)
_SEND_SCOPE = "outbox.send"
_SEND_SCOPE_BLOCKED = "outbox.send.business_blocked"
_SEND_SCOPE_FAILED = "outbox.send.failure"

_SEND_MODEL = "outbox-send"
_SEND_MODEL_BLOCKED = "outbox-send-blocked"
_SEND_MODEL_FAILED = "outbox-send-failed"

_SEND_PROVIDER = "internal"


# ===== 5 契约 helper 复用(D4.8 _validate_outbox_* — D4.7.3 v1.0.3 P1-1 范本)=====
# 注: send_adapter 不重写 _validate_outbox_*,直接复用 outbox_adapter 公共入口
# 严判校验逻辑改一处全改 — 不允许 send_adapter 自造不同规则的严判


# ===== compute_send_acceptance(3 条 AC 契约描述 — 沿 D4.8 范本)=====


def compute_send_acceptance(
    *,
    subject_length: int,
    body_length: int,
    recipient_email: str,
) -> list[bool]:
    """计算 send 业务的 3 条 AC(D5.3 业务验收契约 — 沿 D4.8 compute_outbox_acceptance).

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
        _SEND_SUBJECT_MIN <= subject_length <= _SEND_SUBJECT_MAX,
        _SEND_BODY_MIN <= body_length <= _SEND_BODY_MAX,
        "@" in recipient_email,
    ]


# ===== 3 个 build_send_* packet 工厂(沿 D4.8 build_outbox_* 范本)=====


def build_send_packet(
    *,
    outbox_id: int,
    source: str,
    tone: str,
    subject_length: int,
) -> TaskPacket:
    """构造 send 成功的 TaskPacket(D5.3 契约 1 成功路径 — PermissionProfile = READ_WRITE).

    D5.3 首次引入"真发 SMTP" 路径(READ_WRITE 权限),与 D4.8 入库共用 READ_WRITE。
    """
    return TaskPacket(
        objective=f"outbox 发送 outbox_id={outbox_id} source={source}",
        scope=[_SEND_SCOPE],
        resources=["connectors/smtp.py", "db/outbox.py"],
        acceptance_criteria=[
            f"subject_length 1-200 (实际 {subject_length})",
            "body_length 10-8000",
            "recipient_email 含 @",
            "SMTP transport.send_message 返回 status=ok",
        ],
        model=_SEND_MODEL,
        provider=_SEND_PROVIDER,
        permission_profile=PermissionProfile.READ_WRITE.value,  # D5.3 沿用 D4.8 契约 3
        recovery_policy="manual",  # 发送成功无需恢复策略
    )


def build_send_blocked_packet(
    *,
    outbox_id: int,
    source: str,
    reason: str,
) -> TaskPacket:
    """构造 send 业务阻断的 TaskPacket(走 record_send_business_blocked_and_emit)."""
    return TaskPacket(
        objective=f"outbox 发送业务阻断 outbox_id={outbox_id} reason={reason}",
        scope=[_SEND_SCOPE_BLOCKED],
        resources=["connectors/smtp.py"],
        acceptance_criteria=[
            f"reason 必为 4 类白名单(实际 {reason})",
            "send_blocked: Literal[True]",
            "kind=Literal['business_blocked']",
        ],
        model=_SEND_MODEL_BLOCKED,
        provider=_SEND_PROVIDER,
        permission_profile=PermissionProfile.READ_ONLY.value,  # 业务阻断不改库
        recovery_policy="none",  # 业务阻断永不重试(D4.7.3 v1.0.6 范本)
    )


def build_send_failure_packet(
    *,
    outbox_id: int,
    source: str,
    consecutive_send_failures: int,
) -> TaskPacket:
    """构造 send 技术失败的 TaskPacket(走 record_send_failure_and_emit, cf 必填)."""
    return TaskPacket(
        objective=f"outbox 发送技术失败 outbox_id={outbox_id} cf={consecutive_send_failures}",
        scope=[_SEND_SCOPE_FAILED],
        resources=["connectors/smtp.py", "db/outbox.py"],
        acceptance_criteria=[
            f"cf >= 1 (实际 {consecutive_send_failures})",
            "send_failed: Literal[True]",
            "last_error.strip() 非空",
        ],
        model=_SEND_MODEL_FAILED,
        provider=_SEND_PROVIDER,
        permission_profile=PermissionProfile.READ_ONLY.value,
        recovery_policy="retry_on_transient",  # 技术失败可重试(D4.8 v1.0.1 修复:task_packet 白名单内)
    )


# ===== build_send_policy_context(双向强一致 — 沿 D4.8 build_outbox_policy_context 范本)=====


def build_send_policy_context(
    *,
    outbox_id: int,
    tone: str,
    priority: str,
    subject_length: int,
    body_length: int,
    last_send_failed: bool,
    consecutive_send_failures: int,
    now_ms: int,
) -> dict[str, Any]:
    """构造 send 决策 context(8 字段 + 双向强一致).

    双向强一致(D4.7.3 v1.0.2 P1-2 范本):
        - last_send_failed=True → cf >= 1
        - last_send_failed=False → cf == 0

    Raises:
        ValueError: type 严判失败 / 双向强一致违反
    """
    if type(last_send_failed) is not bool:
        raise ValueError(
            f"last_send_failed 必须是原生 bool, 实际 "
            f"{type(last_send_failed).__name__}={last_send_failed!r}"
        )
    if type(consecutive_send_failures) is bool or not isinstance(consecutive_send_failures, int):
        raise ValueError(
            f"consecutive_send_failures 必须是原生 int(非 bool), 实际 "
            f"{type(consecutive_send_failures).__name__}={consecutive_send_failures!r}"
        )
    if last_send_failed and consecutive_send_failures < 1:
        raise ValueError(
            f"双向强一致: last_send_failed=True → cf >= 1, "
            f"实际 last_send_failed={last_send_failed} cf={consecutive_send_failures}"
        )
    if not last_send_failed and consecutive_send_failures != 0:
        raise ValueError(
            f"双向强一致: last_send_failed=False → cf == 0, "
            f"实际 last_send_failed={last_send_failed} cf={consecutive_send_failures}"
        )
    return {
        "outbox_id": outbox_id,
        "tone": tone,
        "priority": priority,
        "subject_length": subject_length,
        "body_length": body_length,
        "last_send_failed": last_send_failed,
        "consecutive_send_failures": consecutive_send_failures,
        "now_ms": now_ms,
    }


# ===== 3 DecisionReport dataclass(成功 / 业务阻断 / 技术失败 — 字段名级别硬区分)=====


@dataclass(frozen=True)
class SendDecisionReport:
    """D5.3 业务层接入的可观测报告(成功发送版本).

    字段契约(week1-mvp.md §D5.3):
        - outbox_id / subject_length / body_length / tone / recipient_email / priority

    跨字段强一致(D4.7.3 v1.0.2 P1-2 范本):
        - send_succeeded=True → outbox_id >= 1

    Attributes:
        evaluation: PolicyEngine.evaluate() 完整结果
        event_id: 落地到 events 表的 PolicyDecisionEvent id
        lane_entry_id: LaneBoard 中本次发送的 entry_id(命名 send:<source>:<run_id>)
        liveness: Heartbeat 评估的 Liveness
        send_succeeded: Literal[True](成功发送专属)
        outbox_id: 发送成功的 outbox PK id(>= 1)
        email_id: 邮件主键(>= 0)
        subject: 已严判 1-200 字符
        body: 已严判 10-8000 字符
        tone: OutboxTone 3 选 1
        recipient_email: 含 @ 的字符串
        priority: OutboxPriority 3 选 1
        subject_length: len(subject)
        body_length: len(body)
        latency_ms: 发送耗时(>= 0)
        smtp_code: SMTP 2xx 响应码
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    outbox_id: int  # 跨字段强一致: send_succeeded=True → outbox_id >= 1
    email_id: int  # 关联 emails.id
    subject: str
    body: str
    tone: str
    recipient_email: str
    priority: str
    subject_length: int = 0  # 兼容旧调用(默认放最后 — D4.7.3 v1.0.5 范本)
    body_length: int = 0
    latency_ms: int = 0
    smtp_code: int | None = None
    # 字段名硬区分(D4.7.3 v1.0.3 P2-1 范本,成功发送专属)
    send_succeeded: Literal[True] = True

    def __post_init__(self) -> None:
        """D5.3 字段契约自洽校验(7 项核心契约 + 11 字段透传)."""
        if self.send_succeeded is not True:
            raise ValueError(
                f"SendDecisionReport.send_succeeded 必为 True "
                f"(D5.3 Literal[True] 类型层面固化, 成功发送专属), "
                f"实际 {self.send_succeeded!r}"
            )
        if (
            type(self.outbox_id) is bool
            or not isinstance(self.outbox_id, int)
            or self.outbox_id < 1
        ):
            raise ValueError(
                f"SendDecisionReport.outbox_id 必须是 int(非 bool) >= 1, 实际 "
                f"{type(self.outbox_id).__name__}={self.outbox_id!r}"
            )
        _validate_outbox_email_id(self.email_id)
        _validate_outbox_subject(self.subject)
        _validate_outbox_body(self.body)
        _validate_draft_tone(self.tone)
        _validate_outbox_recipient_email(self.recipient_email)
        _validate_outbox_priority(self.priority)
        # 双向强一致(D4.7.3 v1.0.2 P1-2 范本)
        if (
            type(self.subject_length) is bool
            or not isinstance(self.subject_length, int)
            or self.subject_length < 0
        ):
            raise ValueError(
                f"SendDecisionReport.subject_length 必须是 int(非 bool) >= 0, 实际 "
                f"{type(self.subject_length).__name__}={self.subject_length!r}"
            )
        if (
            type(self.body_length) is bool
            or not isinstance(self.body_length, int)
            or self.body_length < 0
        ):
            raise ValueError(
                f"SendDecisionReport.body_length 必须是 int(非 bool) >= 0, 实际 "
                f"{type(self.body_length).__name__}={self.body_length!r}"
            )
        if (
            type(self.latency_ms) is bool
            or not isinstance(self.latency_ms, int)
            or self.latency_ms < 0
        ):
            raise ValueError(
                f"SendDecisionReport.latency_ms 必须是 int(非 bool) >= 0, 实际 "
                f"{type(self.latency_ms).__name__}={self.latency_ms!r}"
            )


@dataclass(frozen=True)
class SendBlockedDecisionReport:
    """D5.3 业务层接入的可观测报告(业务阻断版本).

    字段名硬区分(D4.7.3 v1.0.3 P2-1 范本):
        - send_blocked: Literal[True](业务阻断专属字段名)
        - kind: Literal["business_blocked"](与 SendFailureDecisionReport 区分)
        - reason: 4 类白名单(recipients_refused / sender_refused / data_error / blacklisted_recipient)
        - last_error: 阻断原因描述(必填非空)
        - consecutive_send_failures: 必为 0(业务阻断不计入失败累加器)
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    last_error: str  # 必填非空
    reason: str  # 4 类白名单
    outbox_id: int
    email_id: int
    subject: str
    body: str
    tone: str
    recipient_email: str
    # 业务阻断不计入失败累加器(D4.7.3 v1.0.1 P1-1 范本)
    consecutive_send_failures: int = 0
    # 字段名硬区分(D4.7.3 v1.0.3 P2-1 范本)
    send_blocked: Literal[True] = True
    kind: Literal["business_blocked"] = "business_blocked"

    def __post_init__(self) -> None:
        """D5.3 业务阻断字段契约校验(7 项核心契约 + 4 类白名单)."""
        if self.send_blocked is not True:
            raise ValueError(
                f"SendBlockedDecisionReport.send_blocked 必为 True, 实际 {self.send_blocked!r}"
            )
        if self.kind != "business_blocked":
            raise ValueError(
                f"SendBlockedDecisionReport.kind 必为 'business_blocked', 实际 {self.kind!r}"
            )
        if type(self.last_error) is not str or not self.last_error.strip():
            raise ValueError(
                f"SendBlockedDecisionReport.last_error 必填非空白 str, 实际 "
                f"{type(self.last_error).__name__}={self.last_error!r}"
            )
        # reason 白名单严判(D4.7.3 v1.0.5 P2-1 范本: type 严判在 hash 前)
        if type(self.reason) is not str:
            raise ValueError(
                f"SendBlockedDecisionReport.reason 必须是 str, 实际 "
                f"{type(self.reason).__name__}={self.reason!r}"
            )
        if self.reason not in SEND_BLOCK_REASON_VALUES:
            raise ValueError(
                f"SendBlockedDecisionReport.reason 必须是 4 类白名单 "
                f"{sorted(SEND_BLOCK_REASON_VALUES)!r}, 实际 {self.reason!r}"
            )
        if (
            type(self.outbox_id) is bool
            or not isinstance(self.outbox_id, int)
            or self.outbox_id < 1
        ):
            raise ValueError(
                f"SendBlockedDecisionReport.outbox_id 必须是 int(非 bool) >= 1, 实际 "
                f"{type(self.outbox_id).__name__}={self.outbox_id!r}"
            )
        _validate_outbox_email_id(self.email_id)
        _validate_outbox_subject(self.subject)
        _validate_outbox_body(self.body)
        _validate_draft_tone(self.tone)
        _validate_outbox_recipient_email(self.recipient_email)
        # 业务阻断 cf 必为 0(D4.7.3 v1.0.1 P1-1 范本:业务阻断 ≠ 技术失败)
        if self.consecutive_send_failures != 0:
            raise ValueError(
                f"SendBlockedDecisionReport.consecutive_send_failures 业务阻断必为 0, "
                f"实际 {self.consecutive_send_failures}"
            )


@dataclass(frozen=True)
class SendFailureDecisionReport:
    """D5.3 业务层接入的可观测报告(技术失败版本).

    字段名硬区分(D4.7.3 v1.0.3 P2-1 范本):
        - send_failed: Literal[True](技术失败专属字段名)
    双向强一致(D4.7.3 v1.0.2 P1-2 范本):
        - last_send_failed=True ↔ cf >= 1
    """

    evaluation: PolicyEvaluation
    event_id: int | None
    lane_entry_id: str
    liveness: Liveness
    last_error: str  # 必填非空
    error_category: str  # 4 类白名单
    outbox_id: int
    email_id: int
    subject: str
    body: str
    tone: str
    recipient_email: str
    consecutive_send_failures: int = 0  # 双向强一致
    retry_after_ms: int = 0  # 指数退避建议(> 0, D5.5 联动)
    # 字段名硬区分(D4.7.3 v1.0.3 P2-1 范本,技术失败专属)
    send_failed: Literal[True] = True

    def __post_init__(self) -> None:
        """D5.3 技术失败字段契约校验(7 项核心契约 + 4 类白名单)."""
        if self.send_failed is not True:
            raise ValueError(
                f"SendFailureDecisionReport.send_failed 必为 True, 实际 {self.send_failed!r}"
            )
        if type(self.last_error) is not str or not self.last_error.strip():
            raise ValueError(
                f"SendFailureDecisionReport.last_error 必填非空白 str, 实际 "
                f"{type(self.last_error).__name__}={self.last_error!r}"
            )
        # error_category 白名单严判
        if type(self.error_category) is not str:
            raise ValueError(
                f"SendFailureDecisionReport.error_category 必须是 str, 实际 "
                f"{type(self.error_category).__name__}={self.error_category!r}"
            )
        if self.error_category not in SEND_FAILURE_ERROR_CATEGORIES:
            raise ValueError(
                f"SendFailureDecisionReport.error_category 必须是 4 类白名单 "
                f"{sorted(SEND_FAILURE_ERROR_CATEGORIES)!r}, 实际 {self.error_category!r}"
            )
        if (
            type(self.outbox_id) is bool
            or not isinstance(self.outbox_id, int)
            or self.outbox_id < 1
        ):
            raise ValueError(
                f"SendFailureDecisionReport.outbox_id 必须是 int(非 bool) >= 1, 实际 "
                f"{type(self.outbox_id).__name__}={self.outbox_id!r}"
            )
        if (
            type(self.consecutive_send_failures) is bool
            or not isinstance(self.consecutive_send_failures, int)
            or self.consecutive_send_failures < 1
        ):
            raise ValueError(
                f"SendFailureDecisionReport.consecutive_send_failures 必须是 int(非 bool) >= 1, "
                f"实际 {type(self.consecutive_send_failures).__name__}={self.consecutive_send_failures!r}"
            )
        if (
            type(self.retry_after_ms) is bool
            or not isinstance(self.retry_after_ms, int)
            or self.retry_after_ms < 0
        ):
            raise ValueError(
                f"SendFailureDecisionReport.retry_after_ms 必须是 int(非 bool) >= 0, 实际 "
                f"{type(self.retry_after_ms).__name__}={self.retry_after_ms!r}"
            )
        _validate_outbox_email_id(self.email_id)
        _validate_outbox_subject(self.subject)
        _validate_outbox_body(self.body)
        _validate_draft_tone(self.tone)
        _validate_outbox_recipient_email(self.recipient_email)


# ===== EmailSendAdapter 主类(5 依赖可注入, 三入口)=====


class EmailSendAdapter:
    """D5.3 业务层接入适配器 — outbox SMTP 发送 接入 PolicyEngine 5 件套.

    复用 D4.7.3 + D4.7.4 + D4.8 范本(6 依赖可注入 + 三入口架构):
        - source: 数据源头(必填非空白)
        - smtp_transport: SMTPTransport Protocol(D5.1 SmtpLibTransport 生产 +
          InMemorySmtpTransport 测试,D5.3 接受任何兼容类)
        - outbox_store: OutboxStore(D5.2 update_status 状态机严判)
        - engine: PolicyEngine(D4.4 决策引擎)
        - heartbeat: Heartbeat(LLM 探活)
        - board: LaneBoard(发送任务看板)
        - blacklist_store: RecipientBlacklistStore(v0.2 B4.3 SMTP 发送路径二次防御,
          复用 outbox_adapter._validate_outbox_blacklist_store helper)

    三入口互斥(D4.7.3 v1.0.1 P1-1 拆分):
        - send_and_emit(成功, send_succeeded=True) → SendDecisionReport
          (v0.2 B4.3:黑名单命中时返回 SendBlockedDecisionReport)
        - record_send_business_blocked_and_emit(业务阻断, 4 类白名单) → SendBlockedDecisionReport
        - record_send_failure_and_emit(技术失败, 4 类异常) → SendFailureDecisionReport

    lane_entry_id 命名: send:<source>:<run_id>(与 classify: / sync: / draft: / review: / outbox: 区分)

    状态机推进(D5.2 契约):
        成功路径:    PENDING_SEND/APPROVED → SENDING → SENT
        业务阻断:    PENDING_SEND/APPROVED → CANCELLED(永不 retry, 直接终态)
        技术失败:    PENDING_SEND/APPROVED → SENDING → FAILED(可 retry 回路)

    异常窄化(D3.3.3 教训):
        - SMTPSendRecipientsRefusedError / SMTPSendSenderRefusedError → 业务阻断入口
        - SMTPSendTransportError / 其他 smtplib 异常 → 技术失败入口
        - OutboxIllegalTransitionError(D5.2)→ 包装为 SMTPSendIllegalTransitionError
          → 状态漂移检测: 技术失败入口 / 白名单外转换: 业务阻断入口
    """

    def __init__(
        self,
        *,
        source: str,
        smtp_transport: _SMTPTransportLike | None = None,
        outbox_store: OutboxStore | None = None,
        engine: PolicyEngine | None = None,
        heartbeat: Heartbeat | None = None,
        board: LaneBoard | None = None,
        blacklist_store: RecipientBlacklistStore | None = None,
        smtp_provider: str
        | None = None,  # v0.2.51: provider 名("qq"/"outlook"/"gmail") → 内部走 SMTPProviderFactory
    ) -> None:
        # D4.7.3 v1.0.5 P2-2 范本: source 严判 strip() 语义非空
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                f"source 必填非空白 str(strip() 非空), 实际 {type(source).__name__}={source!r}"
            )
        self._source = source
        # D4.7.3 v1.0.3 P2-2 范本: is None 不用 or 短路(保留 falsey 替身)
        self._smtp_transport = smtp_transport
        self._outbox_store = outbox_store
        self._engine = engine if engine is not None else PolicyEngine()
        self._heartbeat = (
            heartbeat if heartbeat is not None else Heartbeat(idle_threshold_ms=30_000)
        )
        self._board = board if board is not None else LaneBoard(idle_threshold_ms=60_000)
        # v0.2 B4.3 引入: blacklist_store 默认 None(不接二次防御);注入 RecipientBlacklistStore
        # 时 send_and_emit 入口前会调 is_blocked(entry.recipient_email) 二次校验
        # 复用 outbox_adapter._validate_outbox_blacklist_store(type 严判 + is None fallback)
        self._blacklist_store = _validate_outbox_blacklist_store(blacklist_store)

        # v0.2.51 接入 SMTPProviderFactory:smtp_provider 显式传 → 内部走工厂创建底层 transport
        # smtp_transport 与 smtp_provider 互斥(同传 → 严判 ValueError)
        # v0.2.52 P0 修复(SMTPProviderFactory 协议不匹配):SMTPProviderFactory.create() 返回
        # 高层 SMTPConnector(签名是 async connect() 无 host/port/timeout),不是 SMTPTransport。
        # 正确做法:取 connector.transport(底层 SMTPTransport 实例)赋给 _smtp_transport —
        # SMTPProviderFactory.create() 默认会注入 SmtpLibTransport(),所以 connector.transport
        # 应为非 None;为 robustness 加 None fallback(显式新建 SmtpLibTransport())。
        # 真实发件邮箱来源 = entry.sender_email(由 OutboxDispatcher 在 v0.2.51.1 注入),
        # SMTPProviderFactory 的 email 字段仅用于严判通过,此处用 source 作占位。
        self._smtp_provider: str | None = None
        self._provider_default_host: str | None = None
        self._provider_default_port: int | None = None
        self._provider_default_email: str | None = None
        if smtp_provider is not None:
            if smtp_transport is not None:
                raise ValueError(
                    "smtp_provider 与 smtp_transport 互斥, 同传时冲突(沿 v0.2.51 B 类)"
                )
            from my_ai_employee.connectors.smtp import (  # 延迟 import 避循环
                SmtpLibTransport,
                SMTPProviderFactory,
            )

            # 占位 email:仅供 SMTPProviderFactory 严判通过,真实发件邮箱待 v0.2.51.1
            # OutboxDispatcher 用 entry.sender_email 覆盖(provider 默认值仅作配置参考)
            placeholder_email = f"{source}@my-ai-employee.local"
            connector = SMTPProviderFactory.create(
                provider=smtp_provider,
                email=placeholder_email,
            )
            # v0.2.52 P0 修复:取底层 SMTPTransport(SMTPConnector.transport 属性),
            # 而非把 connector 塞进 _smtp_transport(协议不匹配)
            underlying_transport = connector.transport
            if underlying_transport is None:
                # SMTPProviderFactory.create() 默认会注入 SmtpLibTransport(),但 D5.1-fix
                # 修订后允许 transport=None 创建(防"假成功");此处显式 fallback 兜底
                underlying_transport = SmtpLibTransport()
            self._smtp_transport = underlying_transport
            # 暴露 provider 默认配置(供 OutboxDispatcher / send_and_emit 参考)
            self._smtp_provider = smtp_provider
            self._provider_default_host = connector.server_host
            self._provider_default_port = int(connector.server_port)
            self._provider_default_email = placeholder_email

    def build_lane_entry_id(self, run_id: str) -> str:
        """生成 LaneBoard entry_id: 'send:<source>:<run_id>'."""
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError(
                f"run_id 必填非空白 str(strip() 非空), 实际 {type(run_id).__name__}={run_id!r}"
            )
        return f"send:{self._source}:{run_id}"

    # ===== 公共 helper: 注入未注入依赖时的硬报错 =====

    def _require_smtp_transport(self) -> _SMTPTransportLike:
        if self._smtp_transport is None:
            raise ValueError(
                "smtp_transport 未注入 — EmailSendAdapter.__init__ 必须传 smtp_transport="
                "SmtpLibTransport()/InMemorySmtpTransport(),D5.3 单元测试用 InMemorySmtpTransport 注入"
            )
        return self._smtp_transport

    def _require_outbox_store(self) -> OutboxStore:
        if self._outbox_store is None:
            raise ValueError(
                "outbox_store 未注入 — EmailSendAdapter.__init__ 必须传 outbox_store="
                "OutboxStore(session_factory),D5.3 单元测试用 OutboxStore 注入"
            )
        return self._outbox_store

    # ===== 入口 1: 成功发送 =====

    def send_and_emit(
        self,
        *,
        outbox_id: int,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        smtp_password: str,
        email_message: Any,  # email.message.EmailMessage
        run_id: str = "",
        transport_alive: bool = True,
        now_ms: int | None = None,
    ) -> SendDecisionReport | SendBlockedDecisionReport:
        """成功发送入口(对应契约 1 成功路径 — PENDING_SEND/APPROVED → SENDING → SENT).

        Args:
            outbox_id: OutboxEntry.id(>= 1, 严判)
            smtp_host: SMTP 服务器地址(必填非空)
            smtp_port: SMTP 端口(>= 1, 严判)
            smtp_username: SMTP 用户名(必填非空)
            smtp_password: SMTP 授权码(必填非空,严判非空但不打印)
            email_message: email.message.EmailMessage 实例
            run_id: 运行 ID(默认 = str(now_ms))
            transport_alive: transport 是否健康(默认 True)
            now_ms: 注入"当前时间"(测试用, None = int(time.time() * 1000))

        Returns:
            SendDecisionReport | SendBlockedDecisionReport:
                - 正常发送: SendDecisionReport(send_succeeded=True + outbox_id >= 1 + 11 字段透传)
                - 黑名单命中(v0.2 B4.3): SendBlockedDecisionReport(reason="blacklisted_recipient")

        Raises:
            ValueError: 入口严判失败
            SMTPSendRecipientsRefusedError: SMTPRecipientsRefused 业务阻断
                                            — 调用方应改走 record_send_business_blocked_and_emit
            SMTPSendSenderRefusedError:    SMTPSenderRefused 业务阻断
            SMTPSendTransportError:        SMTPServerDisconnected/SMTPConnectError/SSL/timeout 技术失败
                                          — 调用方应改走 record_send_failure_and_emit
            SMTPSendIllegalTransitionError: OutboxIllegalTransitionError 状态机非法转换
        """
        # 1. 严判入参
        if type(outbox_id) is bool or not isinstance(outbox_id, int) or outbox_id < 1:
            raise ValueError(
                f"outbox_id 必须是原生 int(非 bool) >= 1, 实际 "
                f"{type(outbox_id).__name__}={outbox_id!r}"
            )
        if not isinstance(smtp_host, str) or not smtp_host.strip():
            raise ValueError(
                f"smtp_host 必填非空白 str, 实际 {type(smtp_host).__name__}={smtp_host!r}"
            )
        if (
            type(smtp_port) is bool
            or not isinstance(smtp_port, int)
            or smtp_port < 1
            or smtp_port > 65535
        ):
            raise ValueError(
                f"smtp_port 必须是原生 int(非 bool) 1-65535, 实际 "
                f"{type(smtp_port).__name__}={smtp_port!r}"
            )
        if not isinstance(smtp_username, str) or not smtp_username.strip():
            raise ValueError(
                f"smtp_username 必填非空白 str, 实际 {type(smtp_username).__name__}={smtp_username!r}"
            )
        if not isinstance(smtp_password, str) or not smtp_password:
            # 注意: 不严判 strip(), 授权码可能有尾部空白(虽然不太可能)
            raise ValueError(
                f"smtp_password 必填非空 str, 实际 {type(smtp_password).__name__}=<redacted>"
            )
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )

        transport = self._require_smtp_transport()
        store = self._require_outbox_store()

        # 2. 查 outbox(走 D5.2 by_id)
        start_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        entry = store.by_id(outbox_id)
        if entry is None:
            raise ValueError(
                f"outbox_id={outbox_id} 不存在,无法 send_and_emit (D5.3 入口先查后发,避免无主发送)"
            )
        # D5.6.4 P1: 收窄至 APPROVED only(防 PENDING_SEND 绕过审批)
        # Adapter 不再接 PENDING_SEND — 审批必须显式走 store.update_status(APPROVED, last_approved_at_ms=...)
        if entry.status != OutboxStatus.APPROVED.value:
            raise ValueError(
                f"outbox_id={outbox_id} 状态={entry.status!r} 不在 APPROVED,"
                f"无法 send_and_emit(D5.6.4 收窄至 APPROVED only,防 PENDING_SEND 绕过审批)"
            )
        # D5.6.4 P1: 校验审批凭据(防 APPROVED 但 last_approved_at_ms=None 漏洞)
        if entry.last_approved_at_ms is None:
            raise ValueError(
                f"outbox_id={outbox_id} 状态=APPROVED 但 last_approved_at_ms=None,"
                f"无法 send_and_emit(D5.6.4 审批凭据必传,APPROVED 必带 last_approved_at_ms)"
            )

        # 2.5 v0.2 B4.3 二次防御:审批通过 ≠ 拉黑解除,SMTP 发送前再调 is_blocked
        # 防护场景:入库时收件人不在黑名单(放行)→ 用户审批后被人工/自动加入黑名单 →
        # 若不再校验,SMTP 会真发给黑名单邮箱
        # 沿 B4.2 store_and_emit 范本:_validate_outbox_blacklist_store 严判 + hot-path 检查 +
        # 命中走业务阻断入口(已含黑名单 reason 白名单)
        if self._blacklist_store is not None and self._blacklist_store.is_blocked(
            entry.recipient_email
        ):
            block_entry = self._blacklist_store.find_by_email(entry.recipient_email)
            block_reason = block_entry.reason if block_entry else ""
            last_error_str = (
                f"{entry.recipient_email} 命中黑名单"
                f"(reason={block_reason or 'unspecified'}, "
                f"added_by={block_entry.added_by if block_entry else 'unknown'})"
            )
            # 走业务阻断入口(reason 白名单已含 blacklisted_recipient,Send 4 类扩)
            return self.record_send_business_blocked_and_emit(
                outbox_id=outbox_id,
                reason="blacklisted_recipient",
                last_error=last_error_str,
                run_id=run_id,
                transport_alive=transport_alive,
                now_ms=now_ms,
            )

        # 3. 状态机推进 #1: PENDING_SEND/APPROVED → SENDING
        # D5.2 严判: from_status 必传
        try:
            store.update_status(
                outbox_id,
                OutboxStatus.SENDING.value,
                from_status=entry.status,
            )
        except OutboxIllegalTransitionError as e:
            # D5.2 状态机非法转换 → 包装为 D5.3 异常
            raise SMTPSendIllegalTransitionError(
                f"outbox_id={outbox_id} send_and_emit 状态机非法转换: {e}"
            ) from e

        # 4. 真发 SMTP(D5.1 SMTPTransport 抽象)
        # 异常窄化(D3.3.3 范本): 显式枚举具体 smtplib 异常类, 严禁接 SMTPException / Exception 基类
        # 业务阻断类(永久退信, 永不重试): SMTPRecipientsRefused / SMTPSenderRefused / SMTPDataError
        #     / SMTPAuthenticationError → SENDING → CANCELLED
        # 技术失败类(瞬态, 可重试): SMTPServerDisconnected / SMTPConnectError / socket.timeout
        #     / OSError / SSL → SENDING → FAILED
        smtp_code: int | None = None
        try:
            transport.connect(smtp_host, smtp_port, timeout=30.0)
            transport.login(smtp_username, smtp_password)
            smtp_result = transport.send_message(email_message)
        except smtplib.SMTPRecipientsRefused as e:
            # 业务阻断: 5xx 收件人地址被拒 → 永久退信
            transport.quit()
            raise SMTPSendRecipientsRefusedError(
                f"SMTP 收件人拒收: outbox_id={outbox_id} recipients_refused={e.recipients!r}"
            ) from e
        except smtplib.SMTPSenderRefused as e:
            # 业务阻断: 5xx 发件人被服务器拒收
            transport.quit()
            raise SMTPSendSenderRefusedError(
                f"SMTP 发件人拒收: outbox_id={outbox_id} sender={e.sender!r} code={e.smtp_code}"
            ) from e
        except smtplib.SMTPDataError as e:
            # 业务阻断: 4xx DATA 阶段数据错误(收件人/邮件内容不合规)
            # 例: 452 邮箱满 / 552 邮件超限 / 554 命中 spam 规则
            smtp_code = e.smtp_code
            transport.quit()
            raise SMTPSendRecipientsRefusedError(
                f"SMTP 数据错误(DATA 阶段): outbox_id={outbox_id} "
                f"smtp_code={e.smtp_code} smtp_msg={e.smtp_error!r}"
            ) from e
        except smtplib.SMTPAuthenticationError as e:
            # 业务阻断: SMTP 认证失败(授权码错 / 过期), 需人工审查凭据
            smtp_code = e.smtp_code
            transport.quit()
            raise SMTPSendSenderRefusedError(
                f"SMTP 认证失败: outbox_id={outbox_id} smtp_code={e.smtp_code} "
                f"smtp_msg={e.smtp_error!r}"
            ) from e
        except smtplib.SMTPServerDisconnected as e:
            # 技术失败: 服务器意外断连(瞬态, 可重试)
            transport.quit()
            raise SMTPSendTransportError(
                f"SMTP 服务器断连: outbox_id={outbox_id} error={e!r}"
            ) from e
        except smtplib.SMTPConnectError as e:
            # 技术失败: 连接失败(瞬态, 可重试)
            # 拿掉 v1.0.0 的 SMTPException 基类兜底, 严格窄化(D3.3.3 范本)
            transport.quit()
            raise SMTPSendTransportError(f"SMTP 连接失败: outbox_id={outbox_id} error={e!r}") from e
        except (TimeoutError, OSError) as e:
            # 技术失败: socket.timeout / DNS / OS 网络层错误
            transport.quit()
            raise SMTPSendTransportError(
                f"SMTP 网络层错误: outbox_id={outbox_id} error={e!r}"
            ) from e
        except ssl.SSLError as e:
            # 技术失败: SSL 握手失败(端口错 / 证书过期)
            # 注: smtplib 在 smtplib.py 内部 re-export 了 ssl.SSLError 但 mypy stub 不导出
            # 改用 ssl.SSLError(标准库稳定入口)更鲁棒
            transport.quit()
            raise SMTPSendTransportError(f"SMTP SSL 错误: outbox_id={outbox_id} error={e!r}") from e
        # 注: 不接 smtplib.SMTPException / Exception 基类(防掩盖真实生产问题, D3.3.3 教训)

        # 5. 检查 SMTPSendResult status
        from my_ai_employee.connectors.smtp import (  # 局部 import 避免循环依赖
            SMTP_SEND_OK,
            SMTP_SEND_PERMANENT_BOUNCE,
            SMTP_SEND_TIMEOUT,
            SMTP_SEND_TRANSPORT_ERROR,
        )

        smtp_status = getattr(smtp_result, "status", None)
        smtp_code = getattr(smtp_result, "smtp_code", None)
        smtp_msg = getattr(smtp_result, "smtp_message", None) or getattr(
            smtp_result, "error_detail", None
        )

        if smtp_status == SMTP_SEND_PERMANENT_BOUNCE:
            transport.quit()
            raise SMTPSendRecipientsRefusedError(
                f"SMTP 永久退信(transport 返回): outbox_id={outbox_id} "
                f"smtp_code={smtp_code} smtp_msg={smtp_msg!r}"
            )
        if smtp_status in (SMTP_SEND_TRANSPORT_ERROR, SMTP_SEND_TIMEOUT):
            transport.quit()
            raise SMTPSendTransportError(
                f"SMTP 传输错误(transport 返回): outbox_id={outbox_id} "
                f"status={smtp_status} detail={smtp_msg!r}"
            )
        if smtp_status != SMTP_SEND_OK:
            transport.quit()
            raise SMTPSendTransportError(
                f"SMTP 未知状态(transport 返回): outbox_id={outbox_id} "
                f"status={smtp_status!r} detail={smtp_msg!r}"
            )

        # 6. 状态机推进 #2: SENDING → SENT
        try:
            store.update_status(
                outbox_id,
                OutboxStatus.SENT.value,
                from_status=OutboxStatus.SENDING.value,
            )
        except OutboxIllegalTransitionError as e:
            transport.quit()
            raise SMTPSendIllegalTransitionError(
                f"outbox_id={outbox_id} send_and_emit SENDING→SENT 状态机非法转换: {e}"
            ) from e

        # 7. 优雅退出 SMTP
        transport.quit()

        # 8. 构造 TaskPacket
        packet = build_send_packet(
            outbox_id=outbox_id,
            source=self._source,
            tone=entry.tone,
            subject_length=len(entry.subject),
        )

        # 9. 构造 context(成功路径强制 last_send_failed=False / cf=0)
        end_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        context = build_send_policy_context(
            outbox_id=outbox_id,
            tone=entry.tone,
            priority=entry.priority,
            subject_length=len(entry.subject),
            body_length=len(entry.body),
            last_send_failed=False,
            consecutive_send_failures=0,
            now_ms=end_ms,
        )

        # 10. run_id + lane_entry_id
        rid = run_id or str(start_ms)
        lane_entry_id = self.build_lane_entry_id(rid)

        # 11. PolicyEngine.evaluate
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=None,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload={
                "outbox_id": outbox_id,
                "email_id": entry.email_id,
                "subject_length": len(entry.subject),
                "body_length": len(entry.body),
                "tone": entry.tone,
                "recipient_email": entry.recipient_email,
                "priority": entry.priority,
                "status": OutboxStatus.SENT.value,
                "source": self._source,
                "latency_ms": end_ms - start_ms,
                "smtp_code": smtp_code,
            },
        )

        # 12. LaneBoard 记录
        ac_results = compute_send_acceptance(
            subject_length=len(entry.subject),
            body_length=len(entry.body),
            recipient_email=entry.recipient_email,
        )
        business_accepted = bool(all(ac_results))
        final_status = LaneStatus.FINISHED if business_accepted else LaneStatus.BLOCKED
        existing: LaneEntry | None = None
        try:
            existing = self._board.get(lane_entry_id)
        except Exception:
            existing = None
        if existing is None:
            self._board.add(
                LaneEntry(
                    entry_id=lane_entry_id,
                    objective=f"Outbox send source={self._source} outbox_id={outbox_id}",
                    status=LaneStatus.ACTIVE,  # add 拒绝 FINISHED 终态(D4.8 v1.0.1 修复)
                    owner="email_send",
                )
            )
        self._board.update(
            lane_entry_id,
            status=final_status,
            owner="email_send",
        )

        # 13. Heartbeat
        self._heartbeat.update(transport_alive=transport_alive, now_ms=end_ms)
        liveness = self._heartbeat.evaluate(now_ms=end_ms)

        return SendDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            outbox_id=outbox_id,
            email_id=entry.email_id,
            subject=entry.subject,
            body=entry.body,
            tone=entry.tone,
            recipient_email=entry.recipient_email,
            priority=entry.priority,
            subject_length=len(entry.subject),
            body_length=len(entry.body),
            latency_ms=end_ms - start_ms,
            smtp_code=smtp_code,
        )

    # ===== 入口 2: 业务阻断 =====

    def record_send_business_blocked_and_emit(
        self,
        *,
        outbox_id: int,
        reason: str,
        last_error: Any,  # str | Exception
        run_id: str = "",
        transport_alive: bool = True,
        now_ms: int | None = None,
    ) -> SendBlockedDecisionReport:
        """业务阻断发送入口(对应契约 1 业务阻断路径 — 4 类白名单,v0.2 B4.3 扩 3→4).

        Args:
            outbox_id: OutboxEntry.id(>= 1)
            reason: 4 类白名单(recipients_refused / sender_refused / data_error)
            last_error: 阻断原因描述(str | Exception, 内部 str() 化)

        Returns:
            SendBlockedDecisionReport: send_blocked=True + kind=business_blocked + cf=0
        """
        # 1. 严判入参
        if type(outbox_id) is bool or not isinstance(outbox_id, int) or outbox_id < 1:
            raise ValueError(
                f"outbox_id 必须是原生 int(非 bool) >= 1, 实际 "
                f"{type(outbox_id).__name__}={outbox_id!r}"
            )
        # reason 白名单严判(D4.7.3 v1.0.5 P2-1 范本: type 严判在 hash 前)
        if type(reason) is not str:
            raise ValueError(f"reason 必须是 str, 实际 {type(reason).__name__}={reason!r}")
        if reason not in SEND_BLOCK_REASON_VALUES:
            raise ValueError(
                f"reason 必须是 4 类白名单 {sorted(SEND_BLOCK_REASON_VALUES)!r}, 实际 {reason!r}"
            )
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )

        store = self._require_outbox_store()

        # 2. 归一 last_error(Exception → str)
        if isinstance(last_error, Exception):
            last_error_str = str(last_error)
        else:
            last_error_str = str(last_error) if last_error is not None else ""
        if not last_error_str.strip():
            raise ValueError(
                f"last_error 必填非空白(str | Exception), 实际 "
                f"{type(last_error).__name__}={last_error!r}"
            )

        # 3. 查 outbox(走 D5.2 by_id)
        entry = store.by_id(outbox_id)
        if entry is None:
            raise ValueError(
                f"outbox_id={outbox_id} 不存在,无法 record_send_business_blocked_and_emit"
            )

        # 4. 状态机推进: PENDING_SEND/APPROVED → CANCELLED(直接终态, 不走 SENDING 中间态)
        # D5.2 严判: from_status 必传
        try:
            store.update_status(
                outbox_id,
                OutboxStatus.CANCELLED.value,
                from_status=entry.status,
            )
        except OutboxIllegalTransitionError as e:
            # 业务阻断下状态机非法转换 → 也包装为业务阻断(需人工 review)
            raise SMTPSendIllegalTransitionError(
                f"outbox_id={outbox_id} 业务阻断状态机非法转换: {e}"
            ) from e

        # 5. 构造 TaskPacket
        packet = build_send_blocked_packet(
            outbox_id=outbox_id,
            source=self._source,
            reason=reason,
        )

        # 6. 构造 context(业务阻断 cf 必为 0, 双向强一致)
        end_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        context = build_send_policy_context(
            outbox_id=outbox_id,
            tone=entry.tone,
            priority=entry.priority,
            subject_length=len(entry.subject),
            body_length=len(entry.body),
            last_send_failed=False,  # 业务阻断不计入失败(D4.7.3 v1.0.1 P1-1 范本)
            consecutive_send_failures=0,
            now_ms=end_ms,
        )

        # 7. run_id + lane_entry_id
        rid = run_id or str(end_ms)
        lane_entry_id = self.build_lane_entry_id(rid)

        # 8. PolicyEngine.evaluate
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=None,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload={
                "send_blocked": True,
                "kind": "business_blocked",
                "reason": reason,
                "outbox_id": outbox_id,
                "email_id": entry.email_id,
                "subject_length": len(entry.subject),
                "body_length": len(entry.body),
                "tone": entry.tone,
                "recipient_email": entry.recipient_email,
                "last_error": last_error_str,
                "source": self._source,
            },
        )

        # 9. LaneBoard 记录 — 业务阻断强制 BLOCKED
        existing: LaneEntry | None = None
        try:
            existing = self._board.get(lane_entry_id)
        except Exception:
            existing = None
        if existing is None:
            self._board.add(
                LaneEntry(
                    entry_id=lane_entry_id,
                    objective=f"Outbox send blocked source={self._source} reason={reason}",
                    status=LaneStatus.ACTIVE,
                    owner="email_send",
                )
            )
        self._board.update(lane_entry_id, status=LaneStatus.BLOCKED, owner="email_send")

        # 10. Heartbeat
        self._heartbeat.update(transport_alive=transport_alive, now_ms=end_ms)
        liveness = self._heartbeat.evaluate(now_ms=end_ms)

        return SendBlockedDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            last_error=last_error_str,
            reason=reason,
            outbox_id=outbox_id,
            email_id=entry.email_id,
            subject=entry.subject,
            body=entry.body,
            tone=entry.tone,
            recipient_email=entry.recipient_email,
            consecutive_send_failures=0,
        )

    # ===== 入口 3: 技术失败 =====

    def record_send_failure_and_emit(
        self,
        *,
        outbox_id: int,
        error_category: str,
        last_error: Any,  # str | Exception
        consecutive_send_failures: int = 1,
        retry_after_ms: int = 0,
        run_id: str = "",
        transport_alive: bool = True,
        now_ms: int | None = None,
    ) -> SendFailureDecisionReport:
        """技术失败发送入口(对应契约 1 技术失败路径 — 4 类异常白名单).

        Args:
            outbox_id: OutboxEntry.id(>= 1)
            error_category: 4 类白名单(transport_error / ssl_error / timeout / smtp_other)
            last_error: 失败原因描述(str | Exception)
            consecutive_send_failures: 失败累加器(>= 1, 默认 1, 双向强一致)
            retry_after_ms: 指数退避建议(>= 0, D5.5 联动, 默认 0)

        Returns:
            SendFailureDecisionReport: send_failed=True + cf >= 1 + last_error.strip() 非空
        """
        # 1. 严判入参
        if type(outbox_id) is bool or not isinstance(outbox_id, int) or outbox_id < 1:
            raise ValueError(
                f"outbox_id 必须是原生 int(非 bool) >= 1, 实际 "
                f"{type(outbox_id).__name__}={outbox_id!r}"
            )
        # error_category 白名单严判
        if type(error_category) is not str:
            raise ValueError(
                f"error_category 必须是 str, 实际 {type(error_category).__name__}={error_category!r}"
            )
        if error_category not in SEND_FAILURE_ERROR_CATEGORIES:
            raise ValueError(
                f"error_category 必须是 4 类白名单 {sorted(SEND_FAILURE_ERROR_CATEGORIES)!r},"
                f" 实际 {error_category!r}"
            )
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )
        if (
            type(consecutive_send_failures) is bool
            or not isinstance(consecutive_send_failures, int)
            or consecutive_send_failures < 1
        ):
            raise ValueError(
                f"consecutive_send_failures 必须是原生 int(非 bool) >= 1, 实际 "
                f"{type(consecutive_send_failures).__name__}={consecutive_send_failures!r}"
            )
        if (
            type(retry_after_ms) is bool
            or not isinstance(retry_after_ms, int)
            or retry_after_ms < 0
        ):
            raise ValueError(
                f"retry_after_ms 必须是原生 int(非 bool) >= 0, 实际 "
                f"{type(retry_after_ms).__name__}={retry_after_ms!r}"
            )

        store = self._require_outbox_store()

        # 2. 归一 last_error
        if isinstance(last_error, Exception):
            last_error_str = str(last_error)
        else:
            last_error_str = str(last_error) if last_error is not None else ""
        if not last_error_str.strip():
            raise ValueError(
                f"last_error 必填非空白(str | Exception), 实际 "
                f"{type(last_error).__name__}={last_error!r}"
            )

        # 3. 查 outbox(走 D5.2 by_id)
        entry = store.by_id(outbox_id)
        if entry is None:
            raise ValueError(f"outbox_id={outbox_id} 不存在,无法 record_send_failure_and_emit")

        # 4. 状态机推进: PENDING_SEND/APPROVED → SENDING → FAILED
        # 4a) 先推 SENDING(如果还没推)
        if entry.status in (
            OutboxStatus.PENDING_SEND.value,
            OutboxStatus.APPROVED.value,
        ):
            try:
                store.update_status(
                    outbox_id,
                    OutboxStatus.SENDING.value,
                    from_status=entry.status,
                )
            except OutboxIllegalTransitionError as e:
                raise SMTPSendIllegalTransitionError(
                    f"outbox_id={outbox_id} 技术失败 PENDING→SENDING 状态机非法转换: {e}"
                ) from e
            # 重新查(状态已变)
            entry = store.by_id(outbox_id)
            assert entry is not None  # noqa: S101 — by_id 已知存在

        # 4b) 推 SENDING → FAILED
        if entry.status != OutboxStatus.SENDING.value:
            # 已不在 SENDING(可能其他 process 已推到别的状态)
            raise ValueError(
                f"outbox_id={outbox_id} 状态={entry.status!r} 不在 SENDING,"
                f"无法走技术失败路径(已离开 SENDING 中间态)"
            )
        try:
            store.update_status(
                outbox_id,
                OutboxStatus.FAILED.value,
                from_status=OutboxStatus.SENDING.value,
            )
        except OutboxIllegalTransitionError as e:
            raise SMTPSendIllegalTransitionError(
                f"outbox_id={outbox_id} 技术失败 SENDING→FAILED 状态机非法转换: {e}"
            ) from e

        # 5. 构造 TaskPacket
        packet = build_send_failure_packet(
            outbox_id=outbox_id,
            source=self._source,
            consecutive_send_failures=consecutive_send_failures,
        )

        # 6. 构造 context(技术失败 cf 必为 >= 1, 双向强一致)
        end_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        context = build_send_policy_context(
            outbox_id=outbox_id,
            tone=entry.tone,
            priority=entry.priority,
            subject_length=len(entry.subject),
            body_length=len(entry.body),
            last_send_failed=True,  # 技术失败 ↔ cf >= 1
            consecutive_send_failures=consecutive_send_failures,
            now_ms=end_ms,
        )

        # 7. run_id + lane_entry_id
        rid = run_id or str(end_ms)
        lane_entry_id = self.build_lane_entry_id(rid)

        # 8. PolicyEngine.evaluate
        evaluation = self._engine.evaluate(
            packet=packet,
            context=context,
            store=None,
            lane_entry_id=lane_entry_id,
            run_id=rid,
            extra_business_payload={
                "send_failed": True,
                "consecutive_send_failures": consecutive_send_failures,
                "retry_after_ms": retry_after_ms,
                "error_category": error_category,
                "outbox_id": outbox_id,
                "email_id": entry.email_id,
                "subject_length": len(entry.subject),
                "body_length": len(entry.body),
                "tone": entry.tone,
                "recipient_email": entry.recipient_email,
                "last_error": last_error_str,
                "source": self._source,
            },
        )

        # 9. LaneBoard 记录 — 技术失败走 BLOCKED(caller 决定是否 retry)
        existing: LaneEntry | None = None
        try:
            existing = self._board.get(lane_entry_id)
        except Exception:
            existing = None
        if existing is None:
            self._board.add(
                LaneEntry(
                    entry_id=lane_entry_id,
                    objective=f"Outbox send failure source={self._source} "
                    f"cf={consecutive_send_failures}",
                    status=LaneStatus.ACTIVE,
                    owner="email_send",
                )
            )
        self._board.update(lane_entry_id, status=LaneStatus.BLOCKED, owner="email_send")

        # 10. Heartbeat
        self._heartbeat.update(transport_alive=transport_alive, now_ms=end_ms)
        liveness = self._heartbeat.evaluate(now_ms=end_ms)

        return SendFailureDecisionReport(
            evaluation=evaluation,
            event_id=evaluation.event_id,
            lane_entry_id=lane_entry_id,
            liveness=liveness,
            last_error=last_error_str,
            error_category=error_category,
            outbox_id=outbox_id,
            email_id=entry.email_id,
            subject=entry.subject,
            body=entry.body,
            tone=entry.tone,
            recipient_email=entry.recipient_email,
            consecutive_send_failures=consecutive_send_failures,
            retry_after_ms=retry_after_ms,
        )


# ===== 模块导出 =====


__all__ = [
    # 2 业务阻断 / 技术失败 白名单
    "SEND_BLOCK_REASON_VALUES",
    "SEND_FAILURE_ERROR_CATEGORIES",
    # 1 acceptance + 1 context
    "compute_send_acceptance",
    "build_send_policy_context",
    # 3 packet 工厂
    "build_send_packet",
    "build_send_blocked_packet",
    "build_send_failure_packet",
    # 3 DecisionReport
    "SendDecisionReport",
    "SendBlockedDecisionReport",
    "SendFailureDecisionReport",
    # 主类
    "EmailSendAdapter",
]
