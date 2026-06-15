"""D9.1 — NotesConnector 适配器 + safe_parse + build_raw_note 测试(15 cases).

承接 D9(Apple Notes 同步 + ⌥⌘N 剪贴板结构化)+ 沿 D6 wechat_csv 测试范本。

5 段测试覆盖(15 cases):
    1. NotesConnector 初始化 + 注入 runner(3 tests)
    2. list_all_notes_metadata 解析 AppleScript 输出(4 tests)
    3. safe_parse 严判(4 tests) — 缺字段 / 类型错 / 范围错 / 业务错
    4. build_raw_note 构造 RawNote(2 tests)
    5. 失败隔离(2 tests) — osascript 失败 / timeout 抛 NotesConnectorError

D6 范本:
    - 沿 wechat_csv 测试范本:Runner Mock 注入
    - 失败隔离:单条解析失败不影响其他
    - AppleScript 中文 macOS 坑不直接测(测接口契约)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    pass


# ===== Fixtures =====


@pytest.fixture
def fake_runner():
    """Mock osascript runner(可注入测试场景输出)."""
    return lambda script: ""


@pytest.fixture
def notes_with_metadata() -> dict:
    """典型 AppleScript 元数据输出(2 条 notes)."""
    return {
        "script_output": (
            "{x-coredata://ICNote/A|Notes|笔记标题 A|0|Monday, June 15, 2026 at 10:00:00, "
            "x-coredata://ICNote/B|工作|工作笔记 B|1|2026-06-15T10:00:00}"
        ),
        "expected_count": 2,
        "expected_first": {
            "apple_note_id": "x-coredata://ICNote/A",
            "folder": "Notes",
            "title": "笔记标题 A",
            "is_private": False,
            "modified_at_ms": 1750000000000,  # 实际值由解析决定
        },
    }


# ===== 1. NotesConnector 初始化(3 tests)=====


def test_notes_connector_default_init() -> None:
    """1.1 NotesConnector 默认初始化(osascript 走系统, batch_size=100)."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    connector = NotesConnector()
    assert connector._batch_size == 100
    assert connector._runner is not None


def test_notes_connector_custom_runner_injection() -> None:
    """1.2 注入自定义 osascript runner(测试用 Mock)."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    def custom(script: str) -> str:
        return "mock_output"

    connector = NotesConnector(osascript_runner=custom, batch_size=50)
    assert connector._runner is custom
    assert connector._batch_size == 50


def test_notes_connector_rejects_non_callable_runner() -> None:
    """1.3 runner 非 callable → TypeError."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    with pytest.raises(TypeError, match="osascript_runner"):
        NotesConnector(osascript_runner="not_callable")  # type: ignore[arg-type]


# ===== 2. list_all_notes_metadata 解析(4 tests)=====


def test_parse_metadata_result_empty() -> None:
    """2.1 空 AppleScript 输出 → []."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    assert NotesConnector._parse_metadata_result("") == []
    assert NotesConnector._parse_metadata_result("   ") == []


def test_parse_metadata_result_single_note() -> None:
    """2.2 单条 note 解析(D9.6.2 协议:每行一条 + ASCII 30 字段间)."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    sep = chr(30)  # D9.6.2 P1-2: ASCII 30 (RS) 字段间分隔符
    # 新协议:每行一条 note,字段间 ASCII 30
    result_str = f"x-coredata://ICNote/A{sep}Notes{sep}笔记 A{sep}0{sep}2026-06-15T10:00:00\n"
    notes = NotesConnector._parse_metadata_result(result_str)
    assert len(notes) == 1
    assert notes[0]["apple_note_id"] == "x-coredata://ICNote/A"
    assert notes[0]["folder"] == "Notes"
    assert notes[0]["title"] == "笔记 A"
    assert notes[0]["is_private"] is False


