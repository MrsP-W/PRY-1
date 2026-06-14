# D4 智能层 — claw-code 参考映射表

> **项目内 mapping**（D4 启动检查清单第 2 项要求）
> **触发规则**:参考 [memory/D4-claw-code-auto-reference.md](../Agent%20Assistant/memory/D4-claw-code-auto-reference.md)（D4 智能层启动后每 D-step 必先参考）
> **2026-06-08 创建 · 2026-06-08 D4.2 完成时更新**
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

## 2. D4.2 MCP 生命周期(✅ 2026-06-08 v1.0 锁定)

> **范围**:MCP 客户端基类 + connect/disconnect/重试/降级 + 4 类业务异常 + DegradedReport + Required flag 决策
> **不接真实 server**:全 mock transport,可独立测试
> **注**:D4.2 **不含熔断器**(`failure_count/opened_at` 状态), 仅做 `max_retries` 次重试 + 失败抛错; 熔断器在 D4.4+ 任务策略板阶段加

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

### 2.4 实施子任务(2026-06-08 当日完成)

1. **D4.2.0 mapping + 报告骨架** — 本文件 + `reports/D4.2-MCP抽象层完成.md` 段
2. **D4.2.1 实施 mcp 抽象层**:
   - `src/my_ai_employee/mcp/exceptions.py` — 4 类异常
   - `src/my_ai_employee/mcp/report.py` — `McpDegradedReport` / `McpErrorSurface` / `McpServerStatus`
   - `src/my_ai_employee/mcp/transport.py` — `Transport` 抽象 + `MockTransport` 实现
   - `src/my_ai_employee/mcp/client.py` — `MCPClient` 基类(connect/disconnect/call_tool + 重试 + 4 类异常透传)
   - `src/my_ai_employee/mcp/discovery.py` — `discover_servers()` + Required flag 决策
3. **D4.2.2 写测试**:
   - `tests/mcp/test_exceptions.py` — 4 类异常窄化 + 编程错误透传
   - `tests/mcp/test_report.py` — DegradedReport 数据结构
   - `tests/mcp/test_transport.py` — MockTransport 模拟超时/连接/协议/响应
   - `tests/mcp/test_client.py` — connect/disconnect/call_tool + 重试 + 4 类业务异常
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
| D4.3 | Events 表契约 | `g004-events-reports-contract.md` + `g004-events-reports-verification-map.md` (✅ §4 落地) |
| D4.4 | 任务策略板 | `g006-task-policy-board-verification-map.md` (✅ §5 落地) |
| D4.5 | release readiness | `personal-assistant-roadmap.md` + `g012-final-release-readiness-report.md` |
| D4.6-D4.9 | 实际写 classifier/drafter | 用 `router.route()` 调 LLM,无新参考 |

---

## 4. D4.3 Events 表契约(✅ 2026-06-08 v1.0 锁定)

> **范围**:g004 4 大不变量结构化事件流 — typed event / status / 6 必含 metadata / fingerprint 去重
> **不接业务层**:本步只建契约层(events 表 + 4 StrEnum + 6 必含 metadata + EventStore),D4.4+ 才用 `store.insert()` 真实 emit

### 4.1 claw-code 优先参考

| 关注点 | 文件 | 提炼原则 | 本步骤落地 |
|--------|------|---------|-----------|
| Lane event 4 不变量 | `g004-events-reports-contract.md` §Lane event contract | typed event + status + 6 必含 metadata + fingerprint 去重 | `events/models.py` 4 StrEnum + `events/contract.py` 6 必含字段 + **UNIQUE(fingerprint) 全局唯一** (D4.3.1 复检 P1 修复: 旧 4 字段 UNIQUE 在 `subject_id=NULL` 时被 SQLite 视为不同行, 破坏 dedupe; fallback 跨源场景由 `compute_fingerprint` 入参含 source 保证 fingerprint 不同) |
| 6 必含 metadata 字段 | `g004-events-reports-contract.md` §Lane event contract | seq / timestamp_ms / session_id / ownership / provenance / fingerprint | `REQUIRED_METADATA_KEYS` 元组 + `build_event_metadata()` 工厂 |
| 负向证据 first-class | (D3.3.3 教训应用) | failed/skipped/blocked/cancelled 独立状态 | `EventStatus` 7 枚举 + `by_status(FAILED)` 负向查询 |
| Fingerprint 稳定 | `g004-events-reports-contract.md` §terminal reconciliation | SHA-256 派生 canonical JSON | `compute_fingerprint()` 排除运行时字段(timestamp_ms/seq) |
| 异常范围窄化 | (D3.3.3 教训) | 不接 SQLAlchemyError 基类,只接 IntegrityError | `store.py` `except IntegrityError as err` + `raise ... from err` |
| Programming errors 透传 | (D3.3.3 教训) | ValueError/TypeError 不包装 | `build_event_metadata(seq=-1)` 透传 ValueError |

### 4.2 不照搬的部分

| claw-code 模式 | 本项目做法 | 原因 |
|---------------|-----------|------|
| Rust `LaneEventName` 枚举 + serde 序列化 | Python `enum.StrEnum` + SQLAlchemy ORM | Python 端用户量小,ORM 更易调试 |
| `rust/crates/runtime/src/lane_events.rs` 终端对账 helper | Python 端 `by_session`/`by_status` 简单查询 | 5 万封规模无需 Rust 级对账,SQL 倒序查询足够 |
| Rust 强类型 + serde 反射 | `JSONDict` TypeDecorator + 6 必含字段不变量校验 | SQLAlchemy 2.0 不允许 `metadata` 列名(保留属性),改 `event_metadata` |
| `compute_event_fingerprint` Rust trait 方法 | Python `compute_fingerprint()` 函数 + 排除运行时字段 | 同业务事件多次重试 dedupe,fingerprint 必须跨时间稳定 |

### 4.3 故意不学的

- ❌ Rust 端具体 `lane_events.rs` 实现 — Python 端不抄
- ❌ Report schema v1 (`CanonicalReportV1`/`FieldDelta`/`Projection`) — D4.4+ 任务策略板再加
- ❌ Approval-token 链 — D4.4+ 任务策略板再加
- ❌ Capability negotiation — 单机应用,无多版本消费者场景

### 4.4 实施子任务(2026-06-08 当日完成)

1. **D4.3.0 mapping + schema 同步**:
   - `src/my_ai_employee/core/schema.sql` 扩 events 表 DDL (8 字段,含 `event_metadata` 列名规避 SA 保留)
   - `src/my_ai_employee/core/migrations/versions/0002_events_table.py` alembic 迁移
2. **D4.3.1 实施 5 个 src 模块**:
   - `src/my_ai_employee/events/__init__.py` — 14 个公共导出
   - `src/my_ai_employee/events/exceptions.py` — EventError 基类 + 3 类业务异常
   - `src/my_ai_employee/events/models.py` — Event ORM + 4 StrEnum + JSONDict TypeDecorator
   - `src/my_ai_employee/events/contract.py` — 6 必含 metadata 工厂 + 不变量校验 + SHA-256 fingerprint
   - `src/my_ai_employee/events/store.py` — EventStore: insert + dedupe + 4 类查询
3. **D4.3.2 写 56 个测试**:
   - `tests/events/test_models.py` (18) — Event ORM + 4 StrEnum + JSONDict TypeDecorator
   - `tests/events/test_contract.py` (18) — 6 必含字段不变量 + fingerprint 稳定性 + 异常窄化
   - `tests/events/test_store.py` (20) — insert + dedupe + 4 类查询 + 负向证据
4. **D4.3.3 8 大质量门 + commit + 报告**

### 4.5 验证 anchor(等价于 g004 verification map 6 个 cargo test)

- `pytest tests/events/ -v` 59 passed
- `pytest` 全量 268 passed (D4.2 209 + D4.3 59, D3 老测试 2 个修断言)
- mypy 0 errors / ruff format 0 errors / ruff check 0 errors
- 覆盖率 events 5 模块 ≥ 88% (models 100% / exceptions 100% / store 98.6% / contract 88.7% / 测试 fixtures 共享)
- alembic upgrade head 0002_events OK
- uv build success

### 4.6 关键设计决策(D3.3.3 + D3.2 教训应用)

| 决策 | 理由 | 教训来源 |
|------|------|---------|
| fingerprint 排除 `timestamp_ms/seq` | 同一业务事件多次重试应 dedupe,跨时间稳定 | g004 §"ordering/deduplication hooks" |
| fingerprint canonical JSON `sort_keys=True` | key 顺序不影响哈希 | g004 §"stable canonical" |
| 列名 `event_metadata` 而非 `metadata` | SQLAlchemy Declarative 保留属性 | D3.2.3 NOCASE/JSON 教训 |
| UNIQUE 4 字段 + 列上 `fingerprint` 索引 | SQLite UNIQUE 不支持函数表达式 | D3.2.3 DESC 索引教训 |
| `except IntegrityError as err` + `raise ... from err` | 窄化异常 + 保留 stack trace | D3.3.3 过宽 except 教训 |
| `by_session` Python 端 filter | 避免 SQLite JSON 路径查询方言差异 | D3.2.4 mypy 兼容教训 |
| `on_conflict="ignore"` (默认) + `"raise"` (可选) | dedupe 命中是正常业务,但严格模式要透明 | D3.3.3 失败状态透明化 |
| EventType 全部 3 段式 (`domain.entity.action`) | g004 命名风格 + 便于子动作细分 (4 段如 `email.classify.failed` 允许) | g004 §Lane event contract |
| EventStatus 7 枚举 (含 5 个负向状态) | 负向证据 first-class: failed/skipped/blocked/cancelled/degraded 都是独立状态 | D3.3.3 教训应用 |
| 事件流/audit_log 职责正交 | events = 智能层结构化事件流;audit_log = D3 sync 审计(不动) | 单一职责原则 |

---

## 5. D4.4 任务策略板(✅ 2026-06-08 v1.0 锁定)

> 落地 claw-code `g006-task-policy-board-verification-map.md` 的 4 大核心组件:TaskPacket 8 字段契约 + PolicyEngine 6 决策 + LaneBoard 3 lanes + Heartbeat 3 状态。

### 5.1 claw-code 优先参考

| 关注点 | claw-code 参考 | 提炼原则 | 落地位置 |
|--------|---------------|---------|---------|
| TaskPacket 8 必含字段 | `g006-task-policy-board-verification-map.md` §Task packet | objective / scope / resources / acceptance_criteria / model / provider / permission_profile / recovery_policy | `src/my_ai_employee/policy/task_packet.py` 8 字段 dataclass + `field(default=...)` 全部 default |
| 6 决策规则 | `g006-task-policy-board-verification-map.md` §Executable policy decisions | retry / rebase / stale_cleanup / approval_token / merge / escalate | `src/my_ai_employee/policy/policy_engine.py` `PolicyDecisionKind` 6 枚举 + 6 rule 方法 |
| 3 lanes + 状态转换 | `g006-task-policy-board-verification-map.md` §Active lane board | active / blocked / finished + ACTIVE↔BLOCKED→FINISHED 转换矩阵 | `src/my_ai_employee/policy/lane_board.py` `LaneStatus` 3 枚举 + `_assert_valid_transition` |
| 3 状态心跳 | `g006-task-policy-board-verification-map.md` §Liveness heartbeat | healthy / stalled / transport_dead + 优先级 TRANSPORT_DEAD 最高 | `src/my_ai_employee/policy/heartbeat.py` `Liveness` 3 枚举 + `evaluate()` 优先级 |
| PolicyDecisionEvent 落地 | (D4.3 复用, 不重复) | 复用 `EventStore.insert()` + 6 必含 metadata + 7 业务字段 | `policy_engine.py` `_emit_decision_event()` + 2 个 EventType 扩展 |

### 5.2 不照搬的部分

1. **不照搬 g006 §"policy.rs" 的 Rust trait object 多态** — Python 端用 `PolicyDecisionKind` StrEnum + 字典映射等价(避免引入 `abc.ABC` 复杂度)
2. **不照搬 g006 §"status JSON" 完整 schema** — 只导出 `to_status_json()` 最小集(lanes / freshness / total / idle_threshold_ms),CLI 渲染留 D4.5+
3. **不照搬 g006 §"approval_token_id" 的链式签名** — 只留字符串字段,token 实际生成/校验由 D4.5+ 业务层做(policy 层不引入密钥管理)
4. **不照搬 g006 §"lane board 持久化"** — LaneBoard 是 in-memory,不落 events 表(与 EventStore 解耦),跨进程可见性留 D4.4.1+

### 5.3 故意不学的部分

1. **不学 g006 的 "policy 失败自动重试整个任务"** — D4.4 只声明 `EscalateRequired`,实际重试/升级由 caller 决定(D3.3.3 教训:异常窄化,不替 caller 决定)
2. **不学 g006 的 "merge 触发后自动 push to main"** — D4.4 只声明 `MergeRequired`,实际 git 操作由 D4.5+ 执行(policy 层不依赖 git)
3. **不学 g006 的 "transport_dead 自动重连"** — D4.4 只暴露 `assert_alive()` 抛错,重连由 transport 层(D4.2 MCP)自己处理

### 5.4 实施子任务(2026-06-08 当日完成)

| 子任务 | 文件 | 行数 |
|--------|------|------|
| 1. TaskPacket 8 字段契约 + JSON 双向 + Builder | `src/my_ai_employee/policy/task_packet.py` | 287 |
| 2. Heartbeat 3 状态 + 优先级 + 便捷方法 | `src/my_ai_employee/policy/heartbeat.py` | 157 |
| 3. LaneBoard 3 lanes + 状态转换矩阵 | `src/my_ai_employee/policy/lane_board.py` | 362 |
| 4. PolicyEngine 6 决策 + EventStore 集成 | `src/my_ai_employee/policy/policy_engine.py` | 453 |
| 5. 5 类业务异常 + PolicyError 基类 | `src/my_ai_employee/policy/exceptions.py` | 71 |
| 6. 26 个公共 API 顶层导出 | `src/my_ai_employee/policy/__init__.py` | 95 |
| 7. 2 个 EventType 扩展(复用 D4.3) | `src/my_ai_employee/events/models.py` | +2 |
| 8. 5 个测试文件 + 180 测试 | `tests/policy/` | 1720 |
| 9. D4.4 完成报告 | `reports/D4.4-任务策略板完成.md` | 540+ |

**总产出**:6 src 模块(1425 行) + 1 enum 扩展 + 1 测试修复 + 5 测试文件(1720 行) + 1 报告(540 行) + 1 mapping 段(本段)。

### 5.5 验证 anchor(等价于 g006 verification map 6 个 cargo test)

