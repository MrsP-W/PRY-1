"""AgentRun store + email_to_draft 工作流回归。"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.events.models import Event, EventType
from my_ai_employee.events.store import EventStore
from my_ai_employee.policy.task_packet import TaskPacket
from my_ai_employee.runtime.models import (
    WORKFLOW_EMAIL_TO_DRAFT,
    AgentRunRecord,
    AgentRunStatus,
)
from my_ai_employee.runtime.store import (
    AgentRunIllegalTransitionError,
    AgentRunStore,
)
from my_ai_employee.runtime.workflows.email_to_draft import EmailToDraftInput, run_email_to_draft


@pytest.fixture()
def session_factory() -> Any:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def store(session_factory: Any) -> AgentRunStore:
    return AgentRunStore(session_factory)


@pytest.fixture()
def event_store(session_factory: Any) -> EventStore:
    return EventStore(session_factory)


def _packet() -> TaskPacket:
    return TaskPacket(
        objective="email_to_draft",
        scope=["email"],
        resources=[],
        acceptance_criteria=["draft_ready"],
        model="stub",
        provider="stub",
    )


def test_illegal_transition_rejected(store: AgentRunStore) -> None:
    row = store.create(workflow=WORKFLOW_EMAIL_TO_DRAFT, task_packet=_packet())
    with pytest.raises(AgentRunIllegalTransitionError):
        store.transition(row.run_id, AgentRunStatus.SUCCEEDED)


def test_email_to_draft_dry_run_stops_at_approval(
    store: AgentRunStore, event_store: EventStore
) -> None:
    result = run_email_to_draft(
        store,
        EmailToDraftInput(
            email={"id": "e1", "subject": "hello"},
            dry_run=True,
        ),
        event_store=event_store,
    )
    assert result.status == AgentRunStatus.AWAITING_APPROVAL.value
    assert "draft" in result.steps
    assert result.trace_id
    loaded = store.get_by_run_id(result.run_id)
    assert loaded.status == AgentRunStatus.AWAITING_APPROVAL.value


def test_email_to_draft_resume_idempotent_email_id(store: AgentRunStore) -> None:
    inserts: list[dict[str, Any]] = []

    def outbox_insert(payload: dict[str, Any]) -> str:
        inserts.append(payload)
        return "outbox-1"

    first = run_email_to_draft(
        store,
        EmailToDraftInput(email={"id": "e2", "subject": "x"}, dry_run=False),
        outbox_insert_fn=outbox_insert,
    )
    assert first.status == AgentRunStatus.AWAITING_APPROVAL.value
    assert len(inserts) == 1

    second = run_email_to_draft(
        store,
        EmailToDraftInput(
            email={"id": "e2", "subject": "x"},
            dry_run=False,
            approval_decision="approve",
        ),
        outbox_insert_fn=outbox_insert,
        existing_run_id=first.run_id,
    )
    assert second.status == AgentRunStatus.SUCCEEDED.value
    assert len(inserts) == 1


def test_checkpoint_on_classify_failure(store: AgentRunStore) -> None:
    def boom(_email: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("classify_boom")

    result = run_email_to_draft(
        store,
        EmailToDraftInput(email={"id": "e3", "subject": "x"}, dry_run=True),
        classify_fn=boom,
    )
    assert result.status == AgentRunStatus.CHECKPOINTED.value
    assert result.error_code == "RuntimeError"

    recovered = run_email_to_draft(
        store,
        EmailToDraftInput(email={"id": "e3", "subject": "x"}, dry_run=True),
        existing_run_id=result.run_id,
        classify_fn=lambda e: {"category": "TODO", "confidence": 1.0},
    )
    assert recovered.status == AgentRunStatus.AWAITING_APPROVAL.value


def test_agent_run_events_carry_trace_id(
    store: AgentRunStore, event_store: EventStore, session_factory: Any
) -> None:
    result = run_email_to_draft(
        store,
        EmailToDraftInput(email={"id": "e4", "subject": "URGENT x"}, dry_run=True),
        event_store=event_store,
    )
    with session_factory() as session:
        rows = list(session.scalars(select(Event)).all())
        assert rows
        assert any(r.event == EventType.AGENT_RUN_STARTED.value for r in rows)
        agent_rows = [r for r in rows if str(r.event).startswith("agent.run.")]
        assert agent_rows
        assert all((r.event_metadata or {}).get("trace_id") == result.trace_id for r in agent_rows)


def test_agent_run_record_registered() -> None:
    assert AgentRunRecord.__tablename__ == "agent_runs"
