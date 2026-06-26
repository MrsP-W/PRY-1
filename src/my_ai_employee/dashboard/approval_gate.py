"""v0.2.53.11 — Dashboard ApprovalGate 写操作契约(默认禁写).

本模块只负责"写操作是否允许进入业务实现"的统一判定,当前阶段不执行任何
真实写入:
    - 不写 DB
    - 不发 SMTP
    - 不写 Keychain
    - 不 kickstart launchd

未来真实写动作必须先通过这里的 env + 确认口令 + 审计字段校验,再委派到具体
业务服务。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, Final

from my_ai_employee.dashboard.action_contracts import ACTION_CONTRACTS, is_supported_action

CONTRACT_VERSION: Final = "v0.2.53.11"
DASHBOARD_WRITE_API_ENV: Final = "DASHBOARD_WRITE_API"
CONFIRM_TEXT: Final = "CONFIRM_WRITE"

_TRUTHY: Final = {"1", "true", "yes", "on"}


def is_dashboard_write_api_enabled() -> bool:
    """`DASHBOARD_WRITE_API=1` 判定 — 默认禁写,仅识别 truthy 字面量."""

    raw = os.environ.get(DASHBOARD_WRITE_API_ENV, "").strip().lower()
    return raw in _TRUTHY


def list_action_contracts() -> list[dict[str, str]]:
    """返回前端可展示的写动作契约(无敏感信息)."""

    return [
        {
            "action": action,
            "target_type": contract["target_type"],
            "description": contract["description"],
            "future_effect": contract["future_effect"],
            "required_confirm_text": CONFIRM_TEXT,
        }
        for action, contract in sorted(ACTION_CONTRACTS.items())
    ]


def build_approval_gate_status() -> dict[str, Any]:
    """返回 Dashboard status 可嵌入的 ApprovalGate 状态."""

    return {
        "contract_version": CONTRACT_VERSION,
        "write_enabled": is_dashboard_write_api_enabled(),
        "write_executed": False,
        "confirm_text": CONFIRM_TEXT,
        "actions": list_action_contracts(),
    }


def evaluate_approval_action_request(
    payload: Mapping[str, Any],
    *,
    write_enabled: bool | None = None,
) -> tuple[HTTPStatus, dict[str, Any]]:
    """校验 ApprovalGate POST 请求,当前阶段不执行真实写入.

    Args:
        payload: JSON object body.
        write_enabled: 测试注入;None 时读取 `DASHBOARD_WRITE_API`.

    Returns:
        `(HTTPStatus, payload)`。所有返回都保证 `write_executed=False`。
    """

    enabled = is_dashboard_write_api_enabled() if write_enabled is None else write_enabled
    action = _text_field(payload, "action")
    target_id = _target_id(payload)
    dry_run_raw = payload.get("dry_run", True)
    if type(dry_run_raw) is not bool:
        return _decision(
            HTTPStatus.BAD_REQUEST,
            error="invalid_dry_run",
            reason="dry_run 必须是 bool。",
            write_enabled=enabled,
            action=action,
            target_id=target_id,
            dry_run=True,
            payload=payload,
        )
    dry_run = dry_run_raw

    if not action:
        return _decision(
            HTTPStatus.BAD_REQUEST,
            error="missing_action",
            reason="缺少 action。",
            write_enabled=enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )
    if not is_supported_action(action):
        return _decision(
            HTTPStatus.BAD_REQUEST,
            error="unsupported_action",
            reason=f"不支持的 action: {action}",
            write_enabled=enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )
    if not target_id:
        return _decision(
            HTTPStatus.BAD_REQUEST,
            error="missing_target_id",
            reason="缺少 target_id。",
            write_enabled=enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )

    if not enabled:
        return _decision(
            HTTPStatus.FORBIDDEN,
            error="write_disabled",
            reason=f"默认禁写;需显式设置 {DASHBOARD_WRITE_API_ENV}=1。",
            write_enabled=enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )

    confirm_text = _text_field(payload, "confirm_text")
    if confirm_text != CONFIRM_TEXT:
        return _decision(
            HTTPStatus.FORBIDDEN,
            error="confirmation_required",
            reason=f"需 confirm_text={CONFIRM_TEXT}。",
            write_enabled=enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )

    return _decision(
        HTTPStatus.NOT_IMPLEMENTED,
        error="write_not_implemented",
        reason="ApprovalGate 双门已通过,但 BusinessWriter 未启用,未接业务写入。",
        write_enabled=enabled,
        action=action,
        target_id=target_id,
        dry_run=dry_run,
        payload=payload,
        would_allow=False,
        approval_gate_passed=True,
    )


def _decision(
    status: HTTPStatus,
    *,
    error: str,
    reason: str,
    write_enabled: bool,
    action: str,
    target_id: str,
    dry_run: bool,
    payload: Mapping[str, Any],
    would_allow: bool = False,
    approval_gate_passed: bool = False,
) -> tuple[HTTPStatus, dict[str, Any]]:
    contract = ACTION_CONTRACTS.get(action)
    action_contract: dict[str, str] | None = None
    if contract is not None:
        action_contract = {
            "action": action,
            "target_type": contract["target_type"],
            "future_effect": contract["future_effect"],
        }
    return (
        status,
        {
            "contract_version": CONTRACT_VERSION,
            "read_only": True,
            "write_enabled": write_enabled,
            "write_executed": False,
            "would_allow": would_allow,
            "approval_gate_passed": approval_gate_passed,
            "dry_run": dry_run,
            "error": error,
            "reason": reason,
            "action": action or None,
            "target_id": target_id or None,
            "action_contract": action_contract,
            "audit": {
                "actor": _bounded_text(payload, "actor", default="local_dashboard", limit=80),
                "reason": _bounded_text(payload, "reason", default="", limit=240),
                "source": "dashboard",
            },
            "required": [
                f"{DASHBOARD_WRITE_API_ENV}=1",
                f"confirm_text={CONFIRM_TEXT}",
                "business_writer_implementation",
            ],
        },
    )


def _text_field(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def _target_id(payload: Mapping[str, Any]) -> str:
    value = payload.get("target_id")
    if isinstance(value, str):
        return value.strip()
    if type(value) is int:
        return str(value)
    return ""


def _bounded_text(
    payload: Mapping[str, Any],
    key: str,
    *,
    default: str,
    limit: int,
) -> str:
    text = _text_field(payload, key) or default
    return text[:limit]


__all__ = [
    "CONFIRM_TEXT",
    "CONTRACT_VERSION",
    "DASHBOARD_WRITE_API_ENV",
    "build_approval_gate_status",
    "evaluate_approval_action_request",
    "is_dashboard_write_api_enabled",
    "list_action_contracts",
]
