"""Dashboard 写动作契约 — ApprovalGate 与 BusinessWriter 共用白名单.

避免 `approval_gate.py` / `business_writer.py` / `business_writer_impl.py`
各自维护 4 类 action 导致漂移。
"""

from __future__ import annotations

from typing import Final

ACTION_OUTBOX_APPROVE: Final = "outbox.approve"
ACTION_OUTBOX_CANCEL: Final = "outbox.cancel"
ACTION_NOTES_CONFIRM: Final = "notes.confirm"
ACTION_FINANCE_DISMISS_ANOMALY: Final = "finance.dismiss_anomaly"

SUPPORTED_ACTIONS: Final[tuple[str, ...]] = (
    ACTION_OUTBOX_APPROVE,
    ACTION_OUTBOX_CANCEL,
    ACTION_NOTES_CONFIRM,
    ACTION_FINANCE_DISMISS_ANOMALY,
)

ACTION_CONTRACTS: Final[dict[str, dict[str, str]]] = {
    ACTION_OUTBOX_APPROVE: {
        "target_type": "outbox",
        "description": "审批邮件草稿,未来从 pending_send 推到 approved。",
        "future_effect": "DB status update only; Dispatcher 仍需独立 SMTP 门控。",
    },
    ACTION_OUTBOX_CANCEL: {
        "target_type": "outbox",
        "description": "取消邮件草稿,未来从 pending_send/approved 推到 cancelled。",
        "future_effect": "DB status update only; 不触发 SMTP。",
    },
    ACTION_NOTES_CONFIRM: {
        "target_type": "note",
        "description": "确认 Apple Notes 候选,未来清除 needs_confirm。",
        "future_effect": "DB note status update only。",
    },
    ACTION_FINANCE_DISMISS_ANOMALY: {
        "target_type": "finance_anomaly",
        "description": "忽略财务异常提示,未来写入本地审计/忽略标记。",
        "future_effect": "DB audit marker only; 不导入账单。",
    },
}


def is_supported_action(action: str) -> bool:
    """4 类写动作白名单严判."""
    return action in ACTION_CONTRACTS


__all__ = [
    "ACTION_CONTRACTS",
    "ACTION_FINANCE_DISMISS_ANOMALY",
    "ACTION_NOTES_CONFIRM",
    "ACTION_OUTBOX_APPROVE",
    "ACTION_OUTBOX_CANCEL",
    "SUPPORTED_ACTIONS",
    "is_supported_action",
]
