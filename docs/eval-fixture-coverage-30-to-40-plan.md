# 评测样本 30→40 覆盖矩阵规划 — D6.18.1 起草稿(2026-08-05)

> **范围声明(优先于正文)**:本文为**选题维度 + 覆盖矩阵规划** docs,**不落 JSON fixture 文件**;`业务代码改动 = 0`,不影响运行时、不修改现有 30 条、不动 `ENABLE_*`。
> **承接**:本文是 `docs/eval-fixture-coverage-15-to-30-plan.md` 的下一棒;两文都属于 D6.18.1「30+ 样本 2 轮扩」计划项的 docs-only 拆解,本文只覆盖「30→40」第一轮扩样,**第二轮 40→50 待评估后再另起计划**。
> **前置 baseline**:`main@2f698802`;30 条 fixture 在当前 schema/privacy/ID guards 下 `129 passed`(`TASK-20260804-001` + `TASK-20260804-002` 集成后)。

---

## 1. 现有 30 样本分布(`main@2f698802`)

| Suite | 数量 | 文件清单(摘 5) |
|-------|------|---------------|
| `email_classify` | 13 | `001_todo_reconcile` / `002_system_sender_spam` / `003_meeting_followup` / `005_newsletter_promo` / `006_invoice_payment_request` |
| `email_draft` | 9 | `001_meeting_confirm` / `002_apology_late_reply` / `003_spam_should_be_blocked` / `004_invoice_query_polite` / `005_vendor_schedule` |
| `sap_troubleshoot` | 8 | `001_fb01_auth` / `002_fi12_bank_change` / `003_fb60_posting_block` / `004_tax_code_missing` / `005_period_closed` |
| **总计** | **30** | — |

### 1.1 现有覆盖维度 vs 15→30 扩样补齐度

| 维度 | 15 样本时 | 30 样本后(本基线) | 剩余缺口 |
|------|----------|-------------------|---------|
| 中英混排 | 部分 | 显著改善(新增英文夹杂 5+ 条) | 纯英文商务邮件 |
| 业务意图 | 8 类 / 4 tone / 3 事务码 | 13 类 / 9 tone / 8 事务码 | 跨模块联合、错误码枚举 |
| 边界/对抗 | 钓鱼 + 系统发件人 + 营销 | + 银行变更 + 过账阻塞 + tax 缺失 + period 关闭 | 混淆 spam/phishing 边界 |
| 附件/PII | 无 | 仅 `002_system_sender_spam` 提及附件线索 | 显式附件场景、自报 PII |
| 多轮/上下文 | 单封独立 | 同上(15→30 未补) | `Re:` 链、跨封上下文决策 |

> **结论**:15→30 主要在「意图边界 + 业务广度」上扩展,30→40 应聚焦「英语真实业务邮件 + 显式附件/PII + 跨上下文」三块仍薄弱的维度。

---

## 2. +10 选题维度(分 2 轮,每轮 5 条)

### 2.1 总体配比

| Suite | 30 现有 | +10 增量 | 目标 40 | 增量主题 |
|-------|---------|----------|---------|----------|
| `email_classify` | 13 | +4 | 17 | 纯英文商务 / 附件线索 / Re: 链 / 对抗混淆 |
| `email_draft` | 9 | +3 | 12 | 英语回复 / tone 边界(道歉+催办)/ 附件说明回复 |
| `sap_troubleshoot` | 8 | +3 | 11 | 错误码 M 段 / 跨模块(FB60+FBL5N)/ 权限/角色报头 |
| **总计** | **30** | **+10** | **40** | — |

### 2.2 轮 1(5 条,预计 8/8 落)主题

| # | Suite | 主题 | 覆盖维度 |
|---|-------|------|----------|
| 1 | `email_classify` | 英文 invoice reminder + 附件 | 纯英文 + 附件线索 |
| 2 | `email_classify` | `Re: Fw:` 三层链 meeting reschedule | 多轮上下文 |
| 3 | `email_draft` | 英文 vendor delay apology | 英语 + 道歉 tone |
| 4 | `email_draft` | `Re:` invoice query with attachment note | 多轮 + 附件说明 |
| 5 | `sap_troubleshoot` | `M8 113` 科目错误 + 短转储文本 | 错误码 + 简短症状 |

### 2.3 轮 2(5 条,预计 8/15 落)主题

| # | Suite | 主题 | 覆盖维度 |
|---|-------|------|----------|
| 6 | `email_classify` | 看似紧急实为 phishing(伪 CEO + 付款) | 对抗混淆 |
| 7 | `email_classify` | 自报手机号 + 身份证后 6 位 | PII 风险 |
| 8 | `email_draft` | 催办 + 礼貌边界(中文) | tone 边界 |
| 9 | `sap_troubleshoot` | 跨模块:FB60 过账失败 + FBL5N 行项目对账建议 | 跨模块联合 |
| 10 | `sap_troubleshoot` | 权限报头 `no authorization for ...` 角色/权限缺失 | 权限场景 |

