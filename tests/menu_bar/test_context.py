"""MenuBarServices / build_menu_bar_services 单测."""

from __future__ import annotations

import pytest

from my_ai_employee.menu_bar.context import build_menu_bar_services
from my_ai_employee.menu_bar.expense_service import ExpenseServiceStub
from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceStub
from my_ai_employee.menu_bar.outbox_draft_service import OutboxDraftServiceStub


def test_default_env_returns_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHBOARD_REAL_DB", raising=False)
    services = build_menu_bar_services()
    assert isinstance(services.expense_service, ExpenseServiceStub)
    assert isinstance(services.note_confirm_service, NoteConfirmServiceStub)
    assert isinstance(services.outbox_draft_service, OutboxDraftServiceStub)


def test_real_db_env_injects_impl_when_session_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl
    from my_ai_employee.menu_bar.outbox_draft_service import OutboxDraftServiceImpl

    class _FakeOutbox:
        def by_status(self, status: str, limit: int = 100) -> list[object]:
            return []

    class _FakeNoteStore:
        def count_by_needs_confirm(self, limit: int = 10_000) -> int:
            return 0

        def list_by_needs_confirm(self, limit: int = 10) -> list[object]:
            return []

        def mark_archived(self, apple_note_id: str) -> None:
            pass

    monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
    sentinel = object()
    monkeypatch.setattr(
        "my_ai_employee.dashboard.context._try_build_real_session_factory",
        lambda: sentinel,
    )
    monkeypatch.setattr(
        "my_ai_employee.dashboard.context._try_build_outbox_from_session_factory",
        lambda sf: OutboxDraftServiceImpl(_FakeOutbox()) if sf is sentinel else None,
    )
    monkeypatch.setattr(
        "my_ai_employee.dashboard.context._try_build_note_confirm_from_session_factory",
        lambda sf: NoteConfirmServiceImpl(_FakeNoteStore()) if sf is sentinel else None,
    )
    monkeypatch.setattr(
        "my_ai_employee.dashboard.context._try_build_expense_from_session_factory",
        lambda sf: None,
    )

    services = build_menu_bar_services()
    assert isinstance(services.outbox_draft_service, OutboxDraftServiceImpl)
    assert isinstance(services.note_confirm_service, NoteConfirmServiceImpl)
    assert isinstance(services.expense_service, ExpenseServiceStub)