| 验证项 | 测试文件 | 测试数 |
|--------|----------|--------|
| 5 子类层级 + raise/catch | `tests/policy/test_exceptions.py` | 10 |
| 8 字段契约 + JSON 双向 + 向后兼容 | `tests/policy/test_task_packet.py` | 29 |
| 3 状态 + 优先级 + now_ms 注入 | `tests/policy/test_heartbeat.py` | 27 |
| 3 lanes + 状态转换矩阵 + freshness | `tests/policy/test_lane_board.py` | 50 |
| 6 决策 + EventStore 集成 + fingerprint dedupe + 23 context 严格解析 | `tests/policy/test_policy_engine.py` | 64 |
| **总计** | | **180 passed** (含 10 conftest setup) |

### 5.6 关键设计决策(D3.3.3 + D3.2 教训应用)

| 决策 | 理由 | 教训来源 |
|------|------|---------|
| 8 字段全 `field(default=...)` | 旧 JSON 缺字段仍能 `from_dict()`,向后兼容 | g006 §Task packet "serde(default)" 强调 |
| 5 类业务异常 + PolicyError 基类 | 异常窄化:每类对应一类业务错误,`except PolicyError` 可兜底 | D3.3.3 教训应用 |
| 编程错误 (ValueError) 透传 | 不包装编程错误,避免掩盖问题 | D3.3.3 教训应用 |
| Heartbeat 优先级 TRANSPORT_DEAD > STALLED > HEALTHY | transport 断连 = 必失败,优先于 idle 超时 | g006 §Liveness 段 |
| LaneBoard 状态转换合法性矩阵 | 显式列出合法转换,非法抛 PolicyLaneError | g006 §Lane board 段 |
| 6 决策 priority 排序 (escalate 100 > approval 80 > retry 70 > rebase 60 > stale_cleanup 50 > merge 40) | caller 按 priority 降序执行 | g006 §Executable policy decisions |
| 复用 D4.3 EventStore (新增 2 EventType) | 不引入新表,统一事件流 | D4.3 单一职责延续 |
| now_ms 时间注入 | 测试可控,避免 sleep/time 漂移 | D4.3 模式延续 |
| LaneBoard in-memory,不落 events 表 | 与 EventStore 解耦,简化 D4.4 范围 | 单一职责原则 |
| ApprovalToken 仅字符串字段 | token 生成/校验由 D4.5+ 业务层做 | 关注点分离 |

### 5.7 已知限制(D4.4.1+ 复检 P 项)

| 限制 | D4.4.1+ 改进方向 |
|------|-----------------|
| 6 决策是"声明式评估",不替 caller 执行 | 提供 executor pattern(D4.5+ 业务层) |
| LaneBoard in-memory,跨进程不可见 | D4.4.1+ 落 events 表(lane.entry.added / status_changed) |
| ApprovalToken 无独立存储 | D4.4.1+ 引入 token 签发/校验(基于 events 表 audit log) |
| Status JSON 未接 CLI | D4.5+ 加 `mmx policy status` 子命令 |
| Policy 失败 fallback 是 escalate | D4.4.1+ 加 retry policy for 评估本身 |

---

## 6. D4.5 release readiness + 业务层接入(✅ 2026-06-08 v1.0 锁定 · P0 业务语义修复 + 文档/可观测性补完后)

> **范围**:D4.4 任务策略板首次**真实业务 emit** — 选 D3.3 IMAP 同步(D2 connectors/imap.py 拉邮件 + D3.3 sync.py 入库)做第一个接入点,验证 PolicyEngine.evaluate() 真实落 `POLICY_DECISION_MADE` 事件 + LaneBoard 推进状态 + Heartbeat 探活 IMAP。
> **不引 g007 / g012**:不引入 release CI pipeline,不写 production deploy 脚本;**只交付 ready_for_review 决策包**(5 段报告 + 等用户审批,无 push to main 动作)。
> **不替 caller 执行**:6 决策是声明式,executor pattern 不在本步实现;`SyncPolicyAdapter.evaluate_and_emit` 只负责 emit + 推进 lane,实际 retry/merge/escalate 由 D5+ 业务调度器决定。

### 6.1 claw-code 优先参考

| 关注点 | 文件 | 提炼原则 | 本步骤落地 |
|--------|------|---------|-----------|
| 4 件套不动 | (D4.4 锁定, 不改) | TaskPacket 8 字段 / PolicyEngine 6 决策 / LaneBoard 3 lanes / Heartbeat 3 状态保持 v1.0 | `policy/integration.py` 1 个新模块,**只 import 不修改** D4.4 任何源文件 |
| 业务层接入范本 | `personal-assistant-roadmap.md` §Business layer integration | 4 依赖可注入(event_store / engine / heartbeat / board),不传 = D3.3 行为不变 | `SyncPolicyAdapter.__init__(*, source, event_store=None, engine=None, heartbeat=None, board=None)` 4 可选参数 |
| IMAP sync → policy context | (D3.3 SyncResult 字段对齐) | inserted / failed / duration_seconds → acceptance_results | `build_imap_sync_packet()` + `compute_acceptance_results()` 3 条 AC |
| Decision event 复用 | (D4.3 复用) | 7 业务字段(rule_name / priority / kind / explanation / approval_token_id / all_decisions / context_snapshot)直接合并到 `event_metadata` 顶层 | `policy_engine._emit_decision_event` 已有,本步只触发 |
| Context 12 字段严判 | (D4.4 P1 教训应用) | bool/int/str/list[bool] native type,`type() is bool` 严判,拒 type-coerce | `build_sync_policy_context` 12 字段全用 `type() is bool/int` 严判,脏输入早失败 |
| LaneBoard entry_id 命名 | (D4.4 3 状态转换矩阵) | `sync:<source>:<run_id>` 唯一性由 caller 保证 | `SyncPolicyAdapter.build_lane_entry_id()` 工厂方法 |

### 6.2 不照搬的部分

| claw-code 模式 | 本项目做法 | 原因 |
|---------------|-----------|------|
| `g012-final-release-readiness-report.md` 全 5 段报告 + 7 天观察期 | 5 段 ready_for_review 报告(测试覆盖/质量门/性能/已知限制/待审批) | 项目用户量小,无 production 部署压力,7 天观察期降级为"用户审批" |
| `personal-assistant-roadmap.md` §Executor pattern 实际执行 retry/rebase/merge | `evaluate_and_emit` 只声明决策,不替 caller 执行 | D3.3.3 教训应用:异常窄化,不替 caller 决定 |
| 真实 `mmx policy status` CLI 集成 | 状态 JSON 导出方法已存在,CLI 留 D4.5.1+ | D4.5 范围收敛,CLI 不在本步 |
| `g007-mcp-lifecycle-mapping.md` 4 类 MCP 异常 | 复用 D4.4 PolicyError 5 子类,不引入新异常 | 异常体系已稳定,避免无意义扩张 |

### 6.3 故意不学的部分

1. **不学 g012 §"CI/CD pipeline" 部署脚本** — 交付物是 `ready_for_review` 报告,不是 production deploy;CLAUDE.md 明确"应急版诚信交付 > 假装成功"
2. **不学 g012 §"canary deploy + 灰度"** — 用户量 < 100,全量 release 即可,无灰度必要
3. **不学 g012 §"rollback plan"** — 数据库迁移 alembic 已 `upgrade/downgrade` 双向,无新部署面

### 6.4 实施子任务(2026-06-08 当日完成)

| 子任务 | 文件 | 行数 |
|--------|------|------|
| 1. 业务层接入核心 (3 factory + 1 adapter + 1 dataclass) | `src/my_ai_employee/policy/integration.py` | ~270 |
| 2. 5 个新增公共 API 顶层导出 | `src/my_ai_employee/policy/__init__.py` | +5 (26→31) |
| 3. 35 个集成测试 (5 类) | `tests/policy/test_integration.py` | 397 |
| 4. ready_for_review 5 段报告 | `reports/D4.5-release-readiness.md` | ~400 |
| 5. mapping §6 详细段 | `docs/d4-claw-code-mapping.md` | (本段) |

**总产出**:1 新增 src 模块(270 行) + 1 `__init__` 扩展(26→31 导出) + 1 新增测试(397 行 / 35 tests,含 P0 修复 +4 + v1.0.1 文档/可观测性补完 +2) + 1 报告(400 行) + 1 mapping 段。**D4.4 源文件零修改**(4 件套契约保持 v1.0)。

### 6.5 验证 anchor(8 质量门全绿,v1.0 锁定 6/8)

| 门 | 结果 |
|----|------|
| 1. `pytest tests/policy/ -v` | **217 passed in 0.30s** (D4.4 180 → D4.5 +37 = 35 集成 + 2 v1.0.1,含 P0 修复 +4) |
| 2. `ruff check` | All checks passed |
| 3. `ruff format` | 71 files already formatted |
| 4. `mypy src/my_ai_employee/policy/` | 0 errors / 7 files(D4.4 6 + integration 1) |
| 5. `mypy tests/policy/` | 0 errors / 8 files(D4.4 7 + test_integration 1) |
| 6. `alembic upgrade head --sql` | exit 0 (0003 latest) |
| 7. `uv build` | tar.gz + .whl OK |
| 8. `pytest` (全量) | **496 passed**(D4.3 预存隔离 6/8 晚间已修复,**0 失败**) |

### 6.6 关键设计决策(D3.3.3 + D4.4 P1 + D4.5 P0 教训应用)

| 决策 | 理由 | 教训来源 |
|------|------|---------|
| 4 依赖全可选注入 | D3.3 行为零变化,不传 = 纯评估模式 | Karpathy 原则 2(向后兼容) |
| `evaluate_and_emit` 不替 caller 执行 6 决策 | 只 emit + 推进 lane,实际 retry/merge/escalate 由 D5+ 决定 | D3.3.3 异常窄化教训 |
| `consecutive_failures` 必填原生 int>=0,`type() is int` 严判,透传 ValueError | 编程错误不包装,避免掩盖问题 + 拒 bool 子类 | D4.4 P1 + D4.5 P0-1 反馈 |
| `transport_alive` 必填原生 bool,`type() is bool` 严判 | 字符串"true" 不通过,脏输入早失败 | D4.4 P1 + D4.5 P0-1 反馈 |
| `branch_stale` / `now_ms` 入口严判(type() is bool/int) | 与 D4.4 P1 对齐,`branch_stale="false"` 等脏输入不静默转 True | D4.5 P0-1 反馈 |
| escalate 语义:`failed > 0 AND consecutive_failures >= 3` | 达到连续失败阈值才升级;原 `failed > cf > 0` 颠倒 | D4.5 P0-2 反馈 |
| lane/heartbeat 单一真相源 = `all(acceptance_results)` | 3 条 AC 全 pass 才算"sync 成功",与 PolicyEngine 同步 | D4.5 P0-3 反馈 |
| `run_id` 空时用 `int(time.time()*1000)` 默认值 | 多次调用 lane_entry_id 唯一(测试 `test_run_id_unique_per_call` 验证) | Karpathy 原则 3(最小可用) |
| `record_to_lane` 内部先 add ACTIVE 再 update FINISHED | D4.4 状态矩阵:FINISHED 终态不能直接 add | D4.4 LaneBoard 矩阵 |
| 业务 payload 7 字段合并到 `event_metadata` 顶层 | D4.3.2 决策:`build_event_metadata` `meta.update(extra)` | D4.3.2 contract 教训 |
| `now_ms` 注入而非 time.time() 默认 | 测试可控,避免 sleep/clock 漂移 | D4.3 + D4.4 模式延续 |
| `event_id=None` 表示纯评估模式 | 适配器不强制依赖 store,允许 dry-run | Karpathy 原则 1(think before coding) |
| `lane_entry_id` 命名 `sync:<source>:<run_id>` | 跨次 sync 区分(每次 sync 有独立 run_id) | D4.4 lane_id 命名风格 |
| `lane_entry_id` + `run_id` 写入 `event_metadata`(v1.0.1 反馈闭环) | 修复反馈 #1: 文档说可推算但实际 metadata 没写 → 显式写入便于 `mmx policy history --lane` 跨次串联 | D4.5 v1.0.1 P0 反馈 #1 |

### 6.7 已知限制(D4.5.1+ 复检 P 项)

| 限制 | 改进方向 |
|------|----------|
| 6 决策是声明式,`evaluate_and_emit` 不替 caller 执行 | D4.5.1+ 加 `executor` pattern:retry 调 `IMAPSync.run_once` / escalate 写 events 表 escalation row |
| LaneBoard in-memory,D4.5 仍无持久化 | D4.5.1+ 落 `lane.entry.added` / `status_changed` 事件到 events 表 |
| 单一 source 适配器(IMAP) | D4.6+ 加 `EmailClassifierAdapter` / `EmailDrafterAdapter`(同 SyncPolicyAdapter 4 依赖范本) |
| `consecutive_failures` 外部喂入,D4.5 不接 SyncState | D4.5.1+ 集成 `IMAPSyncState.consecutive_failures` 字段(已有,只接) |
| 无 1 万封真实 spike | D4.5.1+ 在 1 万封真实邮件上跑 `evaluate_and_emit` 30 天(D3.3 spike 已验证 0.30s/万封) |

---

## 7. D4.6 邮件分类器(✅ 2026-06-08 v1.0 锁定 → 2026-06-09 v1.0.1 业务语义修复后真正锁定 → v1.0.2 二次复检后真正锁定 → **v1.0.2 第三次复检后真正锁定**)

### 7.1 claw-code 优先参考

claw-code 仓库无"邮件分类"或"标签路由"模块。**D4.6 直接落 ai/classifier.py,不照搬**。

最近邻的是 `src/agents/prompts.rs`(prompt 模板组织)+ `src/agents/agent_loop.rs`(任务循环 + fallback)。D4.6 借鉴 2 点:

- **数据驱动 prompt**:`ai/prompts/classify.py` 独立模块,与业务代码分离,便于切换 LLM 时只改 prompt
- **5 类枚举 + 严判**:`EmailCategory` 5 类 StrEnum,严判响应 JSON 字段,避免脏输入污染 events

### 7.2 不照搬的部分

- claw-code 通用 agent loop 是 OpenAI function-calling 模式;D4.6 邮件分类是**短响应决策**(≤64 token),不调 function call
- claw-code 任务循环是 long-running;D4.6 分类是单次调用,无状态

### 7.3 故意不学的

