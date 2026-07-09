---
name: pitfall-92-launchd-documents-data-path-block
description: 数字员工 wrapper 启动后,业务代码内 `grep .env` / 写 `data/menu_bar.log` 撞 macOS `~/Documents/`(iCloud 同步目录)沙箱拦截 → 9 维度预检 .env 读不到 → [2/9] DB_ENCRYPTION_KEY / [3/9] Keychain / [4/9] alembic / [6/9] dashboard.server fail 链 · 撞坑 #91 修复后新撞坑,本质是 #91 同根因在业务代码层的延伸
metadata:
  node_type: memory
  type: pitfall
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
  relatedPitfalls: ["pitfall-91-launchd-documents-shell-operation-not-permitted", "pitfall-91-fix-launchd-runner-migration"]
---

# 撞坑 #92 数字员工 wrapper 启动后业务代码路径撞 ~/Documents/ iCloud 沙箱

## 现象

撞坑 #91 修复后(`db3f2e4` + `f430304` 已 push),T3 L3 真实复验(`launchctl load -w com.myaiemployee.digital-employee.plist`)数字员工 wrapper 启动链路成功,但业务代码内继续撞相同根因:

```text
grep: /Users/wei/Documents/DesktopOrganizer/我的AI员工/.env: Operation not permitted
/Users/wei/bin/my-ai-employee-digital-runner: line 252: /Users/wei/Documents/DesktopOrganizer/我的AI员工/data/menu_bar.log: Operation not permitted
```

**9 维度预检 fail 链**(因 `.env` 读不到):

| 项 | 状态 | 根因 |
|----|------|------|
| [1/9] .env 存在 | ✅ | 文件存在(权限 644) |
| [2/9] DB_ENCRYPTION_KEY 缺失或格式错 | ⚠️ | `.env` grep 失败 → 解析不到 key |
| [3/9] Keychain QQ SMTP 授权码 missing | ⚠️ | `.env` 读不到 `IMAP_USER` → Keychain service name 错 |
| [4/9] alembic current 失败 | ⚠️ | 配置缺 → 走错路径 |
| [5/9] scripts/run_menu_bar.py 存在 | ✅ | |
| [6/9] dashboard.server 导入失败 | ⚠️ | 配置缺 |
| [7/9] ⌥⌘N TCC 检查 | ⚠️ | 撞坑 #81 已修,首次启动需手动 |
| [8/9] docs/ui/codex-style-dashboard.html 存在 | ✅ | |
| [9/9] 启动数字员工 | ❌ | 菜单栏启动失败(menu_bar.log 写失败)|

**关键**:wrapper 启动链路(launchd → ~/bin/my-ai-employee-start → ~/bin/my-ai-employee-digital-runner)已 100% OK,撞坑 #91 已彻底修。

**但**:runner 内部调 `ops/start-digital-employee.sh` 后,业务逻辑在 `~/Documents/...` 路径下继续撞相同沙箱根因 → **新撞坑 #92**。

## 触发条件

- 数字员工 wrapper 启动(`launchctl load -w com.myaiemployee.digital-employee.plist`)
- 数字员工业务代码路径在 `~/Documents/DesktopOrganizer/我的AI员工/` 下
- runner 内部执行:
  - `grep` `.env`(读 Documents/.env)→ macOS Documents 沙箱拦截
  - `nohup ... > data/menu_bar.log`(写 Documents/data/)→ macOS Documents 沙箱拦截

## 决策范本(撞坑 #91 vs #92 关键区分)

| 维度 | 撞坑 #91(已修) | 撞坑 #92(新) |
|------|----------------|---------------|
| 触发位置 | **launchd exec 阶段** | **业务代码路径** |
| 路径模式 | `bash exec <Documents>/ops/start-digital-employee.sh` | runner 内 `grep .env` / `> data/menu_bar.log` |
| 撞点 | bash 直接 exec Documents/.sh | 业务代码在 Documents 内读/写其他文件 |
| 修复路径 A 范围 | ✅ 移 wrapper 调用点到 ~/bin/(db3f2e4/f430304)| ❌ **未触** · 业务代码仍在 Documents |
| 错误归因 | docs/v0.2.67 误归为 TCC Python(**已破**)| 同根因(macOS iCloud 同步目录沙箱)|

## 实战(2026-07-09 T3 L3)

