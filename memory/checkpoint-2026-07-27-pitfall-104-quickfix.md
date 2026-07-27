---
name: checkpoint-2026-07-27-pitfall-104-quickfix
description: 撞坑 #104 docs-only MD 漂移抢修全环收口 · 3 commits 链路(ahead 2 待 push 授权)· 用户纠错"5 commits 链路"用语歧义(实际 1 pushed + 2 ahead,无单列步骤)· 9 门全绿 · 等 push 关键词授权
metadata:
  type: checkpoint
---

# 撞坑 #104 抢修全环收口(2026-07-27)

## 用户纠错(本次写入必先回应)

用户反馈:**"你所述'5 commits 链路'若含未单列步骤,建议在收口记录中补全,避免后续审计歧义。"**

实际链路:**3 commits 链路**(无单列步骤)

| # | commit | 类型 | 内容 | 远端状态 |
|---|--------|------|------|----------|
| 1 | `225c350` | docs(v1.1) | D-step plan 入库 + 5件套 stale "WIP 7 files" 校准 (6 files / +252 -8) | ✅ **pushed origin/main** |
| 2 | `1c785a4` | fix(state) | 撞坑 #104 docs-only MD 同步 298→299 (6 files / +9 -9) | ⏸ ahead 1,等 push 授权 |
| 3 | `7c829f5` | docs(memory) | 撞坑 #104 沉淀 (memory/pitfall-104-docs-only-md-drift.md, 101 行) | ⏸ ahead 2,等 push 授权 |

