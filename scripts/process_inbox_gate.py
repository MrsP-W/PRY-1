"""process_inbox 真写门控 — 沿 import_real_gate 4 重防误发范本."""

from __future__ import annotations

import os

REQUIRED_CONFIRM = "yes-i-understand-this-writes-outbox"
ENV_NAME = "PROCESS_INBOX_EXECUTE"
MAX_EXECUTE_LIMIT = 10


def validate_process_inbox_gate(
    *,
    execute: bool,
    confirm: str,
    limit: int,
) -> str | None:
    """校验 process_inbox 真写门控; 通过返回 None, 失败返回 stderr 文案."""
    if not execute:
        return None
    if os.environ.get(ENV_NAME) != "1":
        return (
            f"❌ 默认 dry-run: 须设置 {ENV_NAME}=1 且传 --execute 才允许写 outbox"
            f"(沿 4 重防误发: env + --confirm + --limit 1-{MAX_EXECUTE_LIMIT} + --execute)"
        )
    if confirm != REQUIRED_CONFIRM:
        return f"❌ {ENV_NAME}=1 时 --confirm 必须为 {REQUIRED_CONFIRM!r}"
    if type(limit) is not int or isinstance(limit, bool) or limit < 1:
        return f"❌ --limit 必须为 >=1 的 int, 实际 {limit!r}"
    if limit > MAX_EXECUTE_LIMIT:
        return f"❌ {ENV_NAME}=1 时 --limit 最大 {MAX_EXECUTE_LIMIT}, 实际 {limit}"
    return None


__all__ = ["ENV_NAME", "MAX_EXECUTE_LIMIT", "REQUIRED_CONFIRM", "validate_process_inbox_gate"]
