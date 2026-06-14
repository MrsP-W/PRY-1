# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **我的AI员工** — 全天候个人 AI 数字员工（与 Agent Assistant 兄弟项目，2026-06-12 落地 L4 Agent 层软链）
>
> 最后更新：2026-06-12（**L4 Agent 层软链 5 角色 + 2 专属 + D-step 收官标准动作**）
> 核心模型：MiniMax-M3 · 维护者：Mr-PRY

---

## 🚀 TL;DR — 30 秒读懂我的AI员工

**项目**：Agent Assistant 的"执行器"载体 — 把 10 角色从"晨晚链路半成品"升级为"全天候数字员工"。
**核心差异化**：**数据不出本机**（SQLCipher 加密）+ 与 Agent Assistant **无缝衔接**（Skill/角色复用）+ minimax M3 LLM 统一链路。
**当前阶段**：**D5 业务调度器推进中**（D5.1-D5.6.5 ✅，B3 真正解封，真实 1 封 SMTP 端到端实测通过，sent=1/1.27s；下一步 D5.7 docs 收口 8 件套剩余 + v0.1 发布规划）。

### 🎯 L4 Agent 层 7 角色（事实校验：src/my_ai_employee/agents/ 下 5 软链 + 2 专属）

| 触发词 | 角色类型 | 职责 | D-step 用法 |
|--------|---------|------|-------------|
| `@教练员` | 🔴 软链 | Claude Code 技巧沉淀 | D-step 收官 → 沉淀 1 条 |
| `@检查员` | 🔴 软链 | 质量门 + 8/8 质量检查 | D-step 收官前必跑 |
| `@调试专家` | 🔴 软链 | Bug 排查 + 链路诊断 | D-step 阻塞时 |
| `@回顾员` | 🔴 软链 | 复盘 + 团队评分 | D-step 锁定时 |
| `@内容编辑员` | 🔴 软链 | 排版/草稿/PPT | D4 邮件草稿 + 文档沉淀 |
| `@管家` | 🟡 专属 | 全天候数字员工视角 | D4.x/D5.x/D6+ 视角检查 |
| `@审计员` | 🟡 专属 | LLM/数据流/权限审计 | 涉及数据流 D-step 必配套 |

> **软链路径**：`src/my_ai_employee/agents/教练员.md` → `../../../../Agent Assistant/agents/教练员.md`（Agent Assistant 角色更新自动生效）。

---

## 📌 职责边界

> **CLAUDE.md 职责边界**：**避免与全局 `~/.claude/CLAUDE.md` 重复**。仅承载本项目独有信息。
>
> - **自动加载（全局）**：自动 compact 三件套、输出语言（中文）、记忆规则、What NOT to do → `~/.claude/CLAUDE.md`
> - **共用跳转（兄弟项目）**：10 角色清单、Skill 生态、共享模块、Step 模式 → `../Agent Assistant/CLAUDE.md`
> - **本项目独有（仅写在这里）**：L4 Agent 层软链架构、D-step 收官标准动作、SAP 知识库入口、邮件外发铁律、Tcode 速查

---

## 📌 D-step 标准落地流（5 步）

每个 D-step 落地按此流程（D5.6.4 修复 + D5.6.5 真实 1 封实测锁定时按此跑）：

```
Step 1: @调试专家（如有阻塞）
  ↓ 解锁
Step 2: 实施 + 跑 8/8 质量门（见下表）
  ↓ 通过
Step 3: @检查员 复核 8/8 质量门 + v1.0.x 收口
  ↓ 锁定
Step 4: @教练员 沉淀 1 条 Claude Code 技巧到 memory/（D-step 命名）
  ↓
Step 5: @回顾员 写复盘（v1.0.x 收口 + 下一版本预判）
  ↓
Step 6: 提交 commit + push
```

### ✅ 8/8 质量门（D4.7.3 v1.0.6 收口范本）

