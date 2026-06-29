# 7/1 月度复盘议程 3 + 29 + 30 · loop 范式 + 撞坑 #69/#70 SOP 预制(2026-06-29)

> **目的**:7/1 13:00-13:30 议程 3(7 个 Agent loop 范式批量补齐)+ 议程 29(撞坑 #69 SOP)+ 议程 30(撞坑 #70 SOP)提供 docs-only 预制骨架
> **范围**:7 个待补齐 Agent 的 loop 范式骨架 + 撞坑 #69/#70 SOP 草案
> **沿用**:全局 skill `agent-loop-patterns`(@~/.claude/skills/agent-loop-patterns/SKILL.md · 4 类范式 + 10 Agent 映射)+ v0.2.53.37 §3 主题 3 表格
> **撞坑累计**:**70 类沿用**(本棒无新增)
> **风险门控**:**docs-only 不动业务代码 / 不写 handler / 不接真实数据**

---

## 1. 7 个待补齐 Agent loop 范式骨架(议程 3 · 13:00-13:30)

> **背景**:Agent Assistant 项目当前 10 个 Agent 中 **3 个已标注**(内容编辑员 6/22 / 调试专家 + 舆情监测员 6/25 commit `ac6021b`),**7 个待补齐**(信息员/日报员/教练员/检查员/SAP顾问/回顾员/安全审计员)
> **沿用**:skill `agent-loop-patterns` 4 类范式 = ReAct / Reflection / Plan-Execute / Verifier-Generator + Workflow 编排
> **7/1 补齐方案**:每个 Agent 在 `agents/<name>.md` 末尾加 1 段 loop 范式标注(沿 6/25 commit `ac6021b` 范本)

### 1.1 信息员(议程 10 · 待补齐)

| 维度 | 选型 | 沿用依据 |
|------|------|----------|
| **loop 范式** | **Plan-Execute** | 应急版 v1.9 连续 13 次 + 多数据源(WebSearch 5 源 / `gh api` 旁路)|
| **max_iterations** | **15** | WebSearch 多源轮询 + 5 类降级路径需要高迭代预算 |
| **关键标注** | 应急版兜底(撞坑 #59 + 工具降级范本)| 工具故障时降级到 proxy → env → healthcheck 重探 → 备选抓取 |
| **执行流程** | Step 0 链路导航 → Step 1 数据源选择 → Step 2 多源轮询 → Step 3 dedup → Step 3.5 时间窗口 7 天 → Step 4 文档输出 → Step 5 下一棒 | 沿 `agents/信息员.md` 既有 6 步 |
| **失败模式** | WebSearch 401 × 10 次 → 启动自主修复循环(沿 2026-06-29 废止应急版政策)| 撞坑 #59 范本 |
| **测试覆盖** | spike 验证 + 实战 130+ 主题(沿 `news_dedup.md`)| docs-only 不增加测试 |

### 1.2 日报员(议程 11 · 待补齐 · B2 #1 单独)

| 维度 | 选型 | 沿用依据 |
|------|------|----------|
| **loop 范式** | **ReAct** + **Reflection** 混合 | 标准链路 09:35(每日定时)+ 4 级降级标注(撞坑 #5 v2)|
| **max_iterations** | **3** | Reminders 创建 + 4 级降级 + 主动提醒链路 |
| **关键标注** | 4 级降级(osascript 通知中心 → terminal-notifier → 桌面快捷方式 → 日程表顶部文字兜底 · 2026-06-24)| 撞坑 #5 + 撞坑 #TCC-2026-06-22 |
| **执行流程** | Step 1 Reminders 去重(查询当天)→ Step 2 创建提醒 → Step 2.5 主动提醒 4 级降级 → Step 3 日程表生成 → Step 4 下一棒 | 沿 `agents/日报员.md` 既有 4 步 |
| **失败模式** | AppleScript TCC 阻断 → 自动降级到 osascript 系统级 | 撞坑 #5 v2 范本 |
| **测试覆盖** | 6/24 实战验证全链路 OK + AppleScript 4 坑沉淀 | docs-only |

### 1.3 教练员(议程 12 · 待补齐)

| 维度 | 选型 | 沿用依据 |
|------|------|----------|
| **loop 范式** | **Reflection** | 独立运行连续 13 次 + 1+2 模式(1 步核心 + 2 步检查)|
| **max_iterations** | **5** | 1 步生成 + 2 步反思 + 2 步纠偏足够 |
| **关键标注** | 1+2 模式 = 1 个核心 prompt + 2 次反思迭代 | 沿 `agents/教练员.md` 决策方法论 7 版本演进 |
| **执行流程** | Step 1 提取核心优化项 → Step 2 反思 1 → Step 3 反思 2 → Step 4 合并 → Step 5 下一棒 | 沿 `agents/教练员.md` 既有流程 |
| **失败模式** | 反思重复 → max_iterations=5 强制收敛 | 撞坑 #dec-7 范本 |
| **测试覆盖** | 6/16-6/25 实战 13 天 100% 独立运行 | docs-only |

### 1.4 检查员(议程 13 · 待补齐)

| 维度 | 选型 | 沿用依据 |
|------|------|----------|
| **loop 范式** | **Plan-Execute** (P2 范式) | P2 范式 100% PASS + 4 模板 |
| **max_iterations** | **9** | 9 质量门 + 12:00 强制截点 + Step 1.A/1.B/1.C/1.D 4 阶段 |
| **关键标注** | Plan-Execute + 12:00 强制截点 + 链路不完整也必须出报告 | 沿 `agents/检查员.md` 既有 P2 范式 |
| **执行流程** | Step 0 链路导航 → Step 1.A 收口检查 → Step 1.B 应急版检查 → Step 1.C output 7 天清理 → Step 1.D 月度合并 → Step 2 9 质量门 → Step 3 检查报告 → Step 4 下一棒 | 沿 `agents/检查员.md` 既有 7 步 |
| **失败模式** | 链路断点 → 强制生成报告 + 标注缺失项(不得延迟)| 撞坑 #trouble-12 范本 |
| **测试覆盖** | 6/15-6/25 实战 11 天 P2 范式 100% PASS | docs-only |

### 1.5 SAP 顾问(议程 14 · 待补齐)

| 维度 | 选型 | 沿用依据 |
|------|------|----------|
| **loop 范式** | **Plan-Execute** + **分支决策** | 端午回归 + FI/CO/Basis 分支标注 |
| **max_iterations** | **12** | FI/CO/Basis 3 模块分支 + 错误代码索引 + 4 重防误发 |
| **关键标注** | FI/CO/Basis 分支决策 + 4 重防误发 | 沿 `agents/SAP顾问.md` 既有 3 模块 |
| **执行流程** | Step 0 链路导航 → Step 1 模块识别(FI/CO/Basis)→ Step 2 错误代码索引 → Step 3 4 重防误发 → Step 4 凭证流 → Step 5 SAP 运维记录 → Step 6 下一棒 | 沿 `agents/SAP顾问.md` 既有 6 步 |
| **失败模式** | 错误码未索引 → 自动降级到诊断流程 | 撞坑 #FI/SAP-2026 范本 |
| **测试覆盖** | 6/8-6/25 实战 18 天(沿端午连休)+ skill `sap-fico-consultant` | docs-only |

### 1.6 回顾员(议程 15 · 待补齐)

| 维度 | 选型 | 沿用依据 |
|------|------|----------|
| **loop 范式** | **Reflection** | 沿 6/22-6/24 范本 + 5 分钟处置法 |
| **max_iterations** | **8** | 决策点跨日积压 5 分钟处置法 v1.0 |
| **关键标注** | 5 分钟处置法 = 决策点积压 5 分钟内必须处置 | 沿 `agents/回顾员.md` 既有 5 分钟法 |
| **执行流程** | Step 1 决策点识别 → Step 2 5 分钟处置(若超时升级)→ Step 3 复盘报告 → Step 4 撞坑累积 → Step 5 下一棒 | 沿 `agents/回顾员.md` 既有 5 步 |
| **失败模式** | 决策点积压 >5 分钟 → 升级到 B 类(月度复盘评估)| 撞坑 #retro-2026 范本 |
| **测试覆盖** | 6/22-6/24 范本 + 6/25 决策方法论第 11/12 版候选 | docs-only |

### 1.7 安全审计员(议程 17 · 待补齐)

| 维度 | 选型 | 沿用依据 |
|------|------|----------|
| **loop 范式** | **Verifier-Generator** | 沿 6/24 范本 + Verifier-Generator 范式 |
| **max_iterations** | **5** | 5 维度安全审计(认证 / 授权 / 输入验证 / 输出过滤 / 凭据存储)|
| **关键标注** | 5 维度审计 + Verifier-Generator 范式 | 沿 `agents/安全审计员.md` 既有 5 维度 |
| **执行流程** | Step 1 5 维度生成检查清单 → Step 2 Verifier 验证 → Step 3 修复建议 → Step 4 复测 → Step 5 安全审计报告 → Step 6 下一棒 | 沿 `agents/安全审计员.md` 既有 6 步 |
| **失败模式** | 5 维度任一未通过 → 强制修复 + 复测 | 撞坑 #sec-audit-2026 范本 |
| **测试覆盖** | 6/24 范本 + 7/1 评估后扩展 | docs-only |

### 1.8 已标注 3/10 状态(无需补齐)

| # | Agent | 标注状态 | commit |
|---|-------|----------|--------|
| 16 | 内容编辑员 | ✅ 已标注(6/22 落地)| `ac6021b` 之前 |
| 18 | 调试专家 | ✅ 已标注(6/25 落地)| `ac6021b` |
| 19 | 舆情监测员 | ✅ 已标注(6/25 落地)| `ac6021b` |

**7/1 补齐后预期 10/10(100%)沿用 `agent-loop-patterns` skill 4 类范式**。

### 1.9 7/1 补齐 commit 模板

```bash
# 单个 Agent 补齐 commit(7 个分批 commit 或 1 个聚合 commit)
git add agents/信息员.md agents/日报员.md agents/教练员.md agents/检查员.md agents/SAP顾问.md agents/回顾员.md agents/安全审计员.md
git commit -m "docs(agents): 7 个 Agent loop 范式补齐(信息员/日报员/教练员/检查员/SAP顾问/回顾员/安全审计员 + max_iterations 标注)(7 files +X/-Y)"
```

---

## 2. 撞坑 #69 衍生 SOP(议程 29 · 未来 mypy 严格模式升级)

> **撞坑 #69 起源**:v0.2.53.40 `readlines + writelines` 脚本批量删 `# type: ignore`,误删负向类型测试的精准 `# type: ignore[arg-type]` → 真实 mypy errors 306 → 撞坑累计 +1
> **根因**:`# type: ignore[...]` 注释与代码逻辑紧耦合,批量脚本无法区分"废弃 vs 必要"
> **影响范围**:mypy 严格模式升级(v0.2.40 锁死 `disallow_untyped_defs = true` · v0.2.41 锁死 `--strict`)后所有 type: ignore 注释

### 2.1 SOP 步骤(未来 mypy 严格模式升级时)

| 步骤 | 动作 | 工具 |
|------|------|------|
| **1. 备份 type: ignore 注释清单** | `git grep -n "# type: ignore" src tests > type-ignore-backup-$(date +%Y-%m-%d).txt` | git + grep |
| **2. 分类** | 按 [arg-type] / [union-attr] / [misc] / [return-value] / [assignment] 等 11 类分类(沿 v0.2.53.41 §1.1)| 手工 + 脚本 |
| **3. 验证每个 type: ignore 的必要性** | 每个 type: ignore 注释对应一个 mypy error 编号(沿 v0.2.53.40 撞坑 #69) | mypy --strict |
| **4. 删废弃 type: ignore** | 只删 v0.2.53.41 已修复的 type: ignore(冗余 + unused)| 沿 v0.2.53.40 + v0.2.53.41 修复记录 |
| **5. 改写必要的 type: ignore** | 改用 type stub / Protocol / cast 等更精确表达(沿 v0.2.23 cast 范本)| mypy 严格模式 |
| **6. 验证** | `mypy --strict src tests` 必须 0 errors,且 type: ignore 数量下降 | mypy |
| **7. docs-only 收口** | 写入 `docs/v0.2.X.Y-type-ignore-cleanup.md` + `quality_snapshot.py` L20 claim 同步 | docs-only |

### 2.2 撞坑 #69 预防 checklist(下次升级时)

- [ ] type: ignore 注释备份清单
- [ ] 每个 type: ignore 对应错误编号
- [ ] 批量脚本不直接删除 type: ignore(改用 mypy 输出验证)
- [ ] 修改后 mypy --strict 0 errors 验证
- [ ] docs-only 收口 + `quality_snapshot.py` 同步

### 2.3 沿用边界

- ❌ 不批量删除 type: ignore(撞坑 #69 根因)
- ❌ 不跳过负向类型测试(撞坑 #69 误删原因)
- ❌ 不前进 mypy 严格模式到 mypy 0.9xx(等社区稳定)
- ✅ docs-only SOP 落地(本棒)

---

## 3. 撞坑 #70 衍生 SOP(议程 30 · 中文注释 + type:ignore 同行)

> **撞坑 #70 起源**:v0.2.53.41 hotfix 期间,中文注释 + `# type: ignore[...]` 同一行时,mypy 不识别 type:ignore(必须 `# type:ignore[...]` 注释位于行尾或单独行)
> **根因**:中文注释通常 `# 这是 XXX` 开头,接 `# type: ignore[arg-type]` 后 mypy 解析失败
> **影响范围**:tests/ 58 files 中 8 files 有 type:ignore 与中文注释同行

### 3.1 SOP 步骤(未来 type: ignore 注释时)

| 步骤 | 动作 |
|------|------|
| **1. 中文注释独立行** | 中文注释必须独立成行,不与 type: ignore 同行 |
| **2. type: ignore 行尾规则** | type: ignore 必须位于行尾或单独行 |
| **3. 验证** | `mypy --strict src tests` 必须识别所有 type: ignore |
| **4. docs-only 收口** | 写入 type: ignore 注释规范到 CONTRIBUTING.md 或 `docs/v0.2.X.Y-type-ignore-rule.md` |

### 3.2 撞坑 #70 预防 checklist(每次新增 type: ignore 时)

- [ ] 中文注释独立行(不与 type: ignore 同行)
- [ ] type: ignore 位于行尾或单独行
- [ ] mypy --strict 验证识别
- [ ] v0.2.53.41 hotfix 8 files 检查(沿 `0d21b50` 修复)

### 3.3 沿用边界

- ❌ 不在中文注释同行加 type: ignore(撞坑 #70 根因)
- ❌ 不在 type: ignore 同行加其他注释
- ✅ docs-only SOP 落地(本棒)

---

## 4. 7/1 议程 3 + 29 + 30 执行清单(13:00-13:30 · 30 min)

### 4.1 议程 3(13:00-13:20 · 20 min)

| 动作 | 预估 | 产出 |
|------|------|------|
| 7 个 Agent loop 范式补齐 commit | 10 min | 1 个聚合 commit(7 files)|
| 沿用 `agent-loop-patterns` skill 4 类范式 | — | docs-only |
| 撞坑 #60 沿用(max_iterations 标注) | — | docs-only |

### 4.2 议程 29(13:20-13:25 · 5 min)

| 动作 | 预估 | 产出 |
|------|------|------|
| 撞坑 #69 SOP commit | 3 min | `docs/v0.2.X.Y-type-ignore-sop.md`(本棒预制骨架)|
| `memory/_tool/type-ignore-sop.md` 索引同步 | 2 min | docs-only |

### 4.3 议程 30(13:25-13:30 · 5 min)

| 动作 | 预估 | 产出 |
|------|------|------|
| 撞坑 #70 SOP commit | 3 min | `docs/v0.2.X.Y-type-ignore-rule.md`(本棒预制骨架)|
| CONTRIBUTING.md type: ignore 规则段 | 2 min | docs-only |

### 4.4 总耗时 30 min,产出 3 commits(7 files 改 + 2 docs 新增)

---

## 5. 沿用边界(本棒预制严格遵守)

- ❌ 不写业务代码 / handler / 业务逻辑
- ❌ 不接真实数据 / 不跑 spike / 不创建 0016 alembic migration
- ❌ 不打 `v0.2.x` tag / 不动 `v0.1.0` tag
- ❌ 不前进 `quality_snapshot.py`(沿撞坑 #50 第三层防御 · 88.78% 已稳定)
- ❌ 不增加新测试 / 不修改 approval_gate handler / 不修改 HTML
- ❌ 不立即修复撞坑 #69/#70(本棒仅 docs-only SOP 预制)
- ✅ docs-only 全部(7 files 改 + 2 docs 新增 + Agent loop 范式补齐)
- ✅ 撞坑累计 70 类沿用

---

## 6. 跨项目 memory 沉淀(沿 v0.2.53.37 / v0.2.53.40 范本)

| 项目 | 路径 | 类型 | 状态 |
|------|------|------|------|
| 我的AI员工 | `reports/2026-07-01-loop-patterns-prep.md` | docs(本棒) | 🟢 待 commit |
| Agent Assistant | `L2_memory/_cross-project/2026-07-01-loop-patterns-prep.md` | docs(cross-project) | 📅 7/1 议程 3 决议后沉淀 |
| Agent Assistant | `L2_memory/MEMORY.md` | index(+1 行)| 📅 7/1 议程 3 决议后新增 |

---

**commit 主题**:`docs(7/1 准备): 议程 3+29+30 loop 范式 + 撞坑 #69/#70 SOP 预制(7 个 Agent 骨架 + 2 SOP 草案)`
**撞坑累计**:**70 类沿用**(本棒无新增)
**status**:🟢 ready · 7/1 13:00-13:30 议程 3+29+30 直接执行 commit