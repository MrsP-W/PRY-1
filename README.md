# 我的AI员工 — 全天候个人 AI 数字员工

> **一句话**：把 Agent Assistant 的 10 角色从"晨晚链路"升级为"全天候数字员工"，能力 = 邮件 + 日程 + 财务 + 笔记 + 主动提醒。
>
> **核心差异化**：数据不出本机（隐私优先）+ 与 Agent Assistant 无缝衔接（Skill 复用）+ minimax M3 LLM（统一链路）。
>
> **状态**：🚧 D1-D5.5.4 已完成（D5 业务调度器推进中：D5.1 ✅ → D5.2 ✅ → D5.3 ✅ → D5.4 ✅ → D5.5 ✅ → D5.5.1 ✅ → D5.5.2 ✅ → D5.5.3 ✅ P0 外部 symlink 修复 + P1 调度公平性 + P2 Heartbeat 恢复 → D5.5.4 ✅ P1 双向回填 + 单槽跨轮次轮换 + P3 refresh_last_seen bool 严判；下一步 D5.6 真实发送 spike）。详见 [docs/architecture.md](docs/architecture.md) / [docs/week1-mvp.md](docs/week1-mvp.md) / [docs/week2-mvp.md](docs/week2-mvp.md)。

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
| 复用 | 提供 10 角色 | 软链接 + 委派 |

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
│       ├── agents/           # L4 Agent 层（@管家/@审计员 + Agent Assistant 软链）
│       └── menu_bar/         # Mac 菜单栏 UI
├── tests/                    # pytest 单元测试（D5.5.4:1526 个，覆盖率约 90.2%）
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
make test    # pytest 单元测试（D5.5.4:1526 个，覆盖率约 90.2%）
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
| **D5 业务调度器**（SMTP 发送 + 状态机 + SLA）| 🚧 推进中 | D5.1 ✅ / D5.2 ✅ / D5.3 ✅ / D5.4 ✅ / D5.5 ✅ / D5.6-D5.7 待 |
| D6+ CalDAV + 菜单栏 + launchd | ⏸️ 顺延 | Week 2 决策点 |
| **Week 1 末决策点** | ⏳ | - |
| D7-D11 Week 2 | ⏳ | - |
| **v0.1 发布** | ⏳ | - |

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
| 测试 | pytest + 覆盖率 | D1.1 覆盖率 0% → 62% → D4.8 90.2% → D5.1-fix 91.1%(1385 passed)→ D5.5.3 1522 passed / 90.2% → D5.5.4 1526 passed / 90.2% |
| 调度 | APScheduler + launchd | D5 自研 OutboxDispatcher(D4.8 IMAPSync 范本),launchd D6+ 顺延 |

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
| [docs/architecture.md](docs/architecture.md) | 5 层架构 + 关键决策 + 适配器契约 + 数据流示例 |
| [docs/week1-mvp.md](docs/week1-mvp.md) | Week 1 计划（D1-D5：邮件 + 日程）|
| [docs/week2-mvp.md](docs/week2-mvp.md) | Week 2 计划（D6-D10：财务 + 笔记）|

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

**最后更新**：2026-06-12（D5.5.4:P1 配额浪费(双向回填)+ 单槽饥饿(跨轮次轮换) + P3 refresh_last_seen bool 严判,1526 passed / 8 质量门全绿 / 90.2% 覆盖）
**当前模型**：MiniMax-M3
**维护者**：Mr-PRY
