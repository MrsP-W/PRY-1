"""AgentRunStore — 创建 / 加载 / 检查点 / 状态迁移。"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from my_ai_employee.policy.task_packet import TaskPacket, assert_packet_contract
from my_ai_employee.runtime.models import (
    ALLOWED_AGENT_RUN_TRANSITIONS,
    AgentRunRecord,
    AgentRunStatus,
)


class AgentRunIllegalTransitionError(RuntimeError):
    """非法状态迁移。"""


class AgentRunNotFoundError(LookupError):
    """run_id 不存在。"""


class AgentRunStore:
    """agent_runs 表读写。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        workflow: str,
        task_packet: TaskPacket,
        trace_id: str | None = None,
        parent_event_id: int | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> AgentRunRecord:
        assert_packet_contract(task_packet)
        now = int(time.time() * 1000)
        record = AgentRunRecord(
            run_id=str(uuid.uuid4()),
            trace_id=trace_id or str(uuid.uuid4()),
            workflow=workflow,
            status=AgentRunStatus.PLANNED.value,
            task_packet_json=task_packet.to_dict(),
            checkpoint_json=dict(checkpoint or {}),
            parent_event_id=parent_event_id,
            created_at_ms=now,
            updated_at_ms=now,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            session.expunge(record)
            return record

    def get_by_run_id(self, run_id: str) -> AgentRunRecord:
        with self._session_factory() as session:
            row = session.scalar(select(AgentRunRecord).where(AgentRunRecord.run_id == run_id))
            if row is None:
                raise AgentRunNotFoundError(run_id)
            session.expunge(row)
            return row

    def transition(
        self,
        run_id: str,
        to_status: AgentRunStatus | str,
        *,
        checkpoint_update: dict[str, Any] | None = None,
    ) -> AgentRunRecord:
        target = (
            to_status if isinstance(to_status, AgentRunStatus) else AgentRunStatus(str(to_status))
        )
        with self._session_factory() as session:
            row = session.scalar(select(AgentRunRecord).where(AgentRunRecord.run_id == run_id))
            if row is None:
                raise AgentRunNotFoundError(run_id)
            current = AgentRunStatus(row.status)
            allowed = ALLOWED_AGENT_RUN_TRANSITIONS.get(current, frozenset())
            if target not in allowed:
                raise AgentRunIllegalTransitionError(f"{current.value} → {target.value} 不在白名单")
            row.status = target.value
            if checkpoint_update:
                merged = dict(row.checkpoint_json or {})
                merged.update(checkpoint_update)
                row.checkpoint_json = merged
            row.updated_at_ms = int(time.time() * 1000)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    def save_checkpoint(self, run_id: str, checkpoint_update: dict[str, Any]) -> AgentRunRecord:
        with self._session_factory() as session:
            row = session.scalar(select(AgentRunRecord).where(AgentRunRecord.run_id == run_id))
            if row is None:
                raise AgentRunNotFoundError(run_id)
            merged = dict(row.checkpoint_json or {})
            merged.update(checkpoint_update)
            row.checkpoint_json = merged
            row.updated_at_ms = int(time.time() * 1000)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row


__all__ = [
    "AgentRunIllegalTransitionError",
    "AgentRunNotFoundError",
    "AgentRunStore",
]
