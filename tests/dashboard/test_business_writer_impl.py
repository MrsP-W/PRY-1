"""v0.2.53.46 BusinessWriterImpl 4 动作实写骨架测试.

v0.2.53.17 测试(默认 raise):
    - 4 动作方法默认 raise NotImplementedError(等同 Stub 行为)
    - dry_run 返回 would_allow=False(等待 v0.2.53.19 启用)
    - 真实写入路径留 v0.2.53.19 handler 启用

v0.2.53.46 升级(实写骨架):
    - 4 动作方法统一骨架:参数校验 + 写保护锁 + 依赖检查 + 状态守卫
    - 默认未开写保护锁 → raise NotImplementedError(沿撞坑 #18 风险门控)
    - 有依赖 + 无效 target_id → WriteResult(success=False, error='invalid_target_id')
    - 有依赖 + 有效 target_id → raise NotImplementedError(默认 raise,等待路径 4)
    - 2 个辅助方法:_check_dep + _validate_target_id

v0.2.53.51 升级(audit 真实落档):
    - 4 动作方法成功/失败都落档 audit(real_write_handler_enabled=True 时)
    - 写保护锁 raise / dry_run / invalid_target_id 都不落档(撞坑 #18 「日志」语义)
    - audit_id 字符串格式 "audit:{id}"(撞坑 #64 公共 API 范本)

边界(沿撞坑 #65 + 撞坑 #18):
    - 默认 raise NotImplementedError(等同 Stub 行为)
    - dry_run 返回 would_allow=False(等待 v0.2.53.19 启用)
    - 真实写入路径留 v0.2.53.19 handler 启用
    - audit 落档仅在写保护锁开 + 真实 service 调用后发生
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
from my_ai_employee.menu_bar.approval_gate_audit import InMemoryApprovalGateAuditStore


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
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.approve_outbox("123", audit=audit)

    def test_cancel_outbox_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.cancel_outbox("123", audit=audit)

    def test_confirm_note_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.confirm_note("note-abc", audit=audit)

    def test_dismiss_anomaly_raises(self, writer: BusinessWriterImpl, audit: AuditContext) -> None:
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
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
    """approve_outbox 实写骨架 — 参数校验 + 写保护锁 + 依赖检查."""

    def test_no_deps_raises_not_implemented(self) -> None:
        """默认未开写保护锁 → 先 raise NotImplementedError(沿撞坑 #18 风险门控)."""
        writer = BusinessWriterImpl()
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.approve_outbox("123", audit=AuditContext.default())

    def test_five_gates_open_without_dep_raises_dep_error(self) -> None:
        """五门全开后才暴露具体依赖缺失,避免依赖错误绕过风险门控."""
        writer = BusinessWriterImpl(
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
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
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
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
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
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
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
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
    """v0.2.53.49 approve_outbox 写保护锁开 + fake store 真实调 service(撞坑 #18 测试场景).

    v0.2.53.51 升级(audit 真实落档):
    - 4 个测试都加 InMemoryApprovalGateAuditStore 注入
    - 断言 WriteResult.audit_id 是真实 "audit:N" 格式
    - 断言 audit_store 收到 1 条 success record
    """

    def test_real_write_calls_outbox_store_update_status(self) -> None:
        """写保护锁开 + 依赖注入 → 真实调 outbox_store.update_status(APPROVED)."""

        class _FakeUpdated:
            id = 12345

        fake_store = SimpleNamespace(
            update_status=lambda **kw: _FakeUpdated(),
        )
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        result = writer.approve_outbox("123", audit=AuditContext.default())

        assert result.success is True
        assert result.affected_id == "12345"
        assert result.error is None
        assert "APPROVED" in (result.reason or "")
        assert result.write_executed is True
        # v0.2.53.51 audit 落档:success=True,audit_id="audit:1"
        assert result.audit_id == "audit:1"
        assert audit_store.count() == 1

    def test_real_write_passes_last_approved_at_ms(self) -> None:
        """approve_outbox 必须传 last_approved_at_ms(沿 D5.6.3 P1-1 审批凭据必传规则).

        撞坑 #71 修复(2026-06-30):契约值改为小写,与 OutboxStatus StrEnum 对齐。
        """
        captured: dict[str, Any] = {}

        def _fake_update_status(**kw: Any) -> SimpleNamespace:
            captured.update(kw)
            return SimpleNamespace(id=999)

        fake_store = SimpleNamespace(update_status=_fake_update_status)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        writer.approve_outbox("888", audit=AuditContext.default())

        # 撞坑 #71 修复:new_status 与 OutboxStatus 枚举值一致(小写)
        assert captured.get("new_status") == "approved"
        assert captured.get("from_status") == "pending_send"
        assert captured.get("outbox_id") == 888
        assert isinstance(captured.get("last_approved_at_ms"), int)
        assert captured["last_approved_at_ms"] > 0
        # v0.2.53.51 audit 落档:1 条 record,affected_id="999"
        assert audit_store.count() == 1
        records = audit_store.list_recent(limit=1)
        assert records[0]["action"] == "approve_outbox"
        assert records[0]["affected_id"] == "999"
        assert records[0]["write_executed"] is True


class TestBusinessWriterImplRealWriteHandlerCancelled:
    """v0.2.53.49 cancel_outbox 写保护锁开 + fake store.

    v0.2.53.51 升级(audit 真实落档):
    - 注入 InMemoryApprovalGateAuditStore
    - 断言 audit_id 真实 + audit_store 收到 1 条 record
    """

    def test_real_write_calls_update_status_with_none_approved_at(self) -> None:
        """cancel_outbox 必须传 last_approved_at_ms=None(D5.6.3 P1-1 必传 None 规则).

        撞坑 #71 修复(2026-06-30):契约值改为小写,与 OutboxStatus StrEnum 对齐。
        """
        captured: dict[str, Any] = {}

        def _fake_update_status(**kw: Any) -> SimpleNamespace:
            captured.update(kw)
            return SimpleNamespace(id=999)

        fake_store = SimpleNamespace(update_status=_fake_update_status)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        result = writer.cancel_outbox("777", audit=AuditContext.default())

        assert result.success is True
        assert result.affected_id == "999"
        # 撞坑 #71 修复:new_status 与 OutboxStatus 枚举值一致(小写)
        assert captured.get("new_status") == "cancelled"
        assert captured.get("from_status") == "pending_send"
        assert captured.get("last_approved_at_ms") is None
        # v0.2.53.51 audit 落档
        assert result.audit_id == "audit:1"
        assert audit_store.count() == 1
        records = audit_store.list_recent(limit=1)
        assert records[0]["action"] == "cancel_outbox"
        assert records[0]["affected_id"] == "999"


class TestBusinessWriterImplRealWriteHandlerConfirmNote:
    """v0.2.53.49 confirm_note 写保护锁开 + fake note_confirm_service.

    v0.2.53.51 升级(audit 真实落档).
    """

    def test_real_write_calls_confirm_note(self) -> None:
        """写保护锁开 → 真实调 note_confirm_service.confirm_note(target_id)."""

        captured: dict[str, Any] = {}

        def _fake_confirm_note(*, apple_note_id: str) -> None:
            captured["apple_note_id"] = apple_note_id

        fake_service = SimpleNamespace(confirm_note=_fake_confirm_note)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            note_confirm_service=cast(Any, fake_service),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        result = writer.confirm_note("note-xyz", audit=AuditContext.default())

        assert result.success is True
        assert result.affected_id == "note-xyz"
        assert captured.get("apple_note_id") == "note-xyz"
        # v0.2.53.51 audit 落档:affected_id=target_id
        assert result.audit_id == "audit:1"
        assert audit_store.count() == 1
        records = audit_store.list_recent(limit=1)
        assert records[0]["action"] == "confirm_note"
        assert records[0]["affected_id"] == "note-xyz"


class TestBusinessWriterImplRealWriteHandlerDismissAnomaly:
    """v0.2.53.49 dismiss_anomaly 写保护锁开 + fake anomaly_dismissal_service.

    v0.2.53.51 升级(audit 真实落档).
    """

    def test_real_write_calls_dismiss_with_reason(self) -> None:
        """写保护锁开 → 真实调 anomaly_dismissal_service.dismiss(target_id, reason)."""

        captured: dict[str, Any] = {}

        def _fake_dismiss(*, anomaly_id: str, reason: str) -> None:
            captured["anomaly_id"] = anomaly_id
            captured["reason"] = reason

        fake_service = SimpleNamespace(dismiss=_fake_dismiss)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            anomaly_dismissal_service=cast(Any, fake_service),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        audit = AuditContext(actor="tester", reason="test reason for pitfall #18")
        result = writer.dismiss_anomaly("2026-06-26|星巴克|38.50", audit=audit)

        assert result.success is True
        assert result.affected_id == "2026-06-26|星巴克|38.50"
        assert captured.get("anomaly_id") == "2026-06-26|星巴克|38.50"
        assert captured.get("reason") == "test reason for pitfall #18"
        # v0.2.53.51 audit 落档:reason="test reason for pitfall #18"
        assert result.audit_id == "audit:1"
        assert audit_store.count() == 1
        records = audit_store.list_recent(limit=1)
        assert records[0]["action"] == "dismiss_anomaly"
        assert records[0]["affected_id"] == "2026-06-26|星巴克|38.50"
        assert records[0]["reason"] == "test reason for pitfall #18"
        assert records[0]["actor"] == "tester"


class TestBusinessWriterImplWriteProtectionDefaultLocked:
    """v0.2.53.49 默认写保护锁锁定(撞坑 #18 风险门控)— 4 动作 raise.

    v0.2.53.51 升级(audit 不落档):
    - 写保护锁 raise 时 audit_store 不应被调用(撞坑 #18 「日志」语义)
    - 验证:即使注入 audit_store,count 仍为 0
    """

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
        """默认 _real_write_handler_enabled=False → 4 动作 raise(写保护锁风险门控).

        v0.2.53.51 边界:写保护锁 raise 时 audit 不落档(撞坑 #18 「日志」语义).
        """
        kwargs = cast(Any, kw)
        audit_store = InMemoryApprovalGateAuditStore()
        kwargs["audit_store"] = audit_store
        writer = BusinessWriterImpl(**kwargs)
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            getattr(writer, method_name)("1", audit=AuditContext.default())
        # v0.2.53.51 验证:写保护锁 raise 时 audit_store 不被调用
        assert audit_store.count() == 0

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
            enable_path_4_write=True,
        )
        assert writer._real_write_handler_enabled is True  # noqa: SLF001


# ============================================================
# v0.2.53.51 audit 真实落档测试(覆盖成功/失败/拒写/dry-run 不落档)
# ============================================================


class TestBusinessWriterImplAuditSuccess:
    """v0.2.53.51 audit 落档 — 4 类动作成功路径.

    边界(沿 v0.2.53.51):
        - 写保护锁开 + 依赖注入 + 有效 target_id + service 成功
        - audit_store.record() 收到 1 条 success=True record
        - WriteResult.audit_id 是 "audit:N" 格式
    """

    @pytest.mark.parametrize(
        ("method_name", "fake_dep_kw", "target_id", "expected_affected_id"),
        [
            (
                "approve_outbox",
                {
                    "outbox_store": SimpleNamespace(
                        update_status=lambda **kw: SimpleNamespace(id=100)
                    )
                },
                "100",
                "100",
            ),
            (
                "cancel_outbox",
                {
                    "outbox_store": SimpleNamespace(
                        update_status=lambda **kw: SimpleNamespace(id=200)
                    )
                },
                "200",
                "200",
            ),
            (
                "confirm_note",
                {
                    "note_confirm_service": SimpleNamespace(
                        confirm_note=lambda *, apple_note_id: None
                    )
                },
                "note-1",
                "note-1",
            ),
            (
                "dismiss_anomaly",
                {
                    "anomaly_dismissal_service": SimpleNamespace(
                        dismiss=lambda *, anomaly_id, reason: None
                    )
                },
                "2026-06-26|星巴克|38.50",
                "2026-06-26|星巴克|38.50",
            ),
        ],
    )
    def test_audit_recorded_on_success(
        self,
        method_name: str,
        fake_dep_kw: dict[str, Any],
        target_id: str,
        expected_affected_id: str,
    ) -> None:
        """4 类动作成功路径都落档 audit(success=True, affected_id)."""
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
            **cast(Any, fake_dep_kw),
        )
        result = getattr(writer, method_name)(
            target_id, audit=AuditContext(actor="audit_test", reason="success path")
        )
        assert result.success is True
        assert result.affected_id == expected_affected_id
        # v0.2.53.51:audit_id 真实 "audit:1" 格式
        assert result.audit_id == "audit:1"
        assert audit_store.count() == 1
        record = audit_store.list_recent(limit=1)[0]
        assert record["action"] == method_name
        assert record["target_id"] == target_id
        assert record["affected_id"] == expected_affected_id
        assert record["write_executed"] is True
        assert record["error"] is None
        assert record["actor"] == "audit_test"
        assert record["reason"] == "success path"


