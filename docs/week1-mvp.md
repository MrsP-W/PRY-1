# Week 1 MVP — 邮件 + 日程

> **目标**：在 5 个工作日内交付**邮件自动分类 + 1-click 草稿 + 日程同步**三大功能，可日用。
>
> **架构参考**：[architecture.md](architecture.md)
>
> **里程碑**：Week 1 末（周五晚）— 自用 3 天，决策是否继续 Week 2。

---

## 0. Week 1 总览

### 0.1 范围（In-Scope）

| 功能 | 验收标准 |
|------|----------|
| 邮件自动分类 | 5 类标签准确率 ≥ 80% |
| 1-click 草稿生成 | 单封邮件响应 < 10s |
| CalDAV 日程同步 | iCloud 双向同步（Google 延后）|
| Apple Reminders 同步 | 复用 Agent Assistant 已建能力 |
| Mac 菜单栏状态 | 今日未读 + 今日待办实时显示 |

### 0.2 反例（Out-of-Scope）

- ❌ 邮件发送（Week 1 只生成草稿，用户手动确认）
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
- **4 个 SQLCipher 雷区**：见 [reports/D3.1-数据层基础完成.md](../../我的AI员工/reports/D3.1-数据层基础完成.md) §4

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

**完整踩坑分析**：见 [reports/D3.2-ORM与迁移框架完成.md](../../我的AI员工/reports/D3.2-ORM与迁移框架完成.md) §2 / §4 / §9

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

### D4.7 — 草稿生成器（🎯 2026-06-09 启动，目标 v1.0 锁定）

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

- [ ] `pytest tests/ai/test_drafter.py` 全过（目标 ≥ 50 tests）
- [ ] `pytest tests/ai/test_drafter_adapter.py` 全过（实际 107 tests，三入口 + 公共 API + 顶层导出 + 契约 helper 复用 + 字段名硬区分 + 双向强一致）
- [ ] 单封草稿生成 < 10s（week1-mvp §D4 验收 L527）
- [ ] 严判 LLM 响应：必须 `{"subject": str 非空 + body: str 非空 + tone: <enum>}` 拒 markdown / 拒空 subject / 拒空 body / 拒超长 body (> 8000 字符)
- [ ] D4.5 `SyncPolicyAdapter` 4 依赖可注入范本复用
- [ ] D4.6 `EmailClassifierAdapter` 三入口架构复用（`draft_and_emit` / `record_draft_business_blocked_and_emit` / `record_draft_failure_and_emit`，业务阻断 vs 技术失败字段名级别硬区分）
- [ ] D4.4 6 源文件零修改（4 件套契约保持 v1.0）
- [ ] mypy 0 errors / ruff format 0 errors / ruff check 0 errors / alembic --sql exit 0 / uv build OK
- [ ] lane_entry_id 命名 `draft:<source>:<run_id>`,与 `classify:` / `sync:` 区分
- [ ] **3+1 文档沉淀法**：`reports/D4.7-草稿生成器.md`（操作 / 异常 / 改进）+ spike 报告（100 封草稿质量用户体感）

**D4.7 子任务清单**（预计 8.5 小时）：

| # | 任务 | 预计耗时 | 产出 | 状态 |
|---|------|----------|------|------|
| D4.7.1 | `src/my_ai_employee/ai/drafter.py` EmailDrafter + `_parse_draft_response` | 60 min | drafter 服务 | 🎯 |
| D4.7.2 | `src/my_ai_employee/ai/prompts/draft.py` SYSTEM prompt + `build_user_message` | 30 min | prompt 模板 | 🎯 |
| D4.7.3 | `src/my_ai_employee/policy/integration.py` EmailDrafterAdapter + `DraftDecisionReport` + `DraftFailureDecisionReport` + 3 `_validate_draft_*` helper | 90 min | Adapter | 🎯 |
| D4.7.4 | `src/my_ai_employee/policy/__init__.py` 顶层暴露（D4.6 v1.0.2-second P2-3 教训） | 5 min | 导出 | 🎯 |
| D4.7.5 | `tests/ai/test_drafter.py` 50 tests（30 严判 + 10 batch + 10 prompt） | 90 min | 单元测试 | 🎯 |
| D4.7.6 | `tests/ai/test_drafter_adapter.py` 107 tests（三入口 + 公共 API + 顶层导出 + 契约 helper 复用 + 字段名硬区分 + 双向强一致 + 跨字段校验 + 工厂严判 1:1 + 透传 cf + strip() 语义非空 + type 严判在 hash 前） | 120 min | 适配器测试 | 🎯 |
| D4.7.7 | `docs/week1-mvp.md §D4.7` 本段（v1.0 → v1.0.1 → v1.0.2 演进） | 30 min | 文档 | 🎯 |
| D4.7.8 | `docs/d4-claw-code-mapping.md §8` D4.7 mapping 段 | 30 min | mapping | 🎯 |
| D4.7.9 | `reports/D4.7-草稿生成器.md` v1.0 报告（8 质量门 + 教训应用） | 30 min | 报告 | 🎯 |
| D4.7.10 | **Spike**：100 封真实邮件跑 `draft` + 草稿质量用户体感（精确度 / 长度 / 语气） | 60 min | spike 报告 | 🎯 |
| D4.7.11 | 8 质量门 + commit + 验收 | 30 min | 锁定 | 🎯 |

