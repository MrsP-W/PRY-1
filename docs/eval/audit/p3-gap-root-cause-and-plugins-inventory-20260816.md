# P3 Gap 根因与 plugins 盘点审计 — 只读分析(2026-08-16)

## 0. TL;DR

- **范围**：docs-only 只读审计两个独立事项：(A) `plugins/p3-ops-claude/` 8 文件盘点；(B) 8/14-8/15 health/news gap 根因调查。
- **核心结论**：
  - (A) `plugins/p3-ops-claude/` 自 **2026-08-04 16:09** 起持续 untracked，**非新增**；是 Claude Code 安全编排命令，与主仓脚本一一对应；建议**保留为 untracked WIP**，不入仓。
  - (B) 8/14 6h gap（10:00-15:50 UTC）+ 8/15 全天近乎停摆（9 health samples / 1 news run）+ 8/16 仍只有 5 health / 1 news，**根因高度疑似 macOS 睡眠/关机**——daemon 在 gap 前后均 `healthy=true, reasons=[]`，采样器自身停了；caffeinate 时间窗或 9d 延长（撞坑 #95 修复）可能已到期。
- **v1.1-A 含义**：attention 触发是运营层（机器睡眠）而非 epoch 标记层；rollover 已完成，根因未消除；7d 最早 `2026-08-20T08:42:06Z`，30d 最早 `2026-09-12T08:42:06Z`，但只要睡眠继续复发，attention 不会自动消除。

## 1. 上下文与背景

### 1.1 上次校准以来的变化(8/13 → 8/16)

- main 前进 4 commit 至 `431f2f3` (= origin/main，已同步)
- P3 rollover 已执行：旧 epoch `2026-07-30T07:04:45Z` 已归档（5/5 归档），新 Day0 = `2026-08-13T08:42:06.833689Z`
- watch_once 崩溃已修复（`431f2f3`）
- `scripts/p3_rollover_epoch.py` 与 `tests/scripts/test_p3_rollover_epoch.py` 已入仓（`0254d64`）
- 备份 `burn-in.backup-2026-08-13T08-42-00Z` 保留
- 新增 §6.1 进度 5/5；新增 §6.1 执行报告 `tests/eval/audit/p3-rollover-execution-2026-08-13.md`

### 1.2 触发本次审计的事实

- 最新日报 `2026-08-14.json` 含 `attention: ["health_sample_gap", "news_run_gap"]`，burn_in_status=attention
- v1.1-A 仍 `NOT_UNLOCKED`（4 门槛 2 PASS / 2 FAIL：30-fixture PASS、5 docs-only PASS、7d/30d FAIL）
- 主工作树未跟踪 11 项，其中 `plugins/p3-ops-claude/` 在 8/4 已存在，**非新出现**；本次单独澄清其性质

### 1.3 目标

(A) 盘点 `plugins/p3-ops-claude/`，给出 tracked/WIP 处置建议；(B) 调查 8/14 health/news gap 根因，提出避免 attention 反复触发的可执行项。**不修改** scripts/、tests/、src/、状态目录。

## 2. (A) plugins/p3-ops-claude 盘点

### 2.1 文件清单与时间戳

```
plugins/                                    drwxr-xr-x   Aug  4 16:09
plugins/p3-ops-claude/                      drwxr-xr-x   Aug  4 16:09
plugins/p3-ops-claude/README.md             1 文件
plugins/p3-ops-claude/.claude-plugin/plugin.json
plugins/p3-ops-claude/commands/p3-rollover.md
plugins/p3-ops-claude/commands/p3-watch.md
```

总计 5 个文件（含 1 个目录元数据）。`plugins/` 与 `plugins/p3-ops-claude/` 修改时间均为 **2026-08-04 16:09**，早于 P3 rollover（8/13）、早于 md lint 修复（8/13）、早于本审计（8/16）共 12 天。

### 2.2 内容性质

- **README.md**：声明本插件"只编排既有 P3 脚本，不控制 Cursor GUI"；`/p3-watch` 默认仅诊断（`--repair` 才修）；`/p3-rollover` 仅在首份日报门槛后执行；本地临时加载 `claude --plugin-dir plugins/p3-ops-claude`。
- **plugin.json**：name=`p3-ops-claude`, version=`0.1.0`, author=`Mr-PRY`。
- **commands/p3-rollover.md**：限定 `allowed-tools: Bash(python3 scripts/p3_rollover_epoch.py), Read`；禁止 `--force`；禁止覆盖/删除/手工移动；不修改 LaunchAgent/调度/SMTP/WIP/git/Cursor。
- **commands/p3-watch.md**：限定 `allowed-tools: Bash(python3 scripts/watch_p3_ops.py), Bash(uv run pytest ...), Read`；`--repair` 显式传入才修；默认仅只读诊断；不使用 `--force`；不修改 LaunchAgent/SMTP/状态目录/Cursor。

