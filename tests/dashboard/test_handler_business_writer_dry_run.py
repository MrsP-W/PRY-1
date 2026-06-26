"""v0.2.53.21 handler 接入 BusinessWriter dry-run 测试.

边界(沿 v0.2.53.14 §8 + v0.2.53.19 + 撞坑 #65):
    - 仅当 ApprovalGate 双门通过 + dry_run=True 才合并 writer.dry_run 结果
    - 默认 writer 为 BusinessWriterStub(would_allow=False)
    - 仍保证 write_executed=False(实际写入留 8/1 后)
"""

from __future__ import annotations

from typing import Any

import pytest

from my_ai_employee.dashboard.business_writer import (
    AuditContext,
    BusinessWriterStub,
    WriteDecision,
    WriteResult,
)
from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.handlers import DashboardHandler


def _make_handler(ctx: DashboardContext) -> DashboardHandler:
    """构造带 ctx 的 handler 用于 _merge_writer_dry_run 测试."""
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_context = ctx
    return handler


def _decision(**overrides: Any) -> dict[str, Any]:
    """构造 merge 测试用 decision dict."""
    base: dict[str, Any] = {
        "approval_gate_passed": True,
        "dry_run": True,
        "error": None,
        "would_allow": False,
        "write_executed": False,
        "required": [],
        "action": "outbox.approve",
        "target_id": "123",
        "audit": {"actor": "local_dashboard", "reason": "", "source": "dashboard"},
    }
    base.update(overrides)
    return base


class TestMergeWriterDryRunGuard:
    """_merge_writer_dry_run 触发条件严判(沿 v0.2.53.19 §设计)."""

    def test_no_merge_when_approval_gate_not_passed(self) -> None:
        """approval_gate_passed=False → 不合并(decision 不变)."""
        ctx = DashboardContext()
        handler = _make_handler(ctx)
        decision = _decision(
            approval_gate_passed=False,
            error="write_disabled",
            required=["DASHBOARD_WRITE_API=1"],
            action=None,
            target_id=None,
        )
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged == decision
        assert "business_writer_error" not in merged

    def test_no_merge_when_dry_run_false(self) -> None:
        """dry_run=False → 不合并(实际写入路径,留 8/1 后)."""
        ctx = DashboardContext()
        handler = _make_handler(ctx)
        decision = _decision(dry_run=False, required=["DASHBOARD_WRITE_API=1"])
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged == decision

    def test_no_merge_when_action_unsupported(self) -> None:
        """action 不在白名单 → 不合并."""
        ctx = DashboardContext()
        handler = _make_handler(ctx)
        decision = _decision(action="unknown.action")
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged == decision

    def test_no_merge_when_target_id_empty(self) -> None:
        """target_id 空 → 不合并."""
        ctx = DashboardContext()
        handler = _make_handler(ctx)
        decision = _decision(target_id="")
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged == decision


class TestMergeWriterDryRunWithStub:
    """默认 BusinessWriterStub 时合并结果(would_allow=False)."""

    def test_merge_default_stub_writer(self) -> None:
        """默认 Stub writer dry_run 返回 would_allow=False."""
        ctx = DashboardContext()
        handler = _make_handler(ctx)
        decision = _decision(
            required=["DASHBOARD_WRITE_API=1", "confirm_text=CONFIRM_WRITE"],
            audit={"actor": "local_dashboard", "reason": "用户点击审批", "source": "dashboard"},
        )
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged["would_allow"] is False
        assert merged["business_writer_error"] == "write_not_implemented"
        assert "BUSINESS_WRITER_ENABLED=1" in merged["required"]
        assert "business_writer_implementation" in merged["required"]
        assert merged["write_executed"] is False


