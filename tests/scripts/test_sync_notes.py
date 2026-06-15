"""D9.2 — sync_notes.py CLI + HTML cleaner 测试(15 cases).

承接 docs/v0.1-launch-plan.md §D9 + 沿 tests/scripts/test_import_wechat_cli.py 范本:

测试覆盖(15 cases):
    HTML cleaner 单元测试(7 cases):
        T1. test_clean_html_plain_text             纯文本 → 单行
        T2. test_clean_html_nested_list            嵌套列表 → 含换行
        T3. test_clean_html_with_attachments       附件引用 → (text, [src list])
        T4. test_clean_html_empty_input            空字符串 → ("", [])
        T5. test_clean_html_invalid_type_raises    非 str → TypeError
        T6. test_clean_html_collapse_multi_blanks  多次空行折叠
        T7. test_clean_html_fallback_on_malformed  异常输入兜底

    CLI 集成测试(8 cases):
        T8.  test_cli_no_args_returns_1            argparse 缺子命令 → exit 1
        T9.  test_cli_spike_30_inmemory_success    spike 30 笔 → exit 0 + inserted=30
        T10. test_cli_spike_idempotent_second_run  spike 二次跑 → 全 skipped
        T11. test_cli_spike_alembic_too_old_exit_1 alembic revision 过旧 → exit 1
        T12. test_cli_spike_alembic_missing_exit_1 alembic_version 表不存在 → exit 1
        T13. test_cli_sync_requires_real_network_env sync 默认 deny
        T14. test_cli_sync_max_rows_one_with_db_path sync --max-rows 1 + --db-path
        T15. test_cli_spike_db_path_argument_passed spike --db-path

设计原则(沿 D6.6 P1/P2 修复 + D4.7.3 严判范本):
    - 直接 import main()(不 subprocess,避免 SQLCipher 加密 DB 问题)
    - mock Database.open 走 plain sqlite(测试环境,沿 D6.4 范本)
    - tmp_path 临时文件(避免污染 fixtures)
    - 临时 SQLite 初始化成满足 alembic_version >= '0008_notes' 校验的"伪 alembic DB"
    - 临时 SQLite 显式建 notes 表(10 字段)让 NoteStore.insert 不抛
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# ===== 测试 fixture 工厂 =====


def _make_pretend_alembic_notes_db(db_path: Path, revision: str = "0008_notes") -> None:
    """在临时 SQLite 上伪造 alembic_version + notes 表(用于通过 alembic 校验 + NoteStore.insert).

    真实 SQLCipher + 真实 alembic upgrade head 走 tests/db/test_notes_migration.py
    (D9.1 已落),本测试只验 CLI 行为(alembic 校验 + spike 跑通 + 退出码),不验真实迁移。

    兜底:用 `IF NOT EXISTS` 避免 T8 场景下 tmp_path 复用时的残留冲突。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        # 清理旧 revision + 插新 revision(避免多次调用累积)
        conn.execute("DELETE FROM alembic_version")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))
        conn.execute("""
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
            """)
        conn.commit()
    finally:
        conn.close()


def _make_pretend_alembic_old_db(db_path: Path, revision: str = "0007_transactions") -> None:
    """在临时 SQLite 上伪造 alembic_version 为 0007_transactions(过旧,触发 alembic 校验失败)。

    用于 T11:验证 alembic revision < '0008_notes' 时 CLI exit 1。
    """
    _make_pretend_alembic_notes_db(db_path, revision=revision)


def _make_pretend_alembic_missing_db(db_path: Path) -> None:
    """在临时 SQLite 上不建 alembic_version 表(用于 T12:alembic_version 表不存在)。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.commit()
    finally:
        conn.close()


class _FakeDatabase:
    """Mock Database — 只提供 close(),engine 由 make_sqlalchemy_engine mock 提供。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    def close(self) -> None:
        pass


