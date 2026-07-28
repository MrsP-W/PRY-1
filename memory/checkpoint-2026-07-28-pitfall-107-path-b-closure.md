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

**顺序不可改 · 撞坑 #107 fix 必须先 tracked commit + 干净 `make ci`,再单独授权 rollover**

**关键语义澄清(用户 2026-07-28)**:
- ✅ Step 1 = "报告生成与核验":`p3_burn_in_report.py report` 会写入 `daily/2026-07-28.{json,md}`(**非严格只读**)· 但不动 epoch
- ❌ Step 4 = "已 tracked 之后再 rollover" → **错误**:会让 Step 4 提前触发 Step 5 的状态写入
- ✅ Step 4 = "B1 tracked 后,只做 tracked 版本校验 + 命令预览 + drill,**不执行生产路径 rollover**"
- ✅ Step 5 = "收到单独的 `rollover` 授权后,执行 `p3_rollover_epoch.py`(该命令本身同时完成 epoch 归档 + Day0 创建)"
- ✅ 真实默认路径 `p3_rollover_epoch.py` 只能在 Step 5 收到 `rollover` 关键词后执行

1. **2026-07-29 08:00(北京)**:报告生成与核验
   - `p3_burn_in_report.py report` 会写入 `daily/2026-07-28.{json,md}`(**非严格只读**)
   - 读取 `verify_first_daily.py` 输出 `result=fail_attention` + `daily_written>=1`
   - **不动 epoch**(`burn-in/` / `burn-in-archive/` 维持) · 仅日报文件生成
2. **从最新 `6ce1e5f` 创建全新 worktree**
   - **不要基于旧 `/tmp/my-ai-employee-rollover-fix-v2`**(基于 `883ab3d`,会丢 `84cb563` baseline revert + `6ce1e5f` memory 沉淀)
   - 新 worktree 名:`/tmp/my-ai-employee-rollover-fix-v3` 或 `branch=codex/pitfall-107-fix-v3`
   - `git worktree add -b codex/pitfall-107-fix-v3 /tmp/my-ai-employee-rollover-fix-v3 6ce1e5f`
3. **B1 tracked commit + 基线同步 + 干净 `make ci`**
   - 移植 P1#2 + P2#3 修复 + **改写 `post_state_check` 仅保留"阶段 + 异常类型",去除 `{exc}` 原始异常文本(隐私红线,避免日志泄露本机路径)**
   - **新增显式 `--dry-run` 参数 + 补测试**(支持 Step 4 drill 演练;当前候选无 `--dry-run`,B1 必加)
   - 新增回归测试(从 worktree v2 的 9 tests 同步 + `--dry-run` 测试)
   - 5件套 sync(撞坑 #107 fix 入 tracked,baseline 3182→3191 或 3185 等新值,9 件套全绿)
   - `make ci` 全绿后 commit(独立 commit,主题分明:`fix(scripts): 撞坑 #107 P1#2 gating 改 allow-list + P2#3 后置异常 + privacy redaction + --dry-run`)
4. **tracked 版本校验 + 命令预览 + drill**(**不执行生产路径 rollover**)
   - 校验已 tracked 的 `scripts/p3_rollover_epoch.py`:`git log --oneline -- scripts/p3_rollover_epoch.py` + `git diff main..HEAD -- scripts/p3_rollover_epoch.py`
   - 命令预览:`cat scripts/p3_rollover_epoch.py | head -60` 看主流程
   - drill 模式(用户 2026-07-28 反馈):二选一
     - (a) **临时 `app-support-dir` 演练**:`MY_AI_EMPLOYEE_APP_SUPPORT_DIR=/tmp/rollover-drill-$$ python scripts/p3_rollover_epoch.py --dry-run`(`--dry-run` 由 B1 新增)
     - (b) **`--dry-run` 路径**(B1 必加):`python scripts/p3_rollover_epoch.py --dry-run` 返回结构化验证(门控 + post_state_check 模拟)· 不调 `os.replace` / `start_burn_in`
   - **不动生产默认路径**(`~/Library/Application Support/MyAIEmployee/`)· **不写 `burn-in-archive/`** · **不开新 Day0**
5. **Step 5(单独 `rollover` 授权后)**:执行 `p3_rollover_epoch.py`(默认生产路径)
   - 用户显式 `rollover` 关键词授权(类似 `push` 关键词模式)
   - 该命令本身同时完成:**epoch 归档(`os.replace(source, archive)`)** + **新 Day0 创建(`burn_in.start_burn_in`)**
   - 验证 `result=rolled_over` + `post_state_check=ok`
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
🔴 Step 3-1 报告生成与核验(`p3_burn_in_report.py report` 写 `daily/2026-07-28.{json,md}` · 不动 epoch)
🔴 Step 3-2 从 `6ce1e5f` 创建新 worktree(不要基于旧 `/tmp/my-ai-employee-rollover-fix-v2`)
🔴 Step 3-3 B1 tracked commit(post_state_check 隐私 redaction + `--dry-run` 新参数 + 5件套 sync + make ci 全绿)
🔴 Step 3-4 tracked 版本校验 + 命令预览 + drill(临时 `app-support-dir` 或 `--dry-run` · 不执行生产路径)
🔴 Step 3-5 等单独 `rollover` 关键词授权后执行 `p3_rollover_epoch.py`(默认生产路径 · 归档 + Day0 创建同时完成)

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
- ❌ **新加**:Step 4 不执行生产路径 rollover(只校验 + 预览 + drill on 临时 `app-support-dir` 或 `--dry-run`)
- ❌ **新加**:B1 必加 `--dry-run` 参数 + 补测试(支持 Step 4 drill 演练)
- ❌ **新加**:`rollover` 需 user 显式 `rollover` 关键词授权(类似 `push` 关键词模式)
- ❌ **新加**:真实默认路径 `~/Library/Application Support/MyAIEmployee/` 只在 Step 5 `rollover` 授权后由 `p3_rollover_epoch.py` 写入
