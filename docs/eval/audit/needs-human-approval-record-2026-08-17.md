# Needs-Human 全部批准记录(2026-08-17)

## 0. TL;DR

- **触发**：用户「全部批准」(2026-08-17 上午)
- **批准范围**：3 项 needs_human 任务包（沿用 `needs-human-tracking-2026-08-16` §6）
  - `TASK-needs_human-20260816-001-claude-p3-watch-plist.yaml`
  - `TASK-needs_human-20260816-002-claude-p3-watch-script.yaml`
  - `TASK-needs_human-20260816-003-quality-snapshot-d6102.yaml`
- **本记录**：docs-only；**不动脚本本身**
- **下一步**：开 3 个常规 code worktree 实施修改；commit 后**不 push**（等 SOL 终审 + 显式 push 关键词）

## 1. 上下文与基线

### 1.1 链路

| 时间 | commit | 内容 |
|------|--------|------|
| 8/16 22:30 | `931b74e` | B 类 3 项 needs_human 跟踪审计 + 任务包（queued） |
| 8/17 09:30 | `e87f04a` | 副树 d6102 维持 + 副 worktree 清理决策 |
| **8/17 10:00** | **本任务** | **needs_human 全部批准记录** |

### 1.2 unlock_steps 进度

沿用 `needs-human-tracking-2026-08-16` 跟踪文档约定的 4 步：

```
1. 用户单独以触发关键词批准     ← 本任务完成
2. 开常规 code worktree 实施    ← 下一步（3 个 worktree）
3. 通过 SOL 终审              ← 待用户单独批准/跳过
4. ff-only 合入 main 后单独 push  ← 待用户显式 push 关键词
```

## 2. 3 项批准状态

| ID | 触发关键词 | 批准状态 | 下一步 |
|----|-----------|---------|--------|
| -001 plist | 「批准 ops/claude-p3-watch 入仓」 | ✅ 全部批准隐含 | code worktree 实施 |
| -002 script | 「批准 run-claude-p3-watch 入仓」 | ✅ 全部批准隐含 | code worktree 实施 |
| -003 snapshot | 「批准 d6102 quality_snapshot 集成」 | ✅ 全部批准隐含 | code worktree 实施 + 副树 cherry-pick |

## 3. 实施规范（沿用 needs-human-tracking §2-§4）

### 3.1 -001 plist 实施细节

修改 `ops/claude-p3-watch-launchd.plist.example`：

```diff
- <key>RunAtLoad</key><true/>
+ <key>RunAtLoad</key><false/>
  <key>StartInterval</key><integer>7200</integer>
- <key>ProgramArguments</key><array>
+ <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>/Users/wei/Documents/DesktopOrganizer/我的AI员工/ops/run-claude-p3-watch.sh</string>
  </array>
+ <!-- 强制 P3 状态检查前置：仅当 result=pass 才跑 -->
+ <key>EnvironmentVariables</key>
+ <dict>
+   <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin</string>
+ </dict>
```

文件重命名：`.plist.example` → `.plist.template`（明示未安装）。

### 3.2 -002 script 实施细节

修改 `ops/run-claude-p3-watch.sh`：

```diff
- #!/usr/bin/bash
+ #!/usr/bin/env bash
  # 供外部定时器调用：仅巡检和诊断，默认不自动修复。
+ set -euo pipefail

  PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
- exec claude --plugin-dir "${PROJECT_ROOT}/plugins/p3-ops-claude" -   --permission-mode dontAsk -   --max-budget-usd 1 -   --print "/p3-watch"
+ # 权限从 dontAsk 改为 default：每次操作需用户确认
+ # 移除 --max-budget-usd 1：仅诊断模式，不花 Anthropic budget
+ exec claude --plugin-dir "${PROJECT_ROOT}/plugins/p3-ops-claude" +   --permission-mode default +   --print "/p3-watch" +   2>>"${HOME}/Library/Logs/MyAIEmployee/claude-p3-watch.err.log"
```

### 3.3 -003 snapshot 实施细节

从副树 `codex/d6102-stash-playbook` @ `a1c8469` cherry-pick `src/my_ai_employee/quality_snapshot.py` 的 8 行 diff：

1. 在主工作树创建新 code worktree（基于 main）
2. `git checkout codex/d6102-stash-playbook -- src/my_ai_employee/quality_snapshot.py` 提取副树版本
3. 与当前 main 版本逐行 diff
4. 若冲突：手动 merge（基于撞坑 #104/#105/#107 教训）
5. 跑 ruff/mypy/pytest 实测
6. 更新 SESSION-STATE 中 quality baseline 数字
7. commit + SOL 终审 + push

## 4. 边界

- 不在 docs-only worktree 实施脚本改动
- 不删除 `.plist.example` 后缀名（用户决策）
- 不修改 plugins/p3-ops-claude/ 内容
- 不 load launchd plist
- 不 cherry-pick 副树其他 8 项 WIP
- 不打 tag

## 5. 已验证 / 未验证边界

### 5.1 已验证

- ✅ 3 项 needs_human 任务包已存在并 status=needs_human
- ✅ 用户「全部批准」触发 3 项 unlock_steps step 1
- ✅ 实施细节沿用 needs-human-tracking-2026-08-16 §2-§4

### 5.2 未验证

- ❌ -003 snapshot 副树 8 行 diff 实际内容（需另查）
- ❌ 修改后 ruff/mypy 实测结果
- ❌ 修改后 launchd plist 加载可行性

### 5.3 边界

- 不 push（ahead=1 待落）
- 不启用 Feature Flag / `ENABLE_*`
- 不 load launchd plist
- 不跑 `claude --plugin-dir` / `ops/run-claude-p3-watch.sh`

## 6. 推荐下一步动作

1. **本任务**：commit + ff-only + push（docs-only 记录）
2. **本任务后续**：开 3 个常规 code worktree，分别实施 -001/-002/-003；每项 commit 但不 push
3. **暂停**：等 SOL 终审（不可达 → SOL_BLOCKED）或用户显式 push 关键词

## 7. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-needs-human-approval-record-20260817`，分支 `codex/needs-human-approval-record-20260817`。
- 基线：main=`e87f04a`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-17T10:00:00Z`（写入时）。
