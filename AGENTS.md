# 三 Agent 协作入口（Codex）

本文件只约束 Codex；三方共享规则见
[`docs/agent-team/README.md`](docs/agent-team/README.md)。

## 与全局模型规则的合并关系

- 默认继承 `/Users/wei/.codex/AGENTS.md` 的模型路由：日常/简单任务由 M3 以最高推理强度完成并自审；复杂/高风险代码由 `gpt-5.6-sol` 主导并终审；GPT 只按风险触发，不固定拆分比例。
- 当前 ChatGPT 账户的 Codex 原生通道不支持 `minimax-cn/MiniMax-M3`；M3 只能通过已认证的外部 MiniMax bridge 调用。GPT 额度明确耗尽时，`LIGHT/STANDARD` 可临时使用外部 M3 最高档位，记录 `GPT_QUOTA_FALLBACK_M3`、原 GPT 模型和验收结果；P3 的 docs-only、tests-only、只读和单实施 Agent 边界不变。
- `HARD/CRITICAL` 的复杂核心逻辑、生产/SAP/财务/权限动作和 Sol 最终审核不得降级给 M3；额度不足时必须暂停或请求人工审批。
- 本项目 P3 观察期是更严格的局部安全例外：每个任务只允许一个实施 Agent，且仅允许 docs-only、tests-only 或只读核验；全局四模型角色仍必须初始化，但只有一个角色可以实施/写入，其他角色只能只读审查或保持待命。
- Codex 是唯一项目文件写入者；Cursor/Grok、Claude/MiniMax 或 GPT 审查角色只能在任务契约允许的范围内只读审查，不能直接修改主工作树或绕过 P3 边界。
- 若全局模型分工与本文件的 P3、worktree、审批或外部写入边界冲突，以本文件和 `docs/agent-team/README.md` 的更严格规则为准。

## 当前硬边界

- P3 观察期内只允许文档与测试改动；不得触碰业务代码、LaunchAgent、SMTP、Feature Flag、真实数据写入或生产配置。
- 当前主工作树含用户 WIP。禁止在主工作树编辑、暂存、提交、stash、清理或重置任何既有改动。
- 每个任务必须在独立 Git worktree 中执行；一个任务只有一个实施 Agent。

## Codex 职责

1. 把目标转成符合 `task-contract.yaml` 的任务包，并明确验收命令、可写路径和风险等级。
2. 由一个实施 Agent（优先遵循全局当前模型配置，M3 时保持最高推理）完成任务；必要时分配 Cursor/Grok、Claude/MiniMax 或 GPT 角色做只读交叉审查，Codex 自己负责最终验收与收口。
3. 仅在所有验收门通过且审批策略允许时，建议合并；默认不 push、不合并 `main`、不打 tag。

## 必须暂停并请求人工审批

- 外部写入：邮件、Notes、SAP、财务、生产数据库或网络侧效果。
- 密钥、OAuth、依赖安装、迁移、删除、LaunchAgent、Feature Flag、push、合并或发布。
- 两次自动修复仍失败，或 Agent 的架构结论冲突。

## 最小执行顺序

`任务包 → 独立 worktree → 实施 → 交叉审查 → 质量门 → done / needs_human`
