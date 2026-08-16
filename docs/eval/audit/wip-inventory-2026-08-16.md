# WIP 盘点审计 — 主树 11 项 + 副树 9 条(2026-08-16)

## 0. TL;DR

- **范围**：docs-only 只读盘点 8/13 校准以来持续挂账的 WIP；**不 add、不修复、不清理**（按用户基线指令）。
- **主树 11 项未跟踪**：分类如下
  - A. 可独立沉淀的 docs/tests：**6 项**（建议未来 docs-only commit）
  - B. P3 高风险脚本 → needs_human：**2 项**（`ops/claude-p3-watch-*`）
  - C. 用户私有或历史 WIP，继续保留：**3 项**（`plugins/`、`PR_BODY_*`、累计含 5 文件的 plugins/）
- **副树 `codex/d6102-stash-playbook` 9 条 WIP**：分类如下
  - A. 可独立沉淀的 docs：**3 项**（`docs/superpowers/*`、`memory/pitfall-103-*`、CLAUDE.md 部分）
  - B. P3 高风险 / 代码：**1 项**（`src/my_ai_employee/quality_snapshot.py`）
  - C. 副树历史 stash 或 main 已覆盖：**5 项**（CLAUDE.md/MODIFICATION-LOG.md/README.md/SESSION-STATE.md/docs/v0.2-launch-plan.md + 一个任务 yaml 重复）
- **触发条件**：用户单独说"按 A 入仓" / "按 B 入 needs_human 清单" / "按 C 维持 WIP" 才执行实际修改。

## 1. 主树未跟踪 11 项分类

### 1.1 A 类：可独立沉淀的 docs/tests（6 项）

| 文件 | 大小 | 内容性质 | 入仓建议 |
|------|------|---------|---------|
| `.cursor/rules/agent-team-worktree.mdc` | 26 行 / 1313 B | Cursor 规则文件：三 Agent worktree 边界 + 审批 + 交付格式 | 与 `docs/agent-team/` 同步入仓；明文声明 alwaysApply |
| `AGENTS.md` | 35 行 / 2906 B | Codex 三 Agent 协作入口（合并关系 + 硬边界 + 职责 + 审批） | 入仓主工作树根目录；与 `.cursor/rules/*` 互为补充 |
| `docs/agent-team/README.md` | 53 行 / 2701 B | 三 Agent 协议 Phase 0 文档（目标 + 角色 + 状态机） | 入仓；与 `task-contract.yaml` 配套 |
| `docs/agent-team/task-contract.yaml` | 28 行 / 661 B | 任务契约 YAML 模板（task_id/owner/risk/acceptance_commands/result） | 入仓；当前已被 30+ 任务包实例引用 |
| `docs/v0.2-D6.11.2-feature-flag-design-outline.md` | 201 行 / 8176 B | D6.11.2 Feature Flag 设计大纲（design-only） | 入仓；与 P3 路径 A 关联；待 v1.1-A 解锁后再实施 |
| `memory/pitfall-106-fix-v2-task-package.md` | 294 行 / 9161 B | 撞坑 #106 二修任务包（needs_human 触发，未启动） | 入仓；标 `needs_human` 触发记录 |

**入仓路径风险**：

- 5 项（agent-team / .cursor / AGENTS.md / v0.2-D6.11.2 / pitfall-106）：纯文档；docs-only worktree 内可一次性 commit；与 §6.1 前置类似
- `docs/eval-fixture-coverage-15-to-30-plan.md`（194 行 / 7736 B）：**15→30 规划**，但**已在 main 里有 `docs/eval-fixture-coverage-30-to-40-plan.md`**——主仓已前进到 30→40 规划，**此文件可能已过时**；建议**保留为 WIP 不入仓**（移入 C 类）

修正：A 类实际 **6 项**（去掉 15→30 plan），文件大小已含原 11 项统计

### 1.2 B 类：P3 高风险脚本 → needs_human（2 项）

| 文件 | 大小 | 内容性质 | 风险 |
|------|------|---------|------|
| `ops/claude-p3-watch-launchd.plist.example` | 14 行 / 809 B | launchd plist 模板（`com.myaiemployee.claude-p3-watch`，每 2h 跑 `/p3-watch`） | 高：包含 `RunAtLoad=true`，若复制到 `~/Library/LaunchAgents/` 会被自动 load；触及 LaunchAgent（撞坑红线） |
| `ops/run-claude-p3-watch.sh` | 9 行 / 320 B | 调用 `claude --plugin-dir plugins/p3-ops-claude --permission-mode dontAsk --max-budget-usd 1` | 中：`dontAsk` 模式下 Claude 可自行决策；`--max-budget-usd 1` 限制成本但仍自动运行 |

