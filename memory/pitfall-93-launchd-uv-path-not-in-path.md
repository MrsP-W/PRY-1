---
name: pitfall-93-launchd-uv-path-not-in-path
description: 撞坑 #93(2026-07-09)· launchd 子进程 PATH 不含 /opt/homebrew/bin(uv 安装位置)· T3 L3 实测撞坑 #92 修复后立即暴露 · 修复:wrapper 用绝对路径 /opt/homebrew/bin/uv + ops 脚本用 ${UV_BIN}="command -v uv || echo /opt/homebrew/bin/uv"
metadata:
  node_type: memory
  type: pitfall
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
  relatedPitfalls: ["pitfall-92-launchd-documents-data-path-block", "pitfall-91-launchd-documents-shell-operation-not-permitted", "pitfall-90-launchd-domain-not-persistent"]
---

# 撞坑 #93 — launchd 子进程 PATH 不含 uv 安装位置

## 关联

- **撞坑**:[[pitfall-92-launchd-documents-data-path-block]] 业务代码路径 Documents 沙箱(T3 L3 修复 B 完成后实测时立即暴露 #93)
- **同根因家族**:[[pitfall-91-launchd-documents-shell-operation-not-permitted]] launchd exec 阶段
- **D-step 阶段**:P3-A T3 L3 实测撞坑 #92 修复 B 是否真命中

## 现象

T3 L3 `launchctl load -w com.myaiemployee.digital-employee.plist` 后,数字员工菜单栏启动失败:

```text
launchctl list | grep myaiemployee
- 0 com.myaiemployee.agent
- 1 com.myaiemployee.digital-employee    ← exit 1
- 2 com.myaiemployee.imap-sync

~/Library/Logs/MyAIEmployee/menu_bar.log:
env: uv: No such file or directory
```

**关键诊断**:`ops/start-digital-employee.sh` line 252 区块 `cmd_start_menubar` 调用:

```bash
nohup env DASHBOARD_REAL_DB=1 uv run python "$RUN_MENUBAR" > "$MENUBAR_LOG" 2>&1 &
```

`uv` 在 launchd 子进程 PATH 中找不到 → exit 127 → nohup 失败 → `kill -0 $pid` 不通过 → wrapper exit 1。

## 根因

### launchd 默认 PATH

```text
/Users/wei/bin:/usr/local/bin:/usr/bin:/bin
```

### 用户 shell PATH

```text
/Users/wei/.local/bin:/Users/wei/.n/bin:/opt/homebrew/bin:...  ← 包含 /opt/homebrew/bin
```

### uv 安装位置

```text
/opt/homebrew/bin/uv → /opt/homebrew/Cellar/uv/0.11.6/bin/uv
```

**根因**:launchd 启动子进程使用 minimal PATH,**不继承** 用户 shell `~/.zshrc` / `~/.zprofile` 的 PATH 扩展。Homebrew 用户把 `/opt/homebrew/bin` 加进 PATH 是为了 `brew install` 的二进制(uv / node / python3 / git-lfs 等),但 launchd 直接 `exec()` 子进程时只看到系统级 PATH。

### 同根因家族

撞坑 #91 / #92 是 macOS `~/Documents/` iCloud 同步目录沙箱拦截;撞坑 #93 是 launchd PATH 不含第三方 `/opt/homebrew/bin`。两者共同特点:**user shell 配置不能直接迁移到 launchd 子进程**。

## 修复

### 候选方案对比

| 候选 | 改动 | 风险 | 决定 |
|------|------|------|------|
| **A 绝对路径** | wrapper heredoc 直接 hardcode `/opt/homebrew/bin/uv` | 🟢 最稳 · 1 行 · 不依赖 PATH · wrapper 静态生成 | ✅ **monthly-report + imap-sync wrapper** |
| **B 显式 export PATH** | wrapper 加 `export PATH="/opt/homebrew/bin:$PATH"` | 🟡 影响整个 wrapper · PATH 受 caller 限制 | ❌ |
| **C ${UV_BIN} 变量 + command -v fallback** | ops 脚本顶部 `UV_BIN="$(command -v uv 2>/dev/null \|\| echo /opt/homebrew/bin/uv)"` + 替换所有 `uv` → `${UV_BIN}` | 🟢 兼顾可移植性 + launchd PATH fallback | ✅ **ops/start-digital-employee.sh(digital-runner)** |
| **D shell profile 钩子** | `.zshrc` / `.zprofile` 加 launchd PATH 兼容 | ❌ 沿红线不写 shell profile | ❌ |

### 最终方案(A + C 组合)

#### 1. `scripts/launchd_install.sh` wrapper 模板(方案 A)

```bash
# monthly-report wrapper
echo "exec /opt/homebrew/bin/uv run --project \"${PROJECT_ROOT}\" python -m scripts.monthly_report generate --month \"\${MONTH}\""

# imap-sync wrapper
exec /opt/homebrew/bin/uv run --project "${PROJECT_ROOT}" python scripts/sync_imap.py sync --provider qq --email "${IMAP_USER}"
```

#### 2. `ops/start-digital-employee.sh` digital-runner(方案 C)

脚本顶部(紧跟 `# 启动入口` 段后):

```bash
# 撞坑 #93 修复(2026-07-09):launchd 子进程 PATH 不含 /opt/homebrew/bin(uv 安装位置),
# 用 command -v 优先探测 PATH · fallback 绝对路径,沿 v1.0 launch runbook 范本(可移植)
UV_BIN="$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)"
```

替换 6 处 `uv run` 调用(2 precheck + 2 real nohup + 2 dry-run echo):

```bash
# 1. precheck alembic(原 uv run alembic)
if cd "$PROJECT_ROOT" && "${UV_BIN}" run alembic current >/dev/null 2>&1; then

# 2. precheck dashboard import(原 uv run python -c "import...")
if cd "$PROJECT_ROOT" && "${UV_BIN}" run python -c "import my_ai_employee.dashboard.server" 2>/dev/null; then

# 3. real nohup menu bar(原 uv run python "$RUN_MENUBAR")
nohup env DASHBOARD_REAL_DB=1 "${UV_BIN}" run python "$RUN_MENUBAR" > "$MENUBAR_LOG" 2>&1 &

# 4. real nohup dashboard(原 uv run python -m my_ai_employee.dashboard.server)
nohup env DASHBOARD_REAL_DB=1 "${UV_BIN}" run python -m my_ai_employee.dashboard.server > "$DASHBOARD_LOG" 2>&1 &

# 5/6. dry-run echo(原 echo "[dry-run] ... uv run ...")
echo "[dry-run] DASHBOARD_REAL_DB=1 nohup ${UV_BIN} run python $RUN_MENUBAR > $MENUBAR_LOG 2>&1 &"
echo "[dry-run] DASHBOARD_REAL_DB=1 nohup ${UV_BIN} run python -m my_ai_employee.dashboard.server > $DASHBOARD_LOG 2>&1 &"
```

## 验证

### 测试覆盖

新增 4 个契约测试到 `tests/scripts/test_launchd_install.py`:

- **H1**:`ops/start-digital-employee.sh` 必含 `UV_BIN="$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)"`
- **H2**:所有 `uv run` 调用必用 `${UV_BIN}`(6 处:2 precheck + 2 real nohup + 2 dry-run echo)
- **H3**:monthly-report wrapper heredoc 必用 `/opt/homebrew/bin/uv run --project`
- **H4**:imap-sync wrapper heredoc 必用 `/opt/homebrew/bin/uv run --project`

测试结果:`47 passed in 0.04s`(原 43 + 新 4)。

### 9/9 质量门

实测结果:撞坑 #93 修复完成后:

- `pytest`:2916 passed / 1 skipped(+3 from new H2-H4 tests)
- `coverage`:89.10%
- `mypy`:0 errors, 256 files
- `ruff check`:All checks passed!
- `ruff format`:280+ files already formatted
- `alembic --sql`:exit 0
- `uv build`:Successfully built
- `MD lint`:282 files, 0 errors(原 278 + 新 4 docs/memory)
- `make check-snapshot`:OK

### deploy-only 实测(待 user 授权后)

```bash
bash scripts/launchd_install.sh deploy-only
```

预期:4 wrapper + 3 plist 全部刷新到含 `/opt/homebrew/bin/uv` / `${UV_BIN}` 的形式。

### 实测(待 user 授权后)

```bash
launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.digital-employee.plist
```

预期:
- `menu_bar.log` 出现 `菜单栏已启动(PID=...)` 而非 `env: uv: No such file or directory`
- `dashboard.log` 出现 `Dashboard 已启动(PID=...)`
- `launchctl list | grep myaiemployee` 数字员工 exit 0
- 9/9 预检:alembic current + dashboard.server 导入都成功(原本这两个 warning 因 uv 找不到而触发)

## Why

### 为什么 launchd PATH 不继承 shell

launchd 在 macOS 是 launch daemon,设计上**最小化攻击面 + 不依赖 user session**。当用户未登录时 launchd 也能跑(开机启动),所以:
- 不读 `~/.zshrc` / `~/.zprofile`(user session-bound)
- 不读 `~/.bash_profile`(user session-bound)
- 仅用 `launchctl` 内置的环境变量 + plist 的 `EnvironmentVariables` 字段

这意味着任何"用户 shell 自定义"(PATH 别名 / pyenv / asdf / brew shellenv)都不能直接进入 launchd 子进程。

### 为什么不能用 shell profile 钩子(方案 D 排除)

撞坑 #71 红线:**不写 shell profile**。除红线外:
- shell profile 修改会影响所有交互式 shell,改动面远超 launchd
- `~/.zshrc` launchd 根本不读,改了也无效
- 必须用 launchd-native 解决方案(显式绝对路径 / plist EnvironmentVariables)

### 为什么选 A + C 组合

- **wrapper(A 绝对路径)**:wrapper 是 `scripts/launchd_install.sh` heredoc 静态生成,运行期 PATH 完全无关。绝对路径 0 依赖最稳。
- **ops 脚本(C ${UV_BIN})**:`ops/start-digital-employee.sh` 同时被 wrapper 调用(launchd PATH) + 用户 shell 直接调用(终端 bash)。`${UV_BIN}` 兼容两种场景:shell 有 uv → 直接用;launchd 没 uv → fallback 绝对路径。

## How to apply

### 后续 launchd 复验

user 单独授权 `launchctl load -w com.myaiemployee.digital-employee.plist` → 预期:
- `tail ~/Library/Logs/MyAIEmployee/menu_bar.log` 无 `env: uv: No such file or directory`
- `tail ~/Library/Logs/MyAIEmployee/digital-employee.out.log` 显示 `菜单栏已启动(PID=...)` + `Dashboard 已启动(PID=...)`
- `launchctl list | grep myaiemployee` 数字员工 exit 0
- 9/9 预检从 7/9 OK + 2/9 warning 升级为 9/9 OK(alembic current + dashboard.server 都因 uv 找到而成功)

### 撞坑 #93 修复后下一棒

- 撞坑 #90 launchd 持久化方案 4 候选(可选 D-step)
- docs/v0.2.67 §19-21 误归校正(可选 docs-only)
- P3-B SMTP 单封真发(待 Notes dry-run 复验完成 / 新草稿 + 命名收件人)
- P4 24h dry-run 观察
- P5 v1.0 tag 评估(默认不打)
- T4 v1.0 收口 docs(沿 docs-only)

### don't repeat

- ❌ 不要在 launchd 子进程脚本里假设 shell PATH(必须 `command -v` 或绝对路径)
- ❌ 不要用 `~/.zshrc` / `~/.zprofile` 钩子试图影响 launchd(无效 + 撞红线)
- ❌ 不要把 `uv` 替换为 `python3 -m pip` 之类的 workaround(失去 uv 的 lockfile / venv 管理)
- ❌ 不要在 wrapper heredoc 里写 `PATH=$PATH:...` 然后期望 launchd 继承(launchd 用完全独立的环境)

## 关联记忆

- [[pitfall-92-launchd-documents-data-path-block]] — 撞坑 #92 原坑(T3 L3 修复 B 验证时暴露 #93)
- [[pitfall-92-fix-path-migration]] — 撞坑 #92 修复 B 范本
- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 撞坑 #91 exec 阶段
- [[pitfall-91-fix-launchd-runner-migration]] — 撞坑 #91 修复范本
- [[pitfall-90-launchd-domain-not-persistent]] — 撞坑 #90 session-bound(未触及)
- [[pitfall-launchd-deploy-only-mode]] — deploy-only 安全部署
- [[pitfall-87-snapshot-self-referential-drift]] — 撞坑 #87 校准范本
- [[checkpoint-2026-07-09-p3-a-t3-l3-93-fix]] — 撞坑 #93 修复收口(本轮)
- [[docs/v0.2.75-p3-a-t3-l3-93-fix-2026-07-09]] — 撞坑 #93 修复详细 docs