---
name: checkpoint-2026-07-28-pitfall-107-path-b-closure
description: 撞坑 #107 P1#1 baseline drift Path B 保守 revert 收口 + push origin/main + Step 3 序列锁定(用户 2026-07-28 反馈)
metadata:
  type: checkpoint
---

# 2026-07-28 撞坑 #107 P1#1 baseline drift Path B 保守 revert 收口 + Step 3 序列锁定

✅ 已完成:9 项
🔄 进行中:1 项(等首日报门 2026-07-29T00:00:00Z)
📋 待办:5 项(Step 3 序列 + 红线)

## 关键产出

- commit `84cb563`:fix(state): baseline 3182→3179 revert(6 files / +9 -9)
- commit `6ce1e5f`:docs(memory): 撞坑 #107 P1#1 Path B 保守 + 收口 checkpoint(2 files / +145)
- push origin/main:`883ab3d..6ce1e5f main -> main` ✅ 用户授权 `push` 关键词
- 5件套 sync(quality_snapshot.py + CLAUDE/README/SESSION-STATE/MOD-LOG/v0.2-launch-plan)
- 独立 worktree `/tmp/my-ai-employee-rollover-fix-v2`:撞坑 #107 P1#2 + P2#3 fix 候选(9 tests 全绿 · watch_once kwarg bug 顺手修)untracked 不入 tracked(红线)· **基于 `883ab3d`(旧 HEAD)**,B1 移植前需从最新 `6ce1e5f` 重建
- `memory/pitfall-107-baseline-drift-p1-path-b.md` 范本(本轮新增 · docs-only)
- `MEMORY.md` 索引同步 +2 行

## Step 1-3 全环收口(本轮)

- **Step 1** 撞坑 #106 二修 + merge PR #5 + 撞坑 #103/104/105 全闭环(commit `63eb8bb` + `883ab3d`)
- **Step 1.5** baseline 3182 dirty drift → 撞坑 #107 P1#1 NEW(commit `5c794bd` 是诱因)
- **Step 2** 用户 critical review + Path B 决策(不动 P3 epoch 文件 + 保守 revert)
- **Step 3** 撞坑 #107 二修候选(独立 worktree 9 tests PASS · ruff + format + mypy clean)
- **Step 4** quality_snapshot.py + 5件套 baseline 3182→3179 sync ✅ commit `84cb563`
- **Step 5** 撞坑 #107 沉淀 docs(pitfall-107 memory file)✅ docs-only commit `6ce1e5f`
- ✅ **Step 6** push origin/main(`883ab3d..6ce1e5f`)✅ 用户授权 `push` 关键词

## 9 质量门状态

干净 main(check-snapshot aware exclude untracked):
- pytest:`make test` 仅 tracked → 3179 passed / 1 skipped / **90.26%** ✅
- ruff check:`src/ tests/scripts/ scripts/` ✅ all clean
- ruff format:`src/ tests/scripts/ scripts/` ✅ 222 files already formatted
- mypy `src/`:`Success: no issues found in 143 source files` ✅
- make lint:305 MD files 0 errors ✅
- check-snapshot:working tree 含 3 untracked P3 tests → collected 3183 ≠ 3180 expected → RED(Path B 接受 · working tree drift allowed)
- alembic `--sql`:沿用 v0.2.39 baseline ✅
- uv build:`uv build` OK 沿用 ✅
- coverage:90.26% ✅

## 关键 commit hash

