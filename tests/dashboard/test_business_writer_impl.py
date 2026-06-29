"""v0.2.53.46 BusinessWriterImpl 4 动作实写骨架测试.

v0.2.53.17 测试(默认 raise):
    - 4 动作方法默认 raise NotImplementedError(等同 Stub 行为)
    - dry_run 返回 would_allow=False(等待 v0.2.53.19 启用)
    - 真实写入路径留 v0.2.53.19 handler 启用

v0.2.53.46 升级(实写骨架):
    - 4 动作方法统一骨架:依赖检查 + 参数校验 + 状态守卫 + 默认 raise
    - 无依赖 → raise NotImplementedError(沿撞坑 #18 风险门控)
    - 有依赖 + 无效 target_id → WriteResult(success=False, error='invalid_target_id')
    - 有依赖 + 有效 target_id → raise NotImplementedError(默认 raise,等待路径 4)
    - 2 个辅助方法:_check_dep + _validate_target_id

边界(沿撞坑 #65 + 撞坑 #18):
    - 默认 raise NotImplementedError(等同 Stub 行为)
    - dry_run 返回 would_allow=False(等待 v0.2.53.19 启用)
    - 真实写入路径留 v0.2.53.19 handler 启用
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from my_ai_employee.dashboard.business_writer import (
    ACTION_OUTBOX_APPROVE,
    SUPPORTED_ACTIONS,
    AuditContext,
    WriteResult,
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
        writer = BusinessWriterImpl(session_factory=None)
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
        assert "real_write_handler_enabled" in decision.required

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
        # v0.2.53.46:无依赖 → _check_dep 先 raise(消息含依赖名 "outbox_store",非 "approve_outbox")
        with pytest.raises(NotImplementedError, match="outbox_store"):
            writer.approve_outbox("123", audit=audit)

    def test_cancel_outbox_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="outbox_store"):
            writer.cancel_outbox("123", audit=audit)

    def test_confirm_note_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="note_confirm_service"):
            writer.confirm_note("note-abc", audit=audit)

    def test_dismiss_anomaly_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="anomaly_dismissal_service"):
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


# ============================================================
# v0.2.53.46 4 动作实写骨架测试
# ============================================================


class TestBusinessWriterImplApproveOutboxSkeleton:
    """v0.2.53.46 approve_outbox 实写骨架 — 依赖检查 + 参数校验 + 默认 raise."""

    def test_no_deps_raises_not_implemented(self) -> None:
        """无依赖 → raise NotImplementedError(沿撞坑 #18 风险门控)."""
        writer = BusinessWriterImpl()
        with pytest.raises(NotImplementedError, match="outbox_store"):
            writer.approve_outbox("123", audit=AuditContext.default())

    def test_with_deps_invalid_target_id_returns_write_result(self) -> None:
        """有依赖 + 非 str target_id → WriteResult(success=False, error='invalid_target_id')."""

        writer = BusinessWriterImpl(outbox_store=cast(Any, SimpleNamespace()))
        result = writer.approve_outbox(cast(str, 123), audit=AuditContext.default())
        assert isinstance(result, WriteResult)
        assert result.success is False
        assert result.error == "invalid_target_id"
        assert "target_id 必须是 str" in (result.reason or "")
        assert result.affected_id is None

    def test_with_deps_empty_target_id_returns_write_result(self) -> None:
        """有依赖 + 空字符串 target_id → WriteResult(success=False, error='invalid_target_id')."""

        writer = BusinessWriterImpl(outbox_store=cast(Any, SimpleNamespace()))
        result = writer.approve_outbox("   ", audit=AuditContext.default())
        assert isinstance(result, WriteResult)
        assert result.success is False
        assert result.error == "invalid_target_id"
        assert "必填且必须非空" in (result.reason or "")

    def test_with_deps_valid_target_id_raises_not_implemented(self) -> None:
        """有依赖 + 有效 target_id → raise NotImplementedError(写保护锁默认锁定,撞坑 #18 风险门控)."""

        writer = BusinessWriterImpl(outbox_store=cast(Any, SimpleNamespace()))
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.approve_outbox("123", audit=AuditContext.default())


class TestBusinessWriterImplCancelOutboxSkeleton:
    """v0.2.53.46 cancel_outbox 实写骨架."""

    def test_no_deps_raises_not_implemented(self) -> None:
        writer = BusinessWriterImpl()
        with pytest.raises(NotImplementedError, match="outbox_store"):
            writer.cancel_outbox("123", audit=AuditContext.default())

    def test_with_deps_invalid_target_id_returns_write_result(self) -> None:

        writer = BusinessWriterImpl(outbox_store=cast(Any, SimpleNamespace()))
        result = writer.cancel_outbox(cast(str, None), audit=AuditContext.default())
        assert isinstance(result, WriteResult)
        assert result.success is False
        assert result.error == "invalid_target_id"

    def test_with_deps_valid_target_id_raises_not_implemented(self) -> None:

        writer = BusinessWriterImpl(outbox_store=cast(Any, SimpleNamespace()))
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.cancel_outbox("456", audit=AuditContext.default())


class TestBusinessWriterImplConfirmNoteSkeleton:
    """v0.2.53.46 confirm_note 实写骨架."""

    def test_no_deps_raises_not_implemented(self) -> None:
        writer = BusinessWriterImpl()
        with pytest.raises(NotImplementedError, match="note_confirm_service"):
            writer.confirm_note("note-abc", audit=AuditContext.default())

    def test_with_deps_invalid_target_id_returns_write_result(self) -> None:

        writer = BusinessWriterImpl(note_confirm_service=cast(Any, SimpleNamespace()))
        result = writer.confirm_note(cast(str, 123), audit=AuditContext.default())
        assert isinstance(result, WriteResult)
        assert result.success is False
        assert result.error == "invalid_target_id"

    def test_with_deps_empty_target_id_returns_write_result(self) -> None:

        writer = BusinessWriterImpl(note_confirm_service=cast(Any, SimpleNamespace()))
        result = writer.confirm_note("", audit=AuditContext.default())
        assert isinstance(result, WriteResult)
        assert result.success is False
        assert result.error == "invalid_target_id"

    def test_with_deps_valid_target_id_raises_not_implemented(self) -> None:

        writer = BusinessWriterImpl(note_confirm_service=cast(Any, SimpleNamespace()))
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.confirm_note("note-abc", audit=AuditContext.default())


class TestBusinessWriterImplDismissAnomalySkeleton:
    """v0.2.53.46 dismiss_anomaly 实写骨架."""

    def test_no_deps_raises_not_implemented(self) -> None:
        writer = BusinessWriterImpl()
        with pytest.raises(NotImplementedError, match="anomaly_dismissal_service"):
            writer.dismiss_anomaly("2026-06-26|星巴克|38.50", audit=AuditContext.default())

    def test_with_deps_invalid_target_id_returns_write_result(self) -> None:

        writer = BusinessWriterImpl(anomaly_dismissal_service=cast(Any, SimpleNamespace()))
        result = writer.dismiss_anomaly(cast(str, 123), audit=AuditContext.default())
        assert isinstance(result, WriteResult)
        assert result.success is False
        assert result.error == "invalid_target_id"

    def test_with_deps_valid_target_id_raises_not_implemented(self) -> None:

        writer = BusinessWriterImpl(anomaly_dismissal_service=cast(Any, SimpleNamespace()))
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.dismiss_anomaly("2026-06-26|星巴克|38.50", audit=AuditContext.default())


class TestBusinessWriterImplCheckDepHelper:
    """v0.2.53.46 _check_dep helper — 依赖检查."""

    def test_check_dep_none_raises(self) -> None:
        """dep=None → raise NotImplementedError."""
        writer = BusinessWriterImpl()
        with pytest.raises(NotImplementedError, match="依赖 outbox_store 未注入"):
            writer._check_dep(cast(Any, None), "outbox_store")

    def test_check_dep_non_none_returns_none(self) -> None:
        """dep 非 None → 无 raise,无返回."""
        writer = BusinessWriterImpl()
        # mypy --strict:helper 返回 None,直接调用验证无 raise
        writer._check_dep(object(), "any_dep")


class TestBusinessWriterImplValidateTargetIdHelper:
    """v0.2.53.46 _validate_target_id helper — 参数校验."""

    def test_validate_target_id_str_valid(self) -> None:
        """非空 str → 无错(None)."""
        result = BusinessWriterImpl._validate_target_id("123")
        assert result is None

    def test_validate_target_id_str_with_whitespace_valid(self) -> None:
        """带前后空白的 str → 无错(None,去除空白后非空)."""
        result = BusinessWriterImpl._validate_target_id("  note-abc  ")
        assert result is None

    def test_validate_target_id_str_empty(self) -> None:
        """空字符串 → 错误 reason."""
        result = BusinessWriterImpl._validate_target_id("")
        assert result is not None
        assert "必填且必须非空" in result

    def test_validate_target_id_str_whitespace_only(self) -> None:
        """纯空白 str → 错误 reason."""
        result = BusinessWriterImpl._validate_target_id("   ")
        assert result is not None
        assert "必填且必须非空" in result

    def test_validate_target_id_non_str_int(self) -> None:
        """非 str(int) → 错误 reason."""
        result = BusinessWriterImpl._validate_target_id(123)
        assert result is not None
        assert "target_id 必须是 str" in result
        assert "type=int" in result

    def test_validate_target_id_non_str_none(self) -> None:
        """非 str(None) → 错误 reason."""
        result = BusinessWriterImpl._validate_target_id(None)
        assert result is not None
        assert "target_id 必须是 str" in result
        assert "type=NoneType" in result

    def test_validate_target_id_non_str_bool(self) -> None:
        """非 str(bool) → 错误 reason(严判 type)."""
        result = BusinessWriterImpl._validate_target_id(True)
        assert result is not None
        assert "target_id 必须是 str" in result
        assert "type=bool" in result

    def test_validate_target_id_non_str_list(self) -> None:
        """非 str(list) → 错误 reason."""
        result = BusinessWriterImpl._validate_target_id(["123"])
        assert result is not None
        assert "target_id 必须是 str" in result


class TestBusinessWriterImplSkeletonBoundaries:
    """v0.2.53.46 实写骨架边界 — 撞坑 #18 + 撞坑 #65 沿用."""

    def test_write_executed_invariant_via_invalid_target_id(self) -> None:
        """参数非法时返回 WriteResult(success=False, error='invalid_target_id').

        边界(沿 v0.2.53.15 WriteResult 文档):
            - success=False 时 write_executed=True(失败也算执行过)
            - 我们的"参数校验失败"分支 = 校验已尝试 → write_executed=True
        """

        writer = BusinessWriterImpl(outbox_store=cast(Any, SimpleNamespace()))
        result = writer.approve_outbox(cast(str, 123), audit=AuditContext.default())
        assert result.success is False
        assert result.error == "invalid_target_id"
        # 沿 v0.2.53.15 WriteResult 文档:success=False 时 write_executed=True
        assert result.write_executed is True

    def test_dry_run_unaffected_by_4_action_skeleton(self) -> None:
        """4 动作实写骨架不影响 dry_run 行为(沿 v0.2.53.17 既有契约)."""
        writer = BusinessWriterImpl()
        for action in SUPPORTED_ACTIONS:
            decision = writer.dry_run(action, "1", audit=AuditContext.default())
            assert decision.write_executed is False
            assert decision.would_allow is False
            assert decision.error == "write_not_implemented"

    def test_skeleton_does_not_call_smtp(self) -> None:
        """实写骨架不接 SMTP(沿撞坑 #18 风险门控)."""

        writer = BusinessWriterImpl(
            outbox_store=cast(Any, SimpleNamespace()),
            note_confirm_service=cast(Any, SimpleNamespace()),
            anomaly_dismissal_service=cast(Any, SimpleNamespace()),
        )
        # 即使有依赖 + 有效 target_id,默认 raise = 证明不静默成功
        with pytest.raises(NotImplementedError):
            writer.approve_outbox("1", audit=AuditContext.default())
        with pytest.raises(NotImplementedError):
            writer.cancel_outbox("1", audit=AuditContext.default())
        with pytest.raises(NotImplementedError):
            writer.confirm_note("n1", audit=AuditContext.default())
        with pytest.raises(NotImplementedError):
            writer.dismiss_anomaly("d1", audit=AuditContext.default())

    def test_skeleton_4_actions_all_match_protocol_signatures(self) -> None:
        """4 动作方法签名与 Protocol 契约对齐(沿 v0.2.53.15)."""
        import inspect

        from my_ai_employee.dashboard.business_writer import BusinessWriter

        for method_name in (
            "approve_outbox",
            "cancel_outbox",
            "confirm_note",
            "dismiss_anomaly",
        ):
            proto_sig = inspect.signature(getattr(BusinessWriter, method_name))
            impl_sig = inspect.signature(getattr(BusinessWriterImpl, method_name))
            # 参数名对齐(target_id / audit)
            assert proto_sig.parameters.keys() == impl_sig.parameters.keys()


class TestBusinessWriterImplRealWriteHandlerApproved:
    """v0.2.53.49 approve_outbox 写保护锁开 + fake store 真实调 service(撞坑 #18 测试场景)."""

    def test_real_write_calls_outbox_store_update_status(self) -> None:
        """写保护锁开 + 依赖注入 → 真实调 outbox_store.update_status(APPROVED)."""

        class _FakeUpdated:
            id = 12345

        fake_store = SimpleNamespace(
            update_status=lambda **kw: _FakeUpdated(),
        )
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            real_write_handler_enabled=True,
        )
        result = writer.approve_outbox("123", audit=AuditContext.default())

        assert result.success is True
        assert result.affected_id == "12345"
        assert result.error is None
        assert "APPROVED" in (result.reason or "")
        assert result.write_executed is True

    def test_real_write_passes_last_approved_at_ms(self) -> None:
        """approve_outbox 必须传 last_approved_at_ms(沿 D5.6.3 P1-1 审批凭据必传规则)."""

        captured: dict[str, Any] = {}

        def _fake_update_status(**kw: Any) -> SimpleNamespace:
            captured.update(kw)
            return SimpleNamespace(id=999)

        fake_store = SimpleNamespace(update_status=_fake_update_status)
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            real_write_handler_enabled=True,
        )
        writer.approve_outbox("888", audit=AuditContext.default())

        assert captured.get("new_status") == "APPROVED"
        assert captured.get("from_status") == "PENDING_SEND"
        assert captured.get("outbox_id") == 888
        assert isinstance(captured.get("last_approved_at_ms"), int)
        assert captured["last_approved_at_ms"] > 0


