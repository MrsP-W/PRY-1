"""S9 — launchd 重启 → 全部适配器自愈(Week 2 路径).

承接 docs/v0.1-launch-plan.md:224 S9 唯一编号表行 + docs/week2-mvp.md:225-269 D10 任务。

D6.0 范围(2026-06-14 启动):skip 占位,等 D10 落地后去除 skip。
"""

from __future__ import annotations

import pytest


@pytest.mark.e2e
def test_s9_launchd_restart_recovery():
    """S9.1 — launchd 重启后,IMAP / CalDAV / 微信 / 支付宝 / Apple Notes / 菜单栏 全部适配器自愈."""
    pytest.skip("S9 launchd 重启自愈 — 等 D10 落地后去除 skip")


@pytest.mark.e2e
def test_s9_steward_agent_alive():
    """S9.2 — @管家 Agent 监控所有适配器状态,DOWN 触发通知 + 自动拉起."""
    pytest.skip("S9 launchd 重启自愈 — 等 D10 落地后去除 skip")