- 不用 regex 定位 JSON(强制字段顺序,反序误拒)— D4.6 v1.0.1 P1-4 修复改用平衡括号扫描
- 不用 `float()` / `int()` 静默 coerce(D2 truthy 陷阱)— D4.6 v1.0.1 P2-5 修复改用 type() 严判
- 不用单一 `all_pass` 变量同时驱动 Lane + Heartbeat(SPAM 误报 transport_dead)— D4.6 v1.0.1 P1-2 修复拆分为 `business_accepted` + `transport_alive`
- **不把严判只放在 Adapter 入口(v1.0.2-second P1 教训)**:`compute_classification_acceptance` / `build_classify_policy_context` 是公开 helper,Adapter 重构后可能绕过严判 → 严判下沉到公共 API,Adapter 只复用
- **不用 `category=""` 当失败报告占位符(v1.0.2-second P2-2 教训)**:违反 `ClassifyDecisionReport.category: 5 类` 字段契约 → 定义 `ClassifyFailureDecisionReport` 独立类型,`failed: bool` + `last_error: str` + `consecutive_classify_failures: int`
- **不在 `policy/integration.py` 内部写好但不导出(v1.0.2-second P2-3 教训)**:`build_classify_failure_packet` 已在 `__all__` 但 `policy/__init__.py` 没转发 → 顶层 `from my_ai_employee.policy import ...` 缺名字 ImportError
- **不让公共构造器跳过严判(v1.0.2-third P1 教训)**:`build_classify_packet` 是公开构造器, 旧版仅 `type() is str` + 空检查, 缺 5 类枚举校验 → 复用 `_validate_classify_category` 公共 helper(主入口 + 构造器同一严判口径)
- **不用 `bool` 字段表示"必为 True"语义(v1.0.2-third P2 教训)**:`ClassifyFailureDecisionReport.failed: bool` 仍能手动构造 `failed=False` 混入成功报告 → `Literal[True]` 类型层面固化 + `__post_init__` 显式校验(D3.3.3 教训:数据类字段约束必须自洽)
- **不混用 frozenset `in` 与 helper 严判(v1.0.2-third P2 教训)**:`classify_and_emit` 内联 `if x not in frozenset` 与 `build_classify_packet` / `build_classify_policy_context` 走的 `_validate_classify_category` 不一致 → 统一走 helper,异常统一 `ValueError`,防止 list/dict/set 等不可哈希类型在后续操作触发 `TypeError`

### 7.4 实施子任务(2026-06-08 晚间 + 2026-06-09 晨间三次复检)

| 子步骤 | 文件 | 关键产物 | 状态 |
|--------|------|---------|------|
| D4.6.1 | `src/my_ai_employee/ai/classifier.py` | EmailCategory 5 类 + EmailClassifier + _parse_classification_response | ✅ v1.0 → v1.0.1 → v1.0.2-second |
| D4.6.2 | `src/my_ai_employee/ai/prompts/classify.py` | 5 类 SYSTEM prompt + build_user_message | ✅ v1.0 |
| D4.6.3 | `src/my_ai_employee/policy/integration.py` | EmailClassifierAdapter + 3 factory + ClassifyDecisionReport + 3 _validate_classify_* + ClassifyFailureDecisionReport + Literal[True] | ✅ v1.0 → v1.0.1 → v1.0.2-first → v1.0.2-second → **v1.0.2-third** |
| D4.6.4 | `src/my_ai_employee/ai/providers.py` | LLMAllFallbacksError(D4.6 v1.0.1 P1-1 新增) | ✅ v1.0.1 |
| D4.6.5 | `src/my_ai_employee/ai/router.py` | raise LLMAllFallbacksError 替换 RuntimeError | ✅ v1.0.1 |
| D4.6.6 | `src/my_ai_employee/policy/__init__.py` | 顶层暴露 `ClassifyFailureDecisionReport` + `build_classify_failure_packet`(v1.0.2-second P2-3 修复) | ✅ v1.0.2-second |
| D4.6.7 | `tests/ai/test_classifier.py` | 46 tests(31 旧 + 9 v1.0.1 + 6 v1.0.2-first) | ✅ v1.0.2-first |
| D4.6.8 | `tests/policy/test_classifier_adapter.py` | 69 tests(32 旧 + 8 v1.0.1 + 10 v1.0.2-first + 11 v1.0.2-second + **8 v1.0.2-third**) | ✅ v1.0.2-third |
| D4.6.9 | `tests/ai/test_router.py` | test_all_fail_raises_runtime_error 改测 LLMAllFallbacksError | ✅ v1.0.1 |
| D4.6.10 | `reports/D4.6-邮件分类器.md` | v1.0 段 + §0.5 v1.0.1 + §0.6 v1.0.2-first + §0.7 v1.0.2-second + **§0.8 v1.0.2-third** | ✅ v1.0.2-third |
| D4.6.11 | `docs/week1-mvp.md §D4.6` | v1.0 → v1.0.1 → v1.0.2-first → v1.0.2-second → **v1.0.2-third** 演进表 + 三次复检 + 8 质量门更新 | ✅ v1.0.2-third |
| D4.6.12 | `docs/d4-claw-code-mapping.md §7` | 本段 mapping(v1.0.1 → v1.0.2-third / 576 → 611) | ✅ v1.0.2-third |

### 7.5 验证 anchor(8 质量门 8/8 全绿)

| 门 | 命令 | v1.0.2-third 结果 |
|----|------|---------------------|
| 1 | `pytest` | **611 passed** / 0 failed(v1.0.1 576 → v1.0.2-first 592 → v1.0.2-second 603 → **v1.0.2-third 611**) |
| 2 | `ruff check` | All checks passed |
| 3 | `ruff format --check` | 81 files already formatted |
| 4 | `mypy src` | 0 errors / 43 files |
| 5 | `alembic upgrade head --sql` | exit 0(同 v1.0 DDL) |
| 6 | `uv build` | tar.gz + .whl OK(同 v1.0.2-first,v1.0.1 误写 blocked) |
| 7 | `make lint` | 0 errors |
| 8 | `pytest --collect-only -q` | classifier 46 + adapter 69 = D4.6 115 / 全量 611 |

### 7.6 关键设计决策(D3.3.3 + D4.4 P1 + D4.5 P0 + v1.0.1 P1-1 ~ P1-4 + P2-5 + v1.0.2-first 5 修复 + v1.0.2-second 4 修复 + **v1.0.2-third 4 修复**)

- **复用 D4.1.1 LLM Router**:`router.route(TaskType.CLASSIFY, ...)` 自动走 DeepSeek → Qwen → M3 fallback 链
- **5 类枚举 + 严判**:`EmailCategory` StrEnum + `_parse_classification_response` 7 步防御(类型严判 → markdown fence 剥离 → 平衡括号定位 → json.loads → category 5 类枚举校验 → math.isfinite → 0-1 范围)
- **业务层接入范本**:复用 D4.5 `SyncPolicyAdapter` 4 依赖可注入(`event_store` / `engine` / `heartbeat` / `board`),`classify_and_emit` 5 步主入口
- **业务字段透传**:`extra_business_payload` 扩 PolicyEngine 可选 kwargs,业务字段(category / confidence / model_full_id / email_id / source)合并到 event_metadata 顶层
- **lane_entry_id 命名**:`classify:<source>:<run_id>`(与 `sync:` 区分)
- **D4.6 v1.0.1 业务语义修复汇总**:
  - P1-1:`LLMAllFallbacksError(LLMError)` 解决 router 逃逸 → classifier 自动覆盖
  - P1-2:拆分 `business_accepted`(Lane) vs `transport_alive`(Heartbeat),SPAM / 低置信度 / 慢响应 ≠ LLM 死
  - P1-3:`last_classify_failed` 显式 bool 解决成功路径误触发 retry / escalate
  - P1-4:平衡括号 + `math.isfinite()` 解决反序 JSON 误拒 + NaN 漏过
  - P2-5:严判 duck type 解决 bool / str 静默 coerce(`True → 1.0` / `"0.5" → 0.5`)
- **D4.6 v1.0.2-first 业务语义修复汇总**(type system 层面):
  - P1-1:拆双入口 `classify_and_emit`(成功) / `record_classify_failure_and_emit`(失败,cf 必填),编译期拒绝状态耦合
  - P1-2:5 类严判 `_VALID_CLASSIFY_CATEGORIES` + `latency_ms >= 0`
  - P2-3:平衡 JSON `_find_all_balanced_json` + `_extract_balanced_json` 选含 category+conf
  - P2-4:批处理补全 type hint `ValueError | KeyError` + 缺字段 KeyError 收容
  - P2-5:`math.isfinite()` 拒 NaN/Inf
- **D4.6 v1.0.2-second 二次复检修复汇总**(公共 API + 文档):
  - P1 严判下沉:3 个 `_validate_classify_*` helper(category / confidence / latency_ms)下沉到 `compute_classification_acceptance` + `build_classify_policy_context`,Adapter 重构后无法绕过
  - P2-2 失败报告独立类型:`ClassifyFailureDecisionReport`(`failed: bool` + `last_error: str` 截断 200 + `consecutive_classify_failures: int`)与 `ClassifyDecisionReport` 类型层面区分
  - P2-3 顶层导出:`policy/__init__.py` 暴露 `ClassifyFailureDecisionReport` + `build_classify_failure_packet`,`from my_ai_employee.policy import ...` 不再 ImportError
  - P3 文档同步:报告 49+47 → 46+50 → 46+61 / uv build blocked → passed / week1-mvp 559 → 603 / mapping 576 → 603
- **D4.6 v1.0.2-third 第三次复检修复汇总**(公共 API 自防御 + 数据类自洽 + 文档同步):
  - P1 公共构造器严判:`build_classify_packet` 复用 `_validate_classify_category`(原版仅 `type() is str` + 空检查,缺 5 类校验),与主入口 + 公共 helper 同一严判口径
  - P2 Literal[True] + 字段自洽:`ClassifyFailureDecisionReport.failed: bool` → `Literal[True]`(mypy 编译期拒绝 `failed=False`);新增 `__post_init__` 三重校验(`failed is True` + `last_error` 非空 + `consecutive_classify_failures >= 1`,D3.3.3 教训)
  - P2 异常统一 ValueError:`classify_and_emit` 内联 `if x not in frozenset` 替换为 `_validate_classify_category`,严判入口统一 `ValueError`,防止 list/dict/set 等不可哈希类型在后续操作触发 `TypeError`
  - P3 文档同步:`classify_and_emit` docstring 用例移除已删除的 `consecutive_classify_failures=0`;`record_classify_failure_and_emit` 返回值 docstring 改类型;模块 docstring 增 v1.0.2-third 段

### 7.7 故意不学的范本(g009 §"反范本" 沉淀)

| 旧 v1.0 写法 | 新 v1.0.1+ 写法 | 教训 |
|--------------|---------------|------|
| `raise RuntimeError(...)` (全链失败) | `raise LLMAllFallbacksError(...)` (LLMError 子类) | 业务异常必须从基类继承,业务方 `except` 一行覆盖 |
| `all_pass` 同时驱动 Lane + Heartbeat | `business_accepted` (Lane) + `transport_alive` (Heartbeat) | 业务验收 ≠ 传输存活,两个状态独立判定 |
| 纯 `cf` 推断 `recoverable` | `last_classify_failed AND 0 < cf < 3` 显式 bool | 成功路径责任清晰,避免 caller 隐式重置纪律 |
| 正则 `\{...category...confidence...\}` | 平衡括号扫描 `_extract_balanced_json` | 不假设字段顺序,允许 LLM 自由发挥 |
| `0 <= x <= 1` 范围检查 | `math.isfinite(x) AND 0 <= x <= 1` | NaN / Inf 必须显式拒(NaN 任何比较返回 False) |
| `float(confidence)` / `int(latency_ms)` 静默 coerce | `type() is (int, float) AND not isinstance(x, bool)` | 严判入口拒绝 type-coerce,与 D4.4 P1 对齐 |
| **严判只放 Adapter `classify_and_emit` 入口(v1.0)** | **严判下沉到 `compute_*` + `build_*` 公共 API(v1.0.2-second)** | 公共 helper 必自防御,Adapter 重构不可绕过 |
| **失败报告用 `category=""` 占位符(v1.0)** | **`ClassifyFailureDecisionReport` 独立类型(v1.0.2-second)** | 数据类字段约束必须自洽,空串不是合法 5 类 |
| **`policy/integration.py` 内部写好但不导出(v1.0.1)** | **`policy/__init__.py` 顶层暴露(v1.0.2-second)** | `__all__` 声明 ≠ 实际可导入,顶层必须转发 |
| **公共构造器 `build_classify_packet` 仅 `type() is str` 校验(v1.0.2-second)** | **复用 `_validate_classify_category` 公共 helper(v1.0.2-third)** | 构造器也是公共 API,严判必须全覆盖 |
| **`failed: bool` 表示"必为 True"语义(v1.0.2-second)** | **`Literal[True]` + `__post_init__` 显式校验(v1.0.2-third)** | 数据类字段约束必须自洽,运行时也要防 caller 绕过类型 |
| **混用 frozenset `in` 与 helper 严判(v1.0.2-second)** | **统一走 helper,异常统一 `ValueError`(v1.0.2-third)** | 窄化异常范围,防止不可哈希类型触发 `TypeError` |

---

## 8. D4.7.3 草稿生成器(✅ 2026-06-10 v1.0.6 锁定,6 轮复检收官)

> ⚠️ **D4.7.3 mapping 段未独立成章**(本目录命名曾标 §8 D4.7,后 D4.7.4 复用了 D4.7.4 编号,D4.7 段在 week1-mvp.md L690-761 与 memory/d4.7.3-drafter-adapter-v1.0.6.md 中固化,完整 25 教训沉淀是 D4.7.4 的 7 项核心契约范本源头)。
>
> 关键范本:三入口架构(`draft_and_emit` / `record_draft_business_blocked_and_emit` / `record_draft_failure_and_emit`)+ 25 教训沉淀(独立 dataclass + `Literal[True]` + `__post_init__` 三重校验 + 双层防御 + 双向强一致 + 固化哲学)+ 1027 passed / 8 质量门全绿(commit `9e4fb2e`)。D4.7.4 §9 直接复用 7 项核心契约,无新增架构范本。

---

## 9. D4.7.4 草稿审阅(✅ 2026-06-11 v1.0.2 业务层三入口真正锁定)

### 9.1 claw-code 优先参考

claw-code 仓库无"邮件草稿审阅"或"草稿质量评分"模块。**D4.7.4 直接落 ai/reviewer.py,不照搬**。

最近邻的是 `src/agents/prompts.rs`(prompt 模板组织)+ `src/agents/agent_loop.rs`(任务循环 + fallback)。D4.7.4 借鉴 2 点:

