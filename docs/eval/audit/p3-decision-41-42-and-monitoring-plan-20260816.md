# P3 决策记录 — §4.1 plugins 处置 + §4.2 v1.1-A 路径选择(2026-08-16)

## 0. TL;DR

- **决策时间**：`2026-08-16T21:00:00Z`
- **决策者**：用户「4.1-4.2 全做」
- **§4.1 plugins 处置**：选 **A. 维持 untracked WIP**（理由见 §2.4 审计）
- **§4.2 v1.1-A 短期路径**：选 **B. 监测，8/19 末重新审计**
- **新增文件**：1 个决策记录 + 1 个 8/19 任务包（详见 §3）
- **冻结维持**：未改 caffeinate、未改 launchd、未动 plugins/、未 push ahead

## 1. §4.1 决策：plugins/p3-ops-claude 处置 → A

### 1.1 决策

维持 `plugins/p3-ops-claude/`（5 文件）+ `ops/claude-p3-watch-{launchd.plist.example,run-claude-p3-watch.sh}` 为 **untracked WIP**；不入仓不归档不清理。

### 1.2 理由复核（与 8/16 审计 §2.4 一致）

| 维度 | A 维持 WIP | B 入仓 tracked |
|------|-----------|---------------|
| 内容性质 | 个人 Claude Code 编排（作者 Mr-PRY） | 团队资产 |
| 与主仓耦合 | 只读映射既有 scripts/ | 需引入新工具链 |
| 撞坑 #103 风险 | 中（与主仓逻辑耦合需单独审计） | 低（已 docs 化） |
| 与 freeze 兼容性 | ✅ 维持现状 | ❌ 需另开 worktree 跨 freeze |
| 文档可发现性 | ❌ 个人/小圈可见 | ✅ 新成员可见 |

### 1.3 后续维护约定

- 不主动修改 `plugins/p3-ops-claude/` 内容
- 不引入新 `claude --plugin-dir` 调用（除非用户单独批准）
- 若未来需修改：`git mv` 入仓路径需新 worktree + 用户授权
- 持续 untracked 状态；不写入 `.gitignore`（保持可见性，便于审计）

### 1.4 触发重新评估的条件

- 主仓 P3 脚本（`scripts/p3_rollover_epoch.py` / `watch_p3_ops.py` 等）有破坏性变更 → 评估插件兼容性
- Claude Code / Codex 工具链升级 → 评估 plugin.json schema 兼容
- 用户单独决定入仓 → 开常规 code worktree 实施

## 2. §4.2 决策：v1.1-A 短期路径 → B

### 2.1 决策

走 **监测路径 B**：8/19 末（北京时间 2026-08-19 23:59 CST / UTC 15:59）重新审计 8/16-8/19 期间 health/news gap 情况。

- **若 8/16-8/19 期间持续 gap**（macOS 仍睡眠）→ 切路径 A（caffeinate 续期 + 系统睡眠关闭）
- **若 8/16-8/19 期间 gap 显著减少或消失**（机器已醒）→ 维持 B，等待 7d 时间门 `2026-08-20T08:42:06Z`

### 2.2 当前触发条件（截止 8/16 21:00 CST）

- 7d 时间门：**最早 `2026-08-20T08:42:06Z`（UTC）= `2026-08-20T16:42:06 CST`**，距今 ≈ 3.78 天
- 30d 时间门：**最早 `2026-09-12T08:42:06Z（UTC）= 2026-09-12T16:42:06 CST`**，距今 ≈ 26.78 天
- 当前 attention：仍在 `health_sample_gap / news_run_gap`（8/14 日报）；8/15-8/16 健康采样近乎停摆

### 2.3 8/19 末重新审计检查清单

**前置读取（只读）**：

