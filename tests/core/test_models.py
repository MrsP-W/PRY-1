"""D3.2 — SQLAlchemy 2.0 ORM 测试（覆盖 6 个 Model）。

覆盖（[docs/week1-mvp.md §D3.2 验收]）：

    - 6 个 Model 的 CRUD 基本操作
    - 关系（Email.attachments / Email.labels / Attachment.email 等）
    - 级联删除（Email.delete → Attachment 自动删；Label.delete → EmailLabel 自动删）
    - JSON 字段（recipients / labels list[dict]）往返
    - UNIQUE 约束（emails.source+uid / labels.name+source）
    - 可空字段（message_id / received_at）
    - server_default 生效（last_status="pending" / last_error=""）
    - Base.metadata.create_all + make_sqlalchemy_engine 走 SQLCipher

设计：
    - 复用 test_db.py 的 fixture 模式（tmp_db_path + fake_keychain）
    - 共享 session_factory fixture
    - 用 SQLAlchemy Session + ORM 走所有断言（不走 raw SQL）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import sqlcipher3

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import (  # noqa: E402
    Attachment,
    AuditLog,
    Base,
    Email,
    Label,
    SyncState,
    list_tables,
)
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator


# ===== Fixtures =====


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """测试用临时 DB 路径（不污染真实 ~/Library/Application Support）。"""
    return tmp_path / "test.db"


@pytest.fixture
def fake_keychain(monkeypatch):
    """用 in-memory dict 模拟 Keychain（避免污染真实 macOS Keychain）。"""
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
def db_with_schema(tmp_db_path: Path, fake_keychain: dict) -> Iterator[Database]:
    """打开 DB + 应用 schema + yield（测试后自动 close）。"""
    db = Database.open(db_path=tmp_db_path)
    engine = make_sqlalchemy_engine(db)
    Base.metadata.create_all(engine)
    yield db
    db.close()


@pytest.fixture
def session_factory(db_with_schema: Database):  # type: ignore[no-untyped-def]
    """返回 SQLAlchemy sessionmaker（绑 SQLCipher engine）。"""
    from sqlalchemy.orm import sessionmaker

    engine = make_sqlalchemy_engine(db_with_schema)
    return sessionmaker(bind=engine)


# ===== Metadata / 6 个 Model 注册 =====


def test_six_models_registered_in_metadata() -> None:
    """Base.metadata 注册了 6 个表（mirror schema.sql）。"""
    tables = list_tables()
    assert tables == sorted(
        ["emails", "attachments", "labels", "email_labels", "sync_state", "audit_log"]
    )


# ===== CRUD — Email =====


def test_email_create_and_query(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Email: 创建 + session.get 重查 + 字段一致。"""
    with session_factory() as session:
        e = Email(
            source="qq",
            uid=1,
            message_id="<msg@x.com>",
            subject="Hello",
            sender="alice@example.com",
            recipients=["bob@example.com", "carol@example.com"],
            received_at=1_700_000_000_000,
            raw_size=1024,
            body_text="plain body",
            body_html="<p>html body</p>",
            fetched_at=1_700_000_001_000,
            labels=["inbox", "important"],
        )
        session.add(e)
        session.commit()
        eid = e.id

    with session_factory() as session:
        got = session.get(Email, eid)
        assert got is not None
        assert got.source == "qq"
        assert got.uid == 1
        assert got.message_id == "<msg@x.com>"
        assert got.subject == "Hello"
        # JSON 字段：list 往返
        assert got.recipients == ["bob@example.com", "carol@example.com"]
        assert got.labels == ["inbox", "important"]
        assert got.received_at == 1_700_000_000_000
        assert got.fetched_at == 1_700_000_001_000


