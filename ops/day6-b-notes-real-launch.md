# Day 6 — B 路径 Apple Notes 真同步启动准备(2026-07-01)

> **类型**:7 天计划 Day 6 · 选项 B(Apple Notes 真同步)
> **模式**:docs-only 启动准备(用户选 docs-only · 等下个会话明确 Apple ID + TCC 授权 + 「OK 真同步」)
> **风险**:🟡 中(撞坑 #83 新撞坑登记 · TCC 自动化授权依赖 macOS 系统设置)
> **撞坑关联**:#49 faker 范本 · #81 ⌥⌘N 已修复 · #83 新(Notes 真同步链路)

---

## §1 用户决策(2026-07-01)

| 决策点 | 选择 | 含义 |
|--------|------|------|
| **Day 6 B 路径** | docs-only 启动准备 | 不真同步 · 等 Apple ID + TCC 授权 |
| **NOTES_REAL_NETWORK** | 维持 UNSET(默认) | 真同步须用户显式设置 |
| **TCC 自动化授权** | 用户须先授权(系统设置 → 隐私与安全性 → 自动化) | Notes.app + Terminal/Python |

---

## §2 Notes 真同步前置条件(6 项 checklist)

| # | 条件 | 现状 | 用户动作 |
|---|------|------|---------|
| 1 | Apple ID 已登录(macOS 系统设置 → Internet 账户) | 待确认 | `系统设置 → Internet 账户 → iCloud → Notes 启用` |
| 2 | Notes.app 已开启 iCloud 同步 | 待确认 | Notes.app → 账户 → iCloud 勾选 |
| 3 | macOS TCC 自动化授权 | 未授权 | `系统设置 → 隐私与安全性 → 自动化 → Terminal/Python → Notes.app ✅` |
| 4 | Day 2 撞坑 #81 修复沿用 | ✅ 已修复 | 首次启动菜单栏须先授权 Python.framework 3.12 |
| 5 | `scripts/sync_notes.py sync` 子命令可用 | ✅ 存在 | — |
| 6 | NOTES_REAL_NETWORK=1 env var | 维持 UNSET | 用户授权后设置 |

---

## §3 真实同步命令范本(等用户授权)

### 3.1 真同步 5 条

```bash
# 用户须:
# 1) Apple ID 已登 + Notes.app iCloud 同步开
# 2) macOS TCC 自动化授权(系统设置 → 隐私与安全性 → 自动化)
# 3) 明确授权「OK 真同步 5 条」

export NOTES_REAL_NETWORK=1
uv run python scripts/sync_notes.py sync --max-rows 5
```

### 3.2 spike 模式(无需 TCC · 30 笔 faker)

```bash
# 不需 NOTES_REAL_NETWORK,不需 TCC
uv run python scripts/sync_notes.py spike --n 5
# 预期输出:notes spike: parsed=5 inserted=0 skipped=5 failed=0
```

### 3.3 dry-run 模式(默认拒同步)

```bash
# 不设 NOTES_REAL_NETWORK,默认拒同步
uv run python scripts/sync_notes.py sync --max-rows 5
# 预期输出:❌ 默认拒绝同步: 须设置 NOTES_REAL_NETWORK=1
```

---

## §4 TCC 自动化授权引导(撞坑 #81 沿用)

> **沿 Day 2 撞坑 #81 修复结论**:TCC 应授权 **Python.framework 3.12**(系统 Python),不是 `.venv/bin/python3`(虚拟环境)。

### 4.1 菜单栏自动化

```
系统设置 → 隐私与安全性 → 自动化
  ├─ Terminal(或 iTerm)
  │   └─ ✅ Notes.app
  └─ Python.framework 3.12(系统 Python,不是 .venv/bin/python3)
      └─ ✅ Notes.app
```

### 4.2 一键诊断脚本(沿 ops/check-pitfall-81.sh 范本)

```bash
bash ops/check-pitfall-81.sh --open
# 自动打开系统设置 → 隐私与安全性 → 自动化
```

### 4.3 复测清单(沿 Day 2 撞坑 #81 §4 范本)

- [ ] 系统设置 → 自动化 → Terminal → Notes.app ✅
- [ ] 系统设置 → 自动化 → Python.framework 3.12 → Notes.app ✅
- [ ] 重启菜单栏(`bash ops/start-menubar.sh restart`)
- [ ] 点击菜单栏 → 系统健康 → Notes 状态显示 "connected"

---

## §5 撞坑累计更新

| 撞坑号 | 状态 | 说明 |
|--------|------|------|
| **#83 新登记** | 🟢 docs-only(等真同步时验证) | Apple Notes 真同步链路 |
| **#49** | 🟢 faker 范本 | spike 模式 30 笔 OK |
| **#81** | 🟢 维持 | ⌥⌘N 沿 Day 2 3/3 · 首次启动需 TCC |
| **#71** | 🟢 沿用 | 业务代码 0 改动 |

**撞坑累计 83 类(本轮新增 #83)**。

---

## §6 启动门槛(用户授权触发清单)

| # | 触发项 | 撞坑 |
|---|--------|------|
| 1 | Apple ID 已登 + Notes.app iCloud 同步开 | — |
| 2 | macOS TCC 自动化授权(Terminal/Python → Notes.app) | 撞坑 #81 沿用 |
| 3 | 用户明确授权「OK 真同步 5 条」 | 撞坑 #59 QQ-only |
| 4 | `NOTES_REAL_NETWORK=1 uv run python scripts/sync_notes.py sync --max-rows 5` | 撞坑 #83 验证 |
| 5 | 实测输出 `parsed=5 inserted=N skipped=M failed=0`(N+M=5) | — |
| 6 | 写 `ops/day6-b-notes-real-closure.md` | — |

---

## §7 维护者

**Mr-PRY** · 2026-07-01 Day 6 B 路径 docs-only 启动准备(撞坑 #83 新登记 · NOTES_REAL_NETWORK 维持 UNSET · TCC 授权引导就位 · 撞坑 #81 沿用)· 业务代码 0 改动(撞坑 #71 沿用)· 9/9 质量门 baseline **2620 passed / 88.95%** / 236 MD · 等 Apple ID + TCC + 「OK 真同步」授权。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **下一棒**:Day 6 C 一键启动包(已落地 `ops/start-digital-employee.sh`)。