"""Codex 对话摘要导入、按日笔记与加密读回的回归测试。"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.core.notes_encryption import (
    _CIPHERTEXT_PREFIX_V3,
    NotesCipherImpl,
    NotesCipherStub,
)
from my_ai_employee.db.notes import (
    NOTE_SOURCE_CODEX_CONVERSATION,
    SYNC_STATUS_ARCHIVED,
    Note,
    NoteStore,
)
from my_ai_employee.notes.codex_conversations import (
    CodexConversationNotesService,
    CodexConversationSummary,
    ConversationImportResult,
    load_conversation_summaries_jsonl,
)


def _local_today() -> str:
    """返回与 NoteStore 相同本机时区下的当天日期。"""
    return datetime.now().astimezone().date().isoformat()


def _local_day_ms(day: str, *, hour: int, minute: int = 0) -> int:
    """构造与 NoteStore 按本机自然日筛选一致的毫秒时间戳。"""
    parsed = date.fromisoformat(day)
    local_time = datetime(parsed.year, parsed.month, parsed.day, hour, minute).astimezone()
    return int(local_time.timestamp() * 1000)


def test_local_day_bounds_handles_europe_madrid_dst_offsets() -> None:
    """按日查询必须使用目标日期偏移，不能复用当前冬夏令时的固定 UTC offset。"""
    if not hasattr(time, "tzset"):
        pytest.skip("当前平台不支持 tzset")

    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Europe/Madrid"
        time.tzset()
        actual = {day: NoteStore._local_day_bounds_ms(day) for day in ("2026-01-15", "2026-07-15")}
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()

    madrid = ZoneInfo("Europe/Madrid")
    expected = {
        "2026-01-15": (
            int(datetime(2026, 1, 15, tzinfo=madrid).timestamp() * 1000),
            int(datetime(2026, 1, 16, tzinfo=madrid).timestamp() * 1000),
        ),
        "2026-07-15": (
            int(datetime(2026, 7, 15, tzinfo=madrid).timestamp() * 1000),
            int(datetime(2026, 7, 16, tzinfo=madrid).timestamp() * 1000),
        ),
    }
    assert actual == expected


@pytest.fixture
def engine() -> Iterator[Any]:
    """独立内存库，避免触碰本机实际 Notes 数据。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    return sessionmaker[Any](bind=engine)


@pytest.fixture
def store(session_factory: Any) -> NoteStore:
    return NoteStore(session_factory)


@pytest.fixture
def service(store: NoteStore) -> CodexConversationNotesService:
    return CodexConversationNotesService(store)


@pytest.fixture
def encrypted_store(session_factory: Any) -> NoteStore:
    return NoteStore(session_factory, cipher=NotesCipherImpl(master_key=b"x" * 32))


@pytest.fixture
def encrypted_service(encrypted_store: NoteStore) -> CodexConversationNotesService:
    return CodexConversationNotesService(encrypted_store)


