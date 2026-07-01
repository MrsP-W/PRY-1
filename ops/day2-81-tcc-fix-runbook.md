# 撞坑 #81 修复 Runbook — TCC 补授权 + 菜单栏点击复测(2026-07-01)

> **决策**:用户选 **B — Day 3 延后,先修 #81** · Day 2 可收口 · Day 3 真发等 #81 复测通过
> **类型**:ops runbook(docs-only · 零业务代码 · 撞坑 #71 沿用)
> **风险**:🟢 最低(只改系统授权 + 重启进程 · 不发邮件 · 不写 DB)

---

## §1 结论(一句话)

**#81 最可能是 TCC 授权对象加错了** — 菜单栏实际跑的是 `Python.framework/3.12`,不是 `.venv/bin/python3` 或 `/usr/bin/python3`;补对二进制 + kill 重启后,再测 3 项人工入口。

---

## §2 实测进程链(2026-07-01 诊断)

```text
PID 52230  uv run python scripts/run_menu_bar.py     ← nohup 父进程(PPID=1)
  └─ 52232  Python.framework/Versions/3.12/.../Python  ← 真实 GUI / NSApp / TCC 客户端
```

| 角色 | 绝对路径 |
|------|---------|
| **TCC 必加(主)** | `/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python` |
| uv 包装器(可选) | `/opt/homebrew/bin/uv` |
| 启动终端(建议) | Terminal.app 或 Cursor.app(你用来跑 `start-menubar.sh` 的那个) |

> ⚠️ **不要只加** `.venv/bin/python3` — `uv run` 在本机实际 spawn 的是 Framework Python,与 venv 路径不一致。

---

## §3 修复步骤(约 20 分钟 · 用户物理操作)

### Step 0 — 停掉旧进程(TCC 改完必须重启)

```bash
cd "/Users/wei/Documents/DesktopOrganizer/我的AI员工"
bash ops/start-menubar.sh stop
```

沿 v0.1-real-spike 范本:**TCC 授权后旧进程不会自动拿到新权限,必须 kill + 重启**。

### Step 1 — 辅助功能(⌥⌘N 全局快捷键)

1. 打开:系统设置 → 隐私与安全性 → **辅助功能**
2. 点 **+**,添加上表 **Python.framework 3.12** 路径(或拖入 Finder)
3. 开关打开 ✅
4. 若列表里已有旧的 `python3` / `.venv` 项但灰掉 → 删掉旧项,只保留 Framework Python

快捷打开(可选):

```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

### Step 2 — 自动化(Apple Notes / 系统设置跳转)

1. 系统设置 → 隐私与安全性 → **自动化**
2. 找到 **Python** 或 **Terminal/Cursor** → 允许控制 **System Events** / **Notes** 等
3. 若无条目:先前台启动一次菜单栏(Step 4),点「授权引导」触发系统弹窗

```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"
```

### Step 3 — 输入监控(若 ⌥⌘N 仍无响应)

部分 macOS 版本全局快捷键还需:

```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
```

添加同一 **Python.framework 3.12** 二进制。

### Step 4 — 前台优先复测(排除 nohup 变量)

```bash
bash ops/start-menubar.sh stop   # 确保无后台实例
make menu-bar                    # 前台 · 看 stderr · Ctrl+C 退出
```

**操作顺序(沿 #81 候选 2)**:

1. 点击 macOS **桌面空白处**(让 Terminal 失焦)
2. 点菜单栏 🧑‍💼 图标 → 菜单应弹出
3. 依次测下面 3 项

### Step 5 — 后台复测(通过 Step 4 后再做)

```bash
bash ops/start-menubar.sh restart
bash ops/start-menubar.sh status
```

---

## §4 #81 复测清单(3 项必过 · 人工确认)

| # | 操作 | 期望 | 通过 |
|---|------|------|------|
| 1 | 点 **「系统健康」** | macOS 通知弹出(含 pytest/coverage 基线) | ☐ |
| 2 | 点 **「授权引导」** | 系统设置 → 自动化页打开 | ☐ |
| 3 | **⌥⌘N**(先复制一段文字) | 通知或 badge 有反馈(Stub 阶段至少不 silent fail) | ☐ |

**附加(可选)**:

| # | 操作 | 期望 |
|---|------|------|
| 4 | 点 **「退出」** | 图标消失(若无响应 → Week 2 补 `@rumps.clicked("退出")`) |
| 5 | `bash ops/start-menubar.sh stop` | 后台实例可干净停止 |

---

## §5 若 3 项仍失败 — 分支诊断

| 分支 | 条件 | 下一步 |
|------|------|--------|
| **5A** | 前台 `make menu-bar` ✅ · 后台 `start-menubar.sh` ❌ | #81 子类:nohup Detached GUI · Week 2 改 launchd/.app 包 |
| **5B** | 前台 + 后台都 ❌ | 查 rumps 0.4.0 兼容性(候选 3) · Week 2 docs-only 评估升级 |
| **5C** | 仅 ⌥⌘N ❌ · 菜单点击 ✅ | 只补辅助功能/输入监控,不必阻塞 Day 3 邮件链路 |
| **5D** | 全部 ❌ 但图标可见 | 截图菜单 + `tail -50 data/menu_bar.log` 反馈 |

---

## §6 与 Day 3 门控关系

| 门 | #81 未修 | #81 复测 3/3 通过 |
|----|---------|------------------|
| Day 3 IMAP 同步 | 🟡 可并行(不依赖菜单栏) | ✅ |
| Day 3 QQ SMTP 真发 1 封 | ❌ **暂停**(需菜单栏人工入口) | ✅ 可启动(仍须 5 重门控 + 用户明确授权) |
| Day 4 CSV 导入 | ❌ 不建议跳 | ⏸️ 仍等 Day 3 |

**撞坑红线维持**:#76/#78/#79 真发 · #59 outlook/gmail · #71 业务代码 0 改动。

---

## §7 一键诊断脚本

```bash
bash ops/check-pitfall-81.sh
```

输出:当前 PID · 真实 Python 路径 · TCC 设置深链 · 复测命令提示。

---

## §8 维护者

**Mr-PRY** · 2026-07-01 · 用户决策 B 落地 · 撞坑 #81 从「Week 2 处理」→「Day 3 前必修」· 下一棒:用户完成 §3 Step 1-5 + §4 三项打勾 → 回报「#81 复测通过」→ 授权 Day 3 真发。