### 2.4 ID 前缀与命名规范(沿用 `TASK-20260804-003`)

- `email_classify`:`email_classify_0XX`(0XX 与 30 已有 + 1 起续编,首新增 = `014`)
- `email_draft`:`email_draft_0XX`(首新增 = `010`)
- `sap_troubleshoot`:`sap_troubleshoot_0XX`(首新增 = `009`)

### 2.5 与现有 guards 兼容性(预期)

- **保留域邮箱**:全部使用 `@example.com` / `@example.org` / `@example-test.cn` 之类保留域(`b019043` guard)。
- **连续 11+ 位数字**:身体、电话、卡号、凭证号均使用 ≤10 位或带分隔(` ` / `-`),触发 `b019043` 长数字 guard 失败 = 0。
- **suite 前缀 ID**:`TASK-20260804-003` guard 强制 `id` 以对应 `suite_` 开头,所有 +10 条遵循。
- **PII 处理**:自报手机号、身份证后 6 位等仍以「保留域 + 分隔符」表达,不写明真实数据;脱敏原则遵循 D6.14.1 + D6.15.2。

---

## 3. 节奏与契约

| 阶段 | 范围 | 验收命令 | 状态门槛 |
|------|------|----------|----------|
| 0(本计划) | docs-only 计划文档 + 任务包 | `markdownlint-cli2 docs/eval-fixture-coverage-30-to-40-plan.md`、`yaml.safe_load` 任务包 | 通过 |
| 1(轮 1) | tests-only 落地 5 条 fixture + 更新 `MODIFICATION-LOG.md` | `.venv/bin/python -m pytest tests/eval/test_eval_fixtures_schema.py -q` 全绿;`ruff check tests/eval` | ≥ 134 passed(30→35,新增 5*5=25 assertions) |
| 2(轮 2) | tests-only 再落地 5 条 fixture + 更新 `MODIFICATION-LOG.md` | 同上 | ≥ 139 passed(35→40,新增 5*5=25) |
| 3(复核) | docs-only 跑 readiness #5 候选门槛自评 | 30→40 验收报告 | ≥ 40 条全部通过 guards |

> **数量预估**:每条 fixture schema 测试约 5 assertions(字段、ID 前缀、suite、保留域、长数字);30→35 预计 +25、35→40 再 +25;`main@2f698802` 基线 `129 passed` → `139 passed`(以实际落地为准)。

---

## 4. 红线与不做事清单

- **不修改** 现有 30 条 fixture 的 ID / 字段 / suite;只新增。
- **不启用** 任何 `ENABLE_*`;不动 SLO active;不动 LaunchAgent。
- **不触碰** `src/`、`scripts/`、`.cursor/`、`plugins/`、`ops/` 下的运行时/配置。
- **不接入** 真实数据;全部合成 + 保留域脱敏。
- **不集成**到 `main`;每轮候选落在独立 worktree,经 docs-only review 后由用户单独批准 cherry-pick。
- **不提前** 起草第二轮(40→50)扩样计划,待 40→ 落地并经验证后再评估。

---

## 5. 验收(本计划阶段)

- `markdownlint-cli2 docs/eval-fixture-coverage-30-to-40-plan.md`:0 issues。
- `python -c "import yaml; yaml.safe_load(open('docs/agent-team/tasks/TASK-20260805-001-d6181-fixture-30-to-40-plan.yaml'))"`:解析通过。
- `git diff --check`:通过。
- 白名单严格 3 文件:`docs/eval-fixture-coverage-30-to-40-plan.md` + `docs/agent-team/tasks/TASK-20260805-001-d6181-fixture-30-to-40-plan.yaml` + `MODIFICATION-LOG.md`。
- 任务包 `status: ready_to_merge`;不进入 `done`,待用户批准后进入轮 1。

---

## 6. 后续动作(仅文本,本轮不做)

1. 用户批准 `TASK-20260805-001` 后,新建 `TASK-20260805-002-d6181-fixture-batch1.yaml` 启动轮 1 落地(5 条 fixture + tests-only 更新)。
2. 轮 1 通过后,新建 `TASK-20260805-003-d6181-fixture-batch2.yaml` 启动轮 2(5 条)。
3. 全部落地后再起 docs-only 复核任务,跑 readiness #5 候选门槛自评;**不发起 v1.1-A 解锁、不操作 push/merge**。
4. 第二轮扩样(40→50)待 40→ 经验证后另起计划;不在本文承诺。