- `6ce1e5f` docs(memory): 撞坑 #107 Path B 保守 + 收口 checkpoint[HEAD/origin/main]
- `84cb563` fix(state): baseline 3182→3179 revert(Path B 本轮)
- `883ab3d` fix(docs): daily/2026-07-29.*→07-28.* 漂移修复
- `5c794bd` fix(state): baseline 3179→3182 同步(撞坑 #106 post-merge untracked 3 tests 入 baseline)— 撞坑 #107 P1#1 诱因 · commit `84cb563` 撤回
- `63eb8bb` fix(ops+tests+state): 撞坑 #106 二修(PR #5 merge)
- `a057ad9` P1-1 mypy 严格模式 9 errors 修复

## Step 3 序列(用户 2026-07-28 反馈锁定 · 撞坑 #107 B1 路径)

**顺序不可改 · 撞坑 #107 fix 必须先 tracked commit + 干净 `make ci`,再执行 rollover**

1. **2026-07-29 08:00(北京)**:只读首份日报核验
   - `p3_burn_in_report.py report` 读取 `verify_first_daily.py` 输出 `result=fail_attention` + `daily_written>=1`
   - **不执行 rollover** · 仅核验状态 · 不动业务
2. **从最新 `6ce1e5f` 创建全新 worktree**
   - **不要基于旧 `/tmp/my-ai-employee-rollover-fix-v2`**(基于 `883ab3d`,会丢 `84cb563` baseline revert + `6ce1e5f` memory 沉淀)
   - 新 worktree 名:`/tmp/my-ai-employee-rollover-fix-v3` 或 `branch=codex/pitfall-107-fix-v3`
   - `git worktree add -b codex/pitfall-107-fix-v3 /tmp/my-ai-employee-rollover-fix-v3 6ce1e5f`
3. **B1 tracked commit + 基线同步 + 干净 `make ci`**
   - 移植 P1#2 + P2#3 修复 + **改写 `post_state_check` 仅保留"阶段 + 异常类型",去除 `{exc}` 原始异常文本(隐私红线,避免日志泄露本机路径)**
   - 新增回归测试(从 worktree v2 的 9 tests 同步)
   - 5件套 sync(撞坑 #107 fix 入 tracked,baseline 3182→3191 或 3185 等新值,9 件套全绿)
   - `make ci` 全绿后 commit(独立 commit,主题分明:`fix(scripts): 撞坑 #107 P1#2 gating 改 allow-list + P2#3 后置异常 + privacy redaction`)
4. **再使用已跟踪版本执行 rollover**(tracked 后才允许)
   - **不能先运行未跟踪脚本再补提交**(撞坑 #107 的本质教训:working tree ≠ tracked 必须 commit 之后再跑)
   - `python scripts/p3_rollover_epoch.py`(从已 tracked commit 起 new worktree)
   - 验证 `result=rolled_over` + `post_state_check=ok`
5. **epoch 归档 + Day0 重开 单独授权**
   - 撞坑 #107 fix 入 tracked + 干净 `make ci` + rollover 成功后,**epoch 归档与 Day0 重开仍需用户单独授权**(沿红线"不抢控制权")
   - 归档路径:`burn-in-archive/epoch-2026-07-27T05-34-24Z/`(沿用 #107 P1#2 fail_attention + daily_written>=1 双门判)

## 撞坑 #107 fix 候选 → B1 入 tracked 前必改(用户 2026-07-28 反馈)

**隐私红线**:`post_state_check` 当前包含 `{exc}` 原始异常文本(如 `warning:RuntimeError:run_report:simulated report failure`),`{exc}` 可能泄露本机路径或敏感信息(撞坑 #79 红化 spike 断 Keychain 同源风险)。

**入库前必改**:仅输出"阶段 + 异常类型" — 例如:
- ✅ `warning:RuntimeError:run_report`
- ✅ `warning:TypeError:watch_once`
- ✅ `warning:RuntimeError:run_report;warning:TypeError:watch_once`(多段串联)
- ❌ `warning:RuntimeError:run_report:simulated report failure`(泄露)

**Why**:撞坑 #79 红化误伤 + 撞坑 #97 SQLCipher 路径 都已暴露:`{exc}` raw 字符串包含 `__file__` / `Path.home()` 等本地信息,日志/redact 都可能漏。
**How to apply**:所有脚本 / CLI / JSON payload 字段内禁止内嵌 raw exception text,只保留 `type(exc).__name__` + 阶段标识(如 `run_report` / `watch_once` / `start_burn_in`)。如需 traceback,落本地 stderr,不进 payload。

## 后续 — Step 3 序列执行

🔴 等首份日报门 **2026-07-29T00:00:00Z**(北京 07-29 08:00)开窗
🔴 Step 3-1 只读首日报核验(`p3_burn_in_report.py report`,不执行 rollover)
🔴 Step 3-2 从 `6ce1e5f` 创建新 worktree(不要基于旧 `/tmp/my-ai-employee-rollover-fix-v2`)
🔴 Step 3-3 B1 tracked commit(post_state_check 隐私 redaction + 5件套 sync + make ci 全绿)
🔴 Step 3-4 已 tracked 后执行 rollover
🔴 Step 3-5 epoch 归档 + Day0 重开 单独授权

## 红线全维持

- ❌ 不抢控制权 / 不联网外传 / 不收费 SaaS
- ❌ SMTP 真发需授权 / Notes 真同步默认 dry-run
- ❌ `ENABLE_PATH_4_WRITE=1` / `ENABLE_NOTES_ENCRYPTION=1` 不写
- ❌ v1.0 tag 不打 / git push 需 user 显式 `push` 关键词
- ❌ launchctl load -w 数字员工 需 user 授权
- ❌ 不替用户做 sudo
- ❌ 不动 LaunchAgent load / health/news 调度
- ❌ docs-only 期间不动业务代码(本轮 commit 全是 state/docs)
- ❌ tests-only 期间不跑真实业务
- ❌ 不动 P3 epoch 治理文件(restore 防线:`scripts/p3_rollover_epoch.py` / tests/scripts/test_p3_rollover_epoch.py / ops/claude-p3-watch*)
- ❌ Feature Flag / 15→30 样本扩展 / Claude LaunchAgent 安装 / 删除旧 worktree 一律不做
- ❌ **新加**:不允许先运行未跟踪脚本再补提交(B1 顺序锁)
- ❌ **新加**:payload 字段禁止内嵌 raw exception text(撞坑 #107 fix 入库前必改)
