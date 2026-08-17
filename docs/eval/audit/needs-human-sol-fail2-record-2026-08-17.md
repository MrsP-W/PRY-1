# Needs-Human SOL FAIL #2 记录 + v2 修复设计(2026-08-17)

## 0. TL;DR

- **触发**：SOL 终审结论 #2（用户外部运行 `gpt-5.6-sol`）
- **结论**：`698d974` (unified-fix) **FAIL** — 6 项新增阻断（v1 设计缺陷）
- **新增 6 项阻断**：main 工作树 ff-only dry-run exit 128 / pre-flight JSON 解析错误 / PATH 缺 `/opt/homebrew/bin` / `--permission-prompt-tool` 注释失实 / 旧 `.plist.example` 未真重命名 / `$12/天` 不符合零预算
- **当前状态**：2 个 -001/-002 FAIL 分支 + 1 个 unified-fix FAIL 分支 = 3 个历史快照保留
- **建议**：v2 修复（不实施，等用户批准）

## 1. SOL 终审结论（外部运行）

### 1.1 输入格式

```yaml
SOL REVIEW RESULT: 698d974 (unified-fix): FAIL — 当前 main 工作树不可 ff-only，且 P3 前置门、PATH 与非交互权限语义仍有阻断
REVIEWED BY: gpt-5.6-sol
REVIEWED AT: 2026-08-17T01:39:19Z
```

### 1.2 SOL 6 项新增阻断

| # | 阻断 | v1 缺陷 | v2 修复方向 |
|---|------|---------|------------|
| 1 | **main 工作树不可 ff-only** | `ops/run-claude-p3-watch.sh` 是 untracked；merge 会 overwrite（dry-run exit 128） | merge 前从主工作树 `mv` 到 `/tmp` 临时目录；merge 后可选清理 |
| 2 | **pre-flight JSON 解析错误** | `VERIFY_RESULT=$(...)` 捕获完整 JSON；`[ "$VERIFY_RESULT" != "pass" ]` 永远 != pass | `jq -r .result` 或 `python3 -c "import sys,json;print(json.load(sys.stdin)['result'])"` |
| 3 | **launchd PATH 缺 `/opt/homebrew/bin`** | plist `PATH=/usr/local/bin:/usr/bin:/bin`；Apple Silicon 上 uv 在 `/opt/homebrew/bin` | PATH 增加 `/opt/homebrew/bin`（优先）+ `/usr/local/bin`（Intel 兼容）|
| 4 | **--permission-prompt-tool 注释失实** | MODIFICATION-LOG 和 audit 注释声称使用；实际未传；当前 CLI 不支持 | 移除注释声称；明确"无 --permission-mode"，依赖 shell wrapper 逐次 prompt 或改走 Python 直接路径 |
| 5 | **旧 .plist.example 仍在** | main 工作树未跟踪的 `.example`（含 `RunAtLoad=true`）未真删除 | merge 后立即 `rm ops/claude-p3-watch-launchd.plist.example`（仅在主工作树 merge 成功且脚本改名 `.template` 后） |
| 6 | **`$12/天` 不符合零预算诊断口径** | `--max-budget-usd 1` × 12 runs/day = $12/day 上限 | 改为 `--max-budget-usd 0`（零预算诊断）；或更彻底——不调用 `claude`，直接调 `scripts/watch_p3_ops.py`（纯本地，零成本） |

### 1.3 SOL 静态检查

- ✅ `plutil -lint`：OK
- ✅ `bash -n`：OK
- ✅ `git diff --check`：0 errors
- ✅ 完整 markdown lint：336 文件 0 issues
- ❌ 静态检查**不足以放行**——上述 6 项均为运行时/集成语义问题

## 2. v2 修复设计

### 2.1 plist 修改（v1 → v2）

```diff
   <key>EnvironmentVariables</key>
   <dict>
-    <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin</string>
+    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
     <key>MAX_BUDGET_USD</key><string>1</string>
   </dict>
```

### 2.2 script 修改（v1 → v2）：pre-flight + 零预算 wrapper

```bash
#!/usr/bin/env bash
# 沿用 needs-human-sol-fail2-record-2026-08-17 §2.2 v2 修复设计
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${HOME}/Library/Logs/MyAIEmployee"
ERR_LOG="${HOME}/Library/Logs/MyAIEmployee/claude-p3-watch.err.log"

# P3 pre-flight 检查（解析 JSON，仅比较 .result 字段）
# 修复 SOL -002 阻断 "pre-flight 把完整 JSON 与 "pass" 比较"
VERIFY_JSON=$(uv run python3 "${PROJECT_ROOT}/scripts/verify_p3_first_daily.py"   --app-support-dir "${HOME}/Library/Application Support/MyAIEmployee"   2>>"$ERR_LOG" || echo '{"result": "error"}')
VERIFY_RESULT=$(printf '%s' "$VERIFY_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result', 'error'))")
if [ "$VERIFY_RESULT" != "pass" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) P3 pre-flight FAIL (result=$VERIFY_RESULT); skip" >>"$ERR_LOG"
  exit 0
fi

# 零预算诊断：直接调本地脚本，不调用 claude
# 修复 SOL -006 阻断 "$12/天 不符合零预算诊断口径"
exec uv run python3 "${PROJECT_ROOT}/scripts/watch_p3_ops.py"   --app-support-dir "${HOME}/Library/Application Support/MyAIEmployee"   2>>"$ERR_LOG"
```

