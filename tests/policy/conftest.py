"""D4.4 — policy 测试共享 fixture.

设计:
  - 用 in-memory SQLite 跑 EventStore 集成测试(不依赖 SQLCipher/Keychain, 测试快且隔离).
  - 复用 events conftest 模式, 但每个 policy 测试文件仍可独立 import(conftest 自动发现).
  - 不与 test_db.py 共享 fixture, 因为 D4.4 policy 只需测自身 + EventStore 集成层.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.events import EventStore


@pytest.fixture
def engine():
    """in-memory SQLite engine (无加密, 测试用)."""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    """返回 sessionmaker."""
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory) -> EventStore:
    """EventStore 实例(用于 PolicyEngine 事件落地集成测试)."""
    return EventStore(session_factory)


@pytest.fixture
def valid_packet_dict() -> dict[str, Any]:
    """8 必含字段全填的合法 packet dict(测试用 base fixture)."""
    return {
        "objective": "D4.4 任务策略板验证",
        "scope": ["policy/"],
        "resources": ["mcp:imap"],
        "acceptance_criteria": ["pytest passed", "ruff clean", "mypy 0 errors"],
        "model": "minimax/M3",
        "provider": "minimax",
        "permission_profile": "read_write",
        "recovery_policy": "retry_on_transient",
    }
