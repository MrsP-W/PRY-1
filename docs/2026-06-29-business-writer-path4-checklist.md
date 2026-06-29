# C3 · BusinessWriter 路径 4 实施 checklist(2026-06-29)

> **目的**:沿 v0.2.53.33 BusinessWriter 路径 4 串联稿,产出 8/1 后独立 launch 的实施 checklist(不实施,仅 docs-only 预制)
> **范围**:docs-only · 不创建新文件 / 不实施 / 不打 tag
> **撞坑累计**:**70 类沿用**(本棒无新增)
> **沿用**:`docs/v0.2.53.21-24-business-writer-extension-2026-06-26.md` + `docs/v0.2.53.33` 串联稿 + 撞坑 #18 风险门控

---

## 1. 路径 4 设计稿回顾(沿 v0.2.53.33)

### 1.1 路径 4 定义

| 维度 | 路径 4 内容 |
|------|-------------|
| **触发条件** | 8 路径决策矩阵中 `outcome=dry_run_ready` 且 `would_allow=true` 且 **用户明确授权 + dry_run=False** |
| **动作** | 实际写入 BusinessWriter(不再 raise) |
| **写入位置** | `docs/` + `reports/` + `output/` 3 目录 |
| **写入约束** | 路径白名单 + `..` 穿越防御 + 8KB 截断 + 路径 4 设计稿就绪 |
| **撞坑** | 撞坑 #18 风险门控 + 撞坑 #50 衍生第三版 + 撞坑 #64 公共 API 范本 |

### 1.2 路径 4 与路径 1-3 关系

| 路径 | outcome | 行为 | 撞坑风险 |
|------|---------|------|----------|
| 路径 1 | disabled | 全 Stub | 🟢 零 |
| 路径 2 | disabled | 全 Stub | 🟢 零 |
| 路径 3 | disabled | 全 Stub | 🟢 零 |
| 路径 3.5 | writer_required | 部分启用 | 🟡 中 |
| 路径 4 | dry_run_ready | 实际写入 | 🟡 中(需授权)|
| 路径 4.5 | rejected | 写入拒绝 | 🟢 零 |
| 路径 5 | rejected | 写入拒绝 | 🟢 零 |
| 路径 8 | dry_run_ready | would_allow=true | 🟡 中 |

---

## 2. 实施 checklist(8/1 后独立 launch · 不在本棒做)

### 2.1 前置条件(8 项)

