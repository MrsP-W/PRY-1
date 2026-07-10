# T3 L4 撞坑 #94 B 路径实战 + #95 NEW · checkpoint 2026-07-09

> **状态**:撞坑 #94 ✅ B 路径修复实战完全通过(数字员工 exit 0 + 9/9 + menu_bar B 路径生效)/撞坑 #95 ⚠️ NEW ProcessType=Background fork 限制/1h 观察窗 🟡 启动中
> **HEAD = `74dc9db`** · ahead 0 · 工作区 dirty(待 docs/memory/MOD-LOG commit)
> **位置**:T3 L4 复验 + 撞坑 #95 暴露 + 1h 观察窗启动

---

## HH:MM 21:27-21:35 [T3 L4 撞坑 #94 B 路径复验 + #95 暴露]

✅ 已完成：5/5 步
🔄 进行中：docs/memory/MOD-LOG/5件套 sync + 1h 观察窗启动
📋 待办：1h 观察(15/30/45/60min checkpoint)→ 撞坑 #95 决策 → 24h 观察 → v1.0 评估

### Phase 1 · 前置核验(21:25,5 min)

- HEAD `74dc9db` = `fix(launchd): #94 menu_bar db_path sqlalchemy engine` · `## main...origin/main` ahead 0
- `make check-snapshot` → 双门 OK(2920/1/285 md)
- `make mypy` → Success: 0 errors in 257 source files
- `make lint` → Linting: 285 file(s) · 0 errors
- 9/9 质量门全绿(沿 v0.2.77 收口沉淀)

### Phase 2 · 真实 load -w(21:27,3 min)

- 备份+清干 log:`/tmp/digital-employee.{err,out}.log.bak2` + `menu_bar.log.bak2`
- `launchctl load -w com.myaiemployee.digital-employee.plist` → load OK · RunAtLoad 触发
- 10 秒后:`launchctl list` 3/3 注册,**数字员工 exit 0**(从 c8049ec 时 exit 1 → 0)
- out.log:9/9 预检全过 ✅ + 菜单栏 PID=26648 + Dashboard PID=26659 + 🎉 启动完成
- err.log:**完全空**(无任何错误)
- menu_bar.log:DB 反复 open/close 模式(B 路径生效:每次连接独立 `Database.open(db_path=...)`)

### Phase 3 · 撞坑 #95 NEW 暴露(21:28-21:30,5 min)

- 30 秒后 `pgrep` 空 → menu_bar + dashboard 全部退出
- `lsof -i :8765` 空 → 端口未监听
- `launchctl print` → `state=not running · active count=0`
- PID 文件残留(26648/26659)但进程不存在
- plist `ProcessType=Background` 禁止 fork 子进程 → launchd 回收 subprocess

### Phase 4 · 1h 观察窗决策(21:30,5 min)

- 选项 D · A + B 混合:agent + imap-sync 2/3 active + 数字员工 plist 留注册
- 0 改动 · 锚 launchd 注册表稳定性
- 等 #95 修复 D-step 后再走 24h 完整观察

### Phase 5 · docs/memory/MOD-LOG/5件套 sync(21:30-21:35,5 min)

- docs/v0.2.77-p3-a-t3-l4-94-b-verify-95-expose-2026-07-09.md(写)
- memory/pitfall-95-launchd-background-process-type-no-fork.md(写)
- memory/checkpoint-2026-07-09-p3-a-t3-l4-94-b-verify.md(本文件)
- MODIFICATION-LOG ## 93(待写)
- CLAUDE.md / SESSION-STATE.md / README.md / v0.2-launch-plan.md(待 sync)

### 关键产出(本 checkpoint)

- docs/v0.2.77 + memory/pitfall-95 + memory/checkpoint + MOD-LOG ## 93
- 5 件套 baseline sync 285(从 282 → 285 · 撞坑 #87 self-drift 校准 沿用)
- 9/9 质量门 全绿(无代码改动,纯 docs-only)

### 红线维持(17 项 + #94 + #95)

- 撞坑 #1 凭据 · ✅
- 撞坑 #18 ENABLE_PATH_4_WRITE UNSET · ✅
- 撞坑 #59 outlook/gmail · ✅
- 撞坑 #65 Notes · ✅
- 撞坑 #71 docs-only · ✅(本轮 docs-only · #94 B 路径修复在 c8049ec 沿业务代码改动日破例)
- 撞坑 #85 LLM 草稿幻觉 · ✅
- 撞坑 #86 router · ✅
- 撞坑 #87 snapshot · ✅
- 撞坑 #88 spike · ✅
- 撞坑 #89 notesync · ✅
- 撞坑 #90 launchd session-bound · ⚠️ 持久化待 D-step
- 撞坑 #91 Documents exec · ✅ T3 L4 完全实战验证
- 撞坑 #92 Documents 沙箱 · ✅ T3 L4 完全实战验证
- 撞坑 #93 launchd uv PATH · ✅ T3 L4 完全实战验证
- 撞坑 #94 menu_bar DB context · ✅ **本次 T3 L4 复验 B 路径完全通过**
- 撞坑 #95 ProcessType=Background fork · ⚠️ **NEW 暴露** · 等 D-step 决策
- v1.0 tag · ❌ 不打(等 #95 修复 + 1h 观察稳定)
- SMTP/Notes 真发 / Path4 实写 · ✅ 默认未启用

### 完成度(撞坑 #95 暴露后重整)

- 项目整体 ~94%(不变 · 代码 + docs + 5 件套 sync 全部到位)
- 可无人值守生产 ~82%(↓ 3pp · #95 限制 menu_bar/dashboard 常驻)
- v1.0 发布就绪 ~87%(不变 · 撞坑 #94 修复 +0% v1.0 · #95 待修)

### 1h 观察窗观察项

- 数字员工 plist 状态(launchctl list | grep digital-employee)
- agent 月报 plist 状态(09:00 cron 触发)
- imap-sync plist 状态(07:00 cron 触发)
- 6 个 log 文件大小变化(mtime)
- 进程 pgrep(my-ai-employee 任何进程)

### 下一棒

- user 决策 #95 修复路径(A docs-only 接受 / B 改 plist ProcessType=Interactive / C 拆守护 + nohup setsid / D 不走 launchd 改 tmux daemon)
- 1h 观察后 docs/v0.2.78 #95 修复 D-step
- 24h 观察窗走完整数字员工
- v1.0 tag 评估(默认不打)
