"""v0.2.53.18 DashboardContext.with_business_writer() 集成测试.

边界(沿 v0.2.53.14 §8 + 撞坑 #65 + #64):
    - 默认 business_writer=None → resolve_business_writer() 返回 BusinessWriterStub
    - with_business_writer() 不可变更新(原 ctx 不变)
    - pass None 还原为 BusinessWriterStub
"""

from __future__ import annotations

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
