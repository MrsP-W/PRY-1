"""D6.4 — 0007_transactions alembic 迁移测试(5 cases).

承接 D3.2.3 真实 alembic 迁移测试范本(沿用 tmp_db_path + fake_keychain +
alembic_cfg + patched_database_open fixtures)。

5 段测试覆盖:
    1. upgrade 跑通后 transactions 表存在 + 16 列 + 1 UNIQUE 约束
    2. downgrade -1 跑通后 transactions 表被 drop(outbox/events 等其他表仍在)
    3. upgrade + downgrade + upgrade 三步可幂等执行
    4. UNIQUE(source, external_transaction_id) 约束在 sqlite_master 中可见
    5. 2 索引(idx_transactions_fingerprint + idx_transactions_status_imported DESC)存在

D3.2 8 雷区严判:
    - NUMERIC(10, 2) 非 Float(防精度漂移)
    - BOOLEAN 走 Integer + server_default="0"
    - DATE 走 Date(非 DateTime)
    - AUTOINCREMENT(非 AUTO_INCREMENT)
    - 下划线命名(0007_transactions.py)
    - DESC 索引用 sa.text("imported_at_ms DESC")
    - render_as_batch=True(env.py)
    - downgrade 干净回滚

D7 兼容 5 扩展点(沿 plan §7):
    - source TEXT NOT NULL(str 通用,无硬编码 'wechat')
    - candidate_match_id + needs_confirm schema 必含
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402

# ===== Fixtures(沿用 tests/core/test_migrations.py 范本)=====


@pytest.fixture
def fake_keychain(monkeypatch):
    """in-memory Keychain 模拟。"""
    store: dict[tuple[str, str], str] = {}

    def fake_get() -> keychain.KeychainResult:
        key = (keychain.SERVICE_DB, "data.db")
        if key in store:
            return keychain.KeychainResult(ok=True, value=store[key])
        return keychain.KeychainResult(ok=False, error="not found")

    def fake_set(password: str) -> keychain.KeychainResult:
        store[(keychain.SERVICE_DB, "data.db")] = password
        return keychain.KeychainResult(ok=True)

    monkeypatch.setattr(keychain, "get_db_password", fake_get)
    monkeypatch.setattr(keychain, "set_db_password", fake_set)
    return store


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """测试用临时 DB 路径。"""
    return tmp_path / "transactions_migration_test.db"


@pytest.fixture
def alembic_cfg(tmp_db_path: Path, fake_keychain: dict) -> AlembicConfig:
    """配 alembic 走项目根的 alembic.ini,env.py 自动捡到我们的 fake_keychain。"""
    return AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))


@pytest.fixture
def patched_database_open(tmp_db_path: Path, monkeypatch):
    """monkeypatch Database.open() 用 tmp 路径。"""
    import my_ai_employee.core.db as db_module

    original_open = db_module.Database.open

    def patched_open(db_path=None):  # type: ignore[no-untyped-def]
        return original_open(db_path=tmp_db_path)

    monkeypatch.setattr(db_module.Database, "open", staticmethod(patched_open))
    return tmp_db_path


# ===== 5 cases =====


def test_alembic_upgrade_creates_transactions_table_with_16_columns(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """Case 1 — alembic upgrade head 跑通后 transactions 表存在 + 16 列 + 1 UNIQUE 约束。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            # 1) transactions 表存在
            tables = [
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
            assert "transactions" in tables

            # 2) 16 列全在(D6.4 锁定)
            cols = [
                row[1]
                for row in conn.exec_driver_sql("PRAGMA table_info('transactions')").fetchall()
            ]
            expected_cols = {
                "id",
                "source",
                "external_transaction_id",
                "transaction_date",
                "amount",
                "counterparty",
                "category",
                "payment_method",
                "normalized_fingerprint",
                "needs_confirm",
                "candidate_match_id",
                "status",
                "imported_at_ms",
                "confirmed_at_ms",
                "raw_row_json",
                "notes",
            }
            assert set(cols) == expected_cols, f"差集: {expected_cols - set(cols)}"

            # 3) 1 UNIQUE 约束(用 PRAGMA index_list 查 UNIQUE 索引,SQLite 自动建唯一索引)
            idx_list = conn.exec_driver_sql("PRAGMA index_list('transactions')").fetchall()
            unique_idxs = [row for row in idx_list if row[2] == 1]  # row[2]=unique flag
            assert len(unique_idxs) == 1, f"应有 1 UNIQUE 约束,实际 {len(unique_idxs)}"
            uq_name = unique_idxs[0][1]
            # 验证 UNIQUE 索引含 source + external_transaction_id 两列
            uq_cols = conn.exec_driver_sql(f"PRAGMA index_info('{uq_name}')").fetchall()
            uq_col_names = {row[2] for row in uq_cols}
            assert uq_col_names == {"source", "external_transaction_id"}
    finally:
        db.close()


def test_alembic_downgrade_drops_transactions_table(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """Case 2 — alembic downgrade 显式回到 0006 后 transactions 表被 drop(outbox / events / notes 等其他表仍在)。"""
    from alembic import command

    # 先 upgrade head(确保 transactions + notes 表存在)
    command.upgrade(alembic_cfg, "head")
    # 显式 downgrade 到 0006(0007_transactions 之前)— 删 transactions 表
    # 0008_notes 创建 notes 表 + 0007_transactions 创建 transactions 表,要走 2 步
    command.downgrade(alembic_cfg, "0006_outbox_approval_provenance")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            tables = [
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
            # transactions 表已删
            assert "transactions" not in tables
            # notes 表(D9.1,比 transactions 更晚)也已删
            assert "notes" not in tables
            # 其他表(outbox / events / emails / ...)仍在
            assert "outbox" in tables
            assert "events" in tables
            assert "emails" in tables
    finally:
        db.close()


def test_alembic_upgrade_downgrade_upgrade_idempotent(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """Case 3 — upgrade + downgrade + upgrade 三步可幂等执行(alembic 标准场景)。"""
    from alembic import command

    # 1) upgrade head
    command.upgrade(alembic_cfg, "head")
    # 2) downgrade -1
    command.downgrade(alembic_cfg, "-1")
    # 3) upgrade head 再次
    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            tables = [
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
            # transactions 表已重新建
            assert "transactions" in tables
            # notes 表(D9.1)也建了
            assert "notes" in tables
            # alembic_version = head(v0.2 D8.1 = 0011_merchant_profile)
            version = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
            assert version is not None
            assert version[0] == "0011_merchant_profile"
    finally:
        db.close()


def test_alembic_transactions_unique_constraint_exists(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """Case 4 — UNIQUE(source, external_transaction_id) 约束在 sqlite_master 中可见(L1 硬约束)。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            # SQLite 把 UNIQUE 约束存为自动唯一索引,PRAGMA index_list 查唯一索引
            idx_list = conn.exec_driver_sql("PRAGMA index_list('transactions')").fetchall()
            unique_idxs = [row for row in idx_list if row[2] == 1]  # row[2]=unique flag
            assert len(unique_idxs) == 1, f"应有 1 UNIQUE 约束,实际 {len(unique_idxs)}"
            uq_name = unique_idxs[0][1]
            # 验证 UNIQUE 索引含 source + external_transaction_id 两列(L1 业务阻断依赖此约束)
            uq_cols = conn.exec_driver_sql(f"PRAGMA index_info('{uq_name}')").fetchall()
            uq_col_names = {row[2] for row in uq_cols}
            assert "source" in uq_col_names
            assert "external_transaction_id" in uq_col_names
    finally:
        db.close()


def test_alembic_transactions_two_indexes_exist(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """Case 5 — 2 索引(idx_transactions_fingerprint + idx_transactions_status_imported DESC)存在(D3.2 雷区 #8 DESC)。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            # 索引 1: idx_transactions_fingerprint(L2 软标记,非 UNIQUE)
            idx1 = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='idx_transactions_fingerprint'"
            ).fetchall()
            assert idx1, "idx_transactions_fingerprint 索引缺失"
            assert "normalized_fingerprint" in idx1[0][0].lower()

            # 索引 2: idx_transactions_status_imported(状态机热路径,含 DESC)
            idx2 = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='idx_transactions_status_imported'"
            ).fetchall()
            assert idx2, "idx_transactions_status_imported 索引缺失"
            ddl2 = idx2[0][0].upper().replace('"', "")
            assert "STATUS" in ddl2
            assert "IMPORTED_AT_MS DESC" in ddl2, (
                f"expected 'imported_at_ms DESC' in idx2 DDL, got: {idx2[0][0]}"
            )
    finally:
        db.close()
