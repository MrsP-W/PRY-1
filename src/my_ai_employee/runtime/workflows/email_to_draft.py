"""邮件→草稿 AgentRun 工作流（默认可 dry-run，默认不 SMTP）。

默认接真 EmailClassifier / EmailDrafter；测试可注入 classify_fn/draft_fn 覆盖。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from my_ai_employee.events.models import EventStatus, EventType
from my_ai_employee.events.store import EventStore
from my_ai_employee.policy.task_packet import (
    PermissionProfile,
    RecoveryPolicy,
    TaskPacket,
    assert_packet_contract,
)
from my_ai_employee.runtime.models import WORKFLOW_EMAIL_TO_DRAFT, AgentRunStatus
from my_ai_employee.runtime.store import AgentRunStore

ClassifyFn = Callable[[dict[str, Any]], dict[str, Any]]
DraftFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
OutboxInsertFn = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class EmailToDraftInput:
    """工作流输入：一封脱敏邮件 dict。"""

    email: dict[str, Any]
    dry_run: bool = True
    approval_decision: str | None = None  # "approve" | "cancel" | None(停在 awaiting)


@dataclass
class EmailToDraftResult:
    """工作流结果摘要。"""

    run_id: str
    trace_id: str
    status: str
    steps: list[str] = field(default_factory=list)
    email_id: str | None = None
    error_code: str | None = None


def _email_fields(email: dict[str, Any]) -> tuple[str, str, str]:
    subject = str(email.get("subject") or "")
    sender = str(email.get("sender") or email.get("from") or "")
    body = str(email.get("body_excerpt") or email.get("body") or email.get("body_text") or "")
    return subject, sender, body


def stub_classify_fn(email: dict[str, Any]) -> dict[str, Any]:
    """本地 stub 分类（单测 / --stub-ai）。"""
    subject = str(email.get("subject") or "")
    category = "URGENT" if "urgent" in subject.lower() else "TODO"
    return {"category": category, "confidence": 0.9, "model_full_id": "stub:classify"}


def stub_draft_fn(email: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    """本地 stub 草稿（单测 / --stub-ai）。"""
    return {
        "subject": f"Re: {email.get('subject', '')}".strip(),
        "body": f"[draft] category={classification.get('category')}",
        "tone": "FORMAL",
        "model_full_id": "stub:draft",
        "blocked": False,
    }


def make_classify_fn(*, classifier: Any | None = None) -> ClassifyFn:
    """包装 EmailClassifier → ClassifyFn。"""

    def _classify(email: dict[str, Any]) -> dict[str, Any]:
        from my_ai_employee.ai.classifier import EmailClassifier

        inst = classifier if classifier is not None else EmailClassifier()
        subject, sender, body = _email_fields(email)
        result = inst.classify(subject=subject, sender=sender, body_excerpt=body)
        category = result.category
        category_value = category.value if hasattr(category, "value") else str(category)
        return {
            "category": category_value,
            "confidence": float(result.confidence),
            "model_full_id": str(result.model_full_id),
            "latency_ms": int(result.latency_ms),
        }

    return _classify


def make_draft_fn(*, drafter: Any | None = None) -> DraftFn:
    """包装 EmailDrafter → DraftFn；SPAM / system sender 不调 LLM。"""

    def _draft(email: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
        from my_ai_employee.ai.drafter import EmailDrafter, SpamBlockedError
        from my_ai_employee.ai.safety import is_system_sender

        subject, sender, body = _email_fields(email)
        category = str(classification.get("category") or "")

        if category == "SPAM":
            return {
                "subject": "",
                "body": "",
                "tone": "FORMAL",
                "model_full_id": "gate:spam_skip",
                "blocked": True,
                "block_reason": "spam",
            }
        if is_system_sender(sender):
            return {
                "subject": "",
                "body": "",
                "tone": "FORMAL",
                "model_full_id": "gate:system_sender_skip",
                "blocked": True,
                "block_reason": "system_sender",
            }

        inst = drafter if drafter is not None else EmailDrafter()
        try:
            result = inst.draft(
                subject=subject,
                sender=sender,
                body_excerpt=body,
                email_category=category or None,
            )
        except SpamBlockedError:
            return {
                "subject": "",
                "body": "",
                "tone": "FORMAL",
                "model_full_id": "gate:spam_blocked",
                "blocked": True,
                "block_reason": "spam_blocked",
            }

        tone = result.tone
        tone_value = tone.value if hasattr(tone, "value") else str(tone)
        return {
            "subject": str(result.subject),
            "body": str(result.body),
            "tone": tone_value,
            "model_full_id": str(result.model_full_id),
            "latency_ms": int(result.latency_ms),
            "blocked": False,
        }

    return _draft


def _emit(
    event_store: EventStore | None,
    *,
    event: EventType,
    status: EventStatus,
    trace_id: str,
    run_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if event_store is None:
        return
    payload = {"trace_id": trace_id, "run_id": run_id}
    if extra:
        payload.update(extra)
    event_store.insert(
        event=event,
        status=status,
        source="agent_runtime",
        subject_id=run_id[:64],
        session_id=trace_id,
        extra=payload,
        provenance="test",
    )


def run_email_to_draft(
    store: AgentRunStore,
    payload: EmailToDraftInput,
    *,
    event_store: EventStore | None = None,
    classify_fn: ClassifyFn | None = None,
    draft_fn: DraftFn | None = None,
    classifier: Any | None = None,
    drafter: Any | None = None,
    outbox_insert_fn: OutboxInsertFn | None = None,
    existing_run_id: str | None = None,
) -> EmailToDraftResult:
    """执行或恢复邮件→草稿闭环。

    默认接真 EmailClassifier / EmailDrafter；传入 classify_fn/draft_fn 可覆盖。
    dry_run=True：不写 Outbox，仍走到 awaiting_approval（演示审批门）。
    approval_decision：若提供则 finalize；否则停在 awaiting_approval。
    """
    classify = classify_fn if classify_fn is not None else make_classify_fn(classifier=classifier)
    draft = draft_fn if draft_fn is not None else make_draft_fn(drafter=drafter)
    using_live_ai = classify_fn is None and draft_fn is None
    steps: list[str] = []

    if existing_run_id:
        record = store.get_by_run_id(existing_run_id)
        run_id = record.run_id
        trace_id = record.trace_id
        checkpoint = dict(record.checkpoint_json or {})
        if record.status == AgentRunStatus.AWAITING_APPROVAL.value:
            if payload.approval_decision is None:
                return EmailToDraftResult(
                    run_id=run_id,
                    trace_id=trace_id,
                    status=AgentRunStatus.AWAITING_APPROVAL.value,
                    steps=list(checkpoint.get("completed_steps") or []),
                    email_id=(
                        str(checkpoint["email_id"])
                        if checkpoint.get("email_id") is not None
                        else None
                    ),
                )
            return _finalize_approval(
                store,
                event_store,
                run_id=run_id,
                trace_id=trace_id,
                decision=payload.approval_decision,
                steps=list(checkpoint.get("completed_steps") or []),
                email_id=(
                    str(checkpoint["email_id"]) if checkpoint.get("email_id") is not None else None
                ),
            )
        if record.status in {
            AgentRunStatus.SUCCEEDED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        }:
            return EmailToDraftResult(
                run_id=run_id,
                trace_id=trace_id,
                status=record.status,
                steps=list(checkpoint.get("completed_steps") or []),
                email_id=(
                    str(checkpoint["email_id"]) if checkpoint.get("email_id") is not None else None
                ),
            )
        if record.status in {
            AgentRunStatus.PLANNED.value,
            AgentRunStatus.CHECKPOINTED.value,
        }:
            store.transition(run_id, AgentRunStatus.RUNNING)
        elif record.status != AgentRunStatus.RUNNING.value:
            raise RuntimeError(f"无法从状态 {record.status} resume")
    else:
        packet = TaskPacket(
            objective="email_to_draft",
            scope=["email", "outbox"],
            resources=["classifier", "drafter", "approval_gate"],
            acceptance_criteria=["draft_ready_for_approval", "no_smtp_unless_authorized"],
            model="router" if using_live_ai else "local-stub",
            provider="live" if using_live_ai else "stub",
            permission_profile=PermissionProfile.READ_ONLY.value,
            recovery_policy=RecoveryPolicy.RETRY_ON_TRANSIENT.value,
        )
        assert_packet_contract(packet)
        record = store.create(workflow=WORKFLOW_EMAIL_TO_DRAFT, task_packet=packet)
        run_id = record.run_id
        trace_id = record.trace_id
        checkpoint = {}
        store.transition(run_id, AgentRunStatus.RUNNING)
        _emit(
            event_store,
            event=EventType.AGENT_RUN_STARTED,
            status=EventStatus.STARTED,
            trace_id=trace_id,
            run_id=run_id,
        )

    tool_sequence: list[str] = list(checkpoint.get("tool_sequence") or [])
    completed = list(checkpoint.get("completed_steps") or [])

    try:
        # plan
        if "plan" not in completed:
            steps.append("plan")
            completed.append("plan")
            tool_sequence.append("plan")
            _emit(
                event_store,
                event=EventType.AGENT_RUN_STEP,
                status=EventStatus.SUCCEEDED,
                trace_id=trace_id,
                run_id=run_id,
                extra={"step": "plan", "tool_sequence": list(tool_sequence)},
            )

        # classify
        classification: dict[str, Any]
        if "classify" not in completed:
            classification = classify(payload.email)
            steps.append("classify")
            completed.append("classify")
            tool_sequence.append("classify")
            store.save_checkpoint(
                run_id,
                {
                    "completed_steps": completed,
                    "tool_sequence": tool_sequence,
                    "classification": {
                        "category": classification.get("category"),
                        "confidence": classification.get("confidence"),
                        "model_full_id": classification.get("model_full_id"),
                    },
                },
            )
            _emit(
                event_store,
                event=EventType.AGENT_RUN_STEP,
                status=EventStatus.SUCCEEDED,
                trace_id=trace_id,
                run_id=run_id,
                extra={
                    "step": "classify",
                    "tool_sequence": list(tool_sequence),
                    "model_full_id": classification.get("model_full_id"),
                },
            )
        else:
            classification = dict(checkpoint.get("classification") or {"category": "TODO"})

        # draft + optional outbox
        email_id = checkpoint.get("email_id")
        if "draft" not in completed:
            draft_payload = draft(payload.email, classification)
            steps.append("draft")
            completed.append("draft")
            tool_sequence.append("draft")
            blocked = bool(draft_payload.get("blocked"))
            if not payload.dry_run and not blocked:
                if email_id is None:
                    if outbox_insert_fn is None:
                        email_id = str(
                            payload.email.get("id") or payload.email.get("uid") or "stub"
                        )
                    else:
                        email_id = outbox_insert_fn(
                            {
                                "email": payload.email,
                                "draft": draft_payload,
                                "classification": classification,
                            }
                        )
            else:
                email_id = email_id or str(payload.email.get("id") or "dry-run")
            store.save_checkpoint(
                run_id,
                {
                    "completed_steps": completed,
                    "tool_sequence": tool_sequence,
                    "email_id": email_id,
                    "last_tool": "draft",
                    "draft": {
                        "subject": draft_payload.get("subject"),
                        "tone": draft_payload.get("tone"),
                        "model_full_id": draft_payload.get("model_full_id"),
                        "blocked": blocked,
                        "block_reason": draft_payload.get("block_reason"),
                    },
                },
            )
            _emit(
                event_store,
                event=EventType.AGENT_RUN_STEP,
                status=EventStatus.SUCCEEDED,
                trace_id=trace_id,
                run_id=run_id,
                extra={
                    "step": "draft",
                    "tool_sequence": list(tool_sequence),
                    "email_id": email_id,
                    "blocked": blocked,
                    "model_full_id": draft_payload.get("model_full_id"),
                },
            )
        else:
            email_id = checkpoint.get("email_id")

        # await_approval
        steps.append("await_approval")
        if "await_approval" not in completed:
            completed.append("await_approval")
        store.transition(
            run_id,
            AgentRunStatus.AWAITING_APPROVAL,
            checkpoint_update={
                "completed_steps": completed,
                "tool_sequence": tool_sequence,
                "email_id": email_id,
            },
        )
        _emit(
            event_store,
            event=EventType.AGENT_RUN_AWAITING_APPROVAL,
            status=EventStatus.BLOCKED,
            trace_id=trace_id,
            run_id=run_id,
            extra={"step": "await_approval", "email_id": email_id},
        )

        if payload.approval_decision is None:
            return EmailToDraftResult(
                run_id=run_id,
                trace_id=trace_id,
                status=AgentRunStatus.AWAITING_APPROVAL.value,
                steps=steps or completed,
                email_id=str(email_id) if email_id is not None else None,
            )

        return _finalize_approval(
            store,
            event_store,
            run_id=run_id,
            trace_id=trace_id,
            decision=payload.approval_decision,
            steps=steps or completed,
            email_id=str(email_id) if email_id is not None else None,
        )
    except Exception as exc:
        error_code = type(exc).__name__
        store.transition(
            run_id,
            AgentRunStatus.CHECKPOINTED,
            checkpoint_update={
                "completed_steps": completed,
                "tool_sequence": tool_sequence,
                "error_code": error_code,
                "last_tool": tool_sequence[-1] if tool_sequence else None,
            },
        )
        _emit(
            event_store,
            event=EventType.AGENT_RUN_CHECKPOINT,
            status=EventStatus.DEGRADED,
            trace_id=trace_id,
            run_id=run_id,
            extra={"error_code": error_code, "tool_sequence": list(tool_sequence)},
        )
        return EmailToDraftResult(
            run_id=run_id,
            trace_id=trace_id,
            status=AgentRunStatus.CHECKPOINTED.value,
            steps=steps or completed,
            email_id=str(checkpoint.get("email_id")) if checkpoint.get("email_id") else None,
            error_code=error_code,
        )


def _finalize_approval(
    store: AgentRunStore,
    event_store: EventStore | None,
    *,
    run_id: str,
    trace_id: str,
    decision: str | None,
    steps: list[str],
    email_id: str | None,
) -> EmailToDraftResult:
    if decision == "cancel":
        store.transition(
            run_id,
            AgentRunStatus.CANCELLED,
            checkpoint_update={"approval_decision": "cancel"},
        )
        _emit(
            event_store,
            event=EventType.AGENT_RUN_FAILED,
            status=EventStatus.CANCELLED,
            trace_id=trace_id,
            run_id=run_id,
            extra={"approval_decision": "cancel", "error_code": "approval_cancelled"},
        )
        return EmailToDraftResult(
            run_id=run_id,
            trace_id=trace_id,
            status=AgentRunStatus.CANCELLED.value,
            steps=[*steps, "finalize"],
            email_id=email_id,
            error_code="approval_cancelled",
        )
    if decision != "approve":
        raise ValueError(f"approval_decision 必须是 approve/cancel/None, 实际 {decision!r}")
    store.transition(
        run_id,
        AgentRunStatus.SUCCEEDED,
        checkpoint_update={"approval_decision": "approve", "completed_steps": [*steps, "finalize"]},
    )
    _emit(
        event_store,
        event=EventType.AGENT_RUN_SUCCEEDED,
        status=EventStatus.SUCCEEDED,
        trace_id=trace_id,
        run_id=run_id,
        extra={"approval_decision": "approve", "email_id": email_id},
    )
    return EmailToDraftResult(
        run_id=run_id,
        trace_id=trace_id,
        status=AgentRunStatus.SUCCEEDED.value,
        steps=[*steps, "finalize"],
        email_id=email_id,
    )


__all__ = [
    "EmailToDraftInput",
    "EmailToDraftResult",
    "make_classify_fn",
    "make_draft_fn",
    "run_email_to_draft",
    "stub_classify_fn",
    "stub_draft_fn",
]
