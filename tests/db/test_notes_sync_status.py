"""v0.2.1 #4 — NoteStore sync_status 状态机测试(13 cases).

承接 [[v0.2.1-candidates-2026-06-17]] §5 状态机设计 + D9 NoteStore 已落 ORM 扩展。

4 段测试覆盖(13 cases):
    1. sync_status 字段默认值 + 5 状态枚举(2 tests)
    2. mark_structured 扩展同步写 sync_status='STRUCTURED'(2 tests)
    3. 4 新方法 mark_private_skip / mark_failed / mark_archived / list_by_sync_status(5 tests)
    4. 状态机守卫非法转换拒绝(4 tests)

设计原则(沿 D6.6 P2 修复范本):
    - 状态机守卫:拒绝非法状态转换,抛 ValueError
    - 5 状态枚举白名单:NEW/STRUCTURED/PRIVATE_SKIP/FAILED/ARCHIVED
    - 合法转换:NEW→STRUCTURED/PRIVATE_SKIP/FAILED,FAILED→STRUCTURED(retry),STRUCTURED→ARCHIVED
    - 终态:PRIVATE_SKIP + ARCHIVED 不可再转换
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


# ===== Fixtures(D6.4 范本:InMemory SQLite + create_all)=====


@pytest.fixture
def engine() -> Iterator:
    """InMemory SQLite + Note ORM 11 列 create_all(v0.2.1 #4 sync_status)。"""
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
def store(session_factory):
    """NoteStore 实例。"""
    from my_ai_employee.db.notes import NoteStore

    return NoteStore(session_factory)


@pytest.fixture
def inserted_note(store):
    """典型已插入 note(apple_note_id = 'x-coredata://test/note-001')。"""
    store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="Test Note",
        body="Test body",
        updated_at_ms=1700000000000,
    )
    return "x-coredata://test/note-001"


# ===== 1. sync_status 字段默认值 + 5 状态枚举(2 tests)=====


def test_sync_status_default_is_new(store, inserted_note):
    """1.1 插入 note 后 sync_status 默认值 = 'NEW'。"""
    note = store.find_by_apple_id(inserted_note)
    assert note is not None
    assert note.sync_status == "NEW", f"sync_status 默认应 'NEW', 实际 {note.sync_status!r}"


def test_sync_status_constants_exported():
    """1.2 5 状态常量从 db.notes 正确导出。"""
    from my_ai_employee.db.notes import (
        SYNC_STATUS_ARCHIVED,
        SYNC_STATUS_FAILED,
        SYNC_STATUS_NEW,
        SYNC_STATUS_PRIVATE_SKIP,
        SYNC_STATUS_STRUCTURED,
    )

    assert SYNC_STATUS_NEW == "NEW"
    assert SYNC_STATUS_STRUCTURED == "STRUCTURED"
    assert SYNC_STATUS_PRIVATE_SKIP == "PRIVATE_SKIP"
    assert SYNC_STATUS_FAILED == "FAILED"
    assert SYNC_STATUS_ARCHIVED == "ARCHIVED"


# ===== 2. mark_structured 扩展同步写 sync_status='STRUCTURED'(2 tests)=====


def test_mark_structured_writes_sync_status_structured(store, inserted_note):
    """2.1 mark_structured 同时写 sync_status='STRUCTURED'(沿 D9.4 + v0.2.1 #4 扩展)。"""
    updated = store.mark_structured(inserted_note, ["urgent", "工作"])
    assert updated.sync_status == "STRUCTURED"
    # 验证持久化
    note = store.find_by_apple_id(inserted_note)
    assert note.sync_status == "STRUCTURED"


def test_mark_structured_failed_to_structured_retry(store, inserted_note):
    """2.2 FAILED → STRUCTURED 重试路径(状态机守卫放行)。"""
    # 先标记失败
    store.mark_failed(inserted_note, error_class="LLMError")
    note = store.find_by_apple_id(inserted_note)
    assert note.sync_status == "FAILED"
    # 重试成功 → mark_structured
    updated = store.mark_structured(inserted_note, ["retry_success"])
    assert updated.sync_status == "STRUCTURED"


# ===== 3. 4 新方法(5 tests)=====


