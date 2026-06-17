"""D9.1 — NoteStore + Note ORM 测试(15 cases).

承接 D9(Apple Notes 同步 + ⌥⌘N 剪贴板结构化)+ 沿 D6.4 TransactionStore 测试范本。

5 段测试覆盖(15 cases):
    1. Note ORM 模型列名/类型(3 tests) — 10 列名 + 类型 + UNIQUE 约束
    2. insert 基础功能(3 tests) — 全字段 / 默认值 / 私密/标签可空
    3. insert 入参严判(5 tests) — type/value/范围/枚举(沿 D4.7.3 v1.0.5 P2-1 范本)
    4. UNIQUE 冲突 → NoteDuplicateError(1 test) — L1 业务阻断入口
    5. get_by_id / find_by_apple_id / list_all / list_by_folder 查询(3 tests)

D3.2 8 雷区严判(全部应用):
    - BOOLEAN 走 Integer + server_default="0"
    - AUTOINCREMENT(非 AUTO_INCREMENT)
    - 下划线命名(idx_notes_folder_synced)
    - DESC 索引用 sa.text("synced_at_ms DESC")
    - render_as_batch=True(env.py)
    - downgrade 干净回滚

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突)
    - 拒绝 D3.3.2 反范本(SQLAlchemyError 基类过宽)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    from collections.abc import Iterator

    from my_ai_employee.db.notes import NoteStore


# ===== Fixtures(D6.4 范本:InMemory SQLite + create_all)=====


@pytest.fixture
def engine() -> Iterator:
    """InMemory SQLite + Note ORM 10 列 create_all."""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.notes import Note  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    """返回 sessionmaker."""
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory) -> NoteStore:
    """NoteStore 实例(注入 session_factory)."""
    from my_ai_employee.db.notes import NoteStore

    return NoteStore(session_factory)


@pytest.fixture
def valid_note_params() -> dict:
    """典型合法 note 入参(供 insert 测试复用)."""
    return {
        "apple_note_id": "x-coredata://ICNote/ABC123",
        "folder": "Notes",
        "title": "测试笔记",
        "body": "这是笔记正文",
        "updated_at_ms": 1700000000000,
    }


# ===== 1. Note ORM 模型(3 tests)=====


def test_note_orm_has_11_columns() -> None:
    """1.1 Note ORM 必含 12 列(id/apple_note_id/folder/title/body/attachments_json/is_private/tags/synced_at_ms/updated_at_ms/sync_status)。

    v0.2.1 #4 增量(2026-06-17): 加 sync_status 列(5 状态枚举,默认 'NEW')。
    """
    from my_ai_employee.db.notes import Note

    expected = {
        "id",
        "apple_note_id",
        "folder",
        "title",
        "body",
        "attachments_json",
        "is_private",
        "tags",
        "synced_at_ms",
        "updated_at_ms",
        "sync_status",
        "normalized_fingerprint",
    }
    actual = {col.name for col in Note.__table__.columns}
    assert actual == expected, f"列不匹配:expected={expected}, actual={actual}"


def test_note_orm_tablename_is_notes() -> None:
    """1.2 Note ORM `__tablename__` = 'notes'."""
    from my_ai_employee.db.notes import Note

    assert Note.__tablename__ == "notes"


def test_note_orm_unique_constraint_on_apple_note_id() -> None:
    """1.3 Note ORM 含 UNIQUE 约束 uq_notes_apple_note_id(L1 硬约束)."""
    from sqlalchemy import UniqueConstraint

    from my_ai_employee.db.notes import Note

    # Table.constraints 是 SA 内部属性, FromClause 上无声明(SA 类型分立)— 沿 D4.8 outbox 测试范本
    unique_constraints = [
        c
        for c in Note.__table__.constraints  # type: ignore[attr-defined]
        if isinstance(c, UniqueConstraint) and getattr(c, "name", None) == "uq_notes_apple_note_id"
    ]
    assert len(unique_constraints) == 1


# ===== 2. insert 基础功能(3 tests)=====


def test_insert_full_fields(store: NoteStore, valid_note_params: dict) -> None:
    """2.1 全字段插入 + 必填字段全在 + 默认值正确(folder='Notes',title='',is_private=0)."""
    note = store.insert(
        apple_note_id=valid_note_params["apple_note_id"],
        folder=valid_note_params["folder"],
        title=valid_note_params["title"],
        body=valid_note_params["body"],
        updated_at_ms=valid_note_params["updated_at_ms"],
        attachments_json='[{"name":"a.png","size":1024}]',
        is_private=False,
        tags="work,important",
    )
    assert note.id > 0
    assert note.apple_note_id == valid_note_params["apple_note_id"]
    assert note.folder == "Notes"
    assert note.title == "测试笔记"
    assert note.body == "这是笔记正文"
    assert note.attachments_json == '[{"name":"a.png","size":1024}]'
    assert note.is_private == 0
    assert note.tags == "work,important"
    assert note.synced_at_ms > 0
    assert note.updated_at_ms == 1700000000000


def test_insert_minimal_required_fields(store: NoteStore) -> None:
    """2.2 最小必填字段插入(apple_note_id/folder/title/body/updated_at_ms 必传,其余走默认)."""
    note = store.insert(
        apple_note_id="x-coredata://ICNote/MIN1",
        folder="Notes",
        title="",
        body="",
        updated_at_ms=1700000000000,
    )
    assert note.id > 0
    assert note.attachments_json is None
    assert note.is_private == 0
    assert note.tags is None


def test_insert_is_private_true_stores_as_1(store: NoteStore) -> None:
    """2.3 is_private=True 落库为 1(BOOLEAN 走 Integer)."""
    note = store.insert(
        apple_note_id="x-coredata://ICNote/PRIVATE1",
        folder="Notes",
        title="私密笔记",
        body="**私密**",
        updated_at_ms=1700000000000,
        is_private=True,
    )
    assert note.is_private == 1
    # 二次查也保持 1
    found = store.find_by_apple_id("x-coredata://ICNote/PRIVATE1")
    assert found is not None
    assert found.is_private == 1


# ===== 3. insert 入参严判(5 tests)=====


def test_insert_rejects_non_str_apple_note_id(store: NoteStore) -> None:
    """3.1 apple_note_id 非 str → TypeError."""
    with pytest.raises(TypeError, match="apple_note_id"):
        store.insert(
            apple_note_id=12345,  # type: ignore[arg-type]
            folder="Notes",
            title="",
            body="",
            updated_at_ms=0,
        )


def test_insert_rejects_empty_apple_note_id(store: NoteStore) -> None:
    """3.2 apple_note_id 经 strip 后为空 → ValueError."""
    with pytest.raises(ValueError, match="apple_note_id"):
        store.insert(
            apple_note_id="   ",
            folder="Notes",
            title="",
            body="",
            updated_at_ms=0,
        )


def test_insert_rejects_int_subclass_is_private(store: NoteStore) -> None:
    """3.3 is_private=int 子类(True/False 是 int 子类)→ TypeError(bool 子类陷阱)."""
    with pytest.raises(TypeError, match="is_private"):
        store.insert(
            apple_note_id="x-coredata://ICNote/TEST1",
            folder="Notes",
            title="",
            body="",
            updated_at_ms=0,
            is_private=1,  # type: ignore[arg-type]
        )


def test_insert_rejects_negative_updated_at_ms(store: NoteStore) -> None:
    """3.4 updated_at_ms < 0 → ValueError(epoch ms 必 >= 0)."""
    with pytest.raises(ValueError, match="updated_at_ms"):
        store.insert(
            apple_note_id="x-coredata://ICNote/TEST2",
            folder="Notes",
            title="",
            body="",
            updated_at_ms=-1,
        )


def test_insert_rejects_whitespace_only_tags(store: NoteStore) -> None:
    """3.5 tags 仅含空白字符 → ValueError(应传 None 或非空字符串)."""
    with pytest.raises(ValueError, match="tags"):
        store.insert(
            apple_note_id="x-coredata://ICNote/TEST3",
            folder="Notes",
            title="",
            body="",
            updated_at_ms=0,
            tags="   ",
        )


# ===== 4. UNIQUE 冲突 → NoteDuplicateError(1 test)=====


def test_insert_duplicate_apple_note_id_raises_note_duplicate_error(
    store: NoteStore, valid_note_params: dict
) -> None:
    """4.1 同 apple_note_id 二次插入 → NoteDuplicateError(L1 业务阻断入口)."""
    from my_ai_employee.db.notes import NoteDuplicateError

    store.insert(**valid_note_params)
    with pytest.raises(NoteDuplicateError) as exc_info:
        store.insert(**valid_note_params)
    assert exc_info.value.apple_note_id == valid_note_params["apple_note_id"]


# ===== 5. 查询方法(3 tests)=====


def test_get_by_id_and_find_by_apple_id(store: NoteStore) -> None:
    """5.1 get_by_id + find_by_apple_id 互查(走 PK + UNIQUE 索引)."""
    inserted = store.insert(
        apple_note_id="x-coredata://ICNote/QUERY1",
        folder="Notes",
        title="查询测试",
        body="正文",
        updated_at_ms=1700000000000,
    )
    by_id = store.get_by_id(inserted.id)
    by_apple = store.find_by_apple_id("x-coredata://ICNote/QUERY1")
    assert by_id is not None
    assert by_apple is not None
    assert by_id.id == by_apple.id
    assert by_apple.title == "查询测试"
    # 不存在的 ID
    assert store.find_by_apple_id("nonexistent") is None
    assert store.get_by_id(99999) is None


def test_list_all_ordered_by_synced_at_ms_desc(store: NoteStore) -> None:
    """5.2 list_all 按 synced_at_ms DESC 倒序."""
    for i in range(3):
        store.insert(
            apple_note_id=f"x-coredata://ICNote/ORD{i}",
            folder="Notes",
            title=f"笔记{i}",
            body="",
            updated_at_ms=1700000000000 + i,
            synced_at_ms=1700000000000 + i,  # 显式传,避免同 1ms 累积(undefined 排序)
        )
    notes = store.list_all(limit=10)
    assert len(notes) == 3
    # 倒序:最后插入的排前面
    assert notes[0].title == "笔记2"
    assert notes[1].title == "笔记1"
    assert notes[2].title == "笔记0"


def test_list_by_folder_filters_by_folder(store: NoteStore) -> None:
    """5.3 list_by_folder 按 folder 过滤 + 倒序."""
    store.insert(
        apple_note_id="x-coredata://ICNote/WORK1",
        folder="工作",
        title="工作笔记1",
        body="",
        updated_at_ms=1700000000000,
    )
    store.insert(
        apple_note_id="x-coredata://ICNote/LIFE1",
        folder="生活",
        title="生活笔记1",
        body="",
        updated_at_ms=1700000000001,
    )
    work_notes = store.list_by_folder("工作")
    life_notes = store.list_by_folder("生活")
    assert len(work_notes) == 1
    assert work_notes[0].title == "工作笔记1"
    assert len(life_notes) == 1
    assert life_notes[0].title == "生活笔记1"
