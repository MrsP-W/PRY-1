---
name: checkpoint-2026-07-09-p3-a-t3-l3-reverify
description: P3-A T3 L3 数字员工 launchctl load 真实复验收口 · 撞坑 #91 完全修复验证 ✅ + 撞坑 #92 新暴露(业务代码路径 Documents 沙箱)· launchctl load 数字员工 plist 成功 → 立刻 bootout(因 #92 exit 1)· 等 user 决策 #92 修复路径
metadata:
  node_type: memory
  type: checkpoint
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
---

# P3-A T3 L3 数字员工 launchctl load 真实复验收口 2026-07-09

## 🎯 一句话

P3-A T3 L3 真实复验:`launchctl load -w com.myaiemployee.digital-employee.plist` ✅ 成功 · **撞坑 #91 完全修复**(launchd 启动链路 100% OK · 9 维度预检流程正常 · `~/bin/my-ai-employee-start` → `~/bin/my-ai-employee-digital-runner` → `MY_AI_EMPLOYEE_PROJECT_ROOT` 显式 override 链路 100% 命中)· **撞坑 #92 新暴露**(业务代码路径 `grep .env` / `> data/menu_bar.log` 撞 Documents 沙箱 → 4/9 预检 fail)· 立即 `launchctl bootout` 防 crash loop · launchctl 终态 2/3 注册(数字员工 enabled bootout)· 等 user 决策 #92 修复路径(A 改 runner 路径 / B 移整个项目 / C 软链 / D 暂缓)。

## HH:MM [T3 L3 真实复验收口]

