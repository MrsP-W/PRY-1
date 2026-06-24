"""v0.2.1 #5 — NoteStore normalized_fingerprint L2 跨源去重测试(11 cases).

承接 [[v0.2.1-candidates-2026-06-17]] §6 NoteStore L2/L3 跨源去重 + D6.4 transactions L2 范本。

3 段测试覆盖(11 cases):
    1. normalize_note_fingerprint 纯函数正确性(4 tests)
    2. NoteStore.insert 自动派生 fingerprint(3 tests)
    3. NoteStore.find_candidates_by_fingerprint L2 跨源查询(4 tests)

设计原则(沿 D6.4 transactions 范本):
    - L2 软标记:INDEX(normalized_fingerprint),无 UNIQUE(跨源可能重复)
    - fingerprint 派生公式:SHA256(title + "|" + folder + "|" + YYYY-MM-DD(updated_at_ms))[:32]
    - 候选查询排除自身(exclude_note_id)
    - folder_filter 可选(限定单 folder 候选)
    - limit 默认 5,严判 [1, 100]
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


# ===== Fixtures(D6.4 范本:InMemory SQLite + create_all)=====


@pytest.fixture
def engine() -> Iterator[Any]:
    """InMemory SQLite + Note ORM 12 列 create_all(v0.2.1 #4 sync_status + #5 normalized_fingerprint)。"""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.notes import Note  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    """返回 sessionmaker[Any]."""
    return sessionmaker[Any](bind=engine)


@pytest.fixture
def store(session_factory: Any) -> Any:
    """NoteStore 实例。"""
    from my_ai_employee.db.notes import NoteStore

    return NoteStore(session_factory)


# ===== 1. normalize_note_fingerprint 纯函数正确性(4 tests)=====


def test_normalize_note_fingerprint_basic() -> Any:
    """1.1 normalize_note_fingerprint 基本派生(同 title/folder/date → 同 fingerprint)。"""
    from my_ai_employee.core.fingerprint import normalize_note_fingerprint

    fp = normalize_note_fingerprint("Meeting Notes", "Notes", 1700000000000)
    assert isinstance(fp, str)
    assert len(fp) == 32
    # 全是 [0-9a-f] hex
    assert all(c in "0123456789abcdef" for c in fp.lower())


def test_normalize_note_fingerprint_case_insensitive() -> Any:
    """1.2 同 title/folder 但大小写不同 → 同 fingerprint(沿 strip + lower)。"""
    from my_ai_employee.core.fingerprint import normalize_note_fingerprint

    fp1 = normalize_note_fingerprint("Meeting Notes", "Notes", 1700000000000)
    fp2 = normalize_note_fingerprint("meeting notes", "notes", 1700000000000)
    assert fp1 == fp2, "大小写不敏感(strip + lower)"


def test_normalize_note_fingerprint_different_title() -> Any:
    """1.3 不同 title → 不同 fingerprint。"""
    from my_ai_employee.core.fingerprint import normalize_note_fingerprint

    fp1 = normalize_note_fingerprint("Meeting Notes", "Notes", 1700000000000)
    fp2 = normalize_note_fingerprint("Project Plan", "Notes", 1700000000000)
    assert fp1 != fp2, "不同 title 应派生不同 fingerprint"


def test_normalize_note_fingerprint_different_day() -> Any:
    """1.4 不同日期(updated_at_ms 跨天)→ 不同 fingerprint(只取日期,忽略时分秒)。"""
    from my_ai_employee.core.fingerprint import normalize_note_fingerprint

    # 同一 title/folder,不同日期(2026-06-14 vs 2026-06-15)
    fp_day1 = normalize_note_fingerprint("Meeting", "Notes", 1718304000000)  # 2024-06-13 UTC
    fp_day2 = normalize_note_fingerprint("Meeting", "Notes", 1718390400000)  # 2024-06-14 UTC
    assert fp_day1 != fp_day2, "不同日期应派生不同 fingerprint"


# ===== 2. NoteStore.insert 自动派生 fingerprint(3 tests)=====


def test_insert_auto_derives_fingerprint(store: Any) -> Any:
    """2.1 insert 后 normalized_fingerprint 自动派生(同 title/folder/date 同日)。"""
    note = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    assert note.normalized_fingerprint is not None
    assert len(note.normalized_fingerprint) == 32


def test_insert_same_title_folder_day_same_fingerprint(store: Any) -> Any:
    """2.2 同 title/folder/date 的 note 同 fingerprint(跨 apple_note_id 仍相同)。"""
    note1 = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    # 不同 apple_note_id 但同 title/folder/date
    note2 = store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    assert note1.normalized_fingerprint == note2.normalized_fingerprint


def test_insert_case_insensitive_fingerprint(store: Any) -> Any:
    """2.3 大小写不同的 title/folder 派生相同 fingerprint。"""
    note1 = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="notes",  # 小写
        title="meeting notes",  # 小写
        body="",
        updated_at_ms=1700000000000,
    )
    note2 = store.find_by_apple_id("x-coredata://test/note-002")
    assert note1.normalized_fingerprint == note2.normalized_fingerprint


