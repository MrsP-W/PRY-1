# Needs-Human SOL FAIL 记录(2026-08-17)

## 0. TL;DR

- **触发**：SOL 终审结论（用户外部运行 `gpt-5.6-sol` 提供结论）
- **结论**：2 项 needs_human 均 FAIL / NO-GO
  - `9055389` (-001 plist)：FAIL — 缺 P3 result=pass 前置门、预算门、依赖闭环
  - `188de4a` (-002 script)：FAIL — default 非交互、移除 budget、插件未入仓
- **关键集成阻断**：两个 commit 都是 `b9fa370` 的兄弟分支；当前 `main=dd527e7`，相对每个候选均为 1/1 分叉 → 不能单独或连续 ff-only
- **当前状态**：2 分支保留；未 merge、未 push、未 load、未跑脚本
- **建议下一步**：基于当前 main=dd527e7 新建单一修复分支，解决 6 项 SOL 阻断后重新 SOL 终审

## 1. SOL 终审结论（外部运行）

### 1.1 输入格式

```yaml
SOL REVIEW RESULT:
- 9055389 (-001 plist): FAIL — 缺少 P3 result=pass 前置门、预算门及依赖闭环；无法 ff-only
- 188de4a (-002 script): FAIL — 非交互 default 无法逐次确认、移除 budget 等于取消费用上限、插件未入仓；无法 ff-only
REVIEWED BY: gpt-5.6-sol
REVIEWED AT: 2026-08-17T01:10:44Z
```

### 1.2 评审维度

| 评审点 | -001 plist | -002 script |
|--------|-----------|-------------|
| 格式检查 | ✅ plutil -lint 通过 | ✅ bash -n 通过 |
| `git diff --check` | ✅ 通过 | ✅ 通过 |
| 完整 markdown lint | ✅ 0 issues | ✅ 0 issues |
| **P3 result=pass 前置门** | ❌ 缺 | — |
| **预算门** | ❌ 缺 | ❌ 移除等于取消 |
| **依赖闭环** | ❌ 缺（脚本未入仓） | ❌ 插件未入仓 |
| **非交互确认** | — | ❌ default 非交互 |
| **集成阻断** | ❌ 1/1 分叉 | ❌ 1/1 分叉 |

## 2. 集成阻断详解（关键）

### 2.1 当前分支拓扑

```
dd527e7 (main, origin/main)
    │
    ├── 9055389 (codex/needs-human-001-plist-20260817)
    │     └── 1/1 fork from b9fa370
    │
    └── 188de4a (codex/needs-human-002-script-20260817)
          └── 1/1 fork from b9fa370
```

`git merge --ff-only codex/needs-human-001-plist-20260817` 要求 main 包含其 base commit。当前 main=dd527e7，base=b9fa370，main 比 base 多 3 commit（`f34d1cf`（cleanup 决策）+ `b9fa370`（全部批准记录）+ `dd527e7`（NO-GO 审计））。**因此 ff-only 失败**。

### 2.2 替代方案（不可用）

- ❌ `git merge --no-ff`：会产生 merge commit；非项目惯例（docs-only 任务用 ff-only）
- ❌ `git rebase`：会改写 9055389 历史；与 docs-only 项目惯例冲突
- ❌ 单独 cherry-pick：commit 内容已包含上述缺陷（SOL FAIL 项未解决）

### 2.3 推荐路径

- ✅ 新建单一分支 `codex/needs-human-unified-fix-20260817` 基于 main=dd527e7
- ✅ 单 commit 包含所有 6 项 SOL 阻断修复
- ✅ 完成后重新 SOL 终审（PASS 后 ff-only + push）

## 3. SOL 阻断项修复设计（待用户批准实施）

### 3.1 -001 plist 阻断修复

| SOL 阻断 | 修复内容 |
|---------|---------|
| **P3 result=pass 前置门** | 在 `ProgramArguments` 之前增加 `<key>WatchPaths</key>` 或 `<key>RunConditions</key>` 调用 P3 验证；或新增 `pre-flight-check.sh` wrapper |
| **预算门** | 增加 `EnvironmentVariables` 中 `MAX_BUDGET_USD`；或 wrapper 脚本内部强制 |
| **依赖闭环** | `ops/run-claude-p3-watch.sh` 必须先入仓（同 -002） |