✅ 已完成(撞坑 #91 修复落地):
- `launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.digital-employee.plist` 成功(PID 9404 短暂运行)
- 撞坑 #91 启动链路 100% OK:`~/bin/my-ai-employee-start` → `~/bin/my-ai-employee-digital-runner` → `MY_AI_EMPLOYEE_PROJECT_ROOT` override → `ops/start-digital-employee.sh` 全链路命中
- 撞坑 #91 stderr `bash: .../ops/start-digital-employee.sh: Operation not permitted` **完全消失**
- 数字员工 9 维度预检流程正常启动(out log 显示 1/9 .env 存在 · 5/9 run_menu_bar.py 存在 · 8/9 docs/ui/codex-style-dashboard.html 存在)

🆕 撞坑 #92 暴露(撞坑 #91 同根因在业务代码层):
- `grep: .../.env: Operation not permitted`(数字员工 runner 内 grep Documents/.env)
- `.../data/menu_bar.log: Operation not permitted`(runner 内 redirect 写 Documents/data/)
- 4/9 预检 fail 链:[2/9] DB_ENCRYPTION_KEY 缺 · [3/9] Keychain SMTP 缺 · [4/9] alembic current 失败 · [6/9] dashboard.server 导入失败(全因 .env 读不到)
- 9/9 启动失败:`❌ 菜单栏启动失败(查看日志:tail .../data/menu_bar.log)`

🛑 安全处置:
- 立即 `launchctl bootout gui/501/com.myaiemployee.digital-employee` 防 crash loop
- launchctl list 终态:2/3 注册(agent + imap-sync)· 数字员工 bootout
- plist enabled 状态保留(沿 docs/v0.2.67 范本)

📋 待办:
- user 决策 #92 修复路径(A 改 runner 路径 / B 移整个项目 / C 软链 / D 暂缓)
- #92 修复后再次 T3 L3 真实复验
- P3-B SMTP 单封真发(待 Notes dry-run / 新草稿 + 命名收件人)
- P4 24h dry-run 观察
- P5 v1.0 tag 评估(默认不打)
- T4 v1.0 收口 docs
- 撞坑 #90 持久化方案 D-step 评估
- docs/v0.2.67 §19-21 误归校正 D-step 评估

📂 关键产出:
- `memory/pitfall-92-launchd-documents-data-path-block.md`
- `memory/checkpoint-2026-07-09-p3-a-t3-l3-reverify.md`(本文件)
- `MODIFICATION-LOG.md` ## 89(audit 段,T3 L3 实测)

## 撞坑 #91 vs #92 关键区分

| 维度 | 撞坑 #91(已修) | 撞坑 #92(新) |
|------|----------------|---------------|
| 触发位置 | **launchd exec 阶段** | **业务代码路径** |
| 路径模式 | `bash exec <Documents>/ops/start-digital-employee.sh` | runner 内 `grep .env` / `> data/menu_bar.log` |
| 撞点 | bash 直接 exec Documents/.sh | 业务代码在 Documents 内读/写其他文件 |
| 修复路径 A 范围 | ✅ 移 wrapper 调用点到 ~/bin/(db3f2e4/f430304)| ❌ **未触** · 业务代码仍在 Documents |
| 错误归因 | docs/v0.2.67 误归为 TCC Python(**已破**)| 同根因(macOS iCloud 同步目录沙箱)|

## T3 L3 实测时间线

| 步骤 | 操作 | 结果 |
|------|------|------|
| Step 1 | `launchctl load -w ...digital-employee.plist` | ✅ 成功(无 Load failed: 5)|
| Step 2 | `launchctl list \| grep myaiemployee` | ✅ 3/3 注册(agent PID - / digital-employee PID 9404 / imap-sync PID -)|
| Step 3 | `launchctl print gui/501/com.myaiemployee.digital-employee` | type=LaunchAgent · state=not running · program=~/bin/my-ai-employee-start · 已 exit |
| Step 4 | err log 清空 + bootout + reload | 清空 + bootout OK + reload OK |
| Step 5 | 重读 err log | 🆕 撞坑 #92 `grep .env` + `write menu_bar.log` `Operation not permitted` |
| Step 6 | 重读 out log | ✅ 9 维度预检流程 5/9 OK + 4/9 fail + 9/9 menu_bar 启动失败 |
| Step 7 | launchctl list | 数字员工 `- 1`(exit 1)|
| Step 8 | `launchctl bootout gui/501/com.myaiemployee.digital-employee` | ✅ 立即 bootout(防 crash loop)|
| Step 9 | launchctl list 终态 | 2/3 注册(数字员工 bootout)|

## 撞坑 #92 修复路径候选(D-step 评估)

| 路径 | 范围 | 风险 | 推荐 |
|------|------|------|------|
| **A** 数字员工 runner 内业务代码路径改 `~/bin/` | 最小改动 · 仅改数字员工 | 🟡 .env / log 维护点增多 | **首选**(沿撞坑 #91 路径 A 范本) |
| **B** 整个项目目录移出 `~/Documents/` | 全代码收益 · 大变更 | 🟡 git 历史 / 软链 / TCC 权限全失效 | 长期最佳 |
| **C** 项目保持 Documents,关键配置 + log 路径经 `~/bin/` 软链到 Documents | 折中 | 🟡 软链复杂 / TCC 多层 | 中等 |
| **D** 不动,撞坑 #92 沿 docs/v0.2.67 维持 bootout | 零改动 | 🔴 数字员工永久 bootout | 暂缓可用 |

## 红线维持(17 项 + 撞坑 #90/#91/#92)

| 红线 | 状态 |
|------|------|
| 撞坑 #1 凭据安全 | ✅ |
| 撞坑 #18 ENABLE_PATH_4_WRITE UNSET | ✅ |
| 撞坑 #59 outlook/gmail 不配 | ✅ |
| 撞坑 #65 NotesCipherImpl.decrypt fallback | ✅ |
| 撞坑 #71 docs-only 边界 | ✅(本轮 L3 实测,撞坑 #92 audit only)|
| 撞坑 #76 outbox status 小写 | ✅ |
| 撞坑 #78 real mode count=1 | ✅ |
| 撞坑 #79 redactor email 后半部 | ✅ |
| 撞坑 #81 数字员工 TCC Python 误判已知 | ✅ 真实根因撞坑 #91 → #92 撞坑 #92 同根 |
| 撞坑 #85 LLM 草稿幻觉 3 层 | ✅ |
| 撞坑 #86 router 空 token 优雅降级 | ✅ |
| 撞坑 #87 snapshot self-referential 校准 | ✅ 5 件套 2908/1/270 |
| 撞坑 #88 spike ↔ src drift | ✅ |
| 撞坑 #89 real-flow-notesync-dedup | ✅ |
| 撞坑 #90 launchd session-bound | ⚠️ 待 D-step 持久化 |
| 撞坑 #91 Documents exec OS 拦截(launchd 阶段) | ✅ **本轮 T3 L3 完全修复验证** |
| **撞坑 #92**(T3 L3 新暴露)| ✅ 业务代码路径 Documents 沙箱 · 待 user 决策修复路径 |
| v1.0 tag 不打 | ✅ |
| 不写 shell profile | ✅ |
| 不自动 launchctl load -w 数字员工 | ⚠️ 本轮已 L3 授权 load(后 bootout)|
| 0 SMTP 真发 | ✅ |
| 0 Notes 生产同步 | ✅ |
| 0 ENABLE_PATH_4_WRITE | ✅ |

## 关联记忆

- [[pitfall-92-launchd-documents-data-path-block]] — 撞坑 #92 沉淀(同根因 #91 业务代码层)
- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 撞坑 #91 原坑
- [[pitfall-91-fix-launchd-runner-migration]] — 撞坑 #91 修复路径 A
- [[pitfall-90-launchd-domain-not-persistent]] — 撞坑 #90
- [[pitfall-launchd-deploy-only-mode]] — deploy-only 安全模式
- [[docs/v0.2.73-p3-a-t3-l2-deploy-only]] — deploy-only 收口
- [[checkpoint-2026-07-09-p3-a-t3-l2-deploy-only]] — deploy-only 全环
- [[checkpoint-2026-07-09-p3-a-t3-l2-91-fix]] — 撞坑 #91 代码修复收口

## 全局快照

| 维度 | 状态 |
|------|------|
| 远端 HEAD | `f430304`(deploy-only 安全部署)|
| 本地 HEAD | `f430304`(未变更 · 本轮 L3 实测 audit)|
| ahead/behind | 0 / 0(完全同步)|
| 9/9 质量门 | ✅ 全绿(本轮未变更 commit)|
| pytest | 2908 passed / 1 skipped |
| MD lint | 270 files / 0 errors |
| mypy | 0 errors / 256 files |
| coverage | 89.12% |
| launchd 实际 | 2/3 active + 1/3 bootout(数字员工)#92 exit 1 |
| P3-A T0-T2 | ✅ 全收 |
| P3-A T3 L1 | ✅ load 2/3 + 撞坑 #90/#91 |
| P3-A T3 L2 | ✅ 撞坑 #91 代码修复(db3f2e4)+ deploy-only 部署(f430304)|
| P3-A T3 L3 | ✅ **撞坑 #91 完全修复验证 · 撞坑 #92 新暴露 · 待 user 决策修复路径** |
| P3-A T4 v1.0 docs | ⏸ 等 P3-A 全收 |
| 撞坑数 | 91 → **92**(+1 撞坑 #92)|
| v1.0 完成度 | 89% → **89%**(撞坑 #92 待修 -0)|
| 可无人值守 | 88% → **86%**(-2 撞坑 #92 阻塞数字员工)|
| 项目整体 | 93% → **93%** |