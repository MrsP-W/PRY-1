"""D3.2.3 — 真实 alembic 迁移测试。

覆盖（[docs/week1-mvp.md §D3.2 alembic 集成]）：

    - alembic upgrade head 在临时 SQLCipher DB 上成功跑通
    - 跑完后 7 张表都存在（emails / attachments / labels / email_labels /
      sync_state / audit_log / events）  # D4.3.1 复检修正: events 表 (D4.3 新增)
    - alembic_version 表记录当前 revision
    - schema 与 D3.1 schema.sql 1:1 对齐（PRAGMA table_info 验证列+类型）
    - DESC 索引 + NOCASE collation 在真实 DB 生效
    - D4.3.2 复检 P1 修复: 0003 迁移把旧 4 字段 UNIQUE 替换为 UNIQUE(fingerprint)
      (3 个回归测试 — 升级替换 / 幂等 / subject_id=NULL dedupe 强制)

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
from typing import Any

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
def fake_keychain(monkeypatch: Any) -> Any:
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
def alembic_cfg(tmp_db_path: Path, fake_keychain: dict[Any, Any]) -> AlembicConfig:
    """配 alembic 走项目根的 alembic.ini，env.py 自动捡到我们的 fake_keychain。"""
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    # alembic 已经在 ini 里指了 script_location
    return cfg


@pytest.fixture
def patched_database_open(tmp_db_path: Path, monkeypatch: Any) -> Any:
    """monkeypatch Database.open() 用 tmp 路径。"""
    import my_ai_employee.core.db as db_module

    original_open = db_module.Database.open

    def patched_open(db_path: Any = None) -> Any:
        return original_open(db_path=tmp_db_path)

    monkeypatch.setattr(db_module.Database, "open", staticmethod(patched_open))
    return tmp_db_path


# ===== 真 alembic upgrade head 测试 =====


def test_alembic_upgrade_head_creates_all_seven_tables(
    tmp_db_path: Path,
    fake_keychain: dict[Any, Any],
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """alembic upgrade head 跑通后 7 张表 + alembic_version 全存在 (D4.3.1 复检修正)."""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    # 验证 7 张表
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
        assert "emails" in tables
        assert "attachments" in tables
        assert "labels" in tables
        assert "email_labels" in tables
        assert "sync_state" in tables
        assert "audit_log" in tables
        assert "events" in tables  # D4.3.1 复检修正: events 表 (D4.3 新增)
        assert "alembic_version" in tables
    finally:
        db.close()


def test_alembic_version_records_current_revision(
    tmp_db_path: Path,
    fake_keychain: dict[Any, Any],
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """alembic_version 表记录当前 head revision = 0018_agent_runs。

    历史 head 演进:
      - D4.8 锁定时 head=0004_outbox
      - D5.2 加 migration 0005_outbox_sending_state 后 head 推到 0005
      - D5.6.3 加 0006_outbox_approval_provenance(head 推到 0006)
      - D6.4 加 0007_transactions(head 推到 0007)
      - D9.1 加 0008_notes(head 推到 0008)
      - v0.2 B2.1 加 0009_sla_due_at(head 推到 0009)
      - v0.2 B4.1 加 0010_recipient_blacklist(head 推到 0010)
      - v0.2 D8.1 加 0011_merchant_profile(head 推到 0011)
      - v0.2.1 #4 加 0012_note_sync_status(head 推到 0012)
      - v0.2.1 #5 加 0013_note_fingerprint(head 推到 0013)
      - v0.2.1+ 加 0014_note_l2_cross_source(head 推到 0014)
      - v0.2.53.16 加 0015_anomaly_dismissal(head 推到 0015)
      - v0.2.53.51 加 0016_approval_gate_audits(head 推到 0016)
      - Codex 对话笔记加 0017_codex_conversation_notes(head 推到 0017)
      - AgentRun 最小闭环加 0018_agent_runs(head 推到 0018)
    """
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            version = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
        assert version is not None
        assert version[0] == "0018_agent_runs"
    finally:
        db.close()


def test_alembic_schema_matches_d31_sql(
    tmp_db_path: Path,
    fake_keychain: dict[Any, Any],
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """alembic 跑出来的 schema 与 D3.1 schema.sql 关键字段一致。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            # emails.recipients 必须是 TEXT DEFAULT '[]'（不是 JSON）
            col = conn.exec_driver_sql(
                "SELECT type, dflt_value FROM pragma_table_info('emails') WHERE name='recipients'"
            ).fetchone()
            assert col is not None
            assert col[0] == "TEXT", f"expected TEXT, got {col[0]}"
            assert col[1] == "'[]'", f"expected '[]' default, got {col[1]!r}"

            # emails.labels 同样
            col = conn.exec_driver_sql(
                "SELECT type, dflt_value FROM pragma_table_info('emails') WHERE name='labels'"
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
    fake_keychain: dict[Any, Any],
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """alembic 跑出来的 idx_emails_received_at DDL 含 DESC（D3.1 schema 对齐）。"""
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            ddl_rows = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_emails_received_at'"
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
    fake_keychain: dict[Any, Any],
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
    fake_keychain: dict[Any, Any],
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """ORM Base.metadata 表数 == alembic 实际建出的表数（除 alembic_version / sqlite_sequence）。"""
    from alembic import command

    from my_ai_employee.core.models import ApprovalGateAudit  # noqa: F401  # v0.2.53.51
    from my_ai_employee.core.outbox import OutboxEntry  # noqa: F401  # outbox 表
    from my_ai_employee.db.anomaly_dismissals import AnomalyDismissal  # noqa: F401  # v0.2.53.16
    from my_ai_employee.db.blacklist import (
        RecipientBlacklist,  # noqa: F401  # recipient_blacklist 表 (B4.1)
    )
    from my_ai_employee.db.merchant_profile import (
        MerchantProfile,  # noqa: F401  # merchant_profile 表 (D8.1)
    )
    from my_ai_employee.db.notes import Note  # noqa: F401  # notes 表 (D9.1)
    from my_ai_employee.db.transactions import Transaction  # noqa: F401  # transactions 表

    # 0) 显式 import 各表 ORM 模型让 Base.metadata 注册表
    #    (沿 D4.3.2 复检发现: core/models.py 不 import 各表模块)
    from my_ai_employee.events import models as _events_models  # noqa: F401
    from my_ai_employee.runtime.models import AgentRunRecord  # noqa: F401  # agent_runs

    # 1) alembic 跑通
    command.upgrade(alembic_cfg, "head")

    # 2) 拿真实 DB 表名
    db = Database.open(db_path=tmp_db_path)
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

        # 真 DB 多的表:
        #   - alembic_version (alembic 自动建)
        #   - sqlite_sequence (SQLite 在首次 INSERT AUTOINCREMENT 表时自动建, 0003 触发)
        assert real_tables - orm_tables == {"alembic_version", "sqlite_sequence"}
        # ORM 表都在真 DB
        assert orm_tables.issubset(real_tables)
    finally:
        db.close()


# ===== D4.3.2 复检 P1 修复: 0003 迁移回归 =====


def test_0003_migration_replaces_4_field_unique_with_global_fingerprint(
    tmp_db_path: Path,
    fake_keychain: dict[Any, Any],
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """D4.3.2 复检 P1 回归: 0003 把旧 4 字段 UNIQUE 替换为 UNIQUE(fingerprint).

    模拟场景:
        1. 跑 alembic upgrade 到 0002_events（旧版 4 字段 UNIQUE)
        2. 手动 INSERT 两条 subject_id=NULL + 同 fingerprint 的行（旧 4 字段 UNIQUE bug 允许）
        3. 跑 alembic upgrade head(D5.2 后 head=0005_outbox_sending_state)
        4. 验证:
           a. events 表的 UNIQUE 约束是单字段 fingerprint
           b. subject_id=NULL + 同 fingerprint 再次插入 → IntegrityError (dedupe 生效)
           c. alembic_version = 当前 head
    """
    from alembic import command

    # 1) 跑 0002 (旧版 schema, 但当前 0002 已是 UNIQUE(fingerprint) — 见下方 1b 还原)
    command.upgrade(alembic_cfg, "0002_events")
    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.begin() as conn:
            # 1b) 手动 DROP 新约束 + 重建旧 4 字段 UNIQUE (模拟已迁移到 D4.3.1 改前 0002 的旧库)
            conn.exec_driver_sql("CREATE TABLE events_with_old_unique AS SELECT * FROM events")
            conn.exec_driver_sql("DROP TABLE events")
            conn.exec_driver_sql("""
                CREATE TABLE events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    event           TEXT    NOT NULL,
                    status          TEXT    NOT NULL,
                    source          TEXT    NOT NULL DEFAULT '',
                    subject_id      TEXT,
                    fingerprint     TEXT    NOT NULL DEFAULT '',
                    event_metadata  TEXT    NOT NULL DEFAULT '{}',
                    created_at      INTEGER NOT NULL,
                    UNIQUE(event, source, subject_id, fingerprint)
                )
                """)
            conn.exec_driver_sql("INSERT INTO events SELECT * FROM events_with_old_unique")
            conn.exec_driver_sql("DROP TABLE events_with_old_unique")
            # 1c) 验证旧 4 字段 UNIQUE 已生效
            ddl = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            assert ddl is not None
            assert "UNIQUE(event, source, subject_id, fingerprint)" in ddl[0]
    finally:
        db.close()

    # 2) 跑 0003 迁移
    command.upgrade(alembic_cfg, "head")
    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            # 3a) UNIQUE 已是单字段 fingerprint
            ddl = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            assert ddl is not None
            assert "UNIQUE(fingerprint)" in ddl[0]
            assert "UNIQUE(event, source, subject_id, fingerprint)" not in ddl[0]
            # 3b) alembic_version 已记录当前 head
            version = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
            assert version is not None
            assert version[0] == "0018_agent_runs"
    finally:
        db.close()


def test_0003_migration_is_idempotent_for_new_0002_path(
    tmp_db_path: Path,
    fake_keychain: dict[Any, Any],
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """D4.3.2 复检 P1 回归: 0002 (D4.3.1 改后) → 0003 是 no-op 幂等.

    模拟场景:
        1. 跑 alembic upgrade head(D5.2 后 = 0002 + 0003 + 0004 + 0005, 走 D4.3.1 改后 0002 路径)
        2. 验证 events 表存在 + UNIQUE(fingerprint) 生效
        3. 验证 alembic_version = 当前 head
    """
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.connect() as conn:
            ddl = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            assert ddl is not None
            assert "UNIQUE(fingerprint)" in ddl[0]

            version = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
            assert version is not None
            assert version[0] == "0018_agent_runs"
    finally:
        db.close()


def test_0003_migration_subject_id_null_dedupe_enforced(
    tmp_db_path: Path,
    fake_keychain: dict[Any, Any],
    alembic_cfg: AlembicConfig,
    patched_database_open: Path,
) -> None:
    """D4.3.2 复检 P1 回归: 0003 跑完后, subject_id=NULL + 同 fingerprint 必须 dedupe.

    关键 invariant: 旧 4 字段 UNIQUE 在 subject_id=NULL 时允许重复(D4.3.1 P1 复现),
    新 UNIQUE(fingerprint) 全局唯一 — 即便 subject_id=NULL, 同 fingerprint 第二次插必败.
    """
    from alembic import command

    command.upgrade(alembic_cfg, "head")

    db = Database.open(db_path=tmp_db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        with engine.begin() as conn:
            # 1) 插第一条 subject_id=NULL
            conn.exec_driver_sql("""
                INSERT INTO events
                    (event, status, source, subject_id, fingerprint, event_metadata, created_at)
                VALUES
                    ('llm.call.started', 'started', 'minimax', NULL,
                     'fp-A', '{"seq": 1, "timestamp_ms": 1000,
                              "session_id": "s1", "ownership": "observe",
                              "provenance": "live", "fingerprint": "fp-A"}',
                     1000)
                """)
            # 2) 同 fingerprint + subject_id=NULL 第二次插 → 必败(UNIQUE(fingerprint) 触发)
            #    注意: SQLCipher dialect 不一定包装 dbapi 异常为 SA IntegrityError
            #    (D3.3.3 教训: 双层 except 防御) — 同时接两种类型
            import sqlcipher3.dbapi2 as _sqlcipher_dbapi
            from sqlalchemy.exc import IntegrityError as SAIntegrityError

            try:
                conn.exec_driver_sql("""
                    INSERT INTO events
                        (event, status, source, subject_id, fingerprint, event_metadata, created_at)
                    VALUES
                        ('llm.call.started', 'started', 'minimax', NULL,
                         'fp-A', '{"seq": 2, "timestamp_ms": 2000,
                                  "session_id": "s1", "ownership": "observe",
                                  "provenance": "live", "fingerprint": "fp-A"}',
                         2000)
                    """)
                inserted_twice = True
            except (SAIntegrityError, _sqlcipher_dbapi.IntegrityError):
                inserted_twice = False
            assert not inserted_twice, (
                "UNIQUE(fingerprint) 失效: subject_id=NULL + 同 fingerprint 重复插入未被拒绝"
            )

            # 3) 验证确实只有 1 条
            count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM events WHERE fingerprint = 'fp-A'"
            ).fetchone()
            assert count is not None
            assert count[0] == 1
    finally:
        db.close()
