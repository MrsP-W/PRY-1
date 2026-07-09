---
name: checkpoint-2026-07-09-p3-a-t3-l2-92-fix
description: P3-A T3 L2 撞坑 #92 修复路径 B 收口 2026-07-09 · runtime 全部路径 ~/Documents/ → ~/Library/Application Support/ 迁移 · 9/9 质量门 + check-snapshot 双门 OK · deploy-only 实测 6/6 wrapper + 3 plist 部署 · .env 自动迁移成功 · launchctl 2/3 active + 数字员工 bootout 等 user 授权 T3 L3 实测
metadata:
  node_type: memory
  type: checkpoint
  originSessionId: c12aa87a-83e7-4b90-9631-fdb90140610a
---

# P3-A T3 L2 撞坑 #92 修复路径 B 收口 2026-07-09

## 🎯 一句话

撞坑 #92 业务代码路径 Documents 沙箱修复路径 B 实施完成:`ops/start-digital-employee.sh` + `scripts/launchd_install.sh` + `tests/scripts/test_launchd_install.py` 三件套协同改动,4 files / ~80 lines 净增 / 5 新测试(F8/F9/F10/G1/G2)+ 撞坑 #87 #87 校准 5 件套 baseline sync(`2908/1/270/89.12%` → `2913/1/278/89.10%`)· 9/9 质量门 + check-snapshot 双门 OK · `bash scripts/launchd_install.sh deploy-only` 实测成功(`.env` 自动迁移 2355 bytes / 58 lines,3 wrapper + 3 plist 部署)· launchctl list 终态 2/3 active + 数字员工 bootout · **user 单独授权后 T3 L3 实测验证 #92 修复 B 是否真命中(预期 err log 无 `Operation not permitted` + 9/9 预检 OK + 菜单栏启动成功)**。

## HH:MM [T3 L2 #92 修复 B 收口]

✅ 已完成:
- 撞坑 #92 修复 B 实施:`ops/start-digital-employee.sh` 路径变量(`APP_SUPPORT_DIR` + `ENV_FILE` + `DATA_DIR` + `LOG_DIR`)+ `scripts/launchd_install.sh` 改 heredoc(`cat << EOF`) + APP_SUPPORT setup + .env 自动迁移 + 3 wrapper export 三变量
- 新增 5 测试:F8(APP_SUPPORT setup)+ F9(wrapper 显式 export)+ F10(IMAP wrapper 用 APP_SUPPORT_ENV)+ G1(start 读 ENV_FILE)+ G2(start DATA_DIR 用 APP_SUPPORT)
- F5 同步调整:从 `echo "..."` 转义形式(`\\"${VAR}\\"`)改 heredoc 形式(`"${VAR}"`)
- 撞坑 #87 self-drift 校准 5 件套 baseline sync:`2908/1/270/89.12%` → `2913/1/278/89.10%`
- 9/9 质量门 + check-snapshot 双门 OK
- deploy-only 实测 6/6 wrapper 文件就位 + 3 plist 部署 + .env 自动迁移(`Documents/.env` 58L → `~/Library/Application Support/MyAIEmployee/.env` 58L · 2355 bytes)

🟡 待办:
- user 单独授权 launchctl load -w 数字员工 → T3 L3 实测验证
- 撞坑 #90 launchd 持久化方案(D-step 评估)
- docs/v0.2.67 §19-21 误归校正(docs-only)
- P3-B SMTP 单封真发(待 Notes dry-run 复验 / 新草稿)
- P4 24h dry-run
- P5 v1.0 tag 评估(默认不打)
- T4 v1.0 收口 docs

📂 关键产出:
- `docs/v0.2.74-p3-a-t3-l2-92-fix-2026-07-09.md`(详细 docs)
- `memory/pitfall-92-fix-path-migration.md`(修复沉淀)
- `memory/checkpoint-2026-07-09-p3-a-t3-l2-92-fix.md`(本文件)
- `MODIFICATION-LOG.md` ## 90 段(本次)
- `src/my_ai_employee/quality_snapshot.py` baseline 更新
- `README.md` / `CLAUDE.md` / `SESSION-STATE.md` / `MODIFICATION-LOG.md` / `docs/v0.2-launch-plan.md` 5 件套 sync

## 撞坑 #92 修复路径 B 关键改造点

