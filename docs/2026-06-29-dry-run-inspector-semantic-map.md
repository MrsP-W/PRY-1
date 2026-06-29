# C2 · HTML dry-run inspector 语义对照表(2026-06-29)

> **目的**:沿 v0.2.53.26 + v0.2.53.29 HTML dry-run inspector 字段 → 前端 badge 文案,产出后端 8 路径决策矩阵与前端 4 类 outcome 收敛对照表
> **范围**:docs-only · 不修改 HTML / 不修改 handler / 不接真实数据
> **撞坑累计**:**70 类沿用**(本棒无新增)
> **沿用**:`docs/v0.2.53.26-html-three-gate-2026-06-26.md` + `docs/v0.2.53.29-html-inspector-3-fields-2026-06-26.md` + 撞坑 #68 决策矩阵与可视化拆分模式

---

## 1. 后端 8 路径决策矩阵(沿 v0.2.53.22 + v0.2.53.26)

### 1.1 3 个 env 变量 + 1 个请求参数

| 变量 | 类型 | 含义 |
|------|------|------|
| `DASHBOARD_REAL_DB` | env var (str) | 真实 DB 启用(只读)|
| `BUSINESS_WRITER_ENABLED` | env var (str) | BusinessWriter 启用 |
| `dry_run` | request param (bool) | 实际 dry-run 模式 |

### 1.2 8 路径决策表

| 路径 | DB | Writer | dry_run | outcome | HTTP | would_allow | write_executed |
|------|----|--------|---------|---------|------|-------------|----------------|
| 1 | 0 | 0 | False | disabled | 200 | null | False |
| 2 | 0 | 0 | True | disabled | 200 | null | False |
| 3 | 0 | 1 | False | writer_required | 501 | null | False |
| 4 | 0 | 1 | True | writer_required | 501 | null | False |
| 5 | 1 | 0 | False | disabled | 200 | null | False |
| 6 | 1 | 0 | True | disabled | 200 | null | False |
| 7 | 1 | 1 | False | rejected | 200 | false | False |
| 8 | 1 | 1 | True | dry_run_ready | 200 | true | False |

**关键不变式**:
- ✅ `write_executed` 恒 False(路径 1-8)
- ✅ 8 路径 → 4 outcome 收敛(backend 定决策,frontend 定可视化)
- ✅ 4 outcome → 4 颜色映射(沿 v0.2.53.26)

---

## 2. 前端 4 outcome 收敛 + 3 badge(沿 v0.2.53.26 + v0.2.53.29)

### 2.1 4 outcome → 4 颜色 + 4 文案

| outcome | 颜色 | 文案 | would_allow |
|---------|------|------|-------------|
| **disabled** | 灰色(#999)| "全 Stub · 无 I/O" | null |
| **writer_required** | 黄色(#FFA500)| "Writer 启用 · DB 未启用 · 需先启 DB" | null |
| **rejected** | 红色(#DC3545)| "三门全开 · 非 dry-run · 实际写入拒绝" | false |
| **dry_run_ready** | 绿色(#28A745)| "三门全开 + dry-run · would_allow 可查" | true |

### 2.2 HTML inspector 3 badge(沿 v0.2.53.29)

| badge | 字段 | 渲染规则 | 颜色 |
|-------|------|----------|------|
| **env badge** | `business_writer_env_enabled` | value=true → 绿色 "ENV ON" / value=false → 灰色 "ENV OFF" | 绿/灰 |
| **Impl badge** | `business_writer_impl_injected` | value=true → 绿色 "Impl injected" / value=false → 灰色 "Impl missing" | 绿/灰 |
| **ready badge** | `business_writer_ready` | value=true → 绿色 "Ready" / value=false → 黄色 "Not ready" | 绿/黄 |

### 2.3 system 视图「审批门」card 4 项(沿 v0.2.53.26)

| 字段 | 说明 |
|------|------|
| `first_gate` | `DASHBOARD_REAL_DB` 状态 |
| `second_gate` | `BUSINESS_WRITER_ENABLED` 状态 |
| `third_gate` | `dry_run` 请求参数状态 |
| `outcome` | 4 类 outcome 之一 |

---

## 3. 后端 8 路径 ↔ 前端 4 outcome ↔ HTML 3 badge 收敛对照

### 3.1 总对照表

| 后端路径 | outcome | would_allow | HTML badge 1 | HTML badge 2 | HTML badge 3 |
|----------|---------|-------------|--------------|--------------|--------------|
| 1 | disabled | null | ENV OFF | Impl missing | Not ready |
| 2 | disabled | null | ENV OFF | Impl missing | Not ready |
| 3 | writer_required | null | ENV ON | Impl injected | Not ready |
| 4 | writer_required | null | ENV ON | Impl injected | Not ready |
| 5 | disabled | null | ENV OFF | Impl missing | Not ready |
| 6 | disabled | null | ENV OFF | Impl missing | Not ready |
| 7 | rejected | false | ENV ON | Impl injected | Not ready |
| 8 | dry_run_ready | true | ENV ON | Impl injected | Ready |

### 3.2 关键洞察(撞坑 #68 衍生)

- **后端 8 路径** → 决策矩阵,完全确定
- **前端 4 outcome** → 可视化收敛,4 类颜色
- **HTML 3 badge** → 字段级细节,沿 v0.2.53.29

**两层拆分模式**:backend 定 8 路径决策,frontend 收敛 4 outcome,避免双重真相源。

---

## 4. 沿用边界(本棒 C2 严格遵守)

- ❌ 不修改 HTML / handler / 业务逻辑
- ❌ 不接真实 BusinessWriter / SMTP / DB
- ❌ 不前进 `quality_snapshot.py`
- ❌ 不打 `v0.2.x` tag
- ❌ 不创建 0016 alembic migration / ApprovalGateAudit ORM
- ❌ 不实施路径 4 实写(8/1 后独立 launch)
- ✅ docs-only 全部(对照表)
- ✅ 撞坑累计 70 类沿用
- ✅ write_executed 恒 False 不变式

---

**commit 主题**:`docs(C2): HTML dry-run inspector 语义对照表(后端 8 路径 ↔ 前端 4 outcome ↔ HTML 3 badge 收敛)(docs-only)`
**撞坑累计**:**70 类沿用**(本棒无新增)
**status**:🟢 ready · 7/1 议程 8 撞坑 #68 衍生 5 项评估时引用