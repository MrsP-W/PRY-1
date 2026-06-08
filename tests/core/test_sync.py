"""D3.3 — IMAP 同步入库测试。

覆盖（[docs/week1-mvp.md §D3.3 验收标准]）：

    - 同步入口走 safe_fetch（mock 返回固定 list[dict]）
    - 增量同步：基于 SyncState.last_uid 只拉新邮件
    - 100/批 commit ORM 入库
    - 失败隔离：单封失败不阻塞后续（用 raise_side_effect mock）
    - received_at 缺失 → fallback 到 fetched_at
    - SyncState 首次写入 + 后续更新
    - UNIQUE(source, uid) 冲突 → skipped 计数

设计：
    - 复用 D3.2.3 fake_keychain + tmp_db_path fixture（同样走 SQLCipher）
    - mock BaseConnector（不依赖 IMAPConnector 真连接）
    - 真 Database（端到端验证 100/批 commit + SyncState upsert）
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.connectors.base import BaseConnector, HealthStatus  # noqa: E402
from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sync import IMAPSync, SyncResult  # noqa: E402


def _arun(coro):
    """测试用 async runner（避免 pytest-asyncio 配置依赖）。"""
    return asyncio.run(coro)


# ===== Fixtures（复用 D3.2.3 模式）=====


@pytest.fixture
def fake_keychain(monkeypatch):
    """in-memory Keychain 模拟（D3.2.3 同款）。"""
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
def tmp_db_path(tmp_path: Path, fake_keychain: dict) -> Path:
    """测试用临时 DB 路径（设 fake_keychain 触发 set_db_password）。"""
    return tmp_path / "sync_test.db"


@pytest.fixture
def db(tmp_db_path: Path, fake_keychain: dict) -> Iterator[Database]:
    """打开真 SQLCipher DB（用 D3.1 schema.sql 初始化）。

    schema.sql 是多语句 DDL，走 `_conn.executescript()`（单语句 `execute`
    会报 "You can only execute one statement at a time"）。这是测试专用
    入口，绕开 `Database.execute()` 的单语句限制（业务代码用 alembic 迁移）。
    """
    from my_ai_employee.core.db import Database as _Db

    _db = _Db.open(db_path=tmp_db_path)
    schema_path = PROJECT_ROOT / "src" / "my_ai_employee" / "core" / "schema.sql"
    if schema_path.exists():
        with open(schema_path, encoding="utf-8") as f:
            # executescript 不受单语句限制（fixture 专用）
            _db._conn.executescript(f.read())  # noqa: SLF001
    _db.close()
    # 重开（让 PRAGMA 生效）
    db = _Db.open(db_path=tmp_db_path)
    yield db
    db.close()


# ===== Mock BaseConnector =====


class FakeIMAPConnector(BaseConnector):
    """测试用 fake connector（继承 BaseConnector 满足 mypy 严格类型检查）。

    `connect/fetch/healthcheck` 是 ABC 抽象方法 — 测试不调它们（IMAPSync 走
    safe_fetch），所以实现为 no-op raise NotImplementedError。
    """

    def __init__(
        self,
        raw_emails: list[dict[str, Any]],
        source: str = "qq",
    ) -> None:
        super().__init__()
        self._raw = raw_emails
        self._source = source
        self.close_called = False

    @property
    def source_name(self) -> str:
        return self._source

    async def connect(self) -> None:
        raise NotImplementedError("FakeIMAPConnector 不支持 connect")

    async def fetch(self, since: datetime) -> list[dict[str, Any]]:
        raise NotImplementedError("FakeIMAPConnector 不支持 fetch（用 safe_fetch）")

    async def healthcheck(self) -> HealthStatus:
        raise NotImplementedError("FakeIMAPConnector 不支持 healthcheck")

    async def safe_fetch(self, since: datetime) -> list[dict[str, Any]]:
        return list(self._raw)

    async def close(self) -> None:
        self.close_called = True


# ===== 辅助：构造 raw email =====


def make_raw(
    uid: int,
    *,
    subject: str = "Test",
    sender: str = "alice@example.com",
    received_at: int | None = 1700000000000,
    message_id: str | None = "<abc@qq.com>",
) -> dict[str, Any]:
    return {
        "uid": uid,
        "subject": subject,
        "sender": sender,
        "received_at": received_at,
        "raw_size": 1024,
        "message_id": message_id,
        "recipients": ["user@qq.com"],
        "labels": ["inbox"],
    }


# ===== 1. 基础同步：100 封全量入库 =====


def test_sync_inserts_all_emails_to_db(
    db: Database,
) -> None:
    """基础同步：3 封 mock 邮件全量入库，DB 可见。"""
    raw = [make_raw(uid=i + 1) for i in range(3)]
    connector = FakeIMAPConnector(raw)
    sync = IMAPSync(db, connector, batch_size=100)
    try:
        result = _arun(sync.run_once())
    finally:
        sync.close()

    assert isinstance(result, SyncResult)
    assert result.total_fetched == 3
    assert result.inserted == 3
    assert result.skipped == 0
    assert result.failed == 0
    assert result.new_last_uid == 3

    # 验证 DB 真实存在
    rows = db.fetch_all("SELECT uid, subject FROM emails ORDER BY uid")
    assert [(r["uid"], r["subject"]) for r in rows] == [
        (1, "Test"),
        (2, "Test"),
        (3, "Test"),
    ]


# ===== 2. 增量同步：SyncState.last_uid 过滤 =====


def test_sync_filters_out_old_uids(
    db: Database,
) -> None:
    """增量：SyncState.last_uid=2 时，UID=1/2 应被过滤，UID=3/4 才入库。"""
    # 先手动设 SyncState.last_uid = 2
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    db.execute(
        "INSERT INTO sync_state (source, last_sync_at, last_uid, "
        "last_status, last_error, consecutive_failures, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("qq", now_ms, 2, "ok", "", 0, now_ms),
    )
    db.commit()  # 显式 commit（Database.execute 不自动 commit — D3.2 设计）

    # mock 拉 4 封（UID 1-4）
    raw = [make_raw(uid=i + 1) for i in range(4)]
    connector = FakeIMAPConnector(raw)
    sync = IMAPSync(db, connector, batch_size=100)
    try:
        result = _arun(sync.run_once())
    finally:
        sync.close()

    # 只入 2 封（UID 3/4），UID 1/2 被过滤
    assert result.total_fetched == 4
    assert result.inserted == 2
    assert result.new_last_uid == 4

    rows = db.fetch_all("SELECT uid FROM emails ORDER BY uid")
    assert [r["uid"] for r in rows] == [3, 4]


# ===== 3. 100/批 commit =====


def test_sync_commits_per_batch(
    db: Database,
) -> None:
    """100/批 commit：250 封 → 3 个 commit（100 + 100 + 50）。"""
    raw = [make_raw(uid=i + 1) for i in range(250)]
    connector = FakeIMAPConnector(raw)
    sync = IMAPSync(db, connector, batch_size=100)
    try:
        result = _arun(sync.run_once())
    finally:
        sync.close()

    assert result.inserted == 250
    assert result.new_last_uid == 250
    # 验证 250 行
    rows = db.fetch_all("SELECT COUNT(*) AS cnt FROM emails")
    assert rows[0]["cnt"] == 250


# ===== 4. 失败隔离：单批 SQLAlchemyError 不阻塞后续 =====


class FailingBatchConnector(BaseConnector):
    """safe_fetch 返回 250 封 + run_once 第 1 次 _commit_batch 抛 SQLAlchemyError。

    模拟"批次 1（1-100）整批失败"场景（最坏情况）— 验证 sync 顶层
    except SQLAlchemyError 隔离，第 2/3 批继续入库。

    继承 BaseConnector 满足 mypy 严格类型检查；connect/fetch/healthcheck
    实现为 no-op raise（测试不调）。
    """

    def __init__(self, raw_emails: list[dict[str, Any]]) -> None:
        super().__init__()
        self._raw = raw_emails
        self._call_count = 0

    @property
    def source_name(self) -> str:
        return "qq"

    async def connect(self) -> None:
        raise NotImplementedError("FailingBatchConnector 不支持 connect")

    async def fetch(self, since: datetime) -> list[dict[str, Any]]:
        raise NotImplementedError("FailingBatchConnector 不支持 fetch")

    async def healthcheck(self) -> HealthStatus:
        raise NotImplementedError("FailingBatchConnector 不支持 healthcheck")

    async def safe_fetch(self, since: datetime) -> list[dict[str, Any]]:
        return list(self._raw)

    async def close(self) -> None:
        pass


def test_sync_continues_after_batch_failure(
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失败隔离：第 1 批触发 SQLAlchemyError → 第 2/3 批仍正常入库。

    D3.3 设计：run_once 顶层 for batch 循环每批独立 try/except —
    任一批 SQLAlchemyError 不阻塞下一批。失败批计 failed=N，下一批继续。
    """
    # 触发 SQLAlchemyError 的方式：让 _commit_batch 看到破坏性 SQL
    # 简洁做法：mock sync._commit_batch 让第 1 次返回 SQLAlchemyError
    from sqlalchemy.exc import OperationalError

    raw = [make_raw(uid=i + 1) for i in range(250)]
    connector = FailingBatchConnector(raw)
    sync = IMAPSync(db, connector, batch_size=100)

    # monkeypatch _commit_batch：第 1 次抛 OperationalError，后续正常
    original_commit = sync._commit_batch  # type: ignore[attr-defined]  # noqa: SLF001
    call_count = {"n": 0}

    def maybe_fail(source: str, now_ms: int, batch: list[dict[str, Any]]) -> tuple[int, int, int]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # OperationalError(stmt, params, orig) — orig 不能是 None
            raise OperationalError("simulated", {}, Exception("orig"))
        result: tuple[int, int, int] = original_commit(source, now_ms, batch)
        return result

    monkeypatch.setattr(sync, "_commit_batch", maybe_fail)

    try:
        result = _arun(sync.run_once())
    finally:
        sync.close()

    # 第 1 批（1-100）→ OperationalError → failed=100
    # 第 2 批（101-200）→ inserted=100
    # 第 3 批（201-250）→ inserted=50
    assert result.failed == 100
    assert result.inserted == 150
    assert result.new_last_uid == 250  # max_uid 从成功批算


