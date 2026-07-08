---
name: pitfall-86-router-empty-api-key-graceful-degradation
description: router 在 provider 配置不完整(空 api_key / 空 base_url)时应跳过该档走 fallback,而不是调 chat() 让 httpx 抛 "Illegal header value b'Bearer '"
metadata:
  type: feedback
---

# 撞坑 #86 — router 空 token 优雅降级(2026-07-08)

**触发场景**:Day 13 完全体 阶段 2.3 实战跑 `process_inbox --execute --limit 1`,看到日志:
```
[router] primary=deepseek/deepseek-chat 失败: LLMConnectionError("LLM 网络错误 | provider=deepseek | err=Illegal header value b'Bearer '")
[router] secondary=qwen/qwen3-max 成功 | latency=4010ms
```

**根因**:`DEEPSEEK_API_KEY` 未配置(注释掉)→ `_resolve_api_key(DEEPSEEK, None)` 返回 `""` → `OpenAICompatibleProvider.__init__` 不做空 key 校验(只检查 capability registry 不检查 env)→ `provider.chat()` 构造 `Authorization: Bearer ` (空 token)→ httpx 抛 `Illegal header value b'Bearer '` → 被 catch 包装成 LLMConnectionError → 走 fallback → 但产生误导性日志 + 熔断计数器累加(配置问题被当网络问题)。

**修复**:在 `LLMRouter.route()` 第 4 步(调 chat() 前)加 `provider.healthcheck()` 门控:
```python
provider = get_provider(full_id)
if not provider.healthcheck():
    logger.warning(f"[router] {full_id} 配置不完整(api_key 或 base_url 缺失),跳过 {tier_name} | task_type={task_type.value}")
    # 还原 primary_attempts 计数(未真正尝试)
    if tier_name == "primary":
        self._stats.primary_attempts -= 1
    else:
        self._stats.fallback_attempts -= 1
    continue
```

**关键设计**:
- **配置问题 ≠ 网络问题**:不计入熔断(`breaker.record_failure()` 不调)
- **stats 不污染**:`primary_attempts` / `fallback_attempts` 还原回 0,因为没真尝试
- **清晰日志**:warning 级 "配置不完整" 替换 LLMConnectionError 噪声

**测试覆盖**(`tests/ai/test_router.py::TestRouterHealthcheckGate` 4 cases):
1. `test_empty_deepseek_key_skips_primary` — DEEPSEEK_API_KEY 未设 → primary 跳过,secondary 成功
2. `test_empty_key_does_not_trip_breaker` — 配置缺失 5 次路由,breaker 仍关闭,failure_count = 0
3. `test_empty_key_all_tiers_config_missing_raises` — 全链都缺 → LLMAllFallbacksError
4. `test_valid_key_still_uses_primary` — DEEPSEEK_API_KEY 存在 → primary 仍被调(不破坏正常路径)

**Why**:撞坑 #85 三层防御落地后,跑 process_inbox 实战首次撞到 — 之前一直是 mock 测试,看不到真实"空 key"路径。router 应该把"配置完整性"作为前置门控,跟 capability registry 同级。

**How to apply**:
- 任何新增 provider 都自动受益(因为 `provider.healthcheck()` 是 `OpenAICompatibleProvider` 公共方法)
- 任何 router 改造都不要绕过 healthcheck 门控(否则会回到"配置问题当网络问题"老路)
- 撞坑 #76+#85+#86 三闭合已成型:审批伪造 / 草稿幻觉 / 配置降级 三层独立防御

**关联**:
- 撞坑 #85(LLM 草稿幻觉三层防御)· 撞坑 #76(outbox status + 防审批伪造)· 撞坑 #50(snapshot 5 件套 sync)
- HEAD `ae071f0` → `撞坑 #86 commit` 即将 push
- 业务代码改动日:撞坑 #71 docs-only 边界破例(沿 cf369c7 范本)