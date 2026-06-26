"""v0.2.53.18 + v0.2.53.27 DashboardContext.with_business_writer() 集成测试.

边界(沿 v0.2.53.14 §8 + 撞坑 #65 + #64 + v0.2.53.27):
    - 默认 business_writer=None → resolve_business_writer() 返回 BusinessWriterStub
    - with_business_writer() 不可变更新(原 ctx 不变)
    - pass None 还原为 BusinessWriterStub
    - v0.2.53.27:`BUSINESS_WRITER_ENABLED=1` + `DASHBOARD_REAL_DB=1` + session_factory OK → 注入 Impl
    - v0.2.53.27:任一条件缺失 → 静默降级 Stub(沿 v0.2.53.8 单项失败范本)
"""

from __future__ import annotations

import pytest

from my_ai_employee.dashboard.business_writer import BusinessWriterStub
from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl
from my_ai_employee.dashboard.context import DashboardContext


class TestDefaultBusinessWriter:
    """默认 business_writer=None → resolve_business_writer() 返回 Stub."""

    def test_default_business_writer_is_none(self) -> None:
        """默认 ctx.business_writer 是 None(沿撞坑 #65 默认 Stub)."""
        ctx = DashboardContext()
        assert ctx.business_writer is None

    def test_resolve_business_writer_default_returns_stub(self) -> None:
        """resolve_business_writer() 默认返回 BusinessWriterStub."""
        ctx = DashboardContext()
        writer = ctx.resolve_business_writer()
        assert isinstance(writer, BusinessWriterStub)


class TestWithBusinessWriterImmutable:
    """with_business_writer() 不可变更新(沿 #64 公共 API 范本)."""

    def test_with_business_writer_returns_new_ctx(self) -> None:
        """with_business_writer() 返回新 ctx(原 ctx 不变)."""
        ctx = DashboardContext()
        new_writer = BusinessWriterStub()
        new_ctx = ctx.with_business_writer(new_writer)
        # 原 ctx 不变
        assert ctx.business_writer is None
        # 新 ctx business_writer 已替换
        assert new_ctx.business_writer is new_writer

    def test_with_business_writer_preserves_other_services(self) -> None:
        """with_business_writer() 保留其他 service(沿 v0.2.53.7 范本)."""
        ctx = DashboardContext()
        original_expense = ctx.expense_service
        original_note_confirm = ctx.note_confirm_service
        original_outbox = ctx.outbox_draft_service
        new_ctx = ctx.with_business_writer(BusinessWriterStub())
        assert new_ctx.expense_service is original_expense
        assert new_ctx.note_confirm_service is original_note_confirm
        assert new_ctx.outbox_draft_service is original_outbox

    def test_with_business_writer_none_resets_to_stub(self) -> None:
        """pass None 还原为 BusinessWriterStub(撞坑 #65 默认行为)."""
        ctx = DashboardContext().with_business_writer(BusinessWriterImpl())
        assert ctx.business_writer is not None
        new_ctx = ctx.with_business_writer(None)
        # 即使 pass None,resolve_business_writer() 仍返回非 None 的 Stub
        assert new_ctx.resolve_business_writer() is not None
        assert isinstance(new_ctx.resolve_business_writer(), BusinessWriterStub)


class TestResolveBusinessWriter:
    """resolve_business_writer() 解析逻辑."""

    def test_resolve_with_writer(self) -> None:
        """ctx.business_writer 非 None → 直接返回."""
        writer = BusinessWriterStub()
        ctx = DashboardContext().with_business_writer(writer)
        assert ctx.resolve_business_writer() is writer

    def test_resolve_with_none_returns_stub(self) -> None:
        """ctx.business_writer=None → 返回新 Stub 实例(撞坑 #65)."""
        ctx = DashboardContext()
        writer = ctx.resolve_business_writer()
        assert writer is not None
        assert isinstance(writer, BusinessWriterStub)


class TestBusinessWriterInjectionOptIn:
    """撞坑 #65 opt-in 4 阶段范本 — 默认 Stub + 显式注入替换."""

    def test_opt_in_replaces_writer(self) -> None:
        """显式 opt-in 替换 writer(沿 v0.2.53.7 pattern)."""
        ctx = DashboardContext()
        # 默认 resolve → Stub
        assert isinstance(ctx.resolve_business_writer(), BusinessWriterStub)
        # 显式 opt-in
        writer = BusinessWriterImpl()
        new_ctx = ctx.with_business_writer(writer)
        assert new_ctx.resolve_business_writer() is writer


