# Needs-Human 跟踪审计 — B 类 3 项(2026-08-16)

## 0. TL;DR

- **范围**：docs-only 建 needs_human 跟踪；不动 B 类 3 项脚本本身，仅记录原因 + 路径 + 等待条件
- **B 类 3 项**（沿用 `wip-inventory-2026-08-16` §1.2 + §2.3）：
  - `ops/claude-p3-watch-launchd.plist.example`（主树，14 行）
  - `ops/run-claude-p3-watch.sh`（主树，9 行）
  - `src/my_ai_employee/quality_snapshot.py`（副树 d6102-stash-playbook，8 行 diff）
- **新增**：1 跟踪文档 + 3 needs_human 任务包
- **状态**：3 项均待 `needs_human`；不主动修改；等用户单独授权

## 1. 上下文与背景

### 1.1 上次校准以来的链路

| 时间 | commit | 内容 |
|------|--------|------|
| 8/16 21:00 | `089815e` | §4.1-4.2 决策 + 8/19 监测计划 |
| 8/16 21:30 | `ee66713` | WIP 盘点审计（主树 11 项 + 副树 9 条） |
| 8/16 22:00 | `99f3832` | A 类 6 项主树 WIP 入仓 |
| **8/16 22:30** | **本任务** | **B 类 3 项 needs_human 跟踪** |

### 1.2 wip-inventory §1.2 / §2.3 结论回顾

**B 类判定标准**（沿用）：

- 触及 LaunchAgent 红线
- 涉及 `dontAsk` / 自动运行 / 外部写入
- 业务代码改动（撞坑 #104/#105/#107 历史）
- 不入仓跨 freeze；不修复；不清理

### 1.3 目标

固化 3 项 needs_human 状态，避免与 A 类入仓混淆；建立追踪机制；等用户单独决定。

## 2. needs_human-001 — claude-p3-watch-launchd.plist

### 2.1 文件

- 路径：`ops/claude-p3-watch-launchd.plist.example`（主树 untracked，14 行）
- 时间戳：2026-08-04 16:09（与 §4.1 plugins/ 同批创建）
- 内容：launchd plist 模板，含 `<key>RunAtLoad</key><true/>` + `StartInterval=7200`

### 2.2 风险（继承 wip-inventory §1.2）

| 风险点 | 说明 |
|--------|------|
| LaunchAgent 红线 | `<key>RunAtLoad</key><true/>` 一旦复制到 `~/Library/LaunchAgents/` 立即生效 |
| `RunAtLoad=true` | 触发后每 2h 自动执行 `claude --permission-mode dontAsk --max-budget-usd 1 --print /p3-watch` |
| 无 P3 漂移检测 | plist 模板未含 P3 epoch 状态检查；空跑也会触发 attention |
| 与 `com.myaiemployee.p3-awake` 冲突 | 当前 PID 1708（caffeinate -i -t）；与 plist 调度无去重 |

### 2.3 解除 needs_human 条件

- 用户单独以「批准 ops/claude-p3-watch 入仓」关键词触发
- 触发后开常规 code worktree（非常规 docs-only），实施：
  - 修改 `RunAtLoad=true` → `RunAtLoad=false`（手动 load 验证）
  - 增加 P3 状态检查前置（`script result=$(python3 scripts/verify_first_daily.py)` 仅当 `result=pass` 才跑）
  - 增加 `--max-budget-usd 0`（仅诊断，不花钱）
  - 修改文件后缀 `.plist.example` → `.plist.template`（明示未安装）

### 2.4 不做的事

- 不自动 load plist
- 不复制到 `~/Library/LaunchAgents/`
- 不改 `RunAtLoad=true`
- 不与 P3 自动联动

## 3. needs_human-002 — claude-p3-watch.sh

### 3.1 文件

- 路径：`ops/run-claude-p3-watch.sh`（主树 untracked，9 行）
- 时间戳：2026-08-04 16:09
- 内容：`exec claude --plugin-dir plugins/p3-ops-claude --permission-mode dontAsk --max-budget-usd 1 --print "/p3-watch"`

### 3.2 风险（继承 wip-inventory §1.2）

| 风险点 | 说明 |
|--------|------|
| `--permission-mode dontAsk` | Claude 自动决策；可执行 `git push` / `kill` / `mv` 等任意命令 |
| `--max-budget-usd 1` | 限制成本但仍自动运行；每 2h 触发一次 = 12 次/天 ≈ $12/天上限 |
| 与 P3 主路径耦合 | `/p3-watch` 命令可触发 `verify_p3_first_daily.py --force`（plugin 文档禁止但 CLI 未强校验） |
| 输出 JSON 无审计 | stdout 仅 `--print` 模式；无 log 文件、无 stdout 捕获、无 alert |

### 3.3 解除 needs_human 条件

- 用户单独以「批准 run-claude-p3-watch 入仓」关键词触发
- 触发后开常规 code worktree，实施：
  - 修改 `--permission-mode dontAsk` → `--permission-mode default`（每次需确认）
  - 移除 `--max-budget-usd 1`（或改为 `0` 仅诊断）
  - 增加 `set -euo pipefail` 严格 shell 模式
  - 加 stderr 重定向到 `~/Library/Logs/MyAIEmployee/claude-p3-watch.err.log`

### 3.4 不做的事

