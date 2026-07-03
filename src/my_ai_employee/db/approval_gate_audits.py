"""ApprovalGateAuditStoreImpl — approval_gate_audits 表读写封装.

沿 db/outbox.py 范本 + menu_bar/approval_gate_audit.py Protocol 契约。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from my_ai_employee.core.models import ApprovalGateAudit
from my_ai_employee.menu_bar.approval_gate_audit import (
    MAX_LIST_RECENT,
    AuditRecord,
    AuditRecordResult,
)

_AUDIT_ID_PREFIX = "audit:"


def _row_to_dict(row: ApprovalGateAudit) -> dict[str, Any]:
    return {
        "action": row.action,
        "target_id": row.target_id,
        "actor": row.actor,
        "reason": row.reason,
        "write_executed": bool(row.write_executed),
        "affected_id": row.affected_id,
        "error": row.error,
        "executed_at_ms": row.executed_at_ms,
        "decision": None,
    }


class ApprovalGateAuditStoreImpl:
    """真实 SQL 落档 — DASHBOARD_REAL_DB=1 opt-in."""

    def __init__(self, session_factory: sessionmaker[Session] | Any) -> None:
        self._session_factory = session_factory

    def is_enabled(self) -> bool:
        return True

    def record(self, record: AuditRecord) -> AuditRecordResult:
        try:
            with self._session_factory() as session:
                row = ApprovalGateAudit(
                    action=record.action,
                    target_id=record.target_id,
                    actor=record.actor,
                    reason=record.reason,
                    write_executed=1 if record.write_executed else 0,
                    affected_id=record.affected_id,
                    error=record.error,
                    executed_at_ms=record.executed_at_ms,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return AuditRecordResult(
                    success=True,
                    audit_id=f"{_AUDIT_ID_PREFIX}{row.id}",
                    executed_at_ms=record.executed_at_ms,
                    error=None,
                    reason=None,
                )
        except Exception:  # noqa: BLE001 — audit 落档失败不阻塞业务
            return AuditRecordResult(
                success=False,
                audit_id=None,
                executed_at_ms=None,
                error="store_failed",
                reason="ApprovalGateAuditStoreImpl record 失败",
            )

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or limit < 1 or limit > MAX_LIST_RECENT:
            limit = 10
        try:
            with self._session_factory() as session:
                rows = session.scalars(
                    select(ApprovalGateAudit)
                    .order_by(ApprovalGateAudit.executed_at_ms.desc())
                    .limit(limit)
                ).all()
                return [_row_to_dict(row) for row in rows]
        except Exception:  # noqa: BLE001
            return []


__all__ = ["ApprovalGateAuditStoreImpl"]
