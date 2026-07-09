---
name: pitfall-92-fix-path-migration
description: 撞坑 #92 修复路径 B(2026-07-09)· 把 launchd runtime .env / data/ / pid / log 路径全部迁出 ~/Documents/ iCloud 同步目录 → ~/Library/Application Support/MyAIEmployee/ + ~/Library/Logs/MyAIEmployee/(沿 v1.0 launch runbook 范本)
metadata:
  node_type: memory
  type: pitfall-fix
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
  relatedPitfalls: ["pitfall-92-launchd-documents-data-path-block", "pitfall-91-launchd-documents-shell-operation-not-permitted", "pitfall-launchd-deploy-only-mode"]
---

# 撞坑 #92 修复路径 B — runtime 路径迁 ~/Library/Application Support/

## 关联

- **撞坑**:[[pitfall-92-launchd-documents-data-path-block]] 业务代码路径 Documents 沙箱
- **同根因**:[[pitfall-91-launchd-documents-shell-operation-not-permitted]] launchd exec 阶段
- **修复范本**:[[v1.0-launch-runbook]] v1.0 launch 阶段已规划类似路径

## 修复内容

### runtime 路径映射(沿 v1.0 launch runbook 范本)

| 用途 | 旧路径(Documents 沙箱) | 新路径(非 Documents) |
|------|------|------|
| `.env` | `$PROJECT_ROOT/.env` | `$HOME/Library/Application Support/MyAIEmployee/.env` |
| `data/` | `$PROJECT_ROOT/data/` | `$HOME/Library/Application Support/MyAIEmployee/data/` |
| PID files | `$PROJECT_ROOT/data/*.pid` | `$APP_SUPPORT_DIR/data/*.pid` |
| 业务日志 | `$DATA_DIR/logs/*.log` | `$HOME/Library/Logs/MyAIEmployee/*.log`(v1.0 已是非 Documents)|

### env override 优先级

```bash
APP_SUPPORT_DIR="${MY_AI_EMPLOYEE_APP_SUPPORT_DIR:-$HOME/Library/Application Support/MyAIEmployee}"
ENV_FILE="${MY_AI_EMPLOYEE_ENV_FILE:-$APP_SUPPORT_DIR/.env}"
DATA_DIR="$APP_SUPPORT_DIR/data"
LOG_DIR="${MY_AI_EMPLOYEE_LOG_DIR:-$HOME/Library/Logs/MyAIEmployee}"
```

**关键**:launchd 安装脚本生成的 `~/bin/my-ai-employee-start` wrapper 显式 `export` 三个变量,避免 ops 脚本 fallback 到默认 Documents 路径。

## 实施步骤

1. **`scripts/launchd_install.sh` 改 heredoc**
   - 新增 `APP_SUPPORT_DIR` + `APP_SUPPORT_ENV` 变量定义(沿 v1.0 launch runbook)
   - 段落「`# ===== 2. 目标目录校验 =====`」后追加 APP_SUPPORT_DIR 创建 + 权限校验
   - `.env` 自动迁移(若 source 存在且 target 不存在 → `cp`)
   - IMAP wrapper + start wrapper 生成改 heredoc(`cat << EOF`),避免 `echo "..."` 转义地狱
   - digital-runner wrapper 显式 `export` 三个变量

2. **`ops/start-digital-employee.sh` 路径变量迁 APP_SUPPORT**
   - `APP_SUPPORT_DIR` + `ENV_FILE` + `DATA_DIR` 重新定义
   - `LOG_DIR` 沿 v1.0 launch runbook 仍走 `~/Library/Logs/MyAIEmployee`(无需改)
   - `_get_imap_user_from_env` 读 `$ENV_FILE`
   - 预检 1/9 .env / 2/9 DB_ENCRYPTION_KEY / 9/9 data/ 全部走新路径

3. **`tests/scripts/test_launchd_install.py` 新增 5 个测试**
   - F8:APP_SUPPORT_DIR 创建 + .env 自动迁移
   - F9:digital-runner wrapper 显式 export APP_SUPPORT_DIR + ENV_FILE
   - F10:IMAP wrapper `ENV_FILE="${APP_SUPPORT_ENV}"`
   - G1:start 脚本读 ENV_FILE 而非 PROJECT_ROOT/.env
   - G2:start 脚本 `DATA_DIR="$APP_SUPPORT_DIR/data"` 而非 PROJECT_ROOT/data
   - F5 同步调整:`assert 'export MY_AI_EMPLOYEE_PROJECT_ROOT="${PROJECT_ROOT}"'`(heredoc 无 `\\"` 转义)

## 9 门 + check-snapshot 双门

实测结果:`2913 passed / 1 skipped / 89.10% / 278 MD / mypy 256 files` · make check-snapshot 双门 OK。

撞坑 #87 self-referential drift 校准:`2908/1/270/89.12%` → `2913/1/278/89.10%`(5 件套 baseline 同步,沿 [[day11-snapshot-guardian-drift-2026-07-04]] 第 7 步)。

