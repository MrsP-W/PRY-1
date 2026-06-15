"""D9.6.1 — ClipboardCaptureService:⌥⌘N 剪贴板 → Notes 真链路业务层.

承接 D9.5 ⌥⌘N 全局快捷键 + D9.4 NoteStructurerService 三入口范本:
  - 沿 D4.7.3 v1.0.6 强一致契约:三入口(capture_and_emit / record_private_skip_and_emit
    / record_failure_and_emit)互斥返回 1 种决策报告
  - 复用 NoteStructurerService.structure_and_emit 走 LLM 链路(不重做 LLM 编排)
  - 复用 NoteStore.insert 落库(不重做 NoteStore)
  - clipboard_reader 注入:默认 pyperclip.paste,test 用 lambda 注入(避免真读剪贴板)

设计要点(2026-06-15 锁定):
  - ⌥⌘N 触发:读 pyperclip.paste() → 构造 clip_id (clipboard://{ts}-{token_hex(4)})
    → NoteStore.insert(写 raw 笔记) → NoteStructurerService.structure_and_emit(走 LLM)
  - clip_id 用 `clipboard://` 前缀,与 x-coredata:// 苹果笔记同构(沿 D9.1 范本)
  - 重复按 ⌥⌘N(同 ts 同 token hex 4) 概率 2^32,NoteDuplicateError 自然兜底
  - 空剪贴板 → record_failure_and_emit(reason="llm_failure", last_error="empty clipboard")
  - DB 锁 → record_failure_and_emit(reason="db_failure") 透传 OperationalError
  - LLM 失败 → structurer 内部 record_failure_and_emit(reason="llm_failure") 透传
  - 3 入口同构 D4.7.3:返回 3 类型联合,调用方 isinstance 区分

D4.7.3 v1.0.6 教训应用(2026-06-15 锁定):
  - 异常范围窄化: 显式 except (NoteDuplicateError, OperationalError, ValueError, TypeError)
  - 不静默吞 except: OperationalError 透传 → reason="db_failure" 走技术失败入口
  - 强一致: record_private_skip_and_emit 不计入 cf(consecutive_failures 不入参)
  - 复用 FailureDecisionReport(不新建 CaptureFailureReport 等),monitoring 字段一致

为什么不重建 LLM 链路: NoteStructurerService 已经有完整 8 步流程(查 note → 业务阻断
判别 → 构造 prompt → 调 LLM → 解析响应 → 写 tags → 落 events → 返回),clipboard_capture
只做"前置采集 + 落库"两步,把 note 喂给 structurer,避免双 LLM 编排导致双源不一致。

D9.6.1 决策(2026-06-15 锁定):
  - 决策 1: 复用 NoteStructurerService 三入口(不重建),clipboard_capture 主类只做
    "剪贴板→NoteStore→structurer" 编排 + 3 入口委派
  - 决策 2: 决策报告类型 = StructuredNote | PrivateSkipDecisionReport | FailureDecisionReport
    (3 类型联合,无 CaptureSuccessReport,统一复用 structurer 决策报告)
  - 决策 3: clipboard_reader 注入签名 `Callable[[], str]`,test 用 lambda 注入,
    默认 `pyperclip.paste`(添加 pyperclip>=1.8.2 依赖)
  - 决策 4: clip_id 格式 `clipboard://{ts}-{token_hex(4)}`,与 x-coredata:// 同构
  - 决策 5: body 上限 8000 字符(沿 _BODY_MAX_CHARS_AUDIT,与 structurer 2000 不同
    —— structurer 内部 prompts 截断到 2000 入 LLM,这里落库用 8000 防 note.body 撑爆)
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from typing import Any, Literal

import pyperclip
from loguru import logger
from sqlalchemy.exc import OperationalError

from my_ai_employee.ai.note_structurer import (
    FailureDecisionReport,
    NoteStructurerService,
    PrivateSkipDecisionReport,
    StructuredNote,
)
from my_ai_employee.db.notes import NoteDuplicateError, NoteStore

# ===== 业务常量 =====

# 决策报告 3 类型联合(沿 D4.7.3 v1.0.6 强一致契约)
CaptureReport = StructuredNote | PrivateSkipDecisionReport | FailureDecisionReport

# clip_id 前缀(与 D9.1 x-coredata:// 同构,主键 UNIQUE)
_CLIP_ID_PREFIX: str = "clipboard://"

# 剪贴板文本上限(落库用,与 structurer 入 LLM 2000 不同)
_BODY_MAX_CHARS: int = 8000

# 标题截断长度(NoteStore._validate_title 限 200,这里预截断到 50 字符)
_TITLE_MAX_CHARS: int = 50

# 失败 reason 白名单(沿 structurer 锁定枚举,扩需 B 类)
_FAILURE_REASONS: frozenset[str] = frozenset({"llm_failure", "db_failure"})

# 技术失败 reason 锁白名单(委派 structurer 时复用)
LiteralReason = Literal["llm_failure", "db_failure"]


# ===== 公共严判 helper(D4.7.3 v1.0.5 P1 范本:严判下沉到 helper)=====


def _validate_clip_id(clip_id: Any) -> str:
    """严判 clip_id 非空白 str(1-128 字符)且带 clipboard:// 前缀."""
    if type(clip_id) is not str:
        raise ValueError(
            f"clip_id 必须是 str, 实际 type={type(clip_id).__name__}, value={clip_id!r}"
        )
    stripped = clip_id.strip()
    if not stripped:
        raise ValueError(f"clip_id 必非空(经 strip()), 实际 {clip_id!r}")
    if not stripped.startswith(_CLIP_ID_PREFIX):
        raise ValueError(f"clip_id 必以 '{_CLIP_ID_PREFIX}' 开头, 实际 {stripped!r}")
    if len(stripped) > 128:
        raise ValueError(f"clip_id 长度超 128(实际 {len(stripped)})")
    return stripped


