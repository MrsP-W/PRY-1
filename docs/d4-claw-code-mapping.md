# D4 智能层 — claw-code 参考映射表

> **项目内 mapping**（D4 启动检查清单第 2 项要求）
> **触发规则**:参考 [memory/D4-claw-code-auto-reference.md](../Agent%20Assistant/memory/D4-claw-code-auto-reference.md)（D4 智能层启动后每 D-step 必先参考）
> **2026-06-08 创建 · 2026-06-09 启动 D4.2 时更新**
> **快照基线**:claw-code 6/7 已拉过 12 个文件,后续有变更需 re-fetch

---

## 0. 全局架构原则(6 条,跨 12 文件总结)

1. **Truthful Status** — 任何 API 返回含 status 字段
2. **Degraded Graceful** — 失败不阻塞 + 显式报告
3. **Evidence-Backed** — prose 不可信,必须结构化证据
4. **Capability-Aware** — LLM 集成按模型族特殊处理
5. **Workspace-Bound** — 文件操作 canonical path 边界(**不是** string-prefix)
6. **Machine-Readable** — 需求/任务 schema 固定字段

---

## 1. D4.1 LLM 路由层(✅ 6/8 v1.0 锁定)

| 关注点 | claw-code 参考文件 | 提炼的原则 | 落地位置 |
|--------|-------------------|-----------|---------|
| OpenAI-compatible 协议 | `docs/local-openai-compatible-providers.md` | `/v1/chat/completions` + Bearer 统一 | `ai/providers.py:138-148` base_url 表 |
| Capability registry | `docs/MODEL_COMPATIBILITY.md` | 模型族 capability 数据驱动 | `ai/capability.py` `CAPABILITY_REGISTRY` |
| 4 类业务异常窄化 | (D3.3.3 教训应用) | `LLMError` 基类 + 4 子类 | `ai/providers.py:38-65` |
| 编程错误透传 | (D3.3.3 教训) | `ValueError`/`TypeError` 不包装 | `ai/router.py:183` `except LLMError` |
| Fallback 链 | `src/router/fallback.py`(Rust 模式) | primary/secondary/tertiary 异构 | `ai/fallback.py` `FALLBACK_CHAINS` |
| Circuit Breaker | (D3.3.3 教训应用) | 3 失败熔断 + 冷却期重置 | `ai/fallback.py` `CircuitBreaker` |

**D4 自动参考规则触发检查**:
- [x] 启动 D4.1 时已读 mapping 表
- [x] D4.1 + D4.1.1 报告含"📚 参考来源"段
- [x] rust/ 不看具体实现,Python src/ 可参考

---

## 2. D4.2 MCP 生命周期(2026-06-09 启动)

> **范围**:MCP 客户端基类 + connect/disconnect/重试/熔断 + 4 类业务异常 + DegradedReport + Required flag 决策
> **不接真实 server**:全 mock transport,可独立测试

### 2.1 claw-code 优先参考

| 关注点 | 文件 | 提炼的原则 | 本步骤落地 |
|--------|------|-----------|-----------|
| Degraded startup | `g007-mcp-lifecycle-mapping.md` §Degraded MCP startup | `discover_tools_best_effort` 单 server 失败不拖垮启动 | `mcp/discovery.py` `discover_servers()` |
| 失败 payload 5 字段 | `g007-mcp-lifecycle-mapping.md` `McpErrorSurface` | phase + server + message + context + recoverability | `mcp/exceptions.py` + `mcp/report.py` |
| Required vs optional | `g007-mcp-lifecycle-mapping.md` Required vs optional | `mcpServers.<name>.required` 决策:必填失败→abort,可选失败→degraded | `mcp/client.py` `connect_required_servers()` |
| Degraded Report | `g007-mcp-lifecycle-mapping.md` `McpDegradedReport` | working + failed + available_tools + missing_tools | `mcp/report.py` `McpDegradedReport` |
| 4 类异常窄化 | (D3.3.3 + D4.1 教训应用) | MCPTimeoutError / MCPConnectionError / MCPProtocolError / MCPResponseError | `mcp/exceptions.py` |
| 编程错误透传 | (D3.3.3 教训) | `ValueError`/`TypeError` 不包装 | `mcp/client.py` `except MCPError` 收窄 |
| 关键 regression | `g007-plugin-mcp-verification-map.md` `manager_discovery_report_keeps_healthy_servers_when_one_server_fails` | 1 个 server 失败不阻塞其他 server | `tests/mcp/test_discovery.py::test_discovery_keeps_healthy_servers` |

