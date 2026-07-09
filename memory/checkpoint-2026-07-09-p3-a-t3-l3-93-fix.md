---
name: checkpoint-2026-07-09-p3-a-t3-l3-93-fix
description: P3-A T3 L3 撞坑 #93 修复收口 2026-07-09 · launchd 子进程 PATH 不含 /opt/homebrew/bin(uv 安装位置)· wrapper 改绝对路径 + ops 脚本用 ${UV_BIN} 检测 · 9/9 质量门 + check-snapshot 双门 OK · 47/47 launchd 测试 PASSED · 等 user 授权 T3 L4 实测验证
metadata:
  node_type: memory
  type: checkpoint
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
---

# P3-A T3 L3 撞坑 #93 修复收口 2026-07-09

## 🎯 一句话

撞坑 #93 launchd PATH 不含 /opt/homebrew/bin 修复完成:`ops/start-digital-employee.sh` 用 `${UV_BIN}="$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)"` + 6 处 `uv` → `${UV_BIN}` 替换 + `scripts/launchd_install.sh` wrapper heredoc 模板改绝对路径 `/opt/homebrew/bin/uv` + 4 新测试(H1-H4 撞坑 #93 契约)· 9/9 质量门 + check-snapshot 双门 OK · 47/47 launchd 测试 PASSED · 撞坑 #87 self-drift 校准 5 件套 baseline sync(`2913/1/278` → `2916/1/282`)· **user 单独授权后 T3 L4 实测验证 #93 修复是否真命中(预期 menu_bar.log 无 `env: uv: No such file or directory` + 9/9 预检 OK + 菜单栏 + Dashboard 都启动)**。

## HH:MM [T3 L3 #93 修复 收口]