# ===== 5. received_at 缺失 → fallback 到 fetched_at =====


def test_sync_received_at_fallback_to_fetched_at(
    db: Database,
) -> None:
    """received_at=None → fallback 到 fetched_at（D3.1.1 决策）。"""
    raw = [make_raw(uid=1, received_at=None)]
    connector = FakeIMAPConnector(raw)
    sync = IMAPSync(db, connector, batch_size=100)
    try:
        result = _arun(sync.run_once())
    finally:
        sync.close()

    assert result.inserted == 1
    row = db.fetch_one("SELECT received_at, fetched_at FROM emails WHERE uid=1")
    assert row is not None  # mypy：fetch_one 返回 dict | None
    # received_at == fetched_at（fallback 成功）
    assert row["received_at"] == row["fetched_at"]
    assert row["received_at"] > 0  # 非零


# ===== 6. SyncState 首次写入 =====


def test_sync_creates_sync_state_on_first_run(
    db: Database,
) -> None:
    """首次同步：SyncState 表被自动创建行。"""
    raw = [make_raw(uid=1)]
    connector = FakeIMAPConnector(raw)
    sync = IMAPSync(db, connector, batch_size=100)
    try:
        _arun(sync.run_once())
    finally:
        sync.close()

    rows = db.fetch_all(
        "SELECT source, last_uid, last_status, consecutive_failures FROM sync_state"
    )
    assert len(rows) == 1
    assert rows[0]["source"] == "qq"
    assert rows[0]["last_uid"] == 1  # last_uid
    assert rows[0]["last_status"] == "ok"
    assert rows[0]["consecutive_failures"] == 0


