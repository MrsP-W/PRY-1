# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **我的AI员工** — 全天候个人 AI 数字员工（与 Agent Assistant 兄弟项目，2026-06-12 落地 L4 Agent 层软链）
>
> 最后更新:2026-07-02(**Day 10 Phase 2 — `count_by_needs_confirm` SQL COUNT(*) 优化 ✅**(2026-07-02 · `NoteStore.count_by_needs_confirm` + `NoteConfirmServiceImpl` 改调 count · `tests/db/test_notes_l2_cross_source.py` +2) · Phase 1.2 fallback/Dashboard/菜单栏解密 ✅(沿用) · Phase 1.1 Keychain 接线 ✅(沿用) · 9 质量门 **2790 passed / 2 skipped / 89.11%** / **244 MD** / mypy **248 files** · **`ENABLE_NOTES_ENCRYPTION=1` 不写 shell profile · Notes 真加密生产仍不开**))
> 核心模型：MiniMax-M3 · 维护者：Mr-PRY

---

## 🚀 TL;DR — 30 秒读懂我的AI员工

**项目**：Agent Assistant 的"执行器"载体 — 把 10 角色从"晨晚链路半成品"升级为"全天候数字员工"。
**核心差异化**：**数据不出本机**（SQLCipher 加密）+ 与 Agent Assistant **无缝衔接**（Skill/角色复用）+ minimax M3 LLM 统一链路。
**当前阶段**：**Day 10 Phase 2 — `count_by_needs_confirm` SQL COUNT(*) 优化 ✅**(2026-07-02 · 菜单栏/Dashboard 待确认计数改 SQL COUNT(*) · `tests/db/test_notes_l2_cross_source.py` +2) · Phase 1.2 解密集成 ✅(沿用) · Phase 1.1 Keychain 接线 ✅(沿用) · 9/9 质量门 **2790 passed / 2 skipped / 89.11%** / **244 MD** / mypy **248 files** · **`ENABLE_NOTES_ENCRYPTION=1` 不写 shell profile · Notes 真加密生产仍不开**。

### 🎯 L4 Agent 层 7 角色（事实校验：src/my_ai_employee/agents/ 下 7 普通文件,沿 D5.5.3 P0 修复软链 → 实际文件复制）

| 触发词 | 角色类型 | 职责 | D-step 用法 |
|--------|---------|------|-------------|
| `@教练员` | 📄 普通 | Claude Code 技巧沉淀 | D-step 收官 → 沉淀 1 条 |
| `@检查员` | 📄 普通 | 质量门 + 9/9 质量检查 | D-step 收官前必跑 |
| `@调试专家` | 📄 普通 | Bug 排查 + 链路诊断 | D-step 阻塞时 |
| `@回顾员` | 📄 普通 | 复盘 + 团队评分 | D-step 锁定时 |
| `@内容编辑员` | 📄 普通 | 排版/草稿/PPT | D4 邮件草稿 + 文档沉淀 |
| `@管家` | 🟡 专属 | 全天候数字员工视角 | D4.x/D5.x/D6+ 视角检查 |
| `@审计员` | 🟡 专属 | LLM/数据流/权限审计 | 涉及数据流 D-step 必配套 |

