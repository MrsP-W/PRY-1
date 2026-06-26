"""v0.2.53.15 BusinessWriter Protocol + Stub + AuditContext + WriteResult/Decision 测试.

边界(沿 v0.2.53.14 设计骨架):
    - 默认全 Stub(无真实写入)
    - dry_run 返回 write_executed=False 恒定
    - 4 类动作方法抛 NotImplementedError(占位)
"""

from __future__ import annotations

import pytest

from my_ai_employee.dashboard.business_writer import (
    ACTION_FINANCE_DISMISS_ANOMALY,
    ACTION_NOTES_CONFIRM,
    ACTION_OUTBOX_APPROVE,
    ACTION_OUTBOX_CANCEL,
    SUPPORTED_ACTIONS,
    AuditContext,
    BusinessWriterStub,
    WriteDecision,
    WriteResult,
)


class TestAuditContext:
    """AuditContext dataclass 严判."""

    def test_default_audit_context(self) -> None:
        """默认 actor + reason + source."""
        audit = AuditContext(actor="test_user", reason="unit test")
        assert audit.actor == "test_user"
        assert audit.reason == "unit test"
        assert audit.source == "dashboard"
        assert audit.timestamp_ms is None

    def test_audit_default_factory(self) -> None:
        """默认工厂(actor='local_dashboard', reason='')."""
        audit = AuditContext.default()
        assert audit.actor == "local_dashboard"
        assert audit.reason == ""
        assert audit.source == "dashboard"

    def test_audit_actor_too_long_raises(self) -> None:
        """actor 超 80 字符 → ValueError."""
        with pytest.raises(ValueError, match="actor 超长"):
            AuditContext(actor="a" * 81, reason="")

    def test_audit_reason_too_long_raises(self) -> None:
        """reason 超 240 字符 → ValueError."""
        with pytest.raises(ValueError, match="reason 超长"):
            AuditContext(actor="test", reason="r" * 241)

    def test_audit_actor_at_limit_ok(self) -> None:
        """actor 正好 80 字符 → OK(边界内)."""
        AuditContext(actor="a" * 80, reason="")

    def test_audit_reason_at_limit_ok(self) -> None:
        """reason 正好 240 字符 → OK(边界内)."""
        AuditContext(actor="test", reason="r" * 240)

    def test_audit_custom_source(self) -> None:
        """自定义 source."""
        audit = AuditContext(actor="x", reason="y", source="cli")
        assert audit.source == "cli"

    def test_audit_custom_timestamp(self) -> None:
        """自定义 timestamp_ms."""
        audit = AuditContext(actor="x", reason="y", timestamp_ms=1234567890)
        assert audit.timestamp_ms == 1234567890


class TestWriteResultDataclass:
    """WriteResult dataclass 字段."""

    def test_success_result(self) -> None:
        """成功结果."""
        result = WriteResult(
            success=True,
            affected_id="outbox-123",
            error=None,
            reason="",
            audit_id="audit-456",
            write_executed=True,
        )
        assert result.success is True
        assert result.affected_id == "outbox-123"
        assert result.error is None
        assert result.audit_id == "audit-456"

    def test_failure_result(self) -> None:
        """失败结果."""
        result = WriteResult(
            success=False,
            affected_id=None,
            error="outbox_illegal_transition",
            reason="PENDING_SEND → APPROVED 不允许",
            audit_id=None,
            write_executed=True,
        )
        assert result.success is False
        assert result.error == "outbox_illegal_transition"
        assert result.write_executed is True


class TestWriteDecisionDataclass:
    """WriteDecision dataclass 字段(沿 v0.2.53.11 _decision 响应)."""

    def test_dry_run_decision(self) -> None:
        """dry-run 默认决策."""
        decision = WriteDecision(
            action=ACTION_OUTBOX_APPROVE,
            target_id="123",
            write_enabled=False,
            would_allow=False,
            write_executed=False,
            dry_run=True,
            audit=AuditContext.default(),
            error="write_disabled",
            reason="默认禁写",
            required=("DASHBOARD_WRITE_API=1",),
        )
        assert decision.action == ACTION_OUTBOX_APPROVE
        assert decision.write_executed is False
        assert decision.would_allow is False


class TestBusinessWriterStubDryRun:
    """BusinessWriterStub.dry_run 4 类动作覆盖."""

    @pytest.fixture
    def stub(self) -> BusinessWriterStub:
        return BusinessWriterStub()

    @pytest.fixture
    def audit(self) -> AuditContext:
        return AuditContext.default()

    def test_dry_run_outbox_approve(self, stub: BusinessWriterStub, audit: AuditContext) -> None:
        decision = stub.dry_run(ACTION_OUTBOX_APPROVE, "123", audit=audit)
        assert decision.action == ACTION_OUTBOX_APPROVE
        assert decision.target_id == "123"
        assert decision.write_executed is False
        assert decision.would_allow is False
        assert decision.error == "write_not_implemented"

    def test_dry_run_outbox_cancel(self, stub: BusinessWriterStub, audit: AuditContext) -> None:
        decision = stub.dry_run(ACTION_OUTBOX_CANCEL, "456", audit=audit)
        assert decision.action == ACTION_OUTBOX_CANCEL
        assert decision.write_executed is False

    def test_dry_run_notes_confirm(self, stub: BusinessWriterStub, audit: AuditContext) -> None:
        decision = stub.dry_run(ACTION_NOTES_CONFIRM, "note-abc", audit=audit)
        assert decision.action == ACTION_NOTES_CONFIRM
        assert decision.write_executed is False

    def test_dry_run_finance_dismiss(self, stub: BusinessWriterStub, audit: AuditContext) -> None:
        decision = stub.dry_run(
            ACTION_FINANCE_DISMISS_ANOMALY, "2026-06-26|星巴克|38.50", audit=audit
        )
        assert decision.action == ACTION_FINANCE_DISMISS_ANOMALY
        assert decision.write_executed is False

    def test_dry_run_required_fields(self, stub: BusinessWriterStub, audit: AuditContext) -> None:
        """required tuple 含 4 项(沿 v0.2.53.11 ApprovalGate 决策矩阵)."""
        decision = stub.dry_run(ACTION_OUTBOX_APPROVE, "1", audit=audit)
        assert "DASHBOARD_WRITE_API=1" in decision.required
        assert "confirm_text=CONFIRM_WRITE" in decision.required
        assert "BUSINESS_WRITER_ENABLED=1" in decision.required
        assert "business_writer_implementation" in decision.required