class TestMergeWriterDryRunWithMockWriter:
    """Mock Writer writer dry_run would_allow=True 测试."""

    class _MockAllowWriter(BusinessWriterStub):
        """Mock writer — dry_run 返回 would_allow=True."""

        def dry_run(
            self,
            action: str,
            target_id: str,
            *,
            audit: AuditContext,
        ) -> WriteDecision:
            return WriteDecision(
                action=action,
                target_id=target_id,
                write_enabled=True,
                would_allow=True,
                write_executed=False,
                dry_run=True,
                audit=audit,
                error=None,
                reason="mock: writer 就绪",
                required=("writer_ready",),
            )

        def approve_outbox(
            self,
            target_id: str,
            *,
            audit: AuditContext,
        ) -> WriteResult:
            return WriteResult(
                success=True,
                affected_id=target_id,
                error=None,
                reason="mock approved",
                audit_id=None,
                write_executed=False,
            )

    def test_merge_mock_writer_would_allow_true(self) -> None:
        """Mock writer dry_run 返回 would_allow=True 时合并."""
        ctx = DashboardContext().with_business_writer(self._MockAllowWriter())
        handler = _make_handler(ctx)
        decision = _decision(
            required=["DASHBOARD_WRITE_API=1", "confirm_text=CONFIRM_WRITE"],
            audit={"actor": "test_user", "reason": "unit_test", "source": "dashboard"},
        )
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged["would_allow"] is True
        assert merged["business_writer_error"] is None
        assert merged["business_writer_reason"] == "mock: writer 就绪"
        assert "writer_ready" in merged["required"]
        assert merged["write_executed"] is False


class TestMergeWriterDryRunExceptionIsolation:
    """writer 异常隔离(沿撞坑 #65 + v0.2.53.8)."""

    class _BrokenWriter(BusinessWriterStub):
        """Mock writer — dry_run 抛 RuntimeError."""

        def dry_run(
            self,
            action: str,
            target_id: str,
            *,
            audit: AuditContext,
        ) -> WriteDecision:
            raise RuntimeError("writer 内部异常")

    def test_writer_exception_isolated(self) -> None:
        """writer 抛 RuntimeError → decision 不变(approval_gate 决策优先)."""
        ctx = DashboardContext().with_business_writer(self._BrokenWriter())
        handler = _make_handler(ctx)
        decision = _decision(
            required=["DASHBOARD_WRITE_API=1"],
            audit={"actor": "test_user", "reason": "", "source": "dashboard"},
        )
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged == decision


class TestMergeWriterDryRunAll4Actions:
    """4 类动作都触发 writer dry_run 合并."""

    @pytest.mark.parametrize(
        "action",
        [
            "outbox.approve",
            "outbox.cancel",
            "notes.confirm",
            "finance.dismiss_anomaly",
        ],
    )
    def test_all_4_actions_trigger_writer_dry_run(self, action: str) -> None:
        """4 类动作都通过白名单 + 触发 writer dry_run."""
        ctx = DashboardContext()
        handler = _make_handler(ctx)
        decision = _decision(
            action=action,
            target_id="test_target",
            audit={"actor": "test_user", "reason": "test", "source": "dashboard"},
        )
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged["business_writer_error"] == "write_not_implemented"
        assert "BUSINESS_WRITER_ENABLED=1" in merged["required"]


class TestMergeWriterDryRunWriteExecutedInvariant:
    """write_executed 恒为 False 不变式(沿 v0.2.53.11)."""

    def test_write_executed_never_true_after_merge(self) -> None:
        """合并后 write_executed 仍为 False(不会因 writer 就绪而变 True)."""
        ctx = DashboardContext().with_business_writer(
            TestMergeWriterDryRunWithMockWriter._MockAllowWriter()
        )
        handler = _make_handler(ctx)
        decision = _decision(
            audit={"actor": "test_user", "reason": "", "source": "dashboard"},
        )
        merged = handler._merge_writer_dry_run({}, decision)
        assert merged["would_allow"] is True
        assert merged["write_executed"] is False


class TestMergeWriterDryRunAuditContext:
    """AuditContext 沿 v0.2.53.11 audit 字段构造(actor / reason / source)."""

    def test_audit_actor_reason_source_propagated(self) -> None:
        """audit actor / reason / source 从 decision 提取 + 传 writer."""

        captured_audit: list[AuditContext] = []

        class _CaptureWriter(BusinessWriterStub):
            def dry_run(
                self,
                action: str,
                target_id: str,
                *,
                audit: AuditContext,
            ) -> WriteDecision:
                captured_audit.append(audit)
                return WriteDecision(
                    action=action,
                    target_id=target_id,
                    write_enabled=True,
                    would_allow=True,
                    write_executed=False,
                    dry_run=True,
                    audit=audit,
                )

        ctx = DashboardContext().with_business_writer(_CaptureWriter())
        handler = _make_handler(ctx)
        decision = _decision(
            audit={
                "actor": "custom_actor",
                "reason": "custom reason",
                "source": "cli",
            },
        )
        handler._merge_writer_dry_run({}, decision)
        assert len(captured_audit) == 1
        audit = captured_audit[0]
        assert audit.actor == "custom_actor"
        assert audit.reason == "custom reason"
        assert audit.source == "cli"