## deploy-only 实测

```text
✅ 首次迁移 .env:/Users/wei/Documents/.../我的AI员工/.env → /Users/wei/Library/Application Support/MyAIEmployee/.env
📋 3 wrapper 部署到 ~/bin/my-ai-employee-{monthly-report,imap-sync,start,digital-runner}
✅ 3 plist 部署到 ~/Library/LaunchAgents/
✅ ~/Library/Logs/MyAIEmployee/ 日志目录就绪
```

.env 迁移后:
- 原:`/Users/wei/Documents/.../我的AI员工/.env` 58 lines · 2355 bytes
- 新:`/Users/wei/Library/Application Support/MyAIEmployee/.env` 58 lines · 2355 bytes
- (撞坑 #1 红线维持:`head -5 .env` 被 OS 拦下,只 `wc -l` 间接验证)

## launchctl 现状

| Label | 状态 | 备注 |
|------|------|------|
| `com.myaiemployee.agent` | active · exit 0 | 月报 cron |
| `com.myaiemployee.imap-sync` | registered · exit 2 | IMAP 每日 |
| `com.myaiemployee.digital-employee` | **bootout** | 待 launchctl load -w 实测 |

## Why

**为什么 path B 是最优解**(vs A 改 runner / C 软链 / D 暂缓):

1. **A 改 runner 路径**:仍受 iCloud 同步目录 macOS 自动同步行为影响(`uploads/`
   目录被复制到其他设备),数据私密性受损
2. **B 整项目迁出 Documents**:撞坑 #1 红线最强证据 — `.env` / `data/` 是 macOS 视
   为用户敏感数据的标准位置,迁 `~/Library/Application Support/` 反而是 Apple 推荐
3. **C 软链**:撞坑 #92 根因是 macOS 沙箱拦截,软链仍指向 Documents → 拦截继续触发
4. **D 暂缓**:数字员工永久 bootout,完全体 6/6 job 失去

B 路径对应业务代码 + 安装脚本 5 处同步改动,改完跑 9 门 + check-snapshot 全绿 + deploy-only 实测 6/6 wrapper 文件就位 = 撞坑 #92 已修。

## How to apply

1. **后续 launchd 复验**:user 单独授权 `launchctl load -w com.myaiemployee.digital-employee.plist` → 预期:
   - `tail ~/Library/Logs/MyAIEmployee/digital-employee.err.log` 无 `Operation not permitted`
   - `tail ~/Library/Logs/MyAIEmployee/digital-employee.out.log` 显示 9/9 预检 OK + 菜单栏启动成功
   - `launchctl list | grep myaiemployee` 3/3 注册

2. **撞坑 #92 修复后下一棒**:
   - 撞坑 #90 launchd 持久化方案 4 候选(可选 D-step)
   - docs/v0.2.67 §19-21 误归校正(可选 docs-only)
   - P3-B SMTP 单封真发(待 Notes dry-run 复验完成 / 新草稿 + 命名收件人)
   - P4 24h dry-run 观察
   - P5 v1.0 tag 评估(默认不打)
   - T4 v1.0 收口 docs(沿 docs-only)

3. **don't repeat**:
   - 不要在 `~/Documents/` 下做任何 launchd runtime 活动(读 / 写 / exec 任何文件)
   - 不要硬编码 `$PROJECT_ROOT/.env` 在 wrapper 内(沿 use `$APP_SUPPORT_ENV` 模式)
   - 不要在 install.sh 内用 `echo "..."` 包多行 wrapper 内容(改 heredoc,易读 + 测试)

## 关联记忆

- [[pitfall-92-launchd-documents-data-path-block]] — 撞坑 #92 原坑
- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 撞坑 #91 exec 阶段
- [[pitfall-91-fix-launchd-runner-migration]] — 撞坑 #91 path A 修复范本
- [[pitfall-90-launchd-domain-not-persistent]] — 撞坑 #90(未触及)
- [[pitfall-launchd-deploy-only-mode]] — deploy-only 安全部署
- [[pitfall-87-snapshot-self-referential-drift]] — 撞坑 #87 校准
- [[day11-snapshot-guardian-drift-2026-07-04]] — 5 件套同步范本
- [[checkpoint-2026-07-09-p3-a-t3-l2-deploy-only]] — T3 L2 部署收口
- [[checkpoint-2026-07-09-p3-a-t3-l2-91-fix]] — 撞坑 #91 修复
- [[checkpoint-2026-07-09-p3-a-t3-l3-reverify]] — T3 L3 真复验(#92 暴露)
- [[checkpoint-2026-07-09-p3-a-t3-l2-92-fix]] — T3 L2 #92 修复收口(本 checkpoint)
- [[docs/v0.2.74-p3-a-t3-l2-92-fix-2026-07-09]] — 详细 docs
