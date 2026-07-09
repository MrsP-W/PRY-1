---
name: checkpoint-2026-07-09-p3-a-t3-l2-deploy-only
description: P3-A T3 L2 deploy-only 安全部署收口 · commit f430304 · launchd install 新增 deploy-only/no-load 模式 · 刷新 ~/bin wrapper + plist + log 不执行 launchctl load -w · 9 门全绿 2908/1/270/256/89.12% · 已 push 远端 · 数字员工仍未 load · T3 L3 单独授权
metadata:
  node_type: memory
  type: checkpoint
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
---

# P3-A T3 L2 deploy-only 安全部署收口 2026-07-09

## 🎯 一句话

P3-A T3 L2 撞坑 #91 修复后续:`scripts/launchd_install.sh` 新增 `deploy-only` / `no-load` 安全部署模式 · commit `f430304` · 实际刷新 `~/bin/my-ai-employee-{start,digital-runner}` + 3 plist + log dir · **不执行** `launchctl load -w` · 数字员工仍未 load(launchctl 仅 agent + imap-sync)· 9 门全绿 2908/1/270/256/89.12% · 本地 ahead → push 完成 · 远端 HEAD = `f430304` · T3 L3(真实 load 复验 #91)单独授权待 user。

## HH:MM [T3 L2 deploy-only 收口]

✅ 已完成:
- `scripts/launchd_install.sh` 新增 `deploy-only` / `no-load` 模式(同义别名)
- `tests/scripts/test_launchd_install.py` 新增 deploy-only 契约测试(预期 wrapper 部署 + 无 launchctl load 调用)
- 实际刷新本机 `~/bin/my-ai-employee-start` + `~/bin/my-ai-employee-digital-runner`
- 数字员工 plist 未触发 load:`launchctl list | grep myaiemployee` 仅 2 行(agent + imap-sync)
- 9 门全绿:make test 2908 passed / 1 skipped · coverage 89.12% · check-snapshot 双门 OK · lint 270 files · mypy 0/256 files · ruff 全绿
- 5 件套 baseline sync:2907/1/270 → **2908/1/270**(README/CLAUDE/SESSION-STATE/MODIFICATION-LOG/v0.2-launch-plan + quality_snapshot.py)
- `MODIFICATION-LOG.md` ## 88(deploy-only 收口 3 段)· 状态基线行(line 116)同步到 2908/1/270
- `docs/v0.2.73-p3-a-t3-l2-deploy-only-2026-07-09.md` 收口文档
- git commit `f430304` 落本地 → **已 push 远端** · 远端 HEAD = `f430304`

