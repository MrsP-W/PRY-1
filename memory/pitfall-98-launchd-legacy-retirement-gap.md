---
name: pitfall-98-launchd-legacy-retirement-gap
description: launchd_install.sh 升级时未自动 retire 旧 com.myaiemployee.digital-employee · 旧 Dashboard 占 8765 导致双实例
metadata:
  type: project
---

# 撞坑 #98 — launchd 升级场景旧 job 迁移缺口

## 现象(2026-07-10 代码审查发现)

`scripts/launchd_install.sh` 仅 deploy 4 个新 job(agent / imap-sync / menu-bar / dashboard),**未**在加载新 job 前自动 retire 旧的 `com.myaiemployee.digital-employee`(Day 14 #95 修复前的父子进程 + `ProcessType=Background` 模式)。

升级时若旧版本仍残留:

1. 旧 `digital-employee` plist 仍注册 → launchd 不会自动 unload
2. 旧 Dashboard 可能继续占 port 8765
3. 新 Dashboard load 时:bind 失败 OR 与旧实例同时监听 8765(行为不确定)
4. 用户看到 "Dashboard 无法启动" / 状态错乱

## 根因

- 撞坑 #95 修复仅改 plist 拆 2 独立 LaunchAgent,**未**提供升级迁移步骤
- `launchd_install.sh` install 段直接进入 "load 新 4 job",无前置 "retire 旧 1 job" 段
- `uninstall` 段也只清理新 4 label,旧 `digital-employee` 漏网

## 严重度评估

| 维度 | 评估 |
|------|------|
| 当前实例故障 | ❌ 否(本机已手动 bootout + rm plist) |
| 升级场景阻断 | ⚠️ 是(从 #95 之前版本升级时必现) |
| 双实例风险 | ⚠️ port 8765 冲突 / HTTP 路由错乱 |
| 用户体验 | ⚠️ 静默失败(Dashboard 不起,err log 无显式信号) |

## 修复(2026-07-10 P1-2 已落地)

`scripts/launchd_install.sh` install 段插入 **5.5 legacy retirement**:

```bash
LEGACY_LABEL="com.myaiemployee.digital-employee"
LEGACY_PLIST="${LAUNCH_AGENTS_DIR}/${LEGACY_LABEL}.plist"
LEGACY_WRAPPER="${HOME_BIN}/my-ai-employee-start"
LEGACY_LOG_OUT="${LOG_DIR}/digital-employee.out.log"
LEGACY_LOG_ERR="${LOG_DIR}/digital-employee.err.log"

# 1. launchctl list 探测
# 2. 已注册 → launchctl unload, 兜底 launchctl bootout
# 3. rm plist / wrapper / 2 个 log
# 4. 验证 launchctl list 无残留(失败 exit 4)
```

**幂等**:已 retire 直接跳过(grep -q 未命中 + 文件不存在跳过分支)。

`uninstall` 段同步扩展到 **5 label**(原 4 + `com.myaiemployee.digital-employee`),wrapper 删除列表加 `~/bin/my-ai-employee-start`。

## 回归测试(K1-K4 · 2026-07-10 加)

| Test | 验证内容 |
|------|---------|
| K1 | install.sh 必含 legacy retirement 段(unload + bootout + rm + grep -q) |
| K2 | legacy retirement 必在 launchctl load 之前(否则旧实例仍在 8765) |
| K3 | legacy retirement 必幂等(未注册/不存在都跳过,不报错) |
| K4 | uninstall 段必把 legacy 一并 retire(unload + plist + verify ≥ 3 处) |

## 关联

- 撞坑 #95(`ProcessType=Background` 禁 fork · #98 是 #95 修复的升级路径补遗)
- 撞坑 #96(IMAP wrapper 绝对路径 · 同次升级应一并修)
- 撞坑 #91(macOS Documents/ iCloud exec OS 层拦截 · `~/bin` wrapper 改调 `${HOME}/bin/...` runner)

## Why & How to apply

**Why**:#95 修复时只关心"拆 2 独立 LaunchAgent",遗漏"如何从旧版本升级过来"的迁移路径。
**How to apply**:任何后续 launchd job 拆分(类似 #95)必须同步考虑:**旧 plist/wrapper 怎么 retire**。`launchd_install.sh` 模板已带 legacy retirement 段,后续新 job 替换时按相同范本补加对应 LEGACY_* 变量。