# 我的AI员工 — 全天候个人 AI 数字员工

> **一句话**：把 Agent Assistant 的 10 角色从"晨晚链路"升级为"全天候数字员工"，能力 = 邮件 + 日程 + 财务 + 笔记 + 主动提醒。
>
> **核心差异化**：数据不出本机（隐私优先）+ 与 Agent Assistant 无缝衔接（Skill 复用）+ minimax M3 LLM（统一链路）。
>
> **状态**：🎯 **v0.1.0 tag 已落、v0.2.4 状态漂移审查机制入库、v0.2 launch plan 整体收口 docs(57 主项目 commits · 13 子阶段双链)、v0.2.2 #8 SMTPProviderFactory 部分实化、v0.2.1 docs 校准完成(状态漂移修复)、v0.2.2 实施链推进中**(2026-06-18 22:30 复核)。`git tag v0.1.0` 锚定 commit `2af775f` 不动；按用户 6/16 晚指令，本轮不封口 v0.1.0、不跑 6/23 kickstart + seal 脚本、不打 v0.2.0 tag。D1-D7 + D9 Apple Notes + D10 Agent/月报/launchd + 6/16 A/B/C/D 真实 spike 已收口；v0.2 B1/B2/B4 已实化，B-5 已从 pynput 切到 Quartz CGEvent tap，D8 已完成规则异常检测 + 商家画像 + 月报/菜单栏接入 + S11 e2e，D8.5 已完成半真实账单误报修复，D8 W3 faker 三阶段验证完整(30/102/1000 笔)。**v0.2.1 #3/#4/#5/#6 与 v0.2.1+ NoteStore L2 跨源写入已落地**(2026-06-18 docs-only 校准盘点 4 候选:`de5de10` ExpenseServiceStub 实化 + `0a1386c` NoteStore 状态机化 + `75f87cc` + `b751820` NoteStore L2/L3 跨源去重 / NoteStore L2 跨源写入)。v0.2.2 #1/#2/#3/#6/#7 已落地；v0.2.2 #5 OAuth 2.0 Phase 2 已 **5 commits 收口**(docs-only 启动 `b7b9ea7` + commit 2 MicrosoftOAuth2 `c0f83d4` + commit 3 GoogleOAuth2 `564b8db` + commit 4 XOAUTH2 `9966ad0` + commit 5 依赖加锁 `6a0549e`)；v0.2.2 #8 SMTPProviderFactory 工厂模式实化(`b2cf3c5` + `51da8fd`,撞坑恢复 commit,10 new tests,QQ/Outlook/Gmail connector + provider-aware Keychain,**真实发送仍受 SMTP_REAL_NETWORK + spike_send_100 provider 白名单门控**)。**v0.2 launch plan 整体收口**(2026-06-18 端午不休息第 1 天锚定 · 13 子阶段双链锚定 · 57 主项目 commits · 撞坑恢复范本沉淀)。**v0.2.4 状态漂移审查机制入库**(4 机制 + 7/1 月度复盘 checklist + 撞坑恢复 3 步范本 + 撞坑分类 2 类)。当前 `make test` **2220 passed / 1 skipped / coverage 88.85%**，8/8 质量门全绿。详见 [docs/v0.2.4-drift-review-mechanism-2026-06-18.md](docs/v0.2.4-drift-review-mechanism-2026-06-18.md)(v0.2.4 状态漂移审查机制入库 · 7/1 月度复盘准备)。详见 [reports/v0.2-closure-2026-06-18.md](reports/v0.2-closure-2026-06-18.md)(v0.2 launch plan 整体收口 docs · 撞坑恢复范本)。详见 [reports/v0.2.2-p8-smtp-provider-factory-2026-06-18.md](reports/v0.2.2-p8-smtp-provider-factory-2026-06-18.md)(v0.2.2 #8 SMTPProviderFactory 收口 · 撞坑恢复 commit)。详见 [reports/v0.2.1-candidates-closure-2026-06-18.md](reports/v0.2.1-candidates-closure-2026-06-18.md)(v0.2.1 6 候选盘点 + 状态漂移修复范本)。详见 [reports/v0.2.2-p5-oauth-deps-2026-06-18.md](reports/v0.2.2-p5-oauth-deps-2026-06-18.md) / [reports/v0.2.2-p5-oauth-xoauth2-2026-06-18.md](reports/v0.2.2-p5-oauth-xoauth2-2026-06-18.md) / [reports/v0.2.2-p5-oauth-google-2026-06-18.md](reports/v0.2.2-p5-oauth-google-2026-06-18.md) / [reports/v0.2.2-p5-oauth-microsoft-2026-06-18.md](reports/v0.2.2-p5-oauth-microsoft-2026-06-18.md) / [docs/v0.2.2-p5-oauth-phase2-launch-2026-06-18.md](docs/v0.2.2-p5-oauth-phase2-launch-2026-06-18.md) / [reports/v0.2.2-p7-fk-circular-2026-06-18.md](reports/v0.2.2-p7-fk-circular-2026-06-18.md)。

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
├── tests/                    # pytest 单元测试(2211 passed / 1 skipped,覆盖率 88.86%,fail_under=80 硬门槛)
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
make test    # pytest 单元测试(2211 passed / 1 skipped,覆盖率 88.86%,fail_under=80 硬门槛)
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
| 测试 | pytest + 覆盖率 | D1.1 覆盖率 0% → 62% → D4.8 90.2% → D5.1-fix 91.1%(1385 passed)→ D5.5.3 1522 passed / 90.2% → D5.5.4 1532 passed / 90.1% → D5.5.5 1534 passed / 90.3% → D5.6.4 1561 passed / 90.4% → D5.6.5 1563 passed / 90.4%(真实 SMTP 1 封新增 2 集成测试)→ S6 e2e 1738 passed / 90.1% → D9.5+S7 e2e 1839 passed / 89.6% → **D9.6 5 修复 1858 passed / 89.5%(fail_under=80 硬门槛)** → D10.1-D10.4 **1955 passed / 1 skipped / 89.48%**(D10.5 收口)→ post-tag 修复 **1958 passed / 1 skipped / 89.48%** → v0.2 B1/B2 docs 收口 **1964 passed / 1 skipped / 89.5%** → v0.2 B4.1 **1980 passed / 1 skipped / 89.45%** → v0.2 B4.2 **1988 passed / 1 skipped / 89.46%** → v0.2 B4.2 closure **1991 passed / 1 skipped / 89.47%** → v0.2 B4.3 + B-5 Quartz + D8.1-D8.4 **2024 passed / 1 skipped / 89.23%** → D8.5 半真实账单误报修复 **2028 passed / 1 skipped / 89.25%** → v0.2.1 #4 NoteStore 状态机化 **2041 passed / 1 skipped / 89.33%** → v0.2.1 #5+#3 **2064 passed / 1 skipped / 89.21%** → v0.2.1 #2 **2077 passed / 1 skipped / 89.21%** → v0.2.1 #6 + NoteStore L2 跨源写入 **2100 passed / 1 skipped / 89.07%** → v0.2.2 #1/#2 **2135 passed / 1 skipped / 89.03%** → v0.2.2 #3 **2159 passed / 1 skipped / 89.08%** → v0.2.2 #6/#7 **2176 passed / 1 skipped / 89.28%** → v0.2.2 #5 commit 2/3/4 **2211 passed / 1 skipped / 88.86%**(2026-06-18 20:30 实测,9/9 质量门全绿) |
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
| [reports/v0.1-e2e-scenarios.md](reports/v0.1-e2e-scenarios.md) | **🎯 9 端到端场景 spike 汇总(D10.4)** |
| [docs/architecture.md](docs/architecture.md) | 5 层架构 + 关键决策 + 适配器契约 + 数据流示例 |
| [docs/week1-mvp.md](docs/week1-mvp.md) | Week 1 计划（D1-D5：邮件 + 日程）|
| [docs/week2-mvp.md](docs/week2-mvp.md) | Week 2 计划（D6-D10：财务 + 笔记）|
| [docs/v0.1-launch-plan.md](docs/v0.1-launch-plan.md) | v0.1 启动规划(D6/D7/D9/D10 4 子阶段 + 收口)|
| [docs/v0.2-launch-plan.md](docs/v0.2-launch-plan.md) | v0.2 启动规划(6 子阶段预映射 + 5 决策 + 完成定义)|
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

