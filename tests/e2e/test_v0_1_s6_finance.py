"""S6 — 微信/支付宝 CSV 导入 → 解析 → 入库 → 菜单栏支出更新(Week 2 路径).

承接 docs/v0.1-launch-plan.md:221 S6 唯一编号表行 + docs/week2-mvp.md:58-96 D6 + D7 任务。

D6.0 范围(2026-06-14 启动):skip 占位,等 D6 + D7 落地后去除 skip。
D6.1 完成后:本测试用 InMemory faker CSV 跑端到端(WeChatCSVConnector + TransactionAdapter)。
"""

from __future__ import annotations

import pytest


@pytest.mark.e2e
def test_s6_wechat_csv_import_100_inmemory():
    """S6.1 — 微信账单 CSV InMemory 100 笔导入,3 层去重 + 5 类分类 + status 流转."""
    pytest.skip("S6 微信/支付宝 CSV 导入 — 等 D6 + D7 落地后去除 skip")


@pytest.mark.e2e
def test_s6_cross_source_dedup():
    """S6.2 — 跨源去重:同一笔交易(同日同金额同商家)不会被微信+支付宝两边都导入."""
    pytest.skip("S6 微信/支付宝 CSV 导入 — 等 D6 + D7 落地后去除 skip")


@pytest.mark.e2e
def test_s6_menu_bar_expense_update():
    """S6.3 — 菜单栏支出总额实时更新(写入 transactions 后触发)."""
    pytest.skip("S6 微信/支付宝 CSV 导入 — 等 D6 + D7 落地后去除 skip")