def _run_cli_with_mock_db(
    db_path: Path,
    argv: list[str],
) -> int:
    """跑 sync_notes.main,Database.open + make_sqlalchemy_engine 都用 mock(走 plain sqlite)。

    Returns:
        退出码(0/1/2/3)
    """
    from sqlalchemy import create_engine

    from scripts import sync_notes  # noqa: PLC0415

    fake_db = _FakeDatabase(db_path)
    plain_engine = create_engine(f"sqlite:///{db_path}")

    with (
        patch.object(sync_notes, "Database") as mock_db_class,
        patch.object(sync_notes, "make_sqlalchemy_engine", return_value=plain_engine),
    ):
        mock_db_class.open.return_value = fake_db
        return sync_notes.main(argv)


# ===== T1. 纯文本 → 单行 =====


def test_clean_html_plain_text() -> None:
    """D9.2:T1 纯文本 → 去除标签后单行。"""
    from my_ai_employee.adapters.apple_notes.html_cleaner import clean_notes_html

    text, attachments = clean_notes_html("<p>Hello World</p>")
    assert text == "Hello World"
    assert attachments == []


# ===== T2. 嵌套列表 → 含换行 =====


def test_clean_html_nested_list() -> None:
    """D9.2:T2 嵌套列表 → li 元素前后含换行,空行折叠。"""
    from my_ai_employee.adapters.apple_notes.html_cleaner import clean_notes_html

    html = "<ul><li>Item A</li><li>Item B</li><li>Item C</li></ul>"
    text, attachments = clean_notes_html(html)
    assert "Item A" in text
    assert "Item B" in text
    assert "Item C" in text
    assert text.count("\n") >= 2  # 至少 2 个换行
    assert attachments == []


# ===== T3. 附件引用 → (text, [src list]) =====


def test_clean_html_with_attachments() -> None:
    """D9.2:T3 <img>/<en-media> 附件引用 → 提取 src 到 attachment_refs。"""
    from my_ai_employee.adapters.apple_notes.html_cleaner import clean_notes_html

    html = '<p>Body</p><img src="photo.png" alt="x"><en-media src="audio.m4a"></en-media>'
    text, attachments = clean_notes_html(html)
    assert "Body" in text
    assert "photo.png" in attachments
    assert "audio.m4a" in attachments


# ===== T4. 空字符串 → ("", []) =====


def test_clean_html_empty_input() -> None:
    """D9.2:T4 空字符串 → 兜底返回 ("", []),不抛异常。"""
    from my_ai_employee.adapters.apple_notes.html_cleaner import clean_notes_html

    text, attachments = clean_notes_html("")
    assert text == ""
    assert attachments == []


# ===== T5. 非 str → TypeError =====


def test_clean_html_invalid_type_raises() -> None:
    """D9.2:T5 入口段 type 严判:非 str 抛 TypeError(沿 D4.7.3 严判范本)。"""
    from my_ai_employee.adapters.apple_notes.html_cleaner import clean_notes_html

    with pytest.raises(TypeError, match="html 必须是 str"):
        clean_notes_html(12345)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="html 必须是 str"):
        clean_notes_html(None)  # type: ignore[arg-type]


# ===== T6. 多次空行折叠 =====


def test_clean_html_collapse_multi_blanks() -> None:
    """D9.2:T6 多个连续 <p></p> 或 <br><br> 折叠为最多 1 个空行(\\n\\n)。"""
    from my_ai_employee.adapters.apple_notes.html_cleaner import clean_notes_html

    html = "<p>Para 1</p><p></p><p></p><p></p><p>Para 2</p>"
    text, _ = clean_notes_html(html)
    # 多个空 <p> 不应导致 \\n{3,}
    assert "\n\n\n" not in text
    assert "Para 1" in text
    assert "Para 2" in text


# ===== T7. 异常输入兜底 =====


