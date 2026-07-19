# Codex 风格工作台 P0/P2 静态原型 + AI 每日情报台

> 范围:静态 UI 原型 + 本地 API 预览 + AI 情报本地缓存;写操作只到 ApprovalGate 契约层,不发 SMTP、不写 Keychain。当前 P0-4 观察期不重启服务、不安装新闻 LaunchAgent。

## 结论

P0 原型用于验证"我的AI员工"是否应该升级为 Codex 式本地工作台:左侧能力导航、中间任务线程、右侧上下文检查器、底部折叠执行日志。P2 已补充本地 API 连接:status / tasks / outbox / notes / news/daily / reports / report preview,并在 v0.2.53.11 增加 ApprovalGate 写操作契约骨架。

## 产物

- `docs/ui/codex-style-dashboard.html`
- `docs/v0.2.53-codex-style-ui-design-2026-06-25.md`
- `docs/v0.2-launch-plan.md` 的 `v0.2.53 Codex 风格 UI 工作台计划`

## 当前覆盖页面

| 页面 | P0 覆盖 | 说明 |
|------|---------|------|
| 今日 | ✅ + API | 待办摘要、任务线程、安全门控 |
| 邮件 | ✅ + API | 草稿列表、审批按钮、真实发送禁用态 |
| 系统 | ✅ + API | 质量门、Provider、Git、审批门 |
| 笔记 | ✅ + API | Notes 待确认列表 |
| 每日新闻 | ✅ + API | 国内/国际 AI 事件、官方发布、已核验原话与发言线索筛选 |
| 报告 | ✅ + API | 本地报告清单、搜索、点击预览 |
| ApprovalGate | ✅ 设计态 | POST 契约、默认禁写、审计预览 |

## AI 每日情报台

- **刷新链路**:受控 HTTPS Feed → 本地 `Application Support/MyAIEmployee/news/latest.json` 原子缓存 → `GET /api/news/daily` → Dashboard；API 请求从不访问外网，页面每 5 分钟只重读本地 API 以看见新的缓存。
- **内容层级**:国内 AI 大事件、国际 AI 大事件、官方模型/产品发布、AI 大佬公开发言；优先标注 SAP、企业 AI、Agent、RAG、MCP、开发工具与安全治理。
- **来源分层**:OpenAI、Google AI、Hugging Face、NVIDIA Newsroom 与 OpenAI 官方视频为一手发布；Google 新闻、36氪、TechCrunch、VentureBeat、The Verge 仅作事件发现并保留原文链接。
- **AI 大佬发言**:当前自动核验源为 NVIDIA Newsroom RSS；仅当官方正文同时存在受白名单约束的说话人、紧邻的明确归因与逐字引号时显示“已核验原话”。普通动态窗口为 72 小时，已核验原话保留 7 天并在 48 条上限中预留最多 4 条。媒体转述只标为“发言线索”，不加引号、不由模型改写。国内尚未发现等价的官方 RSS 逐字来源，先不自动生成国内引语；未来仅可加入人工审核的一手逐字稿清单。
- **筛选与覆盖**:页面提供全部 / 国内 / 国际 / 已核验原话 / 发言线索五类筛选；刷新后显示来源健康与软验收（国内 ≥4、国际 ≥8、已核验原话 ≥1），不足时提示覆盖待补全而不虚构内容。
- **失败降级**:单一来源失败不阻塞其他来源；所有来源失败或全部解析为空时，原子保留最后一份非空内容、记录本次来源状态并显示“上次刷新降级”；首次刷新前明确显示空态。
- **网络边界**:采集器只接受白名单 HTTPS 初始 URL；重定向最多两跳，且必须同一 HTTPS origin，拒绝跨域、HTTP、非标准端口、localhost 与私网 IP。
- **调度状态**:当前可手动运行刷新器，尚未部署每小时 LaunchAgent。P0-4 通过和 GUI 域授权后，才新增独立 one-shot 任务（`StartInterval=3600`、`RunAtLoad=true`、无 `KeepAlive`）。
- **待办边界**:新闻是信息流，不计入邮件与 Notes 的人工待办总数。

## 评审检查点

1. 左侧导航是否符合日常工作顺序:今日 / 邮件 / 笔记 / 每日新闻 / 日程 / 报告 / 系统 / 设置。
2. 中间任务线程是否能清楚表达"用户指令 → 计划 → 执行 → 证据 → 结果"。
3. 右侧上下文检查器是否足够承载草稿、笔记、AI 情报来源健康、风险门控和证据。
4. 高风险动作禁用态是否足够醒目:真实 SMTP、Keychain 写入、launchd/kickstart、tag 创建。
5. 信息密度是否适合个人日常使用,而不是变成泛 Dashboard。

## 推荐下一步

1. 运行一次 `uv run python scripts/refresh_daily_news.py`，确认本地缓存生成、NVIDIA 原话来源和每源状态。
2. 运行 `make dashboard-api`，打开 `docs/ui/codex-style-dashboard.html`，确认“每日新闻”能切换五类筛选且只读本地缓存。
3. P0-4 观察通过且获得 GUI 域授权后，再部署独立 one-shot LaunchAgent（`StartInterval=3600`、`RunAtLoad=true`、无 `KeepAlive`）；不要复用或重载现有四个 job。

## 暂不做

- 不引入 React / Vite / Tauri / Electron。
- 不读取或展示 Keychain 明文。
- 不新增真实发送入口。
- 不删除现有 Finance 后端、账单数据、移动伴侣兼容接口或审批契约；仅从工作台展示层移除。
- 不抓取需要登录的 X/微博/公众号，不把媒体转述写成大佬原话。
- 不把 ApprovalGate 契约等同于真实写入授权。
