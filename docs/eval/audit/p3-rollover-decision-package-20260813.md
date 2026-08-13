# P3 Rollover 决策包 — 只读审计与 GO/NO-GO(2026-08-13)

## 0. TL;DR

- **范围**：docs-only 只读审计 P3 epoch rollover 决策；不执行 rollover，不修改脚本，不写状态目录。
- **当前 epoch**：`Day0=2026-07-30T07:04:45.527698Z`；归档目录已有 4 个历史 epoch。
- **核心发现**：`scripts/p3_burn_in_report.py:run_report` 的资格汇总（line 956 起）会扫描整个 epoch 的 health/news journal 后才计算 `attention`，而 `2026-08-11.json` 等历史日报含有 `health_sample_gap / news_run_gap / news_failure`。即便实时 interval 全绿（health `max_gap=10.0m`、news `max_gap=60.2m`），汇总仍把整个 epoch 标为 `attention`。
- **结论**：`CONDITIONAL GO`。直接执行不可，必须先满足 5 个前置条件（见 §6）。
- **不推荐**：NO-GO + 等到 `2026-08-29T07:04:45.527698Z` 30d 自动 PASS — 因为 attention 是 epoch 内 hard 阻断，30d 不会自动消除 attention。

## 1. 上下文与目标

### 1.1 当前状态证据(2026-08-13 11:31–11:43 CST)

- 本地 `main=25789cc`，远端 `origin/main=cfae507`，本地 **ahead 4**（`dd05d08` / `c2ee261` / `3750927` / `25789cc`）。
- v1.1-A 仍 `NOT_UNLOCKED`；4 必须门槛 2 PASS / 2 FAIL；最新完整日报 `2026-08-11.json` 仍 `attention`。
- Day0 = `2026-07-30T07:04:45.527698Z`；上次未做 rollover 时点 ≈ `2026-07-30T07:04Z`。
- 实时：health PASS(`max_gap=10.0m`, `tail=1.75m`)、news PASS(`max_gap=60.2m`)；最近 4 次新闻运行 max_gap=99.33m 超 90m 阈值；alert_open=false, failure_streak=0。
- 30d 时间门最早 `2026-08-29T07:04:45.527698Z`，距离 ≈ 15.75 天。

### 1.2 目标

固化最新证据、审计既有未跟踪脚本，给出 GO/NO-GO 决策与前置条件，**不执行 rollover**。

## 2. 资格汇总逻辑详解（只读）

源文件 `scripts/p3_burn_in_report.py:run_report`（line 922 起，节选 line 956 起）：

```python
health = _health_summary(samples, alerts, start=epoch, end=now)
news = _news_summary(news_runs, start=epoch, end=now)
attention = _dedupe(_attention_from_summary(health, news, input_integrity=input_integrity))
progress = _progress(epoch=epoch, now=now, has_attention=bool(attention))
if attention:
    status = "attention"
elif progress["thirty_day_no_p0_p1"]["eligible"] is True:
    status = "pass"
else:
    status = "collecting"
```

- `samples / alerts / news_runs` 通过 `read_jsonl` 读取**自 Day0 至 now**的整个 journal，不做窗口裁剪。
- `_attention_from_summary`（line 753）会基于整段 `health / news` 输出 8 类 attention：`health_unhealthy_sample / health_sample_gap / health_alert_opened / news_run_gap / news_degraded / news_failure / news_overlap / input_integrity_issue`。
- **结论**：任一历史样本触发 attention，整个 epoch 都会被标 `attention`。实时 interval PASS 不会反向改写历史，30d 时间到也不会消除 attention。**唯一清零路径是 rollover 或手动改写 journal（不可取）**。

### 2.1 当前 attention 来源

最新完整日报 `2026-08-11.json` 包含：

| attention | 来源 | rollover 后是否消失 |
|-----------|------|---------------------|
| `health_sample_gap` | 历史窗口中存在 gap | ✅（journal 归档后，新 Day0 从空白开始） |
| `news_run_gap` | `news_runs.gaps.count > 0`（99.33m 来源） | ✅（同上） |
| `news_failure` | 历史 `news_runs.failure > 0` | ✅（同上） |