### 2.2 不照搬的部分

| claw-code 模式 | 本项目做法 | 原因 |
|---------------|-----------|------|
| Rust `McpServerManager::discover_tools_best_effort` 异步 | Python 同步 `discover_servers()` | 项目用户量小,同步更易调试 |
| `mcpServers` 配置文件 + JSON 解析 | 硬编码 server config dict | 暂未接真实 server,配置硬编码简化测试 |
| `lifecycle.Init` / `lifecycle.Shutdown` 命令数组 | `connect()` / `disconnect()` 方法 | Python 协议,无命令数组概念 |
| `MCP stdio` + `JSON-RPC` transport | `Transport` 抽象基类 + mock 实现 | 暂不绑死 stdio 协议,留可扩展性 |

### 2.3 故意不学的

- ❌ Rust 端具体 `mcp_stdio.rs` 实现 — 我们是 Python,不抄 Rust 代码
- ❌ 真实 MCP server 连接 — 项目内没需求,先建抽象
- ❌ `McpOAuth` 流程 — D4.2 不涉及认证

### 2.4 实施子任务(2026-06-09)

1. **D4.2.0 mapping + 报告骨架** — 本文件 + `reports/D4.2-MCP抽象层完成.md` 段
2. **D4.2.1 实施 mcp 抽象层**:
   - `src/my_ai_employee/mcp/exceptions.py` — 4 类异常
   - `src/my_ai_employee/mcp/report.py` — `McpDegradedReport` / `McpErrorSurface` / `McpServerStatus`
   - `src/my_ai_employee/mcp/transport.py` — `Transport` 抽象 + `MockTransport` 实现
   - `src/my_ai_employee/mcp/client.py` — `MCPClient` 基类(connect/disconnect/call_tool + 重试/熔断)
   - `src/my_ai_employee/mcp/discovery.py` — `discover_servers()` + Required flag 决策
3. **D4.2.2 写测试**:
   - `tests/mcp/test_exceptions.py` — 4 类异常窄化 + 编程错误透传
   - `tests/mcp/test_report.py` — DegradedReport 数据结构
   - `tests/mcp/test_transport.py` — MockTransport 模拟超时/连接/协议/响应
   - `tests/mcp/test_client.py` — connect/disconnect/call_tool + 重试/熔断
   - `tests/mcp/test_discovery.py` — `discover_keeps_healthy_servers_when_one_fails` 关键 regression
4. **D4.2.3 8 大质量门 + commit + 报告**

### 2.5 验证 anchor(等价于 g007 6 个 cargo test)

- `pytest tests/mcp/ -v` 全部过
- `pytest tests/mcp/test_discovery.py::test_discovery_keeps_healthy_servers_when_one_fails` 关键 regression
- mypy 0 errors / ruff format 0 errors / ruff check 0 errors
- 覆盖率 mcp 包 ≥ 90%

---

## 3. 后续 D-step mapping(预判,未细化)

> 待 D4.2 完成后,按同样模式细化

| D-step | 主题 | 优先参考 |
|--------|------|---------|
| D4.3 | Events 表契约 | `g004-events-reports-contract.md` + `g004-events-reports-verification-map.md` |
| D4.4 | 任务策略板 | `g006-task-policy-board-verification-map.md` |
| D4.5 | release readiness | `personal-assistant-roadmap.md` + `g012-final-release-readiness-report.md` |
| D4.6-D4.9 | 实际写 classifier/drafter | 用 `router.route()` 调 LLM,无新参考 |

---

**最后更新**:2026-06-09(D4.2 启动,落 mapping 第二段)
**维护者**:Mr-PRY
**关联**:
- [memory/D4-claw-code-auto-reference.md](../Agent%20Assistant/memory/D4-claw-code-auto-reference.md) — 全局规则
- [memory/claw-code-reference.md](../Agent%20Assistant/memory/claw-code-reference.md) — 仓库快照 + 6 个高价值文件
- [memory/tools_status.md](../Agent%20Assistant/memory/tools_status.md) — gh api 旁路 GFW 用法