# ===== 3. NoteStore.find_candidates_by_fingerprint L2 跨源查询(4 tests)=====


def test_find_candidates_returns_cross_source_matches(store: Any) -> Any:
    """3.1 同 fingerprint 的 2 笔 note 互为候选(L2 跨源查询基本场景)。"""
    note1 = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    fp = note1.normalized_fingerprint
    assert fp is not None
    candidates = store.find_candidates_by_fingerprint(fp)
    # 2 笔都查到(候选含自身,因为未传 exclude_note_id)
    assert len(candidates) == 2
    assert {c.apple_note_id for c in candidates} == {
        "x-coredata://test/note-001",
        "x-coredata://test/note-002",
    }


def test_find_candidates_exclude_self(store: Any) -> Any:
    """3.2 exclude_note_id 排除自身(写入时防自命中)。"""
    note1 = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    fp = note1.normalized_fingerprint
    assert fp is not None
    candidates = store.find_candidates_by_fingerprint(fp, exclude_note_id=note1.id)
    assert len(candidates) == 1
    assert candidates[0].apple_note_id == "x-coredata://test/note-002"


def test_find_candidates_folder_filter(store: Any) -> Any:
    """3.3 folder_filter 限定单 folder 候选。"""
    # folder A 同 fingerprint
    store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="FolderA",
        title="Meeting",
        body="",
        updated_at_ms=1700000000000,
    )
    store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="FolderA",
        title="Meeting",
        body="",
        updated_at_ms=1700000000000,
    )
    # folder B 同 title 但不同 folder → 不同 fingerprint
    store.insert(
        apple_note_id="x-coredata://test/note-003",
        folder="FolderB",
        title="Meeting",
        body="",
        updated_at_ms=1700000000000,
    )
    # 查 FolderA 的 fingerprint + folder_filter='FolderA'
    fp = store.find_by_apple_id("x-coredata://test/note-001").normalized_fingerprint
    assert fp is not None
    candidates = store.find_candidates_by_fingerprint(fp, folder_filter="FolderA")
    assert len(candidates) == 2
    assert all(c.folder == "FolderA" for c in candidates)


def test_find_candidates_validates_fingerprint(store: Any) -> Any:
    """3.4 find_candidates_by_fingerprint 严判 fingerprint 必为 32 chars SHA-256 hex。"""
    with pytest.raises(ValueError, match="fingerprint 必须是 32 chars SHA-256 hex"):
        store.find_candidates_by_fingerprint("too_short")
    with pytest.raises(ValueError, match="fingerprint 必须只含"):
        store.find_candidates_by_fingerprint("g" * 32)  # 非 hex 字符
