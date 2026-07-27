---
name: pitfall-104-docs-only-md-drift
description: "docs-only commit (含新增 .md) 后未同步 quality_snapshot.py baseline + 5件套顶部状态行,导致 test_tracked_md_count_matches_snapshot_lint 红 + check-snapshot state-entries 报错;修法 沿撞坑"
metadata: 
  node_type: memory
  type: pitfall
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
---

# 撞坑 #104 — docs-only commit 后 5件套 MD 同步遗漏

## 触发场景

docs-only commit 新增 1 个 `.md` 文件(如 `docs/v1.1-p3-observation-d-step-plan.md` 入库)后,
未在同次 commit(或后续 commit)同步:

1. `src/my_ai_employee/quality_snapshot.py` 的 `lint: str = "298 files 0 errors"` baseline
2. 5件套顶部状态行(CLAUDE.md L9 + L18 + README L9 + SESSION-STATE.md L6 + L20 + L35 + MOD-LOG 质量基线 + docs/v0.2-launch-plan.md L264)的 `MD lint 298` / `298 MD` 字样

立即触发 2 重失败:

- `tests/test_quality_snapshot.py::test_tracked_md_count_matches_snapshot_lint` RED:
  `count_tracked_md_files(PROJECT_ROOT) == 298` 但实测 299 (新增 +1)
- `make check-snapshot` 中 `scripts/check_state_entries.py` 报 `state entry docs match quality_snapshot` 失败:
  SESSION-STATE.md L6/L20/MOD-LOG L118 写 `298` vs snapshot 写 `299`

## 失败场景

```
$ make check-snapshot
OK: quality_snapshot matches live baseline (3164 passed / 1 skipped · 298 md files)
ERROR: SESSION-STATE.md:20 missing 'MD lint **299**' (entry drift vs quality_snapshot)
ERROR: SESSION-STATE.md:20 stale 'MD lint **298**' (entry drift vs quality_snapshot)
make: *** [check-snapshot] Error 1
```

`make test` 中:
```
FAILED tests/test_quality_snapshot.py::test_tracked_md_count_matches_snapshot_lint
=== 1 failed, 3163 passed, 1 skipped ===
make: *** [test] Error 1
```

## 根因

撞坑 #50 范本 (`src/my_ai_employee/quality_snapshot.py` line 5-6 注释明示):
"docs-only 规则:不前进 pytest/coverage; **新增 Markdown 后必须同步 MD lint 计数**(与 `git ls-files '*.md'` 对齐 · `make lint` 仅扫 tracked 文件)。"

实际操作中:
1. docs-only commit 完成,git push
2. 跑验证时**漏跑** `make check-snapshot`(只跑了 `make lint`,显示 299 files 0 errors,但 5件套没有同步 git push 前已察觉)
3. `make test` 真跑才暴露 1 failed + `make check-snapshot` state-entries 红

撞坑 #50 第三层同步范本(L9+L18 + L6+L20+L35 + MOD-LOG 质量基线 + v0.2-launch-plan L264)明示:**5件套含 8 处需同步对象**,偶有遗漏(本次 L20 启动候选段)。

## 修法 (沿撞坑 #50/#87/#103 docs-only 范本)

```bash
# 1. 修 quality_snapshot.py baseline
sed -i 's|lint: str = "298 files 0 errors"|lint: str = "299 files 0 errors"|' \
  src/my_ai_employee/quality_snapshot.py

# 2. 5件套同步 docs-only 顶部状态行
# CLAUDE.md L9 + L18 + README L9 + SESSION-STATE L6+L20+L35
# + MOD-LOG 顶部"质量基线"行 + docs/v0.2-launch-plan.md L264

# 3. 验证 (必跑 make check-snapshot,不只 make lint)
make check-snapshot   # OK + state entries OK
make lint             # 299 files 0 errors
make mypy             # 0 errors / 292 files

# 4. docs-only commit
git add CLAUDE.md README.md SESSION-STATE.md MODIFICATION-LOG.md \
        docs/v0.2-launch-plan.md src/my_ai_employee/quality_snapshot.py
git commit -m "fix(state): #104 docs-only MD 同步 298→299"
```

## 范本价值

撞坑 #50 第一版(2026-06-24)只规定"5件套 + quality_snapshot 同步",
撞坑 #87(2026-06-26)细化"`passed = collected - stable_failures` baseline 公式",
撞坑 #103(2026-06-29)沉淀"`git stash` 暂存 tracked 测试 → collected 漂移",
撞坑 #104 NEW(2026-07-27)沉淀"**docs-only commit 后首次 push 前,必跑 `make check-snapshot` + `make test` 双验**(光跑 `make lint` 不够)。

## 关联

- [[pitfall-50-snapshot-guardian-drift]] — docs-only 第三层 baseline 范本始祖
- [[pitfall-87-snapshot-self-referential-drift]] — baseline passed 公式
- [[pitfall-103-stash-collected-drift]] — git stash 暂存 tracked 测试 → collect 漂移范本
- [[pitfall-102-verify-p3-cli-too-early-test-time-coupled]] — CLI 时序硬编码范本
- [[docs/v1.1-p3-observation-d-step-plan]] — 触发本撞坑的 D-step plan (新增 1 .md → +1)

## Why / How to apply

**Why**: P3 epoch 治理收口 + D-step plan 入库 + push origin/main 后,用户跑 `make ci` 才暴露 1 failed;
不在 docs-only commit 内完成同步 → 触发 push 后状态不一致 + 用户察觉 → 等于失去 docs-only 同步核心价值。

**How to apply**:
1. docs-only commit (新增 .md) 后,**必跑 `make check-snapshot` 而非只看 `make lint`** — 后者只扫格式不扫文件计数
2. 5件套顶部状态行同步清单(8 处):CLAUDE L9+L18 + README L9 + SESSION-STATE L6+L20+L35 + MOD-LOG 质量基线 + v0.2-launch-plan L264
3. 沿袭撞坑 #50 grep pattern: `grep -rn "MD lint 298\|298 MD\|298 files" CLAUDE.md README.md SESSION-STATE.md MODIFICATION-LOG.md docs/v0.2-launch-plan.md`
