# 我的AI员工 — 全天候个人 AI 数字员工

> **一句话**：把 Agent Assistant 的 10 角色从"晨晚链路"升级为"全天候数字员工"，能力 = 邮件 + 日程 + 财务 + 笔记 + 主动提醒。
>
> **核心差异化**：数据不出本机（隐私优先）+ 与 Agent Assistant 无缝衔接（Skill 复用）+ minimax M3 LLM（统一链路）。
>
> **状态**:🟢 **v0.2.53.4 Dashboard 只读 API 扩展**(2026-06-25 · `/api/outbox` + `/api/notes/pending` + `/api/finance/anomalies` · `OutboxDraftService.list_pending_drafts` · `limit` 1–100)。**质量门**:**2293 passed / 1 skipped / 88.49%** / mypy --strict 0 errors(217 files) / ruff 全绿 / format 231 files / **MD lint 152 files** 0 errors。**下一棒**:静态 HTML 邮件/笔记/财务页接新端点 / outlook+gmail Keychain → 真实 SMTP / 8/1 截点。**边界**:不真发邮件、不写凭据、不 kickstart launchd、不打 `v0.2.x` tag。

---

## 🤝 与 Agent Assistant 的关系

**兄弟项目**：

- **Agent Assistant**（`../Agent Assistant/`）— 10 角色多 Agent 系统、Skill 生态、MD 维护纪律、跨会话记忆
- **我的AI员工**（本项目）— Agent Assistant 的"执行器"载体：把"晨晚链路半成品"升级为"全天候数字员工"

**互不重复**：

| 维度 | Agent Assistant | 我的AI员工 |
|------|----------------|------------|
| 时间维度 | 09:00 + 21:00 截点 | 全天候 + 主动 |
| 数据源 | 公开信息（新闻/SAP 知识）| 个人数据（邮件/日程/账本/笔记）|
| 存储 | Markdown 文档 | SQLite 加密 + 向量索引 |
| 接口 | 文档产出 | 菜单栏 + Web Dashboard + 移动伴侣 |
| 隐私 | 公开 | 本地优先（**sqlcipher3**，D1.1 替代 pysqlcipher3）|
| 复用 | 提供 10 角色 | 5 复制 + 委派 |

---

## 🎯 核心定位（员工视角）

### 我（员工）是谁？

- **服务者** — 帮你处理邮件/日程/账本/笔记，**不替你决策**
- **24h 在岗** — 周一 09:00 邮件到了就处理，周日 22:00 财务异常也提醒
- **数据管家** — 你的隐私数据（邮件正文、交易记录、笔记）**只存在你的 Mac 上**

### 我不做什么（铁律）

> **2026-06-11 修订**:D5 业务调度器解封"邮件发送",1-click 草稿可走 SMTP 真实发送(用户 1-click 审批后),仍保留"不抢控制权"原则 — 自动发送**必须有用户预先确认过的草稿**。

- ❌ **不抢控制权** — 草稿生成走两阶段:**① AI 生成 → outbox 库 → 1-click 审批 ② 用户审批后 D5 SMTP 真实发送**(D4.8 v1.0.1 + D5.7 锁定)
- ❌ **不联网外传** — 敏感数据（身份证/银行卡/私密笔记）走本地规则
- ❌ **不收费 SaaS** — 这是**你的工具**，不是订阅服务

---

## 📂 目录结构

```
我的AI员工/
├── README.md                 # 本文件
├── pyproject.toml            # 依赖管理（PEP 621 + uv）
├── uv.lock                   # 锁定版本（自动生成，提交）
├── package.json              # npm 依赖（markdownlint-cli2 锁版本）
├── package-lock.json         # npm 锁文件（提交）
├── .python-version           # Python 3.12 锁定
├── Makefile                  # 命令入口
├── .env.example              # 环境变量模板
├── .markdownlint.json        # 文档规范
├── .gitignore                # 忽略规则
├── src/
│   └── my_ai_employee/       # 主代码（D1.1 重构：去 src/ 顶层）
│       ├── main.py           # 入口（make hello）
│       ├── connectors/       # L1 适配器层（IMAP/CalDAV/账单/Notes）
│       ├── core/             # L2 数据层（SQLite/schema/models）
│       ├── ai/               # L3 智能层（分类/草稿/财务/笔记）
│       ├── agents/           # L4 Agent 层（@管家/@审计员 + Agent Assistant 5 复制）
│       └── menu_bar/         # Mac 菜单栏 UI
├── tests/                    # pytest 单元测试(2273 passed / 1 skipped,覆盖率 88.84%,fail_under=80 硬门槛)
├── docs/                     # 设计文档
│   ├── architecture.md       # 5 层架构
│   ├── week1-mvp.md          # Week 1 计划
│   └── week2-mvp.md          # Week 2 计划
├── reports/                  # 阶段报告归档（D1 报告等）
└── data/                     # 运行时数据（gitignore）
    ├── data.db               # SQLite 加密
    ├── health.log            # 适配器健康
    └── llm_audit.log         # LLM 调用审计
```

---

## 🚀 快速开始

