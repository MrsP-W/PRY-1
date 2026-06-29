"""v0.2 B4.1 — RecipientBlacklistStore + RecipientBlacklist ORM 测试(16 cases).

承接 v0.1.0 post-tag 阶段 + 沿 D9.1 NoteStore 测试范本。

5 段测试覆盖(16 cases):
    1. RecipientBlacklist ORM 模型(3 tests) — 6 列名 + tablename + UNIQUE 约束
    2. insert 基础功能(3 tests) — 全字段 / 默认值 / is_active=1 默认启用
    3. insert 入参严判(4 tests) — type/value/范围/枚举(沿 D4.7.3 v1.0.5 P2-1 范本)
    4. UNIQUE 冲突 → RecipientBlacklistDuplicateError(1 test) — L1 业务阻断入口
    5. 查询 + deactivate(5 tests) — get_by_id / find_by_email / is_blocked / list_all / deactivate

D3.2 8 雷区严判(全部应用):
    - BOOLEAN 走 Integer + server_default="0/1"
    - AUTOINCREMENT(非 AUTO_INCREMENT)
    - 下划线命名(idx_recipient_blacklist_active)
    - DESC 索引用 sa.text("added_at_ms DESC")
    - render_as_batch=True(env.py)
    - downgrade 干净回滚

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突)
    - 拒绝 D3.3.2 反范本(SQLAlchemyError 基类过宽)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    from collections.abc import Iterator

    from my_ai_employee.db.blacklist import RecipientBlacklistStore


# ===== Fixtures(沿 D9.1 NoteStore 测试范本:InMemory SQLite + create_all)======


@pytest.fixture
def engine() -> Iterator[Any]:
    """InMemory SQLite + RecipientBlacklist ORM 6 列 create_all."""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.blacklist import RecipientBlacklist  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    """返回 sessionmaker[Any]."""
    return sessionmaker[Any](bind=engine)


@pytest.fixture
def store(session_factory: Any) -> RecipientBlacklistStore:
    """RecipientBlacklistStore 实例(注入 session_factory)."""
    from my_ai_employee.db.blacklist import RecipientBlacklistStore

    return RecipientBlacklistStore(session_factory)


@pytest.fixture
def valid_bl_params() -> dict[Any, Any]:
    """典型合法 blacklist 入参(供 insert 测试复用)."""
    return {
        "recipient_email": "spam@example.com",
        "reason": "用户举报 spam",
        "added_by": "manual",
        "added_at_ms": 1700000000000,
    }


# ===== 1. RecipientBlacklist ORM 模型(3 tests)======


def test_recipient_blacklist_orm_has_6_columns() -> None:
    """1.1 RecipientBlacklist ORM 必含 6 列(id/recipient_email/reason/added_by/added_at_ms/is_active)."""
    from my_ai_employee.db.blacklist import RecipientBlacklist

    expected = {
        "id",
        "recipient_email",
        "reason",
        "added_by",
        "added_at_ms",
        "is_active",
    }
    actual = {col.name for col in RecipientBlacklist.__table__.columns}
    assert actual == expected, f"列不匹配:expected={expected}, actual={actual}"


def test_recipient_blacklist_orm_tablename_is_recipient_blacklist() -> None:
    """1.2 RecipientBlacklist ORM `__tablename__` = 'recipient_blacklist'."""
    from my_ai_employee.db.blacklist import RecipientBlacklist

    assert RecipientBlacklist.__tablename__ == "recipient_blacklist"


def test_recipient_blacklist_orm_unique_constraint_on_recipient_email() -> None:
    """1.3 RecipientBlacklist ORM 含 UNIQUE 约束 uq_recipient_blacklist_email(L1 硬约束)."""
    from sqlalchemy import UniqueConstraint

    from my_ai_employee.db.blacklist import RecipientBlacklist

    # Table.constraints 是 SA 内部属性,FromClause 上无声明(SA 类型分立)— 沿 D9.1 NoteStore 测试范本
    unique_constraints = [
        c
        for c in RecipientBlacklist.__table__.constraints
        if isinstance(c, UniqueConstraint)
        and getattr(c, "name", None) == "uq_recipient_blacklist_email"
    ]
    assert len(unique_constraints) == 1


# ===== 2. insert 基础功能(3 tests)======


def test_insert_full_fields(
    store: RecipientBlacklistStore, valid_bl_params: dict[Any, Any]
) -> None:
    """2.1 全字段插入 + 必填字段全在 + 默认值正确(reason/added_by/is_active)."""
    entry = store.insert(
        recipient_email=valid_bl_params["recipient_email"],
        reason=valid_bl_params["reason"],
        added_by=valid_bl_params["added_by"],
        added_at_ms=valid_bl_params["added_at_ms"],
    )
    assert entry.id > 0
    assert entry.recipient_email == "spam@example.com"
    assert entry.reason == "用户举报 spam"
    assert entry.added_by == "manual"
    assert entry.added_at_ms == 1700000000000
    assert entry.is_active == 1


def test_insert_default_values(store: RecipientBlacklistStore) -> None:
    """2.2 默认值插入:reason=''/added_by='manual'/is_active=1/added_at_ms=now."""
    entry = store.insert(recipient_email="user@example.com")
    assert entry.reason == ""
    assert entry.added_by == "manual"
    assert entry.is_active == 1
    assert entry.added_at_ms > 0  # 默认 = 当前时间


def test_insert_added_by_three_choices(store: RecipientBlacklistStore) -> None:
    """2.3 added_by 3 选 1 枚举: 'manual' / 'auto_spam' / 'auto_bounce' 全部接受."""
    for i, added_by in enumerate(["manual", "auto_spam", "auto_bounce"]):
        entry = store.insert(
            recipient_email=f"user{i}@example.com",
            added_by=added_by,
        )
        assert entry.added_by == added_by


# ===== 3. insert 入参严判(4 tests)======


def test_insert_rejects_non_string_recipient_email(store: RecipientBlacklistStore) -> None:
    """3.1 recipient_email 必填非 str — TypeError."""
    with pytest.raises(TypeError, match="recipient_email 必须是 str"):
        store.insert(recipient_email=123)


def test_insert_rejects_empty_or_whitespace_recipient_email(
    store: RecipientBlacklistStore,
) -> None:
    """3.2 recipient_email 必填非空白(strip() 后非空)— ValueError."""
    with pytest.raises(ValueError, match="recipient_email 必非空"):
        store.insert(recipient_email="   ")


def test_insert_rejects_recipient_email_without_at_sign(store: RecipientBlacklistStore) -> None:
    """3.3 recipient_email 必须含 '@' 字符 — ValueError."""
    with pytest.raises(ValueError, match="recipient_email 必须含 '@'"):
        store.insert(recipient_email="notanemail")


def test_insert_rejects_invalid_added_by(store: RecipientBlacklistStore) -> None:
    """3.4 added_by 必 3 选 1 枚举 — ValueError(沿 D4.7.3 v1.0.5 P2-1 范本)."""
    with pytest.raises(ValueError, match="added_by 必须是 3 选 1 枚举"):
        store.insert(recipient_email="user@example.com", added_by="invalid_source")


# ===== 4. UNIQUE 冲突 → RecipientBlacklistDuplicateError(1 test)======


def test_insert_raises_duplicate_error_on_unique_conflict(
    store: RecipientBlacklistStore,
) -> None:
    """4.1 UNIQUE(recipient_email) 冲突 → RecipientBlacklistDuplicateError(L1 业务阻断入口)."""
    store.insert(recipient_email="dup@example.com", reason="首次拉黑")
    with pytest.raises(Exception) as exc_info:
        store.insert(recipient_email="dup@example.com", reason="二次拉黑")
    # 接受 RecipientBlacklistDuplicateError 或其基类 Exception
    assert "RecipientBlacklistDuplicateError" in type(exc_info.value).__name__
    assert "dup@example.com" in str(exc_info.value)


# ===== 5. 查询 + deactivate(5 tests)======


def test_get_by_id_returns_entry(store: RecipientBlacklistStore) -> None:
    """5.1 get_by_id 查到刚 insert 的条目."""
    entry = store.insert(recipient_email="find@example.com")
    found = store.get_by_id(entry.id)
    assert found is not None
    assert found.id == entry.id
    assert found.recipient_email == "find@example.com"


def test_find_by_email_returns_entry(store: RecipientBlacklistStore) -> None:
    """5.2 find_by_email 按 recipient_email 查询(B4.2 hot-path 反向查询)."""
    store.insert(recipient_email="search@example.com", reason="测试")
    found = store.find_by_email("search@example.com")
    assert found is not None
    assert found.recipient_email == "search@example.com"
    assert found.reason == "测试"


def test_is_blocked_returns_true_for_active_entry(store: RecipientBlacklistStore) -> None:
    """5.3 is_blocked 邮箱在黑名单(is_active=1)返回 True(B4.2 hot-path)."""
    store.insert(recipient_email="block@example.com")
    assert store.is_blocked("block@example.com") is True


def test_list_all_returns_only_active_by_default(store: RecipientBlacklistStore) -> None:
    """5.4 list_all(only_active=True 默认)仅返回 is_active=1 软启用条目."""
    entry1 = store.insert(recipient_email="a@example.com")
    entry2 = store.insert(recipient_email="b@example.com")
    store.deactivate(entry2.id)
    active = store.list_all()
    assert len(active) == 1
    assert active[0].id == entry1.id


def test_deactivate_soft_deletes_entry(store: RecipientBlacklistStore) -> None:
    """5.5 deactivate(bl_id) 软删除(is_active=0),审计可追溯."""
    entry = store.insert(recipient_email="deact@example.com")
    assert store.is_blocked("deact@example.com") is True
    store.deactivate(entry.id)
    # 软删除后 is_blocked 返回 False
    assert store.is_blocked("deact@example.com") is False
    # 但条目仍存在(只读)
    still_there = store.get_by_id(entry.id)
    assert still_there is not None
    assert still_there.is_active == 0