### 3.2 -002 script 阻断修复

| SOL 阻断 | 修复内容 |
|---------|---------|
| **非交互确认** | 移除 `--permission-mode default`（等价非交互）；改用 `--permission-mode acceptEdits`（仅接受 edit 类） 或自定义 wrapper 逐次 prompt |
| **预算上限** | 恢复 `--max-budget-usd 1`（保留费用上限） |
| **插件入仓** | `plugins/p3-ops-claude/` 5 文件全部 tracked（不再 WIP） |

### 3.3 统一分支 commit 设计（草案）

单 commit 包含：
1. `ops/claude-p3-watch-launchd.plist.template`（重命名 .example → .template）
   - RunAtLoad=false
   - 增加 WatchPaths 触发 P3 验证前置
   - EnvironmentVariables 含 MAX_BUDGET_USD
2. `ops/run-claude-p3-watch.sh`
   - 移除 dontAsk/default；改用 wrapper 逐次 prompt 模式
   - 恢复 --max-budget-usd 1
   - stderr 重定向
3. `plugins/p3-ops-claude/` 5 文件 tracked 入仓
   - README.md
   - .claude-plugin/plugin.json
   - commands/p3-rollover.md
   - commands/p3-watch.md

### 3.4 工作量评估

- plist 修改：~10 行
- script 修改：~15 行（含 wrapper 设计）
- plugins 入仓：5 文件新增（已存在 untracked）
- 总体：中等工作量；需 SOL 终审后 ff-only + push

## 4. 当前状态保留

### 4.1 保留项

- `codex/needs-human-001-plist-20260817` @ `9055389`：保留分支（含 FAIL commit 历史）
- `codex/needs-human-002-script-20260817` @ `188de4a`：保留分支（含 FAIL commit 历史）
- 2 个 worktree：保留（不删）
- 主树 5 项未跟踪 WIP + 副树 d6102 9 条 WIP：保留

### 4.2 待关闭任务

- `TASK-needs_human-20260816-001-claude-p3-watch-plist.yaml`：status=needs_human → failed（SOL FAIL）
- `TASK-needs_human-20260816-002-claude-p3-watch-script.yaml`：status=needs_human → failed（SOL FAIL）
- `TASK-needs_human-20260816-003-quality-snapshot-d6102.yaml`：status=no_go（已关闭）

跟踪文档 `docs/eval/audit/needs-human-tracking-2026-08-16.md` §6 表格待下次 docs-only commit 更新。

## 5. 边界

- 不 merge 任何 FAIL commit
- 不 push 任何 FAIL commit
- 不 load plist
- 不跑 `ops/run-claude-p3-watch.sh`
- 不启用 Feature Flag / `ENABLE_*`
- 不动 plugins/（除非新建统一分支后批准）

## 6. 已验证 / 未验证

### 6.1 已验证

- ✅ SOL FAIL 结论（用户提供）
- ✅ 2 commit 的 base=b9fa370（不是 main=dd527e7）
- ✅ 当前 main=dd527e7，origin/main=dd527e7，ahead/behind=0/0
- ✅ 2 个 worktree 仍存在
- ✅ 全量 lint：334 文件 0 issues

### 6.2 未验证

- ❌ SOL review 实际运行位置（用户提供；信任）
- ❌ 修复方案是否满足 SOL 要求（需实施后重审）

## 7. 推荐下一步动作

1. **本任务**：commit + ff-only + push（docs-only 记录）
2. **本任务后**：用户单独决定是否启动「统一修复分支」（选项 B）；如不启动，2 FAIL commit 永久保留作为历史快照
3. **不建议**：merge 任何 FAIL commit；push ahead；用 cherry-pick 偷渡

## 8. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-needs-human-sol-fail-record-20260817`，分支 `codex/needs-human-sol-fail-record-20260817`。
- 基线：main=`dd527e7`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-17T11:30:00Z`（写入时）。
- SOL reviewer：`gpt-5.6-sol`（用户提供外部运行结论）。
