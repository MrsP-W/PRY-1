"""v0.1 端到端 9 场景测试(S1-S9 唯一编号表).

承接 docs/v0.1-launch-plan.md:158-219 + docs/week2-mvp.md:248-260 的 9 场景表。

当前阶段(2026-06-15):
    - S1-S4:可跑(基于 D3-D5 已有设施 + InMemory faker)
    - S5:默认 skip,`SMTP_REAL_NETWORK=1` env 触发(沿 D5.6.5 范本)
    - S6:已实化(微信/支付宝导入 + 跨源去重 + 菜单栏支出聚合)
    - S7:等 D9.2+ sync_notes / ⌥⌘N / Notes e2e 落地
    - S8-S9:等 D10 落地

markers:
    @pytest.mark.e2e            标记 e2e 测试(pyproject 配 e2e marker)
    @pytest.mark.requires_real  标记需真实网络的 e2e 测试(SMTP/微信)
"""