class TestBusinessWriterImplAuditFailure:
    """v0.2.53.51 audit 落档 — service 抛异常时也落档.

    边界(沿 v0.2.53.51 + 撞坑 #18 「日志」语义):
        - 写保护锁开 + 依赖注入 + 有效 target_id + service throws
        - audit_store.record() 收到 1 条 success=False record(带 error)
        - 异常透传(用户主动操作必须看到 ValueError,沿 note_confirm_service.py:113-115)
    """

    def test_audit_recorded_on_service_failure(self) -> None:
        """approve_outbox service 抛异常 → audit 落档(success=False, error)+ 异常透传."""

        def _fake_update_status_raises(**kw: Any) -> SimpleNamespace:
            raise ValueError("outbox not found")

        fake_store = SimpleNamespace(update_status=_fake_update_status_raises)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        with pytest.raises(ValueError, match="outbox not found"):
            writer.approve_outbox("404", audit=AuditContext(actor="audit_failure_test", reason=""))
        # v0.2.53.51:failure 也落档
        assert audit_store.count() == 1
        record = audit_store.list_recent(limit=1)[0]
        assert record["action"] == "approve_outbox"
        assert record["target_id"] == "404"
        assert record["affected_id"] is None
        assert record["write_executed"] is True
        assert record["error"] is not None
        assert "ValueError" in record["error"]
        assert "outbox not found" in record["error"]

    def test_audit_recorded_on_cancel_service_failure(self) -> None:
        """cancel_outbox service 抛异常 → audit 落档 + 异常透传."""

        def _fake_update_status_raises(**kw: Any) -> SimpleNamespace:
            raise RuntimeError("DB connection lost")

        fake_store = SimpleNamespace(update_status=_fake_update_status_raises)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        with pytest.raises(RuntimeError, match="DB connection lost"):
            writer.cancel_outbox("500", audit=AuditContext.default())
        assert audit_store.count() == 1
        record = audit_store.list_recent(limit=1)[0]
        assert record["action"] == "cancel_outbox"
        assert "RuntimeError" in record["error"]

    def test_audit_recorded_on_confirm_note_failure(self) -> None:
        """confirm_note service 抛异常 → audit 落档 + 异常透传."""

        def _fake_confirm_raises(*, apple_note_id: str) -> None:
            raise ValueError(f"note {apple_note_id} not confirmed")

        fake_service = SimpleNamespace(confirm_note=_fake_confirm_raises)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            note_confirm_service=cast(Any, fake_service),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        with pytest.raises(ValueError, match="not confirmed"):
            writer.confirm_note("note-404", audit=AuditContext.default())
        assert audit_store.count() == 1
        record = audit_store.list_recent(limit=1)[0]
        assert record["action"] == "confirm_note"
        assert record["affected_id"] is None

    def test_audit_recorded_on_dismiss_anomaly_failure(self) -> None:
        """dismiss_anomaly service 抛异常 → audit 落档 + 异常透传."""

        def _fake_dismiss_raises(*, anomaly_id: str, reason: str) -> None:
            raise ValueError(f"anomaly {anomaly_id} invalid")

        fake_service = SimpleNamespace(dismiss=_fake_dismiss_raises)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            anomaly_dismissal_service=cast(Any, fake_service),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        with pytest.raises(ValueError, match="invalid"):
            writer.dismiss_anomaly("2026-06-26|星巴克|38.50", audit=AuditContext.default())
        assert audit_store.count() == 1
        record = audit_store.list_recent(limit=1)[0]
        assert record["action"] == "dismiss_anomaly"


