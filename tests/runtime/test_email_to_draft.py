"""AgentRun store + email_to_draft 工作流回归。"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from my_ai_employee.ai.capability import TaskType
from my_ai_employee.ai.classifier import EmailClassifier
from my_ai_employee.ai.drafter import EmailDrafter
from my_ai_employee.ai.providers import LLMResponse
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
from my_ai_employee.runtime.workflows.email_to_draft import (
    EmailToDraftInput,
    make_classify_fn,
    make_draft_fn,
    run_email_to_draft,
    stub_classify_fn,
    stub_draft_fn,
)


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


def _stub_kwargs() -> dict[str, Any]:
    return {"classify_fn": stub_classify_fn, "draft_fn": stub_draft_fn}


class _MockRouter:
    def route(
        self,
        *,
        task_type: Any,
        messages: Any,
        temperature: Any,
        max_tokens: Any,
        trace_id: str | None = None,
    ) -> LLMResponse:
        del messages, temperature, max_tokens, trace_id
        if task_type == TaskType.CLASSIFY:
            return LLMResponse(
                content='{"category": "TODO", "confidence": 0.91}',
                model_full_id="mock-classifier",
                input_tokens=10,
                output_tokens=5,
                latency_ms=12,
            )
        return LLMResponse(
            content=(
                '{"subject": "Re: hello", "body": "您好，已收到您的邮件，我们会尽快处理。", '
                '"tone": "FORMAL"}'
            ),
            model_full_id="mock-drafter",
            input_tokens=20,
            output_tokens=30,
            latency_ms=18,
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
        **_stub_kwargs(),
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
        **_stub_kwargs(),
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
        **_stub_kwargs(),
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
        draft_fn=stub_draft_fn,
    )
    assert result.status == AgentRunStatus.CHECKPOINTED.value
    assert result.error_code == "RuntimeError"

    recovered = run_email_to_draft(
        store,
        EmailToDraftInput(email={"id": "e3", "subject": "x"}, dry_run=True),
        existing_run_id=result.run_id,
        **_stub_kwargs(),
    )
    assert recovered.status == AgentRunStatus.AWAITING_APPROVAL.value


def test_agent_run_events_carry_trace_id(
    store: AgentRunStore, event_store: EventStore, session_factory: Any
) -> None:
    result = run_email_to_draft(
        store,
        EmailToDraftInput(email={"id": "e4", "subject": "URGENT x"}, dry_run=True),
        event_store=event_store,
        **_stub_kwargs(),
    )
    with session_factory() as session:
        rows = list(session.scalars(select(Event)).all())
        assert rows
        assert any(r.event == EventType.AGENT_RUN_STARTED.value for r in rows)
        agent_rows = [r for r in rows if str(r.event).startswith("agent.run.")]
        assert agent_rows
        assert all((r.event_metadata or {}).get("trace_id") == result.trace_id for r in agent_rows)


def test_live_classifier_drafter_with_mock_router(store: AgentRunStore) -> None:
    router = _MockRouter()
    classifier = EmailClassifier(router=router)  # type: ignore[arg-type]
    drafter = EmailDrafter(router=router)  # type: ignore[arg-type]

    result = run_email_to_draft(
        store,
        EmailToDraftInput(
            email={
                "id": "e5",
                "subject": "hello",
                "sender": "user@example.com",
                "body_excerpt": "请帮忙看看这封邮件。",
            },
            dry_run=True,
        ),
        classifier=classifier,
        drafter=drafter,
    )
    assert result.status == AgentRunStatus.AWAITING_APPROVAL.value
    loaded = store.get_by_run_id(result.run_id)
    checkpoint = loaded.checkpoint_json or {}
    assert checkpoint.get("classification", {}).get("category") == "TODO"
    assert checkpoint.get("classification", {}).get("model_full_id") == "mock-classifier"
    assert checkpoint.get("draft", {}).get("blocked") is False
    assert checkpoint.get("draft", {}).get("model_full_id") == "mock-drafter"
    packet = loaded.task_packet_json or {}
    assert packet.get("provider") == "live"


def test_spam_category_skips_drafter_and_blocks(store: AgentRunStore) -> None:
    def spam_classify(_email: dict[str, Any]) -> dict[str, Any]:
        return {"category": "SPAM", "confidence": 0.99, "model_full_id": "stub:spam"}

    calls: list[str] = []

    def tracking_draft(email: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
        calls.append("draft")
        return make_draft_fn()(email, classification)

    result = run_email_to_draft(
        store,
        EmailToDraftInput(
            email={
                "id": "e6",
                "subject": "win money",
                "sender": "promo@example.com",
                "body_excerpt": "click",
            },
            dry_run=True,
        ),
        classify_fn=spam_classify,
        draft_fn=tracking_draft,
    )
    assert result.status == AgentRunStatus.AWAITING_APPROVAL.value
    assert calls == ["draft"]
    loaded = store.get_by_run_id(result.run_id)
    draft = (loaded.checkpoint_json or {}).get("draft") or {}
    assert draft.get("blocked") is True
    assert draft.get("block_reason") == "spam"


def test_make_classify_fn_maps_fields() -> None:
    router = _MockRouter()
    classifier = EmailClassifier(router=router)  # type: ignore[arg-type]
    out = make_classify_fn(classifier=classifier)(
        {"subject": "x", "sender": "a@b.com", "body_excerpt": "hello world"}
    )
    assert out["category"] == "TODO"
    assert out["model_full_id"] == "mock-classifier"


def test_agent_run_record_registered() -> None:
    assert AgentRunRecord.__tablename__ == "agent_runs"
