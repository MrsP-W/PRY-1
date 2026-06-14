"""D6.2 — core 测试共享 fixture(transactions 表临时建表,InMemory SQLite).

承接 D6.2 dedup.py 3 层去重模型测试基础设施:

    - InMemory SQLite + 临时建 transactions 表(只含 dedup 需要的 6 列,简化版)
    - 复用 tests/policy/conftest.py 范本(Base.metadata.create_all)
    - D6.4 替换为完整 ORM 即可(本 conftest 仅 D6.2 阶段使用)

设计决策:
    - transactions 表简化版(只含 dedup 必需的 6 列):
        id / source / external_transaction_id / amount / counterparty / normalized_fingerprint
    - 不含 needs_confirm / candidate_match_id / status / etc.(D6.4 才完整)
    - D6.4 migrations 0007 落地后,本 conftest 可删除,统一走 test_transactions.py
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import (
    create_engine,
    text,
)
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def engine() -> Iterator:
    """InMemory SQLite + 临时建 transactions 简化表(D6.2 阶段)."""
    eng = create_engine("sqlite:///:memory:")

    # 用 DDL 临时建表(简化版,只含 dedup 必需 6 列)
    ddl = text(
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_transaction_id TEXT NOT NULL,
            amount NUMERIC(10, 2) NOT NULL,
            counterparty TEXT NOT NULL,
            normalized_fingerprint TEXT NOT NULL,
            UNIQUE(source, external_transaction_id)
        )
        """
    )
    with eng.begin() as conn:
        conn.execute(ddl)
        # L2 软标记用 INDEX(非 UNIQUE)
        conn.execute(
            text(
                "CREATE INDEX idx_transactions_fingerprint ON transactions(normalized_fingerprint)"
            )
        )
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
