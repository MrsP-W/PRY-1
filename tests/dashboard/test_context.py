"""v0.2.53.7 + v0.2.53.8 — DashboardContext opt-in 真实 DB 集成测试.

边界(沿 v0.2.53.6):
    - 不真发邮件
    - 不输出邮件 body
    - 不默认读取 Keychain DB 密码
    - 不写 DB / 不打 tag / 不 kickstart launchd
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest

from my_ai_employee.dashboard.context import (
    DashboardContext,
    _is_real_db_enabled,
    _try_build_expense_from_session_factory,
    _try_build_note_confirm_from_session_factory,
    _try_build_real_outbox_drafts,
    _try_build_real_session_factory,
)
from my_ai_employee.menu_bar.expense_service import ExpenseServiceStub
from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceStub
from my_ai_employee.menu_bar.outbox_draft_service import (
    OutboxDraftServiceImpl,
    OutboxDraftServiceStub,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """每个测试前清掉 DASHBOARD_REAL_DB,避免真实环境干扰."""
    monkeypatch.delenv("DASHBOARD_REAL_DB", raising=False)
    yield


# ===== A1 env 门控 =====


class TestRealDbGate:
    """A1: DASHBOARD_REAL_DB env 门控判定."""

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE", "Yes"])
    def test_truthy_values_enable(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("DASHBOARD_REAL_DB", value)
        assert _is_real_db_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "random"])
    def test_other_values_disable(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("DASHBOARD_REAL_DB", value)
        assert _is_real_db_enabled() is False

    def test_unset_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DASHBOARD_REAL_DB", raising=False)
        assert _is_real_db_enabled() is False


# ===== A2 默认行为不变 + opt-in 路径 =====


class TestDefaultBehavior:
    """A2 默认行为:无 env → 全 Stub(沿 v0.2.53.6 行为不变)."""

    def test_default_returns_stub(self) -> None:
        ctx = DashboardContext.default()
        assert isinstance(ctx.outbox_draft_service, OutboxDraftServiceStub)
        assert isinstance(ctx.note_confirm_service, NoteConfirmServiceStub)
        assert isinstance(ctx.expense_service, ExpenseServiceStub)

    def test_default_is_pure_construction_no_io(self) -> None:
        """默认路径不应触发 DB I/O(Keychain/DB/open 等)."""
        with patch(
            "my_ai_employee.dashboard.context._try_build_real_session_factory"
        ) as mock_build:
            DashboardContext.default()
            mock_build.assert_not_called()


class TestOptInRealDb:
    """A2 opt-in 路径:设 env → 尝试注入 Impl;失败 → 降级 Stub."""

    def test_opt_in_calls_builder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        with patch(
            "my_ai_employee.dashboard.context._try_build_real_session_factory",
            return_value=None,
        ) as mock_build:
            ctx = DashboardContext.default()
            mock_build.assert_called_once()
            assert isinstance(ctx.outbox_draft_service, OutboxDraftServiceStub)
            assert isinstance(ctx.note_confirm_service, NoteConfirmServiceStub)
            assert isinstance(ctx.expense_service, ExpenseServiceStub)

    def test_opt_in_success_uses_impl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """opt-in 成功 → 三个真实服务分别注入."""

        class _FakeOutbox:
            def get_pending_draft_count(self) -> int:
                return 0

            def list_pending_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
                return []

        class _FakeNotes:
            def get_pending_confirm_count(self) -> int:
                return 0

            def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
                return []

            def confirm_note(self, apple_note_id: str) -> None:
                return None

        class _FakeExpense:
            def get_total_notes_count(self) -> int:
                return 0

            def get_unsynced_count(self) -> int:
                return 0

            def get_recent_note_titles(self, limit: int = 5) -> list[str]:
                return []

            def is_clipboard_listener_running(self) -> bool:
                return False

            def get_tcc_authorization_status(self) -> bool:
                return False

            def get_anomaly_count(self) -> int:
                return 0

            def get_recent_anomalies(self, limit: int = 10) -> list[dict[str, Any]]:
                return []

        fake_sf = object()
        fake_outbox = _FakeOutbox()
        fake_notes = _FakeNotes()
        fake_expense = _FakeExpense()
        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        with (
            patch(
                "my_ai_employee.dashboard.context._try_build_real_session_factory",
                return_value=fake_sf,
            ),
            patch(
                "my_ai_employee.dashboard.context._try_build_outbox_from_session_factory",
                return_value=fake_outbox,
            ) as mock_outbox,
            patch(
                "my_ai_employee.dashboard.context._try_build_note_confirm_from_session_factory",
                return_value=fake_notes,
            ) as mock_notes,
            patch(
                "my_ai_employee.dashboard.context._try_build_expense_from_session_factory",
                return_value=fake_expense,
            ) as mock_expense,
        ):
            ctx = DashboardContext.default()
            mock_outbox.assert_called_once_with(fake_sf)
            mock_notes.assert_called_once_with(fake_sf)
            mock_expense.assert_called_once_with(fake_sf)
            assert ctx.outbox_draft_service is fake_outbox
            assert ctx.note_confirm_service is fake_notes
            assert ctx.expense_service is fake_expense

    def test_opt_in_partial_injection_keeps_stubs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_sf = object()
        fake_outbox = object()
        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        with (
            patch(
                "my_ai_employee.dashboard.context._try_build_real_session_factory",
                return_value=fake_sf,
            ),
            patch(
                "my_ai_employee.dashboard.context._try_build_outbox_from_session_factory",
                return_value=fake_outbox,
            ),
            patch(
                "my_ai_employee.dashboard.context._try_build_note_confirm_from_session_factory",
                return_value=None,
            ),
            patch(
                "my_ai_employee.dashboard.context._try_build_expense_from_session_factory",
                return_value=None,
            ),
        ):
            ctx = DashboardContext.default()
            assert ctx.outbox_draft_service is fake_outbox
            assert isinstance(ctx.note_confirm_service, NoteConfirmServiceStub)
            assert isinstance(ctx.expense_service, ExpenseServiceStub)


class TestBuilderFallback:
    """A2 构造器失败模式:任意异常 → 返回 None → ctx 降级 Stub."""

    def test_session_factory_import_error_returns_none(self) -> None:
        with patch(
            "my_ai_employee.core.db.Database.open",
            side_effect=ImportError("no db"),
        ):
            assert _try_build_real_session_factory() is None

    def test_import_error_returns_none(self) -> None:
        """ImportError 时降级(无依赖环境)."""
        with patch(
            "my_ai_employee.core.db.Database.open",
            side_effect=ImportError("no db"),
        ):
            assert _try_build_real_outbox_drafts() is None

    def test_db_missing_returns_none(self) -> None:
        """FileNotFoundError(首次未 init_schema) → None."""
        with patch(
            "my_ai_employee.core.db.Database.open",
            side_effect=FileNotFoundError("data.db not found"),
        ):
            assert _try_build_real_session_factory() is None
            assert _try_build_real_outbox_drafts() is None

    def test_keychain_failure_returns_none(self) -> None:
        """Keychain 缺密码(PermissionError) → None."""
        with patch(
            "my_ai_employee.core.db.Database.open",
            side_effect=PermissionError("keychain denied"),
        ):
            assert _try_build_real_session_factory() is None

    def test_wrong_password_returns_none(self) -> None:
        """密码错(sqlcipher3.DatabaseError)→ None."""
        with patch(
            "my_ai_employee.core.db.Database.open",
            side_effect=Exception("file is not a database"),
        ):
            assert _try_build_real_session_factory() is None

    def test_note_confirm_builder_returns_none_on_failure(self) -> None:
        with patch(
            "my_ai_employee.db.notes.NoteStore",
            side_effect=RuntimeError("notes failed"),
        ):
            assert _try_build_note_confirm_from_session_factory(object()) is None

    def test_expense_builder_returns_none_on_failure(self) -> None:
        with patch(
            "my_ai_employee.db.transactions.TransactionStore",
            side_effect=RuntimeError("tx failed"),
        ):
            assert _try_build_expense_from_session_factory(object()) is None


# ===== A3 边界维持 =====


class TestBoundaries:
    """A3 边界维持:沿 v0.2.53.6 撞坑范本."""

    def test_default_does_not_read_keychain(self) -> None:
        """默认路径不应调 security / Keychain 读取命令."""
        with patch("subprocess.run") as mock_run:
            DashboardContext.default()
            # 默认路径应零 subprocess 调用(只 git probe 在 _default_git_head 内部)
            # Keychain probe 也不在默认路径触发(只有调用 ctx.keychain_probe() 才触发)
            assert mock_run.call_count == 0

    def test_real_impl_does_not_expose_body(self) -> None:
        """真实 Impl 返回字段不含 body(沿 v0.2.53.6 撞坑 #4)."""
        # 反射性验证:OutboxDraftServiceImpl._entry_to_dict 字段列表不包含 body

        class _Entry:
            id = 1
            email_id = 10
            subject = "test"
            recipient_email = "x@y.com"
            status = "pending_send"
            priority = "normal"
            created_at = 1000
            sla_due_at_ms = 2000
            last_approved_at_ms = None

        d = OutboxDraftServiceImpl._entry_to_dict(_Entry())
        assert "body" not in d
        assert set(d.keys()) == {
            "outbox_id",
            "email_id",
            "subject",
            "recipient_email",
            "status",
            "priority",
            "created_at",
            "sla_due_at_ms",
            "last_approved_at_ms",
        }


# ===== with_outbox_drafts 不可变更新范本 =====


class TestWithOutboxDrafts:
    """with_* 不可变更新(沿 v0.2.53.6 范本 + 不可变数据类)."""

    def test_with_replaces_service(self) -> None:
        ctx1 = DashboardContext.default()
        assert isinstance(ctx1.outbox_draft_service, OutboxDraftServiceStub)

        class _NewService:
            def get_pending_draft_count(self) -> int:
                return 42

            def list_pending_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
                return []

        new = _NewService()
        ctx2 = ctx1.with_outbox_drafts(new)

        assert isinstance(ctx1.outbox_draft_service, OutboxDraftServiceStub)
        assert ctx2.outbox_draft_service is new
        assert ctx2.version == ctx1.version
        assert ctx2.quality_gates == ctx1.quality_gates

    def test_with_note_confirm_replaces_service(self) -> None:
        ctx1 = DashboardContext.default()

        class _NewNotes:
            def get_pending_confirm_count(self) -> int:
                return 1

            def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
                return []

            def confirm_note(self, apple_note_id: str) -> None:
                return None

        new = _NewNotes()
        ctx2 = ctx1.with_note_confirm(new)
        assert isinstance(ctx1.note_confirm_service, NoteConfirmServiceStub)
        assert ctx2.note_confirm_service is new

    def test_with_expense_replaces_service(self) -> None:
        ctx1 = DashboardContext.default()

        class _NewExpense:
            def get_total_notes_count(self) -> int:
                return 0

            def get_unsynced_count(self) -> int:
                return 0

            def get_recent_note_titles(self, limit: int = 5) -> list[str]:
                return []

            def is_clipboard_listener_running(self) -> bool:
                return False

            def get_tcc_authorization_status(self) -> bool:
                return False

            def get_anomaly_count(self) -> int:
                return 3

            def get_recent_anomalies(self, limit: int = 10) -> list[dict[str, Any]]:
                return []

        new = _NewExpense()
        ctx2 = ctx1.with_expense(new)
        assert isinstance(ctx1.expense_service, ExpenseServiceStub)
        assert ctx2.expense_service is new
