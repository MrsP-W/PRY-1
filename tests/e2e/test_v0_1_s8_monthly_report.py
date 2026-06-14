"""S8 — 每月 1 号 09:00 → 月报生成 → 通知用户(Week 2 路径).

承接 docs/v0.1-launch-plan.md:223 S8 唯一编号表行 + docs/week2-mvp.md:225-269 D10 任务。

D6.0 范围(2026-06-14 启动):skip 占位,等 D10 落地后去除 skip。
"""

from __future__ import annotations

import pytest


@pytest.mark.e2e
def test_s8_monthly_report_generation():
    """S8.1 — 每月 1 号 09:00 cron 触发,生成 Markdown 月报 + 同比/环比统计."""
    pytest.skip("S8 每月 1 号 09:00 月报 — 等 D10 落地后去除 skip")


@pytest.mark.e2e
def test_s8_audit_agent_notification():
    """S8.2 — @审计员 Agent 通知用户月报已生成(不超过 5 次/天)."""
    pytest.skip("S8 每月 1 号 09:00 月报 — 等 D10 落地后去除 skip")
