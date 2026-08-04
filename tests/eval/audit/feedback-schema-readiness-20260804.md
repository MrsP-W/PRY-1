# D6.15.2 Feedback Schema 设计契约 只读 Readiness 审计（2026-08-04）

> **范围声明**：本文只读审计候选分支 `claude/d6152-feedback-schema-20260803`（HEAD `688e22d`，
> `9f74797 + 688e22d`）的 `docs/v1.1-feedback-schema.md` 设计契约（design-only，2026-08-03）。
> **不修改候选原文**，**不实施落库/采集器/UI/摘要密钥**，**不读写真实数据**。

## 1. 审计基线

- main `7b6c0c1`（30-fixture guards + SLO chain + Feature Flag 只读审计 已集成 · ahead origin/main 6 · 13 项用户 WIP 完整）
- 候选基线：`566c1a8`；候选相对当前 main 多 3 文件（315 insertions）：`MODIFICATION-LOG.md`、`docs/agent-team/tasks/TASK-20260803-009-d6152-feedback-schema.yaml`、`docs/v1.1-feedback-schema.md`
- v1.1-A readiness：`2 PASS / 2 FAIL`（30-fixture + SLO design docs 集成 PASS；7d/30d + Feature Flag design 集成 FAIL）
- 候选文档位置：候选分支 `claude/d6152-feedback-schema-20260803`，未集成到 main

## 2. 结构完整性

| 节 | 标题 | 完整性 |
|----|------|--------|
| 1 | 结论 | ✅ 四态总览 |
| 2 | 目标与非目标 | ✅ 5 目标 + 5 非目标 |
| 3 | 四态语义 | ✅ 4 态表 + reason code 白名单 |
| 4 | `feedback_event` 最小 schema | ✅ 字段表 + diff_summary 白名单 |
| 5 | 摘要与隐私边界 | ✅ HMAC-SHA256 + 禁止内容清单 |
| 6 | 未来落库契约（不在 P3 实现） | ✅ 追加式 + 幂等 + 纠错 + fail-closed |
| 7 | 反馈到离线评测的闭环 | ✅ 9 步流程 + 4 状态机 |
| 8 | 聚合口径 | ✅ 6 指标 + 空分母规则 |
| 9 | P3、Feature Flag 与安全门 | ✅ 优先级 + 5 红线 |
| 10 | 版本与后续可测验收 | ✅ v1 版本 + 8 验收点 |
| 11 | 本任务验收清单 | ✅ 11/11 勾选 |

**结构结论**：11 节完整、四态 schema 闭环自洽、验收 11/11 勾选；无结构性缺口。

## 3. 四态语义核对（核心）

| label | 用户语义 | `before_hash` | `after_hash` | `diff_summary` | `reason_code` |
|-------|---------|--------------|-------------|---------------|--------------|
| `adopt` | 原样采纳 | 必填 | 禁止 | 禁止 | 可选 |
| `modify` | 修改后使用 | 必填 | 必填且 ≠ before | 必填 | 可选 |
| `reject` | 拒绝/未使用 | 必填 | 禁止 | 禁止 | 必填（含 `unspecified`） |
| `unknown` | 历史未标注 | 必填 | 禁止 | 禁止 | 必填（4 个 unknown reason） |

**关键约束验证**：
- ✅ `unknown` 不是异常兜底；malformed 整条拒绝，不修补成 `unknown`
- ✅ `modify` 必须有 `after_hash ≠ before_hash`，杜绝 trivial 修改
- ✅ `reject.unspecified` 是显式 reason code，不是字段缺失
- ✅ reason code 白名单锁定 19 个枚举（4+6+6+4 = 20 个含 null），未来扩展必须升 schema 版本
- ✅ 自由文本原因不进入事件（拒绝运行时临时放行）

## 4. 隐私边界核对

§5 禁止进入事件/日志/任务包/fixture 的内容清单：

| 类别 | 禁止内容 |
|------|---------|
| 通讯 | 邮箱地址、收件人、主题、正文、签名、附件 |
| 业务 | Notes 标题/正文、SAP 客户/供应商/公司代码/凭证号、财务明细 |
| 身份 | 姓名、手机号、证件号、银行卡号 |
| 系统 | 内部主机名、绝对私有路径 |
| 凭据 | API key、密码、Token、Cookie、OAuth、证书、错误原文 |
| AI | 原始 prompt、模型完整响应、用户自由文本原因、可逆 diff |

**隐私结论**：6 类禁止清单完整覆盖撞坑 #1/#18/#65/#71/#76/#78/#79/#81/#85/#86/#87/#88/#92/#93/#94/#97/#98 红线；与 `tests/eval/SCHEMA.md` 保留域规则一致。

## 5. P3 安全门核对

§9 优先级与红线：

| 红线 | 一致性 |
|------|--------|
| 安全红线 + 人工审批 > P3 > 离线评测 > 反馈 > Feature Flag | ✅ 与 AGENTS.md "硬边界" 一致 |
| 四态 schema 全部 `inactive`；无运行时采集或落库 | ✅ 与 P3 观察期一致 |
| P3 attention/输入完整性不可被高 adopt 抵消 | ✅ 与 SESSION-STATE 一致 |
| Feature Flag `on` 不授予 SMTP/Notes/SAP/财务权限 | ✅ 与 Feature Flag §9 红线一致 |
| 反馈/评测不能自动把 `off`/`dry_run` 改 `on` | ✅ 与撞坑保护一致 |
| 外部写入仍需既有环境门/策略门/逐次人工审批 | ✅ 与 AGENTS.md "外部写入" 边界一致 |

