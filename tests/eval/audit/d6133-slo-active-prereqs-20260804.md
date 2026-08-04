# D6.13.3 SLO 从 design-only 切换到 active 的实施前置清单（docs-only）

**任务**：在 P3 7d 通过时点附近（不是现在），把当前已集成到 main 的 `docs/v1.1-slo-contract.md` 5 个 SLO 维度从 `inactive` 切换到 `active`。
**范围**：docs-only；列前置条件、依赖、阻断条件；不实施任何采集器、告警、看板、调度、写入或邮件。
**基础**：`docs/v1.1-slo-contract.md` HEAD 在 main（4 commits chain：`4e0baff → 93f14f5 → 81651f5 → 7b6c0c1`）。本文假设该设计契约不再修改；如有变更，先重启本文。

## 1. 当前现状（已存在 vs 待建）

| 维度 | SLI | 数据源级 | active 前置类型 | 当前进度 |
|------|-----|---------|-----------------|----------|
| SLO-1 availability | `healthy_rate` + `active_open_alerts = 0` | `existing` | 渠道与告警 | health samples/alerts 已有；active_open_alerts 重算需时段重建 |
| SLO-2 freshness | 双端窗口 anchor | `existing` | 窗口与聚合 | news runs 已有；窗口起点/终点收集模式待切片化 |
| SLO-3 result quality | 离线评测聚合 | `existing`/`partial` | 评测 runner 与聚合 | `tests/eval/` 30-fixture + schema 测试已就绪；聚合 runner 概念为 `partial` |
| SLO-4 response latency | p50 / p99 | `partial` / `future` | 采集器 | 当前未采集 capability latency；属于 D6.13.3 设计契约中的 `partial`/`future` |
| SLO-5 security / compliance | `decision_coverage_rate` + `evaluation_status` | `existing`/`future` | 决策流与摘要密钥 | D6.15.2 audit 已集成；D6.15.3 密钥生命周期评估未集成；D6.11.2 FF docs 未集成 |

## 2. 通用前置（任一 SLO active 都需满足）

1. **审计通道打通**：复用 D6.13.3 SLO 自身审计事件最小集（`resolved(pass)` / `breach` / `unknown`），不新设独立通道。
2. **告警通道**：单窗口告警可走本机日志；通知渠道（Mail / Slack / Notes）必须经 D6.11.2 Feature Flag + 单独审批任务。
3. **Feature Flag 接入**：与 `runtime.credential_access`、`runtime.alerting_enabled`、`runtime.report_publishing` 三类 gate 联动。
4. **采集器隔离**：所有 SLO 采集器跑在同一 watch 子目录下，禁止污染 main 业务代码；不进入 LaunchAgent。
5. **P3 7d 通过**：硬门之一；任一完整 UTC 日出 `attention` 即不可切 `active`。
6. **burn-in 数据保留**：原有 `p3_burn_in_report.py` 历史 evidence 不能被新 SLO 覆盖或回写。
7. **新 SLO 不得放宽现有 attention 规则**：现有规则对任一不健康 sample fail-closed，新 SLO `available_rate >= 99%` 不能反推放宽。
8. **docs 先行**：本文完成后另开 docs-only 实施前置核对（4 文件白名单）；实施前不再以"前置契约"为唯一依据。

## 3. 每维度独立前置

### 3.1 SLO-1 availability

- 重建 `active_open_alerts` 末态：从 `alert_id` 最新事件状态推算，而非窗口内 `opened` 累计。
- health samples journal 在 P3 watch 下落库；schema 校验器拒绝 row 残缺（`unknown`）。
- `healthy_rate >= 99.0%` 与 `active_open_alerts = 0` 同时成立才 `pass`；任一不成立即时切 `breach`。
- 恢复条件：连续 3 个 valid sample healthy + 当前 alert 已 `resolved`；仅关闭告警，不抹除 breach 日结。

### 3.2 SLO-2 freshness

- 完整日 anchor：UTC 00:00:00–23:59:59，仅完整 UTC 日进入定稿；不足一日仅入滑动窗口。
- 双端窗口起点/终点必落 audit：起点 sample、终点 sample、两者 elapsed 秒数。
- 跨 scope 聚合：news / health / eval 分别取 anchor 后按 `scope` 拼装。
- 任一 scope 窗口残缺（start/end 缺失），整体判 `unknown`。

### 3.3 SLO-3 result quality

- 走 `tests/eval/` 已有 30-fixture + privacy/ID guards；runner 周期性跑得结果可重放。
- 任何 schema 失败、privacy 命中、ID 前缀违规，相应 suite 判 `unknown`；其他 suite 不豁免。
- 聚合 runner 输出的 breach 列表必须给出"哪个 suite / 多少 fixture / 哪个 guard"的颗粒度。
- 不动 `tests/eval/test_eval_fixtures_schema.py` 已有 69 passed 测试。