class TestBusinessWriterImplAuditDryRunNoRecord:
    """v0.2.53.51 audit 落档 — dry_run 不落档(撞坑 #18 「日志」语义).

    边界:
        - dry_run() 是预览,不实际执行 → audit 不应被记录
        - 即便 audit_store 注入,dry_run 也不调用 store.record()
    """

    def test_dry_run_does_not_record_audit(self) -> None:
        """dry_run() 不调 audit_store.record()(撞坑 #18 范本)."""
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        decision = writer.dry_run(ACTION_OUTBOX_APPROVE, "123", audit=AuditContext.default())
        # dry_run 返回 WriteDecision(dry_run=True, write_executed=False)
        assert decision.write_executed is False
        assert decision.dry_run is True
        # v0.2.53.51:audit_store 0 条 record
        assert audit_store.count() == 0

    @pytest.mark.parametrize("action", SUPPORTED_ACTIONS)
    def test_dry_run_4_actions_no_audit(self, action: str) -> None:
        """4 类动作 dry_run 都不落档 audit."""
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        writer.dry_run(action, "1", audit=AuditContext.default())
        assert audit_store.count() == 0


class TestBusinessWriterImplAuditInvalidTargetNoRecord:
    """v0.2.53.51 audit 落档 — invalid_target_id 不落档(撞坑 #18 「日志」语义).

    边界:
        - 参数校验失败(invalid_target_id)是用户输入问题,非写操作尝试
        - audit 不应被记录(避免日志污染)
    """

    @pytest.mark.parametrize(
        ("method_name", "kw", "bad_target_id"),
        [
            ("approve_outbox", {"outbox_store": SimpleNamespace()}, cast(str, 123)),
            ("cancel_outbox", {"outbox_store": SimpleNamespace()}, cast(str, None)),
            ("confirm_note", {"note_confirm_service": SimpleNamespace()}, ""),
            ("dismiss_anomaly", {"anomaly_dismissal_service": SimpleNamespace()}, "   "),
        ],
    )
    def test_invalid_target_id_no_audit(
        self,
        method_name: str,
        kw: dict[str, Any],
        bad_target_id: Any,
    ) -> None:
        """参数非法 → WriteResult(success=False),不落档 audit(撞坑 #18 范本)."""
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
            **cast(Any, kw),
        )
        result = getattr(writer, method_name)(bad_target_id, audit=AuditContext.default())
        assert result.success is False
        assert result.error == "invalid_target_id"
        # v0.2.53.51:invalid_target_id 不落档
        assert audit_store.count() == 0