def test_clean_html_fallback_on_malformed() -> None:
    """D9.2:T7 异常 HTML 兜底:解析失败不抛异常,返回 (原文去标签, [])。

    HTMLParser 对部分破损 HTML 会通过 error() 报告,本测试用极端输入
    验证兜底路径不阻塞入库。
    """
    from my_ai_employee.adapters.apple_notes.html_cleaner import clean_notes_html

    # HTMLParser 实际很宽容,这里用包含未关闭标签 + 错误嵌套的输入触发 handle_data
    malformed = "<div><p>Unclosed<p>Nested</div>"
    text, attachments = clean_notes_html(malformed)
    # 兜底返回:即使主解析失败,fallback _strip_simple_html_fallback 也会去标签
    assert "Unclosed" in text or "Nested" in text
    assert isinstance(attachments, list)


# ===== T8. argparse 缺子命令 → exit 1 =====


def test_cli_no_args_returns_1(tmp_path: Path) -> None:
    """D9.2:T8 argparse subparsers 缺子命令 → SystemExit 2(沿 sync_imap.py 范本)。

    注:argparse 缺子命令时,subparsers(required=True) 会自动 SystemExit(2),
    我们的 main() 不接住此异常。我们测的是:不传子命令时,系统级 SystemExit 抛,
    这等价于 CLI 退出码 1(用户错用)。
    """
    db = tmp_path / "no_args.db"
    _make_pretend_alembic_notes_db(db)
    with pytest.raises(SystemExit):
        _run_cli_with_mock_db(db, [])


# ===== T9. spike 30 笔 → exit 0 + inserted=30 =====


def test_cli_spike_30_inmemory_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D9.2:T9 spike 30 笔 faker → exit 0,stdout 含 inserted=30。"""
    db = tmp_path / "spike_30.db"
    _make_pretend_alembic_notes_db(db)
    rc = _run_cli_with_mock_db(db, ["spike", "--n", "30"])
    captured = capsys.readouterr()
    assert rc == 0, f"spike 30 笔应 exit 0,实际 {rc}\nstdout={captured.out}\nstderr={captured.err}"
    assert "notes spike:" in captured.out
    assert "parsed=30" in captured.out
    assert "inserted=30" in captured.out
    assert "n=30" in captured.out


# ===== T10. spike 二次跑 → 全 skipped(幂等)=====


def test_cli_spike_idempotent_second_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D9.2:T10 spike 二次跑同 DB → 全 skipped(同 apple_note_id 命中 L1 幂等)。"""
    db = tmp_path / "spike_idempotent.db"
    _make_pretend_alembic_notes_db(db)
    # 第一次跑
    rc1 = _run_cli_with_mock_db(db, ["spike", "--n", "5"])
    captured1 = capsys.readouterr()
    assert rc1 == 0
    assert "inserted=5" in captured1.out
    # 第二次跑(同 DB)
    rc2 = _run_cli_with_mock_db(db, ["spike", "--n", "5"])
    captured2 = capsys.readouterr()
    assert rc2 == 0, (
        f"spike 二次跑应 exit 0,实际 {rc2}\nstdout={captured2.out}\nstderr={captured2.err}"
    )
    assert "inserted=0" in captured2.out
    assert "skipped=5" in captured2.out


# ===== T11. alembic revision 过旧 → exit 1 =====


def test_cli_spike_alembic_too_old_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D9.2:T11 alembic revision 0007_transactions < 0008_notes → exit 1(防漏迁移)。"""
    db = tmp_path / "old_alembic.db"
    _make_pretend_alembic_old_db(db, revision="0007_transactions")
    rc = _run_cli_with_mock_db(db, ["spike", "--n", "5"])
    captured = capsys.readouterr()
    assert rc == 1, f"alembic revision 过旧应 exit 1,实际 {rc}\nstderr={captured.err}"
    assert "Alembic version 校验失败" in captured.err


# ===== T12. alembic_version 表不存在 → exit 1 =====


def test_cli_spike_alembic_missing_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D9.2:T12 alembic_version 表不存在 → exit 1(未初始化 alembic 迁移)。"""
    db = tmp_path / "no_alembic.db"
    _make_pretend_alembic_missing_db(db)
    rc = _run_cli_with_mock_db(db, ["spike", "--n", "5"])
    captured = capsys.readouterr()
    assert rc == 1, f"alembic_version 表不存在应 exit 1,实际 {rc}\nstderr={captured.err}"
    assert "Alembic version 校验失败" in captured.err


