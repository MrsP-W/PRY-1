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

**下一棒 → D4.3 Events 表契约**（6/10 启动，参考 claw-code `g004-events-reports-contract.md`）

### D4.2 — MCP 抽象层（✅ v1.0 锁定 2026-06-08）

**承接 D4.1.1 下一棒**：MCP 客户端基类抽象 + 生命周期 + 4 类业务异常 + DegradedReport（**不接真实 MCP server**，仅 MockTransport 留扩展）。

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

**下一棒 → D4.3 Events 表契约**（6/10 启动，参考 claw-code `g004-events-reports-contract.md`）

### 目标

邮件自动分类（5 类）+ 1-click 草稿生成，端到端可用。

### 任务清单

> **2026-06-08 更新**：D4.0 LLM 路由层（前置 D-step，v1.0 锁定）已建好，本节 D4.1-D4.8 任务改用 `router.route()` 调用而非直接调 LLM SDK。

| # | 任务 | 预计耗时 | 产出 | 状态 |
|---|------|----------|------|------|
| 4.0 | LLM 路由层（capability + provider + fallback + router）| 90 min | 5 文件 + 30 测试 | ✅ v1.0 锁定（6/8）|
| 4.1.1 | **HTTP 实施**：`OpenAICompatibleProvider.chat()` + httpx + 4 类异常 + 26 测试 | 90 min | httpx 调用 + respx 集成测试 | ✅ v1.0 锁定（6/8 20:30）|
| 4.2 | 写 `ai/classifier.py`（用 `router.route(CLASSIFY, ...)` + 5 类标签）| 90 min | 分类服务 | ⏳ 待启动 |
| 4.3 | 写 `ai/drafter.py`（用 `router.route(DRAFT, ...)` + 历史回复模式）| 90 min | 草稿服务 | ⏳ 待启动 |
| 4.4 | 写 `ai/prompts/classifier.txt`（中文 prompt + few-shot 5 例）| 30 min | 提示词 | ⏳ 待启动 |
| 4.5 | 写 `ai/prompts/drafter.txt`（中文 prompt + 角色设定）| 30 min | 提示词 | ⏳ 待启动 |
| 4.6 | 写 `scripts/classify_all.py`（批量分类 + 准确率统计）| 60 min | 评估脚本 | ⏳ 待启动 |
| 4.7 | 写 `tests/ai/test_classifier.py`（500 封真实邮件标注）| 60 min | 单元测试 | ⏳ 待启动 |
| 4.8 | **Spike**：100 封手标邮件做混淆矩阵 | 60 min | 准确率报告 | ⏳ 待启动 |
| 4.9 | 写 `core/audit.py`（LLM 调用审计日志）| 30 min | 合规依据 | ⏳ 待启动 |

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

### 📌 下一棒 → D4.3（Events 表契约）→ D4.4 → D5

- **D4.0 LLM 路由层 + D4.1.1 HTTP 实施 + D4.2 MCP 抽象层 三锁定**（6/8 22:00）
- D4.0 路由决策 + D4.1.1 真实 HTTP 调用 + D4.2 MCP 抽象 = D4.3-D4.9 可直接 `router.route()` + `client.call_tool()` 双底座
- 下棒任务：**D4.3 Events 表契约**（6/10 启动，参考 claw-code `g004-events-reports-contract.md`）
- 再下棒：D4.4 任务策略板 → D4.5 release readiness（6/14 周末）

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

**最后更新**：2026-06-07
**状态**：D1 已完成（脚手架通过），D2 待启动
**维护者**：Mr-PRY
