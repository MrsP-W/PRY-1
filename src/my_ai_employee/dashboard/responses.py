"""Dashboard 只读 JSON 响应构建."""

from __future__ import annotations

import os
from typing import Any

from my_ai_employee.core.keychain import (
    SERVICE_SMTP_GMAIL,
    SERVICE_SMTP_OUTLOOK,
    SERVICE_SMTP_QQ,
)
from my_ai_employee.dashboard.context import DashboardContext, safe_count


def build_status_payload(ctx: DashboardContext) -> dict[str, Any]:
    """GET /api/status — 系统健康 + 门控状态(只读)."""
    smtp_real = os.environ.get("SMTP_REAL_NETWORK", "").strip() in {"1", "true", "yes"}
    keychain = {
        "smtp_qq": "present" if ctx.keychain_probe(SERVICE_SMTP_QQ) else "missing",
        "smtp_outlook": "present" if ctx.keychain_probe(SERVICE_SMTP_OUTLOOK) else "missing",
        "smtp_gmail": "present" if ctx.keychain_probe(SERVICE_SMTP_GMAIL) else "missing",
    }
    qg = ctx.quality_gates
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