class TestBusinessWriterImplAuditStoreFallback:
    """v0.2.53.51 audit 落档 — audit_store=None 走默认 Stub(撞坑 #65 范本).

    边界:
        - audit_store 默认 None → ApprovalGateAuditStoreStub(is_enabled=False)
        - record() 永远返回 success=False
        - WriteResult.audit_id = None(Stub 不落档)
    """

    def test_audit_store_none_uses_stub(self) -> None:
        """audit_store=None → ApprovalGateAuditStoreStub(撞坑 #65 默认 Stub)."""

        class _FakeUpdated:
            id = 999

        fake_store = SimpleNamespace(
            update_status=lambda **kw: _FakeUpdated(),
        )
        # 显式不传 audit_store,验证默认 Stub
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        result = writer.approve_outbox("123", audit=AuditContext.default())
        assert result.success is True
        # Stub 返回 audit_id=None(撞坑 #65 默认禁写)
        assert result.audit_id is None

    def test_audit_store_failure_does_not_block_business(self) -> None:
        """audit_store.record() 抛异常 → WriteResult 仍正常返回(撞坑 #18 「日志」语义)."""

        class _FakeUpdated:
            id = 999

        class _BrokenAuditStore:
            def record(self, record: Any) -> Any:
                raise RuntimeError("audit store broken")

            def is_enabled(self) -> bool:
                return True

            def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
                return []

        fake_store = SimpleNamespace(
            update_status=lambda **kw: _FakeUpdated(),
        )
        broken_audit_store = _BrokenAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, fake_store),
            audit_store=cast(Any, broken_audit_store),
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        # audit_store 抛异常,但业务 WriteResult 仍正常
        result = writer.approve_outbox("123", audit=AuditContext.default())
        assert result.success is True
        assert result.affected_id == "999"
        # audit_id=None(落档失败,但不抛异常)
        assert result.audit_id is None


