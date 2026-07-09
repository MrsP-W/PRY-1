---
name: checkpoint-2026-07-09-p3-a-t3-l2-91-fix
description: P3-A T3 L2 撞坑 #91 修复收口 · commit db3f2e4 · 数字员工 wrapper 改调 ~/bin runner · MY_AI_EMPLOYEE_PROJECT_ROOT override · F4-F6 契约测试 · make ci 9 门全绿 2907/1/270/256/89.12% · ahead 1 等 push · T3 L3 数字员工 launchctl load 单独授权
metadata:
  node_type: memory
  type: checkpoint
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
---

# P3-A T3 L2 撞坑 #91 wrapper 修复收口 2026-07-09

## 🎯 一句话

P3-A T3 L2 收口:撞坑 #91 修复路径 A 落地 · commit `db3f2e4` · `scripts/launchd_install.sh` 新增 `~/bin/my-ai-employee-digital-runner` · `my-ai-employee-start` 改设 `MY_AI_EMPLOYEE_PROJECT_ROOT` 后调 runner · `ops/start-digital-employee.sh` 支持 project root override · `tests/scripts/test_launchd_install.py` F4-F6 契约测试 · `make ci` 9 门全绿 **2907 passed / 1 skipped / 270 MD / 256 mypy / 89.12%** · 本地 HEAD ahead origin 1 · 等 user push + T3 L3 真实 load 单独授权。

## HH:MM [P3-A T3 L2 收口]

✅ 已完成:
- `scripts/launchd_install.sh` 新增 `TARGET_START_RUNNER="${HOME_BIN}/my-ai-employee-digital-runner"` 部署块
- `my-ai-employee-start` 改:`export MY_AI_EMPLOYEE_PROJECT_ROOT="${PROJECT_ROOT}" && exec "${HOME_BIN}/my-ai-employee-digital-runner" start`
- `ops/start-digital-employee.sh` line 34:`PROJECT_ROOT="${MY_AI_EMPLOYEE_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"` 支持 override
- `tests/scripts/test_launchd_install.py` 新增 F4(runner 部署)· F5(禁 Documents exec)· F6(显式 override)3 契约测试
- `docs/v0.2.72-p3-a-t3-l2-91-fix-2026-07-09.md` 收口文档
- `MODIFICATION-LOG.md` ## 86(下一棒执行)+ ## 87(T3 L2 修复收口 3 段)
- 5 件套 baseline 同步 2904/1/269 → **2907/1/270**(README/CLAUDE/SESSION-STATE/MODIFICATION-LOG/v0.2-launch-plan + quality_snapshot.py)
- `make ci` 9 门全绿 · check-snapshot 双门 OK
- git commit `db3f2e4` 已落本地

🔄 进行中:
- 等 user push 授权(`db3f2e4` ahead 1)
- 等 user T3 L3 单独授权:`launchctl load -w` 数字员工 plist + 观察 err log 无 `#91 Operation not permitted`

📋 待办:
- user push `db3f2e4` 远端
- user 单独授权 T3 L3 真实复验 `launchctl load -w com.myaiemployee.digital-employee.plist`
- P3-B SMTP 单封真发(待 Notes dry-run 复验完成 / 新草稿 + 命名收件人)
- P4 24h dry-run 观察
- P5 v1.0 tag 评估(默认不打)
- T4 v1.0 收口 docs(沿 docs-only)
- 撞坑 #90 持久化方案 D-step 评估(4 候选)
- docs/v0.2.67 §19-21 误归校正 D-step 评估(可选 docs-only)

📂 关键产出:
- `scripts/launchd_install.sh` + `ops/start-digital-employee.sh` + `tests/scripts/test_launchd_install.py` F4-F6 · `docs/v0.2.72-p3-a-t3-l2-91-fix-2026-07-09.md`
- `MODIFICATION-LOG.md` ## 86 + ## 87
- `memory/pitfall-91-fix-launchd-runner-migration.md`
- `memory/checkpoint-2026-07-09-p3-a-t3-l2-91-fix.md`(本文件)

## 修复路径对比

| 路径 | 决策 |
|------|------|
| **A** 移调用点到 `~/bin/` runner(本轮) | ✅ **选中** |
| B 移 sh 本体出项目 | ❌ 破坏 git 历史 |
| C `cat sh \| bash` 绕过 exec | ❌ stdin 复杂 |
| D TCC Allow Execution | ❌ 撞坑 #81 假说已破 |

## T3 L3 真实复验 checklist(user 单独授权后执行)

