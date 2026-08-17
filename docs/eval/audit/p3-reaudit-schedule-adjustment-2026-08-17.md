# P3 Re-audit 时间表调整(2026-08-17)

## 0. TL;DR

- **触发**：用户纠正重评时间（避免部分日偏差）+ 扩展判定指标
- **重评时间调整**：`8/19 23:59 CST`（仅到 8/19 15:59 UTC）→ **`8/20 08:05 CST`（完整窗口 [8/16 00:00Z, 8/20 00:00Z)）**
- **决策**：**B 路径不变**；监测至 8/20 08:05 CST
- **关键修正**：`TASK-... queued` 只是任务包状态，**不等于已存在自动调度**
- **扩展判定指标**：health gap ≤ 1800s / news gap ≤ 7200s / Battery-Clamshell Sleep 关联 / launchd exit code / caffeinate 单实例
- **不做**：8/18-8/19 提前审计；A1 / pmset / rollover
- **本任务**：docs-only 决策记录 + 任务包重建（queued 状态保留；不创建自动调度）

## 1. 用户决策原始结论

```yaml
DECISION:
  path: B
  reaudit_at: "2026-08-20T08:05:00+08:00"  # 8/20 08:05 CST = 8/20 00:05 UTC
  window: "[2026-08-16T00:00:00Z, 2026-08-20T00:00:00Z)"  # 4 完整 UTC 日
  rationale: |
    8/19 23:59 CST 仅到 8/19 15:59 UTC，非完整 UTC 日；会产生部分日偏差
    8/20 08:05 CST = 8/20 00:05 UTC，覆盖完整 8/16-8/19 4 日窗口

TIMELINE:
  - now..8/20 08:05 CST: 只监测，不提前审计
  - 8/20 08:05 CST: 重评完整窗口 + 检查日计数 + health/news 最大 gap + 睡眠记录
  - 8/20 16:42 CST: 只读执行 7d 时间门核验（预期仍 NOT_UNLOCKED）
  - 8/20 17:00..8/21 18:34 CST: 仅在确定继续长期观察时，决定是否单独授权有限期 A1

CHECKLIST (extended):
  - health gap ≤ 1800 秒
  - news gap ≤ 7200 秒
  - gap 是否与 Battery/Clamshell Sleep 重合
  - launchd runs/last exit code
  - caffeinate 是否仍只有一个实例

NOT_DOING:
  - 8/18 或 8/19 早审计
  - A1、pmset、rollover

CRITICAL_NOTE:
  - TASK-... queued 只是任务包状态，不等于已存在自动调度
  - 若希望自动重评，需要单独确认或创建调度
```

## 2. 纠正 `42d51e0` 原设定错误

### 2.1 原设定（`42d51e0`）

- 重评时间：`8/19 23:59 CST`
- UTC 等价：`2026-08-19T15:59:00Z`
- 完整窗口：`[8/16 00:00Z, 8/19 15:59Z)` = 约 3.66 天
- 问题：**非完整 UTC 日**（8/19 仅 16 小时数据）→ 部分日偏差

### 2.2 用户修正

- 重评时间：`8/20 08:05 CST`（或 `08:00`）
- UTC 等价：`2026-08-20T00:05:00Z`
- 完整窗口：`[8/16 00:00Z, 8/20 00:00Z)` = 4 完整 UTC 日
- 优势：8/16-8/19 全部完整；可计算日均 + 比较跨日

### 2.3 自动调度声明

- 任务包 `TASK-20260819-001-p3-gap-reaudit` status=`queued` → **仅文档状态**
- **无实际 launchd plist / cron / scheduler** 触发 8/19 23:59 CST
- 8/20 08:05 CST 同样**无自动调度**；需用户手动触发或单独创建调度

## 3. 时间线详细规划

### 3.1 当前状态

- Day0 = `2026-08-13T08:42:06Z`
- Elapsed ≈ 4 天（截至 8/17 14:00 CST）
- v1.1-A: `NOT_UNLOCKED`（4 门槛 2 PASS / 2 FAIL）

### 3.2 时间窗