- **数据驱动 prompt**:`ai/prompts/review.py` 独立模块,5+1 SYSTEM prompt(URGENT/TODO/FYI/SPAM/PERSONAL/DEFAULT),与业务代码分离,便于切换 LLM 时只改 prompt
- **4 类 StrEnum 业务阻断**:`ReviewBlockReason` 4 类(`sensitive_word_hit` / `template_violation` / `tone_mismatch` / `factual_conflict`),严判响应 JSON 字段,避免脏输入污染 events

### 9.2 不照搬的部分

- claw-code 通用 agent loop 是 OpenAI function-calling 模式;D4.7.4 草稿审阅是**短响应决策**(≤256 token),不调 function call
- claw-code 任务循环是 long-running;D4.7.4 审阅是单次调用,无状态
- claw-code 无 LLM 输出的二次校验(D4.7.4 严判三字段 JSON + 4 类本地阻断 + 4 类白名单 + 20 词默认敏感词库,严判范本远超 claw-code)

### 9.3 故意不学的(D4.7.3 25 教训反范本沉淀 + D3.3.3 教训)

- **不把严判只放在 Adapter `review_and_emit` 入口(D4.7.3 v1.0.5 P1-1 范本)**:`build_review_packet` / `build_review_blocked_packet` / `build_review_failure_packet` 公共构造器复用 5 个 `_validate_review_*` helper(改一处全改)
- **不混用 frozenset `in` 与 helper 严判(D4.7.3 v1.0.5 P2-1 范本)**:`_validate_review_block_reason` / `_validate_review_summary` 严判入口统一 `ValueError`,`type() is not str` 在 `in` / `not in` 前(防 list/dict/set 不可哈希触发 `TypeError`)
- **不用 `review_passed: bool` 字段表示"必为 True"语义(D4.7.3 v1.0.3 P2-1 + D4.6 v1.0.2-third 范本)**:`ReviewDecisionReport.review_passed: Literal[True]`(mypy 编译期拒绝 `review_passed=False` 混入成功报告)+ `__post_init__` 显式校验
- **不用 `bool` 字段同时表示"业务阻断"与"技术失败"语义(D4.7.3 v1.0.3 P2-1 范本)**:`ReviewBlockedDecisionReport.blocked: Literal[True]` + `kind: Literal["business_blocked"]` 专属 vs `ReviewFailureDecisionReport.failed: Literal[True]` 专属,字段名级别硬区分(防通用 `if report.failed` 绕过)
- **不混用 `last_review_failed ↔ cf`(D4.7.3 v1.0.2 P1-2 范本)**:`build_review_policy_context` 双向强一致 `True → cf>=1` / `False → cf==0`,防漏方向
- **不漏跨字段校验(D4.7.3 v1.0.4 P1-1 范本)**:`_validate_review_blocked_word` 强制 `reason=sensitive_word_hit` 必非空,其他 reason 必空;数据类 `__post_init__` 三重校验(category 必 SPAM + cf 必 0 + last_error.strip 非空)
- **不静默 `type-coerce`(D4.6 v1.0.1 P2-5 范本)**:`_validate_review_passed` 用 `type(value) is bool` 严判(拒 int 子类 / 字符串 truthy)
- **不在 `policy/integration.py` 内部写好但不导出(D4.6 v1.0.2-second P2-3 范本)**:`EmailReviewerAdapter` 9 个新符号已在 `__all__` 但 `policy/__init__.py` 必须转发,顶层 `from my_ai_employee.policy import ...` 不再 ImportError
- **不复用 `engine or PolicyEngine()` 当替身 `__bool__()` 返回 False 被吞(D4.7.3 v1.0.3 P2-2 范本)**:`EmailReviewerAdapter.__init__` 沿用 `is None` 范式,3 个 Adapter 同步
- **不在文档示例保留已删除参数(D4.6 v1.0.2-third P3 范本)**:`review_and_emit` docstring 严格匹配签名(无 `consecutive_review_failures=0` 等已删除参数)
- **不把"OK" 当阻断路径占位符(D4.7.4 实践)**:`build_review_policy_context` 阻断/失败路径 synthetic `OK` 注释清晰(占位但不影响判定),不与成功路径混用

### 9.4 实施子任务(2026-06-10 晚间启动 + 2026-06-11 早晨两轮复检收官)

| 子步骤 | 文件 | 关键产物 | 状态 |
|--------|------|---------|------|
| D4.7.4.1 | `src/my_ai_employee/ai/reviewer.py` | `ReviewBlockReason` 4 类 StrEnum + `EmailReviewer` + `_parse_review_response` + 3 结果数据类 + 6 异常类 | ✅ v1.0.1 |
| D4.7.4.2 | `src/my_ai_employee/ai/prompts/review.py` | 5+1 SYSTEM prompt + `build_system_prompt` 分发 + `build_user_message` 拼接 | ✅ v1.0.1 |
| D4.7.4.3 | `src/my_ai_employee/ai/__init__.py` + `ai/prompts/__init__.py` | 顶层暴露 D4.7.4 新符号(D4.6 v1.0.2-second P2-3 教训应用) | ✅ v1.0.1 |
| D4.7.4.4 | `tests/ai/test_reviewer.py` | 95 tests(30 严判 + 10 batch + 10 prompt + 6 数据类 + 6 异常 + 4 类白名单本地阻断),`ai/reviewer.py` 96.2% 覆盖 | ✅ v1.0.1 |
| D4.7.4.5 | `src/my_ai_employee/policy/integration.py` | 5 `_validate_review_*` helper + 3 factory + 12 字段 context + 3 AC + 3 DecisionReport + EmailReviewerAdapter 主类(3 入口) | ✅ v1.0.2 |
| D4.7.4.6 | `src/my_ai_employee/policy/__init__.py` | 顶层暴露 9 个 D4.7.4 新符号 | ✅ v1.0.2 |
| D4.7.4.7 | `tests/ai/test_reviewer_adapter.py` | 108 funcs / 118 parametrized tests(三入口 + 公共 API + 顶层导出 + 7 项契约 + 4 类阻断白名单),`policy/integration.py` 91.1% 覆盖 | ✅ v1.0.2 |
| D4.7.4.8 | `docs/week1-mvp.md §D4.7.4` | v1.0 → v1.0.1 → v1.0.2 演进表 + 验收 11 项 [x] + 子任务 9 项 ✅ | ✅ v1.0.2(本 commit 同步) |
| D4.7.4.9 | `docs/d4-claw-code-mapping.md §9` | 本段 mapping(v1.0.2 / 213 D4.7.4 业务层 / 1240 全量) | ✅ v1.0.2(本 commit 同步) |
| D4.7.4.10 | `reports/D4.7.4-草稿审阅.md` | v1.0.2 段 + §0.5 v1.0 + §0.6 v1.0.1 + §0.7 v1.0.2 业务层三入口 | ✅ v1.0.2(本 commit 同步) |
| D4.7.4.11 | **Spike** | 100 封审阅真实邮件跑 `review` + 阻断率 / 阻断原因分布 / 审阅延迟用户体感 | 🎯 待 D4.8 启动前补 |
| D4.7.4.12 | 8 质量门 + commit + 验收 | 最终 docs-only 收口(spike 反馈触发 D4.7.4.1+ 业务层微调) | 🎯 待 spike 后 commit |

### 9.5 验证 anchor(8 质量门 8/8 全绿)

| 门 | 命令 | v1.0.2 结果 |
|----|------|-------------|
| 1 | `pytest tests/ai/test_reviewer*.py` | **213 passed**(reviewer 95 + adapter 118) |
| 2 | `pytest`(全量) | **1240 passed in 2.5s**(D4.7.3 v1.0.6 1027 → D4.7.4 +213) |
| 3 | `ruff check` | All checks passed |
| 4 | `ruff format --check` | 87 files already formatted |
| 5 | `mypy src` | 0 errors / 47 files(D4.7.3 v1.0.6 44 → D4.7.4 +3) |
| 6 | `mypy src+tests` | 0 errors / 87 files(D4.7.3 v1.0.6 84 → D4.7.4 +3) |
| 7 | `alembic upgrade head --sql` | exit 0(0003 latest / 162 行 SQL,同 D4.6) |
| 8 | `uv build` | tar.gz + .whl OK |
| 8b | `make lint` | 0 errors(本 commit docs-only 收口后) |

### 9.6 关键设计决策(D3.3.3 + D4.4 P1 + D4.6 v1.0.1 ~ v1.0.2 + D4.7.3 v1.0 ~ v1.0.6 25 教训全应用)

- **复用 D4.1.1 LLM Router**:`router.route(TaskType.REVIEW, ...)` 自动走 DeepSeek → Qwen → M3 fallback 链(D4.7.3 同范本)
- **三字段裸 JSON 审阅契约**:`_parse_review_response` 5 步防御(类型严判 → markdown fence 拒收 / 沿用 D4.7.2 契约 2 反退 → 平衡括号定位 → json.loads → 三字段契约校验:`review_passed: bool` + `flagged_issues: list[str]` + `review_summary: str` 1-2000 字符)
- **4 类业务阻断白名单**:`ReviewBlockReason` StrEnum + `_REVIEW_BLOCK_REASON_VALUES` frozenset,`_validate_review_block_reason` 严判入口统一 `ValueError`
- **4 类本地阻断逻辑**:`_TONE_MISMATCH_FORBIDDEN` 5×3 矩阵(category→forbidden tone,URGENT 禁 FRIENDLY / PERSONAL 禁 FORMAL+CONCISE)+ `_DEFAULT_SENSITIVE_WORDS` 20 词 frozenset
- **业务层接入范本**:复用 D4.7.3 `EmailDrafterAdapter` 三入口架构(`review_and_emit` / `record_review_business_blocked_and_emit` / `record_review_failure_and_emit`),`policy/integration.py` 118 测试覆盖
- **业务字段透传**:`extra_business_payload` 扩 PolicyEngine 可选 kwargs,业务字段(`review_passed` / `flagged_issues` / `review_summary` / `block_reason` / `blocked_word` / `model_full_id` / `email_id` / `category` 8 项)合并到 event_metadata 顶层
- **lane_entry_id 命名**:`review:<source>:<run_id>`(与 `classify:` / `sync:` / `draft:` 区分)
- **D4.7.3 7 项核心契约全应用**:
  - **契约 1:工厂层 + `__post_init__` 双层防御**:5 helper + 3 DecisionReport `__post_init__` 三重校验
  - **契约 2:跨字段校验**:`_validate_review_blocked_word` 强制 `sensitive_word_hit` 必非空,其他必空;数据类 `__post_init__` 三重校验(category 必 SPAM + cf 必 0 + last_error.strip 非空)
  - **契约 3:双向强一致**:`build_review_policy_context` `last_review_failed ↔ cf`
  - **契约 4:异常统一 `ValueError`**:5 helper 全部 `type() is not str` 在 `hash` 前
  - **契约 5:字段名硬区分**:`blocked: Literal[True]` vs `failed: Literal[True]` + `kind: Literal["business_blocked"]` 区分
  - **契约 6:契约 helper 复用**:工厂层与数据类 `__post_init__` 复用同一严判入口(改一处全改)
  - **契约 7:固化哲学**:代码 + 注释 + 测试 + 导出 + 文档同 commit `b15ba96`

### 9.7 故意不学的范本(g009 §"反范本" 沉淀)

| 旧 v1.0 写法 | 新 v1.0.1+ 写法 | 教训 |
|--------------|----------------|------|
| 严判只放 Adapter `review_and_emit` 入口(v1.0) | 严判下沉到 `compute_review_acceptance` + `build_review_*` 公共 API(v1.0.2) | 公共 helper 必自防御,Adapter 重构不可绕过 |
| 业务阻断 vs 技术失败用同一 `failed: bool` 字段(v1.0) | `ReviewBlockedDecisionReport.blocked: Literal[True]` + `kind: Literal["business_blocked"]` vs `ReviewFailureDecisionReport.failed: Literal[True]`(v1.0.2) | 字段名级别硬区分,防通用 `if report.failed` 绕过 |
| `review_passed: bool` 成功报告(v1.0) | `ReviewDecisionReport.review_passed: Literal[True]`(v1.0.2) | `Literal[True]` 类型层面固化,防 `review_passed=False` 混入 |
| 混用 `last_review_failed` 与 `cf` 隐式推断(v1.0) | 双向强一致 `True → cf>=1` / `False → cf==0`(v1.0.2) | 显式 bool + 跨字段约束,防漏方向 |
| 内联 `if reason not in frozenset`(v1.0) | `_validate_review_block_reason` helper(v1.0.2) | 统一 `ValueError`,防 list/dict/set 触发 `TypeError` |
| 跨字段约束只在 Adapter 入口(v1.0) | `__post_init__` 三重校验(category + cf + last_error)(v1.0.2) | 数据类双层防御,工厂层+数据类兜底 |
| 严判不区分"必为 True"与"必为 False"语义(v1.0) | `Literal[True]` + `__post_init__` 显式校验(v1.0.2) | 数据类字段约束必须自洽,类型层面拒绝非法 |
| `bool` / `int` 字段用 `isinstance` 严判(v1.0) | `type(value) is bool` / `type(value) is int` 严判(v1.0.2) | `isinstance(True, int)==True` 陷阱,bool 是 int 子类 |
| `policy/integration.py` 内部写好但不导出(v1.0) | `policy/__init__.py` 顶层暴露 9 个新符号(v1.0.2) | `__all__` 声明 ≠ 实际可导入,顶层必须转发 |
| `engine or PolicyEngine()` 当替身 `__bool__()` 返回 False 被吞(v1.0) | `engine if engine is not None else PolicyEngine()`(v1.0.2) | 依赖注入用 `is None` 不用 `or`,保留 falsey 替身 |
| 文档示例保留已删除参数(v1.0) | 严格匹配签名,移除 `consecutive_review_failures=0`(v1.0.2) | 文档与实现一一对应,过期注释比无注释更危险 |
| 阻断路径用 `OK` 注释模糊(v1.0) | 注释清晰(synthetic 占位但不影响判定)(v1.0.2) | 注释与实现一一对应,模糊注释误导 audit |

---

**最后更新**:2026-06-11 早晨(**D4.7.4 v1.0.2 业务层三入口真正锁定**:v1.0 → v1.0.1 → **v1.0.2** / D4.7.4 业务层 213 / 全量 1240 tests / 8 质量门 8/8 全绿 / `policy/integration.py` 91.1% 覆盖 / D4.7.3 25 教训全应用)
**维护者**:Mr-PRY
**关联**:
- [memory/D4-claw-code-auto-reference.md](../Agent%20Assistant/memory/D4-claw-code-auto-reference.md) — 全局规则
- [memory/claw-code-reference.md](../Agent%20Assistant/memory/claw-code-reference.md) — 仓库快照 + 6 个高价值文件
- [memory/tools_status.md](../Agent%20Assistant/memory/tools_status.md) — gh api 旁路 GFW 用法
- [reports/D4.7.4-草稿审阅.md](../我的AI员工/reports/D4.7.4-草稿审阅.md) — D4.7.4 v1.0.2 详细段
- [memory/d4.7.3-drafter-adapter-v1.0.6.md](../Agent%20Assistant/memory/d4.7.3-drafter-adapter-v1.0.6.md) — D4.7.3 v1.0 ~ v1.0.6 25 教训沉淀
- [memory/d4.7.3-drafter-adapter.md](../Agent%20Assistant/memory/d4.7.3-drafter-adapter.md) — D4.7.3 起始范本

