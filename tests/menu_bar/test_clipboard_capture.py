"""D9.6.1 — ClipboardCaptureService 测试(12 cases,沿 D4.7.3 v1.0.6 严判范本).

设计原则:
    - NoteStore + NoteStructurerService 全用 MagicMock 注入(不真连 DB / LLM)
    - clipboard_reader 用 lambda 注入(避免真读剪贴板)
    - 3 入口互斥返回 1 种决策报告:isinstance 区分
    - 严判类型契约(D4.7.3 v1.0.5/v1.0.6):type() is int 非 bool, type() is str 非 bytes 等
    - 严判失败路径 + 异常透传(D3.3.3):OperationalError 走 db_failure 入口
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from my_ai_employee.ai.note_structurer import (
    FailureDecisionReport,
    PrivateSkipDecisionReport,
    StructuredNote,
)
from my_ai_employee.db.notes import NoteDuplicateError
from my_ai_employee.menu_bar.clipboard_capture import (
    ClipboardCaptureService,
)

# ===== Fixtures =====


@pytest.fixture
def mock_store() -> MagicMock:
    """MagicMock 注入的 NoteStore(不真连 DB)."""
    return MagicMock(spec=["insert", "find_by_apple_id"])


@pytest.fixture
def mock_structurer() -> MagicMock:
    """MagicMock 注入的 NoteStructurerService(不真调 LLM).

    默认:
        - structure_and_emit 返回 StructuredNote 成功报告
        - record_failure_and_emit 用 side_effect 从入参构造真实 FailureDecisionReport
          (避免测试重复 boilerplate)
        - record_private_skip_and_emit 不设默认值(让 test 显式 return_value)
    """
    mock = MagicMock(
        spec=["structure_and_emit", "record_private_skip_and_emit", "record_failure_and_emit"]
    )
    mock.structure_and_emit.return_value = StructuredNote(
        apple_note_id="clipboard://1234-abcd",
        category="TODO",
        tags=["foo", "bar", "baz"],
        model_full_id="claude-haiku-4-5",
        latency_ms=123,
        body_length=42,
    )

    # record_failure_and_emit 用 side_effect 从入参构造真实 FailureDecisionReport
    # (沿 structurer 真实实现: last_error = str(exc)[:200], cf/reason 透传)
    def _build_failure(
        clip_id: str,
        exc: BaseException,
        *,
        reason: str = "llm_failure",
        consecutive_failures: int = 1,
    ) -> FailureDecisionReport:
        return FailureDecisionReport(
            apple_note_id=clip_id,
            last_error=str(exc)[:200],
            consecutive_failures=consecutive_failures,
            reason=reason,  # type: ignore[arg-type]
        )

    mock.record_failure_and_emit.side_effect = _build_failure
    return mock


@pytest.fixture
def fake_reader() -> Any:
    """返回固定文本的 lambda(替代 pyperclip.paste)."""
    return lambda: "Hello, this is a clipboard test content."


@pytest.fixture
def service(
    mock_store: MagicMock, mock_structurer: MagicMock, fake_reader: Any
) -> ClipboardCaptureService:
    """完整注入的 ClipboardCaptureService."""
    return ClipboardCaptureService(
        store=mock_store, structurer=mock_structurer, clipboard_reader=fake_reader
    )


# ===== T01-T03: __init__ 严判 =====


def test_init_raises_on_none_store(mock_structurer: MagicMock, fake_reader: Any) -> None:
    """T01: store=None → ValueError(沿 D4.7.3 严判范本)."""
    with pytest.raises(ValueError, match="store 必传非 None NoteStore"):
        ClipboardCaptureService(
            store=None,  # type: ignore[arg-type]
            structurer=mock_structurer,
            clipboard_reader=fake_reader,
        )


def test_init_raises_on_none_structurer(mock_store: MagicMock, fake_reader: Any) -> None:
    """T02: structurer=None → ValueError."""
    with pytest.raises(ValueError, match="structurer 必传非 None NoteStructurerService"):
        ClipboardCaptureService(
            store=mock_store,
            structurer=None,  # type: ignore[arg-type]
            clipboard_reader=fake_reader,
        )


def test_init_raises_on_non_callable_reader(
    mock_store: MagicMock, mock_structurer: MagicMock
) -> None:
    """T03: clipboard_reader 非 callable → TypeError."""
    with pytest.raises(TypeError, match="clipboard_reader 必为 callable"):
        ClipboardCaptureService(
            store=mock_store,
            structurer=mock_structurer,
            clipboard_reader="not_callable",  # type: ignore[arg-type]
        )


# ===== T04: generate_clip_id 格式 =====


def test_generate_clip_id_format(service: ClipboardCaptureService) -> None:
    """T04: generate_clip_id 必以 'clipboard://' 开头 + ts-hex4 格式."""
    clip_id = service.generate_clip_id()
    assert clip_id.startswith("clipboard://")
    # 后缀形如 {ts_ms}-{token_hex(4)},token_hex(4) = 8 hex chars
    suffix = clip_id[len("clipboard://") :]
    parts = suffix.split("-")
    assert len(parts) == 2
    assert parts[0].isdigit()  # ts_ms
    assert len(parts[1]) == 8  # token_hex(4) = 8 hex
    assert all(c in "0123456789abcdef" for c in parts[1])
    # 2 次调用必 unique(token_hex 4 熵 2^32)
    clip_id_2 = service.generate_clip_id()
    assert clip_id != clip_id_2


# ===== T05-T06: 空剪贴板 / 纯空白 =====


def test_capture_empty_clipboard_returns_failure(
    service: ClipboardCaptureService, mock_structurer: MagicMock
) -> None:
    """T05: 剪贴板空字符串 → FailureDecisionReport(reason='llm_failure')."""
    service._reader = lambda: ""
    result = service.capture_and_emit()
    assert isinstance(result, FailureDecisionReport)
    assert result.reason == "llm_failure"
    assert "empty clipboard" in result.last_error
    # structurer 不应被调
    mock_structurer.structure_and_emit.assert_not_called()


def test_capture_whitespace_only_returns_failure(
    service: ClipboardCaptureService, mock_structurer: MagicMock
) -> None:
    """T06: 剪贴板纯空白(空格/Tab/换行) → FailureDecisionReport(同空)."""
    service._reader = lambda: "   \n\t  "
    result = service.capture_and_emit()
    assert isinstance(result, FailureDecisionReport)
    assert result.reason == "llm_failure"
    assert "empty clipboard" in result.last_error
    mock_structurer.structure_and_emit.assert_not_called()


# ===== T07: 成功路径 =====


def test_capture_success_delegates_to_structurer(
    service: ClipboardCaptureService,
    mock_store: MagicMock,
    mock_structurer: MagicMock,
    fake_reader: Any,
) -> None:
    """T07: 正常剪贴板 → NoteStore.insert + structurer.structure_and_emit → 返回 structurer 结果."""
    result = service.capture_and_emit()
    # NoteStore.insert 被调 1 次
    mock_store.insert.assert_called_once()
    call_kwargs = mock_store.insert.call_args.kwargs
    assert call_kwargs["folder"] == "clipboard"
    assert call_kwargs["is_private"] is False
    assert call_kwargs["apple_note_id"].startswith("clipboard://")
    assert call_kwargs["body"] == fake_reader()
    # structurer.structure_and_emit 被调 1 次,参数是 insert 的 clip_id
    mock_structurer.structure_and_emit.assert_called_once()
    called_clip_id = mock_structurer.structure_and_emit.call_args.args[0]
    assert called_clip_id == call_kwargs["apple_note_id"]
    # 返回值是 structurer.structure_and_emit 的返回值
    assert result is mock_structurer.structure_and_emit.return_value
    assert isinstance(result, StructuredNote)
    assert result.category == "TODO"


# ===== T08: NoteDuplicateError L1 幂等 =====


def test_capture_duplicate_id_continues_to_structurer(
    service: ClipboardCaptureService,
    mock_store: MagicMock,
    mock_structurer: MagicMock,
) -> None:
    """T08: NoteStore.insert 抛 NoteDuplicateError(L1 幂等)→ 不阻断,继续 structurer."""
    mock_store.insert.side_effect = NoteDuplicateError("duplicate", apple_note_id="clipboard://x")
    result = service.capture_and_emit()
    # structurer 仍被调
    mock_structurer.structure_and_emit.assert_called_once()
    assert isinstance(result, StructuredNote)


# ===== T09: OperationalError 走 db_failure =====


def test_capture_operational_error_returns_db_failure(
    service: ClipboardCaptureService,
    mock_store: MagicMock,
    mock_structurer: MagicMock,
) -> None:
    """T09: NoteStore.insert 抛 OperationalError(DB 锁)→ FailureDecisionReport(db_failure)."""
    mock_store.insert.side_effect = OperationalError("simulated DB lock", None, Exception())
    result = service.capture_and_emit()
    assert isinstance(result, FailureDecisionReport)
    assert result.reason == "db_failure"
    # structurer 不被调
    mock_structurer.structure_and_emit.assert_not_called()


# ===== T10: reader 抛异常 =====


def test_capture_reader_raises_returns_failure(
    service: ClipboardCaptureService, mock_structurer: MagicMock
) -> None:
    """T10: pyperclip 抛异常(TCC 拒 / 剪贴板无权限)→ FailureDecisionReport(llm_failure)."""

    def _raise() -> str:
        raise RuntimeError("clipboard access denied")

    service._reader = _raise
    result = service.capture_and_emit()
    assert isinstance(result, FailureDecisionReport)
    assert result.reason == "llm_failure"
    assert "clipboard access denied" in result.last_error
    mock_structurer.structure_and_emit.assert_not_called()


# ===== T11: record_private_skip_and_emit 委派 =====


def test_record_private_skip_delegates(
    service: ClipboardCaptureService, mock_structurer: MagicMock
) -> None:
    """T11: record_private_skip_and_emit → 委派 structurer,带正确 clip_id."""
    expected = PrivateSkipDecisionReport(apple_note_id="clipboard://x-y")
    mock_structurer.record_private_skip_and_emit.return_value = expected
    result = service.record_private_skip_and_emit("clipboard://x-y")
    assert result is expected
    mock_structurer.record_private_skip_and_emit.assert_called_once_with("clipboard://x-y")


def test_record_private_skip_validates_clip_id(
    service: ClipboardCaptureService,
) -> None:
    """T11b: record_private_skip_and_emit 严判 clip_id 必 clipboard:// 前缀."""
    with pytest.raises(ValueError, match="clip_id 必以 'clipboard://' 开头"):
        service.record_private_skip_and_emit("not_clipboard://x")


# ===== T12: record_failure_and_emit 委派 + kw 透传 =====


def test_record_failure_delegates_with_kwargs(
    service: ClipboardCaptureService, mock_structurer: MagicMock
) -> None:
    """T12: record_failure_and_emit → 委派 structurer,reason / consecutive_failures 透传.

    注:fixture 的 side_effect 会从入参构造真实 FailureDecisionReport,所以验字段而非对象同一性.
    """
    exc = OperationalError("boom", None, Exception())
    result = service.record_failure_and_emit(
        "clipboard://x-y", exc, reason="db_failure", consecutive_failures=3
    )
    assert isinstance(result, FailureDecisionReport)
    assert result.apple_note_id == "clipboard://x-y"
    assert result.reason == "db_failure"
    assert result.consecutive_failures == 3
    assert "boom" in result.last_error
    # 验证委派调用的 kwargs 透传
    mock_structurer.record_failure_and_emit.assert_called_once_with(
        "clipboard://x-y", exc, reason="db_failure", consecutive_failures=3
    )
