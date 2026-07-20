# PydanticAI Spike Lab（不迁移主工程）

日期：2026-07-20

## 目的

在临时目录对比 PydanticAI 与本仓库 `AgentRun` 最小闭环，仅验证：

1. 结构化输出（typed result）
2. 工具调用前审批钩子（HITL / ApprovalGate 映射）
3. MCP 工具契约（本机 stdio 白名单思路）
4. Trace 字段映射到 `trace_id` / events metadata

## 明确不做

- 不引入 LangGraph / CrewAI 到主工程
- 不替换 `src/my_ai_employee/runtime/`
- 不开放 Shell / SMTP / Keychain
- 不把本 lab 依赖写入 `pyproject.toml`（实验用独立 venv）

## 建议对照表

| PydanticAI 概念 | 本仓库映射 |
|-----------------|------------|
| Agent run / durable execution | `AgentRunRecord` + checkpoint_json |
| Tool approval / HITL | `awaiting_approval` + ApprovalGate |
| MCP servers | `StdioTransport` + `GatedToolCaller` |
| Instrumentation / OTel | `trace_id` + `LLMRouter.last_trace()` + `agent.run.*` events |

## 如何实验（可选）

```bash
cd output/2026-07-20/labs/pydantic-ai-spike
python3 -m venv .venv && source .venv/bin/activate
pip install 'pydantic-ai==2.13.0'
# 自行编写最小 script；成功标准见上表「能否映射」
```

## 结论门槛

若无法在不改主工程的前提下把一次 run 的 `trace_id`、审批点、工具序列映射回 `AgentRun` 字段，则保持现有 runtime，不采纳迁移。