class TestBusinessWriterImplRealWriteHandlerCancelled:
    """v0.2.53.49 cancel_outbox 写保护锁开 + fake store."""

    def test_real_write_calls_update_status_with_none_approved_at(self) -> None:
        """cancel_outbox 必须传 last_approved_at_ms=None(D5.6.3 P1-1 必传 None 规则)."""

        captured: dict[str, Any] = {}

        def _fake_update_status(**kw: Any) -> SimpleNamespace:
            captured.update(kw)
            return SimpleNamespace(id=999)

        fake_store = SimpleNamespace(update_status=_fake_update_status)
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            real_write_handler_enabled=True,
        )
        result = writer.cancel_outbox("777", audit=AuditContext.default())

        assert result.success is True
        assert result.affected_id == "999"
        assert captured.get("new_status") == "CANCELLED"
        assert captured.get("from_status") == "PENDING_SEND"
        assert captured.get("last_approved_at_ms") is None


class TestBusinessWriterImplRealWriteHandlerConfirmNote:
    """v0.2.53.49 confirm_note 写保护锁开 + fake note_confirm_service."""

    def test_real_write_calls_confirm_note(self) -> None:
        """写保护锁开 → 真实调 note_confirm_service.confirm_note(target_id)."""

        captured: dict[str, Any] = {}

        def _fake_confirm_note(*, apple_note_id: str) -> None:
            captured["apple_note_id"] = apple_note_id

        fake_service = SimpleNamespace(confirm_note=_fake_confirm_note)
        writer = BusinessWriterImpl(
            note_confirm_service=cast(Any, fake_service),
            real_write_handler_enabled=True,
        )
        result = writer.confirm_note("note-xyz", audit=AuditContext.default())

        assert result.success is True
        assert result.affected_id == "note-xyz"
        assert captured.get("apple_note_id") == "note-xyz"