### 2.3 关联文件（同为 untracked）

```
ops/claude-p3-watch-launchd.plist.example    Aug  4（同期）
ops/run-claude-p3-watch.sh                   Aug  4（同期）
```

两者与 `plugins/p3-ops-claude/` 同日创建；plist.example 是未安装模板；`run-claude-p3-watch.sh` 使用 `dontAsk`，无自动修复或外部写入。

### 2.4 入仓 vs WIP 评估

| 维度 | 入仓 tracked | 维持 WIP untracked |
|------|------------|-------------------|
| 文档可发现性 | ✅ 新成员可见 | ❌ 仅个人/小圈可见 |
| 代码审计覆盖 | ✅ 受 lint/CI 约束 | ❌ ruff/mypy 不跑 |
| 用户私有性 | ❌ 与他人共享 | ✅ 个人编排工具 |
| 撞坑 #103（stash 收集漂移）风险 | 低（已 docs 化） | 中（与主仓逻辑耦合需单独审计） |
| 与 freeze 的兼容性 | 需另开 worktree 单独批准 | 维持现状（11 untracked 之一） |

**判断**：**建议维持 WIP untracked**。理由：

1. 内容明确是个人 Claude Code 编排工具，作者字段为 `Mr-PRY`，非团队资产
2. README 自述"只编排既有 P3 脚本"——主仓 `scripts/p3_rollover_epoch.py` 等已 tracked，本插件不重复逻辑
3. 已存 12 天，状态稳定，未触发任何冲突
4. 入仓需另开常规 code worktree，跨 freeze 边界；本次 docs-only 不动

**保留位置**：`plugins/p3-ops-claude/` + `ops/claude-p3-watch-{launchd.plist.example,run-claude-p3-watch.sh}`，统一作为"个人 P3 编排层 WIP"。

### 2.5 已验证/未验证边界

- ✅ 5 文件路径、修改时间、内容
- ✅ 与主仓脚本的耦合关系（只读映射 `p3_rollover_epoch.py` / `watch_p3_ops.py` / `test_watch_p3_ops.py` / `test_verify_p3_first_daily.py`）
- ❌ 未跑 ruff/mypy（未跟踪文件）
- ❌ 未实际加载 `claude --plugin-dir plugins/p3-ops-claude`（无 GUI 操作）

## 3. (B) 8/14-8/16 Gap 根因调查

### 3.1 数据证据（来源：`burn-in/daily/2026-08-14.json` + `health/samples.jsonl` + `news/runs.jsonl`）

#### 3.1.1 健康采样：每日样本数（30 天趋势）

```
2026-08-04:  65   ← 偏低
2026-08-05: 141
2026-08-06:  66   ← 偏低
2026-08-07:  51   ← 偏低
2026-08-08:  70   ← 偏低
2026-08-09: 132
2026-08-10: 139
2026-08-11:  92   ← 略低
2026-08-12: 128
2026-08-13: 137   ← rollover 日
2026-08-14: 101   ← 略低（6h gap）
2026-08-15:   9   ← 严重停摆
2026-08-16:   5   ← 持续停摆
```

正常基线 ~140 样本/天（10 分钟间隔）。8/4、8/6-8/8、8/11、8/14-8/16 出现明显低谷。

#### 3.1.2 新闻运行：每日次数（30 天趋势）

```
2026-08-04: 11
2026-08-05: 23
2026-08-06: 11
2026-08-07:  9
2026-08-08: 11
2026-08-09: 23
2026-08-10: 23
2026-08-11: 16
2026-08-12: 21
2026-08-13: 23   ← rollover 日
2026-08-14: 17   ← 6h gap（10:00-15:50 UTC 缺失 6 次）
2026-08-15:  1   ← 严重停摆
2026-08-16:  1   ← 持续停摆
```

正常基线 23-25 次/天（每小时）。8/4、8/6-8/8、8/11、8/14-8/16 同步低谷。

