"""v0.2.53.6 — OutboxDraftServiceImpl 测试."""

from __future__ import annotations

import time
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.db.outbox import OutboxStore
from my_ai_employee.menu_bar.outbox_draft_service import (
    OutboxDraftServiceImpl,
    OutboxDraftServiceStub,
)


class _FakeEntry:
    def __init__(
        self,
        *,
        outbox_id: int,
        subject: str,
        status: str,
        created_at: int,
        body: str = "private body should not leak",
    ) -> None:
        self.id = outbox_id
        self.email_id = outbox_id + 100
        self.subject = subject
        self.body = body
        self.recipient_email = "user@example.com"
        self.status = status
        self.priority = "normal"
        self.created_at = created_at
        self.sla_due_at_ms = created_at + 3_600_000
        self.last_approved_at_ms = None


class _FakeOutboxStore:
    def __init__(self, entries_by_status: dict[str, list[_FakeEntry]] | None = None) -> None:
        self.entries_by_status = entries_by_status or {}
        self.calls: list[tuple[str, int]] = []

    def by_status(self, status: str, limit: int = 100) -> list[_FakeEntry]:
        self.calls.append((status, limit))
        return list(self.entries_by_status.get(status, []))[:limit]


class _RaisingOutboxStore:
    def by_status(self, status: str, limit: int = 100) -> list[Any]:
        raise RuntimeError("db unavailable")


@pytest.fixture
def sqlite_outbox_store() -> OutboxStore:
    """真实 OutboxStore + SQLite in-memory,不碰 Keychain/真实 DB."""
    engine = create_engine("sqlite:///:memory:")
    from my_ai_employee.events import models as _events_models  # noqa: F401

    Base.metadata.create_all(engine)
    sf = sessionmaker[Any](bind=engine)
    return OutboxStore(sf)


def test_stub_defaults() -> None:
    stub = OutboxDraftServiceStub.get_default_stub()
    assert stub.get_pending_draft_count() == 0
    assert stub.list_pending_drafts() == []


def test_impl_requires_outbox_store() -> None:
    with pytest.raises(TypeError, match="outbox_store 必填"):
        OutboxDraftServiceImpl(None)

    with pytest.raises(TypeError, match="by_status"):
        OutboxDraftServiceImpl(object())


def test_impl_counts_pending_send_and_approved() -> None:
    store = _FakeOutboxStore(
        {
            "pending_send": [
                _FakeEntry(outbox_id=1, subject="待审批", status="pending_send", created_at=2)
            ],
            "approved": [
                _FakeEntry(outbox_id=2, subject="已审批", status="approved", created_at=1)
            ],
        }
    )
    service = OutboxDraftServiceImpl(store)

    assert service.get_pending_draft_count() == 2
    assert store.calls == [("pending_send", 10_000), ("approved", 10_000)]


def test_impl_list_pending_drafts_sorts_and_hides_body() -> None:
    store = _FakeOutboxStore(
        {
            "pending_send": [
                _FakeEntry(outbox_id=1, subject="较新", status="pending_send", created_at=20)
            ],
            "approved": [_FakeEntry(outbox_id=2, subject="较旧", status="approved", created_at=10)],
        }
    )
    service = OutboxDraftServiceImpl(store)

    rows = service.list_pending_drafts(limit=10)

    assert [r["outbox_id"] for r in rows] == [2, 1]
    assert rows[0]["subject"] == "较旧"
    assert rows[0]["status"] == "approved"
    assert "body" not in rows[0]


def test_impl_limit_validation() -> None:
    service = OutboxDraftServiceImpl(_FakeOutboxStore())
    for bad in (True, "10", 0, 101):
        with pytest.raises(ValueError, match="limit 必须"):
            service.list_pending_drafts(limit=bad)


def test_impl_swallows_query_exceptions() -> None:
    service = OutboxDraftServiceImpl(_RaisingOutboxStore())
    assert service.get_pending_draft_count() == 0
    assert service.list_pending_drafts(limit=10) == []


def test_impl_with_real_outbox_store(sqlite_outbox_store: OutboxStore) -> None:
    older = sqlite_outbox_store.insert(
        email_id=1,
        subject="真实 pending",
        body="hello body pending",
        tone="FORMAL",
        recipient_email="a@example.com",
        created_at=1_700_000_000_000,
    )
    newer = sqlite_outbox_store.insert(
        email_id=2,
        subject="真实 approved",
        body="hello body approved",
        tone="FORMAL",
        recipient_email="b@example.com",
        created_at=1_700_000_001_000,
    )
    sqlite_outbox_store.update_status(
        newer.id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(time.time() * 1000),
    )

    service = OutboxDraftServiceImpl(sqlite_outbox_store)

    assert service.get_pending_draft_count() == 2
    rows = service.list_pending_drafts(limit=10)
    assert [r["outbox_id"] for r in rows] == [older.id, newer.id]
    assert rows[0]["subject"] == "真实 pending"
    assert rows[1]["status"] == "approved"
    assert "body" not in rows[0]