class TestWithBusinessWriterDefaultStubBehavior:
    """Default stub 行为(沿 v0.2.53.15 不变式)."""

    def test_default_stub_dry_run_write_executed_false(self) -> None:
        """默认 Stub dry_run 恒 write_executed=False."""
        from my_ai_employee.dashboard.business_writer import (
            ACTION_OUTBOX_APPROVE,
            AuditContext,
        )

        ctx = DashboardContext()
        writer = ctx.resolve_business_writer()
        audit = AuditContext.default()
        decision = writer.dry_run(ACTION_OUTBOX_APPROVE, "1", audit=audit)
        assert decision.write_executed is False


# ===== v0.2.53.27 BUSINESS_WRITER_ENABLED env 门控(沿 DASHBOARD_REAL_DB=1 范本) =====


class TestBusinessWriterOptInDefault:
    """v0.2.53.27 默认行为 — BUSINESS_WRITER_ENABLED 未设时,default() 保持 BusinessWriterStub."""

    def test_env_unset_default_returns_stub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BUSINESS_WRITER_ENABLED 未设 → default() 仍走 Stub."""
        from my_ai_employee.dashboard.business_writer import BusinessWriterStub

        monkeypatch.delenv("BUSINESS_WRITER_ENABLED", raising=False)
        ctx = DashboardContext.default()
        # 默认 business_writer 字段 None(沿撞坑 #65)
        assert ctx.business_writer is None
        # resolve_business_writer() 返回 Stub
        assert isinstance(ctx.resolve_business_writer(), BusinessWriterStub)

    def test_env_disabled_values_default_returns_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUSINESS_WRITER_ENABLED=0/false/no → 仍 Stub(沿 _is_real_db_enabled 严判)."""
        from my_ai_employee.dashboard.business_writer import BusinessWriterStub

        for value in ["0", "false", "no", "off", ""]:
            monkeypatch.setenv("BUSINESS_WRITER_ENABLED", value)
            ctx = DashboardContext.default()
            assert ctx.business_writer is None
            assert isinstance(ctx.resolve_business_writer(), BusinessWriterStub)