#### 3.1.3 8/14 关键 gap（来源 daily 报告）

health gaps：
- 03:41 → 05:19 UTC（1.65h）
- 10:00 → 12:00 UTC（2.01h）
- 12:00 → 14:39 UTC（2.65h）
- 14:39 → 15:30 UTC（0.84h）

news gaps：
- 03:19 → 05:48 UTC（约 2.5h）
- 09:49 → 15:50 UTC（**6h**，**最大**）

**注意**：health 与 news 在同一窗口（10:00-15:50 UTC）双双停摆。

#### 3.1.4 gap 窗口内 daemon 状态（关键）

```
8/14 10:00:04  healthy=True reasons=[]  jobs.dashboard=(pid, registered)=(True, True)  jobs.menu-bar=(True, True)
8/14 12:00:46  healthy=True reasons=[]  jobs.dashboard=(True, True)  jobs.menu-bar=(True, True)
8/14 14:39:53  healthy=True reasons=[]  jobs.dashboard=(True, True)  jobs.menu-bar=(True, True)
8/14 15:30:34  healthy=True reasons=[]  jobs.dashboard=(True, True)  jobs.menu-bar=(True, True)
8/14 15:40:37  healthy=True reasons=[]  jobs.dashboard=(True, True)  jobs.menu-bar=(True, True)
8/14 15:50:38  healthy=True reasons=[]  jobs.dashboard=(True, True)  jobs.menu-bar=(True, True)
```

**daemon 在 gap 前后均健康运行**——`dashboard`、`menu-bar` 的 PID 在所有样本中均存在。**停的是采样器，不是被监控对象**。

### 3.2 假设清单

| # | 假设 | 支持证据 | 反驳证据 |
|---|------|---------|---------|
| H1 | **macOS 睡眠/关机**（机器长时间断电/睡眠） | 8/15 全天 9 samples、8/16 仅 5；与 8/4-8/8 模式类似 | 无 wake/sleep 日志直接证据 |
| H2 | caffeinate `-t` 到期（撞坑 #95 修复设为 9d） | `com.myaiemployee.p3-awake` 当前 PID 1708（运行中），但 -t 过期后进程继续持锁的语义需复核 | 当前 launchd 显示 p3-awake 仍在跑 |
| H3 | launchd 在睡眠/唤醒后未及时 re-arm health-monitor / news-refresh | 8/14-8/15 同时停摆 → 单一共享调度器问题 | 无 launchd log 确认 |
| H4 | 磁盘满 / IO 阻塞 | 无 | 无 |
| H5 | scripts/burn-in 配置错 | 无 | 8/12、8/13 均正常 → 配置稳定 |

**最可能假设**：**H1 + H2 组合**。caffeinate -t 9d 自 8/3 修复时起算，8/12 已到期；机器进入常规睡眠模式；launchd 守护随系统睡眠而停跑。

### 3.3 影响与 v1.1-A 含义

- **当前新 Day0 epoch elapsed ≈ 75h（3.1d）**；7d 时间门最早 `2026-08-20T08:42:06Z`，距今 ≈ 3.7d。
- **若 H1+H2 成立**：机器只要再睡眠 > 30 min（health 阈 1800s）或 > 2h（news 阈 7200s），attention 立即重新触发。
- **30d 窗口同理**：30 天内需要连续无 sleep gap > 30 min 才可能到 30d no_p0_p1 PASS；这在开发机器上几乎不可能。
- **结论**：v1.1-A 解锁**短期内（8/20 前）无现实路径**，除非：(i) caffeinate 续期 + (ii) 系统睡眠关闭 + (iii) 历史日报 attention 自然过期。

### 3.4 已验证/未验证边界

- ✅ daily 报告 attention 来源分析
- ✅ health/news journal 30 天趋势
- ✅ gap 窗口内 daemon 状态反查（采样器停 vs 被采样对象停的区分）
- ✅ 当前 launchd plist 注册情况（9 个 com.myaiemployee.* plist；p3-awake/dashboard/menu-bar 当前运行）
- ❌ 未读 `/var/log/com.apple.xpc.launchd/launchd.log`（需 sudo，超出只读范围）
- ❌ 未读 `p3-awake` 实际到期时间（plist 内 `caffeinate -i -t` 参数）
- ❌ 未读 macOS sleep 日志（`pmset -g log`）

## 4. 建议动作（不构成自动执行授权）