### 2.3 删除旧 `.plist.example`

仅在 merge 成功**之后**，主工作树内：
```bash
rm ops/claude-p3-watch-launchd.plist.example
```

### 2.4 merge 前清理 main 工作树 untracked

为避免 merge 时 overwrite 失败（SOL -001 阻断），执行：
```bash
mkdir -p /tmp/needs-human-v2-merge-stash-20260817
mv ops/run-claude-p3-watch.sh ops/claude-p3-watch-launchd.plist.example    /tmp/needs-human-v2-merge-stash-20260817/
mv plugins /tmp/needs-human-v2-merge-stash-20260817/
# 合并后清理 /tmp 临时目录
```

### 2.5 MODIFICATION-LOG / 注释修复

- 移除 "显式 --permission-prompt-tool" 注释（SOL -004 阻断）
- 替换为 "零预算诊断：直接调本地 watch_p3_ops.py"

## 3. v2 修复 commit 设计

单 commit 包含：
1. `ops/claude-p3-watch-launchd.plist.template`：PATH 增加 `/opt/homebrew/bin`
2. `ops/run-claude-p3-watch.sh`：pre-flight JSON 解析 + 零预算 wrapper（不调 claude）
3. MODIFICATION-LOG：修正注释（移除 --permission-prompt-tool 声称；明确"零预算诊断"）

**集成结构**：
- 仍基于 `main=a30b9ca` 直接 commit（避免兄弟分支）
- 工作量：小（≈30 行）
- 风险：低（零预算本地脚本，不调外部 API）

## 4. 当前 pending 3 分支

```
codex/needs-human-001-plist-20260817        9055389  ← FAIL #1 (历史快照)
codex/needs-human-002-script-20260817       188de4a  ← FAIL #1 (历史快照)
codex/needs-human-unified-fix-20260817      698d974  ← FAIL #2 (历史快照)
```

3 个分支均保留为失败历史快照；不解锁 needs_human；待 v2 实施后重新 SOL 终审。

## 5. needs_human 状态矩阵更新

| 任务 | v1 状态 | v2 状态 |
|------|---------|--------|
| `TASK-needs_human-20260816-001` | failed（SOL FAIL #1）| failed（v1 + v2 都未实施） |
| `TASK-needs_human-20260816-002` | failed（SOL FAIL #1）| failed（v1 + v2 都未实施） |
| `TASK-needs_human-20260816-003` | no_go（cherry-pick 回退基线）| no_go（维持） |

跟踪文档 `needs-human-tracking-2026-08-16.md` §6 表格待下次 docs-only commit 同步。

## 6. 边界

- 不 merge 任何 FAIL commit（包括 v1 unified-fix）
- 不 push ahead
- 不 load plist
- 不跑 v1 script（pre-flight JSON 解析错误 + claude 调用 $12/天）
- 不启用 Feature Flag / `ENABLE_*`
- 不删 3 个历史快照分支（保留作为失败参考）

## 7. 已验证 / 未验证

### 7.1 已验证

- ✅ SOL FAIL #2 结论（用户提供）
- ✅ 6 项新增阻断的具体代码位置
- ✅ 当前 main=a30b9ca=origin/main，ahead/behind=0/0
- ✅ 全量 lint：336 文件 0 issues
- ✅ 3 个历史快照分支保留
- ✅ 主树 5 项 untracked（含旧 `.plist.example` 与 `run-claude-p3-watch.sh`）

### 7.2 未验证

- ❌ `/opt/homebrew/bin/uv` 在 launchd 环境下的实际可达性（需用户环境实测）
- ❌ `scripts/watch_p3_ops.py` 是否完全替代 claude `/p3-watch` 命令的功能
- ❌ v2 修复后实际 SOL 终审结论

## 8. 推荐下一步动作

1. **本任务**：commit + ff-only + push（docs-only 记录）
2. **本任务后**：用户单独决定是否启动 v2 修复；启动后开 `codex/needs-human-unified-fix-v2-20260817` 分支
3. **不建议**：merge 任何 FAIL commit；删历史快照分支；用当前 v1 实施

## 9. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-needs-human-sol-fail2-record-20260817`，分支 `codex/needs-human-sol-fail2-record-20260817`。
- 基线：main=`a30b9ca`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-17T12:00:00Z`（写入时）。
- SOL reviewer：`gpt-5.6-sol`（用户提供外部运行结论 #2）。