> **D1.1 决策**：依赖管理从 **Poetry → uv**（PEP 621 标准格式），Python 固定 **3.12**。
>
> 旧 `poetry install` 命令已弃用，请用 `uv sync` 或 `make install`。

### 1. 安装依赖

```bash
cd ~/Documents/DesktopOrganizer/我的AI员工
make install    # 内部 = uv sync --extra dev + pip install -e .
```

或者手动：

```bash
uv sync --extra dev
uv pip install -e .
```

### 2. 验证项目跑通

```bash
make hello   # 输出 "Hello, 我的AI员工" + 当前时间
```

### 3. 跑测试

```bash
make test    # pytest 单元测试(2273 passed / 1 skipped,覆盖率 88.84%,fail_under=80 硬门槛)
```

### 4. 文档 lint

```bash
make install-npm    # 首次跑：装 markdownlint-cli2（项目级）
make lint           # 检查 .md 格式
```

### 5. 全部命令

```bash
make help
```

### 6. 直接运行（不通过 make）

```bash
.venv/bin/python -m my_ai_employee.main            # Hello 信息
.venv/bin/python -m my_ai_employee.main --info     # 项目详情
.venv/bin/python -m my_ai_employee.main --version  # 版本号
.venv/bin/python -m my_ai_employee.main --help     # 帮助
```

> **说明**：用 `python -m my_ai_employee.main` 而不是 `python src/my_ai_employee/main.py`，
> 避免 Python 把 main.py 当成顶层脚本而非包的一部分（D1.1 包名重构）。

输出示例：

```
📋 我的AI员工 — 可用命令

  make hello    验证项目跑通（Hello, 我的AI员工）
  make dev      启动开发模式（hot reload）
  make test     跑 pytest 单元测试
  make lint     Markdown 格式检查
  make run      启动主程序（占位）
  make clean    清理临时文件
  make help     显示本帮助
```

---

## 🗓️ 里程碑

> **2026-06-11 修订**:D4 智能层 + D4.8 草稿入库已锁定,D5 重新定义为业务调度器(SMTP 发送链路),CalDAV/菜单栏/launchd 顺延 D6+。

