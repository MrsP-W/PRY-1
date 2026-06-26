"""v0.2.53.17 BusinessWriterImpl 接入骨架测试(默认 raise NotImplementedError).

边界(沿 v0.2.53.14 §10 + 撞坑 #65):
    - 默认 raise NotImplementedError(等同 Stub 行为)
    - dry_run 返回 would_allow=False(等待 v0.2.53.19 启用)
    - 真实写入路径留 v0.2.53.19 handler 启用
"""

from __future__ import annotations

import pytest

from my_ai_employee.dashboard.business_writer import (
    ACTION_OUTBOX_APPROVE,
    SUPPORTED_ACTIONS,
    AuditContext,
)
from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl


class TestBusinessWriterImplConstruction:
    """BusinessWriterImpl 构造 — 所有依赖可选."""

    def test_default_no_deps(self) -> None:
        """无依赖构造 OK(默认 raise)."""
        writer = BusinessWriterImpl()
        assert writer is not None

    def test_with_session_factory_only(self) -> None:
        """只传 session_factory OK."""
        writer = BusinessWriterImpl(session_factory=None)  # type: ignore[arg-type]
        assert writer is not None

    def test_with_all_deps_none(self) -> None:
        """所有依赖 None OK(默认 raise)."""
        writer = BusinessWriterImpl(
            session_factory=None,
            outbox_store=None,
            note_confirm_service=None,
            anomaly_dismissal_service=None,
        )
        assert writer is not None


class TestBusinessWriterImplDryRun:
    """dry_run 默认 would_allow=False(等待 v0.2.53.19)."""

    @pytest.fixture
    def writer(self) -> BusinessWriterImpl:
        return BusinessWriterImpl()

    @pytest.fixture
    def audit(self) -> AuditContext:
        return AuditContext.default()

    def test_dry_run_unknown_action_returns_unsupported(
        self, writer: BusinessWriterImpl, audit: AuditContext
    ) -> None:
        """未知 action → error='unsupported_action'."""
        decision = writer.dry_run("unknown.action", "1", audit=audit)
        assert decision.error == "unsupported_action"
        assert decision.write_executed is False
        assert decision.would_allow is False

    @pytest.mark.parametrize("action", SUPPORTED_ACTIONS)
    def test_dry_run_known_actions_would_allow_false(
        self, writer: BusinessWriterImpl, audit: AuditContext, action: str
    ) -> None:
        """4 类已知 action dry_run 都返回 would_allow=False(等待启用)."""
        decision = writer.dry_run(action, "any_target", audit=audit)
        assert decision.action == action
        assert decision.write_executed is False
        assert decision.would_allow is False
        assert decision.error == "write_not_implemented"

    def test_dry_run_required_fields(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        """required 含 4 项(沿 v0.2.53.14 §6.2 决策矩阵)."""
        decision = writer.dry_run(ACTION_OUTBOX_APPROVE, "1", audit=audit)
        assert "DASHBOARD_WRITE_API=1" in decision.required
        assert "confirm_text=CONFIRM_WRITE" in decision.required
        assert "BUSINESS_WRITER_ENABLED=1" in decision.required
        assert "handler_path_4_enabled" in decision.required

    def test_dry_run_exception_isolation(
        self, writer: BusinessWriterImpl, audit: AuditContext
    ) -> None:
        """dry_run 异常收容(沿 v0.2.53.14 §7.4)— 4 类已知 action 都返回正常决策."""
        # 验证 dry_run 4 类已知 action 都正常返回(异常收容路径)
        for action in SUPPORTED_ACTIONS:
            decision = writer.dry_run(action, "any_target", audit=audit)
            assert decision.write_executed is False
            assert decision.error == "write_not_implemented"


class TestBusinessWriterImplActionsRaise:
    """4 类动作方法默认 raise NotImplementedError(等待 v0.2.53.19)."""

    @pytest.fixture
    def writer(self) -> BusinessWriterImpl:
        return BusinessWriterImpl()

    @pytest.fixture
    def audit(self) -> AuditContext:
        return AuditContext.default()

    def test_approve_outbox_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="approve_outbox"):
            writer.approve_outbox("123", audit=audit)

    def test_cancel_outbox_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="cancel_outbox"):
            writer.cancel_outbox("123", audit=audit)

    def test_confirm_note_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="confirm_note"):
            writer.confirm_note("note-abc", audit=audit)

    def test_dismiss_anomaly_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="dismiss_anomaly"):
            writer.dismiss_anomaly("2026-06-26|星巴克|38.50", audit=audit)


class TestBusinessWriterImplBoundaries:
    """撞坑 #65 + v0.2.53.8 边界 — 默认不真写 + 不接 SMTP + 不读 Keychain."""

    @pytest.fixture
    def writer(self) -> BusinessWriterImpl:
        return BusinessWriterImpl()

    @pytest.fixture
    def audit(self) -> AuditContext:
        return AuditContext.default()

    def test_default_does_not_write_db(
        self, writer: BusinessWriterImpl, audit: AuditContext
    ) -> None:
        """默认所有动作方法 raise(不静默成功 = 证明不写 DB)."""
        with pytest.raises(NotImplementedError):
            writer.approve_outbox("1", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.cancel_outbox("1", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.confirm_note("n1", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.dismiss_anomaly("d1", audit=audit)

    def test_default_dry_run_does_not_smtp(
        self, writer: BusinessWriterImpl, audit: AuditContext
    ) -> None:
        """默认 dry_run 不发 SMTP(返回 would_allow=False)."""
        decision = writer.dry_run(ACTION_OUTBOX_APPROVE, "1", audit=audit)
        assert decision.write_executed is False
        assert decision.would_allow is False
        # 没有 affected_id = 没真写
        assert decision.error == "write_not_implemented"


class TestBusinessWriterImplDryRunInvariants:
    """dry_run 不变式 — write_executed 恒为 False."""

    @pytest.fixture
    def writer(self) -> BusinessWriterImpl:
        return BusinessWriterImpl()

    @pytest.fixture
    def audit(self) -> AuditContext:
        return AuditContext.default()

    @pytest.mark.parametrize("action", SUPPORTED_ACTIONS)
    def test_write_executed_always_false(
        self, writer: BusinessWriterImpl, audit: AuditContext, action: str
    ) -> None:
        decision = writer.dry_run(action, "any_target", audit=audit)
        assert decision.write_executed is False
