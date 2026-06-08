"""D4.3 — EventStore: events 表读写封装.

设计:
  - insert(): 走 g004 4 不变量 (typed event + status + 6 必含 metadata + fingerprint 去重)
  - by_session / by_subject / by_event_type / by_status: 4 类热路径查询
  - dedupe_by_fingerprint: UNIQUE 冲突处理(D3.3.3 教训 — 窄化到 IntegrityError, 不静默吞)
  - 不接业务层 (D4.4+ LLM/MCP/分类/草稿才用), D4.3 是契约层

参考 D3.3.3 教训:
  - except 范围窄化: 只接 sqlalchemy.exc.IntegrityError, 不接 SQLAlchemyError 基类
  - 失败状态透明化: dedupe 命中是正常业务, 用 upsert 模式(返回已有 Event)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from my_ai_employee.events.contract import (
    assert_event_invariants,
    build_event_metadata,
    compute_fingerprint,
)
from my_ai_employee.events.exceptions import EventFingerprintConflictError
from my_ai_employee.events.models import (
    Event,
    EventOwnership,
    EventProvenance,
    EventStatus,
    EventType,
)


class EventStore:
    """events 表读写封装.

    Usage:
        store = EventStore(session_factory)
        event = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id="req-123",
            seq=1,
            session_id="sess-abc",
        )
        assert event.id is not None
        assert event.fingerprint != ""  # 已被 compute_fingerprint 写回
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # ===== insert =====

    def insert(
        self,
        event: str | EventType,
        status: str | EventStatus,
        source: str,
        subject_id: str | None = None,
        seq: int = 0,
        session_id: str = "",
        ownership: EventOwnership | str = EventOwnership.OBSERVE,
        provenance: EventProvenance | str = EventProvenance.LIVE,
        extra: dict[str, Any] | None = None,
        timestamp_ms: int | None = None,
        on_conflict: str = "ignore",
    ) -> Event:
        """插入一条事件.

        Args:
            event: 事件类型(enum 或字符串)
            status: 事件状态(enum 或字符串)
            source: 事件源头
            subject_id: 关联实体 ID(可空)
            seq: 单调递增序号
            session_id: 会话身份(空 = 全局)
            ownership: 事件所有权
            provenance: 事件来源
            extra: 业务扩展字段
            timestamp_ms: Unix epoch ms(默认 = 当前时间)
            on_conflict: UNIQUE 冲突处理:
                - "ignore" (默认): 静默去重, 返回已存在 Event
                - "raise": 抛 EventFingerprintConflictError

        Returns:
            新插入的 Event(冲突时返回已存在 Event)

        Raises:
            EventContractError: event/status 非法
            EventMetadataError: metadata 缺字段
            EventFingerprintConflictError: on_conflict="raise" 时 UNIQUE 冲突
            ValueError / TypeError: 编程错误(透传)
        """
        # 1. 构造 metadata (6 必含字段)
        metadata = build_event_metadata(
            seq=seq,
            session_id=session_id,
            ownership=ownership,
            provenance=provenance,
            extra=extra,
            timestamp_ms=timestamp_ms,
        )
        # 2. 校验不变量(失败抛 EventContractError / EventMetadataError)
        assert_event_invariants(event=event, status=status, metadata=metadata)
        # 3. 字符串归一(便于后续计算 fingerprint)
        from my_ai_employee.events.contract import _normalize_enum

        event_value = _normalize_enum(event, EventType, "event")
        status_value = _normalize_enum(status, EventStatus, "status")
        # 4. 计算 fingerprint 并写回 metadata
        fingerprint = compute_fingerprint(
            event=event_value,
            status=status_value,
            source=source,
            subject_id=subject_id,
            metadata=metadata,
        )
        metadata["fingerprint"] = fingerprint
        # 5. created_at 取 metadata.timestamp_ms(冗余但便于排序)
        created_at = metadata["timestamp_ms"]
        # 6. 插入 (D3.3.3 教训: 窄 except, 只接 IntegrityError)
        with self._session_factory() as session:
            try:
                row = Event(
                    event=event_value,
                    status=status_value,
                    source=source,
                    subject_id=subject_id,
                    fingerprint=fingerprint,
                    event_metadata=metadata,  # 列名 event_metadata(SA 保留属性规避)
                    created_at=created_at,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return row
            except IntegrityError as err:
                session.rollback()
                if on_conflict == "raise":
                    raise EventFingerprintConflictError(
                        f"UNIQUE 冲突: fingerprint={fingerprint[:16]}... "
                        f"(event={event_value!r} status={status_value!r} "
                        f"source={source!r} subject_id={subject_id!r})"
                    ) from err
                # ignore 模式: 查询已存在 Event
                existing = self.get_by_fingerprint(fingerprint)
                if existing is not None:
                    return existing
                # 极小概率: UNIQUE 冲突但查不到(并发删除?) — 重抛
                raise

    # ===== 查询方法 (热路径) =====

    def get_by_id(self, event_id: int) -> Event | None:
        """按 id 查单条."""
        with self._session_factory() as session:
            return session.get(Event, event_id)

    def get_by_fingerprint(self, fingerprint: str) -> Event | None:
        """按 fingerprint 查单条(应用层引用, 跨表查找)."""
        with self._session_factory() as session:
            stmt = select(Event).where(Event.fingerprint == fingerprint)
            return session.execute(stmt).scalar_one_or_none()

    def by_session(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[Event]:
        """按 session_id 查事件(同会话事件流).

        实现: Python 端 filter (避免 SQLite JSON 路径查询方言差异).
        session_id 存在 event_metadata["session_id"] 字段内.
        """
        with self._session_factory() as session:
            stmt = select(Event).order_by(Event.created_at.desc())
            rows = list(session.execute(stmt).scalars().all())
        # Python 端 filter + 截断 (limit 在 Python 端生效)
        matched = [r for r in rows if r.event_metadata.get("session_id") == session_id]
        return matched[:limit]

    def by_subject(
        self,
        subject_id: str,
        limit: int = 100,
    ) -> list[Event]:
        """按 subject_id 查事件(同一实体的事件流, e.g. 同一邮件的 LLM 调用 + 分类 + 草稿)."""
        with self._session_factory() as session:
            stmt = (
                select(Event)
                .where(Event.subject_id == subject_id)
                .order_by(Event.created_at.desc())
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def by_event_type(
        self,
        event_type: str | EventType,
        limit: int = 100,
    ) -> list[Event]:
        """按事件类型查(同类型事件流, e.g. 所有 LLM_CALL_FAILED)."""
        event_value = event_type.value if isinstance(event_type, EventType) else event_type
        with self._session_factory() as session:
            stmt = (
                select(Event)
                .where(Event.event == event_value)
                .order_by(Event.created_at.desc())
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def by_status(
        self,
        status: str | EventStatus,
        limit: int = 100,
    ) -> list[Event]:
        """按状态查(负向证据查询, e.g. 所有 FAILED 事件)."""
        status_value = status.value if isinstance(status, EventStatus) else status
        with self._session_factory() as session:
            stmt = (
                select(Event)
                .where(Event.status == status_value)
                .order_by(Event.created_at.desc())
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def count(self) -> int:
        """总数(测试用)."""
        from sqlalchemy import func

        with self._session_factory() as session:
            stmt = select(func.count()).select_from(Event)
            return int(session.execute(stmt).scalar_one())


# ===== 模块导出 =====


__all__ = ["EventStore"]
