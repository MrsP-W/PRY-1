# Day 8 — 撞坑 #71 解除 · 业务代码改动日 启动准备(2026-07-01)

> **类型**:Day 8+ 启动 · 撞坑 #71 解除
> **模式**:docs-only 启动准备(等用户明确 Day 8 具体业务改动目标)
> **风险**:🟡 中(撞坑 #71 6 周+7 天 业务代码 0 改动首次解除 · 9/9 质量门 baseline 推进)
> **撞坑关联**:#71 解除(业务代码改动日)· #18 风险门控 · #59 红线维持 · #65 BusinessWriter + AuditContext 沿用 · #76/#78/#79 5 重门控沿用

---

## §1 用户决策(2026-07-01)

| 决策点 | 选择 | 含义 |
|--------|------|------|
| **Day 8 方向** | 撞坑 #71 解除 · 业务代码改动日 | 6 周+7 天 业务代码 0 改动 首次解除 |
| **候选业务改动** | 见 §2(4 候选)· 等用户选 1 个 | docs-only 启动准备 · 不立刻实施 |
| **撞坑 #59** | 🟢 红线维持 | outlook/gmail 仍不配置 · 业务改动不碰 SMTP 多账户 |
| **9/9 质量门** | 🟢 准备推进 | 业务改动必跑 9 门 · baseline 可能前进(2620 passed / 88.95% / 242 MD / 238 mypy)|

---

## §2 Day 8 业务改动 4 候选(用户决策点)

| 候选 | 风险 | 改动范围 | 撞坑关联 | 推荐度 |
|------|------|---------|---------|--------|
| **A. 1-click 审批 UI 化(推荐)** | 🟢 低 | `src/my_ai_employee/dashboard/server.py` approval-gate 端点 + `docs/ui/codex-style-dashboard.html` 1-click button | 撞坑 #59 红线维持(仍 1-click 手动)· 撞坑 #65 沿用(BusinessWriter) | ⭐⭐⭐ |
| **B. Dashboard 真实写路径** | 🟡 中 | `src/my_ai_employee/ai/business_writer.py` + dashboard 写端点 | 撞坑 #18 风险门控(ENABLE_PATH_4_WRITE=1)· 撞坑 #65 沿用 | ⭐⭐ |
| **C. 移动伴侣 API 设计** | 🟡 中 | `src/my_ai_employee/api/`(新模块)+ D5+ 接口 | 撞坑 #71 第一次新模块 · docs 先行 | ⭐ |
| **D. Notes 加密增强** | 🟢 低 | `src/my_ai_employee/core/notes_encryption.py`(新模块)| 撞坑 #64 SHA-256 沿用 + 字段级加密扩展 | ⭐ |

---

## §3 推荐候选 A(1-click 审批 UI 化)详细方案

### 3.1 现状

- **Day 3 C 路径**:`scripts/send_one_qq_email.py` 真发 1 封(撞坑 #76/#78/#79 5 重门控全开)
- **Day 6 C 路径**:`ops/start-digital-employee.sh` 一键启动包含「1-click 审批入口」(`http://127.0.0.1:8765/api/approval-gate/audits`)
- **撞坑 #65**:`BusinessWriter Protocol + Stub + AuditContext + WriteResult/Decision` 已就位(6/26 落地)
- **Dashboard API**:`src/my_ai_employee/dashboard/server.py` 有只读 approval-gate 端点(`/api/approval-gate/audits`)

### 3.2 Day 8 目标

把「1-click 审批」从**单文件 CLI**(Day 3 范本)**升级**为**Dashboard UI 化 + 端点**:
1. **新增 POST 端点**:`/api/approval-gate/decide` 接受 `{audit_id, action: "approve"|"reject", actor, reason}` 提交审批决定
2. **AuditContext 写入**:调用 `BusinessWriter.decide()` 把审批决定落到 `outbox_audits` 表(撞坑 #65 沿用)
3. **5 重门控沿用**:`ENABLE_PATH_4_WRITE=1` + `actor ≤ 80` + `reason ≤ 240` + `actor 必填` + `decision 必填` 严判
4. **Dashboard HTML**:`docs/ui/codex-style-dashboard.html` 新增 1-click 按钮 + 审批结果 toast
5. **撞坑 #59 红线维持**:**仍 1-click 手动**,Dashboard 不自动真发邮件,需要用户在 UI 上点击"批准"按钮

### 3.3 业务代码改动范围(估算)

| 文件 | 类型 | 估算行数 | 改动 |
|------|------|---------|------|
| `src/my_ai_employee/dashboard/server.py` | 改 | +60-80 | 新增 POST 端点 + 调用 BusinessWriter |
| `src/my_ai_employee/dashboard/templates/dashboard.html` 或 `docs/ui/codex-style-dashboard.html` | 改 | +30-50 | 1-click 按钮 + 审批 toast |
| `tests/dashboard/test_approval_gate_decide.py` | 新 | +80-100 | 5 重门控 + 撞坑 #65 AuditContext 写测试 |
| 业务代码小计 | — | +90-130 行 | 撞坑 #71 解除 |
| 测试代码小计 | — | +80-100 行 | 9/9 质量门 baseline 前进 |

### 3.4 9/9 质量门推进预期

| # | 门 | Day 8 预期 |
|---|----|-----------|
| 1 | pytest | 2620 → **2700+ passed**(+5-8 tests) |
| 2 | ruff check | 全绿 |
| 3 | ruff format | 全绿 |
| 4 | mypy src | 0 errors / 238 files |
| 5 | mypy src+tests | 0 errors(撞坑 #31 沿用 · 0 errors 已清零)|
| 6 | alembic --sql | exit 0 · 可能有新表 `outbox_audits` DDL(撞坑 #65 沿用) |
| 7 | uv build | OK |
| 8 | MD lint | 242 → **244 MD files**(+Day 8 收口 docs + 启动准备 doc) |
| 9 | coverage | 88.95% → **89.0%+**(dashboard 端点测试覆盖) |

### 3.5 撞坑关联

| 撞坑 | 状态 | 说明 |
|------|------|------|
| **#71** | 🟢 **解除** | 业务代码首次改动(撞坑 #71 决议 B 范围 沿用 6 周+7 天后解除) |
| **#18** | 🟢 风险门控沿用 | ENABLE_PATH_4_WRITE 维持 UNSET · 5 重门控替代 |
| **#59** | 🟢 红线维持 | outlook/gmail 仍不配置 · 1-click 不自动真发 |
| **#65** | 🟢 沿用 | BusinessWriter + AuditContext + WriteResult/Decision |
| **#76/#78/#79** | 🟢 沿用 | 5 重门控 + actor 80/reason 240 严判 + --count=1 |
| **#50** | 🟢 漂移防御 | MD count 推进 → 6 文件同步 |

---

## §4 其他 3 候选简要说明

### 4.1 候选 B(Dashboard 真实写路径)

- **改动**:`ENABLE_PATH_4_WRITE=1` + `BusinessWriter` 真链路 + audit log
- **风险**:🟡 中(撞坑 #18 风险门控 + 5 重门控)
- **撞坑关联**:撞坑 #65 沿用 · 撞坑 #18 反转(需要用户明确)
- **推荐度**:⭐⭐(风险比 A 高,改动比 A 大)

### 4.2 候选 C(移动伴侣 API 设计)

- **改动**:`src/my_ai_employee/api/`(新模块)+ D5+ 接口设计
- **风险**:🟡 中(新模块 + 接口契约)
- **撞坑关联**:撞坑 #71 第一次新模块 · docs 先行(纯设计)
- **推荐度**:⭐(Day 8 不适合大改,适合 C 后 Day 9+)

### 4.3 候选 D(Notes 加密增强)

- **改动**:`src/my_ai_employee/core/notes_encryption.py`(新模块)+ 字段级加密
- **风险**:🟢 低(增量新模块)
- **撞坑关联**:撞坑 #64 SHA-256 沿用 + 字段级加密扩展
- **推荐度**:⭐(Day 8 也可以做,但 A 更直接对应 Day 3 C 路径演进)

---

## §5 Day 8 实施步骤(沿 D-step 标准 6 步 · 候选 A 范本)

```
Step 1: @调试专家(如无阻塞跳过)
  ↓
Step 2: 实施(dashboard POST 端点 + BusinessWriter 接入 + HTML 1-click button)
  + 跑 9/9 质量门(预期 baseline 前进)
  ↓
Step 3: @检查员 复核 9/9 质量门 + 撞坑 #59 红线检查
  ↓
Step 4: @教练员 沉淀 1 条 Claude Code 技巧到 memory/(Day 8 命名)
  ↓
Step 5: @回顾员 写复盘(Day 8 撞坑 #71 解除意义 + Day 9+ 预判)
  ↓
Step 6: 提交 commit + push(2-3 commits:业务代码 + 收口 docs)
```

---

## §6 业务代码改动(撞坑 #71 解除)

| 维度 | Day 1-7 累计 | Day 8 候选 A 预期 |
|------|------------|-----------------|
| **`src/` 业务代码** | 0 改动(撞坑 #71 沿用 6 周+7 天)| +90-130 行(撞坑 #71 解除)|
| **`scripts/` 业务辅助** | 1 新文件 `import_real_gate.py` | 0 |
| **`scripts/` 业务改动** | `monthly_report.py` / `import_wechat.py` / `import_alipay.py` | 0 |
| **`docs/`** | 18+ D-step 收口 + Day 1-7 报告 | +Day 8 收口 docs + 启动准备 doc |
| **`tests/` 新测试** | +9(Day 6 前 P0/P1)| +5-8(Day 8 dashboard 端点) |

**撞坑 #71 解除信号**:`src/` 业务代码首次出现 `+` 改动(沿 git diff --stat 统计)。

---

## §7 维护者

**Mr-PRY** · 2026-07-01 Day 8 启动准备 docs-only · 撞坑 #71 解除 · 业务代码改动日 · 4 候选(1-click 审批 UI 化 / Dashboard 真实写路径 / 移动伴侣 API / Notes 加密增强)· 推荐候选 A(🟢 低风险 · 沿 Day 3 C 路径 + Day 6 C 启动包 + 撞坑 #65 沿用)· 等用户明确 Day 8 具体目标 → 实施。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **下一棒**:用户决策 Day 8 候选 → 实施候选 A 或其他 → 9/9 质量门 baseline 推进。

---

## §8 决策待办

| 序号 | 决策点 | 选项 | 默认 |
|------|--------|------|------|
| 1 | Day 8 业务改动候选 | A / B / C / D | A(推荐)|
| 2 | 撞坑 #18 是否反转(候选 B 需要)| YES / NO | NO(维持 UNSET)|
| 3 | 撞坑 #71 解除时间点 | Day 8 / Day 9+ | Day 8(用户已决议) |
| 4 | 9/9 质量门 baseline 前进策略 | 全推进 / 选推 pytest+MD | 全推进 |