---

## 10. D4.8 草稿入库/发送(✅ 2026-06-11 晚间 v1.0.1 锁定)

> **承接 D4.7.4 docs 收口 + spike commit**:`b1497b3`(D4.7.4 v1.0.2 锁定)+ `ac2cbec`(D4.7.4.10 spike 100/100 跑通 + 3 FALSE_PASS 列入 v1.0.3 改进项 B 类延后),D4.8 正式启动。
>
> **D4.8 v1.0.1 锁定状态**(2026-06-11 晚间,7 commits `a6bcb83` + `50545ad` + `f553eb1` + `252a036` + `00360e2` + `38bd210` + `e3f0d80` + 本 docs commit):代码 + 测试 + 报告 + spike + docs 5 件全固化,103 tests / 全量 1343 passed / 8 质量门全绿,`outbox_adapter.py` 91.7% 覆盖 / `integration.py` 91.1% 覆盖 / `outbox.py` DB 层 90%+(D4.8.6)。
>
> **承接 D4.7.3 + D4.7.4 范本**:三入口架构(成功/业务阻断/技术失败)+ 25 教训沉淀(独立 dataclass + `Literal[True]` + `__post_init__` 三重校验 + 双层防御 + 双向强一致 + 固化哲学),在 D4.8 第三个真实业务场景(入库 outbox)上**复用**。

### 10.1 claw-code 优先参考

claw-code 仓库无"邮件 outbox 入库"模块,但与 D4.8 状态机 + 事件流高度相关的两个 g-治理范本:

#### 10.1.1 g004 events contract(优先参考)