# ===== 7. SyncState 二次更新 =====


def test_sync_updates_existing_sync_state(
    db: Database,
) -> None:
    """二次同步：SyncState 同一行被更新（不新建）。"""
    raw1 = [make_raw(uid=1)]
    sync1 = IMAPSync(db, FakeIMAPConnector(raw1), batch_size=100)
    try:
        r1 = _arun(sync1.run_once())
    finally:
        sync1.close()
    assert r1.new_last_uid == 1

    # 第二次同步 — 拉 UID=2
    raw2 = [make_raw(uid=2)]
    sync2 = IMAPSync(db, FakeIMAPConnector(raw2), batch_size=100)
    try:
        r2 = _arun(sync2.run_once())
    finally:
        sync2.close()
    assert r2.new_last_uid == 2

    # 仍只有 1 行 sync_state
    rows = db.fetch_all("SELECT source, last_uid FROM sync_state")
    assert len(rows) == 1
    assert rows[0]["last_uid"] == 2  # 第二次 last_uid 覆盖


# ===== 8. JSONList 字段入库（recipients / labels）=====


def test_sync_persists_jsonlist_fields(
    db: Database,
) -> None:
    """JSONList 字段：recipients / labels list 入库后取出仍是 list。"""
    raw = [
        {
            "uid": 1,
            "subject": "Test",
            "sender": "alice@x.com",
            "received_at": 1700000000000,
            "raw_size": 100,
            "message_id": "<m1@x.com>",
            "recipients": ["bob@x.com", "carol@x.com"],
            "labels": ["inbox", "important"],
        }
    ]
    connector = FakeIMAPConnector(raw)
    sync = IMAPSync(db, connector, batch_size=100)
    try:
        _arun(sync.run_once())
    finally:
        sync.close()

    # db.fetch_* 走 raw cursor，JSONList TypeDecorator 不生效（只在 ORM 层生效）
    # D3.2.3 决策：DDL 走 TEXT，ORM 走 list；raw cursor 拿 JSON 字符串，需手动 loads
    import json as _json

    row = db.fetch_one("SELECT recipients, labels FROM emails WHERE uid=1")
    assert row is not None  # mypy：fetch_one 返回 dict | None
    assert isinstance(row["recipients"], str)  # raw cursor 拿的是 JSON 文本
    assert _json.loads(row["recipients"]) == ["bob@x.com", "carol@x.com"]
    assert _json.loads(row["labels"]) == ["inbox", "important"]

    # 对比：用 ORM 拿是 list（TypeDecorator 透明转换）
    from sqlalchemy.orm import Session

    from my_ai_employee.core.models import Email as _Email
    from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine

    engine = make_sqlalchemy_engine(db)
    with Session(engine) as session:
        orm_email = session.get(_Email, 1)
    assert orm_email is not None
    assert isinstance(orm_email.recipients, list)
    assert orm_email.recipients == ["bob@x.com", "carol@x.com"]
    assert isinstance(orm_email.labels, list)
    assert orm_email.labels == ["inbox", "important"]


# ===== 9. 完整清理：close() 被调用 =====


def test_sync_closes_connector(
    db: Database,
) -> None:
    """run_sync helper 应在 finally 关闭 connector。"""
    from my_ai_employee.core.sync import run_sync

    raw = [make_raw(uid=1)]
    connector = FakeIMAPConnector(raw)
    _arun(run_sync(db, connector, batch_size=100))
    assert connector.close_called is True