class TestBusinessWriterStubActions:
    """BusinessWriterStub 4 类动作方法默认抛 NotImplementedError(占位)."""

    @pytest.fixture
    def stub(self) -> BusinessWriterStub:
        return BusinessWriterStub()

    @pytest.fixture
    def audit(self) -> AuditContext:
        return AuditContext.default()

    def test_approve_outbox_not_implemented(
        self, stub: BusinessWriterStub, audit: AuditContext
    ) -> None:
        with pytest.raises(NotImplementedError, match="approve_outbox"):
            stub.approve_outbox("123", audit=audit)

    def test_cancel_outbox_not_implemented(
        self, stub: BusinessWriterStub, audit: AuditContext
    ) -> None:
        with pytest.raises(NotImplementedError, match="cancel_outbox"):
            stub.cancel_outbox("123", audit=audit)

    def test_confirm_note_not_implemented(
        self, stub: BusinessWriterStub, audit: AuditContext
    ) -> None:
        with pytest.raises(NotImplementedError, match="confirm_note"):
            stub.confirm_note("note-abc", audit=audit)

    def test_dismiss_anomaly_not_implemented(
        self, stub: BusinessWriterStub, audit: AuditContext
    ) -> None:
        with pytest.raises(NotImplementedError, match="dismiss_anomaly"):
            stub.dismiss_anomaly("2026-06-26|星巴克|38.50", audit=audit)


class TestSupportedActionsWhitelist:
    """SUPPORTED_ACTIONS 白名单(与 v0.2.53.11 ApprovalGate 契约对齐)."""

    def test_whitelist_has_4_actions(self) -> None:
        assert len(SUPPORTED_ACTIONS) == 4

    def test_whitelist_contains_all_4(self) -> None:
        assert ACTION_OUTBOX_APPROVE in SUPPORTED_ACTIONS
        assert ACTION_OUTBOX_CANCEL in SUPPORTED_ACTIONS
        assert ACTION_NOTES_CONFIRM in SUPPORTED_ACTIONS
        assert ACTION_FINANCE_DISMISS_ANOMALY in SUPPORTED_ACTIONS


class TestBusinessWriterStubFactory:
    """BusinessWriterStub.get_default_stub 工厂."""

    def test_get_default_stub(self) -> None:
        """工厂返回 BusinessWriterStub 实例."""
        stub = BusinessWriterStub.get_default_stub()
        assert isinstance(stub, BusinessWriterStub)


class TestBusinessWriterBoundaries:
    """撞坑 #65 边界 — 默认无写入 + 无 SMTP + 无 Keychain."""

    @pytest.fixture
    def stub(self) -> BusinessWriterStub:
        return BusinessWriterStub()

    @pytest.fixture
    def audit(self) -> AuditContext:
        return AuditContext.default()

    def test_default_does_not_read_keychain(
        self, stub: BusinessWriterStub, audit: AuditContext
    ) -> None:
        """默认 Stub 不调用 KeychainProbe(沿 #65 边界)."""
        # 验证 dry_run 不依赖外部资源
        decision = stub.dry_run(ACTION_OUTBOX_APPROVE, "1", audit=audit)
        assert decision.write_executed is False

    def test_default_does_not_write_db(self, stub: BusinessWriterStub, audit: AuditContext) -> None:
        """默认 Stub 4 类动作方法抛 NotImplementedError,不写 DB."""
        # 调用任何动作方法必须抛错(证明不静默成功)
        with pytest.raises(NotImplementedError):
            stub.approve_outbox("1", audit=audit)
        with pytest.raises(NotImplementedError):
            stub.cancel_outbox("1", audit=audit)
        with pytest.raises(NotImplementedError):
            stub.confirm_note("n1", audit=audit)
        with pytest.raises(NotImplementedError):
            stub.dismiss_anomaly("d1", audit=audit)


class TestDryRunWriteExecutedFalseInvariant:
    """dry_run 响应 write_executed 恒为 False 不变式(沿 v0.2.53.11)."""

    @pytest.fixture
    def stub(self) -> BusinessWriterStub:
        return BusinessWriterStub()

    @pytest.fixture
    def audit(self) -> AuditContext:
        return AuditContext.default()

    @pytest.mark.parametrize("action", SUPPORTED_ACTIONS)
    def test_write_executed_always_false(
        self, stub: BusinessWriterStub, audit: AuditContext, action: str
    ) -> None:
        decision = stub.dry_run(action, "any_target", audit=audit)
        assert decision.write_executed is False