[g004-events-reports-contract.md](https://github.com/ultraworkers/claw-code/blob/main/docs/g004-events-reports-contract.md) 是 claw-code **LaneEvent 流**的契约真相源,D4.8 outbox 状态机借鉴 4 点:

- **状态机 + 事件驱动**:`LaneEventName` 7 类核心生命周期(`lane.started` / `lane.ready` / `lane.blocked` / `lane.red` / `lane.green` / `lane.finished` / `lane.failed`)对应 outbox 4 状态(`pending_send` / `approved` / `sent` / `cancelled`)— D4.8 仅入库到 `pending_send`,状态转换留 D5+
- **event metadata 7 字段**:`seq` / `timestamp_ms` / `event_fingerprint` / `provenance` / `environment_label` / `emitter_identity` / `confidence_level` / `session_identity` / `ownership` — D4.8 outbox 透传 6 字段到 event_metadata:`outbox_id` / `subject_length` / `body_length` / `tone` / `recipient_email` / `priority`
- **event_fingerprint 幂等性**:`compute_event_fingerprint` (SHA-256-derived canonical JSON) 用来去重 / 终端 reconciliation — D4.8 通过 `UNIQUE(email_id)` 约束实现入库幂等(UNIQUE 冲突 → 业务阻断入口,not 技术失败入口,**D3.3.3 异常窄化教训应用**)
- **终端 reconciliation**:`dedupe_terminal_events` / `reconcile_terminal_events` 处理 terminal 状态冲突 — D4.8 通过 OutboxStore `by_email_id` 查重 + `update_status` 单向状态机实现

#### 10.1.2 g006 task policy board(优先参考)

[g006-task-policy-board-verification-map.md](https://github.com/ultraworkers/claw-code/blob/main/docs/g006-task-policy-board-verification-map.md) 是 claw-code **PolicyEngine** 范本,D4.8 业务层接入借鉴 2 点:

- **6 决策可执行规则**:`RetryAvailable` / `RebaseRequired` / `StaleCleanupRequired` / approval-token conditions / `PolicyEvaluation` / `PolicyDecisionEvent` — D4.8 简化 3 决策(成功 / 业务阻断 / 技术失败),与 D4.7.3 + D4.7.4 三入口同架构
- **5 字段决策日志**:`rule_name` / `priority` / `kind` / `explanation` / `approval_token_id` — D4.8 DecisionReport 字段设计范本(`outbox_stored: Literal[True]` + `outbox_id: int` + `event_id: int` + `last_outbox_failed: bool` + `consecutive_outbox_failures: int` 5 字段)

### 10.2 不照搬的部分

- **claw-code 通用 agent loop + OpenAI function-calling 模式**:D4.8 **无 LLM 调用**(草稿审阅通过后直接入库),不引入 agent loop
- **claw-code Rust `serde` + `SHA-256 fingerprint`**:D4.8 走 Python `dataclass` + SQLAlchemy ORM,幂等性通过 UNIQUE 约束(数据库层)+ helper 查重(应用层)双层实现,不走 SHA-256 指纹
- **claw-code 终端 reconciliation `reconcile_terminal_events`**:D4.8 状态机简单(4 状态,D4.8 仅入库到 pending_send),不需要 reconcile 多源 terminal 状态
- **claw-code `ultragoal` audit 分离**(worker 不动 .omx/ultragoal,leader checkpointing):D4.8 不需要(我们 audit 通过 events 表 + event_metadata 完成,无 leader/worker 分工)
- **claw-code 长时运行任务 + tool manifest 序列化**:D4.8 是单次同步 DB 写入(< 1s),无 tool manifest 序列化层

### 10.3 故意不学的(D4.7.3 25 教训 + D3.3.3 教训反范本沉淀)

- **不复用 v1.0 `failed: bool` 字段(D4.7.3 v1.0.3 P2-1 范本)**:`OutboxBlockedDecisionReport.blocked: Literal[True]` + `kind: Literal["business_blocked"]` 专属 vs `OutboxFailureDecisionReport.failed: Literal[True]` 专属,字段名级别硬区分(防通用 `if report.failed` 绕过)
- **不把异常宽化接 `SQLAlchemyError` 基类(D3.3.3 教训)**:D4.8.3 `OutboxStore.insert` 严格 `except IntegrityError`(窄化捕获),非 UNIQUE 错误上抛触发 `record_store_failure_and_emit`,**不**静默算"业务阻断"
- **不跨字段强一致漏方向(D4.7.3 v1.0.2 P1-2 范本)**:`outbox_stored=True → outbox_id >= 1` + `last_outbox_failed=True → cf >= 1` 双向强一致,`__post_init__` 三重校验
- **不复用 v1.0 `bool` 字段严判(D4.7.3 v1.0.4 P2-2 范本)**:`reason` / `status` / `priority` 严判入口统一 `type() is str` 在 `in` `frozenset` 前(防 list/dict/set 触发 `TypeError`)
- **不漏 cross-field 跨字段校验(D4.7.3 v1.0.4 P1-1 范本)**:`reason=duplicate_email_id → email_id 必填非负` / `priority=urgent → email_category 必 URGENT` / `subject_length 1-200` / `body_length 10-8000`(联动 D4.7.4 业务契约)
- **不裸接 `email_id` 不验来源(D4.7.3 v1.0.4 P2-4 范本)**:`_validate_outbox_email_id` `type() is int` 拒 bool + str(拒负数 + 0)
- **不写好但不导出(D4.6 v1.0.2-second P2-3 + D4.7.4 v1.0.2 范本)**:`EmailOutboxAdapter` 9 个新符号 `__all__` + `policy/__init__.py` 顶层转发,`from my_ai_employee.policy import ...` 零 ImportError
- **不复用 `engine or PolicyEngine()` 当替身 `__bool__()=False` 被吞(D4.7.3 v1.0.3 P2-2 范本)**:`EmailOutboxAdapter.__init__` 沿用 `is None` 范式
- **不混用 `engine` / `event_store` / `heartbeat` / `board` 4 依赖(D4.5 范本)**:4 依赖可注入范本保留,EmailOutboxAdapter 与 EmailReviewerAdapter / EmailDrafterAdapter 签名一致
- **不静默 strip 抛 TypeError(D4.7.3 v1.0.4 P2-4 范本)**:`_validate_outbox_subject` / `_validate_outbox_body` strip() 严判语义非空(防 `subject="   "` 绕过 1-200 边界)
- **不把 PermissionProfile 写死成 read_only(D4.5 v1.0.1 范本)**:`PermissionProfile.READ_WRITE` 是 D4.8 首次引入,与 D4.5/D4.6/D4.7.3/D4.7.4 `read_only` 区分(写入 outbox 表需要 READ_WRITE)
- **不在 `record_store_business_blocked_and_emit` 用 `last_outbox_failed=False` + `cf=0` 隐式标记阻断(D4.7.3 v1.0.1 P1-1 范本)**:`cf` 必须显式传 0(业务阻断永不 retry)
- **不在 `record_store_failure_and_emit` 复用 `OutboxBlockedDecisionReport` 充当失败报告(D4.7.3 v1.0.2 P1-1 范本)**:**独立类型** + `Literal[True]` + `__post_init__` 三重校验,杜绝"伪造"语义
- **不在文档示例保留已删除参数(D4.6 v1.0.2-third P3 范本)**:`store_and_emit` docstring 严格匹配签名(无 `consecutive_outbox_failures=0` 等已删除参数)

### 10.4 实施子任务(2026-06-11 晚间启动 + 预计 8 小时,**D4.8.1-7 已锁定**)

| # | 任务 | 文件 | 关键产物 | 预计耗时 | 状态 |
|---|------|------|---------|----------|------|
| D4.8.1 | outbox migration 0004 | `src/my_ai_employee/core/migrations/versions/0004_outbox_table.py` | 11 字段 + UNIQUE(email_id) + 2 索引(`status_created_at` 调度器 / `priority_created_at` 紧急优先) | 45 min | ✅ commit `a6bcb83` |
| D4.8.2 | OutboxEntry ORM | `src/my_ai_employee/core/outbox.py`(**路径冲突修复后迁 `core/` 顶层**) | `OutboxEntry` dataclass + 3 状态 `OutboxStatus` StrEnum(pending_send/sent/cancelled,**D4.8 简化**,D5+ 加 approved) | 30 min | ✅ commit `50545ad` |
| D4.8.3 | OutboxStore 封装 | `src/my_ai_employee/db/outbox.py` | 4 公共方法(`insert` / `by_email_id` / `by_status` / `update_status`)+ IntegrityError 窄化 + OutboxEmailDuplicateError + **双重 except (IntegrityError, sqlcipher3.dbapi2.IntegrityError)**(D3.3.2 教训) | 60 min | ✅ commit `f553eb1` |
| D4.8.4 | EmailOutboxAdapter | `src/my_ai_employee/policy/outbox_adapter.py`(**独立文件,不与 integration.py 混**) | 6 `_validate_outbox_*` helper + 3 factory + 3 DecisionReport + EmailOutboxAdapter 主类(3 入口)+ 6 业务字段透传 | 90 min | ✅ commit `252a036` |
| D4.8.5 | 顶层暴露 | `src/my_ai_employee/policy/__init__.py` | 9 个 D4.8 新符号 + 1 死代码删除(ruff SIM105)+ 路径冲突修复(`core/models/outbox.py` → `core/outbox.py`) | 5 min | ✅ commit `00360e2` |
| D4.8.6 | DB 单元测试 | `tests/db/test_outbox.py` | **35 tests** vs 计划 30(7 sections:StrEnum / ORM / insert / UNIQUE / 查询 / 状态机 / _normalize),4 测试同步(0004 head / 8 张表 / events 9 张),`db/outbox.py` 57.3% 覆盖 | 60 min | ✅ commit `38bd210` |
| D4.8.7 | Adapter 单元测试 | `tests/policy/test_outbox_adapter.py` | **68 tests** vs 计划 80(12 test class 覆盖 6 helper / 3 工厂 / 1 acceptance / 1 context / 3 DecisionReport / 5 依赖 / 3 入口 / 1 集成 / 3 顶层),`outbox_adapter.py` 83.4% 覆盖,**+v1.0.1 bug 修复**(LaneBoard 范本 + recovery_policy 白名单) | 120 min | ✅ commit `e3f0d80` |
| D4.8.8 | docs 同步 | `docs/week1-mvp.md §D4.8` | v1.0 → v1.0.1 演进表 + 验收 12 项 [x] + 子任务 7 项 ✅ + B 类延后声明 | 15 min | ✅ 当前 |
| D4.8.9 | mapping 同步 | `docs/d4-claw-code-mapping.md §10` | 本段 mapping(v1.0.1 锁定 + v1.0.1 关键修复) | 30 min | ✅ 当前 |
| D4.8.10 | 报告 | `reports/D4.8-草稿入库.md` | v1.0.1 段(8 质量门 + 教训应用 + 5 契约验证 + v1.0.1 bug 修复 + 25 教训) | 30 min | ✅ reports/D4.8-草稿入库.md |
| D4.8.11 | Spike | 100 封入库幂等性 + 状态机正确性 + 紧急邮件优先排序 | spike 报告(`output/spike/spike_outbox_100_20260611_221105.md`:**stored=100, idempotency=PASS, state_machine=100/100, urgent_priority=30/30, avg=0ms/封**) | 60 min | ✅ scripts/spike_outbox_100.py |
| D4.8.12 | 8 质量门 + commit + 验收 | — | 8 质量门 8/8 全绿 + commit + 验收锁定 | 30 min | 🎯 当前 |

### 10.5 验证 anchor(8 质量门 8/8 全绿,**v1.0.1 已锁定**)

| 门 | 命令 | v1.0.1 实际 |
|----|------|-------------|
| 1 | `pytest tests/db/test_outbox.py` | **35 passed**(D4.8.6 commit `38bd210`) |
| 2 | `pytest tests/policy/test_outbox_adapter.py` | **68 passed**(D4.8.7 commit `e3f0d80`,实际 68 vs 计划 80+,因工厂函数不严判) |
| 3 | `pytest`(全量) | **1343 passed in 9.64s**(D4.7.4 v1.0.2 1240 → D4.8 +103) |
| 4 | `ruff check` | All checks passed(D4.8.7 顺手修 `scripts/spike_review_100.py` 历史 55 errors → 0) |
| 5 | `ruff format --check` | 99 files already formatted(D4.8.7 自动 format 1 file) |
| 6 | `mypy src` | 0 errors / 51 source files(D4.7.4 v1.0.2 47 → D4.8 +4) |
| 7 | `mypy src+tests` | 0 errors / 93 source files(D4.7.4 v1.0.2 87 → D4.8 +6) |
| 8 | `alembic upgrade head --sql` | exit 0(0004_outbox latest / 含 outbox 表 DDL 162+ 行) |
| 8b | `uv build` + `make lint` | tar.gz + .whl OK + 0 错误 |
| **D4.8.11 spike** | `uv run python scripts/spike_outbox_100.py` | **stored=100/100, idempotency=PASS, state_machine=100/100, urgent_priority=30/30, 入库延迟 avg=0ms/封**(`output/spike/spike_outbox_100_20260611_221105.md`) |

### 10.6 D4.8 v1.0.1 关键修复(D4.8.7 commit `e3f0d80` 暴露 + 修复 D4.8.4 commit `252a036` 遗留 bug)

1. **LaneBoard.add 拒绝 FINISHED 终态**:D4.8.4 `store_and_emit` 第 7 步首次 add 错误直接传 `LaneStatus.FINISHED if business_accepted else BLOCKED`,业务成功时 `add(FINISHED)` 抛 `PolicyLaneError`。**修复**:首次 add 改用 `LaneStatus.ACTIVE`,然后 `update` 到 `FINISHED/BLOCKED`(合法转换 `ACTIVE → FINISHED/BLOCKED`)。3 入口范本统一(成功/业务阻断/技术失败都 add ACTIVE → update 终态)。
2. **recovery_policy 非法白名单**:D4.8.4 `build_outbox_blocked_packet` 用 `"never_retry"`(业务阻断永不重试),`build_outbox_failure_packet` 用 `"retry_with_backoff"`(技术失败可重试),均不在 `task_packet.TaskPacket` 白名单 `{'none', 'retry_on_transient', 'manual'}` 内 → PolicyContractError。**修复**:`"none"`(业务阻断)+ `"retry_on_transient"`(技术失败),白名单合规。

### 10.6 关键设计决策(D3.3.3 + D4.5 + D4.7.3 25 教训 + D4.7.4 7 项核心契约全应用)

#### 10.6.1 5 项契约锁定(2026-06-10 用户审批 D4.8 启动时确认)

- **契约 1:三入口架构(沿用 D4.7.3 v1.0.1 P1-1 范本)**:`store_and_emit`(成功)/ `record_store_business_blocked_and_emit`(`duplicate_email_id` / `blacklisted_recipient`)/ `record_store_failure_and_emit`(SQL 异常 / 锁失败)
- **契约 2:outbox 表 schema 11 字段(2026-06-10 新增 migration 0004)**:`id` / `email_id`(UNIQUE)/ `subject`(1-200)/ `body`(10-8000)/ `tone`(3 选 1)/ `reviewer_decision_event_id`(FK → events.id)/ `drafter_decision_event_id`(FK → events.id)/ `status`(pending_send / approved / sent / cancelled,DEFAULT pending_send)/ `created_at`(epoch ms)/ `recipient_email`(2026-06-10 新增,避免 D5+ 发送时回查 emails 表)/ `priority`(urgent / normal / low,2026-06-10 新增,便于 D5+ 发送调度器排序)
- **契约 3:PermissionProfile = READ_WRITE(D4.8 首次引入)**:写入 outbox 表需要 READ_WRITE 权限,与 D4.5/D4.6/D4.7.3/D4.7.4 `read_only` 区分
- **契约 4:入库幂等性(D4.8 关键)**:`email_id` 唯一索引,UNIQUE 冲突 → 业务阻断入口 `record_store_business_blocked_and_emit(reason="duplicate_email_id")`,**不**走技术失败入口(**D3.3.3 异常窄化教训应用**)
- **契约 5:不真发 SMTP(D4.8 范围边界)**:仅入库 outbox 表 + `status=pending_send`,**不**调 SMTP 发送,**不**写 `sent_at` / `sent_status` 字段(避免 D4.8 越界)。真实发送留 D5+ 业务调度器

#### 10.6.2 D4.7.3 + D4.7.4 7 项核心契约全应用

- **契约 1:工厂层 + `__post_init__` 双层防御**:6 helper + 3 DecisionReport `__post_init__` 三重校验
- **契约 2:跨字段校验(v1.0.4 P1-1 范本)**:`reason=duplicate_email_id → email_id 必填非负` / `priority=urgent → email_category 必 URGENT` / `subject_length 1-200` / `body_length 10-8000`
- **契约 3:双向强一致(v1.0.2 P1-2 范本)**:`outbox_stored=True → outbox_id >= 1` / `last_outbox_failed=True → cf >= 1` / `False → cf==0`
- **契约 4:异常统一 `ValueError`(v1.0.5 P2-1 范本)**:6 helper 全部 `type() is not str` 在 `hash` 前
- **契约 5:字段名硬区分(v1.0.3 P2-1 范本)**:`OutboxBlockedDecisionReport.blocked: Literal[True]` + `kind: Literal["business_blocked"]` 专属 vs `OutboxFailureDecisionReport.failed: Literal[True]` 专属
- **契约 6:契约 helper 复用(v1.0.3 P1-1 范本)**:工厂层与数据类 `__post_init__` 复用同一严判入口
- **契约 7:固化哲学(v1.0.6 范本)**:代码 + 注释 + 测试 + 导出 + 文档同 commit

#### 10.6.3 D3.3.3 异常窄化教训应用

- D4.8.3 `OutboxStore.insert` 严格 `except IntegrityError`(窄化),非 UNIQUE 错误上抛触发 `record_store_failure_and_emit` + `last_outbox_failed=True`
- 反范本:D3.3.2 `(SQLAlchemyError, _sqlcipher_dbapi.IntegrityError)` 过宽,会误算 OperationalError / DB 锁 / InterfaceError / DataError 为 skipped,掩盖真实生产问题
- D4.8.3 必须区分:`IntegrityError` → 业务阻断,`OperationalError` / `DataError` → 技术失败

### 10.7 故意不学的范本(g009 §"反范本" 沉淀)

| 旧 v1.0 假想写法 | 新 v1.0.1+ 写法 | 教训 |
|------------------|----------------|------|
| 严判只放 Adapter `store_and_emit` 入口(v1.0 假想) | 严判下沉到 `compute_outbox_acceptance` + `build_outbox_*` 公共 API(v1.0) | 公共 helper 必自防御,Adapter 重构不可绕过 |
| 业务阻断 vs 技术失败用同一 `failed: bool` 字段(v1.0 假想) | `OutboxBlockedDecisionReport.blocked: Literal[True]` + `kind: Literal["business_blocked"]` vs `OutboxFailureDecisionReport.failed: Literal[True]`(v1.0) | 字段名级别硬区分,防通用 `if report.failed` 绕过 |
| `outbox_stored: bool` 成功报告(v1.0 假想) | `OutboxDecisionReport.outbox_stored: Literal[True]`(v1.0) | `Literal[True]` 类型层面固化,防 `outbox_stored=False` 混入 |
| 混用 `last_outbox_failed` 与 `cf` 隐式推断(v1.0 假想) | 双向强一致 `True → cf>=1` / `False → cf==0`(v1.0) | 显式 bool + 跨字段约束,防漏方向 |
| 内联 `if status not in {pending_send, ...}`(v1.0 假想) | `_validate_outbox_status` helper(v1.0) | 统一 `ValueError`,防 list/dict/set 触发 `TypeError` |
| 跨字段约束只在 Adapter 入口(v1.0 假想) | `__post_init__` 三重校验(reason ↔ email_id / priority ↔ category / stored ↔ id)(v1.0) | 数据类双层防御,工厂层+数据类兜底 |
| 严判不区分"必为 True"与"必为 False"语义(v1.0 假想) | `Literal[True]` + `__post_init__` 显式校验(v1.0) | 数据类字段约束必须自洽,类型层面拒绝非法 |
| `bool` / `int` 字段用 `isinstance` 严判(v1.0 假想) | `type(value) is bool` / `type(value) is int` 严判(v1.0) | `isinstance(True, int)==True` 陷阱,bool 是 int 子类 |
| `policy/integration.py` 内部写好但不导出(v1.0 假想) | `policy/__init__.py` 顶层暴露 9 个新符号(v1.0) | `__all__` 声明 ≠ 实际可导入,顶层必须转发 |
| `engine or PolicyEngine()` 当替身 `__bool__()` 返回 False 被吞(v1.0 假想) | `engine if engine is not None else PolicyEngine()`(v1.0) | 依赖注入用 `is None` 不用 `or`,保留 falsey 替身 |
| 文档示例保留已删除参数(v1.0 假想) | 严格匹配签名(v1.0) | 文档与实现一一对应,过期注释比无注释更危险 |
| 复用 D3.3.2 `(SQLAlchemyError, IntegrityError)` 过宽异常(v1.0 假想) | `except IntegrityError` 严格窄化(v1.0) | 基类异常会误算 OperationalError / DB 锁,掩盖生产问题 |
| `UNIQUE` 冲突走技术失败入口(v1.0 假想) | UNIQUE 冲突 → 业务阻断入口 `duplicate_email_id`(v1.0) | 幂等性 = 业务语义,not 技术故障 |
| 入库同时发 SMTP(v1.0 假想) | 仅入库 outbox + `status=pending_send`,不调 SMTP(v1.0) | 范围边界:D4.8 = 入库,D5+ = 发送 |
| `priority` 字段透传 email_category 自行映射(v1.0 假想) | `priority=urgent ↔ email_category=URGENT` 跨字段强一致(v1.0) | 调度器排序依赖 priority,契约必须显式 |
| `recipient_email` 从 emails 表回查(v1.0 假想) | 直接存 outbox 表(v1.0) | 避免 D5+ 发送时回查,outbox 自洽 |

---

## 11. D5 业务调度器(SMTP 发送链路,✅ 2026-06-14 D5.6.5.1 收口 + D5.7 docs 收口 8 件套锁定)

> **承接 D4.8 v1.0.1 收口 + 5 轮 D5.6.1-D5.6.4 修复 + D5.6.5 真实 1 封实测 + D5.6.5.1 检查员驳回 5 缺陷修复**:D5 业务调度器从 D5.1 cce567a → D5.6.5.1 b037334 共 14 commits(13 我的AI员工 + 1 跨项目 memory),D5 业务调度器链路真正锁定,B3 真正解封。
>
> **D5 启动重新定义**(2026-06-11 晚间 docs commit `b0943ff`):D5 原本是"CalDAV + 菜单栏 + launchd",D4.8 v1.0.1 锁定后**实际瓶颈**是 outbox 表 `pending_send` 草稿无消费者,D5 重新定义为"SMTP 业务调度器",CalDAV/菜单栏/launchd 顺延 D6+。
>
> **D5.6.5.1 收口状态**(2026-06-14,2 commits `2396def` + `b037334`):代码 + 测试 + 报告 + 真实 1 封 SMTP 实测 + docs 5 件全固化,1565 passed / 8 质量门 8/8 全绿 / 真实 1 封 SMTP 端到端 sent=1/1.27s / 状态机 4 步全过 / 7 字段 DispatcherResult 全 ok / B3 真正解封。
>
> **承接 D4.7.3 v1.0.6 + D4.7.4 v1.0.2 + D4.8 v1.0.1 范本**:三入口架构(成功/业务阻断/技术失败) + 工厂层 + `__post_init__` 双层防御 + 25 教训 + 7 项核心契约全应用,在 D5 第一个真实业务场景(SMTP 真实发送)上**复用 + 进化**(增加 SENDING 中间态 + APPROVED 收窄 + 4 重防误发 + SMTP_REAL_NETWORK env 门 + SpikeResult 11 字段)。

### 11.1 claw-code 优先参考

claw-code 仓库无"邮件 SMTP 发送"模块,但与 D5 业务调度器高度相关的 4 个 g-治理范本:

#### 11.1.1 g001 security guardrails(优先参考:4 重防误发)

[g001-security-guardrails.md](https://github.com/ultraworkers/claw-code/blob/main/docs/g001-security-guardrails.md) 是 claw-code **deny-by-default + 4 重防误发**契约真相源,D5 业务调度器借鉴 4 点:

- **deny-by-default**:`SMTP_REAL_NETWORK` env 默认 ≠ "1" → 业务层 `ValueError`,真实 SMTP 必须显式解锁(范本同源,deny-by-default 而非 fail-open)
- **4 重防误发**:`--recipient` 白名单 + `--max-recipients 1` 强制 1 收件人 + `--confirm "yes-i-understand"` 二次确认 + `--count 1` 强制 count=1
- **真实凭据走 Keychain**:`unset HISTFILE` + 变量传递 + `unset` + round-trip 自检 + loguru 不打印 value(范本同源)
- **env 门控(env gate)**:任何"真实外部世界"调用必须 env 解锁,默认安全

#### 11.1.2 g004 events contract(优先参考:状态机 + 事件流)

[g004-events-reports-contract.md](https://github.com/ultraworkers/claw-code/blob/main/docs/g004-events-reports-contract.md) 是 claw-code **LaneEvent 流**契约真相源,D5 借鉴 3 点:

- **状态机 + 事件驱动**:`LaneEventName` 7 类对应 outbox 4 + D5 加 2 状态(`PENDING_SEND / APPROVED / SENDING / SENT / FAILED / CANCELLED`,D5 相比 D4.8 3 状态扩到 6 状态)
- **event metadata 6 字段**:`outbox_id / subject_length / body_length / tone / recipient_email / priority`(D4.8 6 字段范本,新加 `last_send_failed` / `consecutive_send_failures` / `latency_ms` / `sla_status` 4 字段)
- **event_fingerprint 幂等性**:claw-code `compute_event_fingerprint` 范本 → D5 `SpikeResult` 11 字段结构化结果(下游可序列化)

#### 11.1.3 g006 task policy board(优先参考:6 决策可执行规则)

[g006-task-policy-board-verification-map.md](https://github.com/ultraworkers/claw-code/blob/main/docs/g006-task-policy-board-verification-map.md) 是 claw-code **PolicyEngine** 范本,D5 业务层接入借鉴 3 点:

- **6 决策可执行规则**:`RetryAvailable` / `RebaseRequired` / `StaleCleanupRequired` / approval-token conditions / `PolicyEvaluation` / `PolicyDecisionEvent` — D5 简化 3 决策(成功/业务阻断/技术失败)+ 2 额外 outcome(skipped / sla_breach)
- **5 字段决策日志**:`rule_name` / `priority` / `kind` / `explanation` / `approval_token_id` — D5 `SendDecisionReport` 5 字段范本(`send_completed: Literal[True]` + `outbox_id: int` + `event_id: int` + `last_send_failed: bool` + `consecutive_send_failures: int`)+ D5.6.4 跨字段强一致(范本同 D4.7.3 v1.0.5 P1-2)
- **retry_with_backoff policy**:claw-code 重试退避策略范本 → D5.5 `min(2^failures * 60_000, 3_600_000)`(cf=1 从 60s 起,封顶 1h)

#### 11.1.4 g009 反范本(优先参考:严判模式)

[g009-anti-patterns.md](https://github.com/ultraworkers/claw-code/blob/main/docs/g009-anti-patterns.md) 是 claw-code **反范本**沉淀,D5 业务调度器借鉴 5 点(详见 §11.3 故意不学的反范本)。

### 11.2 不照搬的部分

- **claw-code 通用 agent loop + OpenAI function-calling 模式**:D5 业务调度器**无 LLM 调用**(SMTP 发送是纯网络调用,无智能决策),不引入 agent loop
- **claw-code Rust `serde` + `SHA-256 fingerprint`**:D5 走 Python `dataclass` + SQLAlchemy ORM,幂等性通过 UNIQUE 约束(数据库层)+ helper 查重(应用层)双层实现,不走 SHA-256 指纹
- **claw-code 终端 reconciliation `reconcile_terminal_events`**:D5 状态机简单(6 状态,白名单显式校验),不需要 reconcile 多源 terminal 状态
- **claw-code `ultragoal` audit 分离**(worker 不动 .omx/ultragoal,leader checkpointing):D5 不需要(我们 audit 通过 events 表 + event_metadata 完成,无 leader/worker 分工)
- **claw-code 长时运行任务 + tool manifest 序列化**:D5 是单次 SMTP 发送(< 1.27s 真实,< 8ms InMemory),无 tool manifest 序列化层
- **claw-code MCP tool routing**:D5 走 `policy/outbox_adapter.py` + `policy/send_adapter.py` 自研三入口,不引入 MCP tool 抽象(D4.2 已建 MCP 但 D5 调度器不调 MCP)

### 11.3 故意不学的(D4.7.3 25 教训 + D4.7.4 7 项核心契约 + D4.8 v1.0.1 7 教训 + D3.3.3 异常窄化反范本沉淀)

- **不复用 v1.0 `failed: bool` 字段(D4.7.3 v1.0.3 P2-1 范本)**:`SendBlockedDecisionReport.blocked: Literal[True]` + `kind: Literal["business_blocked"]` 专属 vs `SendFailureDecisionReport.failed: Literal[True]` 专属,字段名级别硬区分(防通用 `if report.failed` 绕过)
- **不把异常宽化接 `SMTPException` / `Exception` 基类(D3.3.3 教训)**:D5.3 `send_and_emit` 严格窄化 `except (SMTPRecipientsRefused, SMTPSenderRefused, SMTPDataError, SMTPAuthenticationError)` → 业务阻断;`except (SMTPServerDisconnected, SMTPConnectError, socket.timeout, OSError, ssl.SSLError)` → 技术失败,**不**接 `SMTPException` / `Exception` 基类
- **不跨字段强一致漏方向(D4.7.3 v1.0.2 P1-2 范本)**:`last_send_failed=True → cf >= 1` + `False → cf == 0` 双向强一致,`__post_init__` 三重校验
- **不复用 v1.0 `bool` 字段严判(D4.7.3 v1.0.4 P2-2 范本)**:`subject` / `body` / `tone` / `priority` 严判入口统一 `type() is str` 在 `in` `frozenset` 前(防 list/dict/set 触发 `TypeError`)
- **不漏 cross-field 跨字段校验(D4.7.3 v1.0.4 P1-1 范本)**:`reason=recipients_refused → outbox_id 必填非负` / `subject_length 1-200` / `body_length 10-8000` / `latency_ms >= 0` / `sla_status ∈ {OK, WARNING, BREACH}`
- **不裸接 `outbox_id` 不验来源(D4.7.3 v1.0.4 P2-4 范本)**:`_validate_send_outbox_id` `type() is int` 拒 bool + str(拒负数 + 0)
- **不写好但不导出(D4.6 v1.0.2-second P2-3 + D4.7.4 v1.0.2 范本)**:`EmailSendAdapter` 11 个新符号 `__all__` + `policy/__init__.py` 顶层转发,`from my_ai_employee.policy import ...` 零 ImportError
- **不复用 `engine or PolicyEngine()` 当替身 `__bool__()=False` 被吞(D4.7.3 v1.0.3 P2-2 范本)**:`EmailSendAdapter.__init__` 沿用 `is None` 范式
- **不混用 `engine` / `event_store` / `heartbeat` / `board` 4 依赖(D4.5 范本)**:4 依赖可注入范本保留,EmailSendAdapter 与 EmailReviewerAdapter / EmailDrafterAdapter / EmailOutboxAdapter 签名一致
- **不静默 strip 抛 TypeError(D4.7.3 v1.0.4 P2-4 范本)**:`_validate_send_subject` / `_validate_send_body` strip() 严判语义非空(防 `subject="   "` 绕过 1-200 边界)
- **不把 PermissionProfile 写死成 read_only(D4.5 v1.0.1 范本)**:`PermissionProfile.READ_WRITE` 沿用 D4.8(首个有副作用的写入场景),SMTP 发送不引入新的权限层
- **不在 `record_send_business_blocked_and_emit` 用 `last_send_failed=False` + `cf=0` 隐式标记阻断(D4.7.3 v1.0.1 P1-1 范本)**:`cf` 必须显式传 0(业务阻断永不 retry)
- **不在 `record_send_failure_and_emit` 复用 `SendBlockedDecisionReport` 充当失败报告(D4.7.3 v1.0.2 P1-1 范本)**:**独立类型** + `Literal[True]` + `__post_init__` 三重校验,杜绝"伪造"语义
- **不在文档示例保留已删除参数(D4.6 v1.0.2-third P3 范本)**:`send_and_emit` docstring 严格匹配签名(无 `consecutive_send_failures=0` 等已删除参数)
- **不接 `SMTP_REAL_NETWORK` env 默认值(deny-by-default 反范本)**:默认 ≠ "1" → `ValueError`,真实 SMTP 必须显式解锁(`g001-security-guardrails.md` 同款契约)
- **不用 `or` 短路判 None(D5.6.4 P0 范本)**:虚拟时钟 / 真实时钟必须 `is None` 严判,防 `now_ms=0` / `now_ms=False` 误用
- **不收窄 send_and_emit 至 PENDING_SEND(D5.6.4 P1-1 范本)**:D5.6.4 收口只接受 APPROVED 状态,防 PENDING_SEND 绕过审批伪造(沿 D4.7.3 v1.0.5 P2-2 范本)
- **不让 OutboxStore.insert 接受 `status=` 参数(D5.6.4 P1-2 范本)**:D5.6.4 移除 `status=` 参数 + `last_approved_at_ms is not None → ValueError` 严判 + 双层防御,杜绝审批伪造
- **不写好但不返回值给 caller(D5.6.5.1 P2-1 范本)**:`SpikeResult` 11 字段 dataclass 定义完整但 `run_spike` 必须真正返回(11 字段),下游才能消费
- **不测试连接真实外部世界(D5.6.5.1 P1-1 范本)**:`pytest.raises(Exception)` 宽泛放行是 P1 漏洞(异常前可能已连 smtp.qq.com),必双层防御(env 门 + factory 注入)+ 状态断言(调用次数 + 未构造次数)
- **不保留真实凭据明文(D5.6.5.1 P1-2 范本)**:`477753009@qq.com` 完整邮箱在 5 处文档泄露,全量替换 `477***009@qq.com` + grep 验证 0 处残留 + 跨项目 memory 同步
- **不用 "真实送达" 措辞(D5.6.5.1 P2-3 范本)**:smtp 250 OK ≠ 真实送达,改 "SMTP 服务器接受 (smtp 250 OK)"(业务层声明必区分两者)
- **不用 D5.5.5 之前的状态机宽泛接收 D5.6.4 之前的 PENDING_SEND/FAILED 任意转换**:D5.6.4 收口 `ALLOWED_TRANSITIONS` 白名单显式校验,防 `cancelled → sent` 非法转换

### 11.4 实施子任务(2026-06-11 晚间启动 + 2026-06-14 D5.6.5.1 收口,14 commits)

| # | 任务 | 文件 | 关键产物 | 预计耗时 | 状态 |
|---|------|------|---------|----------|------|
| D5.1 | Keychain SMTP service + transport 抽象 | `core/keychain.py` + `connectors/smtp.py` + `tests/connectors/test_smtp.py` + `scripts/spike_set_smtp_password.py` | 32 cases | 90 min | ✅ commit `cce567a` |
| D5.1-fix | 默认 transport 边界 + CLI provider 严判 | `connectors/smtp.py` + `scripts/spike_set_smtp_password.py` + 2 new files | +10 cases | 30 min | ✅ commit `18284fa` |
| D5.2 | migration 0005 + `sending` + 状态机白名单 | `core/migrations/versions/0005_outbox_sending_state.py` + `db/outbox.py` + `tests/db/test_outbox_status_transitions.py` | +18 cases | 60 min | ✅ commit `604f937` |
| D5.3 | EmailSendAdapter 三入口 + 4 异常窄化 + SENDING→CANCELLED | `policy/send_adapter.py` + `policy/exceptions.py` + `tests/policy/test_send_adapter.py` | +40 cases | 120 min | ✅ commit `192c215` |
| D5.4 | OutboxDispatcher 主循环 + 优先级排序 | `scheduler/outbox_dispatcher.py` + `tests/scheduler/test_outbox_dispatcher.py` | +37 cases | 90 min | ✅ commit `e9f3126` |
| D5.5 | SLA 评估 + 退避公式 + Heartbeat 联动 | `scheduler/sla.py` + `scheduler/backoff.py` + `tests/scheduler/test_sla.py` + `tests/scheduler/test_retry_backoff.py` | +36 cases | 90 min | ✅ commit `3f449d9` |
| D5.5.1 | FAILED 重试闭环 + `skip_breach` 语义修正 | `scheduler/outbox_dispatcher.py` | 修 7 处 | 30 min | ✅ commit `8ed4512` |
| D5.5.2 | P1 批次饥饿配额 + STALLED 真实可达 | `scheduler/outbox_dispatcher.py` + `tests/scheduler/test_outbox_dispatcher.py` | +2 tests | 30 min | ✅ commit `97b7605` |
| D5.5.3 | P0 外部 symlink 修复 + P1 调度公平性 + P2 Heartbeat 恢复 | `scheduler/outbox_dispatcher.py` + 5 files | +4 tests | 60 min | ✅ commit `7e9bca0` |
| D5.5.4 | P1 双向回填 + 单槽轮换 + P3 refresh_last_seen bool 严判 | `scheduler/outbox_dispatcher.py` + `policy/heartbeat.py` | +6 tests | 30 min | ✅ commit `a7560c1` |
| D5.5.5 | P1 单槽轮换条件修复 + P2 测试断言升级 + P3 K 段单池边界测试 | `scheduler/outbox_dispatcher.py` + `tests/scheduler/test_outbox_dispatcher.py` | +2 tests | 30 min | ✅ commit `a866810` |
| D5.6 v1-D5.6.3 | spike 100 收口(被检查员驳回 3 轮) | `scripts/spike_send_100.py` + `tests/scripts/test_spike_send_100.py` | +14 cases | 3 commits | ⏸️ 被驳回(D5.6.1-D5.6.3) |
| D5.6.4 | 4th round 5 缺陷修复 + transport factory + SpikeResult | `scripts/spike_send_100.py` + `tests/scripts/test_spike_send_100.py` + `policy/send_adapter.py` | +14 cases | 60 min | ✅ commit `a75894c`+`e07feee`+`9d78900`+`fa7aff5` |
| D5.6.5 | 真实 1 封 SMTP 端到端实测 | `scripts/spike_send_100.py` + `reports/D5.6.5-real-send-1.md` | 真实 sent=1/1.27s | 60 min | ✅ commit `6ac8d9b` |
| D5.6.5.1 | 检查员驳回 5 缺陷修复(测试隔离 + 脱敏 + SpikeResult 落地 + 文档一致 + 措辞) | `scripts/spike_send_100.py` + `tests/scripts/test_spike_send_100_real_network.py` + 5 docs | +2 cases | 60 min | ✅ commit `2396def`+`b037334` |
| D5.7 | docs 收口 8 件套 | 6 docs 文件 + 跨项目 memory | (无新 cases) | 30 min | 🎯 当前 |

### 11.5 验证 anchor(8 质量门 8/8 全绿,**D5.6.5.1 已锁定**)

| 门 | 命令 | D5.6.5.1 实际 |
|----|------|----------------|
| 1 | `pytest tests/` | **1565 passed in 15.59s**(从 D4.8 1343 → D5.5.5 1534 → D5.6.4 1561 → D5.6.5 1563 → D5.6.5.1 1565) |
| 2 | `ruff check` | All checks passed |
| 3 | `ruff format --check` | 124 files already formatted |
| 4 | `mypy src` | 0 issues / 59 source files |
| 5 | `mypy src+tests` | 0 issues / 111 source files |
| 6 | `alembic upgrade head --sql` | exit 0(含 0005 migration 0006 approval_provenance) |
| 7 | `uv build` | tar.gz + .whl OK |
| 8 | `make lint` | 0 errors / 45 files |
| **D5.6.5 真实 1 封** | `SMTP_REAL_NETWORK=1 uv run python scripts/spike_send_100.py --real --count 1` | **sent=1/1.27s / 状态机 4 步全过 / 7 字段 DispatcherResult 全 ok / B3 真正解封**(`smtp.qq.com:465 SSL`) |

### 11.6 D5 关键修复(D5.5.1-D5.6.5.1 5 轮 12 项)

1. **D5.5.1** skip_breach 语义修正 / 跨字段 / F 重试 / 异常收窄
2. **D5.5.2** 批次饥饿配额 / STALLED 不可达修复
3. **D5.5.3** P0 外部 symlink 复制 / P1 调度公平性 / P2 Heartbeat 恢复
4. **D5.5.4** P1 双向回填 / 单槽轮换 / P3 bool 严判
5. **D5.5.5** P1 单槽轮换条件 / P2 测试断言 / P3 单池边界
6. **D5.6.4 P0** 虚拟时钟 is None 严判(`is None` 不用 `or`)
7. **D5.6.4 P1-1** send_and_emit 收窄 APPROVED only(防 PENDING_SEND 绕过)
8. **D5.6.4 P1-2** OutboxStore.insert 防审批伪造(移除 `status=` + 双层防御)
9. **D5.6.4 P1-3** SMTP_REAL_NETWORK 门控 + transport factory 注入
10. **D5.6.5.1 P1-1** 测试隔离加固(注入 InMemorySmtpTransport factory + SmtpLibTransport 构造计数 + 状态断言)
11. **D5.6.5.1 P1-2** 邮箱脱敏(5 文件全量替换 `477***009@qq.com` + grep 验证)
12. **D5.6.5.1 P2-1** SpikeResult 11 字段真正落地(`-> SpikeResult` + 末尾构造并返回)
13. **D5.6.5.1 P2-2** 文档一致 5 处翻 D5.6.5
14. **D5.6.5.1 P2-3** 措辞澄清"smtp 250 OK ≠ 真实送达"

### 11.6 关键设计决策(D3.3.3 + D4.5 + D4.7.3 25 教训 + D4.7.4 7 项核心契约 + D4.8 7 教训 + D5.6.4 4 修复 + D5.6.5.1 5 修复 全应用)

#### 11.6.1 6 项契约锁定(2026-06-11 D5 启动时确认)

- **契约 1:SMTP transport 抽象 + Keychain 凭证**:`SMTPConnector` + `SmtpLibTransport`(生产) + `InMemorySmtpTransport`(测试) + `set_smtp_password / get_smtp_password` 高层封装
- **契约 2:`sending` 状态 + 显式状态机白名单**:migration 0005 enum-only + `ALLOWED_TRANSITIONS` + `OutboxIllegalTransitionError`
- **契约 3:EmailSendAdapter 三入口**:`send_and_emit` / `record_send_business_blocked_and_emit` / `record_send_failure_and_emit` + `SendDecisionReport` 双向强一致
- **契约 4:SMTP 异常窄化(D3.3.3 教训)**:`SMTPRecipientsRefused / SMTPSenderRefused` → 业务阻断 + `SMTPServerDisconnected / SMTPConnectError / socket.timeout / OSError / ssl.SSLError` → 技术失败,**不**接 `SMTPException` / `Exception` 基类
- **契约 5:OutboxDispatcher 主循环**:`run_once()` 6 步:heartbeat → 拉批 → 逐条 send → 累加 → 落日志 → 返回 `DispatcherResult`
- **契约 6:SLA + 退避 + Heartbeat 联动**:`SLAEvaluator(priority, age_ms)` + `min(2^failures * 60s, 1h)` + `assert_alive` 严格

#### 11.6.2 D5.6.4 4 修复 + D5.6.5.1 5 修复 应用

- **D5.6.4 P0 虚拟时钟 is None 严判**:`now_ms if now_ms is not None else int(time.time() * 1000)`(`is None` 不用 `or`,沿 D4.7.3 教训)
- **D5.6.4 P1-1 send_and_emit 收窄 APPROVED only**:入口 `if entry.status != APPROVED: raise`,防 PENDING_SEND 绕过审批
- **D5.6.4 P1-2 OutboxStore.insert 防审批伪造**:移除 `status=` 参数 + `last_approved_at_ms is not None → ValueError` 严判 + 双层防御
- **D5.6.4 P1-3 SMTP_REAL_NETWORK 门控 + transport factory**:`os.environ.get("SMTP_REAL_NETWORK") != "1" → ValueError` + `smtp_transport_factory: Callable[[], Any] | None = None` 注入
- **D5.6.5.1 P1-1 测试隔离加固**:`pytest.raises(Exception)` 改 `fake_factory + SmtpLibTransport.__init__` 跟踪 + 状态断言
- **D5.6.5.1 P1-2 邮箱脱敏**:5 文件全量 `477753009@qq.com` → `477***009@qq.com`
- **D5.6.5.1 P2-1 SpikeResult 真正落地**:`run_spike(...) -> SpikeResult` + 末尾构造并返回 11 字段
- **D5.6.5.1 P2-2 文档一致 5 处**:5 文件全量翻 D5.6.5 / 8 门全绿 / B3 真正解封 / 移除假 commit
- **D5.6.5.1 P2-3 措辞澄清**:"真实送达" → "SMTP 服务器接受 (smtp 250 OK)"(3 文件 + 1 docstring)

### 11.7 故意不学的范本(g009 §"反范本" 沉淀)

| 旧 v1.0 假想写法 | 新 D5.6.5.1 写法 | 教训 |
|------------------|------------------|------|
| 严判只放 Adapter `send_and_emit` 入口(v1.0 假想) | 严判下沉到 `compute_send_acceptance` + `build_send_*` 公共 API(v1.0) | 公共 helper 必自防御,Adapter 重构不可绕过 |
| 业务阻断 vs 技术失败用同一 `failed: bool` 字段(v1.0 假想) | `SendBlockedDecisionReport.blocked: Literal[True]` + `kind: Literal["business_blocked"]` vs `SendFailureDecisionReport.failed: Literal[True]`(v1.0) | 字段名级别硬区分,防通用 `if report.failed` 绕过 |
| `send_completed: bool` 成功报告(v1.0 假想) | `SendDecisionReport.send_completed: Literal[True]`(v1.0) | `Literal[True]` 类型层面固化,防 `send_completed=False` 混入 |
| 混用 `last_send_failed` 与 `cf` 隐式推断(v1.0 假想) | 双向强一致 `True → cf>=1` / `False → cf==0`(v1.0) | 显式 bool + 跨字段约束,防漏方向 |
| 内联 `if priority not in {URGENT, HIGH, NORMAL}`(v1.0 假想) | `_validate_send_priority` helper(v1.0) | 统一 `ValueError`,防 list/dict/set 触发 `TypeError` |
| 跨字段约束只在 Adapter 入口(v1.0 假想) | `__post_init__` 三重校验(reason ↔ outbox_id / send ↔ status / stored ↔ id)(v1.0) | 数据类双层防御,工厂层+数据类兜底 |
| 严判不区分"必为 True"与"必为 False"语义(v1.0 假想) | `Literal[True]` + `__post_init__` 显式校验(v1.0) | 数据类字段约束必须自洽,类型层面拒绝非法 |
| `bool` / `int` 字段用 `isinstance` 严判(v1.0 假想) | `type(value) is bool` / `type(value) is int` 严判(v1.0) | `isinstance(True, int)==True` 陷阱,bool 是 int 子类 |
| `policy/send_adapter.py` 内部写好但不导出(v1.0 假想) | `policy/__init__.py` 顶层暴露 11 个新符号(v1.0) | `__all__` 声明 ≠ 实际可导入,顶层必须转发 |
| `engine or PolicyEngine()` 当替身 `__bool__()` 返回 False 被吞(v1.0 假想) | `engine if engine is not None else PolicyEngine()`(v1.0) | 依赖注入用 `is None` 不用 `or`,保留 falsey 替身 |
| 文档示例保留已删除参数(v1.0 假想) | 严格匹配签名(v1.0) | 文档与实现一一对应,过期注释比无注释更危险 |
| 复用 D3.3.2 `(SQLAlchemyError, IntegrityError)` 过宽异常(v1.0 假想) | `except (SMTPRecipientsRefused, SMTPSenderRefused, SMTPDataError, SMTPAuthenticationError)` 严格窄化(v1.0) | 基类异常会误算 OperationalError / DB 锁,掩盖生产问题 |
| `SMTP_REAL_NETWORK` env 默认 "1" fail-open(v1.0 假想) | 默认 ≠ "1" → `ValueError` deny-by-default(v1.0) | 真实外部世界调用必须 env 显式解锁 |
| `now_ms or int(time.time() * 1000)` 短路判 None(v1.0 假想) | `now_ms if now_ms is not None else int(time.time() * 1000)`(v1.0) | 虚拟时钟 / 真实时钟必须 `is None` 严判 |
| `send_and_emit` 接受任意 status(D5.6.4 之前) | 入口 `if entry.status != APPROVED: raise`(D5.6.4 收口) | 收窄状态防止绕过审批 |
| `OutboxStore.insert(status=APPROVED, last_approved_at_ms=now)`(D5.6.4 之前) | 移除 `status=` 参数 + `last_approved_at_ms is not None → ValueError`(D5.6.4 收口) | 双层防御防止审批伪造 |
| `pytest.raises(Exception)` 宽泛放行真实 SMTP 调用(D5.6.5 之前) | 注入 `InMemorySmtpTransport` factory + `SmtpLibTransport.__init__` 跟踪 + 状态断言(D5.6.5.1 收口) | 测试绝不允许连真实外部世界 |
| 真实邮箱明文写 docs(D5.6.5 之前) | 全量脱敏 `477***009@qq.com` + grep 验证(D5.6.5.1 收口) | 真实凭据脱敏是固化动作 |
| `SpikeResult` 定义完整但 `run_spike` 返 None(D5.6.5 之前) | `-> SpikeResult` + 末尾构造并返回 11 字段(D5.6.5.1 收口) | dataclass 定义必配套 return |
| "真实送达" 措辞(D5.6.5 之前) | "SMTP 服务器接受 (smtp 250 OK)"(D5.6.5.1 收口) | 业务层声明必区分接受与送达 |

---

**最后更新**:2026-06-14 晚间(**D5.6.5.1 收口 + D5.7 docs 收口 8 件套** mapping 段:6 契约锁定 + 16 子任务全部 ✅ + 8 质量门全绿 + 真实 1 封 SMTP 端到端 + 14 commits 收口链 + 14 项关键修复沉淀)
**维护者**:Mr-PRY
**关联**:
- [memory/d5-business-scheduler-launch.md](../Agent%20Assistant/memory/d5-business-scheduler-launch.md) — D5 业务调度器 14 commits 收口链 + 真实 1 封 SMTP 范本
- [memory/d5.6.5-real-send.md](../Agent%20Assistant/memory/d5.6.5-real-send.md) — D5.6.5 真实 1 封 SMTP 端到端实测
- [memory/d5.6.5.1-fixes.md](../Agent%20Assistant/memory/d5.6.5.1-fixes.md) — D5.6.5.1 检查员驳回 5 缺陷修复
- [memory/D4-claw-code-auto-reference.md](../Agent%20Assistant/memory/D4-claw-code-auto-reference.md) — 全局规则(D5 自动参考规则已加)
- [memory/d4.7.3-drafter-adapter-v1.0.6.md](../Agent%20Assistant/memory/d4.7.3-drafter-adapter-v1.0.6.md) — D4.7.3 25 教训沉淀源头
- [memory/d4.8-草稿入库.md](../Agent%20Assistant/memory/d4.8-草稿入库.md) — D4.8 v1.0.1 收口链(契约 5:不真发 SMTP,D5+ 调度器接管)
- [memory/d4.7.4-docs-closure.md](../Agent%20Assistant/memory/d4.7.4-docs-closure.md) — D4.7.4 v1.0.2 docs-only 收口范本
- [memory/d5-redirect-smtp-only.md](../Agent%20Assistant/memory/d5-redirect-smtp-only.md) — D5 启动方向纠正(稳固优先)
- [reports/D5-业务调度器.md](../reports/D5-业务调度器.md) — D5 业务调度器 8 段结构报告(本 D5.7 commit 新建)
- [reports/D5.6.5-real-send-1.md](../reports/D5.6.5-real-send-1.md) — D5.6.5 真实 1 封 SMTP 端到端报告
- [memory/d5.6.4-4th-round-fixes.md](../Agent%20Assistant/memory/d5.6.4-4th-round-fixes.md) — D5.6.4 4th round 5 缺陷修复
- [memory/d5.5.5-p1-p2-p3-fixes.md](../Agent%20Assistant/memory/d5.5.5-p1-p2-p3-fixes.md) — D5.5.5 2 commits 收口
- [memory/d5.5.4-p1-p3-fixes.md](../Agent%20Assistant/memory/d5.5.4-p1-p3-fixes.md) — D5.5.4 P1/P3 修复
- [memory/d5.5.3-p0-p1-p2-fixes.md](../Agent%20Assistant/memory/d5.5.3-p0-p1-p2-fixes.md) — D5.5.3 P0/P1/P2 修复
- [memory/d5.5.2-p1-fixes.md](../Agent%20Assistant/memory/d5.5.2-p1-fixes.md) — D5.5.2 P1 修复
- [memory/d5.5.1-fix-locked.md](../Agent%20Assistant/memory/d5.5.1-fix-locked.md) — D5.5.1 落锁
- [memory/d5.5-audit-findings.md](../Agent%20Assistant/memory/d5.5-audit-findings.md) — D5.5 审计发现 7 处
- [docs/week1-mvp.md §D5 L931-1108](../我的AI员工/docs/week1-mvp.md) — D5 详细计划(6 契约 + 16 子任务 + 6 契约 + 8 风险 + 8 质量门)
- [docs/week1-mvp.md §D4.8 L841-925](../我的AI员工/docs/week1-mvp.md) — D4.8 详细计划(5 契约 + 12 子任务,B3/B5 解封项已清理)
**维护者**:Mr-PRY
**关联**:
- [memory/D4-claw-code-auto-reference.md](../Agent%20Assistant/memory/D4-claw-code-auto-reference.md) — 全局规则
- [reports/D4.8-草稿入库.md](../reports/D4.8-草稿入库.md) — D4.8 v1.0.1 报告(8 质量门 + 5 契约 + 25 教训 + B 类延后)
- [output/spike/spike_outbox_100_20260611_221105.md](../output/spike/spike_outbox_100_20260611_221105.md) — D4.8.11 spike 100 封入库报告
- [memory/claw-code-reference.md](../Agent%20Assistant/memory/claw-code-reference.md) — 仓库快照 + 6 个高价值文件
- [memory/tools_status.md](../Agent%20Assistant/memory/tools_status.md) — gh api 旁路 GFW 用法
- [memory/d4.7.4-v1.0.3-deferred.md](../Agent%20Assistant/memory/d4.7.4-v1.0.3-deferred.md) — D4.7.4 spike 3 FALSE_PASS 列入 v1.0.3 改进项(B 类延后)
- [memory/d4.7.3-drafter-adapter-v1.0.6.md](../Agent%20Assistant/memory/d4.7.3-drafter-adapter-v1.0.6.md) — D4.7.3 25 教训沉淀源头(D4.8 7 项核心契约复用)
- [memory/d4.7.4-docs-closure.md](../Agent%20Assistant/memory/d4.7.4-docs-closure.md) — D4.7.4 v1.0.2 docs-only 收口 commit `b1497b3`
- [reports/D4.7.4.10-spike.md](../我的AI员工/reports/D4.7.4.10-spike.md) — D4.7.4.10 spike 100/100 跑通 + 阻断率/原因/延迟全分析
- [docs/week1-mvp.md §D4.8 L841-909](../我的AI员工/docs/week1-mvp.md) — D4.8 详细计划(5 契约 + 12 子任务)
