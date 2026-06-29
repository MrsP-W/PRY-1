# C1 · ApprovalGate 三门文案 docs 清理(2026-06-29)

> **目的**:沿 v0.2.53.21-29 ApprovalGate 三门系列,集中清理文案表述,统一术语
> **范围**:docs-only,不动 handler / 不动 HTML / 不接真实数据
> **撞坑累计**:**70 类沿用**(本棒无新增)
> **沿用**:`docs/v0.2.53.21-24` 8 路径决策矩阵 + `docs/v0.2.53.26` 三门结果展示 + `docs/v0.2.53.29` inspector 3 fields

---

## 1. 三门设计(沿 v0.2.53.22 + v0.2.53.26 + v0.2.53.29 锚定)

### 1.1 三门定义

| 门 | env var | 含义 | 缺失时行为 |
|----|---------|------|------------|
| **第一门** | `DASHBOARD_REAL_DB=1` | 真实 DB 启用(只读) | 走 Stub 默认 |
| **第二门** | `BUSINESS_WRITER_ENABLED=1` | BusinessWriter 启用 | 走 Stub 默认 |
| **第三门** | `dry_run=True`(请求参数)| 实际 dry-run 模式(无写入) | 走审批拒绝 |

### 1.2 三门组合 → 8 路径决策矩阵(沿 v0.2.53.22 + v0.2.53.26)

| DB | Writer | dry_run | outcome | HTTP | 行为 |
|----|--------|---------|---------|------|------|
| 0 | 0 | False | **disabled** | 200 OK | 全 Stub,dry-run 不允许 |
| 0 | 0 | True | **disabled** | 200 OK | 全 Stub,dry-run 不生效 |
| 0 | 1 | False | **writer_required** | 501 | Writer 启用但 DB 未启用,需先启 DB |
| 0 | 1 | True | **writer_required** | 501 | Writer 启用但 DB 未启用,dry-run 仍不生效 |
| 1 | 0 | False | **disabled** | 200 OK | DB 启用但 Writer 未启用 |
| 1 | 0 | True | **disabled** | 200 OK | DB 启用但 Writer 未启用,dry-run 不生效 |
| 1 | 1 | False | **rejected** | 200 OK | 三门全开但非 dry-run,实际写入拒绝 |
| 1 | 1 | True | **dry_run_ready** | 200 OK | 三门全开 + dry-run,允许查看 would_allow |

### 1.3 4 类 outcome(沿 v0.2.53.26 收敛)

- **disabled** = 全 Stub,无 I/O
- **writer_required** = Writer 启用但 DB 未启用
- **rejected** = 三门全开但非 dry-run
- **dry_run_ready** = 三门全开 + dry-run,允许 would_allow

---

## 2. 文案术语统一表(7/1 议程 3 评估后更新到 docs/)

### 2.1 第一门文案

| 旧表述 | 新表述(7/1 标准化)|
|--------|---------------------|
| "DB 已连接" | "**真实 DB 启用 · DASHBOARD_REAL_DB=1**" |
| "API 已连接 · 5 端点" | "**Dashboard API 已连接 · 5 端点 · DB 默认 Stub · 真实 DB 需 env 门控**" |
| "DB 缺失" | "**真实 DB 未启用 · 默认 Stub · 无 I/O**" |

### 2.2 第二门文案

| 旧表述 | 新表述(7/1 标准化)|
|--------|---------------------|
| "Writer 已注入" | "**BusinessWriter 启用 · BUSINESS_WRITER_ENABLED=1**" |
| "Impl 已构造" | "**BusinessWriterImpl 已注入 · 默认 raise · 不实写**" |
| "ready" | "**三门全开 · dry_run=True · would_allow 可查**" |

### 2.3 第三门文案

| 旧表述 | 新表述(7/1 标准化)|
|--------|---------------------|
| "dry-run 模式" | "**dry_run=True · 实际写入拒绝 · 仅 would_allow 字段返回**" |
| "审批通过" | "**三门 + dry_run=True · would_allow=true · write_executed 恒 False**" |
| "审批拒绝" | "**三门未全开 或 dry_run=False · would_allow=false · 不进入写入路径**" |

### 2.4 HTML inspector 三 badge 文案(沿 v0.2.53.29)

| badge | 文案(7/1 标准化)| 字段 |
|-------|-------------------|------|
| **env badge** | "ENV: BUSINESS_WRITER_ENABLED={value}" | `business_writer_env_enabled` |
| **Impl badge** | "Impl: {injected or missing}" | `business_writer_impl_injected` |
| **ready badge** | "Ready: {ready or not_ready}" | `business_writer_ready` |

---

## 3. 撞坑 #50 衍生文案一致性(沿 v0.2.53.40 + v0.2.53.41 范本)

- ✅ docs/ 与 实测 一致(沿撞坑 #50 衍生第三版)
- ✅ docs/ 与 quality_snapshot.py L18 claim 88.78% 一致
- ✅ docs/ 与 9 质量门实测值 一致
- ❌ 不写"待落档"类描述(撞坑 #50 衍生第三版教训)
- ❌ 不写"estimated"类描述(撞坑 #58 范本)

---

## 4. 沿用边界(本棒 C1 严格遵守)

- ❌ 不修改 approval_gate handler / HTML / 业务逻辑
- ❌ 不接真实 BusinessWriter / SMTP / DB
- ❌ 不前进 `quality_snapshot.py`
- ❌ 不打 `v0.2.x` tag
- ❌ 不创建 0016 alembic migration / ApprovalGateAudit ORM
- ✅ docs-only 全部(文案统一表)
- ✅ 撞坑累计 70 类沿用
- ✅ write_executed 恒 False 不变式

---

**commit 主题**:`docs(C1): ApprovalGate 三门文案统一表(7/1 标准化文案 · 不动 handler/HTML)(docs-only)`
**撞坑累计**:**70 类沿用**(本棒无新增)
**status**:🟢 ready · 7/1 议程 3 评估后批量更新到对应 docs/