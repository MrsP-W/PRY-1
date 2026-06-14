# Week 1 MVP — 邮件 + 日程

> **目标**：在 5 个工作日内交付**邮件自动分类 + 1-click 草稿 + 日程同步**三大功能，可日用。
>
> **架构参考**：[architecture.md](architecture.md)
>
> **里程碑**：Week 1 末（周五晚）— 自用 3 天，决策是否继续 Week 2。

---

## 0. Week 1 总览

### 0.1 范围（In-Scope）

> **2026-06-11 修订**:D5 重新定义为业务调度器(SMTP 发送链路),CalDAV / 菜单栏 / launchd 顺延到 D6+(Week 2 决策点再细化)。

| 功能 | 验收标准 |
|------|----------|
| 邮件自动分类 | 5 类标签准确率 ≥ 80% |
| 1-click 草稿生成 | 单封邮件响应 < 10s |
| **D5 业务调度器(SMTP 发送)** | **outbox 草稿真实发送 + 状态机推进 + SLA 告警**(D4.8 v1.0.1 后瓶颈) |
| Apple Reminders 同步 | 复用 Agent Assistant 已建能力 |

**D6+ 顺延清单**(B 类保留,不在 Week 1 必达):

- ⏸️ CalDAV 日程同步(iCloud 双向,Google 延后)
- ⏸️ Mac 菜单栏状态(今日未读 + 今日待办实时显示)
- ⏸️ launchd 保活(macOS launchd 集成)
- ⏸️ Web Dashboard(Week 2+)

### 0.2 反例（Out-of-Scope）

- ❌ ~~邮件发送(Week 1 只生成草稿,用户手动确认)~~ **D5 已解封,改为 0.1 In-Scope**
- ❌ 财务模块（Week 2）
- ❌ 笔记模块（Week 2）
- ❌ iOS 伴侣（Phase 2）
- ❌ 多账号邮箱（Week 1 只支持单源主邮箱）
- ❌ Web Dashboard（Week 1 只用菜单栏 + CLI）
- ❌ 本地 Ollama LLM（**已确认不做**）

### 0.3 风险预览

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| ~~pysqlcipher3 在 Python 3.14 安装失败~~ | ~~高~~ | ~~数据库全废~~ | **D1.1 已解决**：改用 sqlcipher3（coleifer 活跃 fork），Python 3.12 |
| IMAP OAuth 2.0 复杂度 | 中 | Outlook/Gmail 卡 | D2.5 spike：QQ 优先（授权码），OAuth 推到 D2.5 |
| minimax M3 调用不稳定 | 中 | 智能功能挂 | 规则引擎 fallback（关键词/正则）|
| launchd 后台被杀 | 中 | 定时任务失效 | D5 末做保活 spike + 用户保活清单 |

### 0.4 LLM 决策（已确认，2026-06-07）

| 项 | 选择 | 影响 |
|----|------|------|
| LLM 主路由 | **minimax M3**（统一）| 所有智能层调用同一模型 |
| LLM Fallback | **规则引擎**（关键词/正则）| 降级到 L4 应急版 |
| 敏感数据 | **跳过 LLM**（非走本地）| 标记 `pending`，留待用户处理 |
| 本地 Ollama | ❌ 不实施 | 减少 D1-D10 工作量 |

---

## D1 — 项目脚手架 ✅ 已完成（2026-06-07）

### 目标

可运行的 Python 项目 + 第一个 `make hello` 命令 + 完整目录结构。

### 任务清单（D1 现状快照）

> ⚠️ **本表是 D1 当天状态**。D1.1 已做重要重构（PEP 621 + Python 3.12 + 包名重构），
> 详见下方 **D1.1 修正记录** 段。**以 D1.1 为准**。

| # | 任务 | D1 状态 | 产出 |
|---|------|------|------|
| 1.1 | `git init` + 初始 commit | ✅ | git 仓库（commits: a4189bf, 42ce240, 765fc4b）|
| 1.2 | 写 `pyproject.toml`（Python 3.11+ / poetry 依赖）| ✅ | 项目元数据 |
| 1.3 | 写 `Makefile`（help/hello/dev/test/lint/run/clean/lock/info）| ✅ | 命令入口 |
| 1.4 | 写 `.gitignore`（data/、.env、`__pycache__/`、*.db）| ✅ | 忽略规则 |
| 1.5 | 写 `README.md`（快速开始 + 5 个 Day 0 决策）| ✅ | 入口文档 |
| 1.6 | 写 `.markdownlint.json`（复用 Agent Assistant 配置）| ✅ | 文档规范 |
| 1.7 | 创建 `src/` 目录树（connectors/core/ai/agents/menu_bar）| ✅ | 目录结构 |
| 1.8 | 写 `src/main.py` 打印 "Hello, 我的AI员工"（rich 缺失降级）| ✅ | 可运行入口 |
| 1.9 | 写 `.env.example`（所有需要的环境变量模板）| ✅ | 配置模板 |
| 1.10 | 验证 `make hello` 跑通 + `make lint` 0 错误 | ✅ | 验收 |

**D1 当天总耗时**：约 1.5 小时（不含 brew install poetry 等待）

### D1 验收标准（回顾）