class TestBusinessWriterOptInEnabled:
    """v0.2.53.27 启用行为 — BUSINESS_WRITER_ENABLED=1 + DASHBOARD_REAL_DB=1 + session_factory OK → 注入 Impl."""

    def test_env_set_with_real_db_injects_impl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """双门全开 + session_factory mock 成功 → 注入 BusinessWriterImpl."""
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl

        # 双 env 门控打开
        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        monkeypatch.setenv("BUSINESS_WRITER_ENABLED", "1")
        # Mock _try_build_real_session_factory 返回 session_factory
        sentinel_session_factory = object()
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_real_session_factory",
            lambda: sentinel_session_factory,
        )
        # Mock _try_build_outbox/note_confirm/expense 返回 None(避免依赖)
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_outbox_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_note_confirm_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_expense_from_session_factory",
            lambda _sf: None,
        )
        ctx = DashboardContext.default()
        # 此时 ctx.business_writer 是 BusinessWriterImpl 实例
        assert isinstance(ctx.business_writer, BusinessWriterImpl)

    def test_env_set_with_real_db_failure_returns_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUSINESS_WRITER_ENABLED=1 + DASHBOARD_REAL_DB 未设 → 早返回 ctx,仍走 Stub.

        沿 v0.2.53.27 决策:DASHBOARD_REAL_DB 是前置(需要 session_factory),
        未开时即使 BUSINESS_WRITER_ENABLED=1 也无法注入 Impl → 默认 Stub.
        """
        from my_ai_employee.dashboard.business_writer import BusinessWriterStub

        monkeypatch.delenv("DASHBOARD_REAL_DB", raising=False)
        monkeypatch.setenv("BUSINESS_WRITER_ENABLED", "1")
        ctx = DashboardContext.default()
        assert ctx.business_writer is None
        assert isinstance(ctx.resolve_business_writer(), BusinessWriterStub)

    def test_env_set_session_factory_fails_returns_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUSINESS_WRITER_ENABLED=1 + session_factory 构造失败 → Stub 降级."""
        from my_ai_employee.dashboard.business_writer import BusinessWriterStub

        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        monkeypatch.setenv("BUSINESS_WRITER_ENABLED", "1")
        # session_factory 构造失败(返回 None)
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_real_session_factory",
            lambda: None,
        )
        ctx = DashboardContext.default()
        assert ctx.business_writer is None
        assert isinstance(ctx.resolve_business_writer(), BusinessWriterStub)

    def test_env_set_business_writer_import_fails_returns_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUSINESS_WRITER_ENABLED=1 + BusinessWriterImpl 导入失败 → Stub 降级.

        沿撞坑 #65 单项失败降级范本:即使其他服务注入成功,writer 失败不影响整体.
        """
        from my_ai_employee.dashboard.business_writer import BusinessWriterStub

        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        monkeypatch.setenv("BUSINESS_WRITER_ENABLED", "1")
        sentinel_session_factory = object()
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_real_session_factory",
            lambda: sentinel_session_factory,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_outbox_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_note_confirm_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_expense_from_session_factory",
            lambda _sf: None,
        )

        # 强制 BusinessWriterImpl 构造抛异常
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise ImportError("mocked failure")

        monkeypatch.setattr(
            "my_ai_employee.dashboard.business_writer_impl.BusinessWriterImpl",
            _raise,
        )
        ctx = DashboardContext.default()
        assert ctx.business_writer is None
        assert isinstance(ctx.resolve_business_writer(), BusinessWriterStub)


class TestBusinessWriterOptInInvariants:
    """v0.2.53.27 opt-in 注入后不变式校验(沿 v0.2.53.11 write_executed 恒 False)."""

    def test_impl_dry_run_write_executed_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """注入 BusinessWriterImpl 后,dry_run 仍 write_executed=False(沿 v0.2.53.11)."""
        from my_ai_employee.dashboard.business_writer import (
            ACTION_OUTBOX_APPROVE,
            AuditContext,
        )
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl

        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        monkeypatch.setenv("BUSINESS_WRITER_ENABLED", "1")
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_real_session_factory",
            lambda: object(),
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_outbox_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_note_confirm_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_expense_from_session_factory",
            lambda _sf: None,
        )
        ctx = DashboardContext.default()
        writer = ctx.resolve_business_writer()
        assert isinstance(writer, BusinessWriterImpl)
        audit = AuditContext.default()
        decision = writer.dry_run(ACTION_OUTBOX_APPROVE, "1", audit=audit)
        # v0.2.53.11 不变式
        assert decision.write_executed is False
        # v0.2.53.17 默认 raise(Impl 骨架就绪但未启用 real_write_handler)
        assert decision.would_allow is False

    def test_impl_4_actions_default_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """注入 BusinessWriterImpl 后,4 类动作方法默认 raise NotImplementedError.

        沿 v0.2.53.17 + 撞坑 #65 默认 Stub 边界.
        """
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl

        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        monkeypatch.setenv("BUSINESS_WRITER_ENABLED", "1")
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_real_session_factory",
            lambda: object(),
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_outbox_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_note_confirm_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_expense_from_session_factory",
            lambda _sf: None,
        )
        ctx = DashboardContext.default()
        writer = ctx.resolve_business_writer()
        assert isinstance(writer, BusinessWriterImpl)
        from my_ai_employee.dashboard.business_writer import AuditContext

        audit = AuditContext.default()
        with pytest.raises(NotImplementedError):
            writer.approve_outbox("1", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.cancel_outbox("1", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.confirm_note("1", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.dismiss_anomaly("1", audit=audit)


class TestBusinessWriterOptInIndependence:
    """v0.2.53.27 opt-in 与 DASHBOARD_REAL_DB 解耦."""

    def test_real_db_unset_writer_env_set_returns_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DASHBOARD_REAL_DB 未设 + BUSINESS_WRITER_ENABLED=1 → Stub.

        边界(沿 v0.2.53.27):writer 注入需要 session_factory(由 DASHBOARD_REAL_DB
        门控打开),所以即使 writer env 设了,没有 DB opt-in 仍走 Stub.
        """
        from my_ai_employee.dashboard.business_writer import BusinessWriterStub

        monkeypatch.delenv("DASHBOARD_REAL_DB", raising=False)
        monkeypatch.setenv("BUSINESS_WRITER_ENABLED", "1")
        ctx = DashboardContext.default()
        assert ctx.business_writer is None
        assert isinstance(ctx.resolve_business_writer(), BusinessWriterStub)

    def test_writer_env_unset_returns_stub(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DASHBOARD_REAL_DB=1 + BUSINESS_WRITER_ENABLED 未设 → 仅注入其他服务,writer 仍 Stub."""
        from my_ai_employee.dashboard.business_writer import BusinessWriterStub

        monkeypatch.setenv("DASHBOARD_REAL_DB", "1")
        monkeypatch.delenv("BUSINESS_WRITER_ENABLED", raising=False)
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_real_session_factory",
            lambda: object(),
        )
        # 其他服务注入 mock(避免依赖)
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_outbox_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_note_confirm_from_session_factory",
            lambda _sf: None,
        )
        monkeypatch.setattr(
            "my_ai_employee.dashboard.context._try_build_expense_from_session_factory",
            lambda _sf: None,
        )
        ctx = DashboardContext.default()
        # 即使 DB 开了,writer env 未设仍 Stub
        assert ctx.business_writer is None
        assert isinstance(ctx.resolve_business_writer(), BusinessWriterStub)
