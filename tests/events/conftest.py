"""D4.3 — events 测试共享 fixture.

设计: 用 in-memory SQLite 跑 ORM 测试(不依赖 SQLCipher/Keychain, 测试快且隔离).
不与 test_db.py 共享 fixture, 因为 D4.3 events 只需测 ORM/契约层, 不需要真实加密 DB.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.core.outbox import (
    OutboxEntry,  # noqa: F401  触发 SQLAlchemy 注册(outbox 表 D4.8)
)
from my_ai_employee.events import EventStore
from my_ai_employee.events.models import Event  # noqa: F401  触发 SQLAlchemy 注册(events 表)

if TYPE_CHECKING:
    pass


@pytest.fixture
def engine() -> Any:
    """in-memory SQLite engine (无加密, 测试用)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    """返回 sessionmaker."""
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory: Any) -> EventStore:  # type: ignore[no-untyped-def]
    """EventStore 实例."""
    return EventStore(session_factory)
