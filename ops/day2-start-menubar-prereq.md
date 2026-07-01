# Day 2 — `ops/start-menubar.sh` 提前写好(2026-07-01)

> **类型**:Day 2 组件提前写好(Day 1 阶段 2 后续 · 撞坑 #71 决议 B 范围内)
> **文件**:`ops/start-menubar.sh`(bash 封装 · 撞坑 #71 B 放行 · Day 1-2 基础设施)
> **风险**:🟢 零业务风险(纯 bash 封装 + dry-run 模式 + 不读真实凭据)
> **撞坑关联**:#71 决议 B 放行 · #59 红线维持 · #50 漂移防御

---

## §1 设计要点

### 1.1 4 个子命令(沿 launchd_install.sh 范本)

| 子命令 | 行为 | Day 2 用途 |
|--------|------|------------|
| `start` | nohup 后台启动 + 写 PID 文件 + 日志重定向 | 第一次启动菜单栏 |
| `stop` | 通过 PID 文件 SIGTERM → SIGKILL fallback | 收口 / 重启前 |
| `status` | 检查 PID 是否存活 + 显示最近 5 行日志 | 验证启动 / 调试 |
| `restart` | stop + sleep 1 + start | 改 .env 后重启 |

### 1.2 `--dry-run` 模式

```bash
bash ops/start-menubar.sh --dry-run start
# [dry-run] nohup uv run python /Users/wei/.../run_menu_bar.py > /Users/wei/.../data/menu_bar.log 2>&1 &
# [dry-run] echo $! > /Users/wei/.../data/menu_bar.pid
# ✅ dry-run 完成(未实际启动)
```

- 只打印要执行的命令,不实际跑
- 适合用户在 Day 2 启动前先看脚本会做什么

### 1.3 关键约定(共享路径)

| 路径 | 用途 | 与 Day 7 一键包的关系 |
|------|------|---------------------|
| `data/menu_bar.log` | 菜单栏 stdout/stderr | Day 7 `ops/start-digital-employee.sh` 共享 |
| `data/menu_bar.pid` | 当前菜单栏 PID | Day 7 stop 逻辑共享 |
| `scripts/run_menu_bar.py` | 实际启动脚本 | Day 7 不直接调,统一走 ops/ 封装 |

---

## §2 实测闭环(start → status → stop → status)

```bash
$ bash ops/start-menubar.sh start
[13:17:43] 启动菜单栏后台常驻...
✅ 菜单栏已启动(PID=38001,log=/Users/wei/.../data/menu_bar.log)

$ bash ops/start-menubar.sh status
✅ 菜单栏在跑(PID=38001)

$ bash ops/start-menubar.sh stop
[13:17:48] 停止菜单栏(PID=38001)...
✅ 菜单栏已停止

$ bash ops/start-menubar.sh status
⚠️ 菜单栏未在跑
[13:17:49] 启动:bash ops/start-menubar.sh start
```

**4 步全绿**:
- ✅ start 启动成功 + PID 文件写入
- ✅ status 检测到进程存活
- ✅ stop 通过 PID 文件 SIGTERM 干净退出
- ✅ status(stop 后)正确显示"未在跑"

---

## §3 Day 2 启动步骤(沿用户原计划 + 撞坑 #71 B 范围)

### 3.1 Day 2 09:00-10:30 — TCC 授权(用户本人物理操作)

1. 打开 **系统设置 → 隐私与安全性**
2. **完全磁盘访问** → 添加 `/usr/bin/python3`(或 Terminal/iTerm)→ 授权
3. **自动化** → 允许 Terminal 控制 Apple Notes / Mail 等
4. (可选)**辅助功能** → 允许 menu bar clipboard capture

### 3.2 Day 2 10:30-12:00 — 前台验证菜单栏图标(可选)

```bash
make menu-bar   # 前台启动 + 桌面肉眼确认图标 + Ctrl+C 退出
```

### 3.3 Day 2 14:30-16:00 — 后台常驻(走 ops/start-menubar.sh)

```bash
# 启动菜单栏后台
bash ops/start-menubar.sh start

# 验证在跑
bash ops/start-menubar.sh status

# 验证 5 子模块(沿用户原计划 16:00-17:30 时段)
# 1. clipboard capture — 在 macOS 复制一段文字,菜单栏"立即同步"
# 2. expense 告警 — 触发 expense_service
# 3. note confirm — 创建待确认笔记
# 4. outbox draft — 创建 1 封草稿
# 5. badge polling — 看实时 badge 更新

# 停止
bash ops/start-menubar.sh stop
```

### 3.4 Day 2 17:30-18:00 — Day 7 一键包准备

- `ops/start-menubar.sh` 已就位
- Day 7 写 `ops/start-digital-employee.sh` 时,直接 `bash ops/start-menubar.sh start` + dashboard 启动

---

## §4 撞坑决议

| # | 撞坑 | 状态 |
|---|------|------|
| **#71** docs-only 不前进 pytest/coverage | 🟢 沿用(本棒新文件是 bash 脚本,不影响 pytest/coverage)|
| **#59** outlook/gmail 红线 | 🟢 维持(本脚本不读真实凭据,只调 `scripts/run_menu_bar.py` · 其内部读 Keychain)|
| **#50** 漂移防御 | 🟢 维持(本脚本不读 quality_snapshot,只引项目目录约定)|
| **#1** Key 打印教训 | 🟢 维持(本脚本不 echo 任何 Key / auth_code)|

---

## §5 验证清单

- [x] `bash ops/start-menubar.sh start` ✅(PID=38001)
- [x] `bash ops/start-menubar.sh status` ✅(在跑 + log 显示)
- [x] `bash ops/start-menubar.sh stop` ✅(PID 干净退出)
- [x] `bash ops/start-menubar.sh status`(stop 后)✅(显示"未在跑")
- [x] `bash ops/start-menubar.sh --dry-run start` ✅(只打印命令)
- [x] `bash ops/start-menubar.sh --dry-run stop` ✅(无 PID 文件时 warn)
- [x] 文件 chmod +x ✅(`-rwxr-xr-x`)

---

## §6 维护者

**Mr-PRY** · 2026-07-01 Day 2 组件提前写好 · 撞坑 #71 决议 B 放行 · 撞坑 #59 红线维持 · 业务代码 0 改动(连续 6 周 + 1 天 · 撞坑 #71 沿用)· 等 Day 2 TCC 授权 + 菜单栏后台常驻正式使用。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **沿用范本**:[[v0.2.55.2-path4-spike]] + [[v0.2.7.1-keychain-runbook-and-redaction]] + `scripts/launchd_install.sh` 风格 · **下一棒**:Day 2 TCC 授权(Day 2 09:00 时段用户物理操作)+ `bash ops/start-menubar.sh start`(Day 2 14:30 时段)。