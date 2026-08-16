# 三 Agent 联动协议（Phase 0）

## 目标

让 Codex（GPT）、Cursor Agent（Grok）和 Claude Code（MiniMax M3）以任务队列协作；常驻的是调度器，Agent 任务应是有时限、可恢复、可验收的短进程。

本协议只定义协作控制面，不启用任何生产调度、真实外发或数据写入。

## 角色

| Agent | 默认职责 | 交付 |
| --- | --- | --- |
| Codex | 任务拆分、范围控制、交叉验收、最终收口 | 任务包、验收意见 |
| Cursor / Grok | 跨文件实现、重构、测试补齐 | 任务分支与验证结果 |
| Claude / MiniMax | 项目约束检查、故障诊断、二次修复、沉淀 | 审查意见、修复或文档 |

按任务类型路由：

- 文档或测试：Claude 实施，Codex 验收。
- 新功能：Codex 设计，Cursor 实施，Claude 审查，Codex 收口。
- 疑难缺陷：Claude 定位，Cursor 修复，Codex 回归。
- 高风险变更：三方分别分析后进入 `needs_human`，未经批准不得实施。

## 状态机

`queued → claimed → running → review → verify → ready_to_merge → done`

异常状态：`blocked`、`failed`、`expired`、`needs_human`。

一个任务进入 `needs_human` 不应停止其他无依赖、安全任务。

## 不可违反的控制点

1. 每项任务使用独立 Git worktree；禁止三个 Agent 共用主工作树。
2. 一个任务只允许一个实施者；审查者仅查看该任务 diff，避免覆盖写。
3. 任务必须声明可写路径、验收命令、风险等级和最大自动修复次数。
4. 默认只允许本地读取、文档、测试、lint、build 和任务分支 commit。
5. 默认禁止 push、合并 main、tag、依赖安装、迁移、删除、对外写入与生产配置变更。
6. 不使用 `--yolo`、`--force` 或任何绕过权限/沙箱的无人值守参数。

## P3 观察期附加约束

在 P3 观察结束并通过资格检查前，仅允许 docs-only 和 tests-only 任务。不得修改业务模块、LaunchAgent、健康调度、SMTP、Feature Flag、真实 SAP/Notes/财务数据。

## 运行时规划（P3 后）

后续只部署一个本地 `ai-teamd` 调度器：它轮询任务队列、创建 worktree、以受限权限启动对应 CLI、收集结构化结果并写入审计。Agent 不常驻；空闲时调度器保持待命。

默认上限：单任务 45 分钟、两轮自动修复、超时或冲突进入 `needs_human`。具体额度由后续策略文件配置。

## 任务包

所有联动任务使用 [`task-contract.yaml`](task-contract.yaml) 字段。实施前必须读取任务包；完成后必须返回“修改文件、验收结果、风险、未解决事项、下一棒”。