三项均可在 rollover 后清零。`health_unhealthy_sample / health_alert_opened / news_degraded / news_overlap / input_integrity_issue` 当前均未触发。

## 3. Rollover 脚本行为详解（只读）

源文件 `scripts/p3_rollover_epoch.py:rollover_once`（line 36 起，关键路径）：

```text
1. verification = verify_first_daily(app_support_dir=root)
2. 若 result ∈ {too_early, not_started} → 直接返回，不归档
3. epoch = verification["epoch_started_at"]（来自当前 marker）
4. 若 burn-in-archive/epoch-<ISO> 已存在 → 返回 archive_target_exists（绝不覆盖）
5. 若 burn-in/ 不存在 → 返回 source_missing
6. archive.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
7. os.replace(burn-in/, burn-in-archive/epoch-<ISO>/)   ← 原子移动
8. new_day0 = burn_in.start_burn_in(...)   ← 写新 marker
9. 若 8 抛异常 → 返回 archived_start_failed（archive 已存在，原 epoch 仍在归档里）
10. report = burn_in.run_report(...)   ← 生成新 daily/weekly
11. watch = watch_once(...)   ← 检查 watch 状态
12. 返回 rolled_over + archive_path + new_day0 + report + watch
```

**关键观察**：

- `attention` **不阻断 rollover**。脚本仅在 `too_early / not_started` 时短路。`fail_attention` 会直接走到归档步骤。这是有意设计 — rollover 是清零 attention 的工具。
- `archive_target_exists` 是 fail-closed 护栏：绝不会覆盖已存在的归档。
- `os.replace` 是原子操作（同一文件系统下）。若 step 8 失败，原 epoch 保留在归档里，不会丢失。
- **没有独立备份**：脚本不复制一份到 `burn-in-backup/`。归档是唯一历史。
- **stdout 输出 JSON 摘要**：无 log 文件，无 exit code 细节（仅 `result == "rolled_over"` 时返回 0，否则 1）。

### 3.1 测试覆盖（只读）

源文件 `tests/scripts/test_p3_rollover_epoch.py`（3 个测试，全部 mock）：

| 测试 | 覆盖路径 | mock 对象 |
|------|---------|----------|
| `test_rollover_stops_when_archive_target_exists` | `archive_target_exists` 短路 | `verify_first_daily` |
| `test_rollover_moves_epoch_and_starts_new_day0` | `rolled_over` 成功路径 | `verify_first_daily, start_burn_in, run_report, watch_once` |
| `test_rollover_does_not_start_before_gate` | `too_early` 短路 | `verify_first_daily` |

**未覆盖**：

- `fail_attention` 路径（实际生产场景，attention 不短路 → rollover）
- `source_missing` 路径
- `archived_start_failed` 路径（start_burn_in 抛异常）
- `not_started` 路径
- `os.replace` 跨设备失败（理论上 `burn-in/` 和 `burn-in-archive/` 不同 fs 会 `OSError`，脚本未捕获）

## 4. 当前归档与状态目录（只读 ls）

```
~/Library/Application Support/MyAIEmployee/
├── burn-in/             ← 当前 epoch（Day0=2026-07-30T07:04:45.527698Z）
│   ├── daily/           (26 个 jsonl + 13 个 .json)
│   ├── state.json       (epoch marker)
│   └── weekly/
└── burn-in-archive/
    ├── epoch-2026-07-21T18-23-47Z/
    ├── epoch-2026-07-23T02-30-20Z/
    ├── epoch-2026-07-23T19-59-04Z/
    └── epoch-2026-07-27T05-34-24Z/
```

- 当前 epoch 归档目标：`epoch-2026-07-30T07-04-45Z`（**不存在，无碰撞**）。
- 历史归档皆由前 4 次 rollover 留下；归档命名规则一致（`epoch-<UTC>` 短横线分隔）。
- 当前 `burn-in/` 占用 ≈ 数 MB；归档步骤可秒级完成。

