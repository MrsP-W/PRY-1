"""S7 — ⌥⌘N 剪贴板 → 结构化 → 写入 Notes(Week 2 路径).

承接 docs/v0.1-launch-plan.md:222 S7 唯一编号表行 + docs/week2-mvp.md:181-216 D9 任务。

D6.0 范围(2026-06-14 启动):skip 占位,等 D9 落地后去除 skip。
"""

from __future__ import annotations

import pytest


@pytest.mark.e2e
def test_s7_clipboard_to_notes_shortcut():
    """S7.1 — ⌥⌘N 全局快捷键响应 < 500ms + 剪贴板文本 → Markdown 准确率 ≥ 85%."""
    pytest.skip("S7 ⌥⌘N 剪贴板 → Notes — 等 D9 落地后去除 skip")


@pytest.mark.e2e
def test_s7_notes_full_sync():
    """S7.2 — Apple Notes 100% 同步(全量 + 增量)."""
    pytest.skip("S7 ⌥⌘N 剪贴板 → Notes — 等 D9 落地后去除 skip")