| 阶段 | 状态 | 完成日期 |
|------|------|----------|
| **D1 脚手架** | ✅ 完成 | 2026-06-07 |
| **D2 IMAP 适配器**（QQ 授权码 + Keychain + 熔断）| ✅ 完成 | 2026-06-07 |
| **D3 数据层 + 同步**（D3.1 加密 SQLite + D3.2 ORM/alembic + D3.3 IMAP 同步 1万封 0.35s）| ✅ 完成 | 2026-06-08 |
| **D4 智能层**（D4.1 LLM 路由 + D4.6 分类器 + D4.7 草稿生成 + D4.8 草稿入库 v1.0.1）| ✅ 完成 | 2026-06-11 |
| **D5 业务调度器**（SMTP 发送 + 状态机 + SLA）| ✅ **D5.7.2 真正锁定** | D5.1 ✅ / D5.2 ✅ / D5.3 ✅ / D5.4 ✅ / D5.5 ✅ / D5.6.3 ⏸️(4th round 驳回) / D5.6.4 ✅ (5 项第四轮修复 100% 落地) / **D5.6.5 ✅** (真实 1 封 SMTP 端到端实测通过, sent=1/1.27s, smtp.qq.com:465 SSL) / **D5.6.5.1 ✅** (检查员驳回 5 缺陷全部修复,P1-1 测试隔离 + P1-2 邮箱脱敏 + P2-1 SpikeResult 16 字段 + P2-2 文档一致 + P2-3 措辞澄清) / **D5.7 docs 收口 8 件套** ✅ / **D5.7.1 真正锁定** ✅ (检查员驳回 5 缺陷全部修复,P1-1 旧测试 SMTP 触网 + P1-2 邮箱脱敏固化 + P2-1 D5.7 状态统一 + P2-2 跨项目链接 + P2-3 SpikeResult 字段数 16 统一) / **D5.7.2 真正锁定** ✅ (docs 收口最后一致性修正,P1 D5 报告覆盖率表实测重生成 + P2-1 README 16 字段统一 + P2-2 阶段编号翻 D5.7.2 + P2-3 真实发送报告下一棒翻 v0.1 + P2-4 映射链接路径 + P2-5 DoD 证据补全) |
| **D6 微信账单适配器**（CSV 解析 + 3 层去重 + TransactionAdapter）| ✅ 完成 | 2026-06-15 |
| **D7 支付宝适配器**（CSV 解析 + 跨源去重 + import_all + 虚拟 spike）| ✅ 复检通过 | 2026-06-15 |
| **S6 财务端到端**（微信/支付宝导入 + 菜单栏支出更新）| ✅ 复检通过 | 2026-06-15 |
| **D9.1 Apple Notes 底座**（适配器 + NoteStore + 0008 migration）| ✅ 复检通过 | 2026-06-15 |
| **D9.2 sync_notes.py CLI**（subparsers spike/sync + 4 退出码 + alembic 校验 + HTML cleaner）| ✅ 落地 | 2026-06-15 |
| **D9.3 菜单栏骨架**（rumps NotesMenuBarApp + ExpenseServiceStub 5 方法）| ✅ 落地 | 2026-06-15 |
| **D9.4 NoteStructurerService**（3 入口 + 6 类 SYSTEM prompt + 抗注入范本）| ✅ 落地 | 2026-06-15 |
| **D9.5 ⌥⌘N 全局快捷键**（pynput 子进程 + TCC 引导 + open_privacy_settings）| ✅ 落地 | 2026-06-15 |
| **S7 剪贴板 → Notes 端到端**（NoteStore.insert + structure_and_emit + 30 笔 InMemory + 私有笔记业务阻断）| ✅ 落地 | 2026-06-15 |
| **D9.6 5 修复**（ClipboardCaptureService 3 入口 / AppleScript ASCII 30 协议 / sync_notes OperationalError 透传 → exit 3 / T11 队列真调 / coverage fail_under=80）| ✅ 落地 | 2026-06-15 |
| **D10.1** 7 Agent 角色契约测试(steward + auditor + agent_layer 53 tests)| ✅ 落地 | 2026-06-15 |
| **D10.2** monthly_report.py CLI + finance_monthly.md 模板(subparsers + 4 退出码 + 14 tests)| ✅ 落地 | 2026-06-15 |
| **D10.3** launchd_install.sh + plist + uninstall(5 源判定 + ~/bin/ 部署 + 21 tests)| ✅ 落地 | 2026-06-15 |
| **D10.4** S8 + S9 e2e 实化(去 skip 2 + 2 → 真实断言 3 + 6 = 9 tests)+ 9 场景 spike 全过 | ✅ 落地 | 2026-06-15 |
| **D10.5** docs/v0.1-release-notes.md 8 段 + README v0.1 + v0.1.0 git tag + 跨项目 memory | ✅ 收口 | 2026-06-15 |
| **v0.1.0 发布** | ✅ 收口(2026-06-15 D10.5,2026-07 中下旬正式发布) | - |
| **v0.2 B-5** Quartz CGEvent tap 替代 pynput(macOS Sequoia 兼容) + 11 cases + spike 30 笔 | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2 D8.1** MerchantProfile ORM + alembic 0011 + TransactionStore.list_by_counterparty | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2 D8.2** RuleBasedAnomalyDetector + AnomalyResult 6 类异常(规则基础 + 商家画像) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2 D8.3** 月报异常告警段接入 + 菜单栏"⚠️ 异常告警"菜单项 + ExpenseService 2 方法 | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2 D8.4** S11 真链路 spike(35 baseline + 1 ¥888 异常) + e2e 3 cases | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.1 #4** NoteStore 状态机化(sync_status 5 状态 NEW/STRUCTURED/PRIVATE_SKIP/FAILED/ARCHIVED + 状态机守卫 + 13 tests) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.1 #5** NoteStore L2/L3 跨源去重(normalized_fingerprint title+folder+updated_at_date SHA-256 + find_candidates_by_fingerprint + 11 tests) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.1 #3** ExpenseServiceStub 实化(ExpenseServiceImpl 7 方法 + NoteStore/AnomalyDetector + 5 分钟缓存 + 12 tests) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.1 #2** 真账单 spike 端到端(评估 + spike_real_bill.py 4 重防误发骨架 + 报告模板 + 13 tests,等用户 CSV) | ✅ 6/17 准备就绪 | 2026-06-17 |
| **v0.2.1 #6** OAuth 2.0 抽象层 Phase 1(OAuth2Provider Protocol + OAuth2Token/OAuth2Config + Keychain token 存取 + 14 tests,独立 outlook/gmail) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.1+ NoteStore L2 跨源写入**(needs_confirm + candidate_match_id + alembic 0014 + list_by_needs_confirm + 9 tests) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.2 #1** NoteStructurerService L2 候选 emit 接入(structure_and_emit 携带 needs_confirm/candidate_match_id + 事件模型扩展 + 4 tests) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.2 #2** NoteConfirmService 1-click 确认 UI 接入(Protocol/Stub/Impl + 菜单栏待确认列表/确认首条 + 32 tests) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.2 #3** L3 模糊匹配 ±1 day(商家名归一化 + 日期容错 + Notes L2→L3 fallback + 24 tests) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.2 #6** badge 实时刷新 polling(30s 间隔双 badge 同步 + 17 tests) | ✅ 6/17 落地 | 2026-06-17 |
| **v0.2.2 #7** tests/db/ FK 循环依赖 57 errors 修复(新增 tests/db/conftest.py + 57→0 errors) | ✅ 6/18 落地 | 2026-06-18 |
| **v0.2.2 #5** OAuth 2.0 Phase 2 docs-only 启动文档(5 commits 分解 + 端午不休息时间线) | 🟢 6/18 启动 | 2026-06-18 |
| **v0.2.2 #5 commit 2** MicrosoftOAuth2 实现(msal 接入 + 12 unit tests · 8/8 质量门全绿 · 沿 v0.2.2 范本) | ✅ 6/18 落地 | 2026-06-18 |
| **v0.2.2 #5 commit 3** GoogleOAuth2 实现(google-auth 接入 + 11 unit tests · 9/9 质量门全绿 · 沿 commit 2 范本) | ✅ 6/18 落地 | 2026-06-18 |
| **v0.2.2 #5 commit 4** XOAUTH2 SMTP 鉴权集成(RFC 7628 + 4 重防误发 + 12 unit tests · 顶层 placement 避免重构) | ✅ 6/18 落地 | 2026-06-18 |
| **v0.2.25** P0 二修(真账单 `--max-rows` 真透传 adapter + launchd seal bash bad substitution 修复) | ✅ 6/23 落地 | 2026-06-23 |
| **v0.2.26** W3 虚拟 spike 2345 行收口报告 | ✅ 6/23 落地 | 2026-06-23 |
| **v0.2.27** W3 真实 spike 2345 行收口报告 | ✅ 6/23 落地 | 2026-06-23 |
| **v0.2.28** L2 fingerprint sign-lock(消除 sign 反向误判 · 6 tests · 业务侧 `raw.type→+1/-1` 派生) | ✅ 6/23 落地 | 2026-06-23 |
| **v0.2.29** 候选 review/export 机制(`list_by_needs_confirm` 只读 + JSONL/CSV 导出 + 38 tests) | ✅ 6/23 落地 | 2026-06-23 |
| **v0.2.30** 候选导出硬化(`.gitignore` 保护 + CLI 错误硬化 · 沿 v0.2.18 §3 范本) | ✅ 6/23 落地 | 2026-06-23 |
| **v0.2.31** 候选 review 汇总闭环(6 维度聚合 + review_decision 三分类 + 14 tests · 撞坑 #46/#47/#48) | ✅ 6/24 落地 | 2026-06-24 |
| **v0.2.32** W3 真账单 spike + 撞坑 #49(faker ≠ 真实格式 · 2027 real parser + 4 tests · `--max-rows 1` 跑通 parsed=1 inserted=1 categorized=1 version=2027) | ✅ 6/24 落地 | 2026-06-24 |
| **v0.2.36** W3 真账单 `--max-rows 49` 全量入库收口(选项 B · 阶梯 1→5→10→25→49 五阶段 + 撞坑 #53 v2.0 累计公式 v2.0 + 撞坑 #54 选项 B 优于选项 A 范本 · `parsed=49 inserted=24 categorized=24 duplicates=25`) | ✅ 6/24 落地 | 2026-06-24 |
| **v0.2.37** docs-only 漂移小修(README L301 最后更新 → 历史版本说明 + MODIFICATION-LOG L148 待写 → 已写 · 撞坑 #50 第三层范本沿用) | ✅ 6/24 落地 | 2026-06-24 |
| **v0.2.38** P1-1 mypy 严格模式 9 errors 修复(沿 v0.2.23 cast 范本 + isinstance 守卫 · 撞坑 #55 严格模式 mypy 双 0 范本 · `mypy --check-untyped-defs src tests` 0 errors / 209 files) | ✅ 6/24 落地 | 2026-06-24 |
| **v0.2.39** 启用 `--check-untyped-defs` 为 CI 默认(Makefile mypy target 修复撞坑 #50 docstring/code 漂移 · 撞坑 #55 v2.0 范本升级严格模式 + CI 默认化 = 强制约束) | ✅ 6/24 落地 | 2026-06-24 |
| **v0.2.40** pyproject.toml mypy config 锁死 + 393 errors 全量修复(沿撞坑 #55 v3.0 范本 = 命令层 + 配置层 + Makefile 层 三重锁死 + 撞坑 #56 AST 注入顺序陷阱 · `mypy --disallow-untyped-defs` 0 errors / 209 files) | ✅ 6/24 落地 | 2026-06-24 |
| **v0.2.41** mypy `--strict` 启用 + 388 errors 大幅修复(沿撞坑 #55 v4.0 范本 = 四重锁死 + 388→43 errors = 89% 严格模式覆盖率 + 撞坑 #57 ast.unparse 注释丢失陷阱 · `mypy --strict src tests` 43 errors / 209 files) | ✅ 6/24 落地 | 2026-06-24 |
| **v0.2.42** mypy `--strict` 43 errors 清零 + 硬门锁死(Makefile 取消 `|| echo` 放行 · `mypy --strict src tests` 0 errors / 209 files · 2265 passed / 1 skipped / 88.76% coverage) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.43** outlook/gmail SMTP provider 白名单解封(`spike_send_100.py --smtp-provider {qq,outlook,gmail}` · provider-aware Keychain 能力对齐 · 不真发邮件 · 2265 passed / 1 skipped / 88.76% coverage) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.44** 跳过授权码 + 真实 SMTP spike 延后(用户明确“跳过授权码” · Keychain missing + InMemory sent=1 + SMTP_REAL_NETWORK 硬拦截实测 · 下一棒转 7/1 月度复盘准备) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.45** 7/1 月度复盘准备增量包(补齐 v0.2.36/v0.2.42/v0.2.43/v0.2.44 最新状态 · tag 前置条件从 6/8 更新为 7/8 实质满足 + SMTP 送达延后) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.46** 7/1 月度复盘提前执行版(质量门全绿 + B 类事项三态归档 + 8/1 `v0.2.1` release tag readiness 7/8 实质满足但真实 SMTP 送达延后) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.47** 8/1 release tag 预检包(撞坑 #58 8 项前置条件 + 1 缺口评估范本 + 真实 SMTP spike 恢复 checklist + OutboxDispatcher × SMTPProviderFactory 接入复核 · `make lint` 138 files 0 errors) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.48** align release readiness state(3 文件顶部口径同步到 v0.2.47 · README L7 + SESSION-STATE L1/L4/L12 + MODIFICATION-LOG L82/L83/L84/L87 + 138 files MD lint) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.49** 7/8 月度复盘收官 docs(v0.2.42-v0.2.48 完整时间线 + B 类三态 + 8/1 tag 8 项前置条件 + 7/8 月度复盘交付物闭环) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.50** 8/1 tag 锚定评估 preliminary(preliminary ≠ 最终决策 · 撞坑 #60 范本应用 · 距 8/1 还有 5 周关键时间窗) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.51** SMTPProviderFactory 接入(`feat(send_adapter)` smtp_provider 与 smtp_transport 互斥 + 3 测试覆盖 + 撞坑 #18 风险门控 + 2268 passed / 88.76% coverage / mypy --strict 0 errors / 141 files MD lint) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.52.2** 状态口径同步 + provider 封装硬化(`ProviderDefaults` + 只读属性 · OutboxDispatcher 改读公共 API · docs 三入口 2273/88.82%/143 files MD lint · `test_smpt_*` 拼写修正) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.52.3** 测试侧公共 API 一致性(OutboxDispatcher 暴露 `active_provider` + `provider_defaults` 公共属性 · 5 处私有属性断言迁移到公共 API · docs 三入口 2273/**88.84%** / **144 files** MD lint · 撞坑 #64 公共 API 迁移范本) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.53** Codex 风格 UI P0 启动(设计稿 + v0.2 launch plan 纳入 + `docs/ui/` 静态 HTML 原型 + 原型说明 · 不新增依赖 · 不接真实 DB/SMTP/Keychain · `make lint` **146 files** 0 errors) | ✅ 6/25 P0 启动 | 2026-06-25 |
| **v0.2.53.1** Codex UI P1 菜单栏升级(Codex IA · OutboxDraftService Stub · 打开工作台/系统健康 · +5 tests) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.53.2** P2 Dashboard 只读 API 骨架(`/api/status` + `/api/tasks/today` · stdlib `ThreadingHTTPServer` · `127.0.0.1` · 无新依赖 · 8 tests) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.53.3** Dashboard HTML 接只读 API(静态 HTML hydrate 两端点 + file 原型 CORS/OPTIONS + API 离线兜底 · 2286 passed / 88.46% / MD lint 152 files) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.53.4** Dashboard 只读 API 扩展(`/api/outbox` + `/api/notes/pending` + `/api/finance/anomalies` · +7 tests · 2293 passed / 88.49%) | ✅ 6/25 落地 | 2026-06-25 |
| **v0.2.54** 8/1 tag 复评 + SMTP 就绪检查(7/8 · outlook/gmail Keychain missing · InMemory sent=1) | ✅ 6/25 docs-only | 2026-06-25 |

---

## 🔧 技术栈（已确认）

| 维度 | 选择 | 备注 |
|------|------|------|
| Python | **3.12**（D1.1 固定，避开 3.14 wheel 风险）| `.python-version` 锁定 |
| 依赖管理 | **PEP 621 + uv**（D1.1 从 Poetry 切换）| `pyproject.toml` + `uv.lock`（提交）|
| 数据库 | SQLite + **sqlcipher3**（D1.1 从 pysqlcipher3 切换）| 加密 + 本地（coleifer 维护的活跃 fork）|
| LLM | **minimax M3**（统一链路）| 通过 Claude Code SDK |
| 邮件 | imapclient + OAuth 2.0 + smtplib(SSL 465) | Keychain 凭证(IMAP / SMTP 分别存) |
| CalDAV | iCloud 优先 | **D6+ 顺延**(原 D5,2026-06-11 重新定义) |
| GUI | rumps（Mac 菜单栏）| **D6+ 顺延**,Phase 2 加 Web Dashboard |
| 测试 | pytest + 覆盖率 | D1.1 覆盖率 0% → 62% → D4.8 90.2% → D5.1-fix 91.1%(1385 passed)→ D5.5.3 1522 passed / 90.2% → D5.5.4 1532 passed / 90.1% → D5.5.5 1534 passed / 90.3% → D5.6.4 1561 passed / 90.4% → D5.6.5 1563 passed / 90.4%(真实 SMTP 1 封新增 2 集成测试)→ S6 e2e 1738 passed / 90.1% → D9.5+S7 e2e 1839 passed / 89.6% → **D9.6 5 修复 1858 passed / 89.5%(fail_under=80 硬门槛)** → D10.1-D10.4 **1955 passed / 1 skipped / 89.48%**(D10.5 收口)→ post-tag 修复 **1958 passed / 1 skipped / 89.48%** → v0.2 B1/B2 docs 收口 **1964 passed / 1 skipped / 89.5%** → v0.2 B4.1 **1980 passed / 1 skipped / 89.45%** → v0.2 B4.2 **1988 passed / 1 skipped / 89.46%** → v0.2 B4.2 closure **1991 passed / 1 skipped / 89.47%** → v0.2 B4.3 + B-5 Quartz + D8.1-D8.4 **2024 passed / 1 skipped / 89.23%** → D8.5 半真实账单误报修复 **2028 passed / 1 skipped / 89.25%** → v0.2.1 #4 NoteStore 状态机化 **2041 passed / 1 skipped / 89.33%** → v0.2.1 #5+#3 **2064 passed / 1 skipped / 89.21%** → v0.2.1 #2 **2077 passed / 1 skipped / 89.21%** → v0.2.1 #6 + NoteStore L2 跨源写入 **2100 passed / 1 skipped / 89.07%** → v0.2.2 #1/#2 **2135 passed / 1 skipped / 89.03%** → v0.2.2 #3 **2159 passed / 1 skipped / 89.08%** → v0.2.2 #6/#7 **2176 passed / 1 skipped / 89.28%** → v0.2.2 #5 commit 2/3/4 **2211 passed / 1 skipped / 88.86%** → v0.2.2 #5 commit 5 + #8 + v0.2 launch plan 整体收口 + v0.2.4 + v0.2.5 **2220 passed / 1 skipped / 88.85%** → **v0.2.6 D4.7.4 v1.0.3 改进项延后 2225 passed / 1 skipped / 88.85%** → **v0.2.25 P0 二修 2240 passed / 1 skipped**(2026-06-23) → **v0.2.28 L2 sign-lock 2240 passed / 1 skipped**(2026-06-23,沿用) → **v0.2.31 候选 review 汇总闭环 2261 passed / 1 skipped**(2026-06-24,撞坑 #46/#47/#48) → **v0.2.32 W3 真账单 spike 2265 passed / 1 skipped**(2026-06-24,撞坑 #49 新增 2027 real parser + 4 tests) → **v0.2.33-v0.2.35 docs-only 2265 passed / 1 skipped / 88.77%**(2026-06-24,撞坑 #50/#52/#53 + 阶梯 1→5→10→25 范本 + 跨 spike 累计公式 v1.0) → **v0.2.36 W3 真账单 spike-49 全量入库 2265 passed / 1 skipped / 88.77%**(2026-06-24,撞坑 #53 v2.0 累计公式 + #54 选项 B 优于 A 范本 + 阶梯 5 阶段 1→5→10→25→49 全量入库收口) |
| 调度 | APScheduler + launchd | D5 自研 OutboxDispatcher(D4.8 IMAPSync 范本)→ D10.3 launchd_install.sh 部署(5 源判定 + ~/bin/)+ 每月 1 号 09:00 月报触发 |

---

## 📋 5 个 Day 0 决策（已确认）

| # | 决策 | 选择 |
|---|------|------|
| 1 | 依赖管理 | **PEP 621 + uv**（D1.1 从 Poetry 切换）|
| 2 | CalDAV 优先 | **iCloud**（Apple 生态）|
| 3 | 本地 LLM | **跳过**（统一 minimax M3）|
| 4 | SQLite 加密 | **sqlcipher3**（D1.1 从 pysqlcipher3 切换）|
| 5 | 启动向导语言 | **中文** |

**LLM 路由策略修正**（与原 architecture.md 不同）：

- 主路径：**minimax M3**（不区分类别）
- Fallback：**规则引擎**（关键词/正则）— **不做本地 Ollama**
- 离线：完全降级到只读

---

## 📖 文档地图

| 文档 | 用途 |
|------|------|
| [docs/v0.1-release-notes.md](docs/v0.1-release-notes.md) | **🎯 v0.1.0 发布说明(8 段结构,D10.5 收口)** |
| [reports/2026-07-monthly-review.md](reports/2026-07-monthly-review.md) | **🎯 2026-07 月度复盘提前执行版(v0.2.46 · 5 步执行 + B 类三态 + 8/1 tag readiness)** |
| [reports/v0.1-e2e-scenarios.md](reports/v0.1-e2e-scenarios.md) | **🎯 9 端到端场景 spike 汇总(D10.4)** |
| [docs/architecture.md](docs/architecture.md) | 5 层架构 + 关键决策 + 适配器契约 + 数据流示例 |
| [docs/week1-mvp.md](docs/week1-mvp.md) | Week 1 计划（D1-D5：邮件 + 日程）|
| [docs/week2-mvp.md](docs/week2-mvp.md) | Week 2 计划（D6-D10：财务 + 笔记）|
| [docs/v0.1-launch-plan.md](docs/v0.1-launch-plan.md) | v0.1 启动规划(D6/D7/D9/D10 4 子阶段 + 收口)|
| [docs/v0.2-launch-plan.md](docs/v0.2-launch-plan.md) | v0.2 启动规划(6 子阶段预映射 + 5 决策 + 完成定义)|
| [docs/v0.2.53-codex-style-ui-design-2026-06-25.md](docs/v0.2.53-codex-style-ui-design-2026-06-25.md) | **🆕 v0.2.53 Codex 风格 UI 设计稿(本地工作台 + P0/P1/P2 路线)** |
| [docs/v0.2.53.2-dashboard-readonly-api-2026-06-25.md](docs/v0.2.53.2-dashboard-readonly-api-2026-06-25.md) | **🆕 v0.2.53.2 P2 Dashboard 只读 API 骨架(`/api/status` + `/api/tasks/today`)** |
| [docs/v0.2.53.3-dashboard-html-api-bridge-2026-06-25.md](docs/v0.2.53.3-dashboard-html-api-bridge-2026-06-25.md) | **🆕 v0.2.53.3 静态 Dashboard 接只读 API + 离线兜底** |
| [docs/v0.2.53.4-dashboard-readonly-api-extended-2026-06-25.md](docs/v0.2.53.4-dashboard-readonly-api-extended-2026-06-25.md) | **🆕 v0.2.53.4 只读 API 扩展(outbox/notes/finance)** |
| [docs/ui/codex-style-dashboard.md](docs/ui/codex-style-dashboard.md) | **🆕 Codex 风格工作台 P0/P2 静态原型说明(今日 / 邮件 / 系统 + API)** |
| [docs/v0.2.1-candidates-2026-06-17.md](docs/v0.2.1-candidates-2026-06-17.md) | **🆕 v0.2.1 启动候选清单(6 候选 + 工作量/依赖/风险 3 维度)** |
| [docs/v0.1.0-status-snapshot-2026-06-17.md](docs/v0.1.0-status-snapshot-2026-06-17.md) | **🆕 v0.1.0 tag 状态快照(释放/锁定/后期启动 3 维度复核)** |
| [reports/v0.2.1-closure-2026-06-17.md](reports/v0.2.1-closure-2026-06-17.md) | **🆕 v0.2.1 docs 收口报告(9 commits 链 + 6 候选全部实化 + 5 关键教训 + v0.2.2+ 启动候选)** |
| [reports/v0.2.2-p0-l2-emit-2026-06-17.md](reports/v0.2.2-p0-l2-emit-2026-06-17.md) | **🆕 v0.2.2 #1 NoteStructurerService L2 候选 emit 接入收口报告** |
| [reports/v0.2.2-p2-1click-confirm-ui-2026-06-17.md](reports/v0.2.2-p2-1click-confirm-ui-2026-06-17.md) | **🆕 v0.2.2 #2 NoteConfirmService 1-click 确认 UI 收口报告** |
| [reports/v0.2.2-p3-l3-fuzzy-matching-2026-06-17.md](reports/v0.2.2-p3-l3-fuzzy-matching-2026-06-17.md) | **🆕 v0.2.2 #3 L3 模糊匹配 ±1 day 收口报告** |
| [reports/v0.2.2-p6-badge-realtime-refresh-2026-06-17.md](reports/v0.2.2-p6-badge-realtime-refresh-2026-06-17.md) | **🆕 v0.2.2 #6 badge 实时刷新 polling 收口报告** |
| [reports/v0.2.2-p7-fk-circular-2026-06-18.md](reports/v0.2.2-p7-fk-circular-2026-06-18.md) | **🆕 v0.2.2 #7 tests/db/ FK 循环依赖 57 errors 修复收口报告** |
| [docs/v0.2.2-p5-oauth-phase2-launch-2026-06-18.md](docs/v0.2.2-p5-oauth-phase2-launch-2026-06-18.md) | **🆕 v0.2.2 #5 OAuth 2.0 Phase 2 docs-only 启动文档** |
| [reports/v0.2.2-p5-oauth-microsoft-2026-06-18.md](reports/v0.2.2-p5-oauth-microsoft-2026-06-18.md) | **🆕 v0.2.2 #5 commit 2 MicrosoftOAuth2 收口报告(12 new tests · 8/8 门全绿)** |
| [reports/v0.2.2-p5-oauth-google-2026-06-18.md](reports/v0.2.2-p5-oauth-google-2026-06-18.md) | **🆕 v0.2.2 #5 commit 3 GoogleOAuth2 收口报告(11 new tests · 9/9 门全绿)** |
| [reports/v0.2.2-p5-oauth-xoauth2-2026-06-18.md](reports/v0.2.2-p5-oauth-xoauth2-2026-06-18.md) | **🆕 v0.2.2 #5 commit 4 XOAUTH2 SMTP 鉴权集成收口报告(12 new tests · 9/9 门全绿)** |
| [reports/v0.2.1-candidates-closure-2026-06-18.md](reports/v0.2.1-candidates-closure-2026-06-18.md) | **🆕 v0.2.1 docs 校准收口报告(6 候选盘点 + 状态漂移修复范本 · 4 候选已 commit 盘点)** |
| [docs/v0.2.18-docs-assumption-pitfall-2026-06-22.md](docs/v0.2.18-docs-assumption-pitfall-2026-06-22.md) | **🆕 v0.2.18 docs 假设错误类撞坑专项清单 + 撞坑恢复 3 步实战演练 11(撞坑史 6 类首次专项固化 + 撞坑 #24-#28 + #29 新增 · 范本累计 11)** |
| [docs/v0.2.20-restart-preflight-result-2026-06-22.md](docs/v0.2.20-restart-preflight-result-2026-06-22.md) | **🆕 v0.2.20 6/23 全链路重启实操前复核结果 docs-only(5 校验命令实测 5/5 通过 → GO · A0-A4 5 步实操 · 不扩展新范本只记录结果 · 撞坑 #24/#27/#28/#30/#31 实际命中)** |
| [docs/v0.2.19-6-23-restart-execution-package-2026-06-22.md](docs/v0.2.19-6-23-restart-execution-package-2026-06-22.md) | **🆕 v0.2.19 6/23 全链路重启执行包 docs-only(5 段紧凑 · 不沿用 v0.2.18 12 段范本 · 阶段 1-5 复核 5 校验命令 + 阶段 6-7 启动条件 + 6/23 待用户触发清单)** |

---

## 🚫 反例（明确不做什么）

> 与 "📌 下一棒" 协议配合，确保不偏离核心。

- ❌ **不做 IM（即时通讯）** — 隐私雷区 + 监管风险
- ❌ **不做支付/银行直连** — 合规成本远超收益
- ❌ **不做 toB 套壳** — 你不是产品经理
- ❌ **不做云端优先** — 违反"数据不出本机"原则
- ❌ **不做通用 ChatGPT 包装** — 红海 + 无差异化
- ❌ **不做政府/医疗数据** — 员工身份边界

---

## 🤝 相关项目

- **Agent Assistant**（`../Agent Assistant/`）：10 角色多 Agent 系统（本项目复用的 agent 来源）
- **海天水务 SAP 运维项目**（`../SAP运维项目/`）：SAP FICO 业务知识（被 Agent Assistant 引用）

---

**历史版本说明(沿用撞坑 #50 第三层范本 · 不再"最后更新"口吻)**:本段改写为 v0.2.19(2026-06-22)历史说明 — 当期 6/23 全链路重启执行包 docs-only 收口 + README 状态漂移校准。`git tag v0.1.0` 仍在 commit `2af775f` 不动(v0.1.0 不封口)；README 不再记录精确 HEAD hash，避免 post-tag docs/status commit 后继续漂移，真实 HEAD 以 `git rev-parse --short HEAD` 为准。v0.2 B-5 + D8 实施链已落:Makefile 9 门补齐 + pyobjc-framework-Quartz + clipboard_listener pynput→Quartz + 11 tests + spike 30 笔；D8 规则异常检测 + 商家画像 + 月报/菜单栏接入 + S11 e2e 已落；D8.5 半真实账单误报修复已落；W3 faker 三阶段验证完整。**v0.2.1 docs 校准盘点 4 候选已 commit**:`de5de10` ExpenseServiceStub 实化 + `0a1386c` NoteStore 状态机化 + `75f87cc` + `b751820` NoteStore L2/L3 跨源去重 / NoteStore L2 跨源写入 + v0.2.1 #2 真账单 spike 准备就绪 + v0.2.1 #6 OAuth 2.0 抽象层 Phase 1 docs-only 评估。v0.2.2 #1/#2/#3/#6/#7 已落；v0.2.2 #5 OAuth Phase 2 docs-only + MicrosoftOAuth2 + GoogleOAuth2 + XOAUTH2 SMTP 鉴权集成 + 依赖加锁已落(commit `b7b9ea7` / `c0f83d4` / `564b8db` / `9966ad0` / `6a0549e`)。当前 `make test` **2225 passed / 1 skipped / 88.85%**(2026-06-22 实测沿用)，常规 8/8 质量门全绿；deep-dry-run 已沉淀 mypy tests 13 个历史 baseline 错误。Outlook/Gmail SMTP provider 已部分实化,真实发送仍需授权 + 凭据 + B 类白名单决策。**当前状态以 L7 顶部状态块为准**(v0.2.40 pyproject.toml mypy config 锁死 + 393 errors 全量修复已收口,2026-06-24 · 撞坑 #55 v3.0 三重锁死),`make test` **2265 passed / 1 skipped / 88.77%** + `make mypy` **0 errors / 209 files**(2026-06-24 9/9 质量门全绿),v0.2.1 release tag 锚定策略沿 D5.7.2 范本 8/1 评估。**v0.2.40 下一棒候选**:enable mypy `--strict`(需用户授权)→ outlook-gmail SMTP 真实发送 spike(等 Keychain 凭据 + 授权)→ 7/1 月度复盘。
**当前模型**：MiniMax-M3
**维护者**：Mr-PRY
