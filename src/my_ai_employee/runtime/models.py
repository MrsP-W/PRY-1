"""AgentRun ORM + 状态机白名单。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from my_ai_employee.core.models import Base
from my_ai_employee.events.models import JSONDict

WORKFLOW_EMAIL_TO_DRAFT = "email_to_draft"


class AgentRunStatus(StrEnum):
    """AgentRun 生命周期状态。"""

    PLANNED = "planned"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    CHECKPOINTED = "checkpointed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


ALLOWED_AGENT_RUN_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.PLANNED: frozenset({AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED}),
    AgentRunStatus.RUNNING: frozenset(
        {
            AgentRunStatus.AWAITING_APPROVAL,
            AgentRunStatus.CHECKPOINTED,
            AgentRunStatus.SUCCEEDED,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        }
    ),
    AgentRunStatus.CHECKPOINTED: frozenset(
        {AgentRunStatus.RUNNING, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}
    ),
    AgentRunStatus.AWAITING_APPROVAL: frozenset(
        {AgentRunStatus.SUCCEEDED, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}
    ),
    AgentRunStatus.SUCCEEDED: frozenset(),
    AgentRunStatus.FAILED: frozenset(),
    AgentRunStatus.CANCELLED: frozenset(),
}


class AgentRunRecord(Base):
    """持久化 AgentRun（可恢复检查点 + trace）。"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_agent_runs_run_id"),
        Index("idx_agent_runs_trace", "trace_id"),
        Index("idx_agent_runs_status_updated", "status", text("updated_at_ms DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str] = mapped_column(Text, nullable=False)
    workflow: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=AgentRunStatus.PLANNED.value)
    task_packet_json: Mapped[dict[str, Any]] = mapped_column(JSONDict, nullable=False)
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSONDict, nullable=False, default=dict)
    parent_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)


__all__ = [
    "ALLOWED_AGENT_RUN_TRANSITIONS",
    "AgentRunRecord",
    "AgentRunStatus",
    "WORKFLOW_EMAIL_TO_DRAFT",
]