🔄 进行中:
- 等 user 单独授权 T3 L3(`launchctl load -w` 数字员工 + tail err log 复验 #91)

📋 待办:
- user 授权 T3 L3:`bash scripts/launchd_install.sh deploy-only`(已 done)+ `launchctl load -w com.myaiemployee.digital-employee.plist` + 观察无 `#91 Operation not permitted`
- P3-B SMTP 单封真发(待 Notes dry-run 复验完成 / 新草稿 + 命名收件人)
- P4 24h dry-run 观察
- P5 v1.0 tag 评估(默认不打)
- T4 v1.0 收口 docs(沿 docs-only)
- 撞坑 #90 持久化方案 D-step 评估(4 候选)
- docs/v0.2.67 §19-21 误归校正 D-step 评估(可选 docs-only)

📂 关键产出:
- `scripts/launchd_install.sh` deploy-only 模式 · `tests/scripts/test_launchd_install.py` 契约测试 · `docs/v0.2.73-p3-a-t3-l2-deploy-only-2026-07-09.md`
- `MODIFICATION-LOG.md` ## 88
- `memory/pitfall-launchd-deploy-only-mode.md`
- `memory/checkpoint-2026-07-09-p3-a-t3-l2-deploy-only.md`(本文件)

## 部署模式决策表

| 模式 | 部署 wrapper/plist/log | launchctl load | docs-only 兼容 | 撞坑 #90 reboot 后 | 撞坑 #91 修复后 refresh |
|------|----------------------|----------------|---------------|-------------------|---------------------|
| `install` | ✅ | ✅(全 load)| ❌(破边界) | ✅(完整恢复)| ✅(load 复验)|
| **`deploy-only` / `no-load`** | ✅ | ❌ | ✅ | ✅(待授权 load) | ✅(**本轮选中**)|

## T3 L3 真实复验 checklist(user 授权后执行)

```bash
# Step 1: 已 done(deploy-only 刷 wrapper)
ls -la ~/bin/my-ai-employee-*

# Step 2: 仅加载数字员工 plist
launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.digital-employee.plist

# Step 3: 观察 err log(撞坑 #91 真实复验)
tail -F ~/Library/Logs/MyAIEmployee/digital-employee.err.log
# 期望:无 "Operation not permitted" · 数字员工进程正常启动

# Step 4: 验证 launchd list 注册
launchctl list | grep myaiemployee
# 期望:com.myaiemployee.digital-employee PID + state=running

# Step 5: 验证通过 → 撞坑 #91 真实修复完成 + 撞坑 #81 误判彻底打破
# 验证失败 → 立刻 launchctl bootout + 沉淀新撞坑
```

## 红线维持(16 项 + 撞坑 #90/#91)

| 红线 | 状态 |
|------|------|
| 撞坑 #1 凭据安全 | ✅ |
| 撞坑 #18 ENABLE_PATH_4_WRITE UNSET | ✅ |
| 撞坑 #59 outlook/gmail 不配 | ✅ |
| 撞坑 #65 NotesCipherImpl.decrypt fallback | ✅ |
| 撞坑 #71 docs-only 边界 | ✅(deploy-only 模式严判)|
| 撞坑 #76 outbox status 小写 | ✅ |
| 撞坑 #78 real mode count=1 | ✅ |
| 撞坑 #79 redactor email 后半部 | ✅ |
| 撞坑 #81 数字员工 TCC Python 误判已知 | ✅ 真实根因撞坑 #91 |
| 撞坑 #85 LLM 草稿幻觉 3 层 | ✅ |
| 撞坑 #86 router 空 token 优雅降级 | ✅ |
| 撞坑 #87 snapshot self-referential 校准 | ✅ 5 件套 2908/1/270 |
| 撞坑 #88 spike ↔ src drift | ✅ |
| 撞坑 #89 real-flow-notesync-dedup | ✅ |
| 撞坑 #90 launchd session-bound | ⚠️ 待 D-step 持久化 |
| 撞坑 #91 Documents exec OS 拦截 | ✅ 代码修复+runtime 安全部署 |
| v1.0 tag 不打 | ✅ |
| 不写 shell profile | ✅ |
| 不自动 launchctl load -w(数字员工)| ✅(T3 L3 单独授权)|
| 0 SMTP 真发 | ✅ |
| 0 Notes 生产同步 | ✅ |
| 0 ENABLE_PATH_4_WRITE | ✅ |

## 关联记忆

- [[pitfall-launchd-deploy-only-mode]] — deploy-only 沉淀
- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 撞坑 #91 原坑
- [[pitfall-91-fix-launchd-runner-migration]] — 撞坑 #91 代码修复
- [[pitfall-90-launchd-domain-not-persistent]] — 撞坑 #90 session-bound
- [[docs/v0.2.73-p3-a-t3-l2-deploy-only]] — 收口 audit
- [[docs/v0.2.72-p3-a-t3-l2-91-fix-2026-07-09]] — T3 L2 代码修复收口
- [[checkpoint-2026-07-09-p3-a-t3-l2-91-fix]] — T3 L2 代码修复收口 checkpoint

## 全局快照

| 维度 | 状态 |
|------|------|
| 远端 HEAD | `f430304`(deploy-only 安全部署)|
| 本地 HEAD | `f430304` |
| ahead/behind | 0 / 0(完全同步)|
| 9/9 质量门 | ✅ 全绿 |
| pytest | 2908 passed / 1 skipped |
| MD lint | 270 files / 0 errors |
| mypy | 0 errors / 256 files |
| coverage | 89.12% |
| launchd 实际 | 2/3 active + 1/3 bootout(数字员工) |
| P3-A T0-T2 | ✅ 全收 |
| P3-A T3 L1 | ✅ load 2/3 + 撞坑 #90/#91 |
| P3-A T3 L2 | ✅ 撞坑 #91 代码修复(`db3f2e4`)+ deploy-only 部署(`f430304`) |
| P3-A T3 L3 | ⏸ **待 user 单独授权 launchctl load -w 复验** |
| P3-A T4 v1.0 docs | ⏸ 等 P3-A 全收 |
| 撞坑数 | 91 → **91**(修复不算新坑)|
| v1.0 完成度 | 88% → **89%**(deploy-only = +1%)|
| 可无人值守 | 86% → **88%** |
| 项目整体 | 92% → **93%** |