def test_parse_metadata_result_multiple_notes() -> None:
    """2.3 多条 notes 解析(每行一条 + 失败隔离)."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    sep = chr(30)  # D9.6.2 P1-2: ASCII 30 (RS) 字段间分隔符
    # 新协议:每行一条 note,字段间 ASCII 30
    # 3 条:1 条空 ID(应跳过)+ 2 条正常
    result_str = (
        f"{sep}Notes{sep}空 ID{sep}0{sep}2026-06-15T10:00:00\n"
        f"x-coredata://ICNote/B{sep}工作{sep}工作笔记{sep}1{sep}2026-06-15T11:00:00\n"
        f"x-coredata://ICNote/C{sep}生活{sep}生活笔记{sep}0{sep}2026-06-15T12:00:00\n"
    )
    notes = NotesConnector._parse_metadata_result(result_str)
    # 3 条(空 ID 那条 apple_note_id 为空,_parse_metadata_line 返回 None)
    # 空 ID 视为占位跳过,剩 2 条
    assert len(notes) == 2
    ids = [n["apple_note_id"] for n in notes]
    assert "x-coredata://ICNote/B" in ids
    assert "x-coredata://ICNote/C" in ids


def test_parse_metadata_line_malformed() -> None:
    """2.4 metadata 行格式错误(段数 < 5) → NotesConnectorError."""
    from my_ai_employee.connectors.apple_notes import NotesConnector, NotesConnectorError

    sep = chr(30)
    with pytest.raises(NotesConnectorError, match="metadata 行格式错误"):
        NotesConnector._parse_metadata_line(f"id1{sep}folder1{sep}title1")  # 缺 2 段


# ===== 2.5-2.8 D9.6.2 P1-2 ASCII 30 分隔符 4 边界 case(避逗号/竖线/英文日期坑)=====


def test_parse_metadata_title_with_comma() -> None:
    """2.5 标题含逗号不被切(D9.6.2 新协议:无 list 元素,"," 不参与字段切)."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    sep = chr(30)
    result_str = (
        f"x-coredata://ICNote/A{sep}Notes{sep}Meeting, with, commas{sep}0{sep}2026-06-15T10:00:00\n"
    )
    notes = NotesConnector._parse_metadata_result(result_str)
    assert len(notes) == 1
    # 关键:title 含逗号不被切(因为新协议不再用 "," 切 list 元素,改用 ASCII 30 切字段)
    assert notes[0]["title"] == "Meeting, with, commas"