| 维度 | 实测 |
|------|------|
| launchctl load 数字员工 plist | ✅ 成功(PID 9404 短暂运行后 exit 1)|
| 撞坑 #91 启动链路 bash exec error | ✅ **完全消失** |
| 撞坑 #92 grep .env | ❌ `Operation not permitted` |
| 撞坑 #92 write data/menu_bar.log | ❌ `Operation not permitted` |
| 9 维度预检 | 5/9 OK + 4/9 fail(根因 .env 读不到)|
| 安全处置 | `launchctl bootout gui/501/com.myaiemployee.digital-employee` 立即执行 |
| launchctl list 终态 | 2/3 注册(agent + imap-sync)· 数字员工 bootout |
| 9 质量门 | 不影响(2908/1/270/256/89.12%) |
| 红线 | 0 SMTP · 0 Notes · 0 Path4 · 0 v1.0 tag |

## Why

**为什么 #91 修复后还撞 #92**:

1. **撞坑 #91 修复范围**:`scripts/launchd_install.sh` 移 wrapper 部署点 → launchd 直接 exec `~/bin/my-ai-employee-start`(非 Documents/.sh)
2. **未触及**:`ops/start-digital-employee.sh` 内部业务逻辑仍依赖 Documents 路径(读 .env / 写 log)
3. **macOS Documents 沙箱一致性**:任何 `~/Documents/` 路径下的 `bash exec` / `grep` / `>` redirect 都被 iCloud 沙箱拦截

**撞坑 #91 → #92 是同一根因在不同阶段的表现**:
- #91:launchd 直接 exec Documents/.sh(bash 阶段)
- #92:业务代码在 Documents 读/写(运行时阶段)

## How to apply

1. **撞坑 #92 修复路径候选**(留给 D-step 评估):

   | 路径 | 范围 | 风险 | 推荐 |
   |------|------|------|------|
   | **A** 数字员工 runner 内业务代码路径改 `~/bin/` | 最小改动 · 仅改数字员工 | 🟡 .env / log 维护点增多 | **首选**(沿撞坑 #91 路径 A 范本) |
   | **B** 整个项目目录移出 `~/Documents/` | 全代码收益 · 大变更 | 🟡 git 历史 / 软链 / TCC 权限全失效 | 长期最佳 |
   | **C** 项目保持 Documents,关键配置 + log 路径经 `~/bin/` 软链到 Documents | 折中 | 🟡 软链复杂 / TCC 多层 | 中等 |
   | **D** 不动,撞坑 #92 沿 docs/v0.2.67 维持 bootout | 零改动 | 🔴 数字员工永久 bootout | 暂缓可用 |

2. **临时缓解**(撞坑 #92 修前):
   - 数字员工 plist 沿 docs/v0.2.67 bootout 维持
   - 用户手动 `bash scripts/run_menu_bar.py` 启动菜单栏(绕开 launchd 启动链路)
   - 撞坑 #91 修复后已无"必须自动启动"红线压力(可选 P4 24h 观察)

3. **撞坑 #92 复验 checklist**(D-step 实施后):
   ```bash
   launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.digital-employee.plist
   sleep 5
   tail ~/Library/Logs/MyAIEmployee/digital-employee.err.log
   # 期望:无 "Operation not permitted"(任何路径都不应撞)
   tail ~/Library/Logs/MyAIEmployee/digital-employee.out.log
   # 期望:9/9 预检 OK + 菜单栏启动成功(PID 可见)
   launchctl list | grep myaiemployee
   # 期望:3/3 注册 · 数字员工 state=不是 -1
   ```

4. **docs/v0.2.67 §19-21 校正**:
   - 不动历史(撞坑 #50 严判)
   - audit trail 显式标记:撞坑 #81 真实根因是撞坑 #91,撞坑 #91 修复后撞坑 #92 暴露业务代码层同根因
   - 下次 D-step 校正 docs/v0.2.67 + v0.2.71(可选 docs-only)

## 关联记忆

- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 撞坑 #91 原坑(launchd 阶段)
- [[pitfall-91-fix-launchd-runner-migration]] — 撞坑 #91 修复路径 A(wrapper 移 ~/bin/)
- [[pitfall-90-launchd-domain-not-persistent]] — 撞坑 #90 session-bound
- [[pitfall-launchd-deploy-only-mode]] — deploy-only 安全部署模式
- [[docs/v0.2.73-p3-a-t3-l2-deploy-only]] — deploy-only 收口
- [[checkpoint-2026-07-09-p3-a-t3-l3-reverify]] — T3 L3 真实复验收口(撞坑 #92 暴露)