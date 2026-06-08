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

## 6. D4.5 release readiness + 业务层接入(✅ 2026-06-08 ready_for_review)

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
| Context 12 字段严判 | (D4.4 P1 教训应用) | bool/int/str/list[bool] native type,`type() is bool` 严判,拒 type-coerce | `build_sync_policy_context` 12 字段全用 `bool()/int()` 显式转换 |
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
| 3. 31 个集成测试 (5 类) | `tests/policy/test_integration.py` | 397 |
| 4. ready_for_review 5 段报告 | `reports/D4.5-release-readiness.md` | ~400 |
| 5. mapping §6 详细段 | `docs/d4-claw-code-mapping.md` | (本段) |

**总产出**:1 新增 src 模块(270 行) + 1 `__init__` 扩展(26→31 导出) + 1 新增测试(397 行 / 31 tests) + 1 报告(400 行) + 1 mapping 段。**D4.4 源文件零修改**(4 件套契约保持 v1.0)。

### 6.5 验证 anchor(8 质量门,7 实跑 + 1 预存)

| 门 | 结果 |
|----|------|
| 1. `pytest tests/policy/ -v` | **211 passed in 0.13s** (D4.4 180 → D4.5 +31) |
| 2. `ruff check` | All checks passed |
| 3. `ruff format` | 71 files already formatted |
| 4. `mypy src/my_ai_employee/policy/` | 0 errors / 7 files(D4.4 6 + integration 1) |
| 5. `mypy tests/policy/` | 0 errors / 8 files(D4.4 7 + test_integration 1) |
| 6. `alembic upgrade head --sql` | exit 0 (0003 latest) |
| 7. `uv build` | tar.gz + .whl OK |
| 8. `pytest` (全量) | **489 passed** + 1 D4.3 预存隔离(`test_by_session`,与 D4.5 无关) |

### 6.6 关键设计决策(D3.3.3 + D4.4 P1 教训应用)

| 决策 | 理由 | 教训来源 |
|------|------|---------|
| 4 依赖全可选注入 | D3.3 行为零变化,不传 = 纯评估模式 | Karpathy 原则 2(向后兼容) |
| `evaluate_and_emit` 不替 caller 执行 6 决策 | 只 emit + 推进 lane,实际 retry/merge/escalate 由 D5+ 决定 | D3.3.3 异常窄化教训 |
| `consecutive_failures` 必填 int>=0,严判透传 ValueError | 编程错误不包装,避免掩盖问题 | D4.4 P1 教训 |
| `transport_alive` 必填 bool,`type() is bool` 严判 | 字符串"true" 不通过,显式 `bool()` 转换 | D4.4 P1 教训 |
| `run_id` 空时用 `int(time.time()*1000)` 默认值 | 多次调用 lane_entry_id 唯一(测试 `test_run_id_unique_per_call` 验证) | Karpathy 原则 3(最小可用) |
| `record_to_lane` 内部先 add ACTIVE 再 update FINISHED | D4.4 状态矩阵:FINISHED 终态不能直接 add | D4.4 LaneBoard 矩阵 |
| 业务 payload 7 字段合并到 `event_metadata` 顶层 | D4.3.2 决策:`build_event_metadata` `meta.update(extra)` | D4.3.2 contract 教训 |
| `now_ms` 注入而非 time.time() 默认 | 测试可控,避免 sleep/clock 漂移 | D4.3 + D4.4 模式延续 |
| `event_id=None` 表示纯评估模式 | 适配器不强制依赖 store,允许 dry-run | Karpathy 原则 1(think before coding) |
| `lane_entry_id` 命名 `sync:<source>:<run_id>` | 跨次 sync 区分(每次 sync 有独立 run_id) | D4.4 lane_id 命名风格 |

### 6.7 已知限制(D4.5.1+ 复检 P 项)

| 限制 | 改进方向 |
|------|----------|
| 6 决策是声明式,`evaluate_and_emit` 不替 caller 执行 | D4.5.1+ 加 `executor` pattern:retry 调 `IMAPSync.run_once` / escalate 写 events 表 escalation row |
| LaneBoard in-memory,D4.5 仍无持久化 | D4.5.1+ 落 `lane.entry.added` / `status_changed` 事件到 events 表 |
| 单一 source 适配器(IMAP) | D4.6+ 加 `EmailClassifierAdapter` / `EmailDrafterAdapter`(同 SyncPolicyAdapter 4 依赖范本) |
| `consecutive_failures` 外部喂入,D4.5 不接 SyncState | D4.5.1+ 集成 `IMAPSyncState.consecutive_failures` 字段(已有,只接) |
| 无 1 万封真实 spike | D4.5.1+ 在 1 万封真实邮件上跑 `evaluate_and_emit` 30 天(D3.3 spike 已验证 0.30s/万封) |

---

**最后更新**:2026-06-08(D4.2 锁定 + D4.3 Events 表契约完成 + D4.4 任务策略板完成 + D4.5 release readiness + 业务层接入完成(ready_for_review),落 mapping 第二段 + 熔断口径收口 + D4.3 §4 详细段 + D4.4 §5 详细段 + D4.5 §6 详细段)
**维护者**:Mr-PRY
**关联**:
- [memory/D4-claw-code-auto-reference.md](../Agent%20Assistant/memory/D4-claw-code-auto-reference.md) — 全局规则
- [memory/claw-code-reference.md](../Agent%20Assistant/memory/claw-code-reference.md) — 仓库快照 + 6 个高价值文件
- [memory/tools_status.md](../Agent%20Assistant/memory/tools_status.md) — gh api 旁路 GFW 用法
