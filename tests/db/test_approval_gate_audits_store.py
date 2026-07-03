"""ApprovalGateAuditStoreImpl 集成测试 — 真实 SQL 落档."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.db.approval_gate_audits import ApprovalGateAuditStoreImpl
from my_ai_employee.menu_bar.approval_gate_audit import AuditRecord


@pytest.fixture
def audit_store() -> ApprovalGateAuditStoreImpl:
    from my_ai_employee.events import models as _events_models  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, expire_on_commit=False)
    return ApprovalGateAuditStoreImpl(sf)


def _sample_record(
    *,
    action: str = "outbox.approve",
    target_id: str = "1",
    actor: str = "local_dashboard",
    reason: str = "test",
    write_executed: bool = True,
    affected_id: str | None = "1",
    error: str | None = None,
    executed_at_ms: int | None = None,
) -> AuditRecord:
    return AuditRecord(
        action=action,
        target_id=target_id,
        actor=actor,
        reason=reason,
        write_executed=write_executed,
        affected_id=affected_id,
        error=error,
        executed_at_ms=executed_at_ms if executed_at_ms is not None else int(time.time() * 1000),
    )


def test_impl_is_enabled(audit_store: ApprovalGateAuditStoreImpl) -> None:
    assert audit_store.is_enabled() is True


def test_record_and_list_recent(audit_store: ApprovalGateAuditStoreImpl) -> None:
    now = int(time.time() * 1000)
    result = audit_store.record(
        _sample_record(executed_at_ms=now, target_id="42", action="outbox.approve")
    )
    assert result.success is True
    assert result.audit_id == "audit:1"

    items = audit_store.list_recent(limit=10)
    assert len(items) == 1
    assert items[0]["target_id"] == "42"
    assert items[0]["write_executed"] is True
    assert items[0]["decision"] is None


def test_list_recent_order_desc(audit_store: ApprovalGateAuditStoreImpl) -> None:
    audit_store.record(_sample_record(executed_at_ms=100, target_id="old"))
    audit_store.record(_sample_record(executed_at_ms=200, target_id="new"))
    items = audit_store.list_recent(limit=10)
    assert [i["target_id"] for i in items] == ["new", "old"]
