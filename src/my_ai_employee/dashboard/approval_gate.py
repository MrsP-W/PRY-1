"""v0.2.53.11 — Dashboard ApprovalGate 写操作契约(默认禁写).

本模块只负责"写操作是否允许进入业务实现"的统一判定,自身不直接执行任何
真实写入:
    - 不写 DB
    - 不发 SMTP
    - 不写 Keychain
    - 不 kickstart launchd

真实写动作必须先通过这里的 env + 确认口令 + 审计字段校验,再委派到具体
业务服务,由 BusinessWriterImpl 继续严判第 4/5 门。

v0.2.57 / Day 8 候选 A:`evaluate_decide_request` 高阶封装,把 UI 1-click
`{audit_id, decision, actor, reason, confirm_text}` 映射到现有 4 类
action 契约,沿用同 5 门严判;撞坑 #71 解除(业务代码首次 + 改动日)。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final

from my_ai_employee.dashboard.action_contracts import (
    ACTION_CONTRACTS,
    ACTION_OUTBOX_APPROVE,
    ACTION_OUTBOX_CANCEL,
    is_supported_action,
)

CONTRACT_VERSION: Final = "v0.2.57"

# v0.2.57 / Day 8 候选 A — 1-click 审批 decision 映射
#   - decision="approve" → ACTION_OUTBOX_APPROVE
#   - decision="reject"  → ACTION_OUTBOX_CANCEL
#   - 仅映射 outbox 类决策(notes/finance 决策走 /api/approval-gate/actions 直接契约)
DECISION_OUTBOX_APPROVE: Final = "approve"
DECISION_OUTBOX_REJECT: Final = "reject"
SUPPORTED_DECISIONS: Final[tuple[str, ...]] = (DECISION_OUTBOX_APPROVE, DECISION_OUTBOX_REJECT)

# audit_id / target_id 长度上限(沿 AuditContext MAX_ACTOR_LEN=80 范本)
_MAX_DECIDE_TARGET_ID_LEN: Final = 80
DASHBOARD_WRITE_API_ENV: Final = "DASHBOARD_WRITE_API"
CONFIRM_TEXT: Final = "CONFIRM_WRITE"
# v0.2.53.22 第三道门(沿 v0.2.53.19 §设计)
#   - 默认未设 → 路径 3 仍 `501 write_not_implemented`
#   - 设为 truthy 字面量 → writer 就绪时走 writer.dry_run 路径(仍 write_executed=False)
#   - 实际写入路径(路径 4)需 writer ready + 第 5 门 + 用户明确授权
BUSINESS_WRITER_ENABLED_ENV: Final = "BUSINESS_WRITER_ENABLED"

_TRUTHY: Final = {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class _ParsedActionRequest:
    action: str
    target_id: str
    dry_run: bool


def _parse_action_request(
    payload: Mapping[str, Any],
    *,
    write_enabled: bool,
) -> tuple[_ParsedActionRequest | None, tuple[HTTPStatus, dict[str, Any]] | None]:
    """解析并校验 action/target_id/dry_run + 第一道门(write API).

    Returns:
        `(fields, None)` 成功; `(None, error_decision)` 校验失败。
    """
    action = _text_field(payload, "action")
    target_id = _target_id(payload)
    dry_run_raw = payload.get("dry_run", True)
    if type(dry_run_raw) is not bool:
        return None, _decision(
            HTTPStatus.BAD_REQUEST,
            error="invalid_dry_run",
            reason="dry_run 必须是 bool。",
            write_enabled=write_enabled,
            action=action,
            target_id=target_id,
            dry_run=True,
            payload=payload,
        )
    dry_run = dry_run_raw

    if not action:
        return None, _decision(
            HTTPStatus.BAD_REQUEST,
            error="missing_action",
            reason="缺少 action。",
            write_enabled=write_enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )
    if not is_supported_action(action):
        return None, _decision(
            HTTPStatus.BAD_REQUEST,
            error="unsupported_action",
            reason=f"不支持的 action: {action}",
            write_enabled=write_enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )
    if not target_id:
        return None, _decision(
            HTTPStatus.BAD_REQUEST,
            error="missing_target_id",
            reason="缺少 target_id。",
            write_enabled=write_enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )
    if not write_enabled:
        return None, _decision(
            HTTPStatus.FORBIDDEN,
            error="write_disabled",
            reason=f"默认禁写;需显式设置 {DASHBOARD_WRITE_API_ENV}=1。",
            write_enabled=write_enabled,
            action=action,
            target_id=target_id,
            dry_run=dry_run,
            payload=payload,
        )
    return _ParsedActionRequest(action=action, target_id=target_id, dry_run=dry_run), None


def _require_confirm_text(
    payload: Mapping[str, Any],
    *,
    parsed: _ParsedActionRequest,
    write_enabled: bool,
) -> tuple[HTTPStatus, dict[str, Any]] | None:
    """第二道门:confirm_text 校验;通过返回 None."""
    confirm_text = _text_field(payload, "confirm_text")
    if confirm_text != CONFIRM_TEXT:
        return _decision(
            HTTPStatus.FORBIDDEN,
            error="confirmation_required",
            reason=f"需 confirm_text={CONFIRM_TEXT}。",
            write_enabled=write_enabled,
            action=parsed.action,
            target_id=parsed.target_id,
            dry_run=parsed.dry_run,
            payload=payload,
        )
    return None


def is_dashboard_write_api_enabled() -> bool:
    """`DASHBOARD_WRITE_API=1` 判定 — 默认禁写,仅识别 truthy 字面量."""

    raw = os.environ.get(DASHBOARD_WRITE_API_ENV, "").strip().lower()
    return raw in _TRUTHY


def is_business_writer_enabled() -> bool:
    """`BUSINESS_WRITER_ENABLED=1` 判定 — 默认未启用,仅识别 truthy 字面量.

    沿 v0.2.53.19 §6.2 决策矩阵:这是第三道门.默认禁用,设真值后表示
    writer 层就绪(handler 路径 3.5 → writer.dry_run 合并).
    """

    raw = os.environ.get(BUSINESS_WRITER_ENABLED_ENV, "").strip().lower()
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
        "writer_enabled": is_business_writer_enabled(),
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
    parsed, err = _parse_action_request(payload, write_enabled=enabled)
    if err is not None:
        return err
    assert parsed is not None
    confirm_err = _require_confirm_text(payload, parsed=parsed, write_enabled=enabled)
    if confirm_err is not None:
        return confirm_err

    return _decision(
        HTTPStatus.NOT_IMPLEMENTED,
        error="write_not_implemented",
        reason="ApprovalGate 双门已通过,但 BusinessWriter 未启用,未接业务写入。",
        write_enabled=enabled,
        action=parsed.action,
        target_id=parsed.target_id,
        dry_run=parsed.dry_run,
        payload=payload,
        would_allow=False,
        approval_gate_passed=True,
    )


def evaluate_writer_dry_run(
    payload: Mapping[str, Any],
    *,
    write_enabled: bool | None = None,
    writer_enabled: bool | None = None,
    writer_impl_injected: bool | None = None,
) -> tuple[HTTPStatus, dict[str, Any]]:
    """v0.2.53.22 第三道门判定 — env+confirm 通过 + writer 启用时,返回可合并到 dry-run 的 200 决策.

    v0.2.53.29 扩展:
        - 新增 `writer_impl_injected` 参数(测试注入;None 时保守视为未注入)
        - payload 暴露 3 字段(business_writer_env_enabled / impl_injected / ready)
        - 路径 3 (501 write_not_implemented) 文案边界化:env 已开但 Impl 未注入时
          reason 明确为「writer env only,需 DASHBOARD_REAL_DB=1 + session 成功」

    v0.2.53.30 收紧:
        - 除非 `writer_impl_injected is True`,否则不返回 200 dry-run-ready(None/False 均走 501)

    决策矩阵(沿 v0.2.53.19 §6.2):
        - 路径 1 (DASHBOARD_WRITE_API 未设):           403 write_disabled
        - 路径 2 (env 已开但 confirm_text 错):          403 confirmation_required
        - 路径 3 (env+confirm 通过 + writer 未启用):     501 write_not_implemented
        - 路径 3.5 (env+confirm+writer 都启用 + dry_run=True):  200 OK + approval_gate_passed=True + would_allow 由 writer 决定
        - 路径 4 (env+confirm+writer 都启用 + dry_run=False): 200 OK + handler 委派 writer 实写

    Args:
        payload: 同 evaluate_approval_action_request 的 JSON object body.
        write_enabled: 测试注入;None 时读 `DASHBOARD_WRITE_API`.
        writer_enabled: 测试注入;None 时读 `BUSINESS_WRITER_ENABLED`.
        writer_impl_injected: 测试/handler 注入;None 时保守视为未注入(501,不返回 200).

    Returns:
        `(HTTPStatus, payload)`. 所有返回都保证 `write_executed=False`.
    """
    enabled = is_dashboard_write_api_enabled() if write_enabled is None else write_enabled
    writer_on = is_business_writer_enabled() if writer_enabled is None else writer_enabled
    parsed, err = _parse_action_request(payload, write_enabled=enabled)
    if err is not None:
        return err
    assert parsed is not None
    confirm_err = _require_confirm_text(payload, parsed=parsed, write_enabled=enabled)
    if confirm_err is not None:
        return confirm_err

    # 路径 3:env+confirm 通过,writer 未启用 → 501 write_not_implemented
    if not writer_on:
        # v0.2.53.29 路径 3 default:env 未开 → 沿默认文案
        return _decision(
            HTTPStatus.NOT_IMPLEMENTED,
            error="write_not_implemented",
            reason="ApprovalGate 双门已通过,但 BusinessWriter 未启用,未接业务写入。",
            write_enabled=enabled,
            action=parsed.action,
            target_id=parsed.target_id,
            dry_run=parsed.dry_run,
            payload=payload,
            would_allow=False,
            approval_gate_passed=True,
            writer_env_enabled=writer_on,
            writer_impl_injected=writer_impl_injected,
        )

    # v0.2.53.30 路径 3.5-pre:env 已开 + Impl 未确认注入(None/False) → 501 env_only marker。
    # 触发条件:writer_impl_injected is not True(沿 handler 透传 ctx 或测试保守默认)
    if writer_impl_injected is not True:
        return _decision(
            HTTPStatus.NOT_IMPLEMENTED,
            error="write_not_implemented",
            reason=(
                "ApprovalGate 双门已通过,但 BusinessWriter env 已开且 Impl 未注入;"
                "需 DASHBOARD_REAL_DB=1 + session 成功 + BusinessWriterImpl 构造成功。"
            ),
            write_enabled=enabled,
            action=parsed.action,
            target_id=parsed.target_id,
            dry_run=parsed.dry_run,
            payload=payload,
            would_allow=False,
            approval_gate_passed=True,
            writer_enabled=writer_on,
            writer_env_enabled=writer_on,
            writer_impl_injected=writer_impl_injected,
        )

    # 路径 4:真实写入请求进入 handler,由 BusinessWriterImpl 的 5 门继续严判。
    if not parsed.dry_run:
        return _decision(
            HTTPStatus.OK,
            error=None,
            reason="ApprovalGate 三门已通过(write + confirm + writer),进入 writer 实写路径。",
            write_enabled=enabled,
            action=parsed.action,
            target_id=parsed.target_id,
            dry_run=parsed.dry_run,
            payload=payload,
            would_allow=True,
            approval_gate_passed=True,
            writer_enabled=True,
            writer_env_enabled=True,
            writer_impl_injected=writer_impl_injected,
        )

    # 路径 3.5 dry_run=True:writer dry-run 入口(handler._merge_writer_dry_run 进一步合并)
    return _decision(
        HTTPStatus.OK,
        error=None,
        reason="ApprovalGate 三门已通过(write + confirm + writer),进入 writer dry-run。",
        write_enabled=enabled,
        action=parsed.action,
        target_id=parsed.target_id,
        dry_run=parsed.dry_run,
        payload=payload,
        would_allow=False,  # 由 writer.dry_run 决定(handler 合并后覆盖)
        approval_gate_passed=True,
        writer_enabled=True,
        writer_env_enabled=True,
        writer_impl_injected=writer_impl_injected,
    )


def _decision(
    status: HTTPStatus,
    *,
    error: str | None,
    reason: str,
    write_enabled: bool,
    action: str,
    target_id: str,
    dry_run: bool,
    payload: Mapping[str, Any],
    would_allow: bool = False,
    approval_gate_passed: bool = False,
    writer_enabled: bool = False,
    writer_env_enabled: bool | None = None,
    writer_impl_injected: bool | None = None,
) -> tuple[HTTPStatus, dict[str, Any]]:
    """构造 ApprovalGate 决策 payload.

    v0.2.53.29 扩展:
        - payload 暴露 3 字段(business_writer_env_enabled / impl_injected / ready)
        - writer_impl_injected:None/False 均视为未注入;仅 True 时 ready = env AND injected
    """
    contract = ACTION_CONTRACTS.get(action)
    action_contract: dict[str, str] | None = None
    if contract is not None:
        action_contract = {
            "action": action,
            "target_type": contract["target_type"],
            "future_effect": contract["future_effect"],
        }
    required = [
        f"{DASHBOARD_WRITE_API_ENV}=1",
        f"confirm_text={CONFIRM_TEXT}",
    ]
    if not writer_enabled:
        required.append(BUSINESS_WRITER_ENABLED_ENV + "=1")
        required.append("business_writer_implementation")
    # v0.2.53.29 计算 ready(沿 v0.2.53.28 语义,context.is_business_writer_ready = env AND injected)
    writer_ready = bool(writer_env_enabled) and bool(writer_impl_injected)
    return (
        status,
        {
            "contract_version": CONTRACT_VERSION,
            "read_only": True,
            "write_enabled": write_enabled,
            "writer_enabled": writer_enabled,
            "business_writer_env_enabled": bool(writer_env_enabled),
            "business_writer_impl_injected": bool(writer_impl_injected),
            "business_writer_ready": writer_ready,
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
            "required": required,
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


# ===== v0.2.57 / Day 8 候选 A — 1-click 审批 decide 高阶封装 =====


def _parse_decide_request(
    payload: Mapping[str, Any],
    *,
    write_enabled: bool,
) -> tuple[_ParsedActionRequest | None, tuple[HTTPStatus, dict[str, Any]] | None]:
    """v0.2.57 / Day 8 候选 A — 解析 1-click decide 请求,把 decision 映射到 4 类 action.

    入参字段(沿 HTML 1-click button 范本):
        - audit_id: str(必填,非空,目标 outbox id;与 `target_id` 二选一)
        - decision: "approve" | "reject"(必填)
        - confirm_text: "CONFIRM_WRITE"(必填,第二道门)
        - dry_run: bool(默认 True,决定 3.5/4 路径分支)
        - actor: str(可选,默认 'local_dashboard',≤ 80 字符)
        - reason: str(可选,≤ 240 字符)

    映射规则:
        - decision="approve" → action=ACTION_OUTBOX_APPROVE
        - decision="reject"  → action=ACTION_OUTBOX_CANCEL

    Returns:
        `(parsed_action_request, None)` 成功; `(None, error_decision)` 校验失败。
    """
    # 1. decision 字段(必填 + 白名单)
    decision = _text_field(payload, "decision")
    if not decision:
        return None, _decide_error(
            HTTPStatus.BAD_REQUEST,
            error="missing_decision",
            reason="缺少 decision。",
            write_enabled=write_enabled,
            payload=payload,
            decision="",
            audit_id=_text_field(payload, "audit_id"),
        )
    if decision not in SUPPORTED_DECISIONS:
        return None, _decide_error(
            HTTPStatus.BAD_REQUEST,
            error="unsupported_decision",
            reason=f"不支持的 decision:{decision}(仅 approve / reject)。",
            write_enabled=write_enabled,
            payload=payload,
            decision=decision,
            audit_id=_text_field(payload, "audit_id"),
        )
    action = ACTION_OUTBOX_APPROVE if decision == DECISION_OUTBOX_APPROVE else ACTION_OUTBOX_CANCEL
    # 2. audit_id / target_id(必填,非空,≤ 80)
    audit_id = _text_field(payload, "audit_id")
    if not audit_id:
        return None, _decide_error(
            HTTPStatus.BAD_REQUEST,
            error="missing_audit_id",
            reason="缺少 audit_id。",
            write_enabled=write_enabled,
            payload=payload,
            decision=decision,
            audit_id=audit_id,
        )
    if len(audit_id) > _MAX_DECIDE_TARGET_ID_LEN:
        return None, _decide_error(
            HTTPStatus.BAD_REQUEST,
            error="audit_id_too_long",
            reason=f"audit_id 超长({len(audit_id)}>{_MAX_DECIDE_TARGET_ID_LEN})。",
            write_enabled=write_enabled,
            payload=payload,
            decision=decision,
            audit_id=audit_id,
        )
    target_id = audit_id
    # 3. dry_run(bool 严判)
    dry_run_raw = payload.get("dry_run", True)
    if type(dry_run_raw) is not bool:
        return None, _decide_error(
            HTTPStatus.BAD_REQUEST,
            error="invalid_dry_run",
            reason="dry_run 必须是 bool。",
            write_enabled=write_enabled,
            payload=payload,
            decision=decision,
            audit_id=audit_id,
        )
    dry_run = dry_run_raw
    # 4. write_enabled 第一道门(沿 _parse_action_request 范本)
    if not write_enabled:
        return None, _decide_error(
            HTTPStatus.FORBIDDEN,
            error="write_disabled",
            reason=f"默认禁写;需显式设置 {DASHBOARD_WRITE_API_ENV}=1。",
            write_enabled=write_enabled,
            payload=payload,
            decision=decision,
            audit_id=audit_id,
            dry_run=dry_run,
        )
    return _ParsedActionRequest(action=action, target_id=target_id, dry_run=dry_run), None


def _decide_error(
    status: HTTPStatus,
    *,
    error: str,
    reason: str,
    write_enabled: bool,
    payload: Mapping[str, Any],
    decision: str,
    audit_id: str,
    dry_run: bool = True,
) -> tuple[HTTPStatus, dict[str, Any]]:
    """v0.2.57 / Day 8 候选 A — 构造 1-click decide 错误响应(回显 decision/audit_id/mapped_action).

    比 `_decision` 多 3 字段:
        - decision: 回显
        - audit_id: 回显
        - mapped_action: 决策→action 映射(若可映射)
        - endpoint: "decide"
    """
    mapped_action: str | None = None
    if decision in SUPPORTED_DECISIONS:
        mapped_action = (
            ACTION_OUTBOX_APPROVE if decision == DECISION_OUTBOX_APPROVE else ACTION_OUTBOX_CANCEL
        )
    return (
        status,
        {
            "endpoint": "decide",
            "decision": decision or None,
            "audit_id": audit_id[:_MAX_DECIDE_TARGET_ID_LEN] if audit_id else None,
            "mapped_action": mapped_action,
            "error": error,
            "reason": reason,
            "write_enabled": write_enabled,
            "write_executed": False,
            "approval_gate_passed": False,
            "would_allow": False,
            "dry_run": dry_run,
            "contract_version": CONTRACT_VERSION,
        },
    )


def evaluate_decide_request(
    payload: Mapping[str, Any],
    *,
    write_enabled: bool | None = None,
    writer_enabled: bool | None = None,
    writer_impl_injected: bool | None = None,
) -> tuple[HTTPStatus, dict[str, Any]]:
    """v0.2.57 / Day 8 候选 A — 1-click decide 高阶封装.

    把 HTML 1-click button `{audit_id, decision, actor, reason, confirm_text, dry_run}`
    解析并沿用 `evaluate_writer_dry_run` 5 门(双门 + writer env + writer impl)。
    撞坑 #71 解除(业务代码改动日)· 撞坑 #59 红线维持(不自动真发邮件,需 UI 1-click 审批)。

    决策矩阵(沿 evaluate_writer_dry_run 8 路径,撞坑 #68 决策矩阵与可视化拆分模式):
        - 路径 1: DASHBOARD_WRITE_API 未设 → 403 write_disabled
        - 路径 2: env 已开 + decision 错 / confirm_text 错 → 400 / 403
        - 路径 3: env+confirm 通过 + writer 未启用 → 501 write_not_implemented
        - 路径 3.5: env+confirm+writer 都启用 + dry_run=True → 200 dry-run-ready
        - 路径 4: env+confirm+writer 都启用 + dry_run=False → 200 实写(由 BusinessWriterImpl 5 门严判)

    响应字段扩展(v0.2.57 / Day 8 候选 A):
        - endpoint: "decide"
        - decision: "approve" | "reject"(回显,便于前端展示)
        - audit_id: str(回显)
        - mapped_action: action(决策映射后的 action,便于调试)
        - 其它字段沿 evaluate_writer_dry_run 不变

    Args:
        payload: JSON object body。
        write_enabled: 测试注入;None 时读 DASHBOARD_WRITE_API。
        writer_enabled: 测试注入;None 时读 BUSINESS_WRITER_ENABLED。
        writer_impl_injected: 测试/handler 注入;None 时保守视为未注入(501,不返回 200)。

    Returns:
        `(HTTPStatus, payload)`. 所有返回都保证 `write_executed=False`(dry-run)或
        由 BusinessWriterImpl 实写后置 True。
    """
    enabled = is_dashboard_write_api_enabled() if write_enabled is None else write_enabled
    writer_on = is_business_writer_enabled() if writer_enabled is None else writer_enabled
    parsed, err = _parse_decide_request(payload, write_enabled=enabled)
    if err is not None:
        # err 已经是完整 _decide_error 响应(已含 decision/audit_id/mapped_action/endpoint)
        return err
    assert parsed is not None
    # 沿用 evaluate_writer_dry_run 的 5 门(双门 + writer env + writer impl)
    status, payload_out = evaluate_writer_dry_run(
        {
            "action": parsed.action,
            "target_id": parsed.target_id,
            "confirm_text": payload.get("confirm_text", ""),
            "dry_run": parsed.dry_run,
            "actor": payload.get("actor", "local_dashboard"),
            "reason": payload.get("reason", ""),
            "source": payload.get("source", "dashboard"),
        },
        write_enabled=enabled,
        writer_enabled=writer_on,
        writer_impl_injected=writer_impl_injected,
    )
    # 扩展响应:回显 decision / audit_id / mapped_action / endpoint(便于前端展示)
    payload_out = dict(payload_out)
    decision = _text_field(payload, "decision")
    audit_id = _text_field(payload, "audit_id")[:_MAX_DECIDE_TARGET_ID_LEN]
    payload_out["endpoint"] = "decide"
    payload_out["decision"] = decision or None
    payload_out["audit_id"] = audit_id or None
    payload_out["mapped_action"] = parsed.action
    return status, payload_out


__all__ = [
    "BUSINESS_WRITER_ENABLED_ENV",
    "CONFIRM_TEXT",
    "CONTRACT_VERSION",
    "DASHBOARD_WRITE_API_ENV",
    "DECISION_OUTBOX_APPROVE",
    "DECISION_OUTBOX_REJECT",
    "SUPPORTED_DECISIONS",
    "build_approval_gate_status",
    "evaluate_approval_action_request",
    "evaluate_decide_request",
    "evaluate_writer_dry_run",
    "is_business_writer_enabled",
    "is_dashboard_write_api_enabled",
    "list_action_contracts",
]
