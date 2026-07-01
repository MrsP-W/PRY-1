"""账单 CSV 导入 4 重防误发门控 — import_wechat / import_alipay 共用."""

from __future__ import annotations

import os

REQUIRED_CONFIRM = "yes-i-understand-this-imports-real-bill"


def validate_real_import_gate(
    *,
    env_name: str,
    confirm: str,
    count: int,
    max_rows: int | None,
) -> str | None:
    """校验真实导入门控;通过返回 None,失败返回 stderr 文案."""
    if os.environ.get(env_name) != "1":
        return (
            f"❌ 默认拒绝写库: 须设置 {env_name}=1 才允许导入"
            f"(沿 4 重防误发:env + --confirm + --max-rows 1 + --count 1)"
        )
    if confirm != REQUIRED_CONFIRM:
        return f"❌ {env_name}=1 时 --confirm 必须为 {REQUIRED_CONFIRM!r}"
    if count != 1:
        return f"❌ {env_name}=1 时 --count 必须为 1(防误触发),实际 {count}"
    if max_rows != 1:
        return f"❌ {env_name}=1 时 --max-rows 必须为 1,实际 {max_rows!r}"
    return None


__all__ = ["REQUIRED_CONFIRM", "validate_real_import_gate"]
