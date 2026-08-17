# Needs-Human -003 Snapshot Cherry-pick NO-GO 审计(2026-08-17)

## 0. TL;DR

- **触发**：用户「全部批准」(2026-08-17)；-003 quality_snapshot 集成审批
- **关键发现**：副树 `codex/d6102-stash-playbook` @ `a1c8469` 的 8 行 diff 实为**历史快照值**；cherry-pick 会**回退**当前 main 质量基线
- **结论**：-003 **NO-GO**；不解锁；副树 d6102 WIP 维持原状
- **本任务**：docs-only 审计记录 + 关闭 needs_human-003（status: needs_human → no_go）

## 1. 实际 diff 检查（实施前验证）

### 1.1 副树 d6102 与 main 当前版本对比

`git diff main -- src/my_ai_employee/quality_snapshot.py`（在副树执行）：

```diff
@@ class QualityGateSnapshot: @@
-    pytest: str = "3360 passed / 1 skipped"
-    coverage: str = "90.29%"
+    pytest: str = "3178 passed / 1 skipped"
+    coverage: str = "90.26%"
     mypy: str = "0 errors"
-    mypy_files: str = "294 files"
-    lint: str = "324 files 0 errors"
+    mypy_files: str = "292 files"
+    lint: str = "304 files 0 errors"
```

### 1.2 关键观察

| 字段 | 副树 d6102 (a1c8469) | 当前 main (b9fa370) | 差值（main 前进）|
|------|---------------------|---------------------|------------------|
| pytest | 3178 passed / 1 skipped | 3360 passed / 1 skipped | **+182 tests** |
| coverage | 90.26% | 90.29% | +0.03pp |
| mypy files | 292 files | 294 files | +2 files |
| lint files | 304 files | 324 files | **+20 files** |

**重要：副树的所有值都**小于**当前 main 值**。

### 1.3 副树 commit 历史

副树 HEAD `a1c8469` = `docs(memory): 撞坑 #105 docs-only + fixture 复合漂移沉淀 + D6.10.1 评测样本 4→15 同步收口`（7/28）

- 该 commit 是 7/28 时的"质量门同步"，**当时 3178 passed / 90.26% / 292 files / 304 files 是正确的**
- 自 7/28 至 8/17（约 3 周），main 通过 P3 复盘 + 各种 docs-only commit 前进了 182 tests / 2 files / 20 lint files
- 副树未跟进同步（撞坑 #103/#107 类似漂移）

## 2. Cherry-pick 风险分析

### 2.1 实际 cherry-pick 会发生什么

若 `git checkout codex/d6102-stash-playbook -- src/my_ai_employee/quality_snapshot.py`：

- 当前 main 的 3360 / 90.29% / 294 / 324 → 副树的 3178 / 90.26% / 292 / 304
- **pytest 数量减少 182**：因 main 自 7/28 新增测试（如 fixture 40 条扩样、P3 审计 docs 等）
- **mypy files 减少 2**：可能丢失新文件检查
- **lint files 减少 20**：可能丢失新 markdown 文件 lint
- 表面看无害（仅基线数字），但实质**回退 3 周测试覆盖**

### 2.2 与撞坑 #104/#105/#107 关系

- **撞坑 #104**：docs-only MD 同步 → 撞坑本身就在 7/28 副树记录；副树未沉淀到 main
- **撞坑 #105**：docs-only + fixture 复合漂移 → 副树 commit `a1c8469` 标题就是它
- **撞坑 #107**：baseline drift → 副树版本**正是 baseline drift 实例**

Cherry-pick 副树版本会**重新引入**撞坑 #107 历史基线漂移风险。

## 3. 解锁路径（替代方案）

### 3.1 选项 A（推荐）：不 cherry-pick，保留副树 WIP

- 副树 `src/my_ai_employee/quality_snapshot.py` 维持 8 行 diff 不动
- needs_human-003 status: needs_human → no_go（关闭任务）
- 副树 d6102 9 条 WIP 整体保持挂账
- 当前 main 质量基线（3360 / 90.29% / 294 / 324）保持最新

### 3.2 选项 B：人工 cherry-pick + 重新计算基线

- 用户提供 8/17 实测质量数字（如果副树 8 行是新文档而非回归值）
- 由用户在常规 code worktree 内手动更新
- 触发 SOL 终审

### 3.3 选项 C：副树归档

- 副树整体移到 `archive/worktree-d6102-20260728/`
- 9 条 WIP 全部丢弃
- 副树 HEAD `a1c8469` 的 commit 保留在 git 历史

### 3.4 推荐

**选项 A**：副树 WIP 维持现状；needs_human-003 关闭为 no_go；当前 main 质量基线正确，无需修改。

## 4. 决策依据

### 4.1 与 8/13 用户基线一致

> "存活副 worktree 全保留（按基线）"

副树 d6102 维持 WIP 不动，符合基线。

### 4.2 与 needs-human-tracking-2026-08-16 §4.3 一致

原 needs_human-003 设计假设「副树 8 行 diff 与 main 已 tracked 版本兼容性需 SOL 终审」——本次发现该 diff 是回归值，与原假设不符，故解锁步骤 step 3（SOL 终审）不可达，应在 step 2（实施前）就 NO-GO。

### 4.3 与 wip-inventory-2026-08-16 §2.3 一致

B 类 1 项原本标记为 needs_human；本次审计发现其根本不应 cherry-pick，而是保持副树历史 WIP。

## 5. needs_human-003 状态更新

```
原状态: needs_human
新状态: no_go
关闭原因: cherry-pick 会回退 main 质量基线（撞坑 #107 baseline drift 实例）
```

跟踪文档 `docs/eval/audit/needs-human-tracking-2026-08-16.md` §6 表格需要更新（待用户批准后另开 docs-only commit）。

## 6. 边界

- 不创建 -003 code worktree
- 不 cherry-pick 副树
- 不修改 `src/my_ai_employee/quality_snapshot.py`
- 不 push ahead
- 不启用 Feature Flag

## 7. 已验证 / 未验证边界

### 7.1 已验证

- ✅ 副树与 main 的 `quality_snapshot.py` 实际 diff（8 行）
- ✅ 副树 4 个字段值均小于 main 当前值
- ✅ 副树 commit 历史（a1c8469 = 撞坑 #105）
- ✅ 与 needs_human-003 unlock_steps 的偏离判断

### 7.2 未验证

- ❌ main 当前 3360 / 90.29% / 294 / 324 的实测路径（项目已跟踪）
- ❌ 副树值是否有「近期实测」的合理理由（结论：副树 HEAD 是 7/28 提交，5 周未更新）

### 7.3 边界

- 不动副树 8 行 diff
- 不动 main 当前 quality_snapshot.py
- 不删副树
- 不 push ahead

## 8. 推荐下一步动作

1. **本任务**：commit + ff-only + push（docs-only 记录）
2. **本任务后续**：可选 — 更新 `needs-human-tracking-2026-08-16.md` §6 表格（-003 状态改为 no_go）；需用户单独决定

## 9. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-needs-human-003-snapshot-no-go-20260817`，分支 `codex/needs-human-003-snapshot-no-go-20260817`。
- 基线：main=`b9fa370`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-17T10:30:00Z`（写入时）。
