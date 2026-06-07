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
| pysqlcipher3 在 Python 3.14 安装失败 | 高 | 数据库全废 | D3 末 spike；不通过则降级到 Python 3.12 |
| IMAP OAuth 2.0 复杂度 | 高 | 主流邮箱全卡 | D2 末做 QQ/Outlook/Gmail 三源 spike |
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

### 任务清单

| # | 任务 | 状态 | 产出 |
|---|------|------|------|
| 1.1 | `git init` + 初始 commit | ⏳ 待 git | git 仓库 |
| 1.2 | 写 `pyproject.toml`（Python 3.11+ / poetry 依赖）| ✅ | 项目元数据 |
| 1.3 | 写 `Makefile`（help/hello/dev/test/lint/run/clean/lock/info）| ✅ | 命令入口 |
| 1.4 | 写 `.gitignore`（data/、.env、`__pycache__/`、*.db）| ✅ | 忽略规则 |
| 1.5 | 写 `README.md`（快速开始 + 5 个 Day 0 决策）| ✅ | 入口文档 |
| 1.6 | 写 `.markdownlint.json`（复用 Agent Assistant 配置）| ✅ | 文档规范 |
| 1.7 | 创建 `src/` 目录树（connectors/core/ai/agents/menu_bar）| ✅ | 目录结构 |
| 1.8 | 写 `src/main.py` 打印 "Hello, 我的AI员工"（rich 缺失降级）| ✅ | 可运行入口 |
| 1.9 | 写 `.env.example`（所有需要的环境变量模板）| ✅ | 配置模板 |
| 1.10 | 验证 `make hello` 跑通 + `make lint` 0 错误 | ✅ | 验收 |

**总耗时**：约 1.5 小时（不含 brew install poetry 等待）

### 验收标准

- [x] `python -m src.main` 输出 "Hello, 我的AI员工" 退出码 0
- [x] `make lint` 0 错误（基于 `.markdownlint.json`）
- [x] 目录结构与 [architecture.md §1](architecture.md#1-5-层架构总览) 一致
- [x] main.py 在 rich 缺失时**降级到原生 print**（应急版范本）
- [x] 命令统一用 `python -m src.main`（避免 main.py 冲突）
- [ ] `poetry install` 跑通（**待 brew 装好 poetry 后**）
- [ ] 初始 git commit 干净（无 `__pycache__`、`.env`）

### 关键决策与发现

1. **降级模式**（应急版范本 L3）— `main.py` 检测 `rich` 是否安装，缺失时用纯文本输出
2. **命令模式** — `python -m src.main` 而非 `python src/main.py`（避免 main.py 冲突）
3. **环境** — Python 3.14.4 已装，pip3 受 PEP 668 限制，**需 poetry**（brew 安装中）
4. **依赖锁定** — 全部依赖在 `pyproject.toml`，poetry.lock 首次 install 后生成

### 📌 下一棒 → D2

- 项目骨架已立（含降级模式）
- 下棒需要：邮箱源 + 凭证（QQ 邮箱优先，spike 验证 OAuth 2.0）
- 关键决策：是否需要在 D2 同步把邮件入库？— 我建议**分批入库**（避免 SQLite 锁）

---

## D2 — IMAP 适配器

### 目标

通用 IMAP 连接器，支持 QQ / Outlook / Gmail（OAuth 2.0 + 密码双模式）。

### 任务清单

| # | 任务 | 预计耗时 | 产出 |
|---|------|----------|------|
| 2.1 | 写 `connectors/base.py`（抽象基类 + safe_fetch 失败隔离）| 30 min | 接口契约 |
| 2.2 | 写 `connectors/imap.py`（imapclient + OAuth + 密码双模式）| 90 min | IMAP 适配器 |
| 2.3 | 写 `scripts/test_imap.py` CLI（连任意邮箱测试）| 30 min | 测试入口 |
| 2.4 | 写 OAuth 2.0 凭证获取向导（首次运行引导）| 60 min | 用户引导 |
| 2.5 | **Spike**：QQ / Outlook / Gmail 三源连通性测试 | 60 min | 兼容性报告 |
| 2.6 | 写 `tests/connectors/test_imap.py`（pytest，含 mock IMAP server）| 30 min | 单元测试 |
| 2.7 | 写健康检查 `connectors/imap.py::healthcheck()` | 15 min | 熔断依据 |

**总耗时**：约 5 小时

### 验收标准

- [ ] `python scripts/test_imap.py` 能连 QQ 邮箱
- [ ] `python scripts/test_imap.py` 能连 Outlook
- [ ] `python scripts/test_imap.py` 能连 Gmail
- [ ] 单元测试覆盖率 ≥ 70%
- [ ] OAuth 凭证存在 Keychain（不落盘 .env）
- [ ] 失败时进入熔断（30 min 后再试）

### 风险点

- **OAuth 2.0 复杂度**：Gmail 用 XOAUTH2 / Outlook 用 XOAUTH2 + AAD / QQ 用授权码
- **mitm 风险**：imapclient 默认 `verify=True`，但 macOS 证书链有时不完整

### Spike 输出（必备）

写 `docs/spike-imap-compat.md` 记录：

- 3 个邮箱连通性结果
- OAuth 流程截图
- 凭证存储位置
- 已知限制

### 📌 下一棒 → D3

- IMAP 适配器已就绪
- 下棒需要：邮箱源 + 凭证（在 Keychain）
- 关键决策：是否需要在 D3 同步把邮件入库？— 我建议**分批入库**（避免 SQLite 锁）

---

## D3 — 数据层 + IMAP 同步

### 目标

SQLite 加密 schema + IMAP 邮件入库 + 检索能力。

### 任务清单

| # | 任务 | 预计耗时 | 产出 |
|---|------|----------|------|
| 3.1 | 写 `core/db.py`（pysqlcipher3 封装 + 密码从 Keychain 取）| 60 min | 数据库连接 |
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

- **pysqlcipher3 安装**：Python 3.14 兼容性差，**降级方案**：用 Python 3.12 venv
- **加密开销**：首次批量入库可能慢 2-3x，需做性能 spike

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
