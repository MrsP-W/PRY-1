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

- [ ] `python scripts/test_imap.py --email your@qq.com` 能连 QQ 邮箱
- [ ] 凭证存 macOS Keychain（**不落盘** .env）
- [ ] mock IMAP server 单元测试覆盖率 ≥ 70%
- [ ] 失败时进入熔断（30 min 后再试）
- [ ] 写 `docs/spike-imap-compat.md` 记录 QQ 已通 + Outlook/Gmail 待办

### 风险点（D1.1 收窄后）

- **QQ 授权码**：需用户进 QQ 邮箱网页手动生成（不是密码）
- **mitm 风险**：imapclient 默认 `verify=True`，macOS 证书链有时不完整
- **Outlook/Gmail 推后**：OAuth 2.0 流程复杂度高，留 D2.5 或后续

### 📌 下一棒 → D3

- IMAP 适配器（QQ）已就绪
- D3 任务：SQLCipher 数据层 + 邮件入库（分批）
- 关键决策：分批入库 vs 全量？— 我建议**分批**（避免 SQLite 锁）

---

## D3 — 数据层 + IMAP 同步

### 目标

SQLite 加密 schema + IMAP 邮件入库 + 检索能力。

### 任务清单

| # | 任务 | 预计耗时 | 产出 |
|---|------|----------|------|
| 3.1 | 写 `core/db.py`（**sqlcipher3 封装** + `PRAGMA key` 流程 + 密码从 Keychain 取）| 60 min | 数据库连接 |
| 3.2 | 写 `core/schema.sql`（emails / events / transactions / notes / health_log）| 30 min | 表结构 |
| 3.3 | 写 `core/models.py`（SQLAlchemy ORM + 加密字段）| 60 min | ORM 模型 |
| 3.4 | 写 `core/migrations/`（alembic 初始化 + 首次迁移）| 30 min | 迁移框架 |
| 3.5 | 写 `scripts/sync_imap.py`（增量同步到 SQLite）| 60 min | 同步入口 |
| 3.6 | **Spike**：1 万封邮件批量入库性能（目标 < 30s）| 30 min | 性能报告 |
| 3.7 | 写 `core/indexer.py`（FTS5 全文索引 + sqlite-vss 向量索引）| 60 min | 索引能力 |
| 3.8 | 写 `tests/core/test_db.py`（事务/加密/并发）| 30 min | 单元测试 |

**总耗时**：约 6 小时

### 验收标准

- [ ] 数据库文件存在 `~/Library/Application Support/我的AI员工/data.db`（加密）
- [ ] 1 万封邮件入库 < 30s
- [ ] FTS5 搜索 "SAP" 命中 < 100ms
- [ ] sqlite-vss 语义搜索"财务相关"命中 < 200ms
- [ ] WAL 模式开启（多读单写不阻塞）

### 风险点

- ~~**pysqlcipher3 安装**：Python 3.14 兼容性差~~ → **D1.1 已解决**：用 sqlcipher3（coleifer 维护，Python 3.12 wheel 齐全）+ `PRAGMA key` 加密
- **加密开销**：sqlcipher3 加密 PRAGMA key 校验 + AES-256 加密使入库慢 2-3x，需做性能 spike
- **首次 Keychain 凭证缺失**：D3 启动前用户需在 Keychain 写入 `my-ai-employee.db.password`（D2.3 keychain.py 提供 `set_db_password()` 助手）

### 📌 下一棒 → D4

- 数据层就绪
- 下棒需要：已入库的邮件（500+ 真实数据）
- 关键决策：minimax M3 是否要在 D4 同时接入？— 我建议**D4 直接用**，因为走 Claude Code SDK

---

## D4 — 智能层（邮件分类 + 草稿）

### 目标

邮件自动分类（5 类）+ 1-click 草稿生成，端到端可用。

### 任务清单

| # | 任务 | 预计耗时 | 产出 |
|---|------|----------|------|
| 4.1 | 写 `ai/classifier.py`（minimax M3 + 5 类标签）| 90 min | 分类服务 |
| 4.2 | 写 `ai/drafter.py`（minimax M3 + 历史回复模式）| 90 min | 草稿服务 |
| 4.3 | 写 `ai/prompts/classifier.txt`（中文 prompt + few-shot 5 例）| 30 min | 提示词 |
| 4.4 | 写 `ai/prompts/drafter.txt`（中文 prompt + 角色设定）| 30 min | 提示词 |
| 4.5 | 写 `scripts/classify_all.py`（批量分类 + 准确率统计）| 60 min | 评估脚本 |
| 4.6 | 写 `tests/ai/test_classifier.py`（500 封真实邮件标注）| 60 min | 单元测试 |
| 4.7 | **Spike**：100 封手标邮件做混淆矩阵 | 60 min | 准确率报告 |
| 4.8 | 写 `core/audit.py`（LLM 调用审计日志）| 30 min | 合规依据 |

**总耗时**：约 7 小时

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

### 📌 下一棒 → D5

- 智能层就绪
- 下棒需要：500 封已分类邮件作为 LLM 训练/评估数据
- 关键决策：是否在 D5 加 CalDAV 同步？— 我建议**必须加**（日程是用户高频）

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
