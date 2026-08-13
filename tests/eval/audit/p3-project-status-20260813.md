# P3 与项目状态只读校准（2026-08-13）

## 1. 结论

本轮证据采集于 2026-08-13 11:31–11:43 CST。当前 health 点健康、最新 news
run 成功，但最近 4 次 news interval 为 99.33 分钟，超过 90 分钟门槛，整体
间隔门未通过。fixture 契约保持通过，但 v1.1-A 仍为 **NOT_UNLOCKED**。固定
24h 恢复窗口 PASS 和当前实时健康点均不能覆盖当前 epoch 已存在的日报
attention，也不能替代 7d / 30d 必须门槛。

本轮同时完成 Git worktree 元数据维护：123 条目录已不存在的失效登记已在
备份、dry-run 和不变量核验后移除；所有分支及三棵有效工作树的内容保持不变。

## 2. 执行边界

- 只读取 P3 health、news、burn-in 状态和 launchd 注册状态。
- 项目文件仅修改状态文档与任务契约，不修改业务代码或测试逻辑。
- 不执行 push、tag、rollover、restart、kickstart 或 `ENABLE_*` 变更。
- 不访问 SMTP、Notes、SAP、财务或其他真实外部写入。
- 不修改、暂存、stash、reset 或清理主树与副树的用户 WIP。

## 3. Git 与任务状态

| 检查项 | 结果 |
| --- | --- |
| 本地 main | `dd05d0836c42987f4eff27b2cf205f4029ba47e2` |
| 远端 main | `cfae507c7a95c772b77f04939e1741301565cb7d`（本轮 `ls-remote` 核验） |
| ahead / behind | `1 / 0` |
| tracked / staged 修改 | 0 / 0 |
| 主树未跟踪 WIP | 16 个展开文件；紧凑状态显示 13 行 |
| `TASK-20260812-001` | 2026-08-12 15:37:54 CST 已 ff-only 进入本地 main |
| 远端同步 | 未 push |

因此 `TASK-20260812-001-p3-recovery-status` 从 `ready_to_merge` 校准为 `done`，
同时显式记录 `pushed=false`。本轮不把“本地已集成”表述为“远端已发布”。

## 4. P3 实时只读快照

### 4.1 当前运行点

`health/state.json` 与最新 health journal 行显示：

- `updated_at=2026-08-13T03:31:25.921684Z`；
- `healthy=true`、`reasons=[]`；
- `alert_open=false`、`failure_streak=0`；
- Dashboard `ok=true`、`read_only=true`；
- loopback listener 为 `127.0.0.1:8765`，探针记录端口正在监听；
- menu-bar 与 dashboard 为 required-running 且均有 PID；
- `com.myaiemployee.agent` 已注册但 `required_running=false`，当前无 PID。

最新 news journal 行：

- `at=2026-08-13T03:05:44.165938Z`；
- `success=true`、`degraded=false`、`outcome=success`；
- `item_count=48`。
- `2026-08-13T03:43:11Z` 执行只读
  `verify_launchd_intervals.py --wait-seconds 0`：health
  `max_gap=10.0m`、`tail=1.75m`、PASS；最近 4 次新闻运行的最大间隔为
  99.33 分钟，超过 90 分钟观察阈值，news interval FAIL。虽然
  每次 run 均成功且未降级，实时间隔检查仍不能判 PASS。

这些是当前运行点证据，不是完整资格窗口结论。

### 4.2 固定窗口与历史日报

- 固定恢复窗口：`2026-08-10T05:21:20.671725Z` 至
  `2026-08-11T05:26:14.466Z`，24.0816h，结论 PASS。
- 该窗口 health 144 条、unhealthy=0、最大含边界间隔 635.001684s；news
  24 次、run 级失败 0、最大含边界间隔 3642.248597s。
- `openai-videos` 的 3 次单来源错误所对应 run 均成功且未降级，按固定窗口
  合同为非阻断风险。
- 最新完整日报 `burn-in/daily/2026-08-11.json` 仍为 `status=attention`，
  attention 为 `health_sample_gap`、`news_run_gap`、`news_failure`。
- Day0 权威来源 `burn-in/state.json.started_at` 仍为
  `2026-07-30T07:04:45.527698Z`，本轮未 rollover。

固定窗口 PASS、实时健康点和历史日报属于不同时间口径，必须并列保留，不能
互相覆盖。

## 5. v1.1-A 门槛