```bash
# 当前 epoch marker
cat "$HOME/Library/Application Support/MyAIEmployee/burn-in/state.json"

# 健康采样：8/16-8/19 每日样本数
python3 -c "
import json
from collections import Counter
with open('$HOME/Library/Application Support/MyAIEmployee/health/samples.jsonl') as f:
    samples = [json.loads(l) for l in f if l.strip()]
days = Counter()
for s in samples:
    t = s.get('sample', {}).get('captured_at', '')
    day = t[:10]
    if day in {'2026-08-16', '2026-08-17', '2026-08-18', '2026-08-19'}:
        days[day] += 1
for day in sorted(days):
    print(f'{day}: {days[day]} samples')
"

# 新闻运行：8/16-8/19 每日次数
python3 -c "
import json
from collections import Counter
with open('$HOME/Library/Application Support/MyAIEmployee/news/runs.jsonl') as f:
    runs = [json.loads(l) for l in f if l.strip()]
days = Counter()
for r in runs:
    t = r.get('at', '')
    day = t[:10]
    if day in {'2026-08-16', '2026-08-17', '2026-08-18', '2026-08-19'}:
        days[day] += 1
for day in sorted(days):
    print(f'{day}: {days[day]} runs')
"

# launchd 当前状态
launchctl list | grep myaiemployee

# 当前 p3-awake plist caffeinate 参数
grep -A2 'caffeinate' ~/Library/LaunchAgents/com.myaiemployee.p3-awake.plist 2>&1 | head -10
```

**判定规则**：

| 8/16-8/19 健康采样均值 | 8/16-8/19 新闻运行均值 | 判定 | 后续 |
|----------------------|---------------------|------|------|
| ≥ 100 / 天 | ≥ 18 / 天 | ✅ gap 已消除 | 维持 B；7d 窗口 `2026-08-20T08:42:06Z` 自然观察 |
| 50-100 / 天 | 12-18 / 天 | ⚠️ 部分恢复 | 8/19 末建议切 A（caffeinate 续期） |
| < 50 / 天 | < 12 / 天 | ❌ 持续停摆 | **必须切 A**（caffeinate 续期 + 系统睡眠关闭） |

### 2.4 切路径 A 的具体动作（如触发）

- 检查 `~/Library/LaunchAgents/com.myaiemployee.p3-awake.plist` 中 `caffeinate -i -t <N>` 参数；若已到期，重设为 30d 或无限期 `-i`（去掉 `-t`）
- 系统设置：电源管理 → 防止在电源适配器上睡眠（macOS Ventura+）；`pmset -c disablesleep 1`（需 sudo）
- 不重启 launchd；不重启 daemon；保留现有 p3 epoch

### 2.5 不做的事

- 不二次 rollover（路径 B 监测中）
- 不改 `scripts/p3_burn_in_report.py` 资格逻辑（路径 C 不推荐）
- 不启用 Feature Flag / `ENABLE_*`
- 不打 v1.0 / v1.1 tag
- 不修改 11 项未跟踪 WIP

## 3. 新增文件清单

```
docs/eval/audit/p3-decision-41-42-and-monitoring-plan-20260816.md    ← 本文件
docs/agent-team/tasks/TASK-20260819-001-p3-gap-reaudit.yaml          ← 8/19 重新审计任务包（queued）
MODIFICATION-LOG.md                                                   ← 决策条目
```

## 4. 与上次审计的关联

- **依赖**：[docs/eval/audit/p3-gap-root-cause-and-plugins-inventory-20260816.md](p3-gap-root-cause-and-plugins-inventory-20260816.md)（§2 plugins + §3 gap + §4 三路径）
- **基线 commit**：`a67a5ed docs(p3): gap 根因与 plugins 盘点审计`
- **branch**：`codex/p3-decision-record-20260816`
- **worktree**：`/tmp/wt-p3-decision-record-20260816`
- **HEAD**：`a67a5ed`（待本任务 commit 后前进 1）

## 5. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 决策者：用户「4.1-4.2 全做」→ 选 §4.1 A + §4.2 B
- 时点：`2026-08-16T21:00:00Z`（写入时）