> **D5.5.3 P0 修复(2026-06-12)**：所有角色文件从软链 → 实际文件复制(5 软链 1903 行 uv build OK + 14 files commits `7e9bca0`),防 uv build FileNotFoundError。**沿用测试**:`tests/agents/test_agent_layer.py::test_no_legacy_symlinks_in_agents_dir` 断言 agents/*.md 不是软链。**不要重建软链**(2026-06-23 撞坑 #34 误判修复方向已回滚)。

---

## 📌 职责边界

> **CLAUDE.md 职责边界**：**避免与全局 `~/.claude/CLAUDE.md` 重复**。仅承载本项目独有信息。
>
> - **自动加载（全局）**：自动 compact 三件套、输出语言（中文）、记忆规则、What NOT to do → `~/.claude/CLAUDE.md`
> - **共用跳转（兄弟项目）**：10 角色清单、Skill 生态、共享模块、Step 模式 → `../Agent Assistant/CLAUDE.md`
> - **本项目独有（仅写在这里）**：L4 Agent 层软链架构、D-step 收官标准动作、SAP 知识库入口、邮件外发铁律、Tcode 速查

---

## 📌 D-step 标准落地流（5 步）

每个 D-step 落地按此流程（D5.6.4 修复 + D5.6.5 真实 1 封实测 + D5.6.5.1 检查员驳回 5 缺陷修复 + D5.7 docs 收口 8 件套 + D5.7.1 检查员驳回 5 缺陷修复真正锁定 + **D5.7.2 docs 收口最后一致性修正 真正锁定**时按此跑）：

```
Step 1: @调试专家（如有阻塞）
  ↓ 解锁
Step 2: 实施 + 跑 9/9 质量门（见下表）
  ↓ 通过
Step 3: @检查员 复核 9/9 质量门 + v1.0.x 收口
  ↓ 锁定
Step 4: @教练员 沉淀 1 条 Claude Code 技巧到 memory/（D-step 命名）
  ↓
Step 5: @回顾员 写复盘（v1.0.x 收口 + 下一版本预判）
  ↓
Step 6: 提交 commit + push
```

### ✅ 9/9 质量门（D4.7.3 v1.0.6 收口范本 · Makefile `ci` 串跑）

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
| 9 | coverage | `make coverage`（fail_under=80 通过）|

> **历史范本**：D4.7.3 v1.0.6 收官（6 轮 35+ fixes）就是这套 9 门全绿的完整实践。
>
> 🧬 **D4 智能层 D-step 必先参考** [docs/d4-claw-code-mapping.md](docs/d4-claw-code-mapping.md)（D4 自动参考规则：启动 D4 / D4.x / events / MCP / LLM 路由时先读对应子主题映射）
>
> ⚠️ **mypy 门盲区 + 撞坑 #31 已知技术债**(2026-06-23 检查报告第二轮沉淀 · 7/1 月度复盘 review):
>
> - `make mypy` = `mypy src tests` 联跑 → **0 errors**(宽松版 — 当前门)
> - `uv run mypy tests/` 单独跑 → **0 errors**(2026-07-01 Day 7 前修复 · 历史 14 errors 撞坑 #31)
> - 历史 14 errors 全是 `[no-any-return]`,SQLAlchemy `store.insert().id` 类型推断为 `Any`,helper 声明返回 `int`/`bool` 触发 · 沿 v0.2.23 `cast(int, ...)` 范本已修复

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

### 📝 修改总结必写（MODIFICATION-LOG · 2026-06-18 用户指令）

> **每次修改完成后必须写 1 条 3 段总结**到 [`MODIFICATION-LOG.md`](MODIFICATION-LOG.md)（项目根目录，沿 SESSION-STATE.md 范本）。

**3 段固定结构**（缺一段 = 链路断点）：

1. **本次修改内容** — 关键 commit hash + 主题 + 改动范围（行数/files/tests）+ 链接到 reports/ 详细报告
2. **风险点** — 已知风险 + 触发条件 + 影响范围 + B 类延后 + P1/P2/P3 待办
3. **当前项目整体总结** — 进度数字（pytest / 8 质量门 / tag / 累计 commits）+ 下一步 + 下一棒

**触发条件**（5 类必写，其余不写避免噪音）：

| # | 触发 | 谁来写 |
|---|------|--------|
| 1 | D-step 实施 + commit 后 | 主 Agent |
| 2 | v0.2.x 启动候选收口 | 主 Agent |
| 3 | 关键修复（bug fix / 重构 / 阻塞解除） | @调试专家 / 主 Agent |
| 4 | 文档重大更新（launch plan / closure / week1-2 修订） | @内容编辑员 / 主 Agent |
| 5 | B 类决策激活（用户明确同意后） | 主 Agent |

**与 SESSION-STATE.md 分工**：

- `SESSION-STATE.md` = 状态导向（现在在哪）
- `MODIFICATION-LOG.md` = 变更导向（怎么走过来的 + 路上有什么坑）

**节 token 目标**：后续 AI 只读 `CLAUDE.md` + `SESSION-STATE.md` + `MODIFICATION-LOG.md` 即可掌握完整历史 + 当前状态 + 风险点，无需重读全部 reports/*.md（预计减少 70-80% token）。

**维护规则**：单条 ≤ 50 行 / 不复制代码片段 / 不重复 reports/ 详细报告 / 每月 1 号 12:00+ 检查员清理 > 1 个月旧记录到 `archive/MODIFICATION-LOG-YYYY-MM.md`。

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
| `make mypy` | mypy 严格模式（`mypy src tests` 联跑）| 🔴 每次 D-step |
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