def test_import_jsonl_creates_local_codex_notes(
    service: CodexConversationNotesService,
    tmp_path: Path,
) -> None:
    """JSONL 的已总结对话可显式导入，并按最新结束时间排序。"""
    day = _local_today()
    input_path = tmp_path / "codex-conversations.jsonl"
    input_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "thread_id": "thread-morning",
                        "title": "早间开发",
                        "summary": "完成导入链路设计。",
                        "ended_at_ms": _local_day_ms(day, hour=9),
                    },
                    ensure_ascii=False,
                ),
                "",
                json.dumps(
                    {
                        "thread_id": "thread-afternoon",
                        "title": "下午检查",
                        "summary": "确认测试范围。",
                        "ended_at_ms": _local_day_ms(day, hour=15),
                    },
                    ensure_ascii=False,
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = service.import_summaries(load_conversation_summaries_jsonl(input_path))

    assert result == ConversationImportResult(created=2, updated=0)
    assert result.total == 2
    notes = service.list_daily(day)
    assert [(note.apple_note_id, note.title, note.body) for note in notes] == [
        ("codex://thread-afternoon", "下午检查", "确认测试范围。"),
        ("codex://thread-morning", "早间开发", "完成导入链路设计。"),
    ]
    assert all(note.note_source == NOTE_SOURCE_CODEX_CONVERSATION for note in notes)


def test_import_same_thread_updates_existing_summary(
    service: CodexConversationNotesService,
    store: NoteStore,
) -> None:
    """同一 thread_id 重导入只能更新既有笔记，不能生成重复行或候选。"""
    day = _local_today()
    first_result = service.import_summaries(
        [
            CodexConversationSummary(
                thread_id="thread-update",
                title="初版标题",
                summary="初版总结。",
                ended_at_ms=_local_day_ms(day, hour=10),
            )
        ]
    )
    first_note = store.find_by_apple_id("codex://thread-update")
    assert first_note is not None

    updated_result = service.import_summaries(
        [
            CodexConversationSummary(
                thread_id="thread-update",
                title="更新后标题",
                summary="更新后总结。",
                ended_at_ms=_local_day_ms(day, hour=16),
            )
        ]
    )

    assert first_result == ConversationImportResult(created=1, updated=0)
    assert updated_result == ConversationImportResult(created=0, updated=1)
    updated_note = store.find_by_apple_id("codex://thread-update")
    assert updated_note is not None
    assert updated_note.id == first_note.id
    assert updated_note.title == "更新后标题"
    assert updated_note.body == "更新后总结。"
    assert updated_note.needs_confirm == 0
    assert updated_note.candidate_match_id is None
    assert [note.id for note in service.list_daily(day)] == [first_note.id]


def test_list_daily_filters_by_date_and_excludes_regular_notes(
    service: CodexConversationNotesService,
    store: NoteStore,
) -> None:
    """每日笔记只显示当天 Codex 摘要，且保持结束时间倒序。"""
    day = _local_today()
    previous_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    service.import_summaries(
        [
            CodexConversationSummary(
                thread_id="thread-early",
                title="当天早间",
                summary="早间总结。",
                ended_at_ms=_local_day_ms(day, hour=8),
            ),
            CodexConversationSummary(
                thread_id="thread-late",
                title="当天晚间",
                summary="晚间总结。",
                ended_at_ms=_local_day_ms(day, hour=20),
            ),
            CodexConversationSummary(
                thread_id="thread-previous",
                title="昨日对话",
                summary="昨日总结。",
                ended_at_ms=_local_day_ms(previous_day, hour=20),
            ),
        ]
    )
    store.insert(
        apple_note_id="x-coredata://ICNote/REGULAR-SAME-DAY",
        folder="Notes",
        title="普通笔记",
        body="不应出现在 Codex 对话笔记中。",
        updated_at_ms=_local_day_ms(day, hour=12),
    )

    notes = service.list_daily(day)

    assert [note.title for note in notes] == ["当天晚间", "当天早间"]
    assert [note.title for note in service.list_daily(previous_day)] == ["昨日对话"]


def test_codex_summary_is_not_an_l3_candidate_for_regular_note(
    service: CodexConversationNotesService,
    store: NoteStore,
) -> None:
    """Codex 摘要必须与 Apple Notes 的 L2/L3 候选去重链路隔离。"""
    day = _local_today()
    service.import_summaries(
        [
            CodexConversationSummary(
                thread_id="thread-isolated-source",
                title="同标题不应候选",
                summary="这是 Codex 对话总结，不是普通 Apple Notes。",
                ended_at_ms=_local_day_ms(day, hour=10),
            )
        ]
    )

    regular_note = store.insert(
        apple_note_id="x-coredata://ICNote/REGULAR-NO-CODEX-CANDIDATE",
        folder="Notes",
        title="同标题不应候选",
        body="普通笔记正文。",
        updated_at_ms=_local_day_ms(day, hour=11),
    )

    assert regular_note.needs_confirm == 0
    assert regular_note.candidate_match_id is None


def test_generic_codex_source_is_excluded_from_l2_l3_candidates(store: NoteStore) -> None:
    """公共 insert 的 Codex 来源也不能留下普通 Notes 去重指纹。"""
    day = _local_today()
    codex_note = store.insert(
        apple_note_id="codex://generic-source-isolation",
        folder="Codex 对话",
        title="同标题不应候选",
        body="Codex 摘要。",
        updated_at_ms=_local_day_ms(day, hour=10),
        note_source=NOTE_SOURCE_CODEX_CONVERSATION,
    )
    regular_note = store.insert(
        apple_note_id="x-coredata://ICNote/REGULAR-NO-GENERIC-CODEX-CANDIDATE",
        folder="Codex 对话",
        title="同标题不应候选",
        body="普通 Notes 正文。",
        updated_at_ms=_local_day_ms(day, hour=10),
    )

    assert codex_note.normalized_fingerprint is None
    assert regular_note.needs_confirm == 0
    assert regular_note.candidate_match_id is None


def test_reimport_rejects_archived_codex_conversation(
    service: CodexConversationNotesService,
    store: NoteStore,
) -> None:
    """用户归档后保持终态，重导入不能静默复活或覆盖摘要。"""
    day = _local_today()
    service.import_summaries(
        [
            CodexConversationSummary(
                thread_id="thread-archived",
                title="归档前标题",
                summary="归档前总结。",
                ended_at_ms=_local_day_ms(day, hour=10),
            )
        ]
    )
    archived = store.mark_archived("codex://thread-archived")

    with pytest.raises(ValueError, match="仅 STRUCTURED Codex 对话可重新导入"):
        service.import_summaries(
            [
                CodexConversationSummary(
                    thread_id="thread-archived",
                    title="不应覆盖",
                    summary="不应覆盖归档内容。",
                    ended_at_ms=_local_day_ms(day, hour=12),
                )
            ]
        )

    preserved = store.find_by_apple_id("codex://thread-archived")
    assert archived.sync_status == SYNC_STATUS_ARCHIVED
    assert preserved is not None
    assert preserved.sync_status == SYNC_STATUS_ARCHIVED
    assert preserved.title == "归档前标题"
    assert preserved.body == "归档前总结。"


def test_reimport_encrypted_conversation_requires_available_key(
    encrypted_service: CodexConversationNotesService,
    session_factory: Any,
) -> None:
    """密文已有但当前密钥不可用时，拒绝以 Stub 明文覆盖。"""
    day = _local_today()
    encrypted_service.import_summaries(
        [
            CodexConversationSummary(
                thread_id="thread-encryption-guard",
                title="加密标题",
                summary="加密总结。",
                ended_at_ms=_local_day_ms(day, hour=18),
            )
        ]
    )
    unavailable_service = CodexConversationNotesService(
        NoteStore(session_factory, cipher=NotesCipherStub())
    )

    with pytest.raises(ValueError, match="加密内容不可用"):
        unavailable_service.import_summaries(
            [
                CodexConversationSummary(
                    thread_id="thread-encryption-guard",
                    title="不应降级",
                    summary="不应覆盖加密内容。",
                    ended_at_ms=_local_day_ms(day, hour=19),
                )
            ]
        )

    with session_factory() as session:
        raw = session.execute(
            select(Note).where(Note.apple_note_id == "codex://thread-encryption-guard")
        ).scalar_one()
        assert raw.title.startswith(_CIPHERTEXT_PREFIX_V3)
        assert raw.body.startswith(_CIPHERTEXT_PREFIX_V3)


def test_render_daily_markdown_lists_each_conversation_summary(
    service: CodexConversationNotesService,
) -> None:
    """Markdown 输出包含当日标题、对话数量、标题与逐行摘要。"""
    day = _local_today()
    service.import_summaries(
        [
            CodexConversationSummary(
                thread_id="thread-markdown",
                title="测试 Markdown",
                summary="第一行总结。\n第二行总结。",
                ended_at_ms=_local_day_ms(day, hour=13, minute=5),
            )
        ]
    )

    rendered = service.render_daily_markdown(day)

    assert rendered.startswith(f"# {day} · Codex 对话笔记\n\n共 1 个对话：\n\n")
    assert "## " in rendered
    assert " · 测试 Markdown\n\n" in rendered
    assert "> 第一行总结。\n> 第二行总结。\n" in rendered
    assert rendered.endswith("\n")


def test_load_jsonl_rejects_bad_line_with_line_number(tmp_path: Path) -> None:
    """任一坏行必须带行号失败，避免仅导入输入文件的前半段。"""
    input_path = tmp_path / "invalid-codex-conversations.jsonl"
    input_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "thread_id": "thread-valid",
                        "title": "有效记录",
                        "summary": "不应因后续坏行而部分返回。",
                        "ended_at_ms": 1,
                    },
                    ensure_ascii=False,
                ),
                '{"thread_id":',
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="JSONL 第 2 行不是有效 JSON 对象"):
        load_conversation_summaries_jsonl(input_path)