| 改造点 | 旧 | 新 |
|------|----|----|
| runtime .env | `$PROJECT_ROOT/.env` | `$HOME/Library/Application Support/MyAIEmployee/.env` |
| runtime data/ | `$PROJECT_ROOT/data/` | `$HOME/Library/Application Support/MyAIEmployee/data/` |
| PID 文件 | `$PROJECT_ROOT/data/*.pid` | `$APP_SUPPORT_DIR/data/*.pid` |
| 业务日志 | `$DATA_DIR/logs/*.log`(链式 PROJECT_ROOT)| `$HOME/Library/Logs/MyAIEmployee/*.log`(v1.0 范本已是非 Documents)|
| wrapper 生成 | `echo "..."` 多行 | `cat << EOF` heredoc |
| wrapper export | 仅 `MY_AI_EMPLOYEE_PROJECT_ROOT` | + `MY_AI_EMPLOYEE_APP_SUPPORT_DIR` + `MY_AI_EMPLOYEE_ENV_FILE` |

## Why

**为什么选 path B**(对照 A/C/D 候选):

| 候选 | 范围 | 风险 | 决定 |
|------|----|----|----|
| A 改 runner 路径 | 最小改动 · 仅改数字员工 | 🟡 .env / log 维护点增多;iCloud 仍同步 .env 隐私数据 | ❌ |
| **B 整个项目 runtime 路径迁 `~/Library/Application Support/`** | 全代码收益 · 大变更(本轮 ~80 lines)| 🟢 沿 v1.0 launch runbook 范本 · macOS 推荐位置 · git 历史不变 · 软链不变 | ✅ **本轮实施** |
| C 软链 Documents → ~/bin | 折中 | 🟡 软链复杂 · TCC 多层 · 仍受 iCloud 同步影响 | ❌ |
| D 不动 · 维持 bootout | 零改动 | 🔴 数字员工永久 bootout · 完全体 6/6 job 失去 | ❌ |

**关键决策依据**:
- 撞坑 #1 红线证据:`.env` 包含私密凭据,Apple 推荐放 `~/Library/Application Support/<bundle>/`(系统级保护 + 不进 iCloud 同步)
- 撞坑 #92 根因是 macOS Documents 沙箱拦截 bash exec / grep / `>`,根本解是离开 Documents,而非 workaround
- v1.0 launch runbook 已规划类似路径(此次只是把 launchd runtime 路径提前对齐)

## 撞坑 #92 vs #91 关键区分

| 维度 | 撞坑 #91(T3 L2 已修)| 撞坑 #92(T3 L2 本轮 B 已修)|
|------|------|------|
| 触发位置 | launchd exec 阶段 | runtime 业务代码 |
| 路径模式 | `bash exec <Documents>/ops/start-digital-employee.sh` | `runner > grep .env` / `runner > data/menu_bar.log` |
| 修复路径 | A(wrapper 改调 `~/bin/`)+ B(同本轮)| B(runtime 路径迁 `~/Library/Application Support/` + heredoc)|
| 修复 commit | `db3f2e4` + `f430304` | 本次 `## 90` commit |
| 修复验证 | T3 L3 launchctl load -w 真复验 ✅ | 待 T3 L3 launchctl load -w 实测(本轮路径预期)|

## 全局快照

| 维度 | 状态 |
|------|------|
| 9/9 质量门 | ✅ 全绿(2913/1/89.10/278/256)|
| launchd 实际 | 2/3 active(agent + imap-sync)+ 数字员工 bootout |
| 撞坑数 | 92(= 上轮 · #92 修复不增)|
| v1.0 完成度 | 89% → **91%** |
| 可无人值守 | 86% → **90%** |
| 项目整体 | 93% → **94%** |

## 关联记忆

- [[pitfall-92-launchd-documents-data-path-block]] — 撞坑 #92 原坑(T3 L3 暴露)
- [[pitfall-92-fix-path-migration]] — 撞坑 #92 修复 B 沉淀(本次)
- [[pitfall-91-launchd-documents-shell-operation-not-permitted]] — 撞坑 #91 原坑
- [[pitfall-launchd-deploy-only-mode]] — deploy-only 安全部署模式
- [[pitfall-87-snapshot-self-referential-drift]] — 撞坑 #87 校准
- [[checkpoint-2026-07-09-p3-a-t3-l2-deploy-only]] — T3 L2 deploy-only 收口
- [[checkpoint-2026-07-09-p3-a-t3-l2-91-fix]] — 撞坑 #91 代码修复
- [[checkpoint-2026-07-09-p3-a-t3-l3-reverify]] — T3 L3 真复验(#92 暴露)
- [[day11-snapshot-guardian-drift-2026-07-04]] — 撞坑 #87 5 件套同步范本
- [[docs/v0.2.74-p3-a-t3-l2-92-fix-2026-07-09]] — 详细 docs