- [ ] **条件 1**:8/1 readiness 9/9 项满足(沿 v0.2.47 §5 + v0.2.53.36 §6.2)
- [ ] **条件 2**:撞坑 #68 衍生 5 项已 7/1 评估(沿 `monthly-review-decision-2026-07-01.md`)
- [ ] **条件 3**:撞坑 #69 / #70 SOP 已 7/1 落地(沿 `docs/v0.2.X.Y-type-ignore-sop.md`)
- [ ] **条件 4**:ApprovalGateAudit ORM 已创建(0016 alembic migration)
- [ ] **条件 5**:`BusinessWriterImpl` 默认 raise 已改为实际写入(撞坑 #18 风险门控 + 沿 v0.2.53.21)
- [ ] **条件 6**:`_merge_writer_dry_run` 双门 + dry_run=True 才合并(沿 v0.2.53.21)
- [ ] **条件 7**:HTML 三门面板 + 3 badge + 4 outcome 颜色 已沿 v0.2.53.26 + v0.2.53.29 落地
- [ ] **条件 8**:`BUSINESS_WRITER_ENABLED=1` env 门控已沿 v0.2.53.27 + v0.2.53.29 落地

### 2.2 实施步骤(8/1 后独立 launch)

| 步骤 | 动作 | 预估 | 撞坑风险 |
|------|------|------|----------|
| **步骤 1** | 创建 0016 alembic migration(ApprovalGateAudit 表)| 1h | 🟡 撞坑 #audit-2026(新增)|
| **步骤 2** | 实施路径 4 实写(`BusinessWriterImpl` 改 raise → 实际写入)| 4h | 🟡 撞坑 #writer-write-2026 |
| **步骤 3** | 修改 `_merge_writer_dry_run` 接受 `dry_run=False`(沿 #18 风险门控)| 2h | 🟡 |
| **步骤 4** | 路径白名单 + `..` 防御(沿 v0.2.53.10)| 1h | 🟢 |
| **步骤 5** | 8KB 截断(沿 v0.2.53.10 报告预览)| 30 min | 🟢 |
| **步骤 6** | HTML 三门面板 + 3 badge 更新(路径 4 实写模式)| 2h | 🟡 |
| **步骤 7** | 100 封 path-4 spike(类比 D5.6.5 SMTP spike)| 4h | 🟡 撞坑 #spike-write-2026 |
| **步骤 8** | docs-only 收口 + 跨项目 memory 沉淀 | 2h | 🟢 |
| **总耗时** | 约 **17h**(2-3 天)| — | — |

### 2.3 docs-only 收口动作

- [ ] `docs/v0.2.X.Y-business-writer-path4-launch.md`(新文件)
- [ ] `docs/v0.2-launch-plan.md` P0 checklist 补勾
- [ ] `README.md` / `SESSION-STATE.md` / `MODIFICATION-LOG.md` 三入口同步
- [ ] Agent Assistant 跨项目 memory 沉淀(`L2_memory/_cross-project/v0.2.X.Y-business-writer-path4.md`)

---

## 3. 撞坑 #18 风险门控(实施路径 4 必走)

### 3.1 必须满足的条件

- ✅ 9 质量门全绿
- ✅ 工作区干净
- ✅ `v0.1.0` tag 锚定 `2af775f` 不动
- ✅ `v0.2.1` 正式 tag 未误打
- ✅ **用户明确授权**(撞坑 #18 风险门控 · 必填)

### 3.2 4 重防误发(类比 D5.6.5 SMTP spike)

| 重 | 防误发机制 |
|----|-----------|
| **第 1 重** | `BUSINESS_WRITER_ENABLED=1` env 门控 + 白名单路径 |
| **第 2 重** | `dry_run=True` 才返回 would_allow,实际写入必须 dry_run=False |
| **第 3 重** | ApprovalGateAudit ORM 落档(每条实际写入都有审计记录)|
| **第 4 重** | `write_executed` 字段从恒 False 改为可 True(沿 v0.2.53.11 不变式打破,需 8/1 后独立 commit)|

### 3.3 实施失败回滚

- 任何步骤失败 → 立即回滚到 `v0.2.53.42` 状态(沿 `73552a3` HEAD)
- 不留半截路径 4 状态
- docs-only 收口记录失败原因

---

## 4. 沿用边界(本棒 C3 严格遵守 · 不在本棒做)

- ❌ **不创建 0016 alembic migration**(8/1 后)
- ❌ **不创建 ApprovalGateAudit ORM**(8/1 后)
- ❌ **不实施路径 4 实写**(8/1 后独立 launch)
- ❌ **不修改 approval_gate handler / HTML / 业务逻辑**
- ❌ **不修改 BusinessWriterImpl(仍保持 raise)**
- ❌ **不打 `v0.2.x` tag**
- ❌ **不动 `v0.1.0` tag**(`2af775f` 锚定)
- ❌ **不前进 `quality_snapshot.py`**
- ✅ docs-only 全部(checklist)
- ✅ 撞坑累计 70 类沿用
- ✅ write_executed 恒 False 不变式(沿 v0.2.53.11)

---

## 5. 沿用案例(8/1 后参照)

- **撞坑 #18 风险门控**:v0.2.47 6/25 决策 + v0.2.53.36 6/26 决策 + v0.2.53.42 6/29 决策(本棒三次沿用)
- **撞坑 #50 衍生第三版**:v0.2.53.39 6/28 + v0.2.53.40 6/29 + v0.2.53.41 6/29(三次沿用)
- **撞坑 #64 公共 API 范本**:v0.2.52.3 6/25(沿用)
- **撞坑 #65 opt-in 4 阶段**:v0.2.53.7 6/25 + v0.2.53.27 6/26(两次沿用)
- **撞坑 #68 决策矩阵与可视化拆分模式**:v0.2.53.29 6/26(沿用)

---

**commit 主题**:`docs(C3): BusinessWriter 路径 4 实施 checklist(8 项前置条件 + 8 步骤 + 4 重防误发)(docs-only · 不实施)`
**撞坑累计**:**70 类沿用**(本棒无新增)
**status**:🟢 ready · 8/1 后独立 launch 启动前必读