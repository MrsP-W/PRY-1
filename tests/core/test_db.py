"""D3.1 — SQLCipher 数据库封装测试。

覆盖（[docs/week1-mvp.md §D3.1 验收]）：

    - 首次启动自动生成 32 字节密码 + 存 Keychain
    - 加密 DB 建表 + 写入 + 关闭
    - 正确密码重开 + 读出原数据
    - 错误密码重开 → 抛 sqlcipher3.DatabaseError
    - 5+ 张表 DDL 应用后存在
    - schema.sql 幂等（重复跑不爆）
    - 上下文管理器：成功 commit / 异常 rollback
    - Keychain 密码持久化（重开 Database.open 不重新生成）

设计：monkeypatch keychain API（避免污染真实 macOS Keychain + 跨测试隔离）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import sqlcipher3

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import db as db_module  # noqa: E402
from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import DEFAULT_DB_PATH, SCHEMA_PATH, Database  # noqa: E402

# ===== Fixtures =====


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """测试用临时 DB 路径（不污染真实 ~/Library/Application Support）。"""
    return tmp_path / "test.db"


@pytest.fixture
def fake_keychain(monkeypatch):
    """用 in-memory dict 模拟 Keychain（避免污染真实 macOS Keychain）。

    返回内部 store dict（测试可断言：密码被写入 / 已存在时不重写）。
    """
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


# ===== Keychain 密码管理 =====


def test_first_open_generates_password(tmp_db_path: Path, fake_keychain: dict) -> None:
    """首次启动：Keychain 缺密码 → 自动生成 32 字节随机串存进去。"""
    assert not fake_keychain  # Keychain 是空的

    db = Database.open(db_path=tmp_db_path)

    # Keychain 写入
    assert (keychain.SERVICE_DB, "data.db") in fake_keychain
    password = fake_keychain[(keychain.SERVICE_DB, "data.db")]
    assert len(password) == 64  # 32 字节 → 64 hex chars
    # 不应该是固定的（每次都新生成）
    db.close()


def test_keychain_password_persists_across_opens(tmp_db_path: Path, fake_keychain: dict) -> None:
    """第二次开 DB：复用 Keychain 已有密码（不重新生成）。"""
    with Database.open(db_path=tmp_db_path):
        pass
    first_password = fake_keychain[(keychain.SERVICE_DB, "data.db")]
    with Database.open(db_path=tmp_db_path):
        pass
    second_password = fake_keychain[(keychain.SERVICE_DB, "data.db")]
    assert first_password == second_password  # 复用同一密码


# ===== 加密往返 =====


def test_db_round_trip_with_correct_password(tmp_db_path: Path, fake_keychain: dict) -> None:
    """建库 + 写 1 行 + 关 + 用同一密码重开 + 能读出。"""
    # 1. 写
    db = Database.open(db_path=tmp_db_path)
    db.init_schema()
    db.execute(
        "INSERT INTO sync_state (source, last_sync_at, last_uid, updated_at) VALUES (?, ?, ?, ?)",
        ("qq", 1000, 42, 2000),
    )
    db.commit()
    db.close()

    # 2. 重开
    db2 = Database.open(db_path=tmp_db_path)
    row = db2.fetch_one("SELECT source, last_uid FROM sync_state WHERE source = 'qq'")
    assert row is not None
    assert row["source"] == "qq"
    assert row["last_uid"] == 42
    db2.close()


def test_db_rejects_wrong_password(tmp_db_path: Path, fake_keychain: dict, monkeypatch) -> None:
    """错误密码重开 → Database.open() 时主动抛 sqlcipher3.DatabaseError。

    设计：db.py 主动跑 PRAGMA quick_check 触发密码校验
    （轻量 + 100% 触发 + 不依赖任何表存在）。
    """
    # 1. 用正确密码建库 + 应用 schema（让 DB 有真实加密页）
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()

    # 2. 篡改 Keychain 密码
    fake_keychain[(keychain.SERVICE_DB, "data.db")] = (
        "wrong-password-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )

    # 3. 错误密码重开 → open() 主动抛 DatabaseError
    with pytest.raises(sqlcipher3.DatabaseError, match="密码错误"):
        Database.open(db_path=tmp_db_path)


# ===== Schema 应用 =====


EXPECTED_TABLES = {
    "emails",
    "attachments",
    "labels",
    "email_labels",
    "sync_state",
    "audit_log",
}


def test_init_schema_creates_all_tables(tmp_db_path: Path, fake_keychain: dict) -> None:
    """init_schema 后，6 张表都存在。"""
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        rows = db.fetch_all("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        table_names = {row["name"] for row in rows}

    # 过滤掉 sqlite 内部表（sqlite_sequence 等）
    actual = table_names & EXPECTED_TABLES
    assert actual == EXPECTED_TABLES, f"缺表：{EXPECTED_TABLES - actual}"


def test_init_schema_is_idempotent(tmp_db_path: Path, fake_keychain: dict) -> None:
    """重复调用 init_schema 不爆（IF NOT EXISTS 幂等）。"""
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        db.init_schema()  # 第二遍
        db.init_schema()  # 第三遍


def test_init_schema_creates_indexes(tmp_db_path: Path, fake_keychain: dict) -> None:
    """schema.sql 里的索引都创建了。"""
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        rows = db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
        index_names = {row["name"] for row in rows}

    expected_indexes = {
        "idx_emails_received_at",
        "idx_emails_source_received",
        "idx_emails_sender",
        "idx_emails_message_id",  # D3.1.1 增：message_id 可空后保留普通索引
        "idx_attachments_email_id",
        "idx_labels_source",
        "idx_email_labels_label_id",
        "idx_audit_log_created_at",
        "idx_audit_log_event",
    }
    missing = expected_indexes - index_names
    assert not missing, f"缺索引: {missing}"


# ===== CRUD 基本操作 =====


def test_execute_and_fetch_all(tmp_db_path: Path, fake_keychain: dict) -> None:
    """execute + fetch_all + fetch_one 基础流程。"""
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        db.executemany(
            "INSERT INTO sync_state (source, last_sync_at, last_uid, updated_at) "
            "VALUES (?, ?, ?, ?)",
            [
                ("qq", 1000, 42, 2000),
                ("outlook", 1500, 100, 2500),
                ("gmail", 2000, 200, 3000),
            ],
        )

        rows = db.fetch_all("SELECT source FROM sync_state ORDER BY last_uid")
        assert [r["source"] for r in rows] == ["qq", "outlook", "gmail"]

        one = db.fetch_one("SELECT source FROM sync_state WHERE source = 'gmail'")
        assert one is not None
        assert one["source"] == "gmail"


def test_unique_constraint_on_emails_source_uid(tmp_db_path: Path, fake_keychain: dict) -> None:
    """emails 表 UNIQUE(source, uid) 约束生效（D3.1.1 修正：去重键改 IMAP UID）。

    原因：RFC 5322 Message-ID 经常缺失（垃圾邮件 / 某些 server 不生成），
    原 (source, message_id) 唯一键会导致无 message_id 邮件互相冲突。
    """
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        db.execute(
            "INSERT INTO emails "
            "(source, uid, message_id, subject, received_at, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("qq", 1, "<msg-1@x.com>", "Subj", 1000, 2000),
        )
        db.commit()

        # 重复插入 (qq, 1) → 应该抛 IntegrityError（即使 message_id 不同）
        with pytest.raises(sqlcipher3.IntegrityError):
            db.execute(
                "INSERT INTO emails "
                "(source, uid, message_id, subject, received_at, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("qq", 1, "<msg-different@x.com>", "Subj dup", 1100, 2100),
            )


def test_foreign_keys_enabled(tmp_db_path: Path, fake_keychain: dict) -> None:
    """外键 PRAGMA 已开启（联表查询需要）。"""
    with Database.open(db_path=tmp_db_path) as db:
        fk_status = db.fetch_one("PRAGMA foreign_keys")
        assert fk_status is not None
        # PRAGMA foreign_keys 返回单列，dict_factory 用列名 "foreign_keys"
        assert fk_status["foreign_keys"] == 1  # 1 = ON


# ===== PRAGMA 配置（D3.1.1 增：WAL / busy_timeout / synchronous）=====


def test_journal_mode_is_wal(tmp_db_path: Path, fake_keychain: dict) -> None:
    """PRAGMA journal_mode = WAL 开启（多读单写不阻塞，D3.3 同步脚本并发读必要）。"""
    with Database.open(db_path=tmp_db_path) as db:
        result = db.fetch_one("PRAGMA journal_mode")
        assert result is not None
        # PRAGMA journal_mode 返回单列 dict["journal_mode"]，值是 "wal" / "memory" / "truncate" 等
        assert result["journal_mode"].lower() == "wal"


def test_busy_timeout_is_5000(tmp_db_path: Path, fake_keychain: dict) -> None:
    """PRAGMA busy_timeout = 5000（DB 锁等 5s 再失败，D3.3 写并发必要）。

    注：PRAGMA busy_timeout 查询列名是 "timeout"（不是 "busy_timeout"）— SQLite 文档规定。
    """
    with Database.open(db_path=tmp_db_path) as db:
        result = db.fetch_one("PRAGMA busy_timeout")
        assert result is not None
        # busy_timeout 单位 ms；列名是 "timeout" 而非 "busy_timeout"
        assert result["timeout"] == 5000


def test_synchronous_is_normal(tmp_db_path: Path, fake_keychain: dict) -> None:
    """PRAGMA synchronous = NORMAL（WAL 模式下推荐，性能/安全平衡）。"""
    with Database.open(db_path=tmp_db_path) as db:
        result = db.fetch_one("PRAGMA synchronous")
        assert result is not None
        # PRAGMA synchronous 返回整数：0=OFF, 1=NORMAL, 2=FULL
        assert result["synchronous"] == 1


# ===== 字段可空（D3.1.1 增：message_id / received_at）=====


def test_message_id_is_nullable(tmp_db_path: Path, fake_keychain: dict) -> None:
    """emails.message_id 可空（D3.1.1 修正：IMAP 邮件可能没有 message_id）。

    设计：垃圾邮件 / 某些 IMAP server 不生成 Message-ID，
    原 NOT NULL 会导致入库失败；改为可空 + 普通索引保留查询能力。
    """
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        # 不传 message_id → 应允许
        db.execute(
            "INSERT INTO emails (source, uid, subject, fetched_at) VALUES (?, ?, ?, ?)",
            ("qq", 1, "No Message-ID", 2000),
        )
        db.commit()
        row = db.fetch_one("SELECT message_id FROM emails WHERE uid = 1")
        assert row is not None
        assert row["message_id"] is None


def test_received_at_is_nullable(tmp_db_path: Path, fake_keychain: dict) -> None:
    """emails.received_at 可空（D3.1.1 修正：envelope.date 可能 None）。

    设计：D2 IMAPConnector.envelope.date 可能为 None（缺 Date 头），
    原 NOT NULL 会导致入库失败；改为可空，D3.3 入库映射层 fallback 到 fetched_at。
    """
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        # 不传 received_at → 应允许（D3.3 入库映射层需 fallback 到 fetched_at）
        db.execute(
            "INSERT INTO emails (source, uid, subject, fetched_at) VALUES (?, ?, ?, ?)",
            ("qq", 1, "No Date Header", 2000),
        )
        db.commit()
        row = db.fetch_one("SELECT received_at, fetched_at FROM emails WHERE uid = 1")
        assert row is not None
        assert row["received_at"] is None
        assert row["fetched_at"] == 2000  # fallback 锚点


# ===== 受控 connection 入口（D3.1.2 增：供 D3.2 alembic env.py 用）=====


def test_connection_property_returns_raw_connection(tmp_db_path: Path, fake_keychain: dict) -> None:
    """db.connection 返回底层 sqlcipher3.Connection（D3.1.2 受控入口）。

    设计：alembic 迁移需要 raw connection 调 `connection.run_sync(...)`，
    但直接用私有 `_conn` 是封装泄漏。`connection` property 是受控入口。

    D3.2 调整：row_factory 常态是 None（D3.2 决策：让 SA dialect 探针天然 OK），
    `db.fetch_*` 方法临时设 dict_factory（业务代码用），但 `db.connection`
    这个**受控入口**直接拿 conn — row 是 tuple（D3.2 新行为）。
    """
    with Database.open(db_path=tmp_db_path) as db:
        raw = db.connection
        # 应是 sqlcipher3.Connection 实例（不是 sqlite3.Connection）
        assert isinstance(raw, sqlcipher3.Connection)
        # 验证能正常跑 SQL（说明 PRAGMA key / WAL 都生效）
        # 注：D3.2 起 conn.row_factory 常态是 None，row 是 tuple（不是 dict）
        row = raw.execute("PRAGMA journal_mode").fetchone()
        assert row is not None
        # row 是 tuple — (journal_mode,) 解构
        assert row[0].lower() == "wal"


def test_connection_property_raises_after_close(tmp_db_path: Path, fake_keychain: dict) -> None:
    """DB 关闭后访问 db.connection 抛 RuntimeError（避免使用半关连接）。"""
    db = Database.open(db_path=tmp_db_path)
    db.close()
    with pytest.raises(RuntimeError, match="DB 已关闭"):
        _ = db.connection


def test_connection_property_raises_after_context_exit(
    tmp_db_path: Path, fake_keychain: dict
) -> None:
    """context manager 退出后再访问 db.connection 抛 RuntimeError。"""
    with Database.open(db_path=tmp_db_path) as db:
        pass  # 正常退出，with 块会 close
    with pytest.raises(RuntimeError, match="DB 已关闭"):
        _ = db.connection


# ===== 上下文管理器事务 =====


def test_context_manager_commits_on_success(tmp_db_path: Path, fake_keychain: dict) -> None:
    """with 块正常退出 → 自动 commit。"""
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        db.execute(
            "INSERT INTO sync_state (source, last_sync_at, last_uid, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("qq", 1000, 42, 2000),
        )
    # 重新打开应该能看到数据（说明 commit 了）
    with Database.open(db_path=tmp_db_path) as db:
        row = db.fetch_one("SELECT source FROM sync_state WHERE source = 'qq'")
        assert row is not None


def test_context_manager_rolls_back_on_exception(tmp_db_path: Path, fake_keychain: dict) -> None:
    """with 块抛异常 → 自动 rollback（数据不写入）。"""
    with pytest.raises(RuntimeError, match="boom"), Database.open(db_path=tmp_db_path) as db:
        db.init_schema()
        db.execute(
            "INSERT INTO sync_state (source, last_sync_at, last_uid, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("qq", 1000, 42, 2000),
        )
        raise RuntimeError("boom")

    # 重新打开应该看不到数据（说明 rollback 了）
    with Database.open(db_path=tmp_db_path) as db:
        row = db.fetch_one("SELECT source FROM sync_state WHERE source = 'qq'")
        assert row is None


# ===== 默认路径 =====


def test_default_db_path_is_macos_standard() -> None:
    """默认 DB 路径是 macOS 标准 Application Support 目录。"""
    assert "Application Support" in str(DEFAULT_DB_PATH)
    assert "my-ai-employee" in str(DEFAULT_DB_PATH)
    assert str(DEFAULT_DB_PATH).endswith("data.db")


def test_schema_path_exists() -> None:
    """schema.sql 文件存在（防止相对路径错）。"""
    assert SCHEMA_PATH.exists()
    assert SCHEMA_PATH.name == "schema.sql"
    assert "CREATE TABLE" in SCHEMA_PATH.read_text(encoding="utf-8")


# ===== 模块导出 =====


def test_module_exports() -> None:
    """__all__ 导出正确。"""
    assert "Database" in db_module.__all__
    assert "DEFAULT_DB_PATH" in db_module.__all__
    assert "SCHEMA_PATH" in db_module.__all__