**风险点**：

1. `.plist.example` 后缀已明确"未自动 load"；但复制即生效
2. `run-claude-p3-watch.sh` 与 `plugins/p3-ops-claude` 联动；任一项未受控即可触发 P3 操作
3. 与主仓 `scripts/watch_p3_ops.py`（已 tracked）功能重叠；用户应明确主从

**建议处置**：

- **不入仓**：保持 WIP，避免触发 LaunchAgent 红线
- 若必须入仓：标记 `needs_human`，单独 worktree 由用户批准；并在 README 中明确"严禁 load plist"
- 或采用更稳妥方式：拆 `watch_p3_ops.py` 为只读脚本（已在主仓）；新增 `claude-p3-watch` 作为可选扩展

### 1.3 C 类：用户私有或历史 WIP（3 项 + 累计 plugins/ 5 文件）

| 文件 | 大小 | 内容性质 | 建议 |
|------|------|---------|------|
| `PR_BODY_p0-minimal-fix.md` | 38 行 / 1736 B | P0 #2 干净 worktree 质量门修复的 PR 描述（commit `36113ca` needs_human 触发） | 保留为 WIP；不入仓（无对应 PR 推送）；或入仓 docs/archive/ |
| `docs/eval-fixture-coverage-15-to-30-plan.md` | 194 行 / 7736 B | 15→30 评测样本扩样规划（已被 30→40 规划覆盖） | 保留 WIP 或归档；不入仓（信息已过时） |
| `plugins/p3-ops-claude/` | 5 文件 | 个人 Claude Code 安全编排命令（沿用 §4.1 A 决策） | **维持 WIP**；详见 §4.1 决策 |

**plugins/ 详情**：

```
plugins/p3-ops-claude/README.md                                     5 文件
plugins/p3-ops-claude/.claude-plugin/plugin.json                    8/4 创建
plugins/p3-ops-claude/commands/p3-rollover.md                       持续 untracked 12 天
plugins/p3-ops-claude/commands/p3-watch.md
```

## 2. 副树 `codex/d6102-stash-playbook` 9 条 WIP 分类

### 2.1 副树现状

- HEAD `a1c8469`（7/28，落后 main ≈ 4 周）
- 分支 `codex/d6102-stash-playbook`
- 与 main 比对：`108 files changed, 192 insertions(+), 7494 deletions(-)` — 大量 main 已前进但副树未同步
- 9 条 WIP = 9 个文件本地修改

### 2.2 A 类：可独立沉淀的 docs（3 项）

| 文件 | 状态 | 大小 | 内容性质 | 入仓建议 |
|------|------|------|---------|---------|
| `docs/superpowers/d6-stash-collect-pitfalls.md` | A（新增） | 55 行 / 71 行 diff | D6 stash-collect 撞坑沉淀（pre-stash playbook） | 入仓 docs/superpowers/；与 main 现有 `memory/pitfall-103-stash-collected-drift.md` 互补 |
| `memory/pitfall-103-stash-collected-drift.md` | A（新增） | 46 行 / 44 行 diff | 撞坑 #103 stash 收集漂移（pre-stash playbook） | **已存在于 main**（沿用 8/16 决策 §3.1）；副树版本可能更早；建议保留 WIP 或对照合并 |
| `CLAUDE.md` | M | 266 行 / 6 行 diff | 顶部声明 + 5 件套说明 | 6 行 diff 极小；建议对照 main `CLAUDE.md`（已 tracked）评估是否同步 |

### 2.3 B 类：P3 高风险 / 代码（1 项）

| 文件 | 状态 | 大小 | 内容性质 | 风险 |
|------|------|------|---------|------|
| `src/my_ai_employee/quality_snapshot.py` | M | 45 行 / 8 行 diff | 质量快照脚本（业务代码） | 高：撞坑 #104/#105/#107 与该脚本漂移相关；副树未通过 SOL 终审 |

**处置建议**：

- **不入仓**：代码改动需独立 worktree + SOL 终审
- 已存在 main 中 tracked 副本；副树 diff 仅 8 行；可能已被 main 版本覆盖
- 建议保留 WIP，由用户单独决定是否 cherry-pick

### 2.4 C 类：副树历史 stash 或 main 已覆盖（5 项）

