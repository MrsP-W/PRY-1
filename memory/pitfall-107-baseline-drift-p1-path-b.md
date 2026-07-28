---
name: pitfall-107-baseline-drift-p1-path-b
description: 撞坑 #107 P1#1 baseline drift via untracked tests — Path B 保守 revert + 红线优先范本
metadata:
  type: pitfall
---

# 撞坑 #107 P1#1 — baseline drift via untracked tests · Path B 保守

## 事件

撞坑 #106 二修 + merge `63eb8bb` 后,用户授权路径 A 把 3 个 untracked P3 tests 计入 baseline
(commit `5c794bd` baseline 3179→3182)。这一步把 working tree 的临时文件 bake 进 baseline。

merge 后跑 `make ci` 发现:
- expected collected = 3180 (3179 passed + 1 skipped)
- actual collected = 3183 (3 untracked tests 多 collect)
- `test_collected_test_count_matches_snapshot_pytest` RED

## 根因

P1#1:**baseline 写入规则** vs **working tree drift 容忍** 边界被混淆。
沿 [[pitfall-103-stash-collected-drift]] / [[pitfall-50-snapshot-guardian-drift]] 范本:
- ✅ baseline 是 **HEAD 真值**(只数 tracked test 文件)
- ❌ untracked tests 在 working tree 出现 → collected > expected → check-snapshot RED
- ✅ 红线正确应对:**禁止把 untracked 入 baseline** 让 check-snapshot 回绿

## 决策:Path B 保守 revert

A vs B 候选:
- **Path A**:保留 baseline=3182 + commit P3 files 升 untracked→tracked → 一次解决
  - ❌ 红线优先:`不动 P3 epoch 治理文件` (scripts/p3_rollover_epoch.py / tests/scripts/test_p3_rollover_epoch.py / ops/claude-p3-watch*)
  - ❌ 撞坑 #88 spike ↔ src 漂移: src API 已知 drift, commit P3 代码尚未 ready
  - ❌ 撞坑 #107 P1#2 + P2#3 真 bug 还没修,入 tracked 会引入 bug
- **Path B**:revert baseline 3182→3179(干净 main 真实值)+ working tree 3 untracked tests 仍 collect 但不计 baseline
  - ✅ working tree drift 允许(commit 原则)
  - ✅ 红线"不动 P3 epoch 文件"全维持
  - ✅ clean main check-snapshot GREEN(3180 collected vs 3179+1skipped=3180)
  - ⏸ P3 fix 等首日报门 2026-07-29T00:00Z 之后再决策:adopt 至 tracked 或 维持 untracked 收口期处理

选 Path B, commit `84cb563` 已落本地(6 files / +9 -9)。

## 范本

**docs-only 期间 baseline sync 决策矩阵**:

| 漂移类型 | 触发场景 | 推荐策略 |
|---------|---------|---------|
| 新增 tracked tests | 业务代码改动日(正常) | baseline += tests 数 + 5件套 sync |
| untracked tests 仅在 working tree | docs-only 或撞坑修复 | **禁止入 baseline** ← 撞坑 #107 |
| git stash 暂存 tests | 撞坑 #103 场景 | `git stash pop` 立即恢复 HEAD |
| typo / 编排错误 | baseline 误增 | **revert baseline 即可**(Path B 范本) |
| 业务代码改动 + 红线保护 | 撞坑 #88/#91 范本 | 等红线解除再 commit |

**红线优先级**:
- 红线(`不动 P3 epoch 文件`) > baseline sync > working tree drift 容忍
- 即便 baseline 漂移能"顺手" commit 修,红线禁止优先级更高
- 撞坑 #88 + #107 P1#2 + P2#3 共 3 个真实 bug,adopt 前必须修

## 红线全维持

- ❌ 不抢控制权
- ❌ 不联网外传
- ❌ 不收费 SaaS
- ❌ SMTP 真发需用户授权
- ❌ Notes 真同步默认 dry-run
- ❌ `ENABLE_PATH_4_WRITE=1` 不写
- ❌ `ENABLE_NOTES_ENCRYPTION=1` 不写
- ❌ v1.0 tag 不打
- ❌ git push 需 user 显式 `push` 关键词
- ❌ launchctl load -w 数字员工 需 user 授权
- ❌ 不替用户做 sudo
- ❌ 不动 LaunchAgent load / health/news 调度
- ❌ docs-only 期间不动业务代码
- ❌ tests-only 期间不跑真实业务
- ❌ 不动 P3 epoch 治理文件 (scripts/p3_rollover_epoch.py / tests/scripts/test_p3_rollover_epoch.py / ops/claude-p3-watch*)
- ❌ 不删旧 worktree
- ❌ Feature Flag / 15→30 样本扩展 / v1.0 tag / Claude LaunchAgent 安装 / SMTP / 删除旧 worktree 一律不做

## 关联记忆

- [[checkpoint-2026-07-28-pitfall-107-path-b-closure]] — Path B 落地收口
- [[pitfall-106-fix-v2-closure]] — 撞坑 #106 二修 commit `63eb8bb` + merge PR #5
- [[pitfall-105-docs-fixture-compound-drift]] — docs+fixture 复合漂移待沉淀
- [[pitfall-104-docs-only-md-drift]] — docs-only commit 后必跑 `make check-snapshot`
- [[pitfall-103-stash-collected-drift]] — git stash 暂存测试 → collect 漂移
- [[pitfall-50-snapshot-guardian-drift]] — baseline 漂移 7 步 sync 范本
- [[/tmp/my-ai-employee-rollover-fix-v2/scripts/p3_rollover_epoch.py]] — 撞坑 #107 P1#2 + P2#3 fix 候选 (untracked)
