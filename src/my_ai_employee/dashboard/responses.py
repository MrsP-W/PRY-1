"""Dashboard 只读 JSON 响应构建."""

from __future__ import annotations

import os
from typing import Any

from my_ai_employee.core.keychain import (
    SERVICE_SMTP_GMAIL,
    SERVICE_SMTP_OUTLOOK,
    SERVICE_SMTP_QQ,
)
from my_ai_employee.dashboard.approval_gate import build_approval_gate_status
from my_ai_employee.dashboard.context import DashboardContext, safe_count, safe_list
from my_ai_employee.dashboard.reports import read_report_preview, safe_scan, scan_reports


def build_status_payload(ctx: DashboardContext) -> dict[str, Any]:
    """GET /api/status — 系统健康 + 门控状态(只读)."""
    smtp_real = os.environ.get("SMTP_REAL_NETWORK", "").strip() in {"1", "true", "yes"}
    keychain = {
        "smtp_qq": "present" if ctx.keychain_probe(SERVICE_SMTP_QQ) else "missing",
        "smtp_outlook": "present" if ctx.keychain_probe(SERVICE_SMTP_OUTLOOK) else "missing",
        "smtp_gmail": "present" if ctx.keychain_probe(SERVICE_SMTP_GMAIL) else "missing",
    }
    qg = ctx.quality_gates
    approval_gate = build_approval_gate_status()
    return {
        "read_only": True,
        "version": ctx.version,
        "git_head": ctx.git_head_resolver(),
        "quality_gates": {
            "pytest": qg.pytest,
            "coverage": qg.coverage,
            "mypy": qg.mypy,
            "lint": qg.lint,
        },
        "providers": {
            "smtp_real_network": smtp_real,
            "keychain": keychain,
        },
        "approval_gates": {
            "real_smtp": smtp_real
            and (
                keychain["smtp_outlook"] == "present"
                or keychain["smtp_gmail"] == "present"
                or keychain["smtp_qq"] == "present"
            ),
            "keychain_write": False,
            "real_bill_import": False,
            "launchd_kickstart": False,
            "tag_create": False,
            "dashboard_write_api": approval_gate["write_enabled"],
            "write_contract_version": approval_gate["contract_version"],
            "write_actions": approval_gate["actions"],
        },
    }


def build_tasks_today_payload(ctx: DashboardContext) -> dict[str, Any]:
    """GET /api/tasks/today — 今日待办摘要(只读)."""
    mail_count = safe_count(ctx.outbox_draft_service.get_pending_draft_count)
    notes_count = safe_count(ctx.note_confirm_service.get_pending_confirm_count)
    anomaly_count = safe_count(ctx.expense_service.get_anomaly_count)

    tasks: list[dict[str, Any]] = [
        {
            "id": "mail_drafts",
            "title": "邮件草稿待审批",
            "count": mail_count,
            "category": "mail",
            "priority": "high" if mail_count else "normal",
        },
        {
            "id": "notes_confirm",
            "title": "Notes待确认",
            "count": notes_count,
            "category": "notes",
            "priority": "high" if notes_count else "normal",
        },
        {
            "id": "finance_anomaly",
            "title": "财务异常",
            "count": anomaly_count,
            "category": "finance",
            "priority": "high" if anomaly_count else "normal",
        },
    ]
    total = mail_count + notes_count + anomaly_count
    return {
        "read_only": True,
        "total": total,
        "tasks": tasks,
    }


def build_outbox_payload(ctx: DashboardContext, *, limit: int = 10) -> dict[str, Any]:
    """GET /api/outbox — 邮件草稿队列(只读)."""
    items = safe_list(lambda: ctx.outbox_draft_service.list_pending_drafts(limit))
    count = safe_count(ctx.outbox_draft_service.get_pending_draft_count)
    return {"read_only": True, "count": count, "items": items}


def build_notes_pending_payload(ctx: DashboardContext, *, limit: int = 10) -> dict[str, Any]:
    """GET /api/notes/pending — Notes 待确认列表(只读)."""
    items = safe_list(lambda: ctx.note_confirm_service.list_pending_confirm(limit))
    count = safe_count(ctx.note_confirm_service.get_pending_confirm_count)
    return {"read_only": True, "count": count, "items": items}


def build_finance_anomalies_payload(ctx: DashboardContext, *, limit: int = 10) -> dict[str, Any]:
    """GET /api/finance/anomalies — 财务异常列表(只读)."""
    items = safe_list(lambda: ctx.expense_service.get_recent_anomalies(limit))
    count = safe_count(ctx.expense_service.get_anomaly_count)
    return {"read_only": True, "count": count, "items": items}


def build_reports_payload(
    _ctx: DashboardContext, *, limit: int = 50, type_filter: str | None = None
) -> dict[str, Any]:
    """GET /api/reports — 本地报告清单(只读文件系统扫描).

    Args:
        _ctx: 保持与其他 build_* 一致签名(此端点不依赖 ctx 服务)
        limit: 最大返回条数,[1,100] int
        type_filter: 可选,仅返回指定 type(doc/phase_report/spike/agent_output)

    Returns:
        dict with: read_only, count, items[](path/type/title/date/status/size_bytes)
    """
    items = safe_scan(lambda: scan_reports(limit=limit, type_filter=type_filter))
    return {
        "read_only": True,
        "count": len(items),
        "items": [
            {
                "path": e.path,
                "type": e.type,
                "title": e.title,
                "date": e.date,
                "status": e.status,
                "size_bytes": e.size_bytes,
            }
            for e in items
        ],
    }


def build_report_preview_payload(rel_path: str) -> dict[str, Any] | None:
    """GET /api/reports/preview — 单份报告截断预览(只读).

    Args:
        rel_path: 相对项目根的路径(须通过 reports._resolve_report_path 严判)

    Returns:
        预览 dict 或 None(路径非法 / 文件不可读)。
    """
    preview = read_report_preview(rel_path)
    if preview is None:
        return None
    return {"read_only": True, **preview}
