# Codex 风格工作台 P0/P2 静态原型

> 范围:静态 UI 原型 + 本地只读 API 预览;不发 SMTP、不写 Keychain、不启动 launchd。

## 结论

P0 原型用于验证"我的AI员工"是否应该升级为 Codex 式本地工作台:左侧能力导航、中间任务线程、右侧上下文检查器、底部折叠执行日志。P2 已补充只读 API 连接:`/api/status` + `/api/tasks/today`。

## 产物

- `docs/ui/codex-style-dashboard.html`
- `docs/v0.2.53-codex-style-ui-design-2026-06-25.md`
- `docs/v0.2-launch-plan.md` 的 `v0.2.53 Codex 风格 UI 工作台计划`

## 当前覆盖页面

| 页面 | P0 覆盖 | 说明 |
|------|---------|------|
| 今日 | ✅ + API | 待办摘要、任务线程、安全门控 |
| 邮件 | ✅ | 草稿预览、审批按钮、真实发送禁用态 |
| 系统 | ✅ + API | 质量门、Provider、Git、审批门 |
| 笔记 | 占位 | P1/P2 再接 NoteConfirmService |
| 财务 | 占位 | P1/P2 再接异常检测与候选 review |
| 报告 | 占位 | 后续展示月度复盘、撞坑清单、质量门趋势 |

## 评审检查点

1. 左侧导航是否符合日常工作顺序:今日 / 邮件 / 笔记 / 财务 / 日程 / 报告 / 系统 / 设置。
2. 中间任务线程是否能清楚表达"用户指令 → 计划 → 执行 → 证据 → 结果"。
3. 右侧上下文检查器是否足够承载草稿、账单、笔记、风险门控和证据。
4. 高风险动作禁用态是否足够醒目:真实 SMTP、Keychain 写入、真实账单导入、launchd/kickstart、tag 创建。
5. 信息密度是否适合个人日常使用,而不是变成泛 Dashboard。

## 推荐下一步

1. 运行 `make dashboard-api`。
2. 打开 `docs/ui/codex-style-dashboard.html`,确认顶部显示 `API 已连接`。
3. 下一步再扩展 `/api/outbox`、`/api/notes/pending`、`/api/finance/anomalies`。

## 暂不做

- 不引入 React / Vite / Tauri / Electron。
- 不读取或展示 Keychain 明文。
- 不新增真实发送入口。
- 不绕过现有 Outbox / Notes / Finance 状态机。