### 3.4 SLO-4 response latency

- 数据源当前为 `partial`/`future`：capability latency 尚未在本机持续采集。
- 采集器接入属于 P3 后实施任务，不在 D6.13.3 docs-only 范围。
- 切片前 SLO-4 维持 `inactive`；切前必须前置完成至少 7 个完整 UTC 日的样本覆盖。
- p50 / p99 阈值在 D6.13.3 设计契约冻结；切换前不可临时调整。

### 3.5 SLO-5 security / compliance

- `decision_coverage_rate` 已可基于现有 30-fixture 计算（合法 deny + 合法 allow / 总数）。
- `evaluation_status` 三态：`pass` / `breach` / `unknown`；`unknown` 不豁免其他 SLO。
- 凭据相关判定（摘要密钥生命周期）必须在 D6.15.3 凭据审批任务批准后才进入 active；未批准前 SLO-5 也判 `unknown`。
- 与 D6.11.2 Feature Flag 的 `runtime.credential_access` gate 同步：未启用 gate 时不计算涉及密钥的覆盖率子项。

## 4. 切换动作草案（待用户单独批准，本轮不实施）

```text
# 假设条件：P3 7d 已通过、用户凭据审批已批准、Feature Flag gate 已开
git checkout main
git pull
# 仅当 SLO-1/2/3 满足 active 前置时：
scripts/slo/activate_slo_1_to_3.py
# SLO-4 在 7 日样本覆盖后切换：
scripts/slo/activate_slo_4.py
# SLO-5 在凭据审批通过、Feature Flag gate 开启后切换：
scripts/slo/activate_slo_5.py
```

替换的"激活脚本"为占位；其存在性属于未来实施任务。任何激活动作必须出现 docs/agent-team/tasks 下任务包，并经集成审批 + push 单独授权。

## 5. 阻断条件（任一发生，禁止切换 active）

- 任一完整 UTC 日 health/news/eval 出现 `attention`。
- 30-fixture privacy/ID guard 出现新违规且修复未集成。
- D6.11.2 Feature Flag `runtime.credential_access` 未切到允许态却尝试 SLO-5 active。
- 摘要密钥生命周期评估未集成且 D6.15.2 schema 已集成。
- P3 7d 内出现 P0/P1；或日 burn-in evidence 文件被新逻辑覆盖。
- LaunchAgent / SMTP / Notes / 真实数据写入被任何 active 切换副作用触发。

## 6. 不在本评估内（明确排除）

- 不实施任何采集器、告警、看板、调度。
- 不修改 `docs/v1.1-slo-contract.md` 现有 5 维度定义、阈值、窗口、聚合规则。
- 不接触用户未跟踪 WIP 与候选分支（`eba1050`、`11f92ef`、`69cbb2f`）。
- 不替代 P3 readiness 数字或 burn-in 窗口判定。

## 7. 验收清单（设计文档层面，本轮即检查）

- [x] 列出 5 个 SLO 当前数据源级与 active 前置类型。
- [x] 给出 8 项通用前置与 5 维度独立前置。
- [x] 阻断条件明确且可独立判定。
- [x] 不涉及 `docs/v1.1-slo-contract.md` 的修订。
- [x] 不触动任何候选分支、用户 WIP 或 v1.1-A readiness 数字。

## 8. 与现有 readiness 的关系

| readiness 项 | 当前 main | 本文影响 |
|--------------|-----------|----------|
| 30-fixture privacy/ID guards | PASS | 不变 |
| D6.13.3 SLO docs 集成 | PASS（chain） | 不变；本文不修订设计契约 |
| D6.11.2 Feature Flag docs 集成 | FAIL | 本文不修 |
| D6.15.2 Feedback schema docs 集成 | PENDING（候选 `11f92ef` 可集成） | 不变；用户单独批准后才会变 |
| D6.15.3 摘要密钥生命周期评估 | PENDING（候选 `eba1050`） | 不变；本文与 `eba1050` 评估结论一致：未实施前 SLO-5 不能 active |
| 7d/30d attention | FAIL | 不变 |
| 当前 main 的 v1.1-A UNLOCKED | 否 | 不变；本文是激活前置，不替代 readiness |

---
*核验人：Codex 协调主 Agent（gpt-5.6-luna，max）。*
*模型调用：SOL=未唤醒；TERRA=未唤醒；LUNA=主 Agent 自身；M3=无法通过 Codex 原生通道调用，本轮 docs-only 不触发 external bridge。*
*无外部写入；不动用户 WIP；未触发 push；未集成候选；未跨人工审批门。*