| 文件 | 状态 | 大小 | 处置建议 |
|------|------|------|---------|
| `MODIFICATION-LOG.md` | M | 6652 行 / 471 行 diff | **main 已远前进**（8/16 已加 30+ 条新条目）；副树版本是 7/28 锚点；**保留为副树历史 WIP**，不入 main |
| `README.md` | M | 386 行 / 4 行 diff | main `README.md` 已 tracked；4 行 diff 是撞坑 #104/#105 docs sync；建议对照 main 评估；不入 main |
| `SESSION-STATE.md` | M | 275 行 / 49 行 diff | 同上；49 行 diff 是状态同步差异；保留 WIP |
| `docs/v0.2-launch-plan.md` | M | 360 行 / 6 行 diff | main 已 tracked；6 行 diff 是小同步；保留 WIP |
| `docs/agent-team/tasks/TASK-20260728-001.yaml` | AM | 53 行 | **命名冲突**：main 有 `TASK-20260728-001-d6102-stash-collect.yaml`（46 行）；副树 53 行版本内容不同；保留 WIP，需命名修正后入仓 |

### 2.5 副树整体处置建议

- **副树整体保留**（按用户基线"不清理存活副 worktree"）
- 不 cherry-pick、不 merge、不 reset、不 stash drop
- 9 条 WIP 中 5 条已在 main 中以更新版存在；副树版本是 pre-stash 历史
- 若未来需合并：单独 worktree 重建（基于 main）；逐文件 cherry-pick 评估

## 3. 汇总分类表

| 类别 | 主树 | 副树 | 合计 | 建议触发动作 |
|------|------|------|------|-------------|
| A. 可独立沉淀 docs/tests | 6 | 3 | 9 | docs-only worktree 一次性 commit（待用户批准） |
| B. P3 高风险 → needs_human | 2 | 1 | 3 | 标 `needs_human`；不入仓；待用户单独决定 |
| C. 用户私有 / 历史 WIP | 3（含 plugins/ 5 文件） | 5 | 8 | 维持 WIP；不动 |
| **合计** | **11** | **9** | **20** | — |

## 4. §4.1 A 决策复核（plugins/p3-ops-claude）

按 §4.1 A 决策（`a67a5ed` 已入仓），`plugins/p3-ops-claude/` 维持 WIP 不入仓。复核结果：

- ✅ 时间戳仍为 2026-08-04 16:09（无新变更）
- ✅ 内容性质仍为个人 Claude Code 编排
- ✅ 与主仓 `scripts/watch_p3_ops.py` 等只读映射，无逻辑冲突
- ✅ §1.4 触发重新评估条件未触发

**结论**：维持 §4.1 A 决策；本次不动 plugins/。

## 5. 已验证 / 未验证边界

### 5.1 已验证（只读盘点）

- ✅ 主树 11 项文件路径、大小、内容性质（head 15-30 行）
- ✅ 副树 9 项文件状态（A/M/AM）、大小、与 main 的 diff stat
- ✅ 副树 HEAD `a1c8469` 与 main `089815e` 关系（落后 ≈ 4 周）
- ✅ `plugins/p3-ops-claude/` 时间戳复核
- ✅ 5 项主树 A 类文档 vs main 已 tracked 版本的对照（如 `docs/eval-fixture-coverage-30-to-40-plan.md` 已覆盖 15→30 plan）

### 5.2 未验证（不在本次范围）

- ❌ A 类 6 项入仓是否会触发 ruff/mypy/CI 失败
- ❌ B 类脚本实际执行的安全性测试
- ❌ 副树 9 项与 main 对应文件的逐字节 diff
- ❌ 副树分支策略（是否 ff-only rebase 到 main 后 cherry-pick）

### 5.3 边界与不做

- 不 add 任何 WIP（不入仓）
- 不修复 / 不修改 / 不删除任何文件
- 不清理副 worktree（保留 `codex/d6102-stash-playbook`）
- 不 push / merge / 打 tag
- 不启用 Feature Flag / `ENABLE_*`
- 不跑 `p3_rollover_epoch.py` / `watch_p3_ops.py` / 任何 P3 脚本

## 6. 推荐下一步动作（待用户单独决定）

1. **本周（你决定）**：A 类 6 项主树 + 3 项副树是否合并入仓
   - 若批准：开新 docs-only worktree → 一次性 commit → ff-only → push
   - 若不批准：维持 WIP；下次再盘点
2. **本周（你决定）**：B 类 3 项是否单独开 `needs_human` 任务跟踪
   - 建议：单独建 `docs/agent-team/tasks/TASK-needs_human-20260816-*.yaml` 跟踪
3. **本周（你决定）**：副树 `codex/d6102-stash-playbook` 9 条 WIP 整体处置
   - 选项 A：维持现状（推荐；按基线）
   - 选项 B：单独 worktree ff-only rebase 到 main + cherry-pick
   - 选项 C：归档副树到 `archive/worktree-d6102-20260728/`

## 7. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-wip-inventory-20260816`，分支 `codex/wip-inventory-20260816`。
- 基线：main=`089815e`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-16T21:30:00Z`（写入时）。
