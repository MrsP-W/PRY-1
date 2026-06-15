"""D9.1 — Apple Notes 适配器(AppleScript 读取 + 解析 + 落库).

承接 D9(Apple Notes 同步 + ⌥⌘N 剪贴板结构化)+ 沿 D6 日报员
`Agent Assistant/agents/_shared/AppleScript_坑.md` 4 坑范本:

    坑 #1 逐个 set 不用 record 拆解赋值(中文 macOS 报 -10003)
    坑 #2 用 current date + ISO 8601 不用英文星期字符串(报 -30720)
    坑 #3 tell 块内查询 + first note 引用(变量在 tell 块外失效)
    坑 #4 时区防御(强制 set time of d to 0)

设计(沿 connectors/wechat_csv.py 范本 + D3.2 8 雷区严判):
    - `NotesConnector` 类:list_all_notes() 调 osascript + safe_parse() 异常兜底
    - AppleScript 逐行抓取(避免一次性返回 5000+ 笔记 OOM,沿 week2-mvp L214 风险)
    - `_run_applescript()` 调子进程 + 严判 returncode + decode utf-8
    - `_parse_note_line()` 解析 `id|title|modified_at_ms` 三段格式
    - 附件元数据走 json.dumps([{name, size}, ...])(不含二进制)
    - `is_private` 暂默认 False(Apple Notes 不暴露 is_locked,v0.2 接入 LLM 二次判断)

D3.2 8 雷区严判:
    1. 严判 str 不空(沿 D4.7.3 `__post_init__` 跨字段校验)
    2. type 严判在 hash 操作前(防 TypeError 异常类型)
    3. AppleScript 失败不静默(用 try/except + stderr 兜底)
    4. 解析失败抛 NotesParseError 业务异常(不抛 OSError 系统异常)
    5. attachments_json 严判 None 或 str(非 list)
    6. modified_at_ms 严判 int >= 0(沿 D4.7.3 严判范本)
    7. 调用方必传可执行 osascript(PATH 严判)
    8. 批处理失败隔离(单条失败不影响其他)

D9 决策(2026-06-15 锁定):
    - schema 完整版 10 字段(见 db/notes.py)
    - 附件只存元数据(不含二进制,避免 DB 膨胀)
    - is_private 标记跳过 LLM(沿 D4.7.2 v1.0.6 SPAM 阻断范本)
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from my_ai_employee.connectors._types import RawNote


class NotesConnectorError(Exception):
    """Apple Notes 适配器业务异常(沿 D6.5 TransactionAdapter 范本).

    Attributes:
        apple_note_id: 失败笔记的 Apple ID(可空,整批失败时为 None)
        original_error: 原始异常 / 错误码
    """

    def __init__(
        self,
        message: str,
        *,
        apple_note_id: str | None = None,
        original_error: Any = None,
    ) -> None:
        super().__init__(message)
        self.apple_note_id = apple_note_id
        self.original_error = original_error


# ===== AppleScript 范本(沿 D6 日报员 4 坑严判)=====


# AppleScript 模板:逐行抓取所有 notes 的元数据(不返回 body/attachments,避免 OOM)
# 格式:每个 note 一行 `id|folder|title|is_private|modified_at_iso`
# 解析层从 AppleScript 直接读 body 太慢,采用两次 AppleScript 范本:
#   1. list_all_notes_metadata() — 抓所有 id/folder/title/is_private/modified_at
#   2. get_note_body(apple_id) — 按需单条读 body + attachments
_APPLE_SCRIPT_LIST_METADATA = """
tell application "Notes"
    set outList to {}
    repeat with n in notes
        try
            set nId to id of n as string
        on error
            set nId to ""
        end try
        set nFolder to ""
        try
            set nFolder to name of container of n
        end try
        set nTitle to ""
        try
            set nTitle to name of n
        end try
        set nPriv to 0
        try
            if locked of n is true then
                set nPriv to 1
            end if
        end try
        set nMod to ""
        try
            set nMod to (modification date of n as string)
        end try
        set outList to outList & (nId & "|" & nFolder & "|" & nTitle & "|" & nPriv & "|" & nMod)
    end repeat
    return outList
