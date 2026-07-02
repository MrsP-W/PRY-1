"""v0.2.1+ — NoteStore L2 跨源写入测试(needs_confirm + candidate_match_id 字段 + list_by_needs_confirm).

承接 [[v0.2.1-candidates-2026-06-17]] §9.4 NoteStore L2 跨源写入(沿 D9.6 留口业务落地):
    沿 D6.4 transactions L2 范本:
        - 第一次写入:needs_confirm=0, candidate_match_id=NULL
        - 第二次写入(同 fingerprint,不同 apple_note_id):needs_confirm=1, candidate_match_id=earliest.id
        - 第三次写入(同 fingerprint,更早日期不算 candidate — 日期不同就不同 fingerprint)

3 段测试覆盖(9 cases):
    1. NoteStore.insert 自动派生 needs_confirm(3 tests)
    2. NoteStore.insert 自动锁定 candidate_match_id(3 tests)
    3. NoteStore.list_by_needs_confirm L2 待确认列表(3 tests)

设计原则(沿 D6.4 transactions L2 范本 + 0013 软标记无 FK):
    - L2 软标记:needs_confirm 走 Integer(0/1)(沿 D3.2 雷区 #2)
    - candidate_match_id 纯 Integer 字段,无 FK(沿 0013 范本,引用一致由应用层保)
    - 1-click 确认留 v0.2.2+(本轮不实现)
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


# ===== Fixtures(沿 test_notes_fingerprint.py 范本)====


@pytest.fixture
def engine() -> Iterator[Any]:
    """InMemory SQLite + Note ORM 14 列 create_all(v0.2.1 #4 + #5 + v0.2.1+ L2 跨源)。"""
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


# ===== 1. NoteStore.insert 自动派生 needs_confirm(3 tests)====


def test_insert_first_note_needs_confirm_zero(store: Any) -> Any:
    """1.1 第一次写入:needs_confirm=0(无 L2 候选)。"""
    note = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    assert note.needs_confirm == 0, "首次写入同 fingerprint 应 needs_confirm=0"


def test_insert_second_note_needs_confirm_one(store: Any) -> Any:
    """1.2 第二次写入(同 fingerprint,不同 apple_note_id):needs_confirm=1。"""
    store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    note2 = store.insert(
        apple_note_id="x-coredata://test/note-002",  # 不同 apple_note_id
        folder="Notes",
        title="Meeting Notes",  # 同 title
        body="",
        updated_at_ms=1700000000000,  # 同日期
    )
    assert note2.needs_confirm == 1, "同 fingerprint 跨 apple_note_id 写入应 needs_confirm=1"


def test_insert_different_fingerprint_no_confirm(store: Any) -> Any:
    """1.3 不同 fingerprint(不同 title 或不同日期):needs_confirm=0(无候选)。"""
    store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    note2 = store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Project Plan",  # 不同 title → 不同 fingerprint
        body="",
        updated_at_ms=1700000000000,
    )
    assert note2.needs_confirm == 0, "不同 fingerprint 应 needs_confirm=0"


# ===== 2. NoteStore.insert 自动锁定 candidate_match_id(3 tests)====


def test_insert_first_note_candidate_match_none(store: Any) -> Any:
    """2.1 第一次写入:candidate_match_id=NULL(无候选)。"""
    note = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    assert note.candidate_match_id is None, "首次写入应 candidate_match_id=NULL"


def test_insert_second_note_candidate_match_locks_earliest(store: Any) -> Any:
    """2.2 第二次写入(同 fingerprint):candidate_match_id=earliest.id(最早候选)。"""
    note1 = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    note2 = store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    assert note2.candidate_match_id == note1.id, (
        f"note2.candidate_match_id 应锁定最早 note1.id={note1.id}, 实际={note2.candidate_match_id}"
    )


def test_insert_third_note_candidate_match_locks_first_not_second(store: Any) -> Any:
    """2.3 第三次写入:candidate_match_id 仍锁最早(not 第二早),避免链式引用。"""
    note1 = store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    note2 = store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    note3 = store.insert(
        apple_note_id="x-coredata://test/note-003",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    # note2 锁 note1(note1 是最早),note3 也应锁 note1(不要链式 note2)
    assert note2.candidate_match_id == note1.id
    assert note3.candidate_match_id == note1.id, (
        f"note3.candidate_match_id 应锁最早 note1.id={note1.id}(非 note2.id={note2.id}),"
        f" 实际={note3.candidate_match_id}"
    )


# ===== 3. NoteStore.list_by_needs_confirm L2 待确认列表(3 tests)====


def test_list_by_needs_confirm_returns_only_candidates(store: Any) -> Any:
    """3.1 list_by_needs_confirm 只返 needs_confirm=1 的 notes。"""
    store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    # 同 fingerprint 写入 → needs_confirm=1
    store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    # 不同 fingerprint 写入 → needs_confirm=0
    store.insert(
        apple_note_id="x-coredata://test/note-003",
        folder="Notes",
        title="Project Plan",
        body="",
        updated_at_ms=1700000000000,
    )
    pending = store.list_by_needs_confirm()
    assert len(pending) == 1
    assert pending[0].apple_note_id == "x-coredata://test/note-002"
    assert pending[0].needs_confirm == 1


def test_list_by_needs_confirm_empty_when_no_candidates(store: Any) -> Any:
    """3.2 无 L2 候选时返空 list[Any](全部 needs_confirm=0)。"""
    store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Meeting Notes",
        body="",
        updated_at_ms=1700000000000,
    )
    store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Project Plan",  # 不同 fingerprint
        body="",
        updated_at_ms=1700000000000,
    )
    pending = store.list_by_needs_confirm()
    assert pending == []


def test_list_by_needs_confirm_validates_limit(store: Any) -> Any:
    """3.3 list_by_needs_confirm 严判 limit 范围 [1, 10000] 沿 list_by_sync_status 范本。"""
    with pytest.raises(ValueError, match="limit 必须是"):
        store.list_by_needs_confirm(limit=0)
    with pytest.raises(ValueError, match="limit 必须是"):
        store.list_by_needs_confirm(limit=10001)
    with pytest.raises(ValueError, match="limit 必须是"):
        store.list_by_needs_confirm(limit=True)  # bool 子类陷阱


# ===== 4. NoteStore.count_by_needs_confirm SQL COUNT(*)(Day 10 Phase 2)=====


def test_count_by_needs_confirm_matches_pending_list(store: Any) -> Any:
    """4.1 count_by_needs_confirm 与 list_by_needs_confirm 长度一致."""
    store.insert(
        apple_note_id="x-coredata://ICNote/COUNT-A",
        folder="Notes",
        title="首次",
        body="",
        updated_at_ms=1_700_000_000_000,
    )
    store.insert(
        apple_note_id="x-coredata://ICNote/COUNT-B",
        folder="Notes",
        title="首次",
        body="",
        updated_at_ms=1_700_000_000_000,
    )
    assert store.count_by_needs_confirm() == 1
    assert len(store.list_by_needs_confirm()) == 1


def test_count_by_needs_confirm_zero_when_no_candidates(store: Any) -> Any:
    """4.2 无 L2 候选时 count 为 0."""
    store.insert(
        apple_note_id="x-coredata://ICNote/COUNT-C",
        folder="Notes",
        title="独立笔记",
        body="",
        updated_at_ms=1_700_000_001_000,
    )
    assert store.count_by_needs_confirm() == 0