**已知限制**（D4.7.1+ 复检 P 项预判）：

- 草稿质量难量化（用户主观） → spike 100 封手标 + 用户体感打分
- 草稿长度不可控 → 严判 body 长度上限（e.g. 8000 字符）
- 历史回复模式需要语料 → 暂用 placeholder，D4.7.1+ 接入 `sent_emails` 表
- `draft_batch` 顺序串行（100 封 ≈ 100-1000s） → D4.7.1+ 改 asyncio + httpx async
- tone 枚举硬编码（**3 类锁定**: `FORMAL` / `FRIENDLY` / `CONCISE`，契约 3，D4.7.1 起始固定,后续扩枚举需 B 类审批）→ 暂不支持 APOLOGETIC / INSPIRATIONAL 等额外枚举

**参考来源**：`ai/classifier.py` 严判范本 + `policy/integration.py` EmailClassifierAdapter 4 依赖可注入 + D4.6 v1.0.1 ~ v1.0.2-third 13 项教训应用。完整报告：[reports/D4.7-草稿生成器.md](../reports/D4.7-草稿生成器.md)（待写）。

**下一棒 → D4.7 实施**（本段确认后启动）。D4.6 v1.0.2-third 第三次复检真正锁定（2026-06-09 早晨），D4.7 范围 / 验收 / 参考已明确，等待用户审批。

---

## D5 — CalDAV 同步 + 菜单栏

### 目标

iCloud CalDAV 双向同步 + Mac 菜单栏状态显示。

### 任务清单

| # | 任务 | 预计耗时 | 产出 |
|---|------|----------|------|
| 5.1 | 写 `connectors/caldav.py`（iCloud 优先 + 双向同步 + 冲突解决）| 90 min | CalDAV 适配器 |
| 5.2 | 写 `scripts/sync_caldav.py`（增量同步）| 60 min | 同步入口 |
| 5.3 | 写 `menu_bar/app.py`（rumps + 状态显示）| 90 min | 菜单栏 UI |
| 5.4 | 写 `agents/管家.md`（@管家 Agent 提示词）| 30 min | 主动提醒角色 |
| 5.5 | 写 `scripts/launchd_install.sh`（保活安装）| 30 min | launchd 集成 |
| 5.6 | 写 `scripts/launchd_uninstall.sh` | 15 min | 卸载脚本 |
| 5.7 | **Spike**：launchd 保活效果（24h 监测）| 30 min | 保活报告 |
| 5.8 | 写 `README.md` 更新（首次启动向导）| 30 min | 用户文档 |
| 5.9 | Week 1 集成测试（端到端 5 场景）| 60 min | 验收 |

**总耗时**：约 7 小时

### 验收标准

- [ ] iCloud CalDAV 双向同步 100% 成功
- [ ] 菜单栏图标显示：今日未读 / 今日待办 / 本月支出（占位）
- [ ] launchd 保活 24h 不掉（spike 报告）
- [ ] 端到端 5 场景全过：
  1. 新邮件到达 → 分类 → 菜单栏更新
  2. 用户点草稿 → drafter → Mail.app 草稿
  3. iCloud 新事件 → 同步进 SQLite
  4. SQLite 新事件 → 同步进 iCloud
  5. launchd 启动 → 全部适配器初始化

### 风险点

- **iCloud CalDAV 限流**：连续同步可能被拒，需加 retry + 退避
- **CalDAV 时区**：iCloud 用 UTC，本地显示需转换
- **launchd 权限**：首次安装需 sudo + 引导用户进"系统设置 > 登录项"
- **rumps 兼容性**：macOS 14+ 菜单栏 API 有变化

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

- [ ] 邮件自动分类 5 类 ≥ 80%
- [ ] 1-click 草稿 < 10s
- [ ] iCloud CalDAV 双向同步 100%
- [ ] Mac 菜单栏 4 状态实时
- [ ] launchd 24h 保活
- [ ] 端到端 5 场景全过
- [ ] 自用 3 天体感 ≥ "省时间"
- [ ] MDLint 0 错误
- [ ] 单元测试覆盖率 ≥ 70%
- [ ] `docs/spike-*.md` 3 份报告齐

---

**最后更新**：2026-06-09（D4.6 v1.0.2-third 锁定 + D4.7 范围明确）
**状态**：D1-D4.6 已完成（v1.0.2-third 锁定 6/9 早晨），D4.7 草稿生成器范围已明确待审批启动
**维护者**：Mr-PRY