| # | 门 | 命令 |
|---|----|------|
| 1 | pytest | `make test`（全跑） / `uv run pytest tests/ -v` |
| 2 | ruff check | `uv run ruff check src/ tests/` |
| 3 | ruff format | `uv run ruff format src/ tests/ --check` |
| 4 | mypy src | `uv run mypy src/` |
| 5 | mypy src+tests | `uv run mypy src/ tests/` |
| 6 | alembic --sql | `uv run alembic upgrade head --sql`（exit 0 = DDL 无脏）|
| 7 | uv build | `uv build`（验证打包可发布）|
| 8 | MD lint | `make lint` / `npx markdownlint "**/*.md"` |

> **历史范本**：D4.7.3 v1.0.6 收官（6 轮 35+ fixes）就是这套 8 门全绿的完整实践。
>
> 🧬 **D4 智能层 D-step 必先参考** [docs/d4-claw-code-mapping.md](docs/d4-claw-code-mapping.md)（D4 自动参考规则：启动 D4 / D4.x / events / MCP / LLM 路由时先读对应子主题映射）

---

## 🌐 与 Agent Assistant 的边界（避免重复）

| 维度 | Agent Assistant | 我的AI员工（本项目）|
|------|----------------|-------------------|
| **时间维度** | 09:00 + 21:00 截点 | 全天候 + 主动 |
| **数据源** | 公开信息（新闻/SAP 知识）| 个人数据（邮件/日程/账本/笔记）|
| **存储** | Markdown 文档 | SQLite 加密（SQLCipher）|
| **接口** | 文档产出 | 菜单栏 + Web Dashboard + 移动伴侣 |
| **隐私** | 公开 | **本地优先**（sqlcipher3）|
| **复用** | 提供 10 角色 + 5 共享模块 | **L4 软链 + 委派** |

> **互不重复原则**：本项目 L4 角色软链 Agent Assistant 即可，**不**重新写 system prompt。

---

## 🏗️ 5 层架构（src/my_ai_employee/）

| 层 | 目录 | 职责 | 状态 |
|----|------|------|------|
| **L1 适配器** | `connectors/` | IMAP / CalDAV / 账单 / Notes | D3 ✅ |
| **L2 数据** | `core/` | SQLite / schema / models / migrations | D3.1-D3.2 ✅ |
| **L3 智能** | `ai/` | 分类 / 草稿 / 财务 / 笔记 | D4 ✅（D4.7.3 v1.0.6）|
| **L4 Agent** | `agents/` | 7 角色（5 软链 + 2 专属）| **6/12 刚落地** |
| **L5 UI** | `menu_bar/` | Mac 菜单栏 + Web Dashboard | D5+ 推进中 |

---

## 🌐 SAP 知识库（兄弟项目）

**SAP 运维项目**：`/Users/wei/Documents/DesktopOrganizer/SAP运维项目/`

- `04-常见问题/错误代码索引.md` · `04-常见问题/诊断流程.md` · `02-日常运维/README.md`

### 常用 Tcode 速查（D5+ 业务集成时）

| 场景 | Tcode |
| ---- | ---- |
| 修改开户行 | `FI12` / `FI12_HBANK` |
| 银行主数据 | `FD01/FD02/FD03` |
| 会计凭证过账 | `FB01/F-28/FB60` |

---

## 🚨 铁律（不写会出事）

### 邮件外发（2026-06-11 修订）

> D5 业务调度器解封"邮件发送"，1-click 草稿可走 SMTP 真实发送（用户 1-click 审批后），**仍保留"不抢控制权"原则** — 自动发送必须有用户预先确认过的草稿。

- ❌ **不抢控制权** — 草稿生成走两阶段：① AI 生成 → outbox 库 → 1-click 审批 ② 用户审批后 D5 SMTP 真实发送
- ❌ **不联网外传** — 敏感数据（身份证/银行卡/私密笔记）走本地规则
- ❌ **不收费 SaaS** — 这是用户的工具，不是订阅服务

### 审计留痕（@审计员 红线）

- ⚠️ LLM 调用超 5000ms latency（@内容编辑员 草稿延迟）
- ⚠️ 同一邮箱 1 小时内 > 10 封草稿（防 spam 误发）
- ⚠️ SMTP 发送失败 > 3 次（触发 D5.5 退避重试 + 人工介入）
- ⚠️ 任何敏感数据尝试外发（D8+ 隐私规则）

### D-step 命名约定