def test_encrypted_codex_summary_decrypts_on_daily_read(
    encrypted_service: CodexConversationNotesService,
    encrypted_store: NoteStore,
    session_factory: Any,
) -> None:
    """Codex 导入沿用 Notes AES-GCM：库内密文、按日读取与 Markdown 为明文。"""
    day = _local_today()
    result = encrypted_service.import_summaries(
        [
            CodexConversationSummary(
                thread_id="thread-encrypted",
                title="加密对话标题",
                summary="加密对话总结。",
                ended_at_ms=_local_day_ms(day, hour=18),
            )
        ]
    )
    imported = encrypted_store.find_by_apple_id("codex://thread-encrypted")

    assert result == ConversationImportResult(created=1, updated=0)
    assert imported is not None
    assert imported.title == "加密对话标题"
    assert imported.body == "加密对话总结。"
    with session_factory() as session:
        raw = session.get(Note, imported.id)
        assert raw is not None
        assert raw.title.startswith(_CIPHERTEXT_PREFIX_V3)
        assert raw.body.startswith(_CIPHERTEXT_PREFIX_V3)

    daily_notes = encrypted_service.list_daily(day)
    assert [(note.title, note.body) for note in daily_notes] == [("加密对话标题", "加密对话总结。")]
    assert "> 加密对话总结。" in encrypted_service.render_daily_markdown(day)
