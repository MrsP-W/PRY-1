"""L5 Web Dashboard — 本地 Dashboard API.

默认绑定 127.0.0.1,主路径只读 GET:
    - /api/status
    - /api/tasks/today
    - /api/reports
    - /api/reports/preview

v0.2.53.11 起提供 `POST /api/approval-gate/actions` 写操作契约端点,当前只做
校验/拒绝/审计预览,不执行真实写入。

v0.2.53.15 起新增 `BusinessWriter` Protocol + Stub + `AuditContext` +
`WriteResult` + `WriteDecision`(沿 v0.2.53.14 设计骨架;默认全 Stub)。

v0.2.57 / Day 8 候选 A 起新增 `POST /api/approval-gate/decide` 1-click 审批
高阶封装(沿 evaluate_decide_request),`{audit_id, decision: approve|reject,
actor, reason, confirm_text, dry_run}` → 现有 4 类 action 契约,沿用同 5 门。
"""

from my_ai_employee.dashboard.business_writer import (
    ACTION_FINANCE_DISMISS_ANOMALY,
    ACTION_NOTES_CONFIRM,
    ACTION_OUTBOX_APPROVE,
    ACTION_OUTBOX_CANCEL,
    SUPPORTED_ACTIONS,
    AuditContext,
    BusinessWriter,
    BusinessWriterStub,
    WriteDecision,
    WriteResult,
)
from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.server import create_server, run_server

__all__ = [
    "ACTION_FINANCE_DISMISS_ANOMALY",
    "ACTION_NOTES_CONFIRM",
    "ACTION_OUTBOX_APPROVE",
    "ACTION_OUTBOX_CANCEL",
    "AuditContext",
    "BusinessWriter",
    "BusinessWriterStub",
    "DashboardContext",
    "SUPPORTED_ACTIONS",
    "WriteDecision",
    "WriteResult",
    "create_server",
    "run_server",
]