## 5. 备份 / 回滚方案（推荐）

### 5.1 执行前备份（脚本外）

```bash
# 在主工作树（或任意干净目录）执行，不依赖 rollover 脚本
SRC="$HOME/Library/Application Support/MyAIEmployee/burn-in"
DST="$HOME/Library/Application Support/MyAIEmployee/burn-in.backup-$(date -u +%Y-%m-%dT%H-%M-%SZ)"
cp -a "$SRC" "$DST"   # 含 mode 0700 权限
ls -la "$DST"          # 确认 state.json + daily/ + weekly/
```

- 备份路径独立于 `burn-in-archive/`，**不会被 rollover 移动**。
- 备份时机：在用户单独授权 rollover **之前**，由用户或受信任脚本执行。

### 5.2 执行后回滚（若 new_day0 异常）

```bash
# 撤销 rollover（仅适用于已 rolled_over 且新 Day0 不健康）
rm -rf "$HOME/Library/Application Support/MyAIEmployee/burn-in"
rm -f "$HOME/Library/Application Support/MyAIEmployee/burn-in/state.json"
cp -a "$HOME/Library/Application Support/MyAIEmployee/burn-in-archive/epoch-2026-07-30T07-04-45Z" \
      "$HOME/Library/Application Support/MyAIEmployee/burn-in"
# 验证 state.json 存在且包含原 Day0
cat "$HOME/Library/Application Support/MyAIEmployee/burn-in/state.json"
# 应输出 started_at=2026-07-30T07:04:45.527698+00:00
```

- 步骤1+2 删除新 Day0 创建的 `burn-in/`；步骤3 从归档恢复原 epoch。
- 回滚后 v1.1-A readiness 不前进，仍维持 `NOT_UNLOCKED`。

## 6. GO / NO-GO 决策

### 6.1 选项 A — CONDITIONAL GO（推荐）

**前置条件（必须全部满足）**：

1. **脚本入仓**：将未跟踪的 `scripts/p3_rollover_epoch.py` 和 `tests/scripts/test_p3_rollover_epoch.py` 纳入 tracked（在 docs-only worktree 之外的常规代码 worktree，docs-only 期间不动）。
2. **测试补全**：补 3 个新单元测试覆盖 `fail_attention / source_missing / archived_start_failed` 路径，pytest 全绿。
3. **预演**：在 `tmp_path` 模拟 burn-in/ 与 burn-in-archive/，跑一次 `rollover_once(app_support_dir=tmp_path)`，确认 stdout JSON 结构、archive 命名、new_day0 ISO 与预期一致。
4. **备份落地**：按 §5.1 在执行前生成 `burn-in.backup-<UTC>`，附 md5 校验。
5. **回滚 SOP 就绪**：§5.2 命令复制到执行人本地终端；执行人确认已读。

**授权与执行**：

- 由用户**单独**以"授权 rollover"关键词 + 明确 Day0 = `2026-07-30T07:04:45.527698Z` 同意。
- 执行命令：`python3 scripts/p3_rollover_epoch.py`（无 `--force`）。
- 执行后立即生成一份只读 `tests/eval/audit/p3-rollover-execution-2026-MM-DD.md` 报告，记录：archive_path / new_day0 / report.status / watch.status / 实时 health news PASS 复核。

**预期收益**：

- 新 Day0 起重新累计 7d/30d，7d 最早 `2026-08-20T07:04:45Z`（若 8/13 执行）；30d 最早 `2026-09-12T07:04:45Z`。
- attention 历史清零；v1.1-A 4 门槛在 attention 上 PASS。

### 6.2 选项 B — NO-GO + 等到 8/29 自动 PASS

**判断**：

- **不可行**。`run_report` 资格汇总扫描整个 epoch 的 journal，attention 不会被 30d 时间门自动消除。即便 `2026-08-29` 到来，`attention != []` 仍将 status 标为 `attention`，30d `pass` 不会触发。
- 唯一例外：用户在 8/29 之前手动清掉 `burn-in/daily/*.json` 中触发 attention 的历史记录。但这是**手动改写生产 journal**，违反撞坑 #107（baseline drift），不应走。