**无单列步骤**(即没有 docs-only fix #1 / fix #2 / fix #3 等中间 commit)。**避免混淆**:本 checkpoint 不沿用 5 commits 表述,统一为 3 commits 链路。

## 触发场景 + 暴露过程

**第 1 步**:`225c350` push 后,跑 `make check-snapshot` 报错 + `make test` 暴露 1 failed。

```
FAILED tests/test_quality_snapshot.py::test_tracked_md_count_matches_snapshot_lint
=== 1 failed, 3163 passed, 1 skipped in 121.65s ===
make: *** [test] Error 1
```

**第 2 步**:根因定位 — `docs/v1.1-p3-observation-d-step-plan.md` 入库后,`git ls-files '*.md'` 从 298 → 299,snapshot baseline 未同步 + 5件套顶部状态行 8 处仍写 `298`。

**第 3 步**:沿撞坑 #50/#87 第三层范本 docs-only 同步:
- `quality_snapshot.lint: "298 files 0 errors" → "299 files 0 errors"`
- CLAUDE.md L9+L18 + README L9 + SESSION-STATE.md L6+L20+L35 + MODIFICATION-LOG.md 质量基线 + docs/v0.2-launch-plan.md L264 全部 `298 → 299`
- (踩坑点:第一遍 grep 漏掉 SESSION-STATE.md L20"启动候选"段,通过 `make check-snapshot` 第二轮报错才发现)

**第 4 步**:commit `1c785a4` 落本地 + 沿撞坑 #103 范本沉淀 `memory/pitfall-104-docs-only-md-drift.md` 入项目 git 内 (commit `7c829f5`)

## 9 门质量门最终状态(2026-07-27)

- ✅ `make lint` **299 files 0 errors**
- ✅ `make mypy --strict` **0 errors / 292 source files**
- ✅ `make check-snapshot` **OK** (`3164 passed / 1 skipped · 299 md files` + `state entry docs match quality_snapshot`)
- ✅ working tree 干净,无未提交改动,`git diff --check` 无问题

## 业务代码改动 = 0

`1c785a4` 仅 docs-only 修改 `src/my_ai_employee/quality_snapshot.py` (1 file / 2 行 literal baseline) + 5件套顶部状态行 6 edits。

**`7c829f5`** 仅新增 `memory/pitfall-104-docs-only-md-drift.md` (101 行)。

## 红线维持

- ❌ 不动 LaunchAgent/调度(menu-bar · dashboard · agent · imap-sync · digital-employee 5 job)
- ❌ 不写 SMTP 真实发送 / Notes 真同步 / 财务 / SAP
- ❌ 不启 Feature Flag (维持 `agent_email_to_draft=dry_run`)
- ❌ 不打 v1.0 tag
- ❌ 不写 `ENABLE_NOTES_ENCRYPTION=1` / `ENABLE_PATH_4_WRITE=1` / `ENABLE_RAG=1`
- ❌ 不替用户做 `sudo pmset -a sleep 0` (7d 前推荐,等用户主动 paste)
- ❌ 不自动 `launchctl load -w` 数字员工 plist (撞坑 #91-#98 未授权重启)
- ❌ **未执行 git push** — ahead 2 等用户显式 push 关键词授权

## 撞坑 #104 范本价值(后续审计参考)

撞坑 #50(2026-06-24 第一版 8 处同步范本)→ 撞坑 #87(2026-06-26 passed 公式)→ 撞坑 #103(2026-06-29 stash 暂存)→ **撞坑 #104 NEW(2026-07-27 docs-only commit 后必跑 `make check-snapshot` 而非只看 `make lint`)**。

**关键约束**:
1. docs-only commit (新增 .md) 后,**必跑 `make check-snapshot`**(`make lint` 只扫格式不扫文件计数,不暴露 md 漂移)
2. 5件套顶部状态行同步清单 = **8 处**:CLAUDE L9+L18 + README L9 + SESSION-STATE L6+L20+L35 + MOD-LOG 质量基线 + v0.2-launch-plan L264
3. SESSION-STATE L20"启动候选"段与 L6 状态段 是 grep 容易遗漏的两段,务必双跑 grep + `make check-snapshot` 二验

## 关联

- [[pitfall-50-snapshot-guardian-drift]] — docs-only 第三层 baseline 范本始祖
- [[pitfall-87-snapshot-self-referential-drift]] — baseline passed 公式
- [[pitfall-103-stash-collected-drift]] — git stash 暂存 tracked 测试 → collect 漂移
- [[pitfall-104-docs-only-md-drift]] — 本次新增,docs-only commit 后必跑 check-snapshot 范本
- [[pitfall-102-verify-p3-cli-too-early-test-time-coupled]] — CLI 时序硬编码范本
- [[docs/v1.1-p3-observation-d-step-plan]] — 触发本撞坑的 D-step plan (新增 1 .md → +1)
- [[checkpoint-2026-07-27-p3-epoch-governance]] — 上轮 P3 epoch 治理全环收口
- [[checkpoint-2026-07-27-p3-window-drift-fix]] — 撞坑 #102 cli too_early 抢修全环

## Why / How to apply

**Why**:docs-only commit (新增 1 .md) 后,**只跑 `make lint` 仍可能通过而 `make test` 真跑才暴露 md 漂移**;若 docs-only commit 后立即 push 不验证,等于把"docs-only = 0 风险代码"的语义破坏 — 上线后任何审计/检查员走 `make test` 都会撞红 + 用户会反馈"为什么 commit 通过却 test 失败"。

**How to apply**:
1. docs-only commit 完成 → `make check-snapshot` 必跑 → `make test` 必跑(不可省)
2. 5件套顶部状态行同步 8 处齐全:CLAUDE L9+L18 + README L9 + SESSION-STATE L6+L20+L35 + MOD-LOG 质量基线 + v0.2-launch-plan L264
3. 沉淀用 `memory/pitfall-XXX-*.md`(项目内,git 内跟踪)沿撞坑 #103 范本
4. 用户反馈"链路/收口表述歧义"必先回应再继续 — 本 checkpoint 纠正"5 commits 链路"为"3 commits 链路"

## 下一棒

- **等用户 push 关键词授权**:`push` / `推 origin` → `git push origin main` (ahead 2:`1c785a4` + `7c829f5`)
- **保持 HOLD**:首日报 2026-07-29T00:00Z + 7d 2026-08-03 + 30d 2026-08-26 + `sudo pmset -a sleep 0` 7d 前推荐
- **9 门全绿**:`make lint` 299 0 err / `make mypy` 292 0 err / `make check-snapshot` OK