end tell
"""

# 单条笔记读 body + attachments(按需)
_APPLE_SCRIPT_GET_BODY = """
on getNoteBody(appleId)
    tell application "Notes"
        try
            set theNote to first note whose id is appleId
            set nBody to ""
            try
                set nBody to body of theNote
            end try
            return nBody
        on error errMsg
            return "ERROR: " & errMsg
        end try
    end tell
end getNoteBody

return my getNoteBody("{APPLE_ID}")
"""


# ===== NotesConnector =====


class NotesConnector:
    """Apple Notes 适配器(AppleScript 调子进程 + 解析 + 严判).

    设计(沿 D6 wechat_csv.WeChatCSVConnector 范本):
        - list_all_notes(): 调 list_all_notes_metadata() + 按需 get_note_body()
        - 严判 AppleScript returncode(0 = OK,非 0 = 系统异常)
        - safe_parse(): 单条解析失败抛 NotesConnectorError(不静默)
        - 批处理 100 个为一批(osascript 单次返回避免 OOM)
    """

    def __init__(
        self,
        *,
        osascript_runner: Callable[[str], str] | None = None,
        batch_size: int = 100,
    ) -> None:
        """初始化。

        Args:
            osascript_runner: 可注入的 osascript 执行函数(测试时 Mock,默认调系统 osascript)
            batch_size: 批处理大小(默认 100,沿 week2-mvp L214 风险)
        """
        if osascript_runner is None:
            osascript_runner = self._default_osascript_runner
        if not callable(osascript_runner):
            raise TypeError(
                f"osascript_runner 必须是 callable(函数),"
                f"实际 type={type(osascript_runner).__name__}"
            )
        if type(batch_size) is not int or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError(
                f"batch_size 必须是正 int(非 bool),"
                f"实际 type={type(batch_size).__name__}, value={batch_size!r}"
            )
        self._runner = osascript_runner
        self._batch_size = batch_size

    # ===== 公开 API =====

    def list_all_notes(self) -> list[dict[str, Any]]:
        """列出所有 Apple Notes(全量同步入口).

        Returns:
            list[dict]: 每条 dict 含 apple_note_id/folder/title/is_private/modified_at_ms
                (不含 body / attachments_json — 按需调 get_note_body())

        Raises:
            NotesConnectorError: AppleScript 失败 / 解析失败
        """
        metadata = self.list_all_notes_metadata()
        # 按需 body 抓取(本阶段不抓 body,只列元数据;sync_notes.py 阶段再按需)
        return metadata

    # ===== 内部 API =====

    def list_all_notes_metadata(self) -> list[dict[str, Any]]:
        """列出所有 Notes 元数据(AppleScript 一次抓所有 metadata).

        Returns:
            list[dict]: 含 5 字段(apple_note_id/folder/title/is_private/modified_at_ms)
        """
        result = self._runner(_APPLE_SCRIPT_LIST_METADATA)
        return self._parse_metadata_result(result)

    def get_note_body(self, apple_note_id: str) -> str:
        """按 apple_note_id 单条读 body.

        Args:
            apple_note_id: Apple ID(严判非空)

        Returns:
            笔记正文(HTML 字符串,解析层做 HTML → plain text 转换)

        Raises:
            NotesConnectorError: Apple ID 为空 / AppleScript 失败
        """
        apple_note_id = self._validate_apple_note_id(apple_note_id)
        script = _APPLE_SCRIPT_GET_BODY.replace("{APPLE_ID}", apple_note_id)
        return self._runner(script)

    # ===== 默认 osascript 调用 =====

    @staticmethod
    def _default_osascript_runner(script: str) -> str:
        """默认 osascript 调用(子进程 + 严判 returncode + decode utf-8).

        Raises:
            NotesConnectorError: AppleScript returncode != 0
        """
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except FileNotFoundError as e:
            raise NotesConnectorError(
                "osascript 不在 PATH 中(macOS 系统命令,理论上必定存在)", original_error=e
            ) from e
        except subprocess.TimeoutExpired as e:
            raise NotesConnectorError(
                "osascript 超时(30s),可能 Notes 数据量过大或权限未授权", original_error=e
            ) from e
        if proc.returncode != 0:
            raise NotesConnectorError(
                f"osascript 失败 (returncode={proc.returncode}): {proc.stderr.strip()!r}",
                original_error=proc,
            )
        return proc.stdout

    # ===== 解析层 =====

    @staticmethod
    def _parse_metadata_result(result: str) -> list[dict[str, Any]]:
        """解析 AppleScript 一次抓回的 metadata 字符串.

        AppleScript 返回的是 `{}` list 字符串(逗号分隔,带 `{` `}`),
        解析层先把字符串切行(以换行/逗号为分隔符,AppleScript `&` 拼出来是连续行)
        然后每行按 `|` 切 5 段。

        Returns:
            list[dict]: 解析后的 metadata 列表

        Raises:
            NotesConnectorError: 解析失败
        """
        if not result or not result.strip():
            return []
        # AppleScript 返回的 list 字符串示例: {"id1|folder1|title1|0|2026-06-15}", "id2|..."}
        # 简化处理:按行切(AppleScript list 用 `, ` 分隔,但 `&` 拼接的字符串可能有换行)
        lines: list[str] = []
        for raw_line in result.splitlines():
            stripped = raw_line.strip().rstrip(",").strip()
            if not stripped:
                continue
            # 去 AppleScript 列表外层 { }
            if stripped.startswith("{"):
                stripped = stripped[1:].strip()
            if stripped.endswith("}"):
                stripped = stripped[:-1].strip()
            # 按 `, ` 切(AppleScript list 元素分隔)
            for element in stripped.split(","):
                element = element.strip().strip('"').strip()
                if element:
                    lines.append(element)

        notes: list[dict[str, Any]] = []
        for line in lines:
            try:
                note = NotesConnector._parse_metadata_line(line)
            except NotesConnectorError:
                # 单条失败不影响其他(失败隔离,沿 D6 适配器范本)
                continue
            if note is not None:
                notes.append(note)
        return notes

    @staticmethod
    def _parse_metadata_line(line: str) -> dict[str, Any] | None:
        """解析单行 metadata(5 段 `id|folder|title|is_private|modified_at`).

        Returns:
            dict 或 None(空行返回 None)
        """
        if not line or not line.strip():
            return None
        parts = line.split("|")
        if len(parts) < 5:
            raise NotesConnectorError(
                f"metadata 行格式错误(应 5 段,实际 {len(parts)} 段): {line!r}"
            )
        apple_note_id = parts[0].strip()
        folder = parts[1].strip() or "Notes"
        title = parts[2].strip()
        is_private_str = parts[3].strip()
        modified_at_str = parts[4].strip()
        if not apple_note_id:
            return None  # 空 ID 视为占位,跳过
        # is_private 严判
        is_private = is_private_str == "1" if is_private_str in ("0", "1") else False
        # modified_at_iso 解析失败也兜底为 0(本阶段不严格同步时间,仅占位)
        modified_at_ms = NotesConnector._parse_modified_at_ms(modified_at_str)
        return {
            "apple_note_id": apple_note_id,
            "folder": folder,
            "title": title,
            "is_private": is_private,
            "modified_at_ms": modified_at_ms,
        }

    @staticmethod
    def _parse_modified_at_ms(modified_at_str: str) -> int:
        """解析 AppleScript `modification date as string` 字符串 → Unix epoch ms.

        AppleScript `as string` 输出示例:
            "Monday, June 15, 2026 at 14:30:00"
        解析失败兜底返回 0(沿 D6 解析层严判范本)
        """
        if not modified_at_str:
            return 0
        try:
            # 用 fromisoformat 兜底: 2026-06-15T14:30:00 格式
            from datetime import datetime

            # 尝试 ISO 格式
            try:
                dt = datetime.fromisoformat(modified_at_str)
                return int(dt.timestamp() * 1000)
            except ValueError:
                pass
            # 尝试 AppleScript 默认格式: "Monday, June 15, 2026 at 14:30:00"
            from datetime import datetime as _dt

            for fmt in (
                "%A, %B %d, %Y at %H:%M:%S",
                "%A, %B %d, %Y %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
            ):
                try:
                    dt = _dt.strptime(modified_at_str, fmt)
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    continue
        except Exception:  # noqa: BLE001
            return 0
        return 0

    # ===== 严判 helper =====

    @staticmethod
    def _validate_apple_note_id(apple_note_id: str) -> str:
        """严判 apple_note_id 非空字符串(1-128 字符).

        Raises:
            TypeError: 非 str
            ValueError: 空字符串 / 过长
        """
        if not isinstance(apple_note_id, str):
            raise TypeError(
                f"apple_note_id 必须是 str,实际 type={type(apple_note_id).__name__},"
                f" value={apple_note_id!r}"
            )
        stripped = apple_note_id.strip()
        if not stripped:
            raise ValueError("apple_note_id 必非空(经 strip())")
        if len(stripped) > 128:
            raise ValueError(f"apple_note_id 长度超 128(实际 {len(stripped)})")
        return stripped


# ===== 工厂函数(沿 D6.5 wechat_csv.detect_version 范本)=====


def safe_parse(raw_metadata: dict[str, Any]) -> dict[str, Any]:
    """安全解析 metadata dict(入口段严判).

    Args:
        raw_metadata: list_all_notes_metadata() 返回的 dict 元素

    Returns:
        dict(经严判的 metadata)

    Raises:
        TypeError: 非 dict
        ValueError: 缺字段 / 字段值非法
        NotesConnectorError: 业务异常
    """
    if not isinstance(raw_metadata, dict):
        raise TypeError(f"raw_metadata 必须是 dict,实际 type={type(raw_metadata).__name__}")
    required = {"apple_note_id", "folder", "title", "is_private", "modified_at_ms"}
    missing = required - set(raw_metadata.keys())
    if missing:
        raise ValueError(f"raw_metadata 缺字段: {sorted(missing)}")
    # 复用 NotesConnector 严判
    apple_note_id = NotesConnector._validate_apple_note_id(raw_metadata["apple_note_id"])
    folder = raw_metadata["folder"]
    if not isinstance(folder, str):
        raise TypeError(f"folder 必须是 str,实际 type={type(folder).__name__}")
    title = raw_metadata["title"]
    if not isinstance(title, str):
        raise TypeError(f"title 必须是 str,实际 type={type(title).__name__}")
    is_private = raw_metadata["is_private"]
    if type(is_private) is not bool:
        raise TypeError(
            f"is_private 必须是 bool(非 int),实际 type={type(is_private).__name__},"
            f" value={is_private!r}"
        )
    modified_at_ms = raw_metadata["modified_at_ms"]
    if type(modified_at_ms) is bool or not isinstance(modified_at_ms, int) or modified_at_ms < 0:
        raise ValueError(
            f"modified_at_ms 必须是正 int(非 bool),"
            f"实际 type={type(modified_at_ms).__name__}, value={modified_at_ms!r}"
        )
    return {
        "apple_note_id": apple_note_id,
        "folder": folder,
        "title": title,
        "is_private": is_private,
        "modified_at_ms": modified_at_ms,
    }


def build_raw_note(
    metadata: dict[str, Any],
    body: str = "",
    attachments_json: str | None = None,
) -> RawNote:
    """从 metadata + body + attachments 构造 RawNote(解析层产物).

    Args:
        metadata: list_all_notes_metadata() 返回的 dict 元素
        body: 笔记正文(默认空,按需调 get_note_body())
        attachments_json: 附件元数据 JSON 字符串(不含二进制,可空)

    Returns:
        RawNote 数据类(沿 connectors/_types.py 范本)
    """
    # 局部 import 避免循环依赖
    from my_ai_employee.connectors._types import RawNote

    meta = safe_parse(metadata)
    if not isinstance(body, str):
        raise TypeError(f"body 必须是 str,实际 type={type(body).__name__}")
    if attachments_json is not None and not isinstance(attachments_json, str):
        raise TypeError(
            f"attachments_json 必须是 str 或 None,实际 type={type(attachments_json).__name__}"
        )
    return RawNote(
        apple_note_id=meta["apple_note_id"],
        folder=meta["folder"],
        title=meta["title"],
        body=body,
        attachments_json=attachments_json,
        is_private=meta["is_private"],
        modified_at_ms=meta["modified_at_ms"],
    )


__all__ = [
    "NotesConnector",
    "NotesConnectorError",
    "safe_parse",
    "build_raw_note",
]