```bash
# 1. 重生 wrapper(自动部署 digital-runner)
bash scripts/launchd_install.sh install

# 2. 验证 4 wrapper 部署
ls -la ~/bin/my-ai-employee-*
# 期望:4 个 wrapper(start / monthly-report / imap-sync / digital-runner)

# 3. 仅加载数字员工 plist(L3 单 job 授权)
launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.digital-employee.plist

# 4. 观察 err log(撞坑 #91 真实复验)
tail -F ~/Library/Logs/MyAIEmployee/digital-employee.err.log
# 期望:无 "Operation not permitted" · 数字员工进程正常启动

# 5. 验证 launchd list 注册
launchctl list | grep myaiemployee
# 期望:com.myaiemployee.digital-employee PID + state=running

# 6. 若通过 → 撞坑 #91 真实修复完成 + 撞坑 #81 误判打破 + docs/v0.2.67 可标 deprecated
# 7. 若失败 → 立刻 launchctl bootout + 沉淀新撞坑
```

## 红线维持(16 项 + 撞坑 #90/#91)

| 红线 | 状态 |
|------|------|
| 撞坑 #1 凭据安全 | ✅ |
| 撞坑 #18 ENABLE_PATH_4_WRITE UNSET | ✅ |
| 撞坑 #59 outlook/gmail 不配 | ✅ |
| 撞坑 #65 NotesCipherImpl.decrypt fallback | ✅ |
| 撞坑 #71 docs-only 边界 | ✅(本轮含代码修复,但 launchctl load 仍留 L3)|
| 撞坑 #76 outbox status 小写 | ✅ |
| 撞坑 #78 real mode count=1 | ✅ |
| 撞坑 #79 redactor email 后半部 | ✅ |
| 撞坑 #81 数字员工 TCC Python 误判已知 | ✅ **真实根因撞坑 #91,本轮修复** |
| 撞坑 #85 LLM 草稿幻觉 3 层 | ✅ |
| 撞坑 #86 router 空 token 优雅降级 | ✅ |
| 撞坑 #87 snapshot self-referential 校准 | ✅ 5 件套 2907/1/270 |
| 撞坑 #88 spike ↔ src drift | ✅ |
| 撞坑 #89 real-flow-notesync-dedup | ✅ |
| 撞坑 #90 launchd session-bound | ⚠️ 待 D-step 评估持久化方案 |
| 撞坑 #91 Documents exec OS 拦截 | ✅ **本轮路径 A 修复(db3f2e4)** |
| v1.0 tag 不打 | ✅ |
| 不写 shell profile | ✅ |
| 不自动 launchctl load -w | ✅(T3 L3 单独授权)|
| 0 SMTP 真发 | ✅ |
| 0 Notes 生产同步 | ✅ |
| 0 ENABLE_PATH_4_WRITE | ✅ |

## 关联记忆

- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 原坑(误判打破)
- [[pitfall-91-fix-launchd-runner-migration]] — 修复沉淀
- [[pitfall-90-launchd-domain-not-persistent]] — 同次 T3 发现
- [[pitfall-81-tcc-python-framework-runatload]] — 撞坑 #81 误判归因
- [[docs/v0.2.72-p3-a-t3-l2-91-fix-2026-07-09]] — 收口 audit
- [[docs/v0.2.71-p3-a-t3-launchd-audit-2026-07-08]] — T3 L1 audit
- [[checkpoint-2026-07-08-p3-a-t3-cc]] — T3 L1 收口

## 全局快照

| 维度 | 状态 |
|------|------|
| 远端 HEAD | `aa27144`(`v0.2.71` 收口 + Notes dry-run 复验)|
| 本地 HEAD | `db3f2e4`(`fix(p3-a): resolve #91 launchd digital wrapper path`)|
| ahead/behind | **ahead 1** · 待 push |
| 9/9 质量门 | ✅ 全绿 |
| pytest | 2907 passed / 1 skipped |
| MD lint | 270 files / 0 errors |
| mypy | 0 errors / 256 files |
| coverage | 89.12% |
| launchd 实际 | 2/3 active + 1/3 bootout(数字员工)|
| P3-A T0-T2 | ✅ 全收 |
| P3-A T3 L1 | ✅ load 2/3 + 撞坑 #90/#91 |
| P3-A T3 L2 | ✅ 撞坑 #91 wrapper 修复(`db3f2e4`)|
| P3-A T3 L3 | ⏸ **待 user 单独授权 launchctl load -w 复验** |
| P3-A T4 v1.0 docs | ⏸ 等 P3-A 全收 |
| 撞坑数 | 91 → **91**(修复不算新坑)|
| v1.0 完成度 | 88% → **88%**(修复 ≠ 进度) |
| 可无人值守 | 78% → **86%** |
| 项目整体 | 90% → **92%** |