| # | 必须门槛 | 状态 | 本轮判定 |
| --- | --- | --- | --- |
| 1 | P3 7d unattended | FAIL | 当前 epoch 仍有正式 attention 记录 |
| 2 | P3 30d P0/P1-free | FAIL | 最早 2026-08-29，且仍须 attention 清零 |
| 3 | 评测样本不少于 30 条 | PASS | 现为 40 条；契约测试 169 passed |
| 4 | Feature Flag / SLO / Feedback 文档 | PASS | 仅 design/docs 层，未解冻运行接口 |

总计 **2 PASS / 2 FAIL**，v1.1-A 保持 **NOT_UNLOCKED**。候选门槛 #5 的
40 条 fixture PASS 不替代上述四项必须门槛。

## 6. Worktree 盘点与维护

### 6.1 安全门

执行前完成以下检查：

1. 本轮用户以“按照建议执行”明确授权建议中的 worktree 维护；任务契约将
   `requires_approval` 记录为 `true` 并限定授权范围；
2. 交互执行 `git worktree prune --dry-run --verbose`；
3. dry-run 精确得到 123 条，且每条原因均为
   `gitdir file points to non-existent location`；
4. `git worktree list --porcelain` 同样得到 `prunable=123`；
5. 备份 `.git/worktrees` 到
   `/private/tmp/my-ai-employee-git-worktrees-metadata-20260813.tar.gz`；
6. 保存主树、副树、任务树的完整 status 和全部本地分支引用快照。

证据限制：首次 dry-run 的持久化文件只捕获 stdout，而 Git 将提示写入 stderr，
因此该文件为 0 字节，不能作为持久证据。交互输出已完成 123 条严格核验；持久
证据采用 123 行实际 prune 输出、执行前元数据备份以及四组前后 `cmp`。本报告
不把空文件表述为成功保存的 dry-run 日志。

### 6.2 执行结果

| 不变量 | 执行前 | 执行后 |
| --- | ---: | ---: |
| Git worktree 总条目 | 126 | 3 |
| `.git/worktrees` linked 元数据目录 | 125 | 2 |
| prunable 登记 | 123 | 0 |
| 有效 worktree | 3 | 3 |
| 本地分支 | 128 | 128 |
| 主树未跟踪文件 | 16 | 16 |
| 存活副树 status 行 | 9 | 9 |
| 本任务树 status 行 | 1 | 1 |

三份 status 与分支引用快照均通过字节级 `cmp`。本次仅移除 Git 的失效
worktree 管理元数据，没有删除分支、现存目录或 WIP 文件。

存活副树继续保留：

- 路径：`/Users/wei/Documents/DesktopOrganizer/worktrees/my-ai-employee-d6102`；
- 分支：`codex/d6102-stash-playbook`；
- HEAD：`a1c8469`；
- 状态：9 行 WIP，其中任务 YAML 同时含 staged 与 unstaged 修改；
- 决策：不迁移、不清理、不 reset、不 stash，等待所有者另行处理。

备份只作为事故恢复证据，不应在 Git 仍运行时直接覆盖回 `.git/worktrees`；如需
恢复，先停止相关 Git 操作并人工核验目标路径。

## 7. 质量门

| 命令 | 结果 |
| --- | --- |
| `pytest tests/eval/test_eval_fixtures_schema.py -q --no-cov` | 169 passed |
| `ruff check tests/eval` | All checks passed |
| `git diff --check` | 通过 |
| 关键状态文档 Markdown lint | 本任务提交前复跑 |
| 项目完整 Markdown lint | FAIL：`MODIFICATION-LOG.md` 25 条 MD012/MD022 |

完整 Markdown lint 的 25 条问题来自既有 `MODIFICATION-LOG.md`，本任务不混入
修复。它们不表示 fixture 或业务代码失败，但在修复前不能宣称项目全质量门
通过。

## 8. 后续动作

1. 保持 v1.1-A 冻结，不执行生产或外部写入。
2. 将本 docs-only 校准任务交 SOL / LUNA 只读复审；通过后仅提交任务分支。
3. `MODIFICATION-LOG.md` 格式修复另开 docs-only 任务，避免与状态校准混合。
4. 仅在 Day0 未改变且 attention 有正式清零证据时，于 2026-08-29 后重核
   30d 门槛。
5. push、rollover、Feature Flag 解冻和存活副树处理均须新的单独授权。
