---
name: pitfall-95-launchd-background-process-type-no-fork
description: T3 L4 复验 #94 B 路径修复后暴露 launchd plist ProcessType=Background 不允许 fork 子进程(menu_bar/dashboard 启动后被 launchd 回收)
metadata:
  type: pitfall
---

# 撞坑 #95 · launchd ProcessType=Background 不允许 fork 子进程

**Why:**
T3 L4 复验 #94 B 路径修复(2026-07-09 21:27)成功:数字员工 launcher exit 0(从 1 → 0)+ 9/9 预检全过 + menu_bar.log B 路径 DB 反复 open/close 模式生效。但 **50 秒后** menu_bar + dashboard subprocess 全部退出,`launchctl print` 显示 `state=not running · active count=0` · port 8765 未监听。

**根因**:plist `ProcessType=Background` 在 launchd 语义里 **禁止 fork**。launcher 脚本用 `nohup env DASHBOARD_REAL_DB=1 ${UV_BIN} run python ... > $LOG 2>&1 &` fork 出 menu_bar/dashboard subprocess,launchd 检测到 Background process fork 行为,**回收所有子进程**(Background 进程要求单进程在 foreground,不允许 fork 任何子进程)。

**How to apply:**

## 触发链路(实测栈)

```
launchctl load -w com.myaiemployee.digital-employee.plist
  ↓ RunAtLoad 触发
launchd 启动 my-ai-employee-start wrapper
  ↓
launcher 脚本内 nohup fork menu_bar subprocess(PID 写入 .pid 文件)
  ↓
launchd 检测 Background fork 行为 → 标记违规
  ↓
launcher 退出(exit 0,完成 9/9 预检)
  ↓
launchd 回收 menu_bar/dashboard subprocess(50s 内)
  ↓
state=not running · active count=0 · port 8765 未监听
```

## 与之前撞坑的关联

- 沿 #91(Documents exec)+ #92(代码路径 Documents 沙箱)+ #93(launchd uv PATH 缺失)+ #94(menu_bar DB context manager)的 launchd 实战第五坑
- #91-#94 全部修复通过 ✅
- #95 是 launchd 进程模型的固有限制(Background 模式 strict),而非代码 bug

## 撞坑 #95 与撞坑 #90 launchd session-bound 的关系

- #90:9.5h 内 active → inactive 衰减 · reboot/logout 后失效(持久化方案 D-step)
- #95:launcher fork 立即被回收 · menu_bar/dashboard 不能作为 launchd 子进程常驻
- 两个问题互补:#95 解决"如何让 menu_bar/dashboard 在 launchd 下存活",#90 解决"如何让 launchd job 跨 session 持久化"

## 修复路径候选(待 D-step 决策)

- **A · docs-only 接受当前 launcher 一次性 RunAtLoad 模式**:launcher 每次 load 启动 → 9/9 预检 → fork menu_bar/dashboard(被回收)→ exit 0 · 数字员工 plist 实际变成"启动检查器"而非"数字员工常驻守护" · 1h/24h 观察锚 agent + imap-sync · 0 改动
- **B · 改 plist `ProcessType=Interactive`**:允许 fork · 但需要 GUI session + 用户登入(撞坑 #90 仍生效)· 1 D-step
- **C · 拆守护进程:launcher fork + plist `KeepAlive=true` + `nohup setsid` 强 detach**:launcher 用 `nohup setsid` 强制让子进程脱离 launchd 控制组 · 1 D-step
- **D · 不走 launchd,数字员工用 tmux/screen daemon**:launchd 只管 agent + imap-sync · 数字员工手动 `nohup my-ai-employee-start` 启动 · launchctl bootout 数字员工 plist · 0.5 D-step

## 红线维持

- 不动 `plist` 直到明确决策 → 撞坑 #71 docs-only 边界
- 不写 `.env` 凭据 → 撞坑 #1
- 撞坑 #94 B 路径修复实战通过(`make_sqlalchemy_engine(db_path=...)` 长生命周期连接重开)
- 9/9 质量门 全绿(2920/1/89.12/285/257)

## 推荐路径

**A → B/C 后续 D-step**
- 现在:接受 launcher 一次性 RunAtLoad 模式 · 1h 观察以 agent + imap-sync 为锚
- 后续:决策 B/C/D 修复 #95 · 24h 观察走完整数字员工
- 撞坑 #94 修复(已落地) + #95 修复(D-step 待) + #90 持久化(D-step 待)三件套全完成后,v1.0 tag 评估
