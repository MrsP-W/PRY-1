"""AI 每日情报本地缓存。

缓存位于 Application Support，避免 launchd 进程直接写入 Documents/iCloud 同步目录。
写入使用同目录原子替换；刷新全失败时由上层保留上一份可用快照。
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


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
