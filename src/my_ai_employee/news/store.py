"""AI 每日情报本地缓存。

缓存位于 Application Support，避免 launchd 进程直接写入 Documents/iCloud 同步目录。
写入使用同目录原子替换；刷新全失败时由上层保留上一份可用快照。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator, Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_RUN_OUTCOMES = frozenset({"success", "degraded", "all_sources_failed", "overlap", "runtime_error"})
_SOURCE_STATUSES = frozenset({"ok", "error"})
_RUN_SCHEMA_VERSION = 1


def default_news_cache_path() -> Path:
    """返回运行时缓存默认位置，支持现有 App Support 环境变量。"""
    configured = os.environ.get("MY_AI_EMPLOYEE_APP_SUPPORT_DIR", "").strip()
    app_support = (
        Path(configured) if configured else Path.home() / "Library/Application Support/MyAIEmployee"
    )
    return app_support / "news" / "latest.json"


class FileNewsStore:
    """安全读取与原子写入新闻快照的轻量文件仓库。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_news_cache_path()

    @property
    def runs_path(self) -> Path:
        """返回与缓存同目录的脱敏刷新运行回执路径。"""
        return self.path.parent / "runs.jsonl"

    def read(self) -> dict[str, Any] | None:
        """读取 JSON 对象；缺失、损坏或异常一律降级为 ``None``。"""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return raw if isinstance(raw, dict) else None

    def write(self, snapshot: dict[str, Any]) -> None:
        """原子写入一份已经构建好的快照。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".latest-",
            suffix=".tmp",
            dir=self.path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    def append_run(
        self,
        *,
        at: str,
        outcome: str,
        success: bool,
        degraded: bool,
        item_count: int,
        source_statuses: Iterable[Mapping[str, object]],
    ) -> None:
        """追加一条 P3 可用的脱敏刷新回执，并同步落盘。

        回执严格只保留运行状态和每个来源的计数，不保存新闻标题、URL 或原始异常文本。
        默认路径为 ``Application Support/MyAIEmployee/news/runs.jsonl``。
        """
        record = {
            "schema_version": _RUN_SCHEMA_VERSION,
            "at": at if isinstance(at, str) else "",
            "outcome": outcome if outcome in _RUN_OUTCOMES else "runtime_error",
            "success": bool(success),
            "degraded": bool(degraded),
            "item_count": _safe_item_count(item_count),
            "sources": [_sanitise_source_status(status) for status in source_statuses],
        }
        runs_path = self.runs_path
        _ensure_private_directory(runs_path.parent)
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        descriptor = os.open(runs_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            # 文件可能由早期版本或手工创建；每次写入时收紧权限。
            os.fchmod(handle.fileno(), 0o600)
            handle.write(encoded)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    @contextmanager
    def refresh_lock(self) -> Generator[bool, None, None]:
        """非阻塞的跨进程刷新锁，防止 launchd 重叠运行。"""
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.parent / "refresh.lock"
        with lock_path.open("a", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _ensure_private_directory(path: Path) -> None:
    """创建或收紧承载新闻运行数据的目录权限。"""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def _safe_item_count(value: object) -> int:
    """只允许非负整数计数，避免 bool 或异常对象进入回执。"""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _sanitise_source_status(status: Mapping[str, object]) -> dict[str, object]:
    """白名单化单来源回执，显式丢弃 ``error``、名称和内容字段。"""
    source_id = status.get("source_id")
    outcome = status.get("status")
    return {
        "source_id": source_id if isinstance(source_id, str) else "unknown",
        "status": outcome if outcome in _SOURCE_STATUSES else "error",
        "item_count": _safe_item_count(status.get("item_count")),
    }
