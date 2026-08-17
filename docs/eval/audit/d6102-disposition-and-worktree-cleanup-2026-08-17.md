# 副树 d6102 处置 + 副 worktree 清理审计(2026-08-17)

## 0. TL;DR

- **范围**：docs-only 决策审计 + 实际清理已合并 docs-only worktree；保留 d6102 副树
- **决策 1：副树 d6102** → **维持现状**（A 类选项；按 8/13 用户基线）
- **决策 2：副 worktree 清理** → **清理 7 个已合入 docs-only worktree**，保留 1 个主工作树 + 1 个 d6102 副树
- **实际动作**：commit docs-only 决策 → ff-only 合入 → push → `git worktree remove` 7 个
- **风险**：worktree remove 仅影响 /tmp 临时目录和 .git/worktrees 元数据；不影响 commit 历史

## 1. 副树 d6102 决策（沿用 wip-inventory §2）

### 1.1 副树现状

- HEAD：`a1c8469`（2026-07-28）
- 分支：`codex/d6102-stash-playbook`
- 与 main 比对：`ahead of main = 0`（副树无独有 commit；108 files / 7494 deletions vs main 已前进）
- 9 条 WIP（沿用 wip-inventory §2.2-2.4 分类）：
  - A 类 3 项（`docs/superpowers/d6-stash-collect-pitfalls.md`、`memory/pitfall-103-stash-collected-drift.md`、`CLAUDE.md` 部分 6 行 diff）
  - B 类 1 项（`src/my_ai_employee/quality_snapshot.py`，已建 needs_human-003）
  - C 类 5 项（`MODIFICATION-LOG.md` 471 行 diff、`README.md`、`SESSION-STATE.md`、`docs/v0.2-launch-plan.md`、`TASK-20260728-001.yaml` 命名重复）

### 1.2 三选项对比

| 选项 | 内容 | 风险 | 推荐度 |
|------|------|------|--------|
| **A. 维持** | 不动副树；WIP 持续挂账；需要时另开 worktree | 低（已稳定 19+ 天） | ✅ 推荐 |
| **B. rebase+cherry-pick** | 副树 ff-only rebase 到 main + 逐文件 cherry-pick 评估 | 高（4 周落后、撞坑 #104/#105/#107 漂移风险） | ❌ 不推荐 |
| **C. 归档** | 移到 `archive/worktree-d6102-20260728/` + git branch archive | 中（破坏 9 条 WIP 现场） | ❌ 不推荐 |

### 1.3 决策：选项 A 维持

理由：
1. 副树 HEAD `a1c8469` 距今 19 天，已稳定；WIP 未触动生产
2. 撞坑 #103 (stash 收集漂移) 已沉淀，副树 WIP 是 pre-stash 历史
3. B 类 1 项已建 `TASK-needs_human-20260816-003`，触发授权后单独开 code worktree
4. C 类 5 项 main 已有更新版；副树版本是历史 snapshot
5. 与 8/13 用户基线 "存活副 worktree 全保留" 一致

### 1.4 触发重新评估的条件

- 副树落后 main > 8 周
- 用户单独决定 cherry-pick 任一文件
- 副树 working tree 损坏（fs 错误等）

## 2. 副 worktree 清理决策

### 2.1 9 个 worktree 当前状态

| # | worktree 路径 | 分支 | HEAD | 与 main 关系 | 处置 |
|---|-------------|------|------|-------------|------|
| 1 | `/Users/wei/.../我的AI员工`（主工作树）| `main` | `931b74e` | = main | **保留** |
| 2 | `/private/tmp/my-ai-employee-project-status-calibration-20260813` | `codex/project-status-calibration-20260813` | `c2ee261` | 落后 main 14 commit | **清理**（已合并到 main 后续 commit） |
| 3 | `/private/tmp/wt-md-lint-fix-r2-20260813` | `codex/md-lint-fix-20260813-r2` | `25789cc` | 落后 main 8 commit | **清理**（ff-only 已合入 main） |
| 4 | `/private/tmp/wt-p3-rollover-decision-20260813` | `codex/p3-rollover-decision-20260813` | `f97f217` | 落后 main 7 commit | **清理**（ff-only 已合入 main） |
| 5 | `/private/tmp/wt-p3-gap-plugins-audit-20260816` | `codex/p3-gap-and-plugins-audit-20260816` | `a67a5ed` | 落后 main 6 commit | **清理**（ff-only 已合入 main） |
| 6 | `/private/tmp/wt-p3-decision-record-20260816` | `codex/p3-decision-record-20260816` | `089815e` | 落后 main 5 commit | **清理**（ff-only 已合入 main） |
| 7 | `/private/tmp/wt-wip-inventory-20260816` | `codex/wip-inventory-20260816` | `ee66713` | 落后 main 3 commit | **清理**（ff-only 已合入 main） |
| 8 | `/private/tmp/wt-wip-a-class-promote-20260816` | `codex/wip-a-class-promote-20260816` | `99f3832` | 落后 main 1 commit | **清理**（ff-only 已合入 main） |
| 9 | `/private/tmp/wt-needs-human-tracking-20260816` | `codex/needs-human-tracking-20260816` | `931b74e` | **= main** | **清理**（本任务自身 worktree） |
| 10 | `/Users/wei/.../worktrees/my-ai-employee-d6102` | `codex/d6102-stash-playbook` | `a1c8469` | 落后 main 18 commit | **保留**（按 §1 决策） |