def test_parse_metadata_title_with_pipe() -> None:
    """2.6 标题含 | 不被切(ASCII 30 替代 | 作为字段间分隔符)."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    sep = chr(30)
    result_str = (
        f"x-coredata://ICNote/A{sep}Notes{sep}Pipe | in | title{sep}0{sep}2026-06-15T10:00:00\n"
    )
    notes = NotesConnector._parse_metadata_result(result_str)
    assert len(notes) == 1
    # 关键:title 含 | 不被切(因为字段间用 ASCII 30,不是 |)
    assert notes[0]["title"] == "Pipe | in | title"


def test_parse_metadata_english_date_locale() -> None:
    """2.7 英文 locale 日期 'Monday, June 15, 2026 at 14:30:00' 完整保留 + 真解析.

    D9.6.2 P1-2 修复:旧 list 拼接 + split(',') 会把 Monday, June 15... 拆碎,modified_at 段只剩
    'Monday' 后续 _parse_modified_at_ms 永远失败 → 兜底 0。本测试验证:
    1. modified_at 段必含完整英文日期字符串
    2. _parse_modified_at_ms 真解析(返回 > 0 ms,而非兜底 0)
    """
    from my_ai_employee.connectors.apple_notes import NotesConnector

    sep = chr(30)
    # AppleScript 默认英文 locale 输出格式
    en_date = "Monday, June 15, 2026 at 14:30:00"
    result_str = f"x-coredata://ICNote/A{sep}Notes{sep}test{sep}0{sep}{en_date}\n"
    notes = NotesConnector._parse_metadata_result(result_str)
    assert len(notes) == 1
    # 关键:modified_at_ms 必非 0(解析成功)
    assert notes[0]["modified_at_ms"] > 0, (
        f"英文日期未被真解析,modified_at_ms={notes[0]['modified_at_ms']}"
    )
    # 2026-06-15 14:30:00 UTC → 大约 1.78e12 ms
    import datetime

    expected = int(datetime.datetime(2026, 6, 15, 14, 30, 0).timestamp() * 1000)
    # 允许 ±1 小时时区误差(系统时区可能不是 UTC)
    assert abs(notes[0]["modified_at_ms"] - expected) < 3600 * 1000


def test_parse_metadata_multiple_notes_robust() -> None:
    """2.8 多条 notes 解析时,即使含逗号/竖线/英文日期 都不互相影响."""
    from my_ai_employee.connectors.apple_notes import NotesConnector

    sep = chr(30)
    en_date = "Monday, June 15, 2026 at 14:30:00"
    # 2 条 notes,各自含特殊字符(用 \n 分隔 notes,字段间用 ASCII 30)
    result_str = (
        f"x-coredata://ICNote/A{sep}Notes{sep}A, with comma{sep}0{sep}2026-06-15T10:00:00\n"
        f"x-coredata://ICNote/B{sep}Notes{sep}B | with | pipe{sep}0{sep}{en_date}\n"
    )
    notes = NotesConnector._parse_metadata_result(result_str)
    assert len(notes) == 2
    titles = sorted([n["title"] for n in notes])
    assert titles == ["A, with comma", "B | with | pipe"]
    # 第二条带英文日期,modified_at_ms 必非 0
    b_note = next(n for n in notes if n["apple_note_id"].endswith("/B"))
    assert b_note["modified_at_ms"] > 0


# ===== 3. safe_parse 严判(4 tests)=====


def test_safe_parse_happy_path() -> None:
    """3.1 safe_parse 合法 metadata dict → 严判通过."""
    from my_ai_employee.connectors.apple_notes import safe_parse

    meta = {
        "apple_note_id": "x-coredata://ICNote/OK",
        "folder": "Notes",
        "title": "OK 笔记",
        "is_private": False,
        "modified_at_ms": 1700000000000,
    }
    result = safe_parse(meta)
    assert result["apple_note_id"] == "x-coredata://ICNote/OK"
    assert result["is_private"] is False


def test_safe_parse_rejects_missing_fields() -> None:
    """3.2 safe_parse 缺字段 → ValueError."""
    from my_ai_employee.connectors.apple_notes import safe_parse

    meta = {
        "apple_note_id": "x-coredata://ICNote/OK",
        "folder": "Notes",
        # 缺 title / is_private / modified_at_ms
    }
    with pytest.raises(ValueError, match="缺字段"):
        safe_parse(meta)


def test_safe_parse_rejects_int_is_private() -> None:
    """3.3 safe_parse is_private=int 子类 → TypeError(bool 子类陷阱)."""
    from my_ai_employee.connectors.apple_notes import safe_parse

    meta = {
        "apple_note_id": "x-coredata://ICNote/OK",
        "folder": "Notes",
        "title": "t",
        "is_private": 1,  # type: ignore[dict-item]
        "modified_at_ms": 0,
    }
    with pytest.raises(TypeError, match="is_private"):
        safe_parse(meta)


def test_safe_parse_rejects_negative_modified_at_ms() -> None:
    """3.4 safe_parse modified_at_ms < 0 → ValueError."""
    from my_ai_employee.connectors.apple_notes import safe_parse

    meta = {
        "apple_note_id": "x-coredata://ICNote/OK",
        "folder": "Notes",
        "title": "t",
        "is_private": False,
        "modified_at_ms": -1,
    }
    with pytest.raises(ValueError, match="modified_at_ms"):
        safe_parse(meta)


# ===== 4. build_raw_note 构造(2 tests)=====


def test_build_raw_note_happy_path() -> None:
    """4.1 build_raw_note 从 metadata + body + attachments 构造 RawNote."""
    from my_ai_employee.connectors._types import RawNote
    from my_ai_employee.connectors.apple_notes import build_raw_note

    meta = {
        "apple_note_id": "x-coredata://ICNote/BUILD",
        "folder": "Notes",
        "title": "构造测试",
        "is_private": False,
        "modified_at_ms": 1700000000000,
    }
    raw = build_raw_note(meta, body="正文内容", attachments_json='[{"name":"x.png"}]')
    assert isinstance(raw, RawNote)
    assert raw.apple_note_id == "x-coredata://ICNote/BUILD"
    assert raw.body == "正文内容"
    assert raw.attachments_json == '[{"name":"x.png"}]'
    assert raw.is_private is False


def test_build_raw_note_rejects_non_str_body() -> None:
    """4.2 build_raw_note body 非 str → TypeError."""
    from my_ai_employee.connectors.apple_notes import build_raw_note

    meta = {
        "apple_note_id": "x-coredata://ICNote/BUILD2",
        "folder": "Notes",
        "title": "t",
        "is_private": False,
        "modified_at_ms": 0,
    }
    with pytest.raises(TypeError, match="body"):
        build_raw_note(meta, body=12345)  # type: ignore[arg-type]


# ===== 5. 失败隔离(2 tests)=====


def test_notes_connector_propagates_osascript_failure() -> None:
    """5.1 osascript 失败 → NotesConnectorError(非静默)."""
    from my_ai_employee.connectors.apple_notes import NotesConnector, NotesConnectorError

    def failing_runner(script: str) -> str:
        raise NotesConnectorError("mock osascript failure", original_error=Exception("test"))

    connector = NotesConnector(osascript_runner=failing_runner)
    with pytest.raises(NotesConnectorError, match="mock osascript failure"):
        connector.list_all_notes_metadata()


def test_notes_connector_propagates_subprocess_error(monkeypatch) -> None:
    """5.2 subprocess.run FileNotFoundError → NotesConnectorError."""
    from my_ai_employee.connectors.apple_notes import NotesConnector, NotesConnectorError

    # 模拟 osascript 不在 PATH
    def fake_run(*args, **kwargs):  # noqa: ARG001
        raise FileNotFoundError("osascript not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    connector = NotesConnector()
    with pytest.raises(NotesConnectorError, match="osascript 不在 PATH"):
        connector.list_all_notes_metadata()