**结论**：NO-GO + 等 8/29 自动 PASS 是错误方向。

### 6.3 选项 C — NO-GO + 接受 attention 永久存在

- 放弃 v1.1-A 解锁；维持当前 attention 状态；不再尝试 rollover。
- 仅当业务允许"attention 永久不消除"才可接受。当前 v1.1-A 启动候选被 attention 阻断 30d+ 时间门，因此放弃 v1.1-A 等同于放弃整个 8/29 里程碑。
- 不推荐。

### 6.4 推荐

**CONDITIONAL GO（选项 A）**。但 docs-only worktree 期间不实施 §6.1 前置条件 1-3（涉代码 / tests-only）。实施需另开常规 code worktree 并经用户单独授权。

## 7. 已验证范围与未验证风险

### 7.1 已验证（本次只读审计）

- ✅ SESSION-STATE.md 当前状态真实反映
- ✅ 既有 ahead 4 commits 范围（`dd05d08 / c2ee261 / 3750927 / 25789cc`）
- ✅ `scripts/p3_rollover_epoch.py` 源码行为（含 fail-closed 短路）
- ✅ `tests/scripts/test_p3_rollover_epoch.py` 3 个 mock 测试
- ✅ `scripts/p3_burn_in_report.py:run_report` 资格汇总（line 956 起）
- ✅ `scripts/verify_p3_first_daily.py` 时间门逻辑
- ✅ `scripts/p3_burn_in_report.py:start_burn_in` marker 写入
- ✅ `~/Library/Application Support/MyAIEmployee/` 目录结构与归档命名
- ✅ 当前 epoch marker `state.json`

### 7.2 未验证（不在本审计范围）

- ❌ 未跟踪脚本 ruff / mypy 通过情况（未跑 ruff/mypy）
- ❌ `fail_attention / source_missing / archived_start_failed` 路径的实际行为（未跑）
- ❌ 跨设备 `os.replace` 行为（burn-in/ 与 burn-in-archive/ 同 fs，理论安全）
- ❌ 备份脚本的实际生成与 md5 校验（未生成备份）
- ❌ 实时 attention 来源的精确窗口（仅引用 SESSION-STATE 的"2026-08-11.json 仍 attention"）

### 7.3 边界与不做

- 不跑 `scripts/p3_rollover_epoch.py`（仅源码阅读）
- 不跑 `pytest`（不进入 tests-only worktree）
- 不动 `~/Library/Application Support/MyAIEmployee/burn-in/` 与 `burn-in-archive/`
- 不修改 `scripts/p3_rollover_epoch.py` / `tests/scripts/test_p3_rollover_epoch.py`
- 不 push / merge / 打 tag
- 不启用 Feature Flag / `ENABLE_*`

## 8. 推荐下一步动作

1. **今天（你确认）**：在 docs-only worktree `/tmp/wt-p3-rollover-decision-20260813` 合并 `TASK-20260813-001-p3-rollover-decision.yaml` 与本审计报告；ff-only 合入 main 后触发 push readiness 复核（含 ahead 4 的 4 个 commit）。
2. **本周（你单独决定）**：开常规 code worktree 实施 §6.1 前置条件 1-3；完成后由你单独以"授权 rollover"关键词启动执行 + §5 备份。
3. **8/29 之后**（若 §6.1 未启动）：唯一路径是接受 §6.3 NO-GO + 永久 attention 不可消除。

## 9. 决策签名（本审计输出方）

- 模型：M3（MiniMax-M3）主执行，TERRA/LUNA 未唤醒；SOL 终审为合入门（未触发，详见 MODIFICATION-LOG 同日条目）。
- 工作树：`/tmp/wt-p3-rollover-decision-20260813`，分支 `codex/p3-rollover-decision-20260813`。
- 基线：main=`25789cc`，origin/main=`cfae507`，本地 ahead 4（已含本任务的 docs-only commit 提交后应为 ahead 5）。
- 时点：`2026-08-13T12:30:00Z`（写入时）。
