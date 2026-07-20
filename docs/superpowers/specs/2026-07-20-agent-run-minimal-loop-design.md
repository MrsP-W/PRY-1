# AgentRun 最小闭环设计（2026-07-20）

## 目标

把「功能型个人助手」升级为可执行、可审计、可评测的受控 Agent 工作流：

`任务计划 → 工具调用 → 审批 → 结果/失败 → 可恢复检查点`

## 固定决策

- **首发工作流**：`email_to_draft`（邮件→草稿）。不首发 SAP 排错。
- **不换编排框架**：不引入 LangGraph / CrewAI / 向量库 / 多 Agent handoff。
- **角色 Markdown 不是 Runtime**：`src/my_ai_employee/agents/*.md` 仅 prompt 资产；执行在 `src/my_ai_employee/runtime/`。
- **红线**：默认不 SMTP 真发、不 Shell、不 Keychain 宽开、不 Path4 实写；危险动作只经 ApprovalGate。
- **P3 burn-in 并行**：不重置 Day0，不启停 burn-in Job。

## 状态机

| 状态 | 含义 |
|------|------|
| `planned` | 已建 run + TaskPacket，未执行 |
| `running` | 正在执行步骤 |
| `awaiting_approval` | 草稿已入库，等待 1-click 审批 |
| `checkpointed` | 可恢复失败（瞬态） |
| `succeeded` | 验收通过（停在审批通过或 dry-run 完成，**不含 SMTP**） |
| `failed` | 不可恢复失败 |
| `cancelled` | 审批拒绝 / 用户取消 |

合法迁移（白名单，仿 Outbox）：

- `planned` → `{running, cancelled}`
- `running` → `{awaiting_approval, checkpointed, succeeded, failed, cancelled}`
- `checkpointed` → `{running, failed, cancelled}`
- `awaiting_approval` → `{succeeded, cancelled, failed}`
- `succeeded` / `failed` / `cancelled` → `∅`

## 数据模型（`0018_agent_runs`）

| 列 | 说明 |
|----|------|
| `id` | INTEGER PK |
| `run_id` | TEXT UNIQUE UUID |
| `trace_id` | TEXT NOT NULL（贯穿 LLM/工具/事件） |
| `workflow` | TEXT NOT NULL（首发 `email_to_draft`） |
| `status` | TEXT NOT NULL |
| `task_packet_json` | TEXT NOT NULL（完整 TaskPacket） |
| `checkpoint_json` | TEXT NOT NULL DEFAULT `{}` |
| `parent_event_id` | INTEGER NULL（软引用 events.id） |
| `created_at_ms` / `updated_at_ms` | INTEGER |

checkpoint 最小字段：`completed_steps`、`email_id`、`outbox_email_id`、`last_tool`、`error_code`、`tool_sequence`。

## 邮件→草稿五步

1. **plan** — 构造 TaskPacket（默认 `permission_profile=read_only`，`recovery_policy=retry_on_transient`）
2. **classify** — 可注入分类器（只读）
3. **draft** — 可注入草稿器；非 dry-run 时写入 Outbox `pending_send`（入库≠外发）；resume 时若 checkpoint 已有 `email_id` 则跳过（幂等）
4. **await_approval** — 进入 `awaiting_approval`；真审批走既有 ApprovalGate decide 契约
5. **finalize** — `succeeded` / `cancelled`；**默认不调用 SMTP**

## 事件前缀

新增 `EventType`（三元组风格）：

- `agent.run.started`
- `agent.run.step`
- `agent.run.checkpoint`
- `agent.run.awaiting_approval`
- `agent.run.succeeded`
- `agent.run.failed`

metadata extra 可含：`trace_id`、`run_id`、`step`、`model`、`provider`、`latency_ms`、`input_tokens`、`output_tokens`、`fallback_used`、`error_code`（无正文/密钥）。

## Trace / Eval

- 每次 run 生成 `trace_id`；Router `route(..., trace_id=...)` 可选透传并记入调用结果旁路字段。
- Eval：`scripts/eval_agent_runs.py` + `tests/runtime/fixtures/email_to_draft/` 脱敏样本，断言步骤序列与终态，不访问外网。

## MCP stdio（本机白名单）

- `StdioTransport`：仅绝对路径且在白名单；禁止 `/bin/sh` 包装。
- 工具参数 JSON Schema 校验；默认只读；危险工具必须 `approved=True`（对接 ApprovalGate / AgentRun 审批态）。
- 测试默认仍用 `MockTransport`。
- **不做**：远程 OAuth、增量授权、任务轮询。

## 非目标

多 Agent、SAP 工作流、LangGraph/CrewAI、向量库、宽权限 Shell/SMTP/Keychain 工具。

## 后续 lab

`output/2026-07-20/labs/pydantic-ai-spike/` 仅对比结构化输出 + 审批钩子 + MCP + trace 映射，不迁移主工程。
