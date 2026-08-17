# P3 Gap 重新审计 — 8/19 末任务提前触发(2026-08-17)

## 0. TL;DR

- **触发**：用户「立即手动触发 8/19 re-audit」(2026-08-17)，原计划触发时间为 8/19 末 UTC 15:59 / CST 23:59
- **数据窗口**：8/16-8/17（部分窗口，因 8/19 还未到）
- **3 档判定结果**：⚠️ 健康部分恢复（60.7/天）+ ❌ 新闻持续停摆（10.0/天）→ **建议切路径 A**
- **路径 A 触发条件**：caffeinate 续期 + 系统睡眠关闭（需用户单独以「授权 caffeinate 续期」关键词触发）

## 1. 数据证据

### 1.1 state.json（epoch marker）

```json
{
  "kind": "p3_burn_in_epoch",
  "schema_version": 1,
  "started_at": "2026-08-13T08:42:06.833689+00:00",
  "time_basis": "UTC"
}
```

- Day0: `2026-08-13T08:42:06.833689Z`
- Elapsed: ≈ 4 天（rollover 后）

### 1.2 健康采样每日计数

| 日期 | samples | 趋势 |
|------|---------|------|
| 2026-08-13 (rollover 日) | 137 | 正常基线 |
| 2026-08-14 | 101 | 略低 |
| **2026-08-15** | **9** | **严重停摆** |
| **2026-08-16** | **72** | **部分恢复** |
| **2026-08-17** | **11** | **再次停摆** |
| **8/16-8/17 健康均值** | **41.5 / 天** | **❌ 持续停摆（<50）** |

注：原 §4.2 阈值表设计基于 8/16-8/19 三日窗口（均值）。本次手动触发仅 8/16-8/17 两日；8/15 因历史原因（撞坑 #107 机器睡眠）严重偏低。

### 1.3 新闻运行每日计数

| 日期 | runs | 趋势 |
|------|------|------|
| 2026-08-13 (rollover 日) | 23 | 正常基线 |
| 2026-08-14 | 17 | 略低 |
| **2026-08-15** | **1** | **严重停摆** |
| **2026-08-16** | **12** | **部分恢复** |
| **2026-08-17** | **2** | **再次停摆** |
| **8/16-8/17 新闻均值** | **7.0 / 天** | **❌ 持续停摆（<12）** |

### 1.4 最新 daily report（2026-08-15.json，generated_at 8/16）

```
attention: ['health_sample_gap', 'news_run_gap']
burn_in_status: attention
epoch_started_at: 2026-08-13T08:42:06.833689+00:00
period: 2026-08-15 (complete)
health gaps: 7 次（max 22041s = 6.1h；阈值 1800s）
news gaps: 2 次（max 50171s = 13.9h；阈值 7200s）
```

注：本次窗口（8/16-8/17）尚无对应 daily .json 报告（最新是 8/15）；但 8/15 报告显示 attention 仍未消除。

### 1.5 launchd 当前状态

```
-   0  com.myaiemployee.agent                  ← 注册但未运行（periodic）
-   0  com.myaiemployee.burn-in-report        ← 注册但未运行
1708 0  com.myaiemployee.p3-awake              ← 运行中（caffeinate）
1710 0  com.myaiemployee.dashboard             ← 运行中
-   0  com.myaiemployee.verify-first-daily-once ← 注册但未运行
-   0  com.myaiemployee.health-monitor          ← 注册但未运行（健康采样器）
-   0  com.myaiemployee.imap-sync              ← 注册但未运行
1701 0  com.myaiemployee.menu-bar              ← 运行中
-   0  com.myaiemployee.news-refresh           ← 注册但未运行（新闻调度）
```

### 1.6 p3-awake plist caffeinate 参数

```xml
<string>/usr/bin/caffeinate</string>
<string>-i</string>
<string>-t</string>
<string>...</string>  <!-- 时间秒数 -->
```

- caffeinate `-i -t`（阻止 idle sleep；时间到期后退出）
- 撞坑 #95 修复（v0.2.78）设置 9 天，约 8/12 已过期
- 当前 PID 1708 仍在运行（caffeinate 可能已过期但进程未被回收）

### 1.7 实时 interval 状态（截至 8/17）

- health PASS（max_gap=10m）
- news PASS（最近一次 success，item_count=48）
- **但 daily .json 报告 attention 仍未消除**

## 2. 3 档判定（沿用 p3-decision-41-42 §2.3）

