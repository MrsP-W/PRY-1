# Worktree 归属审计报告(2026-07-28)

> **审计时间**:2026-07-28T05:36Z · **审计者**:主 Agent · **审计方式**:只读 · **授权**:用户"全部授权"
>
> **核心红线**:不动 worktree 内容、不删除任何 worktree、不切分支、不 commit

## 1. 总览

- **总数**:18 个 worktree(含主工作树 1 个 + 17 个辅助)
- **路径分布**:12 个在 `/private/tmp/` · 1 个在 `/Users/wei/Documents/DesktopOrganizer/worktrees/` · 5 个在 `/private/tmp/` 或 `/Users/wei/`
- **活跃度**(按 dirty lines):
  - 🟢 干净(0 dirty):**14 个**
  - ⚠️ 1 dirty(只有 untracked 资源):**3 个**(2 个 agent-team · 1 个 codex/d6-10-2-docs)
  - ⚠️ 9 dirty(主工作树相关):**1 个**(`codex/d6102-stash-playbook`)
  - ⚠️ 17 dirty(主工作树 + 本轮 5 件套修改):**1 个**(main)

## 2. 归属分类(按分支前缀)

| 类别 | 数量 | 分支前缀 | 备注 |
|------|------|----------|------|
| **main** | 1 | `main` | 主工作树,本轮 5件套 sync 后 17 dirty |
| **P0 本轮** | 1 | `p0-minimal-fix` | Step 1 创建,PR #4 merge 后本地未删(因 clean worktree 在用)|
| **agent-team** | 3 | `agent-team/{dryrun-001,tests-001,d6112-flag-design-20260727}` | 2 个 dryrun + 1 个 feature flag design |
| **codex** | 12 | `codex/*` | D6.10.2 / D6.10.3 / D6.11.2 系列 + UI 修复 + P3 sync |
| **docs** | 1 | `docs/d6102-stash-collect-pitfalls` | 撞坑 #103 沉淀 docs-only branch |

## 3. 详细列表

### 3.1 main(主工作树)

