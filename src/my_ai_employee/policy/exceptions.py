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


__all__ = [
    "PolicyError",
    "PolicyContractError",
    "PolicyDecisionError",
    "PolicyApprovalError",
    "PolicyHeartbeatError",
    "PolicyLaneError",
]