| 时点 | CST | UTC | 动作 |
|------|-----|-----|------|
| 现在 | 2026-08-17 14:00 CST | 06:00 UTC | 只监测；不提前审计 |
| 8/18 23:59 CST | — | 15:59 UTC | 监测节点（非触发） |
| 8/19 23:59 CST | — | 15:59 UTC | **不**在此触发（原计划已废弃） |
| **8/20 08:05 CST** | — | 00:05 UTC | **重评触发**：完整窗口 [8/16, 8/20) |
| 8/20 16:42 CST | — | 08:42 UTC | 7d 时间门（PID 1708 可覆盖）|
| 8/20 17:00 CST | — | 09:00 UTC | 7d 门后评估窗口 |
| **8/21 18:34 CST** | — | 10:34 UTC | A1 路径最晚审批截止（30d 续期）|
| 9/12 16:42 CST | — | 08:42 UTC | 30d 时间门（需新决策）|

### 3.3 PID 1708 caffeinate 倒计时

- 用户实测：剩余 ≈4.3 天（截至 8/17 14:00 CST）
- 预计到期：约 8/21 21:42 CST（13:42 UTC）
- 可覆盖：8/20 08:05 CST 重评 + 8/20 16:42 CST 7d 门 + 8/21 18:34 CST A1 截止

## 4. 重评扩展判定清单（沿用 + 增强）

### 4.1 基础判定（日均 vs 阈值）

| 指标 | 阈值 | 实际（8/17 14:00 估）| 含义 |
|------|------|--------------------|------|
| 8/16-8/19 健康均值 | ≥100 / 天 | 待 8/20 实测 | ✅/⚠️/❌ |
| 8/16-8/19 新闻均值 | ≥18 / 天 | 待 8/20 实测 | ✅/⚠️/❌ |

### 4.2 扩展判定（用户新增）

| 检查项 | 阈值 | 8/20 实测方法 |
|--------|------|----------------|
| **health gap** | ≤ 1800 秒 | `samples.jsonl` 计算所有 gap；max 1800s 通过 |
| **news gap** | ≤ 7200 秒 | `runs.jsonl` 计算所有 gap；max 7200s 通过 |
| **Battery/Clamshell Sleep 关联** | 无 gap 与 sleep 重合 | 读 `pmset -g log` 或 `/var/log/pmset.log`；gap 时间与 lid close 时间不重合 |
| **launchd runs/last exit code** | exit 0 或非 0 | `launchctl print` 看 com.myaiemployee.*；不出现异常 exit |
| **caffeinate 单实例** | 仅 1 个进程 | `pgrep caffeinate | wc -l` = 1；PID 仍为 1708 |

### 4.3 判定路径（重评）

- ✅ 全部通过 → 维持 B 监测；7d 时间门核验后可能 NOT_UNLOCKED（历史 attention）
- ⚠️ 部分通过（health 部分 / news 部分） → 8/20 17:00 CST 决策是否 A1
- ❌ 任一不通过 + Battery Sleep 重合 → 必须 A1；用户单独以「授权 A1 路径」触发

## 5. 8/20 08:05 CST 重评执行清单

### 5.1 前置读取（只读）

```bash
# 1. state.json
cat "$HOME/Library/Application Support/MyAIEmployee/burn-in/state.json"

# 2. 8/16-8/19 每日健康采样计数
python3 -c "
import json
from collections import Counter
samples = [json.loads(l) for l in open('$HOME/Library/Application Support/MyAIEmployee/health/samples.jsonl') if l.strip()]
days = Counter()
for s in samples:
    t = s.get('sample', {}).get('captured_at', '')[:10]
    if t in {'2026-08-16','2026-08-17','2026-08-18','2026-08-19'}:
        days[t] += 1
for d in sorted(days): print(f'{d}: {days[d]}')
"

# 3. 8/16-8/19 每日新闻运行计数
python3 -c "
import json
from collections import Counter
runs = [json.loads(l) for l in open('$HOME/Library/Application Support/MyAIEmployee/news/runs.jsonl') if l.strip()]
days = Counter()
for r in runs:
    t = r.get('at', '')[:10]
    if t in {'2026-08-16','2026-08-17','2026-08-18','2026-08-19'}:
        days[t] += 1
for d in sorted(days): print(f'{d}: {days[d]}')
"

# 4. health/news 最大 gap
python3 -c "
import json
# 计算所有 gap；按用户阈值 1800/7200 判定
"
# 5. Battery Sleep 关联
pmset -g log 2>&1 | head -50
# 6. launchd exit code
launchctl print user/$(id -u) 2>&1 | grep -A2 'com.myaiemployee'
# 7. caffeinate 单实例
pgrep caffeinate
```

### 5.2 判定输出

- docs-only 报告：docs/eval/audit/p3-reaudit-2026-08-20.md
- 提交 docs-only + ff-only + push

## 6. 不做项（硬边界，与 `42d51e0` 一致）

- `sudo pmset`
- 无限期 caffeinate
- 第二个 caffeinate 进程
- 二次 rollover
- 提前 8/18-8/19 审计（用户明确禁止）
- A1 路径（除非 8/20 判定触发 + 用户单独授权）
- 系统电源策略修改
- plist 修改 / load / unload
- 自动化调度创建（除非用户单独确认）

## 7. 任务包重建

### 7.1 现状

- `TASK-20260819-001-p3-gap-reaudit`：status=`queued`（文档状态，无调度）
- 实际触发点：8/20 08:05 CST（用户决定）；非 8/19 23:59 CST

### 7.2 重建方案

- 选项 A：保留 `TASK-20260819-001` 但更新 depends_on 与 acceptance_commands 反映新时点
- 选项 B：新建 `TASK-20260820-001-p3-gap-reaudit`（更清晰反映 8/20 重评）
- 推荐：选项 B（避免命名误导）

### 7.3 本任务范围

- 重建 `TASK-20260820-001-p3-gap-reaudit.yaml`（基于原 001 模板）
- 更新 `accepts: 2026-08-20T08:05:00+08:00`
- 更新 acceptance_commands 反映扩展判定清单
- depends_on TASK-20260816-001
- status=queued（不变）
- 删除 `TASK-20260819-001-p3-gap-reaudit.yaml`（避免双任务包混淆）

## 8. 自动调度声明

- `TASK-... queued` 仅是任务包状态
- **不等于已存在自动调度**（无 launchd plist / cron / 内置 scheduler）
- 若希望 8/20 08:05 CST 自动触发，需用户单独：
  - 选项 1：创建 launchd plist（docs-only 任务，需另开 worktree）
  - 选项 2：创建 cron entry（需用户单独批准）
  - 选项 3：手动触发（本任务后等待用户单独指令）

## 9. 已验证 / 未验证

### 9.1 已验证

- ✅ 用户决策（B + 8/20 08:05 CST）
- ✅ 扩展判定清单（5 项新增）
- ✅ 时间线规划（8/20 08:05 / 8/20 16:42 / 8/21 18:34）
- ✅ 现有 P3 状态（Day0=8/13T08:42Z）
- ✅ 任务包现状（仅文档，无调度）
- ✅ 主工作树 ahead/behind=0/0

### 9.2 未验证

- ❌ 8/18-8/19 健康/新闻实际计数（待 8/20 重评）
- ❌ Battery/Clamshell Sleep 实际日志（pmset -g log 待读取）
- ❌ launchd exit code 历史（待 8/20 重评）
- ❌ caffeinate 单实例确认（待 8/20 重评）

### 9.3 边界

- 不动 P3 状态目录
- 不 load / unload plist
- 不跑 `ops/run-claude-p3-watch.sh` / `scripts/p3_rollover_epoch.py`
- 不创建自动调度（除非用户单独确认）
- 不修改任何文件除本任务审计 + 任务包重建 + MODIFICATION-LOG

## 10. 推荐下一步动作

1. **本任务**：commit + ff-only + push（docs-only 决策记录 + 任务包重建）
2. **本任务后**：维持现状；不动任何系统；等 8/20 08:05 CST 用户手动触发重评
3. **可选**：用户单独决定创建自动调度（launchd plist / cron）

## 11. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-p3-reaudit-schedule-20260817`，分支 `codex/p3-reaudit-schedule-20260817`。
- 基线：main=`42d51e0`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-17T14:30:00Z`（写入时）。
- 决策方：用户「继续选 B，但调整重评时间」(2026-08-17 下午)
- 任务包：新建 `TASK-20260820-001-p3-gap-reaudit`（替换原 001）
