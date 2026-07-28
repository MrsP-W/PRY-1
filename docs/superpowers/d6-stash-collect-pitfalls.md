# D6：stash 与 collect 漂移处理范本

## 适用范围

仅用于本地 docs/tests 任务：需要临时收起已跟踪改动，或质量门出现
`pytest --collect-only` / quality snapshot 与基线不一致时。P3 观察期内本范本
不触发脚本、调度、LaunchAgent、Feature Flag 或外部数据写入。

## 先决检查

```bash
git status --short --branch
git stash list
make check-snapshot
```

- 主工作树存在 WIP 时，只读；在基于 `HEAD` 的独立 worktree 内执行任务。
- `git stash list` 非空不等于异常，但必须在任务记录中说明归属和恢复计划。
- `make check-snapshot` 报错时，先保存完整输出；不要修改基线来掩盖原因。

## 诊断矩阵

| 现象 | 首先验证 | 处理 |
| --- | --- | --- |
| stash 后 collect 数减少 | `git stash list` 与 `git status --short` | 恢复该任务专属 stash 后再收集；不得触碰主树 WIP。 |
| 新增 docs/tests 后 snapshot 不一致 | `git diff --name-only`、`make check-snapshot` | 确认增量合理后，同步单一事实源和 5 件套状态。 |
| 只变文档却 MD 计数变化 | `git diff -- '*.md'` | 更新 MD 基线并运行 markdown lint。 |
| fixture 与 docs 同轮变更 | fixture 数量、schema 测试、5 件套 grep | 按一个原子任务收口；沿用撞坑 #105 的复合漂移范本。 |

## 安全恢复顺序

1. 记录 stash ref、所属 worktree 和任务 ID；不执行 `stash clear`、`drop` 或覆盖式恢复。
2. 在任务 worktree 执行 `git stash show --stat <ref>`，确认范围后才执行恢复。
3. 恢复后先跑 `make check-snapshot`；若失败，定位 collect、MD、pytest 或 mypy 哪一项漂移。
4. 仅当变更已验收时更新基线和状态入口；随后运行任务约定的质量门。
5. 两次自动修复仍失败，保留输出并标记 `needs_human`；继续无依赖安全任务。

## P3 延后项

`scripts/check_quality_snapshot.py` 的 `git stash list` 自动警告是设计候选，
在 P3 观察期不实现。原因是它属于运行时脚本修改，超出当前 docs-only/tests-only
白名单。P3 资格通过并获实现任务授权后，再以独立原子任务评估：误报策略、非零
退出码、回滚方式及相应测试。

## 关联证据

- [撞坑 #105](../../memory/pitfall-105-docs-fixture-compound-drift.md)：docs 与 fixture 复合漂移。
- [评测样本契约](../../tests/eval/SCHEMA.md)：fixture 脱敏与字段要求。
