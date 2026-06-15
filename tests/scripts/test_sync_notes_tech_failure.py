"""D9.6.3 P2-1 — sync_notes.py 异常收窄(OperationalError 透传到外层 exit 3).

承接 D9.2 sync_notes.py(commit `1ec2caf` 沿袭)+ D3.3.3 教训(OperationalError 必透传):

2 个核心测试:
    T1. test_cli_sync_per_note_db_lock_propagates_to_exit_3
        sync 模式 + NoteStore.insert 抛 OperationalError → 整批记 exit 3(技术失败),
        不计入 failed_items(透传,不是业务失败)
    T2. test_cli_spike_per_note_db_lock_propagates_to_exit_3
        spike 模式 + NoteStore.insert 抛 OperationalError → 整批记 exit 3(同上)

设计原则(沿 tests/scripts/test_sync_notes.py 范本 + D3.3.3 教训):
    - 直接 import main()(不 subprocess,避免 SQLCipher 加密 DB 问题)
    - mock Database.open 走 plain sqlite(测试环境,沿 D6.4 范本)
    - mock NoteStore 让 insert 抛 OperationalError(模拟 DB 锁)
    - sync 模式还要 mock NotesConnector.list_all_notes() 返回 fake notes(让 per-note loop 跑)
    - spike 模式不需要 mock connector(不走 AppleScript)

D9.6.3 P2-1 修复链路(原 bug):
    - 旧:per-note `except Exception` 把 OperationalError 算成业务失败(进 failed_items,exit 2)
    - 新:`except OperationalError: raise` 透传 → 外层 `except OperationalError` 收 → exit 3
    - 兜底:per-note `except (ValueError, TypeError)` 才是真业务失败(进 failed_items,exit 2)
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# ===== 测试 fixture 工厂(沿 test_sync_notes.py 范本)=====

# alembic 校验需要 0008_notes(对应 notes 表已建)
_NOTES_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        apple_note_id TEXT NOT NULL,
        folder TEXT NOT NULL DEFAULT 'Notes',
        title TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        attachments_json TEXT,
        is_private INTEGER NOT NULL DEFAULT 0,
        tags TEXT,
        synced_at_ms INTEGER NOT NULL,
        updated_at_ms INTEGER NOT NULL,
        UNIQUE(apple_note_id)
    )
"""


def _make_pretend_alembic_notes_db(db_path: Path, revision: str = "0008_notes") -> None:
    """建临时 SQLite + alembic_version + notes 表(沿 test_sync_notes.py 范本)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        conn.execute("DELETE FROM alembic_version")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))
        conn.execute(_NOTES_TABLE_DDL)
        conn.commit()
    finally:
        conn.close()


class _FakeDatabase:
    """Mock Database — 只提供 close()."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def close(self) -> None:
        pass


def _build_fake_note_store_that_locks(*, mode: str) -> MagicMock:
    """Mock NoteStore —— find_by_apple_id 返 None(L1 不命中)+ insert 抛 OperationalError.

    Args:
        mode: "sync" 或 "spike" — 决定 insert 抛异常的次数(都是无限抛,跑到 except 即透传)
    """
    fake_store = MagicMock()
    fake_store.find_by_apple_id.return_value = None
    fake_store.insert.side_effect = OperationalError(
        "simulated DB lock", params=None, orig=Exception("test lock")
    )
    return fake_store


def _build_fake_connector() -> MagicMock:
    """Mock NotesConnector —— list_all_notes() 返回 1 条 fake note + get_note_body 返合法 HTML.

    关键:get_note_body() 必返回合法 HTML str,否则 clean_notes_html() 严判 MagicMock
    抛 TypeError,先于 store.insert 抛,测不到 OperationalError 透传路径。
    """
    fake_connector = MagicMock()
    fake_connector.list_all_notes.return_value = [
        {
            "apple_note_id": "x-coredata://ICNote/TEST",
            "folder": "Notes",
            "title": "Test Note",
            "is_private": False,
            "modified_at_ms": 1750000000000,
        }
    ]
    fake_connector.get_note_body.return_value = "<p>Test body</p>"
    return fake_connector


def _run_cli_with_db_lock(
    db_path: Path,
    argv: list[str],
    *,
    mode: str,
) -> int:
    """跑 sync_notes.main,Database.open + make_sqlalchemy_engine + NoteStore 都用 mock.

    NoteStore.insert 抛 OperationalError 模拟 DB 锁。
    """
    from sqlalchemy import create_engine

    from scripts import sync_notes  # noqa: PLC0415

    fake_db = _FakeDatabase(db_path)
    plain_engine = create_engine(f"sqlite:///{db_path}")
    fake_store = _build_fake_note_store_that_locks(mode=mode)

    with (
        patch.object(sync_notes, "Database") as mock_db_class,
        patch.object(sync_notes, "make_sqlalchemy_engine", return_value=plain_engine),
        patch.object(sync_notes, "NoteStore", return_value=fake_store),
    ):
        mock_db_class.open.return_value = fake_db
        if mode == "sync":
            # sync 模式需要 mock connector,否则真跑 AppleScript 失败
            fake_connector = _build_fake_connector()
            with patch.object(sync_notes, "NotesConnector", return_value=fake_connector):
                return sync_notes.main(argv)
        # spike 模式不需要 connector
        return sync_notes.main(argv)


# ===== T1. sync 模式 per-note DB 锁 → exit 3 =====


def test_cli_sync_per_note_db_lock_propagates_to_exit_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D9.6.3 P2-1:T1 sync 模式 + NoteStore.insert 抛 OperationalError → 整批 exit 3.

    关键断言:
        - exit code == 3(技术失败,不是业务失败 2)
        - stderr 含 "数据库技术失败" 标识
        - failed_items 必不出现(透传路径,不进业务失败列表)
    """
    db = tmp_path / "sync_lock.db"
    _make_pretend_alembic_notes_db(db)
    rc = _run_cli_with_db_lock(db, ["sync"], mode="sync")
    captured = capsys.readouterr()
    assert rc == 3, (
        f"per-note OperationalError 应透传到 exit 3(技术失败),"
        f"实际 {rc}\nstdout={captured.out}\nstderr={captured.err}"
    )
    assert "数据库技术失败" in captured.err
    # 关键:OperationalError 必透传,不计入 failed_items
    assert "failed_item" not in captured.err, (
        f"OperationalError 透传,不该进 failed_items,实际 stderr={captured.err}"
    )


# ===== T2. spike 模式 per-note DB 锁 → exit 3 =====


def test_cli_spike_per_note_db_lock_propagates_to_exit_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D9.6.3 P2-1:T2 spike 模式 + NoteStore.insert 抛 OperationalError → 整批 exit 3.

    关键断言(与 T1 同构):
        - exit code == 3(技术失败)
        - stderr 含 "数据库技术失败" 标识
        - spike failed: 必不出现(透传路径)
    """
    db = tmp_path / "spike_lock.db"
    _make_pretend_alembic_notes_db(db)
    rc = _run_cli_with_db_lock(db, ["spike", "--n", "3"], mode="spike")
    captured = capsys.readouterr()
    assert rc == 3, (
        f"spike per-note OperationalError 应透传到 exit 3,"
        f"实际 {rc}\nstdout={captured.out}\nstderr={captured.err}"
    )
    assert "数据库技术失败" in captured.err
    # 关键:spike failed: 必不出现(OperationalError 透传,不是 spike 业务失败)
    assert "spike failed" not in captured.err, (
        f"OperationalError 透传,不该算 spike failed,实际 stderr={captured.err}"
    )