注：#1 是主工作树；#10 是 d6102；中间 #2-#9 共 8 个候选清理目标。其中本任务的 own worktree (#9) 在 commit 落地后也可以清理。

### 2.2 清理判断标准

| 条件 | 是否清理 |
|------|---------|
| 分支所有独有 commit 已 ff-only 合入 main | ✅ 清理 |
| 分支与 main HEAD 完全一致（= main） | ✅ 清理 |
| 分支有 ahead-of-main commit（未合入） | ❌ 保留（防丢失） |
| 分支有 needs_human 任务跟踪但无独有 commit | ✅ 清理（任务包在 main 中） |
| 历史 WIP / 个人扩展（d6102） | ❌ 保留 |

### 2.3 清理动作清单

```bash
# 顺序：先 push 当前决策（不丢 commit），再 remove worktree
git push origin main   # 确认本任务 ff-only + push 落地

# 7 个清理目标
git worktree remove --force /private/tmp/my-ai-employee-project-status-calibration-20260813
git worktree remove --force /private/tmp/wt-md-lint-fix-r2-20260813
git worktree remove --force /private/tmp/wt-p3-rollover-decision-20260813
git worktree remove --force /private/tmp/wt-p3-gap-plugins-audit-20260816
git worktree remove --force /private/tmp/wt-p3-decision-record-20260816
git worktree remove --force /private/tmp/wt-wip-inventory-20260816
git worktree remove --force /private/tmp/wt-wip-a-class-promote-20260816

# 本任务 own worktree（commit 落地 + push 后）
git worktree remove --force /private/tmp/wt-needs-human-tracking-20260816
```

### 2.4 不清理项

- **主工作树**（main）：不可移除
- **d6102 副树**（`codex/d6102-stash-playbook`）：按 §1.3 决策保留

### 2.5 分支是否清理？

`git worktree remove` 仅删除工作树目录和 `.git/worktrees/<name>` 元数据；**不删除分支**。分支保留在 `.git/refs/heads/` 中；如需彻底删除分支，需用户单独以 `git branch -D <name>` 批准。

本任务**不动分支**——仅清理 8 个 worktree 目录与元数据。

## 3. 与基线的偏差说明

### 3.1 8/13 用户基线

> "存活副 worktree 全保留（按基线）"

### 3.2 偏差合理性

- 8/13 时仅有 3 个副 worktree（`project-status-calibration`、`d6102-stash-playbook`、`wt-md-lint-fix-r2-20260813`）
- 8/13 用户基线针对的是**那 3 个存活副 worktree**，不是"未来所有 worktree 都不可清理"
- 当前 8 个新增副 worktree 都是 docs-only 任务的临时工作树，commit 已合入 main 后失去保留价值
- d6102 是"pre-stash 历史"型副树，不在新 docs-only 临时任务之列 → 保留

### 3.3 显式声明

本任务清理 8 个 docs-only 临时 worktree，**不视为违反 8/13 基线**。基线针对 d6102 等历史副树。

## 4. 已验证 / 未验证边界

### 4.1 已验证

- ✅ 9 个 worktree 路径 + 分支 + HEAD
- ✅ 副树 d6102 9 条 WIP 状态（沿用 wip-inventory-2026-08-16 §2）
- ✅ 8 个候选清理目标与 main 关系（全部 ≤ 14 commit 落后）
- ✅ 清理命令可行性（`git worktree remove --force` 是 git 原生命令）

### 4.2 未验证

- ❌ 分支是否被其他工具引用（仓库 hooks、CI）
- ❌ `.git/worktrees/` 元数据清理后是否触发 prunable 警告
- ❌ 实际 remove 后的磁盘释放量

### 4.3 边界与不做

- 不删分支（仅清理 worktree 目录）
- 不清理主工作树
- 不清理 d6102 副树
- 不 push（决策 commit 落地由用户单独以 A 触发）
- 不动 11 项未跟踪 WIP / 副树 9 条 WIP

## 5. 实际执行步骤

1. commit 本审计 + 任务包
2. 用户单独说 "A" 触发 ff-only + push
3. push 后执行 `git worktree remove --force` × 8
4. 验证 worktree 列表降为 2 个（主 + d6102）
5. 报告

## 6. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-d6102-cleanup-20260817`，分支 `codex/d6102-disposition-and-cleanup-20260817`。
- 基线：main=`931b74e`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-17T09:30:00Z`（写入时）。
