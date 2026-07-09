---
name: pitfall-launchd-deploy-only-mode
description: launchd install 加 deploy-only/no-load 安全部署模式 · 只刷新 ~/bin wrapper + ~/Library/LaunchAgents/*.plist + ~/Library/Logs/MyAIEmployee/,不执行 `launchctl load -w` · 适合"修代码但保持 launchd 不动"或"已运行 plist 不能 bootout 重 load"的场景 · 撞坑 #91 修复后的安全 fallback
metadata:
  node_type: memory
  type: pitfall-fix
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
---

# launchd deploy-only 安全部署模式 · 撞坑 #91 修复后的安全 fallback

## 现象

撞坑 #91 修复后,数字员工 wrapper 已改调 `~/bin/my-ai-employee-digital-runner`(非 iCloud Documents/),代码层修复完成,但实际 `launchctl load -w` 仍待 user 单独授权。

**问题场景**:
1. 撞坑 #91 修复代码已 commit,但业务代码改动日边界不想触发 launchctl 实际重启(撞坑 #71 docs-only 边界)
2. 用户在 reboot 后(撞坑 #90 launchd session-bound)需要重新刷 wrapper 但不想 load
3. D-step 实施阶段(代码 commit 后 → push 前)需要 verify wrapper 文件存在但不能影响 launchd 状态
4. 数字员工 plist 仍 bootout 时,改 install 脚本需验证 wrapper 部署正确,但不能用 `launchctl load -w` 触发 `#91` 重演

## 修复(2026-07-09 · P3-A T3 L2 · `f430304`)

**新增模式**:`scripts/launchd_install.sh deploy-only` / `scripts/launchd_install.sh no-load`

**行为差异**(vs 完整 `install`):

| 步骤 | `install` | `deploy-only` / `no-load` |
|------|-----------|---------------------------|
| 部署 `~/bin/my-ai-employee-{start,monthly-report,imap-sync,digital-runner}` | ✅ | ✅ |
| 部署 `~/Library/LaunchAgents/com.myaiemployee.*.plist` | ✅ | ✅ |
| 创建 `~/Library/Logs/MyAIEmployee/` | ✅ | ✅ |
| 执行 `launchctl load -w` | ✅ | ❌(故意跳过)|
| 退出码 | 沿 5 退出码范本 | 沿 5 退出码范本(成功=0)|

**安全边界**:
- 不影响现有 launchd 注册(agent + imap-sync 2/3 仍注册)
- 不触发 `Operation not permitted`(无 bash exec .sh)
- 不修改 plist 已 enabled 状态
- 不 bootout 任何 plist
- 不动 outbox / Notes / SMTP / Path4

## Why

**为什么需要 deploy-only 模式**:

| 需求 | install | deploy-only |
|------|---------|-------------|
| 完整 P2 install(3 wrapper + 3 plist + 3 load)| ✅ | ❌ |
| 仅刷 wrapper/plist 不 load | ❌(会 load) | ✅ |
| 撞坑 #90 reboot 后 refresh wrapper 不 load | ❌ | ✅ |
| 撞坑 #91 修复后 refresh wrapper 不 load 复验 | ❌ | ✅ |
| docs-only 阶段(沿撞坑 #71) | ❌ | ✅ |
| 业务代码改动日(撞坑 #71 破例) | ✅ | ❌ |

## How to apply

1. **撞坑 #91 修复路径下的推荐命令**:
   ```bash
   # Step 1: 部署 wrapper(不 load)
   bash scripts/launchd_install.sh deploy-only

   # Step 2: 验证 4 wrapper 文件存在
   ls -la ~/bin/my-ai-employee-*

   # Step 3: 验证 plist 文件存在
   ls -la ~/Library/LaunchAgents/com.myaiemployee.*.plist

   # Step 4: 观察 launchd 状态未变(可选)
   launchctl list | grep myaiemployee
   # 期望:仍只有 agent + imap-sync,数字员工未注册

   # Step 5: 单独授权 T3 L3 时再 `launchctl load -w` 数字员工 plist
   launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.digital-employee.plist
   ```

2. **沿 docs-only 边界的 D-step 实施**:
   - 撞坑 #71 docs-only 边界下,**禁止** `install`(会触发 load)
   - 用 `deploy-only` 部署 wrapper 文件 → 留在磁盘待 push 后用户单独 load
   - 不影响 `make ci` 9 门全绿(测试不依赖 launchd 状态)

3. **撞坑 #90 reboot 后 refresh**:
   - reboot 后 `agent` + `imap-sync` 注册丢失(撞坑 #90 session-bound)
   - 用 `deploy-only` 刷 wrapper → **不**自动 load
   - 单独授权 `launchctl load -w` 恢复(避免撞坑 #91 重演)

4. **撞坑 #91 真实复验 checklist**:
   ```bash
   bash scripts/launchd_install.sh deploy-only   # 刷 wrapper(不 load)
   launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.digital-employee.plist
   tail -F ~/Library/Logs/MyAIEmployee/digital-employee.err.log
   # 期望:无 "Operation not permitted" · 数字员工进程正常启动
   ```

## 实战验证(2026-07-09)

| 维度 | 实测 |
|------|------|
| commit | `f430304 fix(p3-a): add launchd deploy-only wrapper refresh` |
| 文件 | `scripts/launchd_install.sh` + `tests/scripts/test_launchd_install.py` |
| 部署结果 | `~/bin/my-ai-employee-{start,digital-runner}` 已刷新 |
| launchctl list | 仍只有 agent + imap-sync(未注册数字员工)|
| 红线 | 0 SMTP · 0 Notes · 0 Path4 · 0 v1.0 tag |
| 9 门 | 全绿(2908 passed / 1 skipped / 89.12% / 256 mypy / 270 MD)|
| ahead/behind | ahead 1 → 已 push → 远端 HEAD = `f430304` |

## 关联记忆

- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 撞坑 #91 原始坑
- [[pitfall-91-fix-launchd-runner-migration]] — 撞坑 #91 修复代码层(路径 A)
- [[pitfall-90-launchd-domain-not-persistent]] — 撞坑 #90 launchd session-bound
- [[docs/v0.2.73-p3-a-t3-l2-deploy-only]] — 本次 deploy-only 收口文档
- [[checkpoint-2026-07-09-p3-a-t3-l2-deploy-only]] — 本次全环收口
- [[checkpoint-2026-07-09-p3-a-t3-l2-91-fix]] — T3 L2 代码修复收口(db3f2e4)