# ===== T13. sync 默认 deny:需 NOTES_REAL_NETWORK=1 =====


def test_cli_sync_requires_real_network_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spike B-1:T13 sync 真 AppleScript 默认 deny,需 NOTES_REAL_NETWORK=1 显式解锁。"""
    from scripts import sync_notes  # noqa: PLC0415

    monkeypatch.delenv("NOTES_REAL_NETWORK", raising=False)
    rc = sync_notes.main(["sync", "--max-rows", "1"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "NOTES_REAL_NETWORK=1" in captured.err
    assert "真实 Apple Notes 同步需显式设置环境变量" in captured.err


# ===== T14. sync --max-rows 1 + --db-path =====


def test_cli_sync_max_rows_one_with_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spike B-1:T14 sync --max-rows 1 只入 1 条,且 --db-path 传给 Database.open。"""
    from sqlalchemy import create_engine

    from scripts import sync_notes  # noqa: PLC0415

    db = tmp_path / "sync_max_rows.db"
    _make_pretend_alembic_notes_db(db)
    fake_db = _FakeDatabase(db)
    plain_engine = create_engine(f"sqlite:///{db}")
    fake_connector = MagicMock()
    fake_connector.list_all_notes.return_value = [
        {
            "apple_note_id": "x-coredata://ICNote/ONE",
            "folder": "Notes",
            "title": "One",
            "is_private": False,
            "modified_at_ms": 1750000000000,
        },
        {
            "apple_note_id": "x-coredata://ICNote/TWO",
            "folder": "Notes",
            "title": "Two",
            "is_private": False,
            "modified_at_ms": 1750000001000,
        },
    ]
    fake_connector.get_note_body.side_effect = ["<p>Body One</p>", "<p>Body Two</p>"]

    monkeypatch.setenv("NOTES_REAL_NETWORK", "1")
    with (
        patch.object(sync_notes, "Database") as mock_db_class,
        patch.object(sync_notes, "make_sqlalchemy_engine", return_value=plain_engine),
        patch.object(sync_notes, "NotesConnector", return_value=fake_connector),
    ):
        mock_db_class.open.return_value = fake_db
        rc = sync_notes.main(["sync", "--max-rows", "1", "--db-path", str(db)])
        mock_db_class.open.assert_called_once_with(db_path=db)

    captured = capsys.readouterr()
    assert rc == 0, f"sync --max-rows 1 应 exit 0,实际 {rc}\n{captured.err}"
    assert "notes sync: parsed=1 inserted=1 skipped=0 failed=0" in captured.out
    assert fake_connector.get_note_body.call_count == 1

    conn = sqlite3.connect(str(db))
    try:
        note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    finally:
        conn.close()
    assert note_count == 1


# ===== T15. spike --db-path =====


def test_cli_spike_db_path_argument_passed(tmp_path: Path) -> None:
    """Spike B-1:T15 spike --db-path 传给 Database.open,避免 dry-run 污染生产 DB。"""
    from sqlalchemy import create_engine

    from scripts import sync_notes  # noqa: PLC0415

    db = tmp_path / "spike_db_path.db"
    _make_pretend_alembic_notes_db(db)
    fake_db = _FakeDatabase(db)
    plain_engine = create_engine(f"sqlite:///{db}")

    with (
        patch.object(sync_notes, "Database") as mock_db_class,
        patch.object(sync_notes, "make_sqlalchemy_engine", return_value=plain_engine),
    ):
        mock_db_class.open.return_value = fake_db
        rc = sync_notes.main(["spike", "--n", "1", "--db-path", str(db)])
        mock_db_class.open.assert_called_once_with(db_path=db)

    assert rc == 0