**安全门结论**：6/6 一致；候选文档严格保持 design-only，未越权。

## 6. 闭环设计核对

§7 反馈到离线评测的 9 步流程：

```text
能力产生 artifact + trace
  → 用户作出四态反馈
  → 本地严格校验、摘要、append feedback_event
  → 脱敏聚合（仍为 eval excluded）
  → 用户对单条记录显式授权
  → 创建不含原文的 fixture 候选
  → 脱敏规则复核：desensitized=true / source=user_redacted
  → 人工批准 fixture_id 与 suite/capability 对齐
  → 离线 runner 消费批准版本
  → 人工审查结果；如需改 Flag，另开审批任务
```

**关键保护**：
- ✅ 反馈创建即 `excluded`；不能因 `adopt`/`modify` 自动晋级
- ✅ `candidate` / `approved` 决策至少包含 6 字段（feedback_id/状态/consent_ref/review_ref/fixture_id/UTC时间/schema 版本）
- ✅ `revoked` 后历史审计保留；runner 不再消费
- ✅ 反馈路径与评测路径完全分离；离线评测不"借用"反馈结果

## 7. 聚合口径核对

§8 6 个聚合指标 + 空分母规则：

| 指标 | 分母 | 空分母行为 |
|------|------|----------|
| `exact_adoption_rate` | `adopt / decided` | unknown |
| `modified_use_rate` | `modify / decided` | unknown |
| `usable_rate` | `(adopt + modify) / decided` | unknown |
| `rejection_rate` | `reject / decided` | unknown |
| `unknown_rate` | `unknown / total_valid` | unknown |
| `feedback_coverage` | `decided / eligible_interactions` | unknown（输入缺失即 unknown） |

**关键约束**：
- ✅ `unknown` 不进入任何正向率分子，也不解释为 reject
- ✅ `modify` 不等价于正确；质量结论仍需离线评测
- ✅ 仅供人工分析；不触发 prompt 更新/模型选择/Flag 晋级/外部动作

## 8. 与 v1.1-A 其他 design doc 的关系

| doc | 状态 | 与 D6.15.2 关系 |
|-----|------|---------------|
| D6.13.3 SLO contract | 已集成 `7b6c0c1`（PASS） | 反馈聚合为离线指标，不进 SLO 告警 |
| D6.11.2 Feature Flag | 设计大纲只读审计 PASS | 反馈不能自动改 Flag 状态；Q1/Q4 拍板后才启动 P2 |
| D6.10.1 评测样本 4→30 | 已落 30 fixture PASS | 反馈必须经过 fixture 闭环才能扩样本 |
| D6.15.2 Feedback | 本审计报告 ready_to_merge | — |

**集成顺序建议**：
1. **短期（now → 2026-08-06）**：本审计报告等待集成审批
2. **P3 7d 通过后**：集成 D6.15.2 Feedback schema；同步另开凭据审批任务评估密钥生命周期
3. **P3 30d 通过后**：起草反馈采集器候选（仍需人工审批）

## 9. 集成前置条件清单

| 条件 | 当前 | 阻塞解除 |
|------|------|---------|
| 摘要密钥生命周期设计 | ❌ 未设计 | 用户另开凭据审批任务 |
| P3 7d 通过 | ⏳ ≈2026-08-06 | 自动判定 |
| 用户集成审批 | ❌ 待审批 | 本报告 ready_to_merge 后用户回复 |
| 撞坑保护同步 | ✅ 引用 + 闭环安全门 | 无需额外动作 |
| 与 SLO/Feature Flag 集成顺序 | ✅ 已通过 SLO；Feature Flag 待 Q1/Q4 | 顺序锁定 |

## 10. 风险与红线复核

- **候选在 `claude/d6152-feedback-schema-20260803` 分支**：本审计**不动候选原文**，仅生成独立报告
- **摘要密钥操作属凭据范畴**：未来密钥生命周期必须走独立人工审批任务，不得随集成一并实施
- **P3 7d 未通过前不得实施落库/采集器**：即便审计通过，仍需等待时间窗
- **反馈不能自动修改 Feature Flag**：即便未来实施，反馈链路与 Flag 链路完全分离
- **不得绕过脱敏复核**：fixture 必须经过 consent + 脱敏 + 人工批准三关；runner 不消费未批准 fixture

## 11. 结论与下一棒

- **集成就绪度**：文档成熟度高（11 节 + 11/11 验收勾选），但被 **摘要密钥生命周期未设计 + P3 7d 双重门控**
- **建议**：保持 design-only 状态至 P3 7d 通过；用户可在本轮另开凭据审批任务评估密钥生命周期
- **下一棒**：
  - 用户：决定是否集成本审计报告（commit 待生成）；可选另开凭据审批任务
  - 自动化：在凭据审批未通过前不实施落库/采集器/密钥；P3 7d 通过后再单独审计
  - docs-only：本轮不动 main、不 push、不合并