✅ 已完成:
- 撞坑 #93 修复:`ops/start-digital-employee.sh` 顶部加 `UV_BIN` 检测变量 + 6 处 `uv` 全部替换为 `${UV_BIN}`(2 precheck + 2 real nohup + 2 dry-run echo)
- `scripts/launchd_install.sh` wrapper heredoc 模板改绝对路径 `/opt/homehomebrew/bin/uv`(monthly-report + imap-sync 2 wrapper)
- 新增 4 测试:H1(UV_BIN 检测)+ H2(6 处全替换)+ H3(monthly wrapper 绝对路径)+ H4(imap wrapper 绝对路径)
- H2 测试 bug 修复:`${{UV_BIN}}` f-string 转义 + regex `\$\{UV_BIN\}[\"']?\s+run` 兼容两种 quote 形式
- 47/47 launchd 测试 PASSED
- 撞坑 #87 self-drift 校准 5 件套 baseline sync:`2913/1/278` → `2916/1/282`
- 4 个新 MD 文件:docs/v0.2.74.1(撞坑 #92 巡检报告)+ docs/v0.2.75(撞坑 #93 修复 docs)+ memory/pitfall-93 + memory/checkpoint-2026-07-09-p3-a-t3-l3-93-fix

🟡 待办:
- user 单独授权 launchctl load -w 数字员工 → T3 L4 实测验证撞坑 #93 修复
- 撞坑 #90 launchd 持久化方案(D-step 评估)
- docs/v0.2.67 §19-21 误归校正(docs-only)
- P3-B SMTP 单封真发(待 Notes dry-run 复验 / 新草稿)
- P4 24h dry-run
- P5 v1.0 tag 评估(默认不打)
- T4 v1.0 收口 docs

📂 关键产出:
- `ops/start-digital-employee.sh`(修改 · +UV_BIN 检测 + 替换 6 处 uv)
- `scripts/launchd_install.sh`(修改 · wrapper heredoc 改绝对路径)
- `tests/scripts/test_launchd_install.py`(修改 · 新增 H1-H4 测试)
- `src/my_ai_employee/quality_snapshot.py`(修改 · lint 278 → 282)
- `README.md` / `CLAUDE.md` / `SESSION-STATE.md` / `MODIFICATION-LOG.md` / `docs/v0.2-launch-plan.md` 5 件套 sync
- `docs/v0.2.74.1-p3-a-92-preload-audit-2026-07-09.md`(新 · 撞坑 #92 巡检报告)
- `docs/v0.2.75-p3-a-t3-l3-93-fix-2026-07-09.md`(新 · 撞坑 #93 修复 docs)
- `memory/pitfall-93-launchd-uv-path-not-in-path.md`(新 · 撞坑 #93 沉淀)
- `memory/checkpoint-2026-07-09-p3-a-t3-l3-93-fix.md`(本文件)
- `MODIFICATION-LOG.md` ## 91 段(本次)

## 撞坑 #93 修复关键改造点

| 改造点 | 旧 | 新 |
|------|----|----|
| wrapper uv 调用 | `exec uv run --project...` | `exec /opt/homebrew/bin/uv run --project...` |
| ops 脚本 uv 调用 | `uv run alembic` / `uv run python ...` | `${UV_BIN} run alembic` / `${UV_BIN} run python ...` |
| UV_BIN 检测 | 不存在 | `UV_BIN="$(command -v uv 2>/dev/null \|\| echo /opt/homebrew/bin/uv)"` |
| 适用场景 | 仅用户 shell | shell + launchd(双兼容)|

## Why

**为什么撞坑 #93 在撞坑 #92 之后才暴露**:
- 撞坑 #91(launchd exec 阶段)修了 `~/bin/wrapper`,但撞坑 #92 暴露 business code 路径 Documents
- 撞坑 #92 修复 B 把所有 .env / data / log 迁出 Documents,本以为完全体 100% 修复
- T3 L3 实测 `launchctl load -w` → out log 显示预检成功(uv 找到)!但 menu bar 子进程 env: uv 找不到

根因排查发现:launchd 子进程 PATH 是 `/Users/wei/bin:/usr/local/bin:/usr/bin:/bin`,**不含** `/opt/homebrew/bin`(uv 实际安装位置)。

这是 macOS launchd 设计上不继承 user shell PATH(`~/.zshrc` 不读)导致的,与撞坑 #91 / #92 无关,是 launchd 生态本身的限制。

**为什么不写 shell profile**(沿撞坑 #71 红线 + launchd 不读 shell profile):
- `.zshrc` / `.zprofile` launchd 根本不会读
- 改 shell profile 影响所有交互式 shell,改动面远超 launchd
- 必须用 launchd-native 解决方案(绝对路径 / plist EnvironmentVariables / 脚本内 UV_BIN 检测)

## 撞坑 #93 vs #91 vs #92 三者区分

| 维度 | #91 | #92 | #93 |
|------|-----|-----|-----|
| 触发位置 | launchd exec 阶段 | runtime 业务代码 | launchd 子进程 PATH |
| 路径模式 | `bash exec <Documents>/ops/...` | `runner > grep .env` | `nohup env ... uv run ...` |
| 拦截源 | macOS Documents 沙箱 | macOS Documents 沙箱 | launchd minimal PATH |
| 修复路径 | wrapper 改 `~/bin/` | runtime 路径迁 APP_SUPPORT | 绝对路径 + UV_BIN 检测 |
| 修复 commit | `db3f2e4` + `f430304` | `5c0c7be` + `47cfe89` | 本轮 commit ## 91 |
| 实测验证 | ✅ T3 L3 | ✅ T3 L3(本次实测暴露 #93)| 🟡 待 T3 L4 |

## 全局快照

| 维度 | 状态 |
|------|------|
| 9/9 质量门 | ✅ 全绿(2916/1/89.10/282/256)|
| launchd 实际 | 3/3 active · 数字员工 exit 1(撞坑 #93 暴露)|
| 撞坑数 | 92 → **93**(+1 · launchd PATH 新发现)|
| v1.0 完成度 | 91% → **92%**(#93 修复 +1)|
| 可无人值守 | 90% → **91%**(#93 修复 +1)|
| 项目整体 | 94% |

## 关联记忆

- [[pitfall-93-launchd-uv-path-not-in-path]] — 撞坑 #93 沉淀
- [[pitfall-92-launchd-documents-data-path-block]] — 撞坑 #92 原坑
- [[pitfall-92-fix-path-migration]] — 撞坑 #92 修复 B
- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 撞坑 #91 exec
- [[pitfall-91-fix-launchd-runner-migration]] — 撞坑 #91 修复
- [[pitfall-90-launchd-domain-not-persistent]] — 撞坑 #90 session-bound(未触及)
- [[pitfall-launchd-deploy-only-mode]] — deploy-only 安全部署
- [[pitfall-87-snapshot-self-referential-drift]] — 撞坑 #87 校准
- [[checkpoint-2026-07-09-p3-a-t3-l3-reverify]] — T3 L3 #92 实测收口(本次暴露 #93)
- [[checkpoint-2026-07-09-p3-a-t3-l2-92-fix]] — T3 L2 #92 修复收口
- [[docs/v0.2.75-p3-a-t3-l3-93-fix-2026-07-09]] — 撞坑 #93 修复详细 docs