def test_mark_private_skip_writes_sync_status(store, inserted_note):
    """3.1 mark_private_skip 写 sync_status='PRIVATE_SKIP'(终态)。"""
    updated = store.mark_private_skip(inserted_note)
    assert updated.sync_status == "PRIVATE_SKIP"
    # 验证持久化
    note = store.find_by_apple_id(inserted_note)
    assert note.sync_status == "PRIVATE_SKIP"


def test_mark_failed_writes_sync_status(store, inserted_note):
    """3.2 mark_failed 写 sync_status='FAILED' + 严判 error_class 非空字符串。"""
    updated = store.mark_failed(inserted_note, error_class="LLMError")
    assert updated.sync_status == "FAILED"


def test_mark_failed_validates_error_class(store, inserted_note):
    """3.3 mark_failed 严判 error_class 必传非空字符串(纯空白拒绝)。"""
    with pytest.raises(ValueError, match="error_class 必须是 str"):
        store.mark_failed(inserted_note, error_class=123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="error_class 必填且必须非空字符串"):
        store.mark_failed(inserted_note, error_class="   ")
    with pytest.raises(ValueError, match="error_class 必填且必须非空字符串"):
        store.mark_failed(inserted_note, error_class="")


def test_mark_archived_writes_sync_status(store, inserted_note):
    """3.4 mark_archived 写 sync_status='ARCHIVED'(终态)。"""
    # 先结构化(归档前置条件:必须 STRUCTURED)
    store.mark_structured(inserted_note, ["to_archived"])
    updated = store.mark_archived(inserted_note)
    assert updated.sync_status == "ARCHIVED"


def test_list_by_sync_status_filters_correctly(store, inserted_note):
    """3.5 list_by_sync_status 按状态过滤(沿 idx_notes_sync_status 索引)。"""
    # 插 3 笔 note,分别 mark 到不同状态
    store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="N2",
        body="",
        updated_at_ms=1700000000001,
    )
    store.insert(
        apple_note_id="x-coredata://test/note-003",
        folder="Notes",
        title="N3",
        body="",
        updated_at_ms=1700000000002,
    )

    store.mark_structured(inserted_note, ["tag_a"])
    store.mark_private_skip("x-coredata://test/note-002")
    # note-003 保持 NEW

    structured = store.list_by_sync_status("STRUCTURED")
    assert len(structured) == 1
    assert structured[0].apple_note_id == inserted_note

    private_skip = store.list_by_sync_status("PRIVATE_SKIP")
    assert len(private_skip) == 1
    assert private_skip[0].apple_note_id == "x-coredata://test/note-002"

    new_notes = store.list_by_sync_status("NEW")
    assert len(new_notes) == 1
    assert new_notes[0].apple_note_id == "x-coredata://test/note-003"

    failed_notes = store.list_by_sync_status("FAILED")
    assert failed_notes == []


# ===== 4. 状态机守卫非法转换拒绝(4 tests)=====


def test_state_guard_rejects_structured_to_structured(store, inserted_note):
    """4.1 状态机守卫:STRUCTURED → STRUCTURED 非法(已结构化,不可重复)。"""
    store.mark_structured(inserted_note, ["first"])
    with pytest.raises(ValueError, match="状态机守卫拒绝非法转换"):
        store.mark_structured(inserted_note, ["second"])


def test_state_guard_rejects_private_skip_to_structured(store, inserted_note):
    """4.2 状态机守卫:PRIVATE_SKIP → STRUCTURED 非法(终态)。"""
    store.mark_private_skip(inserted_note)
    with pytest.raises(ValueError, match="状态机守卫拒绝非法转换"):
        store.mark_structured(inserted_note, ["late"])


def test_state_guard_rejects_archived_to_anything(store, inserted_note):
    """4.3 状态机守卫:ARCHIVED 终态不可再转换(ARCHIVED → STRUCTURED 拒绝)。"""
    store.mark_structured(inserted_note, ["t"])
    store.mark_archived(inserted_note)
    with pytest.raises(ValueError, match="状态机守卫拒绝非法转换"):
        store.mark_structured(inserted_note, ["unarchive"])


def test_state_guard_rejects_invalid_status_string():
    """4.4 _check_state_transition 严判当前/目标状态白名单。"""
    from my_ai_employee.db.notes import NoteStore

    with pytest.raises(ValueError, match="当前 sync_status 非法"):
        NoteStore._check_state_transition("INVALID", "STRUCTURED")
    with pytest.raises(ValueError, match="目标 sync_status 非法"):
        NoteStore._check_state_transition("NEW", "INVALID")
