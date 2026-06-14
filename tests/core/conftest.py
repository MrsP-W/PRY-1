"""D6.2 + D6.4 — core 测试共享 fixture(transactions 表 16 列,InMemory SQLite).

承接 D6.2 dedup.py 3 层去重模型测试基础设施 + D6.4 transactions ORM 16 列升级:

    - InMemory SQLite + 临时建 transactions 表(D6.4 完整 16 列)
    - D6.4 dedup.py ORM 替换 text() 后,需要完整 16 列 schema 才能查得
    - 复用 tests/policy/conftest.py 范本(Base.metadata.create_all)

D6.4 升级:
    - 从 6 列简化版 → 16 列完整版(沿 db/transactions.py Transaction ORM)
    - D6.2 三个 dedup 测试(check_l1_duplicate + find_l2_candidates + mark_l3_needs_confirm)
      仍用此 fixture(完整 16 列 schema 兼容 6 列查询)
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def engine() -> Iterator:
    """InMemory SQLite + 临时建 transactions 完整 16 列表(D6.4 升级).

    用 SQLAlchemy create_all + Transaction model(沿 db/transactions.py)创建,
    无需手写 DDL,Base.metadata 自动同步 ORM → DDL。
    """
    eng = create_engine("sqlite:///:memory:")
    # 显式 import 触发 SQLAlchemy 注册到 Base.metadata
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.transactions import Transaction  # noqa: F401  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    """返回 sessionmaker(沿 policy/conftest 范本)."""
    return sessionmaker(bind=engine)


@pytest.fixture
def session(session_factory) -> Iterator[Session]:
    """单 session fixture(测试完 rollback,隔离各 test)."""
    s = session_factory()
    try:
        yield s
    finally:
        s.close()