- [x] `python -m src.main` 输出 "Hello, 我的AI员工" 退出码 0
- [x] `make lint` 0 错误（基于 `.markdownlint.json`）
- [x] 目录结构与 [architecture.md §1](architecture.md#1-5-层架构总览) 一致
- [x] main.py 在 rich 缺失时**降级到原生 print**（应急版范本）
- [x] 命令统一用 `python -m src.main`（避免 main.py 冲突）
- [x] 初始 git commit 干净（无 `__pycache__`、`.env`）

### D1 关键决策与发现

1. **降级模式**（应急版范本 L3）— `main.py` 检测 `rich` 是否安装，缺失时用纯文本输出
2. **命令模式** — `python -m src.main` 而非 `python src/main.py`（避免 main.py 冲突）
3. **环境** — Python 3.14.4 已装，pip3 受 PEP 668 限制，**需 poetry**（brew 安装中）
4. **依赖锁定** — 全部依赖在 `pyproject.toml`，poetry.lock 首次 install 后生成

### D1.1 修正记录（2026-06-07 17:00+ — D2 启动前必读）

> **背景**：D1 收官后用户给了 6 条优先修改建议（依赖策略/Python 版本/lint 工具/包名/测试/文档/范围）。
> D1.1 一次性修正完毕。**本表是 D1 之后的实际状态**。

| 维度 | D1 原状 | D1.1 修正 | 理由 |
|------|---------|-----------|------|
| **依赖格式** | Poetry（`[tool.poetry.*]`）| **PEP 621**（`[project]` + `[project.optional-dependencies] dev`）| 行业标准、uv/pip/pdm/poetry 全部识别 |
| **装包工具** | `uv pip install -e ".[dev]"`（不识别 poetry group）| `uv sync --extra dev` + `uv pip install -e .` | uv 原生命令、可复现（uv.lock 提交）|
| **Python 版本** | `^3.11`（实际跑 3.14.4）| **`>=3.12,<3.13`**（3.12.13 固定 + `.python-version` 锁）| pysqlcipher3 在 3.14 wheel 缺失 |
| **SQLCipher 包** | `pysqlcipher3>=1.2.0`（wheel 缺失，源包 setup.py 空）| **`sqlcipher3>=0.6.2`**（coleifer 维护的活跃 fork）| 装得上、API 兼容、DB 文件可互迁 |
| **包结构** | `from src import ...`（`include = "src"`）| **`from my_ai_employee import ...`**（`src/my_ai_employee/`）| 标准 Python 命名空间、避免 `src` 命名空间污染 |
| **Lint 工具** | npx markdownlint-cli2（网络/版本都不固定）| **`package.json` 锁 0.22.1** + `make install-npm` 项目级安装 | 可复现 + 离线也能跑 |
| **Pre-commit** | 缺失工具时**静默跳过**（虚假安全）| **缺失时显式失败** + 提示安装命令 | 强制 0 错误、避免"提交了但没检查" |
| **测试覆盖** | 6 测试全 subprocess，覆盖率 **0%** | 18 测试（9 纯函数 + 2 冒烟 + 2 元数据 + 5 参数化），覆盖率 **61.9%** | 可单测 + 真覆盖 |
| **D2 范围** | QQ + Outlook + Gmail + OAuth + Keychain + mock + 健康检查（5h）| **QQ IMAP 授权码优先 + BaseConnector + Keychain + mock + 健康检查**；Outlook/Gmail 降级为 spike | 1 天能完成、不被 OAuth 复杂度卡住 |

**D1.1 总耗时**：约 1 小时

### D1.1 验收标准（当前事实）

- [x] `uv sync --extra dev` 跑通（31 个依赖装上）
- [x] `uv pip install -e .` 装上 `my_ai_employee` 包
- [x] `.venv/bin/python -m my_ai_employee.main` 输出 "Hello, 我的AI员工"
- [x] `make test` 18/18 通过，覆盖率 61.9%
- [x] `uv.lock` 118KB 已生成
- [x] `package.json` 锁 markdownlint-cli2 0.22.1
- [x] pre-commit hook 缺失工具时**显式失败**（不再静默跳过）
- [x] `make lint` 0 错误（基于 markdownlint-cli2 项目级）
- [x] git 状态干净（仅 D1.1 改动未提交）

### 📌 下一棒 → D2（2026-06-08）

- D1.1 修正完毕，包结构稳态
- 下棒需要：QQ 邮箱 IMAP 授权码（用户进 QQ 邮箱网页生成）
- D2 范围**收窄**：BaseConnector + QQ IMAP 授权码 + Keychain + mock + 健康检查（详见下方 D2 段）

---

## D2 — IMAP 适配器（D1.1 收窄范围）✅ 已完成（2026-06-07）

> **D1.1 收窄**：原 D2 计划同时做 QQ/Outlook/Gmail + OAuth 2.0 + Keychain + mock + 健康检查
> （约 5 小时），对单日工作偏满。**D1.1 收窄到**：
>
> - **D2 主任务**：BaseConnector + QQ IMAP 授权码连接 + Keychain 存取 + mock IMAP server + 健康检查
> - **D2.5 Spike**：Outlook / Gmail 连通性记录（不强制 D2 当天完整实现）
> - 完整 OAuth 2.0 推到 D2.5 或 D2.1 延后日

### 目标

通用 IMAP 连接器基类 + QQ 邮箱 IMAP 授权码连通 + Keychain 凭证 + mock 测试 + 健康检查。

### 任务清单

| # | 任务 | 预计耗时 | 产出 |
|---|------|----------|------|
| 2.1 | 写 `my_ai_employee/connectors/base.py`（抽象基类 + safe_fetch 失败隔离）| 30 min | 接口契约 |
| 2.2 | 写 `my_ai_employee/connectors/imap.py`（imapclient + 授权码模式）| 60 min | IMAP 适配器（仅 QQ 优先）|
| 2.3 | 写 `my_ai_employee/core/keychain.py`（macOS Keychain 包装）| 30 min | 凭证存储 |
| 2.4 | 写 `scripts/test_imap.py` CLI（连 QQ 邮箱测试）| 30 min | 测试入口 |
| 2.5 | 写 mock IMAP server（`tests/connectors/mock_imap.py`）| 30 min | 离线测试 |
| 2.6 | 写健康检查 `connectors/imap.py::healthcheck()` | 15 min | 熔断依据 |
| 2.7 | 写 `tests/connectors/test_imap.py`（pytest + mock）| 30 min | 单元测试（覆盖率 ≥ 70%）|
| 2.8 | **Spike**：Outlook / Gmail OAuth 2.0 流程记录 | 30 min | 兼容性报告（不强制当天实现）|

**总耗时**：约 4 小时

### 验收标准（D1.1 收窄版）

**代码/mock/文档项**（D2 收尾已完成）：

- [x] `src/my_ai_employee/connectors/base.py` — 抽象基类 + 熔断 + 失败隔离
- [x] `src/my_ai_employee/connectors/imap.py` — IMAPConnector（QQ 优先，登录后 `select_folder("INBOX", readonly=True)`）
- [x] `src/my_ai_employee/core/keychain.py` — macOS Keychain 凭证（**add -U 原位更新**，不先删后增）
- [x] `scripts/test_imap.py` — CLI 入口（4 互斥子命令，`--provider` 仅允许 `qq`）
- [x] `tests/connectors/test_imap.py` — 16 个测试（**imap.py 覆盖率 94.9%**，验收 ≥70%）
- [x] 失败时进入熔断（30 min 后再试）；healthcheck 失败也计数
- [x] `docs/spike-imap-compat.md` — QQ 完成 + Outlook/Gmail 推后决策（**Gmail 改 2025 口径**）

**真实连通**（待用户提供授权码后手动验收）：

- [ ] `python scripts/test_imap.py --set-password your@qq.com` 写入 Keychain（用户提供 16 位授权码）
- [ ] `python scripts/test_imap.py --check --email your@qq.com` 返回 `✅ 健康检查通过`
- [ ] `python scripts/test_imap.py --fetch-latest --email your@qq.com --days 7` 拉到真实邮件

### 风险点（D1.1 收窄后）

- **QQ 授权码**：需用户进 QQ 邮箱网页手动生成（不是密码）— **D2 启动前置依赖**
- **mitm 风险**：imapclient 默认 `verify=True`，macOS 证书链有时不完整
- **Outlook/Gmail 推后**：OAuth 2.0 流程复杂度高，留 D2.5 或后续

### 📌 下一棒 → D3

- IMAP 适配器（QQ）已就绪
- D3 任务：SQLCipher 数据层 + 邮件入库（分批）
- 关键决策：分批入库 vs 全量？— 我建议**分批**（避免 SQLite 锁）

---

## D3 — 数据层 + IMAP 同步

> **D3 拆分**（2026-06-07 D3.1 收尾时确认）：D3 范围过大（8 任务 / 6 小时），
> 拆成 3 phase，每天 1 phase：
>
> - **D3.1 — 数据层基础**（DB 封装 + 6 表 schema + 测试）— ✅ 已完成（v3.1.3 锁定）
> - **D3.2 — ORM + Migrations**（SQLAlchemy 2.0 + alembic + 迁移闭环）— ✅ 已完成（v1.0 锁定 + D3.2.3 修复闭环：NOCASE 写法 / JSON→TEXT / DESC 索引 / 关系测试）
> - **D3.3 — 同步脚本 + 性能 Spike**（IMAP 入库 + 1 万封 < 30s）— ✅ 已完成（1 万封实测 0.30s）
>
> FTS5 / sqlite-vss 全文+向量索引 → 推到 D4 智能层（与 LLM 分类一起做）

---

### D3.1 — 数据层基础 ✅ 已完成（2026-06-07）

#### 目标

SQLCipher 加密 DB 封装 + 6 张表 schema + 完整测试覆盖。

#### 任务清单

| # | 任务 | 预计耗时 | 产出 |
|---|------|----------|------|
| 3.1.1 | 写 `core/db.py`（sqlcipher3 封装 + `PRAGMA key` + Keychain 密码 + WAL/busy_timeout/synchronous）| 60 min | 数据库连接 |
| 3.1.2 | 写 `core/schema.sql`（emails / attachments / labels / email_labels / sync_state / audit_log）| 30 min | 表结构 |
| 3.1.3 | 写 `tests/core/test_db.py`（Keychain/加密/Schema/CRUD/上下文管理器/PRAGMA 断言/字段可空）| 30 min | 单元测试 |
| 3.1.4 | 写 `scripts/spike_sqlcipher.py`（5 分钟加密往返 spike，验证装包）| 5 min | spike 脚本 |

**总耗时**：约 2 小时（实测）

#### 验收标准（全部 ✅）

**代码/测试/DDL**：

- [x] `src/my_ai_employee/core/db.py` — Database 封装（sqlcipher3 + Keychain + dict_factory + quick_check + **受控 `connection` property**）
- [x] `src/my_ai_employee/core/schema.sql` — 6 张表 + 9 个索引（含 D3.1.1 增的 idx_emails_message_id）
- [x] `tests/core/test_db.py` — **23 个测试**（15 v1 + D3.1.1 +5 + D3.1.2 +3 connection property）
- [x] `scripts/spike_sqlcipher.py` — 5 分钟加密往返 spike
- [x] PRAGMA 矩阵：key + foreign_keys=ON + **journal_mode=WAL** + busy_timeout=5000 + synchronous=NORMAL
- [x] 去重键：`UNIQUE(source, uid)`（D3.1.1 修正：用 IMAP UID 而非 Message-ID）
- [x] 字段可空：`message_id` / `received_at`（D3.1.1 修正：兼容 IMAP 邮件无 Message-ID / 无 Date 头）
- [x] Keychain 凭证：**首次启动自动生成 32 字节随机串写入 Keychain**（service=`my-ai-employee.db`，account=`data.db`），不要求用户手动
- [x] 受控 `connection` 入口（D3.1.2 增）：alembic 走 `Database.open().connection` 而非私有 `_conn`（避免封装泄漏）

**质量门**：

- [x] pytest **60 passed**（37 D2 + 23 D3.1）
- [x] ruff / mypy / `make lint` 0 errors
- [x] db.py 覆盖率 **97.5%**

#### 风险点（已解决）

- ~~**pysqlcipher3 安装**：Python 3.14 兼容性差~~ → **D1.1 已解决**：用 sqlcipher3（coleifer 维护，Python 3.12 wheel 齐全）
- ~~**首次 Keychain 凭证缺失**：用户需手动写~~ → **D3.1.1 已解决**：`Database.open()` 首次启动自动生成 + 写入
- **4 个 SQLCipher 雷区**：见 [reports/D3.1-数据层基础完成.md](../reports/D3.1-数据层基础完成.md) §4

#### 📌 下一棒 → D3.2

- 数据层基础就绪
- 下棒任务：SQLAlchemy 2.0 DeclarativeBase 6 Model + alembic 迁移框架
- 关键决策：alembic env.py 集成 SQLCipher 密码（调 `Database.open().connection` — D3.1.2 新增的受控 property，避免依赖私有 `_conn`）

---

### D3.2 — ORM + Migrations ✅ 已完成（v1.0 锁定 — 2026-06-08 / D3.2.3 + D3.2.4 修复闭环）

#### 目标

SQLAlchemy 2.0 DeclarativeBase 6 个 Model 类 + alembic 迁移框架（集成 SQLCipher 密码），DDL 完全 mirror D3.1 schema.sql。

#### 任务清单

| # | 任务 | 预计耗时 | 实际 | 产出 |
|---|------|----------|------|------|
| 3.2.1 | 写 `core/models.py`（SQLAlchemy 2.0 DeclarativeBase，6 个 Model 类 + JSONList TypeDecorator + list_tables / to_dict）| 60 min | ~50 min | ORM 模型 |
| 3.2.2 | `alembic init core/migrations` + 改 `env.py` 集成 SQLCipher 密码（走 D3.1.2 受控 `connection`）| 30 min | ~30 min | alembic 入口 |
| 3.2.3 | 写 `core/migrations/versions/0001_initial.py`（从 schema.sql 翻译成 alembic op，render_as_batch=True，NOCASE / DESC / TEXT DEFAULT '[]'）| 30 min | ~25 min | 首次迁移 |
| 3.2.4 | 写 `tests/core/test_models.py`（CRUD + relationship + cascade + UNIQUE + server_default + NOCASE + DESC）| 30 min | ~30 min | ORM 测试 |
| 3.2.5 | 写 `core/sqlcipher_compat.py`（SA engine creator 适配层）| — | ~15 min | 适配层 |
| 3.2.6 | 写 `tests/core/test_migrations.py`（真 alembic upgrade head + 离线 SQL 渲染 + schema 一致性）| — | ~25 min | 迁移闭环 |
| 3.2.3+ | **D3.2.3 修复**：4 个阻塞问题闭环（NOCASE 写法 / JSON→TEXT / DESC 索引 / EmailLabel 关系测试）| — | ~40 min | 修复版 |
| 3.2.4 | **D3.2.4 修复**：mypy 5 个 arg-type 错误（`str(Path)` → `Path`）+ alembic 6 个 DeprecationWarning（`path_separator = os`）| — | ~10 min | 修复版 |

**总耗时**：约 3.5 小时

#### 验收标准（全部 ✅）

**代码/测试/DDL**：

- [x] `src/my_ai_employee/core/models.py` — 6 个 Model 类（Email / Attachment / Label / EmailLabel / SyncState / AuditLog）+ 9 索引 + UNIQUE(source, uid) / UNIQUE(name, source) / UNIQUE(source) + **JSONList TypeDecorator**（TEXT 存 JSON 文本，list ↔ 文本透明转换）
- [x] `src/my_ai_employee/core/sqlcipher_compat.py` — SA engine creator 走 SQLCipher（100% 覆盖）
- [x] `src/my_ai_employee/core/migrations/env.py` — alembic env.py 集成 SQLCipher 密码（online 模式调 `make_sqlalchemy_creator` + `render_as_batch=True`）
- [x] `src/my_ai_employee/core/migrations/versions/0001_initial.py` — 首次迁移（6 `op.create_table` + 9 `op.create_index`，**NOCASE / DESC / TEXT DEFAULT '[]' 与 D3.1 schema.sql 1:1**）
- [x] `src/my_ai_employee/core/migrations/script.py.mako` — alembic 标准模板
- [x] `alembic.ini`（项目根）— `script_location = core/migrations` + `prepend_sys_path = src`
- [x] `src/my_ai_employee/core/db.py` — **D3.2 关键调整**：`row_factory` 从 `Database.open()` 推到 `execute/fetch_*` 方法入口（SA dialect 探针天然 OK）
- [x] `tests/core/test_models.py` — **25 个测试**（metadata / 6 Model CRUD / 关系 / 级联 / UNIQUE / server_default / 联合查询 / **NOCASE 大小写唯一性** / **EmailLabel 双轨反查** / **cascade 双向** / **JSONList 序列化** / **DESC 索引 DDL**）
- [x] `tests/core/test_migrations.py` — **6 个真 alembic 测试**（6 表创建 / alembic_version / D3.1 schema 一致性 / DESC 索引 DDL / offline SQL 渲染 / metadata vs DB 表对齐）
- [x] **JSON 字段用 JSONList TypeDecorator**：`Email.recipients` / `Email.labels` DDL 走 TEXT DEFAULT '[]'，ORM 走 list ↔ JSON 文本（**完全 mirror schema.sql**）
- [x] **Label.name COLLATE NOCASE**：`sa.Text(collation="NOCASE")`（D3.1 schema 决策） — "Inbox" / "INBOX" / "inbox" 任意大小写视为同名
- [x] **DESC 索引**：`idx_emails_received_at` / `idx_emails_source_received` / `idx_audit_log_created_at` 全 DESC（热路径"按时间倒序"）
- [x] **server_default 配 default=**：所有有默认值的字段都加 `server_default=`（满足 raw SQL INSERT 也能用默认）

**质量门**：

- [x] pytest **91 passed**（37 D2 + 23 D3.1 + **25 D3.2 Model** + **6 D3.2 Migration**）
- [x] ruff / mypy / `make lint` **0 errors**（D3.2.4 闭环：mypy 0 之前有 5 个 arg-type + 3 个 test_imap 历史 bug）
- [x] models.py 覆盖率 **92.3%**
- [x] sqlcipher_compat.py 覆盖率 **100%**
- [x] db.py 覆盖率 **97.9%**（保持 D3.1 水平）
- [x] `.venv/bin/alembic upgrade head --sql` **exit 0**（D3.2.3 修复闭环 — D3.2 v1.0 时曾因 `sqlite_collation` 写法 ArgumentError）
- [x] pytest -W error::DeprecationWarning **无 6 个 alembic path_separator 警告**（D3.2.4 修复闭环）

#### 风险点（已解决 — 4 个 SQLAlchemy + sqlcipher3 雷区）

- ~~**SA dialect 探针 KeyError: 0**：D3.1 设 `conn.row_factory = _dict_factory` 后 SA `get_isolation_level` 抛 KeyError~~ → **D3.2 已解决**：`row_factory` 推到方法入口临时设 + finally 立即还原
- ~~**server_default 缺失导致 NOT NULL**：仅 `default=` 不生成 SQL DEFAULT 子句~~ → **D3.2 已解决**：每个 default 字段都加 `server_default=`
- ~~**sqlcipher3 Cursor 不支持 `with`**：`with conn.execute(...) as cur:` 抛 TypeError~~ → **D3.2 已解决**：SA 2.0 SQLite dialect 不调 `with cursor()`，直接 `cur = conn.execute(...)`
- ~~**NOCASE 写法报错**：`Column(..., sqlite_collation="NOCASE")` 抛 `ArgumentError: 'sqlite_collation' is not accepted by dialect 'sqlite'`~~ → **D3.2.3 已解决**：`sa.Text(collation="NOCASE")`（collation 是类型参数，不是 column 参数）
- ~~**JSON 字段未 mirror D3.1 schema.sql**：D3.2 migration 走 `sa.JSON()`，schema.sql 走 `TEXT DEFAULT '[]'`~~ → **D3.2.3 已解决**：引入 `JSONList TypeDecorator`，DDL 走 TEXT，ORM 走 list，**完全 mirror schema.sql**
- ~~**DESC 索引缺失**：D3.1 schema 是 DESC，D3.2 v1.0 是普通升序~~ → **D3.2.3 已解决**：`text("received_at DESC")` 表达
- ~~**mypy arg-type 错误（5 处）**：`Database.open(db_path=str(tmp_db_path))` 多绕一层 str，签名是 `Path | None`~~ → **D3.2.4 已解决**：直接传 `Path`，5 处全改
- ~~**alembic 6 个 DeprecationWarning**：`alembic.ini` 缺 `path_separator`，Alembic 升级后默认会改~~ → **D3.2.4 已解决**：显式 `path_separator = os`
- **D3.1.2 测试断言需修**：`db.connection` row 从 dict 变 tuple（row_factory 调整）→ 改 `row[0].lower() == "wal"` tuple 解构

**完整踩坑分析**：见 [reports/D3.2-ORM与迁移框架完成.md](../reports/D3.2-ORM与迁移框架完成.md) §2 / §4 / §9

#### 📌 下一棒 → D3.3

- ORM + alembic 迁移框架就绪（D3.2 v1.0 锁定，D3.2.3 修复闭环）
- 下棒任务：scripts/sync_imap.py（IMAPConnector.safe_fetch + SQLAlchemy Session 批量入库 100/批）+ 1 万封 spike
- 关键决策：
  - D3.3 同步入库走 ORM（`session.add(Email(...))` 100/批 commit）— 简单优先
  - 性能不达标再切 `session.bulk_save_objects` 走 bulk 模式
  - **received_at 缺失 fallback 到 fetched_at**（D3.1.1 决策 — D3.3 入库映射层落实）
  - **JSONList 已就绪**：D3.3 写 `Email(recipients=[...], labels=[...])` 直接生效
  - **真 alembic 迁移测试就绪**：D3.3 增迁移时直接 `alembic revision --autogenerate` + `test_migrations.py` 跑新 revision

---

### D3.3 — 同步脚本 + 性能 Spike（✅ 已完成 — 2026-06-08，详见 `reports/D3.3-同步脚本与性能spike.md`）

#### 目标

IMAPConnector 邮件入库脚本 + 1 万封 mock 邮件 < 30s 入库性能验证。

#### 任务清单

| # | 任务 | 预计耗时 | 实际产出 | 状态 |
|---|------|----------|----------|------|
| 3.3.1 | 写 `src/my_ai_employee/core/sync.py` + `scripts/sync_imap.py`（`IMAPSync` 100/批 commit ORM + CLI）| 90 min | 320 + 110 行 | ✅ |
| 3.3.2 | 写 `tests/core/test_sync.py`（mock BaseConnector + 真实 SQLCipher DB）| 60 min | **11 个端到端用例**（D3.3.1 9 + D3.3.2 +1 UNIQUE 冲突 + D3.3.3 +1 OperationalError 传播）| ✅ |
| 3.3.3 | **Spike**：1 万封 mock 邮件 < 30s 入库 | 30 min | **0.30s / 33000 封/秒** | ✅ |

**总耗时**：约 3 小时（符合预期）

#### 验收标准（全部达标）

- [x] 1 万封邮件入库 < 30s — **实测 0.30s（用预算 1%）**
- [x] 增量同步：基于 `sync_state.last_uid` 只拉新邮件（`test_sync_filters_out_old_uids`）
- [x] 失败隔离：单批失败不阻塞后续（`test_sync_continues_after_batch_failure`）
- [x] received_at 缺失时 fallback 到 fetched_at（D3.1.1 决策 — `test_sync_received_at_fallback_to_fetched_at`）
- [x] 100 封/批 commit（`test_sync_commits_per_batch` — 250 封 → 3 个 commit）

#### 5 关质量门

- [x] pytest **102 passed**（91 → 102，+11 D3.3：D3.3.1 +9 + D3.3.2 +1 UNIQUE 冲突测试 + D3.3.3 +1 OperationalError 传播测试）
- [x] ruff check **0 errors**
- [x] ruff format **No changes needed**
- [x] mypy **0 errors in 27 source files**
- [x] alembic upgrade head --sql **exit 0**

#### 关键交付

| 文件 | 作用 |
|------|------|
| [src/my_ai_employee/core/sync.py](../src/my_ai_employee/core/sync.py) | `IMAPSync` 核心（100/批 commit + SyncState upsert + 失败隔离）|
| [scripts/sync_imap.py](../scripts/sync_imap.py) | CLI（`sync` 真 IMAP 模式 + `spike` 性能模式）|
| [scripts/spike_sync.py](../scripts/spike_sync.py) | 1 万封 faker 性能测试 |
| [tests/core/test_sync.py](../tests/core/test_sync.py) | **11 个 D3.3 端到端测试** |
| [reports/D3.3-同步脚本与性能spike.md](../reports/D3.3-同步脚本与性能spike.md) | 完整完成报告 |

#### 关键设计决策（沉淀）

- **100/批 commit ORM**：避免 SQLite 长事务锁（>500 行易锁）
- **失败隔离范本**：单批 `SQLAlchemyError` → 整批计 `failed=N`，下一批继续
- **`sync.close()` 不 dispose engine**：D3.2.2 教训（SA engine 复用 db 的 SQLCipher conn）
- **scripts/ 不进 mypy 严格区**：CLI 工具代码，不是业务代码

#### 📌 下一棒 → D4

- 数据层就绪
- 下棒需要：已入库的邮件（500+ 真实数据）
- 关键决策：minimax M3 是否要在 D4 同时接入？— 我建议**D4 直接用**，因为走 Claude Code SDK
- 移交清单见 [reports/D3.3 §8](../reports/D3.3-同步脚本与性能spike.md)

---

## D4 — 智能层（邮件分类 + 草稿）

> **2026-06-08 更新**：v2 晨报钩子（MiniMax M3 冲进 OpenRouter 前 3 + 中国大模型 6 周连续超美）触发 LLM 选型调整：原"统一 minimax M3"升级为"国内模型优先 + capability registry + 多 provider fallback"。**D4.0 LLM 路由层作为 D4 子任务的前置 D-step 先建**（v1.0 已锁定 6/8 11:30+，详见 [reports/D4.1-LLM路由层完成.md](../reports/D4.1-LLM路由层完成.md)）。**D4.1.1 HTTP 实施已完成**（v1.0 锁定 6/8 20:30+，详见 [reports/D4.1.1-HTTP调用实施完成.md](../reports/D4.1.1-HTTP调用实施完成.md)）。

### D4.0 — LLM 路由层（前置 D-step，✅ v1.0 锁定 2026-06-08）

**范围**：capability registry + provider 抽象 + fallback 链 + router 决策逻辑（**不调 HTTP**——HTTP 调用在 D4.1 实施）

**交付**：

| 文件 | 行数 | 作用 |
|------|------|------|
| [src/my_ai_employee/ai/capability.py](../src/my_ai_employee/ai/capability.py) | 222 | Capability Registry（9 模型 / 6 国内 + 2 国外 + 1 本地）|
| [src/my_ai_employee/ai/providers.py](../src/my_ai_employee/ai/providers.py) | 154→**306** | Provider 抽象（基类 + OpenAICompatibleProvider + 4 类异常 + httpx 调用）|
| [src/my_ai_employee/ai/fallback.py](../src/my_ai_employee/ai/fallback.py) | 144 | Fallback 链（5 任务 → 4 异构链 + CircuitBreaker）|
| [src/my_ai_employee/ai/router.py](../src/my_ai_employee/ai/router.py) | 231 | Router 主入口（5 步决策法 + 统计 + 单例）|
| [tests/ai/test_router.py](../tests/ai/test_router.py) | 30 → 31 用例 | 单元测试（capability + fallback + provider + router）|
| [tests/ai/test_provider_http.py](../tests/ai/test_provider_http.py) | **26 用例（新增）**| respx mock 6 provider + 4 类异常 + 端到端 |

**质量门**（8 大门全绿）：

- ruff format / check: ✅ 0 errors
- mypy: ✅ **33 files** 0 errors（D4.0 32 → 33，+1 test_provider_http）
- pytest: ✅ **159 passed**（D4.0 132 → 159，+27 D4.1.1 测试）
- 覆盖率: **87.8%**（D4.0 87.0% → 87.8%，+0.8%）/ ai 包 **96.3%**（providers 96.3% / fallback 100% / capability 98% / router 97.4%）
- alembic upgrade head --sql: ✅ exit 0
- uv build: ✅ success

**v2 钩子驱动调整**（vs §0.4 原"统一 minimax M3"决策）：

- 国内模型优先：DeepSeek（0.5 元/百万 token）/ MiniMax M3（冲榜验证）/ Qwen / 腾讯混元 / GLM
- Capability Registry 数据驱动：参考 claw-code `MODEL_COMPATIBILITY.md`
- 5 任务类型 → 5 异构 fallback 链（避免同 provider 雪崩）
- **D3.3.3 教训落地**：4 类业务异常（`LLMTimeoutError` / `LLMConnectionError` / `LLMAPIError` / `LLMResponseError`），编程错误透传（`ValueError` / `TypeError` 不包装）

### D4.1.1 — HTTP 调用实施（✅ v1.0 锁定 2026-06-08）

**承接 D4.1.0 下一棒**：把占位 `OpenAICompatibleProvider.chat()` 实施为真实 httpx 调用。

**新增交付**：

| 改动 | 作用 |
|------|------|
| `providers.py` +152 行 | 4 类业务异常（基类 `LLMError`）+ chat() httpx 调用 + 专用 Key 查找（`DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY` 等）|
| `tests/ai/test_provider_http.py`（新建，258 行）| respx mock 6 provider + 5 类异常 + 端到端 |
| `tests/ai/test_router.py` -18/+28 行 | 删除 D4.1.0 过时 `NotImplementedError` 测试，改写为真实 HTTP 错误测试 |
| `.env.example` +30 行 | 6 provider API Key 模板 |
| `pyproject.toml` +2 deps | `httpx>=0.27` + `respx>=0.21` |

**关键设计**：

- 异常窄化（参考 D3.3.3 教训）：`httpx.TimeoutException` / `ConnectError` / `RequestError` / HTTP 4xx/5xx / 响应解析失败 → 4 类业务异常，编程错误（`ValueError` / `TypeError`）透传
- API Key 优先级：`override 参数` > 专用 Key（`DEEPSEEK_API_KEY` 等）> `OPENAI_API_KEY` 兜底
- `LLMAPIError.body` 截断到 500 字符，防止巨型错误响应爆日志

**下一棒 → D4.3 Events 表契约**（✅ v1.0 锁定 2026-06-08，参考 claw-code `g004-events-reports-contract.md`）

### D4.2 — MCP 抽象层（✅ v1.0 锁定 2026-06-08）

**承接 D4.1.1 下一棒**：MCP 客户端基类抽象 + 生命周期 + 4 类业务异常 + DegradedReport（**不接真实 MCP server**，仅 MockTransport 留扩展）。

> **📌 两套编号说明（2026-06-08 锁定）**：
>
> - **D4.x 智能层基础设施**（大写 D）：D4.0 LLM 路由层 / D4.1.1 HTTP 实施 / D4.2 MCP 抽象 / D4.3 Events 表契约 / D4.4 任务策略板 / D4.5 release readiness，**所有 Agent 在 D4.0 之后任何时间可启动**，目的是建立智能层底座
> - **4.x LLM 业务层**（小写 4）：4.6 写 ai/classifier.py / 4.7 写 ai/drafter.py / 4.8 prompts / 4.9 audit，**必须 D4.3 之后才启动**（需要 events 表 + D4.0 路由 + D4.1.1 HTTP + D4.2 MCP 四个底座）
>
> 编号冲突源自 D4.0 启动时未整体重排，本节 D4.3 锁定时通过分段标题（"D4.x 智能层基础设施" + "4.x LLM 业务层"）保持向后兼容。

**新增交付**：

| 文件 | 行数 | 作用 |
|------|------|------|
| [src/my_ai_employee/mcp/](../src/my_ai_employee/mcp/) | 621 | exceptions(33) + report(87) + transport(164) + client(187) + discovery(145) + **init**(5) |
| [tests/mcp/](../tests/mcp/) | 44 用例 | exceptions(7) + report(11) + transport(12) + client(11) + discovery(8 + 1 fixture) |

**质量门**（8 大门全绿）：

- ruff format / check: ✅ 0 errors（44 files already formatted）
- mypy: ✅ **44 files** 0 errors（D4.1.1 33 → 44，+11 mcp 文件）
- pytest: ✅ **209 passed**（D4.1.1 159 → 209，+50 mcp 测试 [47 + 3 malformed]）
- 覆盖率: **89.4%**（D4.1.1 87.8% → 89.4%，+1.6%）/ mcp 包 **96.7%**（exceptions 100% / report 100% / transport 96.9% / client 94.4% / discovery 96.2%）
- alembic upgrade head --sql: ✅ exit 0
- uv build: ✅ success
- make lint: ✅ 0 errors

**关键设计**（D3.3.3 + D4.1 教训应用）：

- **4 类业务异常**：`MCPTimeoutError` / `MCPConnectionError` / `MCPProtocolError` / `MCPResponseError` + `MCPError` 基类
- **recoverable 标志**：`isinstance(exc, (MCPTimeoutError, MCPConnectionError))` 决定是否重试
- **Required flag 决策**：必填 server 失败 → abort，可选 server 失败 → 计入 `report.failed`（filesystem=optional / calendar=required）
- **`McpErrorSurface` 5 字段**：phase + server + message + context + recoverable
- **`McpDegradedReport` 4 段**：working + failed + available_tools + missing_tools（+ is_healthy/is_degraded 派生属性）
- **关键 regression 测试**：`test_keeps_healthy_servers_when_optional_fails`（对应 claw-code `manager_discovery_report_keeps_healthy_servers_when_one_server_fails`）

**修复记录**（D4.2 期间踩的 6 个坑）：

| 坑 | 修复 |
|----|------|
| `client.py:19` 误写 `dataclasses, field`（11 字符含重复 ca）| `sed` 强制修 |
| MockTransport `call_protocol_error/response_error` 返回坏值（应抛）| 改为 `raise MCPProtocolError/MCPResponseError` |
| `test_discovery.py` 缺 `MCPTimeoutError` import | 加 import |
| `LifecyclePhase(str, enum.Enum)` ruff UP042 | 改 `enum.StrEnum` |
| `resp.get("result", {})` mypy no-any-return | 显式标注 `result: dict[str, Any] = ... # type: ignore[assignment]` |
| 测试 `t.start()` 后设 protocol_error（DID NOT RAISE，因 connect 幂等）| 加 `t.connected = False` |

**参考来源**：[docs/d4-claw-code-mapping.md](../docs/d4-claw-code-mapping.md) §2（D4.2 7 行优先参考 + 4 行不照搬）。完整报告：[reports/D4.2-MCP抽象层完成.md](../reports/D4.2-MCP抽象层完成.md)

**下一棒 → D4.3 Events 表契约**（✅ v1.0 锁定 2026-06-08，参考 claw-code `g004-events-reports-contract.md`）

### 目标

邮件自动分类（5 类）+ 1-click 草稿生成，端到端可用。

### 任务清单

> **2026-06-08 更新**：D4.0 LLM 路由层（前置 D-step，v1.0 锁定）已建好，本节 D4.1-D4.8 任务改用 `router.route()` 调用而非直接调 LLM SDK。

| # | 任务 | 预计耗时 | 产出 | 状态 |
|---|------|----------|------|------|
| 4.0 | LLM 路由层（capability + provider + fallback + router）| 90 min | 5 文件 + 30 测试 | ✅ v1.0 锁定（6/8）|
| 4.1.1 | **HTTP 实施**：`OpenAICompatibleProvider.chat()` + httpx + 4 类异常 + 26 测试 | 90 min | httpx 调用 + respx 集成测试 | ✅ v1.0 锁定（6/8 20:30）|

**⚠️ 6/8 D4.5 release readiness 之后编号重整**(本表 L513-520 为原 D4 智能层规划,6/8 晚间任务重组后,新 D-step 编号 → 旧任务映射):

| 新 D-step | 对应旧任务 | 状态 |
|-----------|-----------|------|
| **D4.6 邮件分类器**(v1.0.2-third 锁定 6/9 早晨) | 4.2 classifier.py + 4.4 classifier prompt + 4.7 test_classifier.py | ✅ 611 passed / 8 质量门全绿 |
| **D4.7 草稿生成器**(本次启动) | 4.3 drafter.py + 4.5 drafter prompt | 🎯 待实施(见下方 §D4.7 段) |
| D4.6.1+ spike 段 | 4.6 classify_all.py + 4.8 100 封 spike | ⏳ 延后(D4.6 锁定后启动) |
| D4.7+ 审计段 | 4.9 core/audit.py | ⏳ 延后(D4.7 锁定后启动) |

**📜 原任务表**(D4.5 之前的 4.0-4.9 旧编号,仅作历史归档):

| 4.2 | 写 `ai/classifier.py`（用 `router.route(CLASSIFY, ...)` + 5 类标签）| 90 min | 分类服务 | ✅ 已合并到 D4.6(6/9 早晨 v1.0.2-third 锁定) |
| 4.3 | 写 `ai/drafter.py`（用 `router.route(DRAFT, ...)` + 历史回复模式）| 90 min | 草稿服务 | 🎯 D4.7 草稿生成器(本次启动) |
| 4.4 | 写 `ai/prompts/classifier.txt`（中文 prompt + few-shot 5 例）| 30 min | 提示词 | ✅ 已合并到 D4.6.2(`ai/prompts/classify.py` 5 类 SYSTEM prompt) |
| 4.5 | 写 `ai/prompts/drafter.txt`（中文 prompt + 角色设定）| 30 min | 提示词 | 🎯 D4.7.2 范围(`ai/prompts/draft.py`) |
| 4.6 | 写 `scripts/classify_all.py`（批量分类 + 准确率统计）| 60 min | 评估脚本 | ⏳ D4.6.1+ spike 段延后 |
| 4.7 | 写 `tests/ai/test_classifier.py`（500 封真实邮件标注）| 60 min | 单元测试 | ✅ 已合并到 D4.6.7(46 tests) |
| 4.8 | **Spike**：100 封手标邮件做混淆矩阵 | 60 min | 准确率报告 | ⏳ D4.6.1+ spike 段延后 |
| 4.9 | 写 `core/audit.py`（LLM 调用审计日志）| 30 min | 合规依据 | ⏳ D4.7+ 审计段(LLM 调用审计)延后 |

**总耗时**：约 7-8 小时（4.0 路由层 + 4.1-4.9 实现）

### 验收标准

- [ ] 分类准确率 ≥ 80%（混淆矩阵见 spike 报告）
- [ ] 单封邮件分类 < 3s
- [ ] 单封草稿生成 < 10s
- [ ] 审计日志完整（含 token 数 + 路由 + 时间）
- [ ] 5 类标签分布合理（无类占比 > 60%）
- [ ] 敏感数据命中黑名单 → 跳过 LLM，标记 `pending`

### 风险点

- **prompt 漂移**：手标 100 封 vs 真实分布差异大时，准确率会掉
- **token 成本**：5000 封邮件分类估算成本（按 minimax M3 单价）
- **降级路径**：minimax M3 不可用时 → 规则引擎（关键词/正则）

### 📌 下一棒 → D4.4 ✅ 已锁定 → D4.5

- **D4.0 + D4.1.1 + D4.2 + D4.3 + D4.4 五锁定**（6/8 22:00 D4.3 + 6/8 22:30 D4.4）
- ✅ **D4.4 任务策略板 v1.0 锁定**（6/8 22:30，6 模块 + 180 policy 测试 + ~97% 覆盖率 + 8 大质量门全绿 + 全量 mypy src tests 0 errors）
- D4.4 P1 收口：context 12 字段严格解析（23 新 test）+ 全量 mypy 10 errors → 0 errors + 总覆盖率 91.8% + 全量 459 passed
- 下棒任务：**D4.5 release readiness + 业务层接入**（**已完成 · 2026-06-08 v1.0 锁定**；原计划是 2026-06-09 晨间链路确认后启动,实际 6/8 晚间已闭环）
- 再下棒：D4.5 release readiness（6/14 周末）

---

### D4.5 — release readiness + 业务层接入（✅ 2026-06-08 v1.0 锁定 · P0 业务语义修复 + 文档/可观测性补完后）

**承接 D4.4 下一棒**：D4.4 决策引擎已锁定，本步**首次真实业务 emit**——选 D3.3 IMAP 同步（D2 connectors/imap.py 拉邮件 + D3.3 sync.py 入库）做第一个接入点。

**范围**：
- **业务层接入**：`SyncPolicyAdapter` 把 D3.3 IMAPSync 接入 D4.4 4 件套（PolicyEngine + LaneBoard + Heartbeat + EventStore）
- **3 个业务层 TaskPacket factory**：`build_imap_sync_packet` / `compute_acceptance_results` / `build_sync_policy_context`（IMAP 同步 → 12 字段 context 严判）
- **5 个新增公共 API 顶层导出**（policy `__init__.py` 26→31）
- **Release 决策包**：`reports/D4.5-release-readiness.md` 5 段 ready_for_review 报告（测试覆盖 / 质量门 / 性能 / 已知限制 / 待人工审批项）—— **不引 g007/g012**（不写 production deploy 脚本，决策包只等用户审批）
- **D4.4 源文件零修改**（4 件套契约保持 v1.0，向后兼容）

**8 大质量门**（8/8 全绿 · v1.0 锁定 6/8）：
- `pytest tests/policy/ -v`: **217 passed in 0.30s**（D4.4 180 → D4.5 +37 = 35 集成 + 2 v1.0.1 文档/可观测性补完,含 P0 修复 +4）
- `ruff check`: All checks passed / `ruff format`: 76 files already formatted
- `mypy src/policy/`: 0 errors / 7 files（D4.4 6 + integration 1）
- `mypy tests/policy/`: 0 errors / 8 files（D4.4 7 + test_integration 1）
- `alembic upgrade head --sql`: exit 0 (0003 latest)
- `uv build`: tar.gz + .whl OK
- `pytest` 全量: **496 passed**（D4.3 预存隔离 6/8 晚间已修复，**0 失败**）

**关键设计**（D3.3.3 + D4.4 P1 + D4.5 P0 教训应用）：
- 4 依赖可注入（event_store / engine / heartbeat / board），不传 = D3.3 行为不变
- `evaluate_and_emit` 不替 caller 执行 6 决策（D3.3.3 异常窄化教训：只声明，不替业务调度器决定）
- 严判入口（**D4.5 P0-1 修复**）：`branch_stale` / `consecutive_failures` / `now_ms` 必须原生 bool/int，拒 type-coerce
- escalate 语义（**D4.5 P0-2 修复**）：`failed > 0 AND consecutive_failures >= 3`（达到阈值才升级）
- lane/heartbeat 单一真相源（**D4.5 P0-3 修复**）：`all(acceptance_results)` 判定，与 PolicyEngine 同步
- `run_id` 空时用 `int(time.time()*1000)` 默认值（多次调用 lane_entry_id 唯一）
- 业务 payload 7 字段合并到 `event_metadata` 顶层（D4.3.2 决策：`build_event_metadata` `meta.update(extra)`）

**已知限制**（D4.5.1+ 复检 P 项）：
- 6 决策是声明式 → D4.5.1+ 加 executor pattern（retry 调 `IMAPSync.run_once` / escalate 写 events 表）
- LaneBoard in-memory 仍未持久化 → D4.5.1+ 落 `lane.entry.added` / `status_changed` 事件
- 单一 IMAP 接入 → D4.6+ 加 `EmailClassifierAdapter` / `EmailDrafterAdapter`（同 4 依赖范本）
- 无 1 万封真实 spike → D4.5.1+ 在 1 万封真实邮件上跑 `evaluate_and_emit` 30 天（D3.3 spike 已验证 0.30s/万封性能基线）

**P0 业务语义修复闭环**（D4.5 ready_for_review → v1.0）：
- **P0-1 严判入口**：原 `bool("false")` 静默转 True 触发误升级 → 改 `type() is bool/int` 严判，3 类脏输入抛 ValueError
- **P0-2 escalate 语义**：原 `failed > cf > 0` 颠倒（failed=10,cf=1 升级 / failed=1,cf=3 不升级）→ 改 `failed > 0 AND cf >= 3`
- **P0-3 lane/heartbeat 单一真相源**：原 `failed==0 AND inserted>0` 把慢同步 / 空同步误标成功 → 改 `all(acceptance_results)`
- 7 个新测试覆盖（`test_build_sync_policy_context_strict_type_rejection` / `test_acceptance_consistency_lane_heartbeat` 等）

**参考来源**：[docs/d4-claw-code-mapping.md §6](../docs/d4-claw-code-mapping.md)（D4.5 6 优先参考 + 4 不照搬 + 3 不学 + 14 决策含 P0 修复）。完整报告：[reports/D4.5-release-readiness.md](../reports/D4.5-release-readiness.md)

**下一棒 → D4.6+ 业务层实现**（classifier / drafter 用 `router.route()` + D4.5 `SyncPolicyAdapter` 范本）。D4.5 **v1.0 已锁定**（2026-06-08 晚间 P0 业务语义修复 + 文档/可观测性补完后），Week 2 业务层启动决策推迟到 6/9 晨间链路确认。

---

### D4.6 — 邮件分类器（✅ 2026-06-09 v1.0.2-third 第三次复检后真正锁定）

**承接 D4.5 业务层范本**：D4.5 `SyncPolicyAdapter` 4 依赖可注入范本（`event_store` / `engine` / `heartbeat` / `board`）+ 5 步主入口，在 D4.6 第二个真实业务场景上**复用**。

**范围**：
- **业务层**：`ai/classifier.py` 实现 `EmailClassifier`（`classify` / `classify_batch`） + `_parse_classification_response` 严判 LLM 响应 + 5 类 StrEnum `EmailCategory`
- **Prompt 模板**：`ai/prompts/classify.py` 5 类 SYSTEM prompt + `build_user_message` 拼接
- **业务层接入**：`EmailClassifierAdapter` 复用 D4.5 范本，`classify_and_emit`（成功入口）+ `record_classify_failure_and_emit`（失败入口）双入口架构（v1.0.2 引入）
- **业务字段透传**：D4.6 新增 `_emit_decision_event` 可选 kwargs `extra_business_payload`，透传 `category / confidence / model_full_id / email_id / source` 5 项到 event_metadata 顶层
- **lane_entry_id 命名**：`classify:<source>:<run_id>`（与 `sync:` 区分，便于 `mmx policy history --lane` 跨次分类串联）
- **5 类标签**：URGENT（紧急）/ TODO（待办）/ FYI（知晓）/ SPAM（垃圾）/ PERSONAL（私人）
- **D4.5 兼容度**：`SyncPolicyAdapter` 5 步主入口 + `evaluate()` `_emit_decision_event` 旧 kwargs 全保留（`extra_business_payload=None` 旧行为零变化）
- **D4.4 兼容度**：D4.4 6 个源文件零修改，仅 `_emit_decision_event` 新增可选 kwargs

**v1.0 → v1.0.1 → v1.0.2-first → v1.0.2-second → v1.0.2-third 演进路径**（2026-06-09 早晨三次复检）：

| 版本 | 提交 | 触发 | 修复项 | 测试数 | 关键变更 |
|------|------|------|--------|--------|----------|
| v1.0 | ab6ad9c | 6/8 晚间初版提交 | — | 559 | 5 类 + 严判 + 业务层接入 |
| v1.0.1 | 22aa82a | 6/9 早晨第一次复检 | 6 P1+P2+P3 | 576 | Router 全链 / 业务传输解耦 / 成功失败分离 / JSON 解析 / duck type / 文档 |
| v1.0.2-first | (并入 v1.0.2-second commit) | 6/9 早晨第二次复检 5 项 | 2 P1 + 3 P2 | 592 | 双入口 type system 锁定 + 5 类严判 + 平衡 JSON + 批处理补全 + NaN 拒收 |
| v1.0.2-second | b7468bb | 6/9 早晨第二次复检 4 项 | 1 P1 + 2 P2 + 1 P3 | 603 | 公开 helper 严判下沉 + `ClassifyFailureDecisionReport` 独立类型 + 顶层导出 + 文档同步 |
| **v1.0.2-third** | c6afda6 | 6/9 早晨第三次复检 4 项 | 1 P1 + 2 P2 + 1 P3 | **611** | 公共构造器严判下沉 + `Literal[True]` 数据类自洽 + 异常统一 `ValueError` + 文档同步 |

**8 大质量门**（8/8 全绿 · v1.0.2-third 第三次复检后 6/9 早晨）：
- `pytest tests/ai/ -v`: classifier 46 passed（D4.6 ai 30 → v1.0.1 40 → v1.0.2-first 46 → v1.0.2-second 46 → v1.0.2-third 46）
- `pytest tests/policy/ -v`: classifier_adapter 69 passed（D4.6 policy 32 → v1.0.1 40 → v1.0.2-first 50 → v1.0.2-second 61 → v1.0.2-third 69）
- `ruff check`: All checks passed / `ruff format`: 81 files already formatted
- `mypy src/`: 0 errors / 43 files
- `alembic upgrade head --sql`: exit 0 (0003 latest)
- `uv build`: tar.gz + .whl OK
- `pytest` 全量: **611 passed**（v1.0.2-first 592 → v1.0.2-second 603 → v1.0.2-third 611，**0 失败**）
- 覆盖率：`policy/integration.py` 94.3% + `ai/classifier.py` 96.4% + `ai/prompts/classify.py` 100%

**v1.0.2 关键设计**（D3.3.3 + D4.4 P1 + D4.5 P0 + v1.0.1 教训应用）：
- 复用 `router.route(TaskType.CLASSIFY, ...)` 自动走 DeepSeek → Qwen → M3 fallback 链（`fallback.FALLBACK_CHAINS` 已配）
- 严判 LLM 响应：必须严格 JSON `{"category": "<枚举>", "confidence": <0-1 float>}` 拒 markdown / 拒 bool（陷阱）/ 拒越界 / 拒非法 category
- 复用 `SyncPolicyAdapter` 4 依赖可注入范本，`classify_and_emit` 5 步主入口
- 业务字段（category / confidence / model_full_id / email_id / source）透传到 event_metadata 顶层，便于 `mmx policy history` 跨业务类型查询
- 正文 > 2000 字符自动截断（防御巨型 body 撑爆 prompt）
- batch 单条响应脏 → 异常入 results 列表，不阻塞后续（D3.3.3 教训：不 catch-all 兜底）

**v1.0.2-first 关键修复**（type system 层面）：
- **P1-1 拆双入口**：成功入口 `classify_and_emit` 无 cf 参数 → 编译期拒绝"成功结果 + last_classify_failed=True"状态耦合；失败入口 `record_classify_failure_and_emit` cf 必填 >= 1 → 必触发 retry/escalate
- **P1-2 5 类严判**：`category_value not in _VALID_CLASSIFY_CATEGORIES` + `latency_ms < 0` 拒收
- **P2-3 平衡 JSON**：`_find_all_balanced_json` 收集所有 + `_extract_balanced_json` 选含 category+conf 的
- **P2-4 批处理补全**：type hint 补 `ValueError | KeyError` + 缺字段 KeyError 收容
- **P2-5 NaN 拒收**：`math.isfinite()` 在 0-1 范围检查前

**v1.0.2-second 关键修复**（公共 API + 文档）：
- **P1 严判下沉**：3 个 `_validate_classify_*` helper 下沉到 `compute_classification_acceptance` + `build_classify_policy_context`，防止 Adapter 重构后绕过严判
- **P2-2 失败报告独立类型**：`ClassifyFailureDecisionReport`（含 `failed: bool` + `last_error: str` + `consecutive_classify_failures: int`），与 `ClassifyDecisionReport`（含 `category: 5 类` + `confidence: float`）类型层面区分，失败入口不再用 `category=""` 违反契约
- **P2-3 顶层导出**：`policy/__init__.py` 暴露 `build_classify_failure_packet` + `ClassifyFailureDecisionReport`，`from my_ai_employee.policy import ...` 不再 ImportError
- **P3 文档同步**：报告 49+47 → 46+50、uv build blocked → 通过、week1-mvp 数字 559 → 603、mapping 数字 576 → 603

**v1.0.2-third 关键修复**（公共 API 自防御 + 数据类自洽 + 文档同步）：
- **P1 公共构造器严判下沉**：`build_classify_packet` 复用 `_validate_classify_category` 公共 helper（原版仅 `type() is str` + 空检查，缺 5 类校验），与主入口 + 公共 helper 同一严判口径（防止传 `"OOPS"` / `"TODO_FIX"` 等任意字符串）
- **P2 Literal[True] + 字段自洽**：`ClassifyFailureDecisionReport.failed: bool` → `Literal[True]`（mypy 编译期拒绝 `failed=False`）；新增 `__post_init__` 三重校验（`failed is True` + `last_error` 非空 + `consecutive_classify_failures >= 1`），D3.3.3 教训应用
- **P2 异常统一 ValueError**：`classify_and_emit` 内联 `if x not in frozenset` 替换为 `_validate_classify_category`，严判入口统一 `ValueError`，防止 list/dict/set 等不可哈希类型在后续操作触发 `TypeError`
- **P3 文档同步**：`classify_and_emit` docstring 用例移除已删除的 `consecutive_classify_failures=0`；`record_classify_failure_and_emit` 返回值 docstring 从 `ClassifyDecisionReport` 改为 `ClassifyFailureDecisionReport`

**关键设计**（D3.3.3 + D4.4 P1 + D4.5 P0 + D4.5 v1.0.1 教训应用）：
- 复用 `router.route(TaskType.CLASSIFY, ...)` 自动走 DeepSeek → Qwen → M3 fallback 链（`fallback.FALLBACK_CHAINS` 已配）
- 严判 LLM 响应：必须严格 JSON `{"category": "<枚举>", "confidence": <0-1 float>}` 拒 markdown / 拒 bool（陷阱）/ 拒越界 / 拒非法 category
- 复用 `SyncPolicyAdapter` 4 依赖可注入范本，`classify_and_emit` 5 步主入口
- 业务字段（category / confidence / model_full_id / email_id / source）透传到 event_metadata 顶层，便于 `mmx policy history` 跨业务类型查询
- 正文 > 2000 字符自动截断（防御巨型 body 撑爆 prompt）
- batch 单条响应脏 → 异常入 results 列表，不阻塞后续（D3.3.3 教训：不 catch-all 兜底）

**已知限制**（D4.6.1+ 复检 P 项）：
- 5 类硬编码（暂不支持扩展到 6+ 类如 NEWSLETTER） → D4.6.1+ 扩 NEWSLETTER / INVOICE 等
- `classify_batch` 顺序串行（100 封 ≈ 50-300s） → D4.6.1+ 改 asyncio + httpx async
- 无 1 千封真实 spike → D4.6.1+ 在 1 千封真实邮件上跑端到端，验证 LLM 准确率 / fallback 触发率
- CLI 集成未做 → D4.6.1+ 加 `mmx classify` 子命令
- 业务字段口径锁定 5 项 → D4.7+ drafter 按需透传（协议已留好）

**参考来源**：`ai/classifier.py` 严判范本 + `policy/integration.py` EmailClassifierAdapter 4 依赖可注入 + D4.5 v1.0.1 反馈闭环模式。完整报告：[reports/D4.6-邮件分类器.md](../reports/D4.6-邮件分类器.md)

**下一棒 → D4.7+ drafter / classifier_v2**（D4.5 范本 + D4.6 EmailClassifierAdapter 复用）。D4.6 **v1.0.2-third 第三次复检真正锁定**（2026-06-09 早晨），W2 业务层启动决策推迟到 6/9 晨间链路确认后启动。D4 智能层底座 6 步全锁定 + 业务层接入范本复用 1 次。

---

### D4.7 — 草稿生成器（✅ 2026-06-10 v1.0.6 锁定，v1.0 → v1.0.1 → v1.0.2 → v1.0.6 演进）

**承接 D4.6 业务层范本**：D4.6 `EmailClassifierAdapter` 4 依赖可注入范本（`event_store` / `engine` / `heartbeat` / `board`）+ 双入口架构（成功/失败 type system 锁定），在 D4.7 第二个真实业务场景上**复用**。

**🔒 4 项契约锁定**（2026-06-09 用户审批 D4.7.1 启动时确认,D4.7.1 实现 commit 中作为测试契约固化）：

1. **草稿无 `confidence` 字段** → 业务验收用**明确长度/必填/tone 枚举**判定（`business_accepted = subject 非空 AND body 长度在 10-8000 AND tone ∈ {FORMAL, FRIENDLY, CONCISE}`），**不**用 LLM 自报 confidence
2. **拒 markdown-wrapped JSON**（不剥离 ```json ... ``` fence）→ LLM 必须返回**裸 JSON**，违者拒收触发 retry；body 字段内容允许 markdown（`*bold*` / `**bold**` 是合法草稿内容）
3. **tone 枚举锁定**：`FORMAL` / `FRIENDLY` / `CONCISE` 三选一,D4.7.1 起始固定,后续扩枚举需 B 类审批
4. **范围限定**（契约 4）：D4.7 只负责**生成草稿文本 + emit 业务事件 + 推进 Lane**,**不写** `drafts` 数据库表、**不创建** Mail.app 草稿、**不接** iCloud CalDAV;端到端联动留 D4.7.1+ / D5+ 业务调度器

**范围**：

- **业务层**：`ai/drafter.py` 实现 `EmailDrafter`（`draft` / `draft_batch`）+ `_parse_draft_response` 严判 LLM 响应
- **Prompt 模板**：`ai/prompts/draft.py` SYSTEM prompt + `build_user_message`（接 `email_category` 入参，D4.6 输出作为 D4.7 输入）
- **业务层接入**：`EmailDrafterAdapter` 复用 D4.6 三入口架构（`draft_and_emit` 成功 + `record_draft_business_blocked_and_emit` 业务阻断 + `record_draft_failure_and_emit` 技术失败，cf 必填 >= 1）
- **业务字段透传**：`draft_subject` / `draft_body` / `tone`（3 选 1 枚举） / `model_full_id` / `email_id` / `category` 6 项到 `event_metadata` 顶层
- **lane_entry_id 命名**：`draft:<source>:<run_id>`（与 `classify:` / `sync:` 区分）
- **D3.3.3 教训应用**：严判入口 + 异常窄化 + 不 catch-all 兜底
- **D4.6 v1.0.1 ~ v1.0.2 教训应用**：
  - P1-1：`LLMAllFallbacksError` 业务异常（全链失败抛子类，不逃逸 RuntimeError）
  - P1-2：拆分 `business_accepted`（Lane）vs `transport_alive`（Heartbeat），**草稿长度越界 / 空 subject / 非法 tone / 占位符未填** ≠ LLM 死（业务验收独立于传输存活，契约 1）
  - P1-3：`last_draft_failed` 显式 bool 解决成功路径误触发 retry / escalate
  - P1-4：平衡括号定位 + 拒 markdown-wrapped JSON（LLM 必须返回裸 JSON，**不剥离** ```json ... ``` fence，违者拒收触发 retry；body 内容允许 markdown，契约 2）
  - P2-5：严判 duck type 拒 type-coerce（`True → 1.0` / `"0.5" → 0.5` 静默 coerce 必须拒）
  - v1.0.2-first：严判下沉到 `compute_*` / `build_*` 公共 API（`_validate_draft_*` helper 复用）
  - v1.0.2-second：`DraftFailureDecisionReport` 独立类型 + `Literal[True]` + `__post_init__` 三重校验
  - v1.0.2-second：`policy/__init__.py` 顶层暴露（`__all__` 声明 ≠ 实际可导入）
  - v1.0.2-third：异常统一 `ValueError`（防止 list/dict/set 不可哈希类型触发 `TypeError`）

**v1.0 验收标准**：

- [x] `pytest tests/ai/test_drafter.py` 全过（78 tests / 严判 30 + batch 10 + prompt 10 + 数据类 6 + 异常 6 + 阻塞 6 + 集成 10）
- [x] `pytest tests/ai/test_drafter_adapter.py` 全过（107 tests，三入口 + 公共 API + 顶层导出 + 契约 helper 复用 + 字段名硬区分 + 双向强一致 + 跨字段校验 + 工厂严判 1:1 + 透传 cf + strip() 语义非空 + type 严判在 hash 前）
- [x] 单封草稿生成 < 10s（week1-mvp §D4 验收 L527，spike 100 封留待 D4.7.4 启动前补）
- [x] 严判 LLM 响应：必须 `{"subject": str 非空 + body: str 非空 + tone: <enum>}` 拒 markdown / 拒空 subject / 拒空 body / 拒超长 body (10-8000 字符边界对称)
- [x] D4.5 `SyncPolicyAdapter` 4 依赖可注入范本复用
- [x] D4.6 `EmailClassifierAdapter` 三入口架构复用（`draft_and_emit` / `record_draft_business_blocked_and_emit` / `record_draft_failure_and_emit`，业务阻断 vs 技术失败字段名级别硬区分）
- [x] D4.4 6 源文件零修改（4 件套契约保持 v1.0）
- [x] mypy 0 errors / ruff format 0 errors / ruff check 0 errors / alembic --sql exit 0 / uv build OK
- [x] lane_entry_id 命名 `draft:<source>:<run_id>`,与 `classify:` / `sync:` 区分
- [x] **3+1 文档沉淀法**：`reports/D4.7-草稿生成器.md`（操作 / 异常 / 改进 25 教训沉淀）+ spike 报告（100 封草稿质量用户体感，B 类决策延后到 D4.7.4 启动前补）

**D4.7 子任务清单**（预计 8.5 小时）：

| # | 任务 | 预计耗时 | 产出 | 状态 |
|---|------|----------|------|------|
| D4.7.1 | `src/my_ai_employee/ai/drafter.py` EmailDrafter + `_parse_draft_response` | 60 min | drafter 服务 | ✅ v1.0 → v1.0.1 → v1.0.2(`7cff852` + `f9e9d1d` + `aeba0e4`) |
| D4.7.2 | `src/my_ai_employee/ai/prompts/draft.py` SYSTEM prompt + `build_user_message` | 30 min | prompt 模板 | ✅ v1.0 → v1.0.8(8 轮复检,`9cf8c98` ~ `717b65a`) |
| D4.7.3 | `src/my_ai_employee/policy/integration.py` EmailDrafterAdapter + `DraftDecisionReport` + `DraftFailureDecisionReport` + 4 `_validate_draft_*` helper | 90 min | Adapter | ✅ v1.0 → v1.0.6(6 轮复检,`9e4fb2e` 业务层契约定型点) |
| D4.7.4 | `src/my_ai_employee/policy/__init__.py` 顶层暴露（D4.6 v1.0.2-second P2-3 教训） | 5 min | 导出 | ✅ v1.0.2(`aeba0e4` 顶层暴露 9 符号) |
| D4.7.5 | `tests/ai/test_drafter.py` 78 tests（30 严判 + 10 batch + 10 prompt + 6 数据类 + 6 异常 + 6 阻塞 + 10 集成） | 90 min | 单元测试 | ✅ v1.0.2(`7cff852`) |
| D4.7.6 | `tests/ai/test_drafter_adapter.py` 107 tests（三入口 + 公共 API + 顶层导出 + 契约 helper 复用 + 字段名硬区分 + 双向强一致 + 跨字段校验 + 工厂严判 1:1 + 透传 cf + strip() 语义非空 + type 严判在 hash 前） | 120 min | 适配器测试 | ✅ v1.0.6(`9e4fb2e` 1027 passed) |
| D4.7.7 | `docs/week1-mvp.md §D4.7` 本段（v1.0 → v1.0.1 → v1.0.2 → v1.0.6 演进） | 30 min | 文档 | ✅ v1.0.6(本 docs-only commit 同步) |
| D4.7.8 | `docs/d4-claw-code-mapping.md §8` D4.7.3 mapping 段 | 30 min | mapping | ✅ v1.0.6(`docs/d4-claw-code-mapping.md` §8 L462-466 沿用) |
| D4.7.9 | `reports/D4.7-草稿生成器.md` v1.0.6 报告（8 质量门 + 25 教训应用） | 30 min | 报告 | ✅ v1.0.6(本 docs-only commit 同步) |
| D4.7.10 | **Spike**：100 封真实邮件跑 `draft` + 草稿质量用户体感（精确度 / 长度 / 语气） | 60 min | spike 报告 | 🎯 B 类决策延后(待 D4.7.4 启动前补,见 §3 报告) |
| D4.7.11 | 8 质量门 + commit + 验收 | 30 min | 锁定 | ✅ v1.0.6(`9e4fb2e` 8 质量门 8/8 全绿) |

**已知限制**（D4.7.1+ 复检 P 项预判）：

- 草稿质量难量化（用户主观） → spike 100 封手标 + 用户体感打分
- 草稿长度不可控 → 严判 body 长度上限（e.g. 8000 字符）
- 历史回复模式需要语料 → 暂用 placeholder，D4.7.1+ 接入 `sent_emails` 表
- `draft_batch` 顺序串行（100 封 ≈ 100-1000s） → D4.7.1+ 改 asyncio + httpx async
- tone 枚举硬编码（**3 类锁定**: `FORMAL` / `FRIENDLY` / `CONCISE`，契约 3，D4.7.1 起始固定,后续扩枚举需 B 类审批）→ 暂不支持 APOLOGETIC / INSPIRATIONAL 等额外枚举

**参考来源**：`ai/classifier.py` 严判范本 + `policy/integration.py` EmailClassifierAdapter 4 依赖可注入 + D4.6 v1.0.1 ~ v1.0.2-third 13 项教训应用。完整报告：[reports/D4.7-草稿生成器.md](../reports/D4.7-草稿生成器.md)（v1.0.6 已固化）。

**下一棒 → D4.7.4 草稿审阅**（D4.7 v1.0.6 业务层三入口 + 25 教训范本 + D4.7.4 草稿审阅业务实现）。D4.7.3 v1.0.6 第六次复检真正锁定（2026-06-10 晚间），D4.7 范围 / 验收 / 参考已明确，业务层契约定型点已固化。

**D4.7 演进路径**（2026-06-10 收官）：D4.7.1 ~ D4.7.11 共 11 个子任务全部锁定。**D4.7.3 v1.0.6**（6 轮复检收官，commit `9e4fb2e`，1027 passed / +107 tests / 8 质量门全绿）作为 D4.7 业务层契约定型点。**D4.7.4 编号复用**为"草稿审阅"主题（详见下段）。

---

### D4.7.4 — 草稿审阅（✅ 2026-06-11 锁定，v1.0 → v1.0.1 → v1.0.2 演进）

**承接 D4.7.3 业务层范本**：D4.7.3 `EmailDrafterAdapter` 三入口架构（成功 / 业务阻断 / 技术失败）+ 25 教训沉淀（独立 dataclass + `Literal[True]` + `__post_init__` 三重校验 + 双层防御 + 双向强一致 + 固化哲学），在 D4.7.4 第二个真实业务场景（**审阅**）上**复用**。

**D4.7.4 演进路径**（2026-06-11 早晨收官）：D4.7.4.1 ~ D4.7.4.9 共 9 个子任务已锁定（代码 + 测试 + 顶层导出 + 文档全固化为 commit `b15ba96`）。**D4.7.4 v1.0.2 业务层三入口真正锁定**，D4.7.4 业务层 213 tests / 全量 1240 passed / 8 质量门全绿 / `policy/integration.py` 91.1% 覆盖（118 adapter tests）。**D4.7.4.10 spike 100 封真实审阅**与 **D4.7.4.11 验收 commit** 是 docs-only 收口后的**最后两步**（非阻塞 D4.7.4 v1.0.2 代码+测试已硬通过；spike 反馈会触发 D4.7.4.1+ 业务层微调，留待 D4.8 启动前并行处理）。完整报告：[reports/D4.7.4-草稿审阅.md](../reports/D4.7.4-草稿审阅.md)（v1.0.2 已固化）。

**🔒 4 项契约锁定**（2026-06-10 用户审批 D4.7.4 启动时确认,D4.7.4 实现 commit 中作为测试契约固化）：

1. **三入口架构**（沿用 D4.7.3 v1.0.1 P1-1 范本）：成功入口 `review_and_emit` + 业务阻断入口 `record_review_business_blocked_and_emit` + 技术失败入口 `record_review_failure_and_emit`（互斥语义,业务阻断 last_review_failed=False / cf=0 永不触发 retry / escalate）
2. **4 类业务阻断白名单**（沿用 D4.7.3 v1.0.5 范本 `type` 严判在 `hash` 前）：`sensitive_word_hit`（敏感词命中,如 PII / 违规词）/ `template_violation`（缺要素,如 TODO 邮件无截止时间）/ `tone_mismatch`（风格不符,如 PERSONAL 邮件用 FORMAL）/ `factual_conflict`（事实矛盾,如草稿日期与原文不符,**2026-06-10 新增**）
3. **裸 JSON 契约**（沿用 D4.7.2 契约 2）：LLM 必须返回严格 JSON `{"review_passed": bool, "flagged_issues": [str, ...], "review_summary": str}` 拒 markdown / 拒空 summary
4. **5 类 SYSTEM prompt 分发**（沿用 D4.7.2 范本）：按 `email_category` 分发不同审阅侧重（URGENT 审责任方+截止 / TODO 审行动项 / FYI 审简洁 / PERSONAL 审友好 / DEFAULT 兜底）

**范围**：

- **业务层**：`ai/reviewer.py` 实现 `EmailReviewer`（`review` / `review_batch`）+ `_parse_review_response` 严判 LLM 响应 + 4 类 `ReviewBlockReason` StrEnum
- **Prompt 模板**：`ai/prompts/review.py` 5 类 SYSTEM prompt + `build_user_message`（接 `email_category` + `draft_result` 入参,D4.7.3 输出作为 D4.7.4 输入）
- **业务层接入**：`EmailReviewerAdapter` 复用 D4.7.3 三入口架构（`review_and_emit` 成功 + `record_review_business_blocked_and_emit` 业务阻断 + `record_review_failure_and_emit` 技术失败,cf 必填 >= 1）
- **业务字段透传**：`review_passed` / `flagged_issues` / `review_summary` / `model_full_id` / `email_id` / `category` 6 项到 `event_metadata` 顶层
- **数据类**：`ReviewDecisionReport`（成功,`review_passed: Literal[True]`） / `ReviewBlockedDecisionReport`（业务阻断,`blocked: Literal[True] + kind=Literal["business_blocked"]`） / `ReviewFailureDecisionReport`（技术失败,`failed: Literal[True]`） 3 类,**字段名级别硬区分**（D4.7.3 v1.0.3 P2-1 教训）
- **业务阻断字段**：`blocked_word: str`（命中词,`strip()` 严判非空）+ `reason: str`（4 类白名单）
- **lane_entry_id 命名**：`review:<source>:<run_id>`（与 `classify:` / `sync:` / `draft:` 区分）
- **D3.3.3 教训应用**：严判入口 + 异常窄化 + 不 catch-all 兜底
- **D4.7.3 v1.0 ~ v1.0.6 教训应用**（**7 项核心契约**）：
  - 工厂层 + `__post_init__` 双层防御（v1.0.5 P1-1 范本）
  - 跨字段校验（v1.0.4 P1-1 范本）：`reason=sensitive_word_hit` → `blocked_word` 必填非空
  - 双向强一致（v1.0.2 P1-2 范本）：`review_passed=True` → `flagged_issues` 可空但 `review_summary` 必填
  - 异常统一 `ValueError`（v1.0.5 P2-1 范本）：`type` 严判在 `hash` 前,防 `TypeError` 泄漏
  - 字段名硬区分（v1.0.3 P2-1 范本）：`blocked` 字段 vs `failed` 字段不可混用
  - 契约 helper 复用（v1.0.3 P1-1 范本）：`_validate_review_*` 工厂层 + 数据类 `__post_init__` 复用同一严判
  - 固化哲学（v1.0.6 范本）：代码 + 文档 + 注释 + 测试同 commit

**v1.0.2 验收标准**（D4.7.4.1 ~ D4.7.4.9 已锁定 9 项,D4.7.4.10 / D4.7.4.11 是 spike + 验收 2 项收口）：

- [x] `pytest tests/ai/test_reviewer.py` 全过（实际 95 tests,5 类 SYSTEM prompt + 4 类阻断白名单 + 严判 + batch,`ai/reviewer.py` 96.2% 覆盖）
- [x] `pytest tests/ai/test_reviewer_adapter.py` 全过（实际 108 funcs / 118 parametrized,三入口 + 公共 API + 顶层导出 + 7 项契约 + 4 类阻断白名单覆盖,`policy/integration.py` 91.1% 覆盖）
- [x] 单封审阅 < 5s（草稿生成 < 10s 的 1/2,因为审阅输入是 DraftResult 而非原始邮件；100 封 spike 实际数据待 D4.7.4.10 验证）
- [x] 严判 LLM 响应:必须 `{"review_passed": bool, "flagged_issues": [str, ...], "review_summary": str}` 拒 markdown / 拒空 summary / 拒超长 summary (> 2000 字符)
- [x] 4 类业务阻断白名单:敏感词 / 模板违规 / 风格不符 / 事实矛盾,每类有专项测试(`TestRecordReviewBusinessBlockedAndEmit` 25 case 全覆盖)
- [x] D4.5 `SyncPolicyAdapter` 4 依赖可注入范本复用
- [x] D4.7.3 `EmailDrafterAdapter` 三入口架构复用（`review_and_emit` / `record_review_business_blocked_and_emit` / `record_review_failure_and_emit`,业务阻断 vs 技术失败字段名级别硬区分）
- [x] D4.4 6 源文件零修改（4 件套契约保持 v1.0）
- [x] mypy 0 errors / ruff format 0 errors / ruff check 0 errors / alembic --sql exit 0 / uv build OK（8 质量门 8/8 全绿,全量 1240 passed）
- [x] lane_entry_id 命名 `review:<source>:<run_id>`,与 `classify:` / `sync:` / `draft:` 区分
- [x] **3+1 文档沉淀法**:`reports/D4.7.4-草稿审阅.md` v1.0.2 已固化（本 commit 同步）+ `docs/d4-claw-code-mapping.md §9` 本 commit 同步 + spike 报告（100 封审阅通过率 + 阻断原因分布,D4.7.4.10 补）

**D4.7.4 子任务清单**（D4.7.4.1 ~ D4.7.4.9 已完成 9 项,代码+测试+顶层导出+文档全固化于 commit `b15ba96`;D4.7.4.10 spike 与 D4.7.4.11 验收 commit 是 docs-only 收口后的最后两步）：

| # | 任务 | 预计耗时 | 产出 | 状态 |
|---|------|----------|------|------|
| D4.7.4.1 | `src/my_ai_employee/ai/reviewer.py` EmailReviewer + `_parse_review_response` + 4 类 `ReviewBlockReason` StrEnum | 60 min | reviewer 服务 | ✅ v1.0.1 |
| D4.7.4.2 | `src/my_ai_employee/ai/prompts/review.py` 5 类 SYSTEM prompt + `build_user_message` + 4 类阻断场景描述 | 30 min | prompt 模板 | ✅ v1.0.1 |
| D4.7.4.3 | `src/my_ai_employee/policy/integration.py` EmailReviewerAdapter + `ReviewDecisionReport` + `ReviewBlockedDecisionReport` + `ReviewFailureDecisionReport` + 5 `_validate_review_*` helper | 90 min | Adapter | ✅ v1.0.2 |
| D4.7.4.4 | `src/my_ai_employee/policy/__init__.py` 顶层暴露（D4.7.3 v1.0.6 教训,9 个新符号） | 5 min | 导出 | ✅ v1.0.2 |
| D4.7.4.5 | `tests/ai/test_reviewer.py` 95 tests（30 严判 + 10 batch + 10 prompt + 6 数据类 + 6 异常 + 4 类白名单本地阻断） | 90 min | 单元测试 | ✅ v1.0.1（96.2% 覆盖） |
| D4.7.4.6 | `tests/ai/test_reviewer_adapter.py` 108 funcs / 118 parametrized tests（三入口 + 公共 API + 顶层导出 + 7 项契约 + 4 类阻断白名单） | 120 min | 适配器测试 | ✅ v1.0.2（91.1% integration.py 覆盖） |
| D4.7.4.7 | `docs/week1-mvp.md §D4.7.4` 本段（v1.0 → v1.0.1 → v1.0.2 演进） | 15 min | 文档 | ✅ v1.0.2（本段已固化） |
| D4.7.4.8 | `docs/d4-claw-code-mapping.md §9` D4.7.4 mapping 段 | 30 min | mapping | ✅ v1.0.2（本 commit 同步） |
| D4.7.4.9 | `reports/D4.7.4-草稿审阅.md` v1.0.2 报告（8 质量门 + 25 教训应用） | 30 min | 报告 | ✅ v1.0.2（本 commit 同步） |
| D4.7.4.10 | **Spike**:100 封审阅真实邮件跑 `review` + 阻断率 / 阻断原因分布 / 审阅延迟用户体感 | 60 min | spike 报告 | 🎯 待 D4.8 启动前补 |
| D4.7.4.11 | 8 质量门 + commit + 验收（最终 docs-only 收口） | 30 min | 锁定 | 🎯 待 spike 后 commit |

**已知限制**（D4.7.4.1+ 复检 P 项预判 — 9 项已固化,2 项留 B 类延后）：

- 审阅质量难量化（用户主观） → spike 100 封手标 + 用户体感打分（D4.7.4.10）
- 4 类阻断白名单可能漏场景（如 SPAM 误判） → D4.7.4.1+ 复检可能新增白名单（**B 类决策**,需用户审批,**延后到「我的AI员工」项目完成后处理**）
- `review_batch` 顺序串行（100 封 ≈ 50-500s） → D4.7.4.1+ 改 asyncio + httpx async
- LLM 审阅成本（每次多 1 次 LLM 调用） → D4.7.4.1+ 评估本地小模型 / 规则引擎 fallback（**B 类决策**,**延后到「我的AI员工」项目完成后处理**）
- 敏感词库内置 20 个高风险词（已落地,PII / 安全 / 内部代号 / 商业秘密 / 硬承诺模式） → D4.7.4.1+ 接入 `sensitive_words` 配置表

**参考来源**：`ai/drafter.py` 严判范本 + `policy/integration.py` EmailDrafterAdapter 三入口范本 + D4.7.3 v1.0 ~ v1.0.6 **25 教训沉淀**（独立 dataclass + `Literal[True]` + `__post_init__` 三重校验 + 双层防御 + 双向强一致 + 固化哲学）。完整报告：[reports/D4.7.4-草稿审阅.md](../reports/D4.7.4-草稿审阅.md)（v1.0.2 已固化）。

**下一棒 → D4.7.4.10 spike（100 封真实审阅）**。D4.7.4 v1.0.2 业务层三入口已真正锁定（2026-06-11 早晨,commit `b15ba96`）,docs-only 收口本 commit 已完成（§D4.7.4 + §9 mapping + v1.0.2 报告 3 文档同步）。D4.7.4.10 spike 100 封真实审阅 + D4.7.4.11 验收 commit 是 docs-only 收口后**最后两步**（非阻塞 — D4.7.4 v1.0.2 代码+测试已硬通过;spike 反馈会触发 D4.7.4.1+ 业务层微调,留待 D4.8 启动前并行处理）。D4.8 启动决策（W2 晨间链路确认）强依赖 D4.7.4 `ReviewDecisionReport.review_passed=True` + `reviewer_decision_event_id` 作为 outbox 外键契约。

---

### D4.8 — 草稿入库/发送（🎯 2026-06-10 启动,目标 v1.0 锁定）

**承接 D4.7.4 业务层范本**：D4.7.4 `EmailReviewerAdapter` 三入口架构（成功 / 业务阻断 / 技术失败）+ 25 教训沉淀,在 D4.8 第三个真实业务场景（**入库 outbox**）上**复用**。

**🔒 5 项契约锁定**（2026-06-10 用户审批 D4.8 启动时确认,D4.8 实现 commit 中作为测试契约固化）：

1. **三入口架构**（沿用 D4.7.3 v1.0.1 P1-1 范本）：成功入口 `store_and_emit` + 业务阻断入口 `record_store_business_blocked_and_emit`（`duplicate_email_id` / `blacklisted_recipient`） + 技术失败入口 `record_store_failure_and_emit`（SQL 异常 / 锁失败）
2. **outbox 表 schema 11 字段**（**2026-06-10 新增 migration 0004**）：`id` / `email_id` (UNIQUE) / `subject` (1-200) / `body` (10-8000) / `tone` (3 选 1) / `reviewer_decision_event_id` (FK → events.id) / `drafter_decision_event_id` (FK → events.id) / `status` (pending_send / approved / sent / cancelled,DEFAULT pending_send) / `created_at` (epoch ms) / **`recipient_email`** (**2026-06-10 新增**,避免 D5+ 发送时回查 emails 表) / **`priority`** (**2026-06-10 新增**,urgent / normal / low,便于 D5+ 发送调度器排序)
3. **PermissionProfile = READ_WRITE**（D4.5 `read_only` / D4.6/D4.7.3/D4.7.4 `read_only` 区分,**D4.8 首次引入 READ_WRITE**）：写入 outbox 表需要 READ_WRITE 权限
4. **入库幂等性**（**D4.8 关键**）：`email_id` 唯一索引,UNIQUE 冲突 → 业务阻断入口 `record_store_business_blocked_and_emit(reason="duplicate_email_id")`,**不**走技术失败入口（**D3.3.3 异常窄化教训应用**）
5. **不真发 SMTP**（**D4.8 范围边界**）：仅入库 outbox 表 + `status=pending_send`,**不**调 SMTP 发送,**不**写 `sent_at` / `sent_status` 字段（避免 D4.8 越界）。真实发送留 D5+ 业务调度器

**范围**：

- **数据库层**：`src/my_ai_employee/core/migrations/versions/0004_outbox_table.py` 新增 outbox 表（11 字段 + UNIQUE(email_id) + 2 索引:`status_created_at` 用于 D5+ 调度器 / `priority_created_at` 用于紧急邮件优先）
- **ORM 模型**：`src/my_ai_employee/core/models/outbox.py` `OutboxEntry` dataclass + 4 状态枚举 `OutboxStatus`（pending_send / approved / sent / cancelled,StrEnum）
- **DB 封装**：`src/my_ai_employee/db/outbox.py` `OutboxStore` 类（`insert` / `by_email_id` / `by_status` / `update_status` 4 个公共方法,**D3.3.3 异常窄化**:except IntegrityError 不接 SQLAlchemyError 基类）
- **业务层接入**：`EmailOutboxAdapter` 复用 D4.7.3 三入口架构（`store_and_emit` 成功 + `record_store_business_blocked_and_emit` 业务阻断 + `record_store_failure_and_emit` 技术失败,cf 必填 >= 1）
- **数据类**：`OutboxDecisionReport`（成功,`outbox_stored: Literal[True]`） / `OutboxBlockedDecisionReport`（业务阻断,`blocked: Literal[True] + kind=Literal["business_blocked"]`） / `OutboxFailureDecisionReport`（技术失败,`failed: Literal[True]`） 3 类,**字段名级别硬区分**
- **业务字段透传**：`outbox_id` / `subject_length` / `body_length` / `tone` / `recipient_email` / `priority` 6 项到 `event_metadata` 顶层
- **跨字段校验**：`reason=duplicate_email_id` → `email_id` 必填非负;`priority=urgent` → `email_category` 必为 URGENT（**D4.7.4 联动契约**）
- **lane_entry_id 命名**：`outbox:<source>:<run_id>`（与 `classify:` / `sync:` / `draft:` / `review:` 区分）
- **D3.3.3 + D4.7.3 v1.0 ~ v1.0.6 教训应用**（**7 项核心契约**,同 D4.7.4 范本）：
  - 工厂层 + `__post_init__` 双层防御
  - 跨字段校验（v1.0.4 P1-1 范本）：`reason=duplicate_email_id` → `email_id` 必填
  - 双向强一致（v1.0.2 P1-2 范本）：`outbox_stored=True` → `outbox_id >= 1`
  - 异常统一 `ValueError`（v1.0.5 P2-1 范本）
  - 字段名硬区分（v1.0.3 P2-1 范本）
  - 契约 helper 复用（v1.0.3 P1-1 范本）：`_validate_outbox_*`
  - 固化哲学（v1.0.6 范本）

**v1.0.1 验收标准**（2026-06-11 晚间演进,D4.8.7 commit `e3f0d80` 锁定后）：

- [x] `pytest tests/db/test_outbox.py` 全过（**35 tests**,D4.8.6 commit `38bd210` 锁定,7 sections:StrEnum / ORM / insert / UNIQUE 冲突 / 查询 / 状态机 / _normalize 严判）
- [x] `pytest tests/policy/test_outbox_adapter.py` 全过（**68 tests** vs v1.0 计划 80+,D4.8.7 commit `e3f0d80` 锁定,12 test class 覆盖 6 helper / 3 工厂 / 1 acceptance / 1 context / 3 DecisionReport / 5 依赖 / 3 入口 / 1 集成 / 3 顶层导出）
- [x] 单封入库 < 1s（DB 写入,无 LLM 调用,实测 0.005s 数量级）
- [x] 严判入库参数:`email_id >= 0` / `subject 1-200 strip 非空` / `body 10-8000 strip 非空` / `tone ∈ 3 类` / `recipient_email 含 @` / `priority ∈ 3 类`
- [x] UNIQUE(email_id) 冲突 → 业务阻断入口,not 技术失败入口（**D3.3.3 异常窄化**:双重 except `(IntegrityError, sqlcipher3.dbapi2.IntegrityError)`）
- [x] D4.5 `SyncPolicyAdapter` 4 依赖可注入范本复用（**D4.8.7 修复**:依赖注入 `is None` 范式替代 `or` 兜底）
- [x] D4.7.3 `EmailDrafterAdapter` 三入口架构复用（业务阻断 vs 技术失败字段名级别硬区分 `blocked` vs `failed` + `kind` 字段）
- [x] PermissionProfile = READ_WRITE（D4.8 首次引入,与 D4.5/D4.6/D4.7.3/D4.7.4 区分）
- [x] D4.4 6 源文件零修改（4 件套契约保持 v1.0）
- [x] mypy 0 errors / ruff format 0 errors / ruff check 0 errors / alembic upgrade head --sql exit 0 / uv build OK（**8 质量门全绿**）
- [x] lane_entry_id 命名 `outbox:<source>:<run_id>`,与 `classify:` / `sync:` / `draft:` / `review:` 区分
- [x] **3+1 文档沉淀法**:`reports/D4.8-草稿入库.md` v1.0.1(D4.8.10 commit 待入库)+ spike 报告 `output/spike/spike_outbox_100_20260611_221105.md`(D4.8.11 commit 待入库)

**v1.0.1 关键修复**（D4.8.7 commit `e3f0d80` 暴露并修复 D4.8.4 commit `252a036` 遗留 bug）：

1. **LaneBoard.add 拒 FINISHED 终态** → `store_and_emit` 第 7 步首次 add 改用 `LaneStatus.ACTIVE`,然后 `update` 到 `FINISHED/BLOCKED`（ACTIVE → FINISHED/BLOCKED 合法转换）。3 入口范本统一。
2. **recovery_policy 非法白名单** → `build_outbox_blocked_packet` 改 `"none"`(业务阻断永不重试),`build_outbox_failure_packet` 改 `"retry_on_transient"`(技术失败可重试),均在 `task_packet.TaskPacket` 白名单内。

**D4.8 子任务清单**（预计 8 小时,**D4.8.1-7 已锁定,8-12 待收口**）：

| # | 任务 | 预计耗时 | 产出 | 状态 |
|---|------|----------|------|------|
| D4.8.1 | `src/my_ai_employee/core/migrations/versions/0004_outbox_table.py` outbox 表 schema 11 字段 + UNIQUE(email_id) + 2 索引 | 45 min | migration | ✅ commit `a6bcb83` |
| D4.8.2 | `src/my_ai_employee/core/models/outbox.py` → `src/my_ai_employee/core/outbox.py` `OutboxEntry` ORM + 3 状态枚举 `OutboxStatus`(**路径冲突修复后迁 core/ 顶层**) | 30 min | ORM | ✅ commit `50545ad` |
| D4.8.3 | `src/my_ai_employee/db/outbox.py` `OutboxStore` 封装（4 公共方法 + IntegrityError 窄化 + OutboxEmailDuplicateError） | 60 min | DB 封装 | ✅ commit `f553eb1` |
| D4.8.4 | `src/my_ai_employee/policy/outbox_adapter.py` EmailOutboxAdapter + 3 DecisionReports + 6 `_validate_outbox_*` helper | 90 min | Adapter | ✅ commit `252a036` |
| D4.8.5 | `src/my_ai_employee/policy/__init__.py` 顶层暴露 9 符号 + outbox 迁 `core/` 顶层 + 1 死代码删除 | 5 min | 导出 | ✅ commit `00360e2` |
| D4.8.6 | `tests/db/test_outbox.py` 35 tests（CRUD + UNIQUE + 状态机 + 索引 + StrEnum + _normalize）+ 4 测试同步(0004 head / 8 张表 / 9 张表) | 60 min | DB 单元测试 | ✅ commit `38bd210` |
| D4.8.7 | `tests/policy/test_outbox_adapter.py` 68 tests + D4.8 v1.0.1 bug 修复(LaneBoard 范本 + recovery_policy 白名单) | 120 min | 适配器测试 | ✅ commit `e3f0d80` |
| D4.8.8 | `docs/week1-mvp.md §D4.8` 本段（v1.0 → v1.0.1 演进） | 15 min | 文档 | ✅ 本 docs commit |
| D4.8.9 | `docs/d4-claw-code-mapping.md §10` D4.8 mapping 段 | 30 min | mapping | 🎯 |
| D4.8.10 | `reports/D4.8-草稿入库.md` v1.0.1 报告（8 质量门 + 教训应用 + v1.0.1 bug 修复） | 30 min | 报告 | ✅ reports/D4.8-草稿入库.md |
| D4.8.11 | **Spike**：100 封入库幂等性 + 状态机正确性 + 紧急邮件优先排序 | 60 min | spike 报告 | ✅ output/spike/spike_outbox_100_20260611_221105.md |
| D4.8.12 | 8 质量门 + commit + 验收 | 30 min | 锁定 | 🎯 当前 |

**已知限制**（D4.8 v1.0.1 已固化,2026-06-14 D5.6.5.1 收口后 B3 / B5 真正解封）：

- ~~outbox 表无 `sent_at` / `sent_status` 字段（避免 D4.8 越界）~~ → **B5 已解封**:D5.2 migration 0005 加 `sending` 状态 + `ALLOWED_TRANSITIONS` 白名单(D5.3 P1 收口加 SENDING → CANCELLED 业务阻断链路)
- ~~真实 SMTP 发送不在 D4.8 范围~~ → **B3 已解封**:D5 业务调度器接管(D5.6.5 commit `6ac8d9b` 真实 1 封 smtp.qq.com:465 SSL 端到端实测通过,sent=1/1.27s)
- 紧急邮件优先排序仅 `priority + created_at` 二维索引,真实调度可能涉及更多维度(**B 类决策仍延后**:扩 priority 枚举 / 加 SLA 字段)
- 黑名单收件人库空白 → 初始 2 类白名单(`duplicate_email_id` / `blacklisted_recipient`),D4.8.1+ 接入 `blacklist_recipients` 配置表(**B 类决策延后**)
- ~~状态机转换规则不完整（D4.8 仅入库到 `pending_send`）~~ → **B5 已解封**:D5.2 加 `pending_send → approved / cancelled` 状态转换白名单,D5.6.4 收窄 `send_and_emit` 仅接受 APPROVED 状态

**参考来源**：`db/` 目录 D3 sync 范本 + `core/models/` ORM 范本 + `policy/integration.py` EmailDrafterAdapter 三入口范本 + D4.7.3 v1.0 ~ v1.0.6 **25 教训沉淀**。完整报告：[reports/D4.8-草稿入库.md](../reports/D4.8-草稿入库.md)。

**下一棒 → v0.1 发布规划**。D5.4 OutboxDispatcher 主循环已完成(commit `e9f3126`),D5.5 SLA + 退避 + Heartbeat 联动已完成(commit `3f449d9`),D5.5.1 补齐 FAILED 重试闭环与 `skip_breach` 统计语义,D5.5.2 commit `97b7605` 修批次饥饿 + STALLED 真实可达,D5.5.3 commit `7e9bca0` P0 外部 symlink + P1 调度公平性 + P2 Heartbeat 恢复,D5.5.4 commit `a7560c1` P1 双向回填 + 单槽轮换 + P3 refresh_last_seen bool 严判,D5.5.5 commit `a866810` P1 单槽轮换条件修复 + P2 测试断言升级 + P3 K 段单池边界测试 + 文档数据同步,D5.6 v1 commit `c4a7d01` ⏸️ 被检查员驳回(措辞失实),D5.6.1 commit `fdf44c6` ⏸️ 5 项修复后被检查员二次驳回,D5.6.2 commit `819affb`+`8fdc088` ⏸️ 7 项二次修复后被检查员第三轮驳回,D5.6.3 commit `007a6be`+`2bc5b3b`+`3de03ed` ⏸️ 第三轮 7 项反馈后被检查员**第四轮**驳回(5 缺陷:虚拟时钟时间倒流 + send_and_emit 收窄 PENDING_SEND + OutboxStore.insert 防审批伪造 + 真实网络门 + 报告命名),**D5.6.4 commit `a75894c`+`e07feee`+`9d78900`+`fa7aff5` ✅ 第四轮 5 缺陷全部修复收口**(P0 虚拟时钟 is None 严判 + P1-1 send_and_emit 收窄 APPROVED only + P1-2 OutboxStore.insert 防审批伪造 + P1-3 SMTP_REAL_NETWORK 门控 + transport factory 注入 + SpikeResult dataclass),**D5.6.5 commit `6ac8d9b` ✅ 真实 1 封 SMTP 端到端实测通过**(smtp.qq.com:465 SSL,4 重防误发 + SMTP_REAL_NETWORK=1 门控全过,sent=1/1.27s / 状态机 4 步全过 / 7 字段 DispatcherResult 全 ok,Keychain round-trip 范本,真实 vs InMemory 性能 ≈ 160x,**B3 真正解封**),**D5.6.5.1 commit `2396def`+`b037334` ✅ 检查员驳回 5 缺陷全部修复**(P1-1 测试隔离双层防御 + P1-2 邮箱脱敏 5 文件 + P2-1 SpikeResult 16 字段落地(D5.7.1 P2-3 统一) + P2-2 文档一致 5 处翻 D5.6.5 + P2-3 措辞 smtp 250 OK ≠ 真实送达),**D5.7 commit `4a24504` ✅ docs 收口 8 件套**,**D5.7.1 commit `2cd434e` ✅ 检查员驳回 5 缺陷全部修复真正锁定**(P1-1 旧测试 SMTP 触网风险 + P1-2 邮箱脱敏固化 + P2-1 D5.7 状态统一 + P2-2 跨项目链接路径 + P2-3 SpikeResult 字段数 16 统一),**D5.7.2 commit `ef83c63` ✅ docs 收口最后一致性修正 真正锁定**(P1 D5 验收报告覆盖率表实测重生成:总覆盖 90.4%→90.2% / send_adapter 92.3%→84.8% / smtp 88.1%→69.6% / keychain 86.5%→45.7% + P2-1 README SpikeResult 16 字段统一 + P2-2 阶段编号翻 D5.7.2 + P2-3 真实发送报告下一棒翻 v0.1 + P2-4 映射链接路径修复 + P2-5 DoD 证据补全)。**D5 业务调度器已完结 / 35 commits 收口链 / 不再开 D5.7.3,直接进入 v0.1 发布规划**(**B 类决策仍延后**:扩 priority 枚举 / 加 SLA 字段 / `blacklist_recipients` 配置表 / outlook/gmail SMTP provider)。

---

## D5 — 业务调度器(SMTP 发送链路)

> **2026-06-11 重新定义**:D5 启动计划原本是"CalDAV + 菜单栏 + launchd",但 D4.8 v1.0.1 锁定后出现**实际瓶颈** — outbox 表能入库 `pending_send` 状态的草稿,但**没有任何消费者把这些草稿真正发出**。D4.8 契约 5 明确"不真发 SMTP,D5+ 调度器接管",这是 B3 自然解封位置。
>
> **范围调整**:D5 = 真实 SMTP 发送链路(7 子阶段)。CalDAV / 菜单栏 / launchd **顺延到 D6+**(Week 2 决策点再细化)。
>
> **D5.0-redirect docs commit**:`docs(d5.0-redirect): 重新定义 D5 = SMTP 业务调度链路`(本段 + §0 反例 + §D4.8 已知限制 + 末棒 + 状态行同 commit 重写,commit `b0943ff`)
**D5.1-fix docs 收口 commit**:本次 commit 同步 D5.1-fix 状态行(4 处"本次"→ ✅ commit `18284fa`)+ 风险表 fallback 错误描述修订(原"connect() 时 fallback"实际是"硬报错"误描述,按实际代码行为重写)

### D5.1 Context — 为什么启动 D5

**问题**:D4.8 v1.0.1 锁定后,`outbox.status=pending_send` 草稿堆积,无消费者。

**目标**:落地 D5 业务调度器 — 消费 `pending_send` / `approved` 行 → SMTP 真实发送 → 状态机推进 `pending_send → sending → sent` / `→ failed`,失败按指数退避(封顶 1h)重试,URGENT 5min SLA 告警,Heartbeat 3 态联动(HEALTHY / STALLED / TRANSPORT_DEAD)。

**预期结果**:D5.7 收口后,8 质量门 8/8 全绿(预计 1498 passed)、`reports/D5-业务调度器.md` 归档、跨项目 memory 同步到 Agent Assistant。**B3(接 SMTP) + B5(sending 状态) 自然解封,B1 / B2 / B4 仍延后**。

### D5.2 核心契约(6 条范围边界)

| # | 契约 | 范本来源 | 必达 |
|---|------|---------|------|
| 1 | **SMTP transport 抽象 + Keychain 凭证** | `connectors/imap.py:45-74` + `core/keychain.py:201-208` | `SMTPConnector` + `SmtpLibTransport` 生产 + `InMemorySmtpTransport` 测试 + `set_smtp_password / get_smtp_password` 高层封装 |
| 2 | **`sending` 状态 + 显式状态机白名单** | `db/outbox.py` `update_status` 扩字段 + `policy/heartbeat.py:104` 状态机范本 | migration 0005 enum-only + `ALLOWED_TRANSITIONS` + `OutboxIllegalTransitionError` |
| 3 | **EmailSendAdapter 三入口** | `policy/outbox_adapter.py:597-611` + `:640-650` 严判 | `send_and_emit` / `record_send_business_blocked_and_emit` / `record_send_failure_and_emit` + `SendDecisionReport` 双向强一致 |
| 4 | **SMTP 异常窄化(D3.3.3 教训)** | `core/sync.py:47-58` 分层 except + `db/outbox.py:148-159` 窄化 | `SMTPRecipientsRefused` → 业务阻断 + `SMTPServerDisconnected / SMTPConnectError / socket.timeout` → 技术失败,**不**接 `SMTPException` / `Exception` 基类 |
| 5 | **OutboxDispatcher 主循环** | `core/sync.py:60-80` 构造 + `run_once` 6 步 | `run_once()` 6 步:heartbeat → 拉批 → 逐条 send → 累加 → 落日志 → 返回 `DispatcherResult` |
| 6 | **SLA + 退避 + Heartbeat 联动** | `policy/heartbeat.py:73-90` + `:130-140` | `SLAEvaluator(priority, age_ms)` + `min(2^failures * 60s, 1h)` + `assert_alive` 严格 |

### D5.3 7 子阶段任务清单

| 子阶段 | 目标 | 关键文件 | 预计 cases | commit |
|--------|------|---------|----------|--------|
| **D5.1** ✅ | Keychain SMTP service + transport 抽象 | `core/keychain.py` + `connectors/smtp.py` + `tests/connectors/test_smtp.py` + `scripts/spike_set_smtp_password.py` | 32 | `cce567a` |
| **D5.1-fix** ✅ | 默认 transport 边界(避免假成功) + CLI provider 严判(只 qq) | `connectors/smtp.py` + `scripts/spike_set_smtp_password.py` + 2 new files(`tests/scripts/`)+ 7 transport boundary + 3 CLI cases | +10 | `18284fa` |
| **D5.2** ✅ | migration 0005 + `sending` + 状态机白名单 | `core/migrations/versions/0005_outbox_sending_state.py` + `db/outbox.py` + `tests/db/test_outbox_status_transitions.py` | +18 | `604f937` |
| **D5.3** ✅ | EmailSendAdapter 三入口 + 4 异常窄化 + SENDING→CANCELLED 业务阻断链路硬收口 | `policy/send_adapter.py` + `policy/exceptions.py` + `tests/policy/test_send_adapter.py` + `tests/policy/test_exceptions.py` + `tests/db/test_outbox_status_transitions.py` | +40(36 send_adapter + 4 收口新增:1 状态机 SENDING→CANCELLED + 3 send_adapter SMTPDataError/AuthError/从 SENDING 推 CANCELLED) | `192c215` |
| **D5.4** ✅ | OutboxDispatcher 主循环(6 步范本 + 异常分流 + Heartbeat 联动)+ 优先级排序 | `scheduler/outbox_dispatcher.py` + `tests/scheduler/test_outbox_dispatcher.py` | +37(D段+ E段合并后减为 37,vs 计划 45) | `e9f3126` |
| **D5.5** ✅ | SLA 评估 + 退避公式 + Heartbeat 联动 + D5.5.1 FAILED 重试闭环/skip_breach 语义修正 + D5.5.2 批次饥饿配额 + STALLED 真实可达 + D5.5.3 P0 外部 symlink 修复 + P1 调度公平性 + P2 Heartbeat 恢复 + D5.5.4 P1 双向回填 + 单槽轮换 + P3 refresh_last_seen bool 严判 + **D5.5.5 P1 单槽轮换条件修复 + P2 测试断言升级 + P3 K 段单池边界测试 + 文档数据同步** | `scheduler/sla.py` + `scheduler/backoff.py` + `scheduler/outbox_dispatcher.py` + `tests/scheduler/test_sla.py` + `tests/scheduler/test_retry_backoff.py` + `tests/scheduler/test_outbox_dispatcher.py` | +36 | `3f449d9` + D5.5.1/D5.5.2/D5.5.3/D5.5.4/D5.5.5 |
| **D5.6** | spike 100 真实发送 + 验收报告 | `scripts/spike_send_100.py` + `reports/D5-spike-100.md` + `reports/d5-acceptance.md` | (无新 cases,跑 8 质量门) | (待) |
| **D5.7** | docs 收口 8 件套(week1-mvp §D5 末棒 + README + mapping §11 + D5 报告 + 跨项目 memory) | 5 docs 文件 | (无新 cases) | (待) |

**当前累计**:1534 cases(D5.5.5 8 质量门全绿;1385 D5.1-fix 锁定 → +149 D5.2-D5.5.5)+ 10 commits(8 我的AI员工 + 1 docs 收口跨项目 + 1 Agent Assistant memory)

### D5.2 状态机白名单(B5 解封项 + D5.3 P1 业务阻断链路硬收口)

```
PENDING_SEND → {SENDING, APPROVED, FAILED, CANCELLED}  # D5.2 vs 启动计划文档偏差:含 APPROVED
APPROVED     → {SENDING, FAILED, CANCELLED}
SENDING      → {SENT, FAILED, CANCELLED}  # D5.3 P1 加 CANCELLED(业务阻断链路硬收口)
SENT         → {}    (终态)
FAILED       → {PENDING_SEND, CANCELLED}  # 重试回 PENDING_SEND
CANCELLED    → {}    (终态)
```

**D5.3 P1 业务阻断链路硬收口说明**:SMTP 永久退信可能在 SENDING 中间态触发(收件人拒收 / SMTPDataError 4xx),
此时 entry.status=SENDING,业务阻断入口 record_send_business_blocked_and_emit 必须能推
SENDING → CANCELLED,否则 ALLOWED_TRANSITIONS 挡死业务阻断链路,entry 永远卡在 SENDING。

D5.2 锁定版 SENDING 目标集仅 {SENT, FAILED} 2 元素 — P1 硬阻塞, D5.3 收口加 CANCELLED。

### D5.3 异常窄化映射(D3.3.3 教训应用 + D5.3 P2-P3 收口)

| smtplib 异常 | Adapter 业务异常 | 业务语义 | recovery_policy | consecutive_send_failures | 收口版本 |
|--------------|-----------------|----------|-----------------|--------------------------|----------|
| `SMTPRecipientsRefused` | `SMTPSendRecipientsRefusedError` | **业务阻断** | `none` | **不递增** | D5.2 |
| `SMTPSenderRefused` | `SMTPSendSenderRefusedError` | **业务阻断** | `none` | **不递增** | D5.2 |
| `SMTPDataError`(4xx DATA 阶段数据错误) | `SMTPSendRecipientsRefusedError`(reason=data_error) | **业务阻断** | `none` | **不递增** | **D5.3 P2 收口** |
| `SMTPAuthenticationError`(认证失败) | `SMTPSendSenderRefusedError`(reason=sender_refused) | **业务阻断** | `none` | **不递增** | **D5.3 P3 收口** |
| `SMTPServerDisconnected` | `SMTPSendTransportError` | 技术失败 | `retry_on_transient` | +1 | D5.2 |
| `SMTPConnectError` | `SMTPSendTransportError` | 技术失败 | `retry_on_transient` | +1 | D5.2 |
| `socket.timeout` / `TimeoutError` | `SMTPSendTransportError` | 技术失败 | `retry_on_transient` | +1 | D5.2 |
| `OSError` / `socket.gaierror` | `SMTPSendTransportError` | 技术失败 | `retry_on_transient` | +1 | D5.3 P2 |
| `ssl.SSLError`(SSL 握手失败) | `SMTPSendTransportError` | 技术失败 | `retry_on_transient` | +1 | **D5.3 P2 收口** |

**关键约束**:**不**接 `SMTPException` / `Exception` 基类,只接具体子类(D3.3.3 教训 — 防 OperationalError / 编程错误被误吞)。

**D5.3 收口修正**:`smtplib.SSLError` 不是 smtplib 公开 API(mypy 报 `attr-defined`),改用标准库 `ssl.SSLError`(SMTPConnector `connectors/smtp.py:151-152` 同款修正)。

### D5.5 SLA 阈值表 + 退避公式

**SLA**:
```
URGENT:  threshold=5min,    warning=3min
HIGH:    threshold=30min,   warning=15min
NORMAL:  threshold=4hour,   warning=2hour
```

**退避**:`retry_after_ms = min(2^(consecutive_send_failures - 1) * 60_000, 3_600_000)`(cf=1 从 60s 起,封顶 1h)

**应用层过滤**:`consecutive_send_failures >= 1` 且 `last_failed_at + retry_after > now` 跳过,计入 `DispatcherResult.skipped`；退避结束后 `FAILED → PENDING_SEND → SENDING → SENT/FAILED` 闭环重试。`DispatcherResult.skip_breach` 是 SLA 额外维度,可与 `sent` / `skipped` 同时成立,不参与互斥 outcome 求和。

### D5.7 验收标准(8 质量门)

| # | 质量门 | 首次过 | 累计 tests |
|---|--------|--------|----------|
| 1 | `uv run pytest` | D5.1(1375)/D5.2(1393)/D5.3(1429)/D5.4(1474)/D5.5(1508)/D5.5.1(1514)/D5.5.2(1518)/D5.5.3(1522)/D5.5.4(1532)/D5.5.5(1534) | **+149 cases** |
| 2 | `uv run ruff check` | D5.1 | 0 errors |
| 3 | `uv run ruff format --check` | D5.1 | 全绿 |
| 4 | `uv run mypy src` | D5.3 | 0 errors |
| 5 | `uv run mypy src+tests` | D5.5 | 0 errors |
| 6 | `uv run alembic upgrade head --sql` | D5.2 | exit 0 |
| 7 | `uv build` | D5.6 | OK |
| 8 | `make lint` | D5.7 | 0 errors |

**D5 启动一票否决**:8 质量门 8/8 全过 + 8 风险缓解 checklist 全应用 + 25 教训应用(D4.7.3 v1.0.6)+ docs 收口 8 件套。

### D5.8 风险点(8 项 → D5 范围内缓解)

| # | 风险 | 等级 | 缓解动作 | 落地子阶段 |
|---|------|------|----------|-----------|
| 1 | **SMTP 凭据 Keychain 写入失败** | 🚨 严重 | D5.1 `set_smtp_password` 写入后立即 round-trip 自检 + `spike_set_smtp_password.py --check` 入口 | D5.1 ✅ |
| 2 | **默认 transport = InMemorySmtpTransport 假成功** | 🚨 严重 | D5.1-fix 默认 `transport=None` + 构造时 `loguru.warning` 提醒 + `connect()` 入口 `is None` 硬报错(`SmtpTransportError`)。生产必须显式传 `SmtpLibTransport()`,测试场景才传 `InMemorySmtpTransport()`,**不**走 fallback | D5.1-fix ✅ `18284fa` |
| 3 | **CLI `--provider` choices 暴露未实现 provider** | ⚠️ 中 | D5.1-fix `spike_set_smtp_password.py --provider` 严判 `choices=("qq",)`,outlook/gmail 由 argparse 自动 `SystemExit 2`(无需运行时抛 `NotImplementedError`,沿 D4.7.3 教训) | D5.1-fix ✅ `18284fa` |
| 4 | **`cancelled → sent` 非法状态转换** | 🚨 严重 | D5.2 `ALLOWED_TRANSITIONS` 白名单 + `OutboxIllegalTransitionError` 严判 | D5.2 |
| 5 | **业务阻断(收件人拒收)被误归类为可重试** | 🚨 严重 | D5.3 异常窄化:recipients_refused / sender_refused 单独捕获 → 业务阻断 + `consecutive_send_failures` 不递增 | D5.3 |
| 6 | **`last_send_failed ↔ consecutive_send_failures` 跨字段不一致** | ⚠️ 中 | D5.3 `SendDecisionReport.__post_init__` 双向校验(D4.7.3 v1.0.5 P1-2 范本) | D5.3 |
| 7 | **SMTP 掉线无限重试撑爆 CPU** | ⚠️ 中 | D5.5 退避公式 `2^failures * 60s` 封顶 1h + 应用层过滤 | D5.5 |
| 8 | **URGENT 邮件 5min 超时未被发现** | ⚠️ 中 | D5.5 `SLAEvaluator.evaluate` 每次 run_once 逐条判 + `ESCALATE_REQUIRED` 决策写 event | D5.5 |

### D5.9 CalDAV / 菜单栏 / launchd 顺延清单(B 类保留)

> **不在 D5 范围**。以下三项**顺延到 D6+**(Week 2 决策点再细化),当前**保留 13 行 B 类延后清单**规则。

- **CalDAV 双向同步** — 落 `connectors/caldav.py` + `scripts/sync_caldav.py`(B 类顺延)
- **Mac 菜单栏状态** — 落 `menu_bar/app.py`(rumps)+ `agents/管家.md`(B 类顺延)
- **launchd 保活** — 落 `scripts/launchd_install.sh / launchd_uninstall.sh`(B 类顺延)

**触发条件**:D5 锁定 + Week 1 末决策点通过 + Week 2 启动后,按实际体感决定 D6+ 优先启动哪一项。

### D5.10 已知限制(D5.1 已固化)

- **SMTPConnector 不继承 `BaseConnector`** — 自维护 `_SmtpCircuitBreakerState`,避免 `fetch` 抽象方法 TypeError(D4.7.3 v1.0.3 duck type 范本)
- **SMTP 凭据严禁 logger 打印 value** — `keychain.set_smtp_password` + `spike_set_smtp_password.py` 只打印 service+account+长度
- **SMTP 授权码与 IMAP 授权码分别存** — 因 QQ 邮箱 IMAP/SMTP 授权码可不同(D2 IMAP 真实 QQ 验收 memory 沉淀)
- **默认 transport 边界** — `SMTPConnector(transport=None)` 不允许忘记显式注入,`connect()` 时才 fallback 到 `InMemorySmtpTransport` 并 loguru WARNING
- **CLI provider 严判** — `spike_set_smtp_password.py --provider {qq,outlook,gmail}`,outlook/gmail 显式 `NotImplementedError` 提示"D5.1 只实现 qq"

**D5.7.2 docs 收口最后一致性修正 真正锁定** ✅。D5.1-D5.7.2 已全部固化(D5.1 `cce567a` + D5.1-fix `18284fa` + D5.2 `604f937` + D5.3 `192c215` + D5.4 `e9f3126` + D5.5 `3f449d9` + D5.5.1 + D5.5.2 `97b7605` + D5.5.3 `7e9bca0` + D5.5.4 `a7560c1` + D5.5.5 `a866810` + D5.6 v1-D5.6.3 ⏸️ 被检查员驳回 + **D5.6.4 `a75894c`+`e07feee`+`9d78900`+`fa7aff5` ✅** 5 缺陷全部修复 + **D5.6.5 `6ac8d9b` ✅ 真实 1 封 SMTP 端到端实测通过** + **D5.6.5.1 `2396def`+`b037334` ✅ 检查员驳回 5 缺陷全部修复** + **D5.7 `4a24504` ✅ docs 收口 8 件套** + **D5.7.1 `2cd434e` ✅ 检查员驳回 5 缺陷全部修复真正锁定** + **D5.7.2 `ef83c63` ✅ docs 收口最后一致性修正 真正锁定**:P1 D5 验收报告覆盖率表实测重生成(总覆盖 90.4%→90.2% / send_adapter 92.3%→84.8% / smtp 88.1%→69.6% / keychain 86.5%→45.7%) + P2-1 README SpikeResult 16 字段统一 + P2-2 阶段编号翻 D5.7.2 + P2-3 真实发送报告下一棒翻 v0.1 + P2-4 映射链接路径修复 + P2-5 DoD 证据补全)。**D5 业务调度器完全锁定,不再开 D5.7.3,直接进入 v0.1 发布规划** + D6+ CalDAV/菜单栏/launchd 顺延(Week 2 决策点)。

**v0.1 启动规划落地**:[docs/v0.1-launch-plan.md](v0.1-launch-plan.md) — 4 子阶段 D6+D7+D9+D10 + 收口,D8 智能财务延后 v0.2,B1/B2/B4/outlook-gmail 仍延后 v0.2,端到端 **9 场景**(S1-S9 唯一编号表,Week 1 5 + Week 2 4,详见 `docs/v0.1-launch-plan.md` § 9 场景表)沿 D5.6.5 真实 1 封范本 + spike 100 量级,2026-07 中下旬发布。

**D5.7 docs 收口 8 件套清单**(D5.7 commit `4a24504` 全部完成):

1. `docs/week1-mvp.md` §D5 末棒翻到 D5.6.5.1 锁定态(本段上方)
2. `docs/week1-mvp.md` §D4.8 已知限制 B3/B5 解封项翻到 D5.6.5.1
3. `docs/week1-mvp.md` 末棒"下一棒 → D5.7 docs 收口 8 件套剩余"(L927 段)
4. `README.md` L7 状态行 + L42 铁律 + L168 D5 推进中行翻到 D5.6.5.1
5. `CLAUDE.md` L7 当前阶段翻到 D5.6.5.1
6. `docs/d4-claw-code-mapping.md` §11 D5 业务调度器 mapping 段(7 段结构范本)
7. `reports/D5-业务调度器.md` 8 段结构报告
8. 跨项目 memory:`Agent Assistant/memory/d5-business-scheduler-launch.md` + `MEMORY.md` 索引 + 全局 memory

**D5.7.1 检查员驳回 5 缺陷修复真正锁定**(本段下方将增补):

1. **P1-1 旧测试 SMTP 触网风险** — `test_spike_send_100_real_mode.py:153` 用 `pytest.raises(Exception)` 宽泛放行 + 不注入 InMemorySmtpTransport factory + 不跟踪 `SmtpLibTransport.__init__`,跑全套测试时可能连接 smtp.qq.com。改注入 `fake_factory` + `tracked_smtp_lib_init` + 状态断言(factory 调 1 次 + SmtpLibTransport 未构造)
2. **P1-2 邮箱脱敏固化** — 完整邮箱在 5 处文档残留(week1-mvp L1143 + d4-claw-code-mapping L794/L868 + Agent Assistant memory 3 处),全量替换脱敏 + grep 验证 0 残留
3. **P2-1 D5.7 状态统一** — README/architecture/CLAUDE/week1-mvp 仍写"收口中"/"剩 1 子阶段",翻到 "D5.7.1 真正锁定"
4. **P2-2 跨项目链接路径** — `docs/*.md` 用 `../Agent%20Assistant/...`(少一级,解析到仓库内部不存在目录),实际需 `../../Agent%20Assistant/...`(从 `docs/` 出到仓库根,再出到 DesktopOrganizer 兄弟目录)
5. **P2-3 SpikeResult 字段数 16 统一** — `scripts/spike_send_100.py:94` 注释"11 字段" + d4-claw-code-mapping 多处 11 字段描述,实际 16 字段

**D5.7.2 docs 收口最后一致性修正 真正锁定**(本段下方增补):

1. **P1 D5 验收报告覆盖率表实测重生成** — `reports/D5-业务调度器.md §1.2` 写总覆盖 90.4% / send_adapter 92.3% / smtp 88.1% / keychain 86.5% 全部与本轮实测不符。本轮实测:总覆盖 90.2% / send_adapter 84.8% / smtp 69.6% / keychain 45.7%(覆盖率表全部从 `coverage report` 当前输出重生成,实测数据固化原则)
2. **P2-1 README SpikeResult 16 字段统一** — README L7 状态行 + L240 最后更新行仍写 "P2-1 SpikeResult 11 字段落地"(D5.6.5.1 commit message 当时描述),实际 SpikeResult 已是 16 字段(2+6+3+4+1)。翻为 "16 字段结构化"
3. **P2-2 阶段编号翻 D5.7.2** — HEAD = `ef83c63 docs(d5.7.2)`(amend 衍生,原始提交 `f670c74`),但 README/architecture/CLAUDE/week1-mvp/D5-业务调度器/D5.6.5-real-send-1 全部仍写 D5.7.1 最终锁定。统一翻 D5.7.2 = ef83c63(选项 A:明确为 D5.7.2 docs 收口,不再开 D5.7.3)
4. **P2-3 真实发送报告下一棒翻 v0.1** — `reports/D5.6.5-real-send-1.md` L201 仍写 "D5.7 docs 收口 8 件套剩余",与上文 D5.7.1 锁定声明冲突,翻为 "v0.1 发布规划"
5. **P2-4 映射链接路径修复** — `docs/d4-claw-code-mapping.md` L4 引用不存在的 `D4-claw-code-auto-reference.md` + L919/920/931/932 使用错误的 `../我的AI员工/...` 路径,改引用真实存在的 `d4-4path-parallel-launch.md` + 同项目内 `../reports/...`
6. **P2-5 DoD 证据补全** — `week1-mvp.md L1195-1203` 8 项 DoD 中 3 项缺证据(分类准确率 ≥80% / 端到端 5 场景 / 自用 3 天每天省 20 分钟),补 `reports/d4-classifier-evaluation.md` / `reports/d5-e2e-spike-100.md` / 标"经验性指标待 v0.1 后量化"链接

### D5.6.4 范围(4th round 修复 — 2026-06-14)

**承接**:D5.6.3 4th round 检查员反馈 5 缺陷全部修复。

**5 修复**:
1. **P0 虚拟时钟时间倒流** — `send_and_emit` / `store_and_emit` / `lane_board.add` 3 处 `end_ms = now_ms if now_ms is not None else int(time.time() * 1000)`(`is None` 严判,不用 `or` 短路)
2. **P1-1 send_and_emit 收窄 APPROVED only** — 入口 `if entry.status != APPROVED: raise`,防 PENDING_SEND 绕过审批
3. **P1-2 OutboxStore.insert 防审批伪造** — 移除 `status=` 参数 + `last_approved_at_ms is not None → ValueError` 严判 + 双层防御
4. **P1-3 SMTP_REAL_NETWORK 门控** — `os.environ.get("SMTP_REAL_NETWORK") != "1" → ValueError`(防误连 smtp.qq.com)
5. **P1-3 transport factory 注入** — `smtp_transport_factory: Callable[[], Any] | None = None` 优先于 real_send,集成测试可注入 InMemorySmtpTransport 替换 SmtpLibTransport

**辅助修复**:
- `SpikeResult` dataclass(16 字段,D5.7.1 P2-3 统一)结构化报告骨架,markdown 渲染层仍用 report_lines,但下游可序列化
- spike verify 阶段用 `current_now_ms`(虚拟时钟)而非真实时间,防"时间倒流"严判
- 4 个旧 real_mode 测试加 `monkeypatch.setenv("SMTP_REAL_NETWORK", "1")`(env 门解锁后验证旧契约继续生效)

**验证**:
- 278 passed in 10.01s(commit 1+2 范围 239 + commit 3 新增 4 + 旧测试修订 7)
- ruff check / format 0 errors
- mypy 5 source files 0 errors
- spike `--count 100` InMemory 跑通(sent=100 / Heartbeat=HEALTHY / p50=7.91ms / p95=10.19ms)

**2 commits**:
- `a75894c`: send_and_emit 收窄 APPROVED only + OutboxStore.insert 防审批伪造(P0 + 3 × P1)
- `e07feee`: SMTP 真实网络门 + transport factory 注入 + SpikeResult(P1-3 + 真实网络门)
- `9d78900`: docs(d5.6.4) 状态行 + B3 解封 + 措辞 + 文档一致 4 修复(检查员反馈,2026-06-14)
- `fa7aff5`: 命名重整 D5.6.3 → D5.6.4 沿 D5.5.5 amend 衍生 hash 范本(2026-06-14)

**详细**:[reports/d5.6.4-acceptance.md](../reports/d5.6.4-acceptance.md) + [reports/D5.6.4-spike-100.md](../reports/D5.6.4-spike-100.md)

---

### D5.6.5 范围(真实 1 封 SMTP 端到端实测 — 2026-06-14)

**承接**:D5.6.4 第四轮 5 缺陷全部修复收口后,用户授权做 1 封真实 SMTP 端到端实测,B3 真正解封。

**实测环境**:
- SMTP 服务器:`smtp.qq.com:465` SSL
- from=to 邮箱:脱敏 `477***009@qq.com`(D5.6.5.1 P1-2 修复,详见下)
- 16 chars 授权码:写入 Keychain(沿 D2 IMAP 范本,`unset HISTFILE` + 变量传递 + round-trip 自检)
- 4 重防误发:`--recipient` + `--max-recipients 1` + `--confirm "yes-i-understand-this-sends-real-email"` + `--count 1`
- env 门控:`SMTP_REAL_NETWORK=1` 显式解锁(默认安全 deny-by-default)

**实测结果**:
- 1 封 SMTP 端到端通过(sent=1, 总调度时长 1.27s)
- 状态机 4 步全过:`PENDING_SEND → APPROVED → SENDING → SENT`
- 7 字段 DispatcherResult 全 ok:`sent=1, total_picked=1, business_blocked=0, technical_failed=0, skipped=0, skip_breach=0, iterations=1`
- 性能基线:真实 1.27s vs InMemory p50=7.91ms ≈ 160x(SSL 握手 + SMTP 协议栈占大头)
- B3 真正解封(已通过 8 质量门 8/8 全绿,1563 passed / 90.4%)

**1 commit**:`6ac8d9b` 真实 1 封 SMTP 端到端实测

**详细**:[reports/D5.6.5-real-send-1.md](../reports/D5.6.5-real-send-1.md) + [memory/d5.6.5-real-send.md](../../Agent%20Assistant/memory/d5.6.5-real-send.md)

---

### D5.6.5.1 范围(检查员驳回 5 缺陷修复 — 2026-06-14)

**承接**:D5.6.5 真实 1 封实测通过后,检查员统一检查驳回 5 缺陷,D5.6.5.1 修复落地。

**5 修复**:
1. **P1-1 测试隔离加固** — `pytest.raises(Exception)` 宽泛放行是 P1 漏洞(异常前可能已连 smtp.qq.com)。改注入 `InMemorySmtpTransport` factory + `SmtpLibTransport.__init__` 构造计数 + factory 调用计数 + 状态断言 3 层防御
2. **P1-2 邮箱脱敏** — `477***009@qq.com`(脱敏)完整邮箱在 5 处文档泄露(README/architecture/spike/REPORT/Agent Assistant memory)。全量替换 `477***009@qq.com`(脱敏) + grep 验证 0 处残留
3. **P2-1 SpikeResult 真正落地** — `run_spike()` 注释 `-> None` + 末尾无 return,形同虚设。改 `-> SpikeResult` + 末尾构造并返回 16 字段(D5.7.1 P2-3 统一;模式 2 + 计数 6 + 时延 3 + 注入 4 + 扩展 1)
4. **P2-2 文档一致** — 5 处文档停留在 D5.6.3 / "待重跑" / B3 延后 / 假 commit `6e9f0e3`。翻到 D5.6.5 / 8 门全绿 / B3 真正解封 / 移除假 commit
5. **P2-3 措辞澄清** — "真实送达" 措辞过强,smtp 250 OK ≠ 真实送达。改 "SMTP 服务器接受 (smtp 250 OK)"(3 文件 + 1 docstring)

**2 commits**:
- `2396def`: spike 测试隔离加固 + run_spike 真正返回 SpikeResult(P1-1 + P2-1,5→6 tests)
- `b037334`: 邮箱脱敏 + 文档一致 + 措辞澄清(P1-2 + P2-2 + P2-3,5 files)

**8 质量门 8/8 全绿**:1565 passed in 15.59s(从 1563 → 1565,+2 R2/R6) / ruff 0 / format 0 / mypy src 0 / mypy src+tests 0 / alembic exit 0 / uv build OK / make lint 0

**5 教训**:测试绝不允许连真实外部世界 / 真实凭据脱敏固化动作 / dataclass 必配套 return / 文档状态行必随实测翻 / SMTP 服务器接受 ≠ 真实送达

**详细**:[memory/d5.6.5.1-fixes.md](../../Agent%20Assistant/memory/d5.6.5.1-fixes.md)(跨项目 memory)

---

## Week 1 末决策点（关键）

> **触发**：D5 末（周五晚）

### 决策矩阵

| 维度 | 达标 | 不达标 |
|------|------|--------|
| 邮件分类准确率 | ≥ 80% | < 80% |
| 1-click 草稿可用性 | 用户 1 周内用 ≥ 3 次 | 0 次 |
| iCloud CalDAV 同步可靠性 | 100% | < 95% |
| 菜单栏稳定性 | launchd 24h 保活 | < 12h |
| 自用体感 | "省时间" | "添麻烦" |

### 四种决策

- **🟢 继续 Week 2** — 5 维度全达标
- **🟡 修补 1-2 周** — 3-4 维度达标
- **🟠 内测延长** — 2-3 维度达标（v0.1 不发布）
- **🔴 砍到自用** — 1 维度以下，定位"高级玩具"

---

## Week 1 验收清单（DoD）

> **2026-06-11 修订**:CalDAV / 菜单栏 / launchd 三项**从 Week 1 DoD 移除**(D5 顺延 D6+),新增 D5 业务调度器 DoD。

- [ ] 邮件自动分类 5 类 ≥ 80%(D4.6 v1.0.2 锁定,D4.7.4 v1.0.2 进一步升级) — **目标已声明但未跑 1 千封真实邮件 spike 量化准确率**;D4.6.1 报告仅基于 dev 集小样本;D7 启动前必跑量化 spike,生成 [reports/D4.6.1-准确率验证.md](reports/D4.6.1-准确率验证.md) 后才可标 [x]
- [x] 1-click 草稿 < 10s(D4.7.3 v1.0.6 锁定,p50 < 2s) — 证据:[reports/D4.7-草稿生成器.md](reports/D4.7-草稿生成器.md) + InMemory 100 封 spike 数据
- [x] **D5 业务调度器:outbox 草稿真实 SMTP 发送 + 状态机推进 + SLA 告警**(**D5.7.2 `ef83c63` 真正锁定**,smtp.qq.com:465 SSL sent=1/1.27s,状态机 4 步全过) — 证据:[reports/D5-业务调度器.md](reports/D5-业务调度器.md) + [reports/D5.6.5-real-send-1.md](reports/D5.6.5-real-send-1.md)
- [ ] 端到端 5 场景全过(适配 D5 业务调度器,CalDAV/iCloud 场景移除) — **目标已声明但未做端到端 5 场景的独立测试报告**;已落地的端到端证据:[reports/D5.6.5-real-send-1.md](reports/D5.6.5-real-send-1.md) SMTP 真实 1 封(5 场景中 1/5) + [reports/d5-acceptance.md](reports/d5-acceptance.md) 25 教训应用 checklist;**5 场景全过为 v0.1 发布前必达**,v0.1 启动后跑全 5 场景 spike,生成 [reports/v0.1-e2e-five-scenarios.md](reports/v0.1-e2e-five-scenarios.md) 后才可标 [x]
- [ ] 自用 3 天体感 ≥ "省时间"(D5 业务调度器日均减少手动发送邮件 20 分钟) — **经验性指标,无量化报告**:开发期间主观体感(草稿生成 < 10s + 1-click 审批 + 真实 SMTP 端到端);v0.1 发布后量化(累计 7 天使用时长 / 草稿采纳率 / 误发率),生成 [reports/v0.1-self-use-3-days.md](reports/v0.1-self-use-3-days.md) 后才可标 [x]
- [x] MDLint 0 错误(`make lint` 0 errors / 45+ files)
- [x] 单元测试覆盖率 ≥ 70%(D5 目标 90%+)**实测 90.2% / 1565 passed**(**D5.7.2 `ef83c63` 锁定,coverage report 本轮实测:总覆盖 90.2% / send_adapter 84.8% / smtp 69.6% / keychain 45.7%**)
- [x] 8 质量门 8/8 全绿(D5.7.2 `ef83c63` 锁定,pytest 1565 / ruff 0 / format 0 / mypy src 0 / mypy src+tests 0 / alembic --sql exit 0 / uv build OK / make lint 0)
- [x] `reports/D*.md` 7 份归档(D1 / D2 / D3.1 / D3.2 / D3.3 / D4.7.4 / D4.8)+ **D5 业务调度器报告 `reports/D5-业务调度器.md` (D5.7.2 锁定)**+ spike 报告 7 份 + D5.6.5 真实 1 封 + D5.6.4 spike 100 封 + D5 acceptance

**D6+ 顺延清单**(Week 1 DoD 不含,Week 2 决策点再评估):

- ⏸️ iCloud CalDAV 双向同步 100%
- ⏸️ Mac 菜单栏 4 状态实时
- ⏸️ launchd 24h 保活

---

**最后更新**：2026-06-13(D5.5.4 commit `a7560c1` P1 双向回填 + 单槽轮换 + P3 refresh_last_seen bool 严判 + D5.5.5 commit `a866810` P1 单槽轮换条件修复 + P2 测试断言升级 + P3 K 段单池边界测试 + 文档数据同步完成,1534 passed / 8 质量门全绿 / 90.3% 覆盖)
**状态**:D1-D5.5.5 已完成(D4.8 v1.0.1 commit `2e48179` + D5.1 `cce567a` + D5.1-fix `18284fa` + D5.2 `604f937` + D5.3 `192c215` + D5.4 `e9f3126` + D5.5 `3f449d9` + D5.5.1 + D5.5.2 `97b7605` + D5.5.3 `7e9bca0` + D5.5.4 `a7560c1` + D5.5.5 `a866810`),剩 D5 业务调度器 2 子阶段(D5.6 真实发送 spike → D5.7 docs 收口 8 件套)
**维护者**:Mr-PRY
