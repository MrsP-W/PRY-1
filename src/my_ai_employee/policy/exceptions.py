"""D4.4 — Policy 业务异常(5 类窄化 + 编程错误透传).

参考 D3.3.3 教训: 异常范围要窄化到真要处理的类型.
- PolicyContractError    — TaskPacket 字段非法(8 必含字段校验失败)
- PolicyDecisionError    — 决策评估失败(rule 自身抛错或 context 信号非法)
- PolicyApprovalError    — 审批 token 缺失/失效(approval_token_id 校验)
- PolicyHeartbeatError   — Heartbeat 不健康(transport_dead)
- PolicyLaneError        — LaneBoard 状态错(transition 不合法)
- PolicyError            — 基类(不是 Exception 兜底)

ValueError / TypeError (编程错误) 透传, 不包装.
"""

from __future__ import annotations


class PolicyError(Exception):
    """Policy 业务异常基类.

    不继承具体业务类, 而是用 isinstance 判断细类.
    """


class PolicyContractError(PolicyError):
    """TaskPacket 字段非法(8 必含字段校验失败).

    例: objective="" / scope 为空 / model 不在 capability registry
    """


class PolicyDecisionError(PolicyError):
    """决策评估失败(rule 自身抛错或 context 信号非法).

    与 g006 §"executing policy decisions" 段对齐:
    rule 评估时缺关键信号(如 last_heartbeat_ms 缺失) → 抛此异常.
    """


class PolicyApprovalError(PolicyError):
    """审批 token 缺失/失效(approval_token_id 校验失败).

    与 g006 §"approval-token conditions" 段对齐:
    approval_token_id 为空但 approval_token_required=True → 抛此异常.
    """


class PolicyHeartbeatError(PolicyError):
    """Heartbeat 不健康(transport_dead 状态).

    与 g006 §"transport-dead" 段对齐:
    heartbeat.liveness == Liveness.TRANSPORT_DEAD → 抛此异常(若 caller 要求 strict).
    """


class PolicyLaneError(PolicyError):
    """LaneBoard 状态错(transition 不合法).

    例: FINISHED lane 不能再 add 新 entry; BLOCKED lane 不能直接 FINISHED
    (需先 ACTIVE → BLOCKED → ACTIVE → FINISHED 路径)
    """


# ===== D5.3 — SMTP 发送 4 类异常(异常窄化 D3.3.3 范本)=====
#
# 异常分类(沿 D3.3.3 教训 — 范围窄化,不接 smtplib.SMTPException / Exception 基类):
#   - 业务阻断(永久退信,永不重试): SMTPSendRecipientsRefusedError / SMTPSendSenderRefusedError
#   - 技术失败(瞬态错误,可重试):  SMTPSendTransportError
#   - 状态机非法转换:               SMTPSendIllegalTransitionError(继承 D5.2 异常基类)
#
# 设计要点:
#   - 全部继承 PolicyError(不直接继承 Exception,统一业务异常入口)
#   - 不接 smtplib.SMTPException / Exception 基类(避免掩盖真实生产问题)
#   - 调用方(D5.4 OutboxDispatcher)按 isinstance + 异常类名分流:
#     recipients_refused / sender_refused → 业务阻断入口(record_send_business_blocked_and_emit)
#     transport_error / illegal_transition → 技术失败入口(record_send_failure_and_emit)
#   - D4.7.3 v1.0.1 范本: 业务阻断 cf=0 永不 retry; 技术失败 cf>=1 触发 retry|escalate


class SMTPSendRecipientsRefusedError(PolicyError):
    """SMTP 收件人拒收异常(D5.3 — 业务阻断入口,永久退信,永不重试).

    触发场景:
        - smtplib.SMTPRecipientsRefused — SMTP 5xx 收件人地址被拒
        - smtplib.SMTPDataError 4xx — DATA 阶段数据错误

    调用方(D5.4 OutboxDispatcher)走 record_send_business_blocked_and_emit,
    consecutive_send_failures 不递增,recovery_policy="none"。
    """


class SMTPSendSenderRefusedError(PolicyError):
    """SMTP 发件人拒收异常(D5.3 — 业务阻断入口,凭据错或发件人未授权)。

    触发场景:
        - smtplib.SMTPSenderRefused — SMTP 发件人被服务器拒收(550 等)
        - smtplib.SMTPAuthenticationError — 认证失败(从 SmtpAuthError 透传)

    调用方(D5.4 OutboxDispatcher)走 record_send_business_blocked_and_emit,
    永不重试,需人工审查凭据或发件人配置。
    """


class SMTPSendTransportError(PolicyError):
    """SMTP 传输层错误(D5.3 — 技术失败入口,瞬态网络/服务器问题,可重试)。

    触发场景:
        - smtplib.SMTPServerDisconnected — 服务器意外断连
        - smtplib.SMTPConnectError — 连接失败
        - smtplib.SMTPException(其他,未识别子类)— 兜底技术失败
        - socket.timeout / TimeoutError — socket 超时
        - OSError / socket.gaierror — DNS 解析失败
        - ssl.SSLError — SSL 握手失败

    调用方(D5.4 OutboxDispatcher)走 record_send_failure_and_emit,
    consecutive_send_failures 递增,触发指数退避重试。
    """


class SMTPSendIllegalTransitionError(PolicyError):
    """SMTP 发送状态机非法转换异常(D5.3 — 透传 D5.2 OutboxIllegalTransitionError)。

    触发场景:
        - D5.2 OutboxStore.update_status(*, from_status) 抛 OutboxIllegalTransitionError
          时,EmailSendAdapter 捕获并包装为该异常(便于 D5.4 Dispatcher isinstance 判断)

    调用方(D5.4 OutboxDispatcher)按业务语义区分:
        - 状态漂移检测(concurrent write)→ 走 record_send_failure_and_emit(retry|escalate)
        - 白名单外转换(bug)→ 走 record_send_business_blocked_and_emit(需人工 review)
    """


__all__ = [
    "PolicyError",
    "PolicyContractError",
    "PolicyDecisionError",
    "PolicyApprovalError",
    "PolicyHeartbeatError",
    "PolicyLaneError",
    # D5.3 新增 4 类 SMTP 异常
    "SMTPSendRecipientsRefusedError",
    "SMTPSendSenderRefusedError",
    "SMTPSendTransportError",
    "SMTPSendIllegalTransitionError",
]
