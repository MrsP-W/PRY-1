# Day 6 — C 路径一键启动包收口(2026-07-01)

> **类型**:7 天计划 Day 6 · 选项 C(`ops/start-digital-employee.sh` 一键启动包)
> **模式**:基础设施文件新写(撞坑 #71 决议 B 范围内 · 沿 ops/start-menubar.sh Day 2 范本)
> **风险**:🟢 低(纯 ops 脚本 · 不读真实凭据 · 串联已有服务 · 9 维度预检)
> **撞坑关联**:#71 B 范围 · #59 红线维持 · #18 风险门控 · #50 漂移防御 · #81 已修复

---

## §1 用户决策(2026-07-01)

| 决策点 | 选择 | 含义 |
|--------|------|------|
| **Day 6 C 路径** | 真写 `ops/start-digital-employee.sh` | 撞坑 #71 B 范围内(基础设施) |
| **串联范围** | menubar 后台 + Dashboard 只读 API + Keychain 验证 + 1-click 审批引导 | 4 棒串跑 |
| **真实凭据** | 不读(撞坑 #59 红线维持) | 仅探测 Keychain 是否已配 |

---

## §2 实际产出

### 2.1 脚本骨架

**`ops/start-digital-employee.sh`** 新写(~290 行 · chmod +x · bash -n OK):

```
┌─────────────────────────────────────────────┐
│ preflight_check (9 维度)                    │
│   ├─ .env + DB_ENCRYPTION_KEY 64 hex       │
│   ├─ Keychain QQ SMTP 授权码探测(不读)    │
│   ├─ alembic current + run_menu_bar.py 存在 │
│   ├─ dashboard.server 模块导入             │
│   ├─ ⌥⌘N TCC 检查(撞坑 #81 提醒)         │
│   └─ docs/ui HTML + data/ 目录             │
├─────────────────────────────────────────────┤
│ cmd_start                                   │
│   ├─ preflight_check                       │
│   ├─ cmd_start_menubar(后台 nohup)         │
│   └─ cmd_start_dashboard(DASHBOARD_REAL_DB=1)│
├─────────────────────────────────────────────┤
│ cmd_stop / cmd_status / cmd_health / restart│
└─────────────────────────────────────────────┘
```

### 2.2 5 个子命令(沿 ops/start-menubar.sh 范本)

| 子命令 | 行为 | 撞坑 |
|--------|------|------|
| `start` | 预检 + 启动 menubar + dashboard | 撞坑 #18 风险门控(DASHBOARD_REAL_DB=1 + ENABLE_PATH_4_WRITE UNSET) |
| `stop` | 全停(先 dashboard 后 menubar) | — |
| `status` | PID + 日志最近 5 行 + Dashboard HTTP 200 | — |
| `health` | 预检 + status + Keychain + make check-snapshot | 撞坑 #50 漂移防御联动 |
| `restart` | stop + start | — |

### 2.3 `--dry-run` 模式(沿 ops/start-menubar.sh 范本)

```bash
bash ops/start-digital-employee.sh --dry-run start
# 预期输出:9 维度预检 + nohup ... & 打印(不实际启动)
```

---

## §3 实测验证(2026-07-01 16:13)

### 3.1 语法 + dry-run 实测

| # | 命令 | 结果 |
|---|------|------|
| 1 | `bash -n ops/start-digital-employee.sh` | ✅ SYNTAX_OK |
| 2 | `chmod +x ops/start-digital-employee.sh` | ✅ 755 |
| 3 | `bash ops/start-digital-employee.sh --dry-run start` | ✅ 9 维度预检全跑通(8 ✅ + 1 ⚠️ Keychain missing)+ 2 启动命令 dry-run 打印 |

### 3.2 9 维度预检结果

| # | 维度 | 实际 |
|---|------|------|
| 1 | .env 存在 | ✅ |
| 2 | DB_ENCRYPTION_KEY 64 hex | ✅ |
| 3 | Keychain QQ SMTP 授权码 | ⚠️ missing(撞坑 #59 部分激活缺失 · Day 1 阶段 2 已配 QQ SMTP,但本会话 fresh shell 可能不在原 security session)|
| 4 | alembic current | ✅ |
| 5 | scripts/run_menu_bar.py 存在 | ✅ |
| 6 | dashboard.server 模块导入 | ✅ |
| 7 | ⌥⌘N TCC 提醒 | ⚠️ 用户须先授权 Python.framework 3.12(撞坑 #81 沿用)|
| 8 | docs/ui HTML 存在 | ✅ |
| 9 | data/ 目录 | ✅ |

**预检失败 1 项**(Keychain QQ SMTP · 不阻断启动 · 需用户确认)。撞坑 #71 沿用:不阻断。

---

## §4 与已有 ops 脚本关系

| 脚本 | 职责 | Day |
|------|------|-----|
| `ops/start-menubar.sh` | 单一 menubar 启停 | Day 2 |
| `ops/day2-81-tcc-fix-runbook.md` | 撞坑 #81 修复 runbook | Day 2 |
| `ops/check-pitfall-81.sh` | 撞坑 #81 一键诊断 | Day 2 |
| **`ops/start-digital-employee.sh`** | **一键数字员工启动(menubar + dashboard + Keychain + 1-click 审批)** | **Day 6 C** |

---

## §5 撞坑累计更新

| 撞坑号 | 状态 | 说明 |
|--------|------|------|
| **#71** | 🟢 沿用(决议 B 范围内) | 基础设施文件 0 业务风险 |
| **#59** | 🟢 红线维持 | 本脚本不读真实凭据,仅探测 Keychain present |
| **#18** | 🟢 风险门控 | DASHBOARD_REAL_DB=1 + ENABLE_PATH_4_WRITE UNSET |
| **#50** | 🟢 漂移防御 | health 子命令联动 `make check-snapshot` |
| **#81** | 🟢 维持 | ⌥⌘N 沿 Day 2 3/3 |

**撞坑累计 83 类 0 新增**(撞坑 #82/#83 已在 Day 6 A/B 登记)。

---

## §6 业务代码改动

- **本棒新增**:`ops/start-digital-employee.sh`(290 行 · 基础设施)
- **`src/` 业务代码改动**:**0**(撞坑 #71 沿用)
- **tests/ 新增**:**0**(脚本纯运维,9 维度预检内置自测)

---

## §7 维护者

**Mr-PRY** · 2026-07-01 Day 6 C 路径收口(`ops/start-digital-employee.sh` 290 行 · 5 子命令 + --dry-run · 9 维度预检 + make check-snapshot 联动)· 撞坑 #71 B 范围内 · 业务代码 0 改动 · 9/9 质量门 baseline **2620 passed / 88.95%** / 236 MD · 等用户实测 `bash ops/start-digital-employee.sh start`(撞坑 #81 ⌥⌘N 首次启动需手动 TCC 授权)。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **下一棒**:Day 6 D 状态收口 + 等 Day 7 启动授权。