| 指标 | 阈值 | 实际（8/16-8/17） | 判定 |
|------|------|-------------------|------|
| 健康均值 | ≥100 / 天 | 41.5 / 天 | ❌ <50 |
| 健康均值 | 50-100 / 天 | 41.5 / 天 | ❌ 不在 50-100 |
| 新闻均值 | ≥18 / 天 | 7.0 / 天 | ❌ <12 |
| 新闻均值 | 12-18 / 天 | 7.0 / 天 | ❌ <12 |

**综合判定**：❌ **必须切路径 A**

**触发条件**：用户单独以「授权 caffeinate 续期」关键词触发后，路径 A 自动启动。

## 3. 路径 A 实施细节（待用户授权）

### 3.1 caffeinate 续期

- 选项 A：续期至 30 天（`/usr/bin/caffeinate -i -t 2592000`）
- 选项 B：移除 `-t` 改为无限期（`-i` alone），依赖 KeepAlive=true 自动重启
- 推荐：选项 A（更可控；过期后 launchd 重新 load plist 时自动续期）

### 3.2 系统睡眠关闭

- 系统设置 → 电源 → 防止在电源适配器上睡眠（macOS Ventura+）
- 命令行：`pmset -c disablesleep 1`（需 sudo）
- 仅适用于插电状态；电池模式不强制

### 3.3 保留现状（不切 A）

- v1.1-A 仍 NOT_UNLOCKED
- 30d 时间门最早 `2026-09-12T08:42:06Z`
- 若不切 A，路径 B 监测继续；但 8/16-8/17 数据显示已触发"必须切 A"

## 4. 与 8/16 决策的一致性

### 4.1 §4.2 三路径决策表

| 路径 | 决策 | 8/16 状态 | 8/17 实测 |
|------|------|----------|----------|
| A. caffeinate 续期 + 系统睡眠关闭 | 推荐度：触发条件时启动 | 待触发 | **触发** |
| B. 监测，8/19 末重新审计 | 当前默认 | 进行中 | **本任务完成；判定触发 A** |
| C. 接受 attention 永久存在 | 不推荐 | 否决 | 否决 |

### 4.2 §2.3 判定表适用

- 8/16 §2.3 设计假设窗口为 8/16-8/19（三日均值）
- 本次实测窗口为 8/16-8/17（两日）
- 三日均值 vs 两日均值的差异：本次均值偏低，因 8/15 严重停摆拉低整体；但实际 8/17（11 samples）也低于阈值
- **结论**：窗口长短不改变判定结果（仍触发 A）

## 5. 边界

- 不实际执行 caffeinate 续期（待用户授权）
- 不修改 launchd plist
- 不 load 任何 plist
- 不启用 Feature Flag / `ENABLE_*`
- 不二次 rollover
- 不动 P3 状态目录
- 不跑 `ops/run-claude-p3-watch.sh`

## 6. 已验证 / 未验证

### 6.1 已验证

- ✅ 8/16-8/17 健康/新闻 实际计数
- ✅ 最新日报 2026-08-15.json attention 状态
- ✅ launchd 9 个 com.myaiemployee.* plist 状态
- ✅ p3-awake caffeinate `-i -t` 参数（时间到期未刷新）
- ✅ v1.1-A 4 门槛状态（不变）
- ✅ 7d/30d 时间门
- ✅ 主工作树 ahead/behind=0/0

### 6.2 未验证

- ❌ p3-awake caffeinate 实际到期时间（plist 内部参数）
- ❌ 机器睡眠历史（8/15-8/17 期间）
- ❌ 系统电源策略当前设置

### 6.3 边界

- 不实际执行 caffeinate 续期
- 不 load 任何 plist
- 不动 P3 状态目录

## 7. 推荐下一步动作

1. **本任务**：commit + ff-only + push（docs-only 审计报告）
2. **本任务后**：用户单独决定路径 A 触发：
   - 关键词「授权 caffeinate 续期」→ 实施 caffeinate 续期 + 系统睡眠关闭
   - 关键词「维持 B」→ 接受 v1.1-A 短期不解锁
   - 关键词「暂停」→ 不动；下次再说

## 8. 决策签名

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-p3-gap-reaudit-20260817`，分支 `codex/p3-gap-reaudit-20260817`。
- 基线：main=`a64e68e`=origin/main；本地 ahead=0；提交后应为 ahead=1。
- 时点：`2026-08-17T13:30:00Z`（写入时；用户「立即手动触发」授权）。
- 任务触发：用户「立即手动触发 8/19 re-audit」(2026-08-17 上午)。
