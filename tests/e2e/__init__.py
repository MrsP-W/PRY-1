"""v0.1 端到端 9 场景测试(S1-S9 唯一编号表).

承接 docs/v0.1-launch-plan.md:158-219 + docs/week2-mvp.md:248-260 的 9 场景表。

D6.0 范围(2026-06-14 启动):
    - S1-S5:Week 1 路径,D5 业务链路已落但 e2e spike 未跑
    - S6-S9:Week 2 路径,等 D6/D7/D9/D10 落地

D6.0 阶段:骨架预埋(commit `test(e2e): D6.0 v0.1 端到端 9 场景骨架`)
    - S1-S4:可跑(基于 D3-D5 已有设施 + InMemory faker)
    - S5:默认 skip,`SMTP_REAL_NETWORK=1` env 触发(沿 D5.6.5 范本)
    - S6-S9:skip 占位,等 D6/D7/D9/D10 落地后去除 skip

markers:
    @pytest.mark.e2e            标记 e2e 测试(pyproject 配 e2e marker)
    @pytest.mark.requires_real  标记需真实网络的 e2e 测试(SMTP/微信)
"""
