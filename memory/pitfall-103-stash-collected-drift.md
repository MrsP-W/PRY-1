---
name: pitfall-103-stash-collected-drift
description: "暂存已跟踪测试文件会改变 pytest collect 基线；必须在专用 worktree 中记录、恢复并复验。"
metadata:
  node_type: memory
  type: pitfall
---

# 撞坑 #103 — stash 造成 collected 基线漂移

## 现象

对包含已跟踪测试文件的工作树执行 `git stash` 后，`pytest --collect-only` 可能少于
quality snapshot 声明的 `passed + skipped`，从而使 `make check-snapshot` 失败。

## 安全处理

1. 先记录 stash ref、任务 ID 和所属独立 worktree；主工作树有 WIP 时只读。
2. 使用 `git stash show --stat <ref>` 核对范围；不执行 `stash clear` 或 `stash drop`。
3. 在同一任务 worktree 恢复该任务专属 stash，再运行 `make check-snapshot`。
4. 仅在收集数恢复且任务质量门通过后，才更新合理的 baseline；不得用修改 baseline 掩盖暂存造成的缺件。
5. 两次自动修复失败，保留输出并标记 `needs_human`。

## P3 边界

`scripts/check_quality_snapshot.py` 的 stash 自动警告仅为候选设计，P3 期间不实现；它会修改运行时脚本，超出 docs-only/tests-only 白名单。

## 关联

- [D6 stash/collect 漂移范本](../docs/superpowers/d6-stash-collect-pitfalls.md)
- [撞坑 #104：Markdown 基线漂移](pitfall-104-docs-only-md-drift.md)
- [撞坑 #105：docs 与 fixture 复合漂移](pitfall-105-docs-fixture-compound-drift.md)