def _validate_clipboard_text(text: Any) -> str:
    """严判 clipboard text 必为 str(None 时返空串)."""
    if text is None:
        return ""
    if type(text) is not str:
        raise ValueError(f"clipboard text 必须是 str 或 None, 实际 type={type(text).__name__}")
    return text


# ===== 业务主类 =====


class ClipboardCaptureService:
    """D9.6.1 — ⌥⌘N 剪贴板 → Notes 业务编排服务.

    三入口契约(沿 D4.7.3 v1.0.6 强一致):
      - capture_and_emit() → CaptureReport(成功/业务阻断/技术失败 3 类型联合)
      - record_private_skip_and_emit(clip_id) → PrivateSkipDecisionReport(委派)
      - record_failure_and_emit(clip_id, exc, *, reason, consecutive_failures) → FailureDecisionReport(委派)

    业务流程(capture_and_emit):
      1. clipboard_reader() 读剪贴板 → text(可能空)
      2. text 为空 → record_failure_and_emit(reason="llm_failure", last_error="empty clipboard")
      3. 生成 clip_id = clipboard://{now_ms}-{secrets.token_hex(4)}
      4. NoteStore.insert(apple_note_id=clip_id, folder="clipboard", title=text[:50], body=text[:8000], is_private=False)
         - NoteDuplicateError: 重复按 ⌥⌘N,L1 幂等跳过,继续 structurer 走 LLM
         - OperationalError: record_failure_and_emit(reason="db_failure") 透传
         - ValueError: record_failure_and_emit(reason="db_failure") 严判失败
         - TypeError: 同上(防误传 None)
      5. 委派 structurer.structure_and_emit(clip_id) → CaptureReport

    Attributes:
        _store: NoteStore 实例(D9.1 必传)
        _structurer: NoteStructurerService 实例(D9.4 必传,沿用 3 依赖:store/llm/event)
        _reader: 剪贴板读取 callable(默认 pyperclip.paste,test 注入 lambda)
    """

    def __init__(
        self,
        *,
        store: NoteStore,
        structurer: NoteStructurerService,
        clipboard_reader: Callable[[], str] = pyperclip.paste,
    ) -> None:
        """初始化.

        Args:
            store: NoteStore 实例(必传,D9.1)
            structurer: NoteStructurerService 实例(必传,D9.4 3 依赖)
            clipboard_reader: 剪贴板读取 callable,默认 pyperclip.paste
        """
        if store is None:
            raise ValueError(f"store 必传非 None NoteStore, 实际 {type(store).__name__}")
        if structurer is None:
            raise ValueError(
                f"structurer 必传非 None NoteStructurerService, 实际 {type(structurer).__name__}"
            )
        if not callable(clipboard_reader):
            raise TypeError(
                f"clipboard_reader 必为 callable, 实际 type={type(clipboard_reader).__name__}"
            )
        self._store = store
        self._structurer = structurer
        self._reader = clipboard_reader

    # ===== 公共 helper =====

    @staticmethod
    def generate_clip_id() -> str:
        """生成唯一 clip_id: clipboard://{now_ms}-{secrets.token_hex(4)}.

        Returns:
            形如 `clipboard://1718438400000-3a2b1c4d` 的字符串

        Notes:
            - ts 用 now_ms 防止跨天冲突
            - token_hex(4) 8 hex chars = 2^32 熵,⌥⌘N 连按 1 万次/s 不撞
            - 双重 unique + NoteStore UNIQUE 约束,即使 8 hex 撞了也 L1 业务阻断兜底
        """
        ts_ms = int(time.time() * 1000)
        token = secrets.token_hex(4)
        return f"{_CLIP_ID_PREFIX}{ts_ms}-{token}"

    # ===== 3 入口 =====

    def capture_and_emit(self) -> CaptureReport:
        """主入口:读剪贴板 → 落 NoteStore → 委派 structurer 走 LLM.

        业务流程:
          1. 读剪贴板 → text(可能空)
          2. text 为空 → record_failure_and_emit("clipboard://empty", ValueError("empty"),
             reason="llm_failure", consecutive_failures=1)
          3. 生成 clip_id
          4. NoteStore.insert(raw 笔记)
             - NoteDuplicateError(L1 幂等):跳过 insert,继续 structurer
             - OperationalError(DB 锁):record_failure_and_emit(reason="db_failure")
             - ValueError / TypeError(严判失败):record_failure_and_emit(reason="db_failure")
          5. 委派 self._structurer.structure_and_emit(clip_id) → CaptureReport

        Returns:
            CaptureReport(3 类型联合):
                - StructuredNote(成功,6 字段契约自洽)
                - PrivateSkipDecisionReport(业务阻断,is_private=True 笔记)
                - FailureDecisionReport(技术失败,DB 锁 / LLM 失败 / 空剪贴板)

        Raises:
            ValueError: 编程错误(参数 type 错,透传不包装)
        """
        # 1. 读剪贴板
        try:
            raw_text = self._reader()
        except Exception as e:  # noqa: BLE001 — pyperclip 在 TCC 拒授权或剪切板为空时可能抛
            logger.error(f"[clipboard_capture] 读剪贴板失败 | err={type(e).__name__}: {e}")
            return self.record_failure_and_emit(
                f"{_CLIP_ID_PREFIX}read_error",
                e,
                reason="llm_failure",
                consecutive_failures=1,
            )

        # 2. 严判 + 空检查
        text = _validate_clipboard_text(raw_text)
        if not text.strip():
            logger.info("[clipboard_capture] 剪贴板为空,跳过 LLM")
            return self.record_failure_and_emit(
                f"{_CLIP_ID_PREFIX}empty",
                ValueError("empty clipboard"),
                reason="llm_failure",
                consecutive_failures=1,
            )

        # 3. 生成 clip_id
        clip_id = self.generate_clip_id()
        # 截断 title / body(防 audit 撑爆,沿 D4.7.3 v1.0.8 范本)
        title = text[:_TITLE_MAX_CHARS]
        body = text[:_BODY_MAX_CHARS]

        # 4. NoteStore.insert
        try:
            self._store.insert(
                apple_note_id=clip_id,
                folder="clipboard",
                title=title,
                body=body,
                updated_at_ms=int(time.time() * 1000),
                is_private=False,
                tags=None,
            )
        except NoteDuplicateError as e:
            # L1 幂等(极小概率,但兜底):跳过 insert,继续 structurer 走 LLM
            # structurer 会查 note → 找到 → 走 is_private 判别 → 走 LLM
            logger.warning(
                f"[clipboard_capture] L1 幂等(已同步过) | clip_id={clip_id}"
                f" | err={type(e).__name__}: {e}"
            )
        except (OperationalError, ValueError, TypeError) as e:
            # 透传 OperationalError(D3.3.3 教训)+ 严判失败 → 技术失败入口
            reason: LiteralReason = (
                "db_failure" if isinstance(e, OperationalError) else "db_failure"
            )
            logger.error(
                f"[clipboard_capture] NoteStore.insert 失败 | clip_id={clip_id}"
                f" | reason={reason} | err={type(e).__name__}: {e}"
            )
            return self.record_failure_and_emit(
                clip_id,
                e,
                reason=reason,
                consecutive_failures=1,
            )

        # 5. 委派 structurer 走 LLM
        return self._structurer.structure_and_emit(clip_id)

    def record_private_skip_and_emit(self, clip_id: str) -> PrivateSkipDecisionReport:
        """业务阻断入口(委派 structurer,沿 D4.7.3 v1.0.6 强一致).

        Args:
            clip_id: 剪贴板笔记 ID(必以 clipboard:// 开头)

        Returns:
            PrivateSkipDecisionReport(委派 structurer 内部 record_private_skip_and_emit)
        """
        clip_id = _validate_clip_id(clip_id)
        logger.info(f"[clipboard_capture] record_private_skip_and_emit | clip_id={clip_id}")
        return self._structurer.record_private_skip_and_emit(clip_id)

    def record_failure_and_emit(
        self,
        clip_id: str,
        exc: BaseException,
        *,
        reason: Literal["llm_failure", "db_failure"] = "llm_failure",
        consecutive_failures: int = 1,
    ) -> FailureDecisionReport:
        """技术失败入口(委派 structurer,沿 D4.7.3 v1.0.6 强一致).

        Args:
            clip_id: 剪贴板笔记 ID
            exc: 触发的异常
            reason: 失败原因类别(llm_failure / db_failure,锁定白名单)
            consecutive_failures: 连续失败次数(必填 >= 1, 默认 1)

        Returns:
            FailureDecisionReport(委派 structurer 内部 record_failure_and_emit)
        """
        clip_id = _validate_clip_id(clip_id)
        logger.error(
            f"[clipboard_capture] record_failure_and_emit | clip_id={clip_id}"
            f" | reason={reason} | cf={consecutive_failures}"
            f" | err={type(exc).__name__}: {str(exc)[:200]}"
        )
        return self._structurer.record_failure_and_emit(
            clip_id,
            exc,
            reason=reason,
            consecutive_failures=consecutive_failures,
        )


__all__ = [
    "CaptureReport",
    "ClipboardCaptureService",
]