- 不实际跑 `ops/run-claude-p3-watch.sh`
- 不启用 `dontAsk` 模式
- 不预设 `--max-budget-usd`
- 不与 launchd plist 联动（plist 单独跟踪）

## 4. needs_human-003 — quality_snapshot.py（副树）

### 4.1 文件

- 路径：`src/my_ai_employee/quality_snapshot.py`（副树 `codex/d6102-stash-playbook`）
- 状态：M（modified），8 行 diff
- 副树 HEAD：`a1c8469`（7/28）
- 副树落后 main ≈ 4 周（108 files / 7494 deletions）

### 4.2 风险（继承 wip-inventory §2.3）

| 风险点 | 说明 |
|--------|------|
| 业务代码改动 | 撞坑 #104/#105/#107 历史漂移源头之一 |
| 副树未通过 SOL 终审 | 落后 main 4 周，缺 ruff/mypy/pytest 验证 |
| 与 main `quality_snapshot.py` 漂移 | main 版本已 tracked；副树 8 行 diff 未同步 |
| 不可独立 cherry-pick | 涉及 baseline drift（quality snapshot 数字与 SESSION-STATE 一致性） |

### 4.3 解除 needs_human 条件

- 用户单独以「批准 d6102 quality_snapshot 集成」关键词触发
- 触发后开常规 code worktree，实施：
  - 单独 cherry-pick 副树 `src/my_ai_employee/quality_snapshot.py` 的 8 行 diff
  - 评估与 main 当前版本的兼容性（main 自 7/28 已前进 4 周）
  - 跑 ruff/mypy/pytest 实测通过
  - 更新 SESSION-STATE 中 quality baseline 数字
  - 通过 SOL 终审

### 4.4 不做的事

- 不 cherry-pick 副树到 main
- 不 reset 副树分支
- 不合并副树到 main
- 不动副树其他 8 项 WIP（仅关注 quality_snapshot.py）

## 5. needs_human 跟踪机制

### 5.1 任务包命名约定

```
TASK-needs_human-YYYYMMDD-NNN-{slug}.yaml
```

### 5.2 状态机

```
queued (initial)
   │
   ▼
pending_user_review    ← 用户单独授权触发关键词
   │
   ▼
approved               ← 用户说「批准 XX」或类似
   │
   ▼
in_progress            ← 常规 code worktree 启动
   │
   ▼
done | needs_human | blocked
```

### 5.3 触发授权关键词

| needs_human | 用户授权关键词示例 |
|------------|------------------|
| -001 plist | "批准 ops/claude-p3-watch 入仓" |
| -002 script | "批准 run-claude-p3-watch 入仓" |
| -003 snapshot | "批准 d6102 quality_snapshot 集成" |

### 5.4 跟踪汇总表（沿用本审计）

每次 needs_human 状态变化必须更新本文件 §6 表格。

## 6. 当前状态（截至 2026-08-16 22:30）

| ID | 文件 | 类别 | 状态 | 上次更新 | 触发关键词 |
|----|------|------|------|---------|-----------|
| needs_human-001 | `ops/claude-p3-watch-launchd.plist.example` | LaunchAgent 红线 | queued | 2026-08-16 22:30 | 「批准 ops/claude-p3-watch 入仓」 |
| needs_human-002 | `ops/run-claude-p3-watch.sh` | dontAsk 自动运行 | queued | 2026-08-16 22:30 | 「批准 run-claude-p3-watch 入仓」 |
| needs_human-003 | `src/my_ai_employee/quality_snapshot.py`（副树） | 代码 + 漂移 | queued | 2026-08-16 22:30 | 「批准 d6102 quality_snapshot 集成」 |

## 7. 已验证 / 未验证边界

### 7.1 已验证

- ✅ 3 项 B 类文件路径、时间戳、内容
- ✅ 主树 5 项剩余未跟踪（B 类 2 + C 类 3，含 plugins/）
- ✅ 副树 9 条 WIP 状态
- ✅ 触发授权关键词（约定）
- ✅ needs_human 任务包命名约定

### 7.2 未验证

- ❌ needs_human 任务包的 Pydantic schema 校验（项目无 schema）
- ❌ 3 项 B 类脚本实际安全性测试
- ❌ 副树 8 行 diff 与 main 当前版本的逐行对照

### 7.3 边界与不做

- 不入仓 B 类 3 项脚本
- 不修改 B 类 3 项脚本
- 不跑 `ops/run-claude-p3-watch.sh` 或 `claude --plugin-dir plugins/p3-ops-claude`
- 不 load launchd plist
- 不 cherry-pick 副树
- 不 push / merge / 打 tag
- 不启用 Feature Flag / `ENABLE_*`

## 8. 推荐下一步动作

1. **本周（你决定）**：3 项 needs_human 是否触发授权关键词
   - 若不触发：维持 queued 状态，下次再盘点
   - 若触发：开常规 code worktree 单独处理
2. **本周（你决定）**：副树 `codex/d6102-stash-playbook` 整体处置（维持 / rebase+cherry-pick / 归档）
3. **8/19 末**（系统触发）：TASK-20260819-001 re-audit

## 9. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-needs-human-tracking-20260816`，分支 `codex/needs-human-tracking-20260816`。
- 基线：main=`99f3832`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-16T22:30:00Z`（写入时）。
