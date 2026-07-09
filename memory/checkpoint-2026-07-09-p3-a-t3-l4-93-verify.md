# T3 L4 撞坑 #93 实战验证 + #94 NEW 暴露 · checkpoint 2026-07-09

> **状态**:撞坑 #93 ✅ 完全验证实战通过(uv PATH / APP_SUPPORT / 9/9 预检)/撞坑 #94 ⚠️ 新暴露(menu_bar SQLAlchemy pool RuntimeError)/1h 观察 ⏸️ 等 #94 决策
> **HEAD = `e74be55`** · ahead 0 · 工作区 dirty(待 收口文档 commit)
> **位置**:T3 L4 launchctl 真实复验完成后,user 授权 1h/24h 观察前的状态归档

---

## HH:MM 20:27-20:30 [T3 L4 撞坑 #93 实战验证]

✅ 已完成：4/4 步
🔄 进行中：T3 L4 收口 docs/memory/MOD-LOG 写
📋 待办：等 user 决策 #94 修复路径(A docs-only / B/C 代码改动 / D 暂缓)

### Phase 1 · 前置核验(20:25-20:26,5 min)
- HEAD e74be55 = `style(launchd): format #93 test guard` · `## main...origin/main` ahead 0
- `make check-snapshot` → 双门 OK(2917/1/282 md)
- wrapper+plist mtime = 20:17:43 = 今日 deploy-only 刷新 + 含 #93 UV_BIN 修复
- runner UV_BIN 6 处使用(line 59 检测 + 195/211/258/264/291/297 调用)
- launchctl list = 3/3 active(数字员工 exit 1 = 16:35 旧 wrapper bootout 残留)
- ⚠️ 关键发现:数字员工在 launchctl 注册但 **无进程**(`pgrep` 空)· exit 1 是 launchd 数据库表持久化记录

### Phase 2 · 陈旧清理 + 真实 load -w(20:27,3 min)
- `launchctl bootout gui/$UID/com.myaiemployee.digital-employee` → 3/3 → 2/3 注册
- `cp err.log /tmp/digital-employee.err.log.bak` + `: > err.log` 清干
- 备份旧 log 到 `/tmp/digital-employee.{err,out}.log.bak`
- `launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.digital-employee.plist` → load OK + RunAtLoad 触发

### Phase 3 · 10 秒后验证 → 撞坑 #93 实战通过(20:28)
- launchctl list → 3/3 注册 ✅
- err.log(NEW)→ 仅 `❌ 菜单栏启动失败(查看日志:...)` · **无** `Operation not permitted` 无 `.env: Operation not permitted` 无 `Documents/data/...`
- out.log(NEW)→ 9/9 预检全过 9/9 ✅(对比 16:35 旧 wrapper 5/9 OK + 4⚠️)
  - `[1/9] .env 存在 (/Users/wei/Library/Application Support/MyAIEmployee/.env)` ✅
  - `[2/9] DB_ENCRYPTION_KEY 64 hex OK` ✅
  - `[3/9] Keychain QQ SMTP 授权码 present` ✅
  - `[4/9] alembic current OK` ✅ ← 比旧 wrapper warn 提升
  - `[5/9] scripts/run_menu_bar.py 存在` ✅
  - `[6/9] dashboard.server 模块 OK` ✅ ← 比旧 wrapper warn 提升
  - `[7/9] ⌥⌘N TCC 检查:用户须先授权 Python.framework 3.12` ⚠️(用户首次启动手动授权)
  - `[8/9] docs/ui/codex-style-dashboard.html 存在` ✅
  - `[9/9] data/ 目录存在(/Users/wei/Library/Application Support/MyAIEmployee/data)` ✅
  - **预检全过 ✅**
- menu_bar.log → 菜单栏进程启动后 ~5 秒在 SQLAlchemy pool 处 RuntimeError(exit 1)

### Phase 4 · 撞坑 #94 新暴露(20:28-20:29,5 min 诊断)
- menu_bar 启动后 SQLAlchemy pool creator → `db.connection` → RuntimeError
- 栈:`sqlcipher_compat.py:63 creator() → db.py:297 RuntimeError`
- 数字员工 launcher 检测菜单栏失败 → ❌ → exit 1
- KeepAlive=false → 不重启循环 · launchctl 表持久化 exit 1
- bootout 已执行 → 清理 launchd 残留 exit 1
- **未自动 load** · 维持 bootout 状态

### 关键产出(本 checkpoint)
- memory/pitfall-94-launchd-menubar-db-context-manager.md
- docs/v0.2.76-p3-a-t3-l4-93-verify-2026-07-09.md(下一步写)
- MODIFICATION-LOG ## 92(下一步写)
- check-snapshot 维持 OK(无代码改动)

### 红线维持(17 项 + #94)
- 撞坑 #1 凭据 · ✅
- 撞坑 #18 ENABLE_PATH_4_WRITE UNSET · ✅
- 撞坑 #59 outlook/gmail · ✅
- 撞坑 #65 Notes · ✅
- 撞坑 #71 docs-only · ✅(本次仅 docs/memory,不写代码)
- 撞坑 #85 LLM 草稿幻觉 · ✅
- 撞坑 #86 router · ✅
- 撞坑 #87 snapshot · ✅
- 撞坑 #88 spike · ✅
- 撞坑 #89 notesync · ✅
- 撞坑 #90 launchd session-bound · ⚠️ 持久化待 D-step
- 撞坑 #91 Documents exec · ✅ T3 L4 完全验证
- 撞坑 #92 Documents 沙箱(代码路径)· ✅ 实战验证
- 撞坑 #93 launchd uv PATH · ✅ **本次真实 RunAtLoad 完全验证**
- 撞坑 #94 menu_bar DB context · ⚠️ **NEW 暴露** · 等 user 决策
- v1.0 tag · ❌ 不打(等 #94 + 1h 观察)
- SMTP/Notes 真发 / Path4 实写 · ✅ 默认未启用

### 完成度(沿 7/8 评估,撞坑 #94 暴露后重整)
- 项目整体 ~94%(不变)
- 可无人值守生产 ~85%(↓2pp · menu_bar 不可达)
- v1.0 发布就绪 ~87%(↓2pp)
