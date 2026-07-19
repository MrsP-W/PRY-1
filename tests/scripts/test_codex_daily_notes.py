"""Codex 对话日记 CLI 的写入门与只读输出回归。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def _write_jsonl(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_import_defaults_to_validate_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """未传 --apply 时仅解析输入，绝不打开数据库。"""
    from scripts import codex_daily_notes

    source = tmp_path / "conversations.jsonl"
    _write_jsonl(
        source,
        '{"thread_id":"thread-1","title":"同步方案","summary":"已完成导入设计。",'
        '"ended_at_ms":1784400000000}\n',
    )

    with patch.object(codex_daily_notes, "_open_service") as mock_open:
        rc = codex_daily_notes.main(["import", "--input", str(source)])

    captured = capsys.readouterr()
    assert rc == 0
    assert "parsed=1" in captured.out
    assert "apply=false" in captured.out
    mock_open.assert_not_called()


def test_import_apply_writes_via_service_and_closes_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--apply 明确写入，并在结束后关闭由 CLI 打开的数据库。"""
    from my_ai_employee.notes.codex_conversations import ConversationImportResult
    from scripts import codex_daily_notes

    source = tmp_path / "conversations.jsonl"
    _write_jsonl(
        source,
        '{"thread_id":"thread-1","title":"同步方案","summary":"已完成导入设计。",'
        '"ended_at_ms":1784400000000}\n',
    )
    fake_db = MagicMock()
    fake_service = MagicMock()
    fake_service.import_summaries.return_value = ConversationImportResult(created=1, updated=0)

    with patch.object(codex_daily_notes, "_open_service", return_value=(fake_db, fake_service)):
        rc = codex_daily_notes.main(
            ["import", "--input", str(source), "--db-path", str(tmp_path / "notes.db"), "--apply"]
        )

    captured = capsys.readouterr()
    assert rc == 0
    assert "parsed=1 created=1 updated=0" in captured.out
    fake_service.import_summaries.assert_called_once()
    call_args = fake_service.import_summaries.call_args
    assert call_args is not None
    imported = call_args.args[0]
    assert [(record.thread_id, record.title, record.summary) for record in imported] == [
        ("thread-1", "同步方案", "已完成导入设计。")
    ]
    fake_db.close.assert_called_once()


def test_import_rejects_invalid_jsonl_without_opening_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """坏 JSONL fail-closed，不能触及数据库。"""
    from scripts import codex_daily_notes

    source = tmp_path / "bad.jsonl"
    _write_jsonl(source, "not-json\n")

    with patch.object(codex_daily_notes, "_open_service") as mock_open:
        rc = codex_daily_notes.main(["import", "--input", str(source), "--apply"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "JSONL 第 1 行不是有效 JSON 对象" in captured.err
    mock_open.assert_not_called()


def test_show_outputs_daily_markdown_and_closes_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """show 将当日每次对话的 Markdown 原样输出，且只走服务读取接口。"""
    from scripts import codex_daily_notes

    fake_db = MagicMock()
    fake_service = MagicMock()
    fake_service.render_daily_markdown.return_value = (
        "# 2026-07-19 · Codex 对话笔记\n\n## 10:00 · 同步方案\n\n> 已完成。\n"
    )

    with patch.object(codex_daily_notes, "_open_service", return_value=(fake_db, fake_service)):
        rc = codex_daily_notes.main(
            [
                "show",
                "--date",
                "2026-07-19",
                "--limit",
                "25",
                "--db-path",
                str(tmp_path / "notes.db"),
            ]
        )

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == fake_service.render_daily_markdown.return_value
    fake_service.render_daily_markdown.assert_called_once_with("2026-07-19", limit=25)
    fake_db.close.assert_called_once()


def test_show_rejects_invalid_limit_before_opening_db(capsys: pytest.CaptureFixture[str]) -> None:
    """show 的条数边界在建库前返回可读错误。"""
    from scripts import codex_daily_notes

    with patch.object(codex_daily_notes, "_open_service") as mock_open:
        rc = codex_daily_notes.main(["show", "--limit", "0"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "--limit 必须是 [1,1000] 的整数" in captured.err
    mock_open.assert_not_called()


def test_show_rejects_invalid_date_before_opening_db(capsys: pytest.CaptureFixture[str]) -> None:
    """日期格式错误必须在打开数据库前拒绝，避免无效输入触发本地副作用。"""
    from scripts import codex_daily_notes

    with patch.object(codex_daily_notes, "_open_service") as mock_open:
        rc = codex_daily_notes.main(["show", "--date", "2026-02-30"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "date 必须是 YYYY-MM-DD" in captured.err
    mock_open.assert_not_called()