# ============================================================
# v0.2.53.55 Path 4 5th gate preflight — 沿 docs/v0.2.53.53 §7
# 不实施 5th gate,仅断言当前安全状态不变式(撞坑 #18)
# ============================================================


class TestBusinessWriterImplPath4FifthGate:
    """Path 4 5th gate — ENABLE_PATH_4_WRITE env 已实施,锁定 4 个不变式.

    设计意图(沿 docs/v0.2.53.53-path4-launch-checklist §2.3 + §7):
        - 5th gate flag `ENABLE_PATH_4_WRITE` 已从 docs-only 升级为代码严判
        - 锁定 4 不变式:① env 不绕过写保护锁 ② 4th 开但 5th 关仍拒写
          ③ raise 时 audit 不落档 ④ dry_run.required 含 env flag
    """

    def test_enable_path_4_write_env_does_not_bypass_write_protection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不变式 #1:设 `ENABLE_PATH_4_WRITE=1` 后,默认写保护锁未开仍 raise.

        撞坑 #18 风险门控:即便运维误设 5th flag env,只要 `_real_write_handler_enabled=False`
        (默认) 且 handler 未启用,4 动作方法依然 raise NotImplementedError → 不实写.
        """
        monkeypatch.setenv("ENABLE_PATH_4_WRITE", "1")
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, SimpleNamespace()),
            note_confirm_service=cast(Any, SimpleNamespace()),
            anomaly_dismissal_service=cast(Any, SimpleNamespace()),
        )
        audit = AuditContext.default()
        # 4 动作方法仍 raise(写保护锁未开,沿 v0.2.53.49 + 撞坑 #18)
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.approve_outbox("123", audit=audit)
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.cancel_outbox("123", audit=audit)
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.confirm_note("note-abc", audit=audit)
        with pytest.raises(NotImplementedError, match="写保护锁未开"):
            writer.dismiss_anomaly("anomaly-key", audit=audit)

    def test_real_write_handler_true_but_fifth_gate_closed_raises(self) -> None:
        """不变式 #2:4th gate 开但 5th gate 关 → 仍拒写."""
        writer = BusinessWriterImpl(
            outbox_store=cast(
                Any, SimpleNamespace(update_status=lambda **kw: SimpleNamespace(id=1))
            ),
            real_write_handler_enabled=True,
            enable_path_4_write=False,
        )
        with pytest.raises(NotImplementedError, match="ENABLE_PATH_4_WRITE=1"):
            writer.approve_outbox("1", audit=AuditContext.default())

    def test_five_gates_open_allows_fake_service_call(self) -> None:
        """不变式 #3:4th + 5th 全开 → 允许进入 fake service 调用."""
        captured: dict[str, Any] = {}

        def _fake_update_status(**kw: Any) -> SimpleNamespace:
            captured.update(kw)
            return SimpleNamespace(id=42)

        writer = BusinessWriterImpl(
            outbox_store=cast(Any, SimpleNamespace(update_status=_fake_update_status)),
            audit_store=InMemoryApprovalGateAuditStore(),
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        result = writer.approve_outbox("42", audit=AuditContext.default())
        assert result.success is True
        assert result.write_executed is True
        assert captured["outbox_id"] == 42

    def test_4_actions_dont_audit_when_raising(self) -> None:
        """不变式 #4:写保护锁 raise 时 `audit_store.record()` 不被调用.

        撞坑 #18 「日志」语义:audit 落档仅在写保护锁开 + 真实 service 调用后发生;
        raise 路径绝不落档(避免「silent success」假象).
        """
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=cast(Any, SimpleNamespace()),
            note_confirm_service=cast(Any, SimpleNamespace()),
            anomaly_dismissal_service=cast(Any, SimpleNamespace()),
            audit_store=cast(Any, audit_store),
            # real_write_handler_enabled 默认 False
        )
        audit = AuditContext.default()
        with pytest.raises(NotImplementedError):
            writer.approve_outbox("123", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.cancel_outbox("123", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.confirm_note("note-abc", audit=audit)
        with pytest.raises(NotImplementedError):
            writer.dismiss_anomaly("anomaly-key", audit=audit)
        assert audit_store.count() == 0, "写保护锁 raise 不应落档 audit"

    def test_dry_run_required_includes_env_flag_until_open(self) -> None:
        """不变式 #5:`dry_run.required` 含 `ENABLE_PATH_4_WRITE=1` 直到第 5 门开启."""
        writer = BusinessWriterImpl()
        audit = AuditContext.default()
        for action in SUPPORTED_ACTIONS:
            decision = writer.dry_run(action, "any_target", audit=audit)
            assert "ENABLE_PATH_4_WRITE=1" in decision.required
            assert "DASHBOARD_WRITE_API=1" in decision.required
            assert "confirm_text=CONFIRM_WRITE" in decision.required
            assert "BUSINESS_WRITER_ENABLED=1" in decision.required
            assert "real_write_handler_enabled" in decision.required

    def test_dry_run_would_allow_true_when_internal_gates_open(self) -> None:
        """4th + 5th 内部门全开 → writer dry_run would_allow=True."""
        writer = BusinessWriterImpl(
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        decision = writer.dry_run(ACTION_OUTBOX_APPROVE, "1", audit=AuditContext.default())
        assert decision.would_allow is True
        assert decision.error is None
        assert "ENABLE_PATH_4_WRITE=1" not in decision.required
        assert "real_write_handler_enabled" not in decision.required


# ============================================================
# v0.2.55.2 真 OutboxStore + 真写路径契约测试(防 #71 漂移)
# 沿 tests/core/conftest.py 范本(InMemory SQLite + Base.metadata.create_all)
# ============================================================


class TestBusinessWriterImplRealWriteOutboxContract:
    """v0.2.55.2 真 OutboxStore + 真写路径契约测试(撞坑 #71 防漂移).

    与 v0.2.53.49 fake SimpleNamespace 关键差异:
        - 真 OutboxStore(session_factory)+ InMemory SQLite + Base.metadata.create_all
        - 断言用 OutboxStatus enum.value(自动跟踪 enum 改名,不是硬编码字符串)
        - DB 真实状态变化验证(OutboxEntry.status / last_approved_at_ms)

    撞坑 #71 修复(2026-06-30)防漂移:
        - 任何调 outbox_store.update_status 时 status 字符串漂移(非 6 选 1)
        - 立即被 OutboxStore._normalize_status 严判 ValueError(无需起 HTTP/真 SMTP)
        - 测试断言用 enum.value 双重锁定,任何对 enum 改名都自动同步
        - 沿 [[pitfall-71-outbox-status-case-mismatch]] + [[pitfall-65-opt-in-4-stages]]
    """

    @pytest.fixture
    def engine(self: Any) -> Any:
        """InMemory SQLite + Base.metadata.create_all(沿 tests/core/conftest.py 范本)."""
        from sqlalchemy import create_engine

        from my_ai_employee.core.models import Base
        from my_ai_employee.core.outbox import OutboxEntry  # noqa: F401 — 注册到 Base.metadata
        from my_ai_employee.events.models import Event  # noqa: F401 — FK 依赖

        eng = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(eng)
        yield eng
        eng.dispose()

    @pytest.fixture
    def session_factory(self: Any, engine: Any) -> Any:
        """sessionmaker 工厂."""
        from sqlalchemy.orm import sessionmaker

        return sessionmaker[Any](bind=engine)

    @pytest.fixture
    def outbox_store(self: Any, session_factory: Any) -> Any:
        """真 OutboxStore(撞坑 #71 防漂移关键 — 不再用 SimpleNamespace)."""
        from my_ai_employee.db.outbox import OutboxStore

        return OutboxStore(session_factory)

    def _seed_pending_outbox(self: Any, session_factory: Any, *, email_id: int = 1) -> int:
        """种一条 status=pending_send 的 outbox 条目(供真写路径测试)."""
        from my_ai_employee.core.outbox import OutboxEntry, OutboxStatus

        with session_factory() as s:
            entry = OutboxEntry(
                email_id=email_id,
                subject="真写契约测试",
                body="approve_outbox 真写契约测试 body",
                tone="FORMAL",
                recipient_email="contract-test@example.com",
                status=OutboxStatus.PENDING_SEND.value,
                created_at=1_700_000_000_000,
                last_approved_at_ms=None,
            )
            s.add(entry)
            s.commit()
            s.refresh(entry)
            return int(entry.id)

    def test_approve_outbox_writes_approved_status_to_db(
        self: Any, session_factory: Any, outbox_store: Any
    ) -> None:
        """approve_outbox 真写 → DB row.status == OutboxStatus.APPROVED.value(enum 锁定).

        撞坑 #71 修复(2026-06-30)防漂移:
        - 断言用 OutboxStatus.APPROVED.value(enum 自动跟踪,不依赖硬编码字符串)
        - 真 OutboxStore.update_status 严判 6 选 1,任何硬编码漂移立即 ValueError
        - 双层防御:契约层(enum 严判)+ 测试层(enum.value 断言)
        """
        from my_ai_employee.core.outbox import OutboxEntry, OutboxStatus

        outbox_id = self._seed_pending_outbox(session_factory, email_id=101)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=outbox_store,
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        result = writer.approve_outbox(str(outbox_id), audit=AuditContext.default())

        # 业务层 WriteResult 断言
        assert result.success is True
        assert result.affected_id == str(outbox_id)
        assert result.error is None
        assert result.write_executed is True

        # DB 真实状态断言(撞坑 #71 防漂移:用 enum.value 锁定)
        with session_factory() as s:
            row = s.get(OutboxEntry, outbox_id)
            assert row is not None
            assert row.status == OutboxStatus.APPROVED.value
            # D5.6.3 P1-1:APPROVED 时 last_approved_at_ms 必写入(非 None,int > 0)
            assert row.last_approved_at_ms is not None
            assert isinstance(row.last_approved_at_ms, int)
            assert row.last_approved_at_ms > 0

        # audit 落档断言
        assert result.audit_id == "audit:1"
        assert audit_store.count() == 1
        record = audit_store.list_recent(limit=1)[0]
        assert record["action"] == "approve_outbox"
        assert record["affected_id"] == str(outbox_id)
        assert record["write_executed"] is True
        assert record["error"] is None

    def test_cancel_outbox_writes_cancelled_status_to_db(
        self: Any, session_factory: Any, outbox_store: Any
    ) -> None:
        """cancel_outbox 真写 → DB row.status == OutboxStatus.CANCELLED.value(enum 锁定).

        撞坑 #71 修复防漂移 + last_approved_at_ms 保留原值(PENDING_SEND 来 NULL):
        - cancel_outbox 必传 last_approved_at_ms=None(D5.6.3 P1-1 严判)
        - 保留 row.last_approved_at_ms(PENDING_SEND 时 None,继续 None,不动)
        """
        from my_ai_employee.core.outbox import OutboxEntry, OutboxStatus

        outbox_id = self._seed_pending_outbox(session_factory, email_id=202)
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=outbox_store,
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        result = writer.cancel_outbox(str(outbox_id), audit=AuditContext.default())

        # 业务层 WriteResult 断言
        assert result.success is True
        assert result.affected_id == str(outbox_id)
        assert result.error is None
        assert result.write_executed is True

        # DB 真实状态断言(撞坑 #71 防漂移:用 enum.value 锁定)
        with session_factory() as s:
            row = s.get(OutboxEntry, outbox_id)
            assert row is not None
            assert row.status == OutboxStatus.CANCELLED.value
            # D5.6.3 P1-1:CANCELLED 时 last_approved_at_ms 必传 None,保留原值(PENDING_SEND 来 None)
            assert row.last_approved_at_ms is None

        # audit 落档断言
        assert result.audit_id == "audit:1"
        assert audit_store.count() == 1
        record = audit_store.list_recent(limit=1)[0]
        assert record["action"] == "cancel_outbox"
        assert record["affected_id"] == str(outbox_id)
        assert record["write_executed"] is True
        assert record["error"] is None
