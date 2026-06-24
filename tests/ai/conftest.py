"""D4.7.3 — ai 测试共享 fixture (in-memory EventStore).

复用 D4.4 policy/conftest.py 范本:
  - in-memory SQLite 跑 EventStore 集成测试(不依赖 SQLCipher/Keychain, 测试快且隔离).
  - 不与 policy/conftest.py 共享 fixture(各 conftest 独立, 避免跨目录 fixture 依赖).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.events import EventStore


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
def store(session_factory: Any) -> EventStore:
    """EventStore 实例(用于 Adapter 事件落地集成测试)."""
    return EventStore(session_factory)


@pytest.fixture
def valid_packet_dict() -> dict[str, Any]:
    """8 必含字段全填的合法 packet dict(测试用 base fixture, 与 policy 对齐)."""
    return {
        "objective": "D4.7.3 草稿适配器验证",
        "scope": ["policy/"],
        "resources": ["mcp:imap"],
        "acceptance_criteria": ["pytest passed", "ruff clean", "mypy 0 errors"],
        "model": "minimax/M3",
        "provider": "minimax",
        "permission_profile": "read_only",
        "recovery_policy": "retry_on_transient",
    }
