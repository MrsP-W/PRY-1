"""v0.2.2 #7 — db 测试共享 fixture.

**根因**(`reports/v0.2.2-p7-fk-circular-2026-06-18.md`):

    - 沿用 [[tests/events/conftest.py]] 范本,显式 import ORM Model
      触发 SQLAlchemy Base.metadata 注册
    - 修复 `pytest tests/db/` 跑时 `outbox.reviewer_decision_event_id` FK
      找不到 `events` 表(`NoReferencedTableError`)
    - 子目录 conftest 不存在 → 各 test 文件 `engine` fixture 自 import Base
      + 自身 model,**漏 import `OutboxEntry` / `Event`** → outbox/events
      表未注册到 `Base.metadata` → create_all 时 FK 校验失败

**范本**(沿 [[tests/events/conftest.py]] 16-20):

    - 显式 import `OutboxEntry` (outbox 表) + `Event` (events 表) + `Note`
    - 显式 import `RecipientBlacklist` / `MerchantProfile` / `Transaction`
      (子目录全部 db test 涉及的 ORM)
    - 全部 `noqa: F401` 标记(lint 不报"unused import")

**目标**:

    - `pytest tests/db/` 子目录跑 0 errors(从 57 errors 降至 0)
    - 不影响 `pytest tests/` 主测试套 2176 passed / 1 skipped / 89.28% 覆盖
    - 沿 [[d5.6.3-p1-1-5-changes]] 范本不破坏现有契约

**沿用范本**:[[d5.6.3-p1-1-5-changes]] / [[d5.7.2-docs-only-closure]] /
[[v0.2.1-candidates-2026-06-17]] / [[b-class-deferral-2026-06-09]]
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 让 tests/ 目录能 import 兄弟包(沿 tests/db/test_*.py 范本)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 显式 import 触发 SQLAlchemy Base.metadata 注册
# E402 是必须的(因 sys.path.insert 必须在 import 前);F401 是必须的(只 import 不引用)
from my_ai_employee.core.models import Base  # noqa: E402, F401
from my_ai_employee.core.outbox import (  # noqa: E402, F401
    OutboxEntry,  # 触发 outbox 表注册
)
from my_ai_employee.db.blacklist import RecipientBlacklist  # noqa: E402, F401
from my_ai_employee.db.merchant_profile import MerchantProfile  # noqa: E402, F401
from my_ai_employee.db.notes import Note  # noqa: E402, F401
from my_ai_employee.db.transactions import Transaction  # noqa: E402, F401
from my_ai_employee.events import EventStore  # noqa: E402, F401
from my_ai_employee.events.models import Event  # noqa: E402, F401  触发 events 表注册


@pytest.fixture
def engine() -> Iterator[Any]:
    """InMemory SQLite + 全部 Model create_all(沿 tests/events/conftest.py 范本).

    **修复 v0.2.2 #7**:
        - 显式 import `OutboxEntry` + `Event` + `Note` + `RecipientBlacklist` +
          `MerchantProfile` + `Transaction`(子目录全部 db test 涉及 ORM)
        - `Base.metadata.create_all(eng)` 创建所有表,outbox.events FK 解析成功
    """
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    """返回 sessionmaker[Any](沿 tests/events/conftest.py:36 范本)."""
    return sessionmaker[Any](bind=engine)