- `D<大版本>.<中版本>.<小版本>` — 例 D4.7.3 = 第 4 大版本第 7 中版本第 3 小版本
- 锁定 v1.0.x 收口 → commit `9e4fb2e` 模式（D4.7.3 v1.0.6 范本）

### D-step 收官报告归档

每个 D-step 收官报告写在 `reports/D<版本>-<模块>.md`：

- 范本：`reports/D4.7-草稿生成器.md` · `reports/D4.8-草稿入库.md` · `reports/D4.6-邮件分类器.md`
- 截至 6/12 共 **18 个报告**（D4.x 收口沉淀）
- 跨 D-step 关联收口写到 `memory/d4.x-...-fixes.md`（如 `memory/d4.6-v1.0.2-fixes.md` 模式）

---

## 🛠️ 关键命令（[Makefile](Makefile) 是真理源，`make help` 全量）

| 命令 | 用途 | 频率 |
|------|------|------|
| `make help` | 查看所有命令 | 🟢 |
| `make hello` | 主入口冒烟测试 | 🟢 启动时 |
| `make dev` | 开发模式（hot reload） | 🟢 |
| `make info` | 显示项目信息 | 🟢 |
| `make test` | 跑 pytest 单元测试 | 🔴 每次 D-step |
| `make test-verbose` | 详细输出（-v）| 🟡 调试时 |
| `make lint` | Markdown 格式检查 | 🔴 每次 D-step |
| `make lint-fix` | 自动修复 MD 格式 | 🟡 收官前 |
| `make typecheck` | mypy 严格模式 | 🔴 每次 D-step |
| `make venv` | 建本地 venv（Python 3.12 + uv）| 🟢 首次 |
| `make install` | 装依赖（`uv sync --extra dev`）| 🟢 首次 |
| `make install-npm` | 装 npm 依赖（markdownlint-cli2）| 🟢 首次 |
| `make install-hooks` | 装 pre-commit hook | 🟢 首次 |
| `make clean` | 清理临时文件 | 🟢 |

### 🎯 单跑测试（高频）

```bash
# 跑单个文件
uv run pytest tests/ai/test_drafter_adapter.py -v

# 跑单个测试函数
uv run pytest tests/ai/test_drafter_adapter.py::TestD473V106Fixes -v

# 按关键字匹配
uv run pytest -k "spam_reply" -v

# 跑某个目录
uv run pytest tests/ai/ -v
```

> D4.7.3 v1.0.6 收官时 `102 passed` 就是用这套单跑范式迭代的。

---

## 📚 相关必读

1. [README.md](README.md) — 一句话定位 + 边界表 + 目录结构
2. [docs/architecture.md](docs/architecture.md) — 5 层架构详解
3. [docs/week1-mvp.md](docs/week1-mvp.md) — D1-D3.x 范围
4. [docs/week2-mvp.md](docs/week2-mvp.md) — D4-D6.x 范围
5. [docs/d4-claw-code-mapping.md](docs/d4-claw-code-mapping.md) — **D4 智能层必读参考源**
6. [docs/spike-imap-compat.md](docs/spike-imap-compat.md) — IMAP 真实 spike（D2 收口沉淀）
7. [../Agent Assistant/CLAUDE.md](../Agent%20Assistant/CLAUDE.md) — 兄弟项目主入口
8. [~/.claude/CLAUDE.md](~/.claude/CLAUDE.md) — 全局规则（自动 compact / 中文输出 / 记忆规则）

### 📊 文档矩阵（按使用频率）

| 文档 | 何时读 |
|------|--------|
| `README.md` | 首次进入项目 |
| `CLAUDE.md`（本文件） | 每次会话开始 |
| `docs/architecture.md` | 改架构 / D-step 跨越 L1-L5 |
| `docs/week1-mvp.md` / `week2-mvp.md` | 规划 D-step |
| `docs/d4-claw-code-mapping.md` | D4 智能层 D-step 必读 |
| `docs/spike-imap-compat.md` | 改 IMAP / 同步逻辑时 |
| `reports/D*.md` | 看 D-step 收官历史范本 |

---

**最后更新**：2026-06-12（L4 Agent 层落地 + D-step 收官标准动作）
**当前模型**：MiniMax-M3 (Custom Opus)
**维护者**：Mr-PRY
