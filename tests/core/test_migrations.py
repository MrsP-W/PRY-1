"""D3.2.3 — 真实 alembic 迁移测试。

覆盖（[docs/week1-mvp.md §D3.2 alembic 集成]）：

    - alembic upgrade head 在临时 SQLCipher DB 上成功跑通
    - 跑完后 6 张表都存在（emails / attachments / labels / email_labels /
      sync_state / audit_log）
    - alembic_version 表记录当前 revision
    - schema 与 D3.1 schema.sql 1:1 对齐（PRAGMA table_info 验证列+类型）
    - DESC 索引 + NOCASE collation 在真实 DB 生效

设计：
    - monkeypatch keychain + Database.open() 让 alembic env.py 走 tmp 路径
    - 用 alembic.command API（不调 subprocess）
    - 测试结束自动清理（db.close + tmp_path 自动清）

阻塞问题 1 闭环：alembic upgrade head --sql 之前会因
`Column(..., sqlite_collation="NOCASE")` 报 ArgumentError，D3.2.3 修复后
本测试保证 online 模式也能跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig

# 让 tests/ 能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402

# ===== Fixtures =====


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
    return tmp_path / "migration_test.db"


@pytest.fixture
def alembic_cfg(tmp_db_path: Path, fake_keychain: dict) -> AlembicConfig:
    """配 alembic 走项目根的 alembic.ini，env.py 自动捡到我们的 fake_keychain。"""
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    # alembic 已经在 ini 里指了 script_location
    return cfg


@pytest.fixture
def patched_database_open(tmp_db_path: Path, monkeypatch):
    """monkeypatch Database.open() 用 tmp 路径。"""
    import my_ai_employee.core.db as db_module

    original_open = db_module.Database.open

    def patched_open(db_path=None):  # type: ignore[no-untyped-def]
        return original_open(db_path=tmp_db_path)

    monkeypatch.setattr(db_module.Database, "open", staticmethod(patched_open))
    return tmp_db_path


# ===== 真 alembic upgrade head 测试 =====


def test_alembic_upgrade_head_creates_all_six_tables(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """alembic upgrade head 跑通后 6 张表 + alembic_version 全存在。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    # 验证 6 张表
    db = Database.open(db_path=str(tmp_db_path))
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            tables = [
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            ]
        assert "emails" in tables
        assert "attachments" in tables
        assert "labels" in tables
        assert "email_labels" in tables
        assert "sync_state" in tables
        assert "audit_log" in tables
        assert "alembic_version" in tables
    finally:
        db.close()


def test_alembic_version_records_current_revision(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """alembic_version 表记录当前 revision = 0001_initial。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=str(tmp_db_path))
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            version = conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).fetchone()
        assert version is not None
        assert version[0] == "0001_initial"
    finally:
        db.close()


def test_alembic_schema_matches_d31_sql(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """alembic 跑出来的 schema 与 D3.1 schema.sql 关键字段一致。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=str(tmp_db_path))
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            # emails.recipients 必须是 TEXT DEFAULT '[]'（不是 JSON）
            col = conn.exec_driver_sql(
                "SELECT type, dflt_value FROM pragma_table_info('emails') "
                "WHERE name='recipients'"
            ).fetchone()
            assert col is not None
            assert col[0] == "TEXT", f"expected TEXT, got {col[0]}"
            assert col[1] == "'[]'", f"expected '[]' default, got {col[1]!r}"

            # emails.labels 同样
            col = conn.exec_driver_sql(
                "SELECT type, dflt_value FROM pragma_table_info('emails') "
                "WHERE name='labels'"
            ).fetchone()
            assert col is not None
            assert col[0] == "TEXT"
            assert col[1] == "'[]'"

            # labels.name COLLATE NOCASE — pragma_table_info 不返回 collation，
            # 从 sqlite_master 的 CREATE TABLE DDL 字符串里找
            ddl = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='labels'"
            ).fetchone()
            assert ddl is not None
            assert "COLLATE NOCASE" in ddl[0].upper().replace('"', ""), (
                f"expected COLLATE NOCASE in labels DDL, got: {ddl[0]}"
            )
    finally:
        db.close()


def test_alembic_creates_desc_indexes(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """alembic 跑出来的 idx_emails_received_at DDL 含 DESC（D3.1 schema 对齐）。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=str(tmp_db_path))
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            ddl_rows = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master "
                "WHERE type='index' AND name='idx_emails_received_at'"
            ).fetchall()
            assert ddl_rows, "idx_emails_received_at not found"
            assert "DESC" in ddl_rows[0][0]

            ddl_rows = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master "
                "WHERE type='index' AND name='idx_audit_log_created_at'"
            ).fetchall()
            assert ddl_rows, "idx_audit_log_created_at not found"
            assert "DESC" in ddl_rows[0][0]
    finally:
        db.close()


def test_alembic_offline_sql_generation(
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """alembic upgrade head --sql（offline 模式）生成完整 DDL 不报错。

    阻塞问题 1 闭环：修复 sqlite_collation 写法后 offline 模式退出码 0。
    """
    from alembic import command

    # offline 模式不需要真 DB — 不会调 Database.open()，但 fake_keychain 保险
    command.upgrade(alembic_cfg, "head", sql=True)

    captured = capsys.readouterr()
    # 关键 DDL 片段必须出现
    assert "CREATE TABLE emails" in captured.out
    assert "CREATE TABLE labels" in captured.out
    assert "CREATE TABLE email_labels" in captured.out
    assert "CREATE TABLE attachments" in captured.out
    assert "CREATE TABLE sync_state" in captured.out
    assert "CREATE TABLE audit_log" in captured.out
    # NOCASE
    assert "NOCASE" in captured.out
    # DESC 索引
    assert "received_at DESC" in captured.out
    assert "created_at DESC" in captured.out
    # TEXT DEFAULT '[]'
    assert "DEFAULT '[]'" in captured.out


# ===== 跑完测试后必须保留：D3.2 models.py metadata 与 alembic 一致 =====


def test_orm_metadata_tables_match_alembic_tables(
    tmp_db_path: Path,
    fake_keychain: dict,
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """ORM Base.metadata 表数 == alembic 实际建出的表数（除 alembic_version）。"""
    from alembic import command

    # 1) alembic 跑通
    command.upgrade(alembic_cfg, "head")

    # 2) 拿真实 DB 表名
    db = Database.open(db_path=str(tmp_db_path))
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            real_tables = {
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        # 3) ORM metadata 表名
        orm_tables = set(Base.metadata.tables.keys())

        # 真 DB 多一张 alembic_version（alembic 自动建）
        assert real_tables - orm_tables == {"alembic_version"}
        # ORM 表都在真 DB
        assert orm_tables.issubset(real_tables)
    finally:
        db.close()
