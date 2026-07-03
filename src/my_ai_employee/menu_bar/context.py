"""Menu bar 服务上下文 — opt-in 真实 Impl 注入(沿 DashboardContext 范本).

门控:`DASHBOARD_REAL_DB=1` 时尝试注入 Expense / NoteConfirm / Outbox 真实 Impl;
失败静默降级 Stub,不阻塞菜单栏启动。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from my_ai_employee.menu_bar.expense_service import ExpenseService, ExpenseServiceStub
from my_ai_employee.menu_bar.note_confirm_service import (
    NoteConfirmService,
    NoteConfirmServiceStub,
)
from my_ai_employee.menu_bar.outbox_draft_service import (
    OutboxDraftService,
    OutboxDraftServiceStub,
)


@dataclass(slots=True)
class MenuBarServices:
    """菜单栏 3 类只读服务容器."""

    expense_service: ExpenseService = field(default_factory=ExpenseServiceStub.get_default_stub)
    note_confirm_service: NoteConfirmService = field(
        default_factory=NoteConfirmServiceStub.get_default_stub
    )
    outbox_draft_service: OutboxDraftService = field(
        default_factory=OutboxDraftServiceStub.get_default_stub
    )


def build_menu_bar_services() -> MenuBarServices:
    """构建菜单栏服务 — 默认 Stub;`DASHBOARD_REAL_DB=1` 时 opt-in 真实 Impl."""
    from my_ai_employee.dashboard.context import (
        _is_real_db_enabled,
        _try_build_expense_from_session_factory,
        _try_build_note_confirm_from_session_factory,
        _try_build_outbox_from_session_factory,
        _try_build_real_session_factory,
    )

    services = MenuBarServices()
    if not _is_real_db_enabled():
        return services
    session_factory = _try_build_real_session_factory()
    if session_factory is None:
        return services
    outbox = _try_build_outbox_from_session_factory(session_factory)
    if outbox is not None:
        services.outbox_draft_service = outbox
    note_confirm = _try_build_note_confirm_from_session_factory(session_factory)
    if note_confirm is not None:
        services.note_confirm_service = note_confirm
    expense = _try_build_expense_from_session_factory(session_factory)
    if expense is not None:
        services.expense_service = expense
    return services


__all__ = ["MenuBarServices", "build_menu_bar_services"]