### 4.1 plugins/p3-ops-claude 处置

- **A**. 维持 untracked WIP（推荐；理由见 §2.4）
- **B**. 单独开常规 code worktree 入仓（需用户批准；跨 freeze）
- **C**. 移入 `archive/plugins-experimental/` 并 gitignore（不推荐；影响个人扩展能力）

### 4.2 v1.1-A 短期路径

#### 4.2.1 路径 A：caffeinate 续期 + 系统睡眠关闭（治本）

- 检查 `com.myaiemployee.p3-awake` plist 当前 caffeinate `-t` 参数
- 若已到期：续期至 9d 或更长；或改为无限期 `-i`（无 `-t`）
- 系统设置：`caffeinate -di` 或 Power Management → 永不睡眠（仅 AC）
- 风险：电源/发热/数据安全；需用户显式决定

#### 4.2.2 路径 B：接受 8/20 7d 窗口观察 + 监测 attention

- 保持当前状态，不动 caffeinate
- 8/19 末重新审计：若 8/15-8/19 仍持续 gap → 路径 A
- 若 8/16 起到 8/19 期间机器不再睡眠 → 路径 B 即可
- 失败成本：再延 7d，30d 最早 9/12

#### 4.2.3 路径 C：接受永久 attention + 手动改造 read-only

- 修改 `scripts/p3_burn_in_report.py` 资格汇总逻辑：把 attention 标记降级为 warning
- 风险：违反"attention 是 hard 阻断"的设计前提；撞坑 #107 类似漂移
- 不推荐

### 4.3 推荐

**路径 B（监测）**，8/19 末重新审计；若 8/16-8/19 仍持续 gap，则切路径 A。

## 5. 已验证范围与未验证风险

### 5.1 已验证

- ✅ 11 项未跟踪 WIP 全部识别；`plugins/p3-ops-claude/` 时间戳确认 8/4 即存在
- ✅ 8/14-8/16 daily report attention 来源（`2026-08-14.json`）
- ✅ health/news journal 30 天每日样本/运行计数
- ✅ 8/14 gap 窗口内 daemon PID 状态反查
- ✅ 当前 launchd com.myaiemployee.* 注册与运行状态
- ✅ MODIFICATION-LOG 最近 4 条目（8/13 集成批准 / 前置 1-3 / 授权 rollover / watch_once 修复）

### 5.2 未验证

- ❌ caffeinate `-t` 实际到期时间（plist 内参数）
- ❌ 8/15-8/16 完整停摆的 macOS 系统日志
- ❌ `~/Library/Logs/com.myaiemployee.*` 详细 stderr（撞坑 #95/#97/#98 修复后已存）
- ❌ 撞坑 #95 fix (`v0.2.78`) 在 8/3 后的 re-arm 记录

### 5.3 边界与不做

- 不跑 `p3_rollover_epoch.py`（已执行过一次，§6.1 五前置已满足）
- 不修改 `scripts/`、`tests/`、`src/`
- 不动 `~/Library/Application Support/MyAIEmployee/burn-in/` 与 `burn-in-archive/`
- 不调整 caffeinate、不改 launchd plist
- 不 push / merge / 打 tag
- 不启用 Feature Flag / `ENABLE_*`
- 不动 11 项未跟踪 WIP
- 不修改 `plugins/p3-ops-claude/` 内容（维持现状）

## 6. 推荐下一步动作

1. **今天（你确认）**：本审计报告 + 任务包 + MODIFICATION-LOG 条目提交 docs-only；ff-only 合入 main 后触发 push readiness 复核（ahead 应仍 = 0）。
2. **本周**：单独盘点 `plugins/p3-ops-claude/` 是否维持 WIP 或入仓（决定 §4.1 A/B/C）。
3. **8/19 末**：仅读复跑 gap 审计；若 8/16-8/19 持续 attention → 启动路径 A（caffeinate 续期 + 系统睡眠关闭）。

## 7. 决策签名（本审计输出方）

- 模型：M3（MiniMax-M3）主执行；TERRA/LUNA 未唤醒。
- 工作树：`/tmp/wt-p3-gap-plugins-audit-20260816`，分支 `codex/p3-gap-and-plugins-audit-20260816`。
- 基线：main=`431f2f3`=origin/main；本地 ahead=0；提交后应为 ahead=1（docs-only）。
- 时点：`2026-08-16T20:50:00Z`（写入时）。