**最后更新**：2026-06-18 21:30(**v0.2.1 #3/#4/#5 docs-only 校准(状态漂移修复)落地** + v0.2.2 #5 commit 5 依赖加锁收口)。`git tag v0.1.0` 仍在 commit `2af775f` 不动(v0.1.0 不封口)；README 不再记录精确 HEAD hash，避免 post-tag docs/status commit 后继续漂移，真实 HEAD 以 `git rev-parse --short HEAD` 为准。v0.2 B-5 + D8 实施链已落:Makefile 9 门补齐 + pyobjc-framework-Quartz + clipboard_listener pynput→Quartz + 11 tests + spike 30 笔；D8 规则异常检测 + 商家画像 + 月报/菜单栏接入 + S11 e2e 已落；D8.5 半真实账单误报修复已落；W3 faker 三阶段验证完整。**v0.2.1 docs 校准盘点 4 候选已 commit**:`de5de10` ExpenseServiceStub 实化 + `0a1386c` NoteStore 状态机化 + `75f87cc` + `b751820` NoteStore L2/L3 跨源去重 / NoteStore L2 跨源写入 + v0.2.1 #2 真账单 spike 准备就绪 + v0.2.1 #6 OAuth 2.0 抽象层 Phase 1 docs-only 评估。v0.2.2 #1/#2/#3/#6/#7 已落；v0.2.2 #5 OAuth Phase 2 docs-only + MicrosoftOAuth2 + GoogleOAuth2 + XOAUTH2 SMTP 鉴权集成 + 依赖加锁已落(commit `b7b9ea7` / `c0f83d4` / `564b8db` / `9966ad0` / `6a0549e`)。当前 `make test` **2211 passed / 1 skipped / 88.86%**，`mypy src tests` / `ruff check` / `ruff format --check .` / `alembic upgrade head --sql` / `uv build` / `make lint` / `coverage fail_under=80` 9/9 质量门全绿。Outlook/Gmail SMTP provider 仍为 docs-only 评估,未实施代码。**下一棒**:6/19-22 端午 4 天链路不停,继续推进 v0.2.2+ 启动候选(候选 #2 真账单 spike 等真 CSV / 候选 #1 outlook/gmail SMTP 单独决策)；6/23+ 手动 launchctl kickstart + W3 真账单 spike(等真 CSV)+ 可选真实 OAuth flow spike。
**当前模型**：MiniMax-M3
**维护者**：Mr-PRY