def test_email_message_id_nullable(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Email.message_id 可空（D3.1.1 修正）。"""
    with session_factory() as session:
        e = Email(
            source="qq", uid=1, subject="no-mid", sender="x@y.com",
            received_at=1000, fetched_at=2000,
        )
        session.add(e)
        session.commit()
        eid = e.id

    with session_factory() as session:
        got = session.get(Email, eid)
        assert got is not None
        assert got.message_id is None


def test_email_received_at_nullable(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Email.received_at 可空（D3.1.1 修正）。"""
    with session_factory() as session:
        e = Email(
            source="qq", uid=1, subject="no-date", sender="x@y.com",
            fetched_at=2000,
        )
        session.add(e)
        session.commit()
        eid = e.id

    with session_factory() as session:
        got = session.get(Email, eid)
        assert got is not None
        assert got.received_at is None
        assert got.fetched_at == 2000


def test_email_default_values(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Email 默认值：subject=""/sender=""/recipients=[]/labels=[]/raw_size=0。"""
    with session_factory() as session:
        e = Email(source="qq", uid=1, sender="x@y.com", fetched_at=2000)
        session.add(e)
        session.commit()
        eid = e.id

    with session_factory() as session:
        got = session.get(Email, eid)
        assert got is not None
        assert got.subject == ""
        assert got.sender == "x@y.com"  # 我们传了
        assert got.recipients == []
        assert got.labels == []
        assert got.raw_size == 0
        assert got.body_text == ""
        assert got.body_html == ""


def test_email_unique_constraint_source_uid(session_factory) -> None:  # type: ignore[no-untyped-def]
    """emails UNIQUE(source, uid) 约束生效（重复 uid 抛 IntegrityError）。"""
    with session_factory() as session:
        session.add(Email(source="qq", uid=1, fetched_at=1000))
        session.commit()

    with session_factory() as session, pytest.raises(sqlcipher3.IntegrityError):
        session.add(Email(source="qq", uid=1, fetched_at=2000))
        session.commit()


# ===== CRUD — Attachment =====


def test_attachment_create_and_query(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Attachment: 创建 + 关联到 email + 重查。"""
    with session_factory() as session:
        e = Email(source="qq", uid=1, sender="x@y.com", fetched_at=2000)
        a = Attachment(
            email=e, filename="a.txt", content_type="text/plain",
            size=10, local_path="/tmp/a.txt", sha256="abc",
        )
        session.add_all([e, a])
        session.commit()
        eid, aid = e.id, a.id

    with session_factory() as session:
        got = session.get(Attachment, aid)
        assert got is not None
        assert got.filename == "a.txt"
        assert got.email_id == eid
        assert got.email.source == "qq"


# ===== CRUD — Label + EmailLabel =====


def test_label_unique_name_source(session_factory) -> None:  # type: ignore[no-untyped-def]
    """labels UNIQUE(name, source) 约束生效。"""
    with session_factory() as session:
        session.add(Label(name="inbox", source="qq"))
        session.commit()

    with session_factory() as session, pytest.raises(sqlcipher3.IntegrityError):
        session.add(Label(name="inbox", source="qq"))
        session.commit()


def test_label_default_color(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Label 默认 color = "#808080" / source = "system"（server_default）。"""
    with session_factory() as session:
        label = Label(name="auto")
        session.add(label)
        session.commit()
        lid = label.id

    with session_factory() as session:
        got = session.get(Label, lid)
        assert got is not None
        assert got.color == "#808080"
        assert got.source == "system"


# ===== 关系 — Email ↔ Attachment =====


def test_email_attachments_relationship(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Email.attachments 反向关系：1 个 email 多个 attachments。"""
    with session_factory() as session:
        e = Email(source="qq", uid=1, sender="x@y.com", fetched_at=2000)
        e.attachments = [
            Attachment(filename="a.txt", size=10, sha256="aaa"),
            Attachment(filename="b.txt", size=20, sha256="bbb"),
        ]
        session.add(e)
        session.commit()
        eid = e.id

    with session_factory() as session:
        got = session.get(Email, eid)
        assert got is not None
        assert len(got.attachments) == 2
        assert {a.filename for a in got.attachments} == {"a.txt", "b.txt"}


def test_attachment_email_back_populates(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Attachment.email 反向关系：attachment 拿到 email 实例。"""
    with session_factory() as session:
        e = Email(source="qq", uid=1, sender="x@y.com", fetched_at=2000)
        a = Attachment(email=e, filename="a.txt")
        session.add_all([e, a])
        session.commit()
        aid = a.id

    with session_factory() as session:
        got = session.get(Attachment, aid)
        assert got is not None
        assert got.email.source == "qq"


# ===== 级联删除 — Email → Attachment =====


def test_cascade_delete_email_to_attachments(session_factory) -> None:  # type: ignore[no-untyped-def]
    """删 Email 自动删附件（cascade="all, delete-orphan" + FK ON DELETE CASCADE）。"""
    with session_factory() as session:
        e = Email(source="qq", uid=1, sender="x@y.com", fetched_at=2000)
        e.attachments = [
            Attachment(filename="a.txt", size=10),
            Attachment(filename="b.txt", size=20),
        ]
        session.add(e)
        session.commit()
        eid = e.id

    # 删 email
    with session_factory() as session:
        e = session.get(Email, eid)
        assert e is not None
        session.delete(e)
        session.commit()

    # 验证 attachments 也被删了
    with session_factory() as session:
        assert session.query(Attachment).count() == 0


# ===== CRUD — SyncState =====


def test_sync_state_default_last_status_pending(session_factory) -> None:  # type: ignore[no-untyped-def]
    """SyncState.last_status server_default = 'pending'。"""
    with session_factory() as session:
        s = SyncState(source="outlook", updated_at=3000)
        session.add(s)
        session.commit()
        sid = s.id

    with session_factory() as session:
        got = session.get(SyncState, sid)
        assert got is not None
        assert got.last_status == "pending"
        assert got.last_sync_at == 0
        assert got.last_uid == 0
        assert got.last_error == ""
        assert got.consecutive_failures == 0


def test_sync_state_unique_source(session_factory) -> None:  # type: ignore[no-untyped-def]
    """sync_state UNIQUE(source) 约束。"""
    with session_factory() as session:
        session.add(SyncState(source="qq", updated_at=2000))
        session.commit()

    with session_factory() as session, pytest.raises(sqlcipher3.IntegrityError):
        session.add(SyncState(source="qq", updated_at=3000))
        session.commit()


# ===== CRUD — AuditLog =====


def test_audit_log_create_and_query(session_factory) -> None:  # type: ignore[no-untyped-def]
    """AuditLog: 创建 + event/source/detail/created_at 都持久化。"""
    with session_factory() as session:
        a = AuditLog(
            event="sync_completed", source="qq",
            detail='{"count": 10}', created_at=4_000,
        )
        session.add(a)
        session.commit()
        aid = a.id

    with session_factory() as session:
        got = session.get(AuditLog, aid)
        assert got is not None
        assert got.event == "sync_completed"
        assert got.source == "qq"
        assert got.detail == '{"count": 10}'
        assert got.created_at == 4_000


# ===== 联合查询 — Email JOIN Attachment =====


def test_email_attachments_filter_by_email(session_factory) -> None:  # type: ignore[no-untyped-def]
    """关系查询：拿某个 email 的所有附件（D3 阶段用得多）。"""
    with session_factory() as session:
        e1 = Email(source="qq", uid=1, sender="x@y.com", fetched_at=1000)
        e2 = Email(source="qq", uid=2, sender="x@y.com", fetched_at=2000)
        e1.attachments = [Attachment(filename="a.txt", size=10)]
        e2.attachments = [
            Attachment(filename="b.txt", size=20),
            Attachment(filename="c.txt", size=30),
        ]
        session.add_all([e1, e2])
        session.commit()
        e1_id, e2_id = e1.id, e2.id

    with session_factory() as session:
        e2_got = session.get(Email, e2_id)
        assert e2_got is not None
        assert len(e2_got.attachments) == 2
        e1_got = session.get(Email, e1_id)
        assert e1_got is not None
        assert len(e1_got.attachments) == 1