class TestBusinessWriterImplRealWriteHandlerDismissAnomaly:
    """v0.2.53.49 dismiss_anomaly 写保护锁开 + fake anomaly_dismissal_service."""

    def test_real_write_calls_dismiss_with_reason(self) -> None:
        """写保护锁开 → 真实调 anomaly_dismissal_service.dismiss(target_id, reason)."""

        captured: dict[str, Any] = {}

        def _fake_dismiss(*, anomaly_id: str, reason: str) -> None:
            captured["anomaly_id"] = anomaly_id
            captured["reason"] = reason

        fake_service = SimpleNamespace(dismiss=_fake_dismiss)
        writer = BusinessWriterImpl(
            anomaly_dismissal_service=cast(Any, fake_service),
            real_write_handler_enabled=True,
        )
        audit = AuditContext(actor="tester", reason="test reason for pitfall #18")
        result = writer.dismiss_anomaly("2026-06-26|星巴克|38.50", audit=audit)

        assert result.success is True
        assert result.affected_id == "2026-06-26|星巴克|38.50"
        assert captured.get("anomaly_id") == "2026-06-26|星巴克|38.50"
        assert captured.get("reason") == "test reason for pitfall #18"


class TestBusinessWriterImplWriteProtectionDefaultLocked:
    """v0.2.53.49 默认写保护锁锁定(撞坑 #18 风险门控)— 4 动作 raise."""

    @pytest.mark.parametrize(
        ("method_name", "kw"),
        [
            ("approve_outbox", {"outbox_store": SimpleNamespace()}),
            ("cancel_outbox", {"outbox_store": SimpleNamespace()}),
            ("confirm_note", {"note_confirm_service": SimpleNamespace()}),
            ("dismiss_anomaly", {"anomaly_dismissal_service": SimpleNamespace()}),
        ],
    )
    def test_default_locked_raises_not_implemented(
        self, method_name: str, kw: dict[str, Any]
    ) -> None:
        """默认 _real_write_handler_enabled=False → 4 动作 raise(写保护锁风险门控)."""

        kwargs = cast(Any, kw)
        writer = BusinessWriterImpl(**kwargs)
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            getattr(writer, method_name)("1", audit=AuditContext.default())

    def test_default_constructor_real_write_handler_false(self) -> None:
        """默认构造 _real_write_handler_enabled=False."""
        writer = BusinessWriterImpl()
        assert writer._real_write_handler_enabled is False  # noqa: SLF001

    def test_explicit_true_unlock(self) -> None:
        """显式 _real_write_handler_enabled=True → 放行(仅测试场景)."""
        writer = BusinessWriterImpl(
            outbox_store=cast(
                Any, SimpleNamespace(update_status=lambda **kw: SimpleNamespace(id=1))
            ),
            real_write_handler_enabled=True,
        )
        assert writer._real_write_handler_enabled is True  # noqa: SLF001
