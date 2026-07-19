"""Codex 对话摘要的本地笔记导入与按日输出。

本模块只接收调用方已经生成的 ``summary``，一条 thread 对应一条笔记：

- 不读取或抓取 Codex 桌面端历史对话；
- 不调用 LLM，不把内容发送到网络；
- 通过 ``NoteStore`` 保存，因此沿用既有 Notes 加密与本地数据库边界；
- 同一个 ``thread_id`` 重导入时更新原笔记，不产生 L2/L3 待确认候选。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from my_ai_employee.db.notes import Note, NoteStore

_MAX_THREAD_ID_CHARS = 120
_MAX_TITLE_CHARS = 512
_MAX_SUMMARY_CHARS = 65_536
_REQUIRED_FIELDS = ("thread_id", "title", "summary", "ended_at_ms")


def _require_nonempty_string(value: Any, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} 必须是 str,实际 type={type(value).__name__}, value={value!r}"
        )
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} 必须非空白字符串")
    if len(cleaned) > maximum:
        raise ValueError(f"{field_name} 长度不得超过 {maximum},实际 {len(cleaned)}")
    if field_name == "thread_id" and any(char in cleaned for char in ("\r", "\n", "\x00")):
        raise ValueError("thread_id 不得包含控制换行字符")
    return cleaned


@dataclass(frozen=True)
class CodexConversationSummary:
    """一条已总结的 Codex 对话输入记录。"""

    thread_id: str
    title: str
    summary: str
    ended_at_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "thread_id",
            _require_nonempty_string(
                self.thread_id, field_name="thread_id", maximum=_MAX_THREAD_ID_CHARS
            ),
        )
        object.__setattr__(
            self,
            "title",
            _require_nonempty_string(self.title, field_name="title", maximum=_MAX_TITLE_CHARS),
        )
        object.__setattr__(
            self,
            "summary",
            _require_nonempty_string(
                self.summary, field_name="summary", maximum=_MAX_SUMMARY_CHARS
            ),
        )
        if (
            type(self.ended_at_ms) is bool
            or not isinstance(self.ended_at_ms, int)
            or self.ended_at_ms < 0
        ):
            raise ValueError(
                "ended_at_ms 必须是原生 int(非 bool)且 >= 0,"
                f" 实际 type={type(self.ended_at_ms).__name__}, value={self.ended_at_ms!r}"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CodexConversationSummary:
        """从 JSONL 单行对象构造并校验输入记录。"""
        missing = [field for field in _REQUIRED_FIELDS if field not in value]
        if missing:
            raise ValueError(f"缺少必填字段: {', '.join(missing)}")
        return cls(
            thread_id=value["thread_id"],
            title=value["title"],
            summary=value["summary"],
            ended_at_ms=value["ended_at_ms"],
        )


@dataclass(frozen=True)
class ConversationImportResult:
    """一次显式导入的结果计数。"""

    created: int = 0
    updated: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated


def load_conversation_summaries_jsonl(path: Path) -> list[CodexConversationSummary]:
    """读取 UTF-8 JSONL；空行跳过，任何坏行都给出行号并 fail-closed。"""
    if not path.is_file():
        raise ValueError(f"输入文件不存在或不是普通文件: {path}")
    records: list[CodexConversationSummary] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"输入文件必须是 UTF-8 JSONL: {path}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            raw_value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL 第 {line_number} 行不是有效 JSON 对象") from exc
        if not isinstance(raw_value, dict):
            raise ValueError(f"JSONL 第 {line_number} 行必须是对象")
        try:
            records.append(CodexConversationSummary.from_mapping(raw_value))
        except ValueError as exc:
            raise ValueError(f"JSONL 第 {line_number} 行无效: {exc}") from exc
    return records


class CodexConversationNotesService:
    """将已总结的 Codex 对话写入本地 Notes，并按自然日生成可读输出。"""

    def __init__(self, store: NoteStore) -> None:
        self._store = store

    def import_summaries(
        self, summaries: Iterable[CodexConversationSummary]
    ) -> ConversationImportResult:
        """逐条幂等导入，返回新建/更新计数。"""
        created = 0
        updated = 0
        for conversation in summaries:
            _note, was_created = self._store.upsert_codex_conversation(
                thread_id=conversation.thread_id,
                title=conversation.title,
                summary=conversation.summary,
                ended_at_ms=conversation.ended_at_ms,
            )
            if was_created:
                created += 1
            else:
                updated += 1
        return ConversationImportResult(created=created, updated=updated)

    def list_daily(self, day: str, *, limit: int = 100) -> list[Note]:
        """读取某一自然日的对话摘要，保持数据库的倒序。"""
        return self._store.list_codex_conversations_for_day(day, limit=limit)

    def render_daily_markdown(self, day: str, *, limit: int = 100) -> str:
        """生成“每次对话一段总结”的当日 Markdown 笔记。"""
        notes = self.list_daily(day, limit=limit)
        lines = [f"# {day} · Codex 对话笔记", ""]
        if not notes:
            lines.append("当日暂无已导入的 Codex 对话总结。")
            return "\n".join(lines) + "\n"
        lines.append(f"共 {len(notes)} 个对话：")
        lines.append("")
        for note in notes:
            local_time = (
                datetime.fromtimestamp(note.updated_at_ms / 1000).astimezone().strftime("%H:%M")
            )
            lines.append(f"## {local_time} · {note.title}")
            lines.append("")
            lines.extend(f"> {line}" if line else ">" for line in note.body.splitlines())
            lines.append("")
        return "\n".join(lines)


__all__ = [
    "CodexConversationNotesService",
    "CodexConversationSummary",
    "ConversationImportResult",
    "load_conversation_summaries_jsonl",
]