| 路径 | HEAD | 状态 |
|------|------|------|
| `/Users/wei/Documents/DesktopOrganizer/我的AI员工` | `2df1ee8f6b` (本地 ahead origin/main by 2) | ⚠️ **17 dirty**(本轮 5件套 sync + scripts/ 撞坑 #106 修复 + 11 untracked)|

### 3.2 P0(本轮 Step 1)

| 路径 | HEAD | 状态 |
|------|------|------|
| `/private/tmp/my-ai-employee-clean-20260728-101106` | `9e35bd5f99` | 🟢 干净(Step 1 clean worktree,沿用 PR #4 base commit)|

### 3.3 agent-team(3 个)

| 分支 | HEAD | 状态 |
|------|------|------|
| `agent-team/dryrun-001` | `18ec5fab2f` | ⚠️ 1 dirty(`?? docs/agent-team/`)|
| `agent-team/tests-001` | `18ec5fab2f` | ⚠️ 1 dirty(`?? docs/agent-team/`)|
| `agent-team/d6112-flag-design-20260727` | `4f8eaaeedf` | 🟢 干净 |

### 3.4 codex(12 个)

| 分支 | HEAD | 状态 |
|------|------|------|
| `codex/d6102-candidate-acceptance-20260728` | `dcf8a4425b` | 🟢 干净 |
| `codex/d6-10-2-docs-20260728` | `be3cb22f60` | ⚠️ 1 dirty(`?? TASK-CONTRACT.yaml`)|
| `codex/d6-10-2-governed-20260728` | `36113ca1fb` | 🟢 干净 |
| `codex/d6102-integrate-20260728` | `36113ca1fb` | 🟢 干净 |
| `codex/d6102-merge-readiness-20260728` | `474cadad6c` | 🟢 干净 |
| `codex/d6102-stash-pitfall` | `4a57b77955` | 🟢 干净 |
| `codex/d6103-attention-evidence-20260728` | `49e1e66cd2` | 🟢 干净 |
| `codex/d6112-feature-flag-design` | `2b100bb0eff` | 🟢 干净 |
| `codex/d6-11-2-review-20260728` | `5cea583825` | 🟢 干净 |
| `codex/fix-mail-button-contrast-20260728` | `da7a66fde1` | 🟢 干净 |
| `codex/p3-snapshot-baseline-sync-20260728` | `f9b64e2390` | 🟢 干净 |
| `codex/d6102-stash-playbook` | `a1c8469573` | ⚠️ **9 dirty**(含 CLAUDE.md / MODIFICATION-LOG.md / README.md / SESSION-STATE.md 修改)|

### 3.5 docs(1 个)

| 分支 | HEAD | 状态 |
|------|------|------|
| `docs/d6102-stash-collect-pitfalls` | `afc918319d` | 🟢 干净 |

## 4. 关键观察

### 4.1 全部 HEAD 都是 0d ago

所有 18 个 worktree 的 HEAD commit 都在 2026-07-28 当天(或最近 commit),说明工作流密集,worktree 创建后没有长期 stale。

### 4.2 dirty lines 集中点

| worktree | dirty | 内容 |
|----------|-------|------|
| main | 17 | 本轮 5件套 sync + scripts/ 撞坑 #106 + 11 untracked(LaunchAgent / rollover 脚本 / 设计文档)|
| codex/d6102-stash-playbook | 9 | **也撞了 5件套**(说明多个 worktree 同时在改 CLAUDE.md / SESSION-STATE.md)|
| agent-team/dryrun-001 + tests-001 | 1+1 | `docs/agent-team/` untracked(同一来源)|
| codex/d6-10-2-docs-20260728 | 1 | `TASK-CONTRACT.yaml` untracked |

### 4.3 与 main 的 ahead/behind 关系

| worktree | 关系 | 备注 |
|----------|------|------|
| codex/d6102-stash-playbook | `a1c8469` (= 干净 worktree 之前 HEAD)| **落后 main 2 commits**(本轮 merge + pull)|
| codex/d6-10-2-governed-20260728 + d6102-integrate-20260728 | `36113ca` (= merge 前本地 HEAD)| **落后 main 3 commits**(本轮 merge + pull)|
| 其他 codex/* | 各种 | 各自独立 |

## 5. 归属建议(供用户决策,不擅自动手)

### 5.1 🟢 活跃 worktree(无需处理)

- `codex/*` 12 个 + `agent-team/*` 3 个 + `docs/*` 1 个 = **16 个** 大概率是各 D-step / agent-team 任务的活跃 worktree
- **建议**:用户单独决策各 worktree 的去留(merge / rebase / 清理),本审计不擅自处理

### 5.2 🟡 本轮特殊 worktree

| worktree | 处理建议 |
|----------|---------|
| `p0-minimal-fix` (Step 1 clean worktree) | **保留**(沿用 PR #4 base commit 用于将来回归验证 · 红线"不删旧 worktree")|
| `main` (主工作树) | **保留**(本轮 17 dirty 是 5件套 sync + scripts/ 撞坑 #106 + 11 untracked)|

### 5.3 ⚠️ 重复 dirty 风险

`codex/d6102-stash-playbook` 与 `main` 同时 dirty 了 4 个 5件套(CLAUDE.md / MODIFICATION-LOG.md / README.md / SESSION-STATE.md)。这意味着多个 worktree 独立做了 5件套同步,**可能在不同 worktree 之间冲突**(撞坑 #50 衍生第三版)。

**建议**:用户审计后,决定哪些 worktree 的 5件套改动是想要的,哪些应该 `git checkout` 丢弃。

## 6. 红线(不动)

- ❌ 不删任何 worktree(包括 stale)
- ❌ 不切分支 / 不 merge / 不 rebase / 不 cherry-pick
- ❌ 不 commit / 不 push
- ❌ 不动 11 组 untracked(LaunchAgent / rollover 脚本 / 设计文档)
- ❌ 不动 P3 epoch 文件
- ❌ 不替用户做 sudo

## 7. 关联

- 撞坑 #50(第三层 MD+pytest 联动漂移):docs-only 期间 5件套同步范本
- 撞坑 #104(docs-only commit 后未同步 quality_snapshot):5件套 sync 8 处同步
- 撞坑 #105(docs+fixture 复合漂移):双层 baseline 漂移
- 撞坑 #106 NEW(`check_quality_snapshot.py:97` 子进程 `uv run pytest` → `sys.executable -m pytest`):干净 worktree 修复后 3175/0 fail