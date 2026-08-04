# D6.15.3 Feedback 摘要密钥生命周期评估（只读）

**评估对象**：D6.15.2 Feedback schema（候选分支 `claude/d6152-feedback-schema-20260803`，HEAD `688e22d`）所规划的 `feedback_event` 摘要密钥生命周期。  
**评估范围**：docs-only；不实施任何密钥生成、存储、分发、轮换或销毁代码；不接入任何凭据仓库；不读写真实数据。  
**评估依据**：
- D6.15.2 设计原稿 `docs/v1.1-feedback-schema.md`（候选分支同上）。
- D6.15.2 只读审计报告 `tests/eval/audit/feedback-schema-readiness-20260804.md`。
- 全局密钥/凭据基线：本仓库 `SECURITY.md`、`.env.example`、`docs/agent-team/README.md`（用户 WIP）。

> 本评估不通过任何自动化动作生成、变更或销毁密钥；所有“如何做”的结论均停留在“若实施应满足”的契约层。

## 1. 摘要密钥在 D6.15.2 中的角色

D6.15.2 schema 在 `feedback_event` 内记录三类与摘要密钥相关的最小字段：

| 字段 | 类型 | 摘要密钥用途 |
|------|------|--------------|
| `before_hash` | hex（32+） | `HMAC-SHA256(key, before)`；用于回放与重放检测 |
| `after_hash` | hex（32+） | `HMAC-SHA256(key, after)`；与 `before_hash` 共同支撑差分脱敏 |
| `diff_summary` | 字典 | 仅允许白名单标签 + `count`，不可逆推原文 |

关键约束：

- 摘要为 **单向 + 密钥相关 + 仅本地**；不允许服务端代为派生或集中对比。
- `feedback_event` 的 `append_only + fail_closed` 已在 D6.15.2 审计中确认；密钥生命周期是其上游依赖。
- 摘要密钥 **不** 包含在 `feedback_event` 内（明文或脱敏均不可），否则丧失 HMAC 不可逆意义。
- 摘要密钥属于“凭据”范畴，按全局 AGENTS 与 `SECURITY.md` 必须走独立的人工审批任务，不允许随 D6.15.2 集成一并实施。

## 2. 威胁建模（密钥泄露影响面）

| 泄露路径 | 影响 | 防护目标 |
|----------|------|----------|
| 本地密钥文件被复制 | 攻击者可派生未来 `before/after_hash`，污染差分事实 | 文件级加密 + 严控访问模式（0600、owner-only） |
| 密钥材料进入日志/异常 | 一旦 dump 暴露密钥本体 | 任何日志/异常都禁止输出密钥材料；白名单 `*_hash` 是合规字段 |
| 跨设备复用同一密钥 | 增加泄露半径 | 设备独立密钥；同步走专门审批 |
| 备份携带密钥 | 备份泄露 = 密钥泄露 | 密钥不入备，或备份本身加密且与数据分离 |
| 长期不轮换 | 累积暴露窗口 | 周期轮换 + 触发轮换（异常、嫌疑、离职） |
| D6.15.2 schema 录入密钥本体 | 失去 HMAC 不可逆；攻击者可任意伪造 `feedback_event` | schema 校验器将密钥字段列入禁止列表 |

## 3. 生命周期阶段契约

下列每一阶段都为“若实施应满足”的最小契约，不替代实现方案的设计任务。

### 3.1 生成

- 由用户在受控 UI/CLI 触发；不监听、不后台生成。
- 最小熵 ≥ 256 bit；来源必须为密码学安全 RNG（`secrets`/`Security.framework`），禁止伪随机。
- 同时派生 `key_id`（公开，用于指代该密钥；不暴露密钥本体）并记录 `created_at`。
- 同设备禁止产生两个等价 `key_id`；新密钥生成应明示旧密钥的影响（仅哈希校验仍可用，但失去对比与告警的可信度）。

### 3.2 存储

- 文件模式 0600，owner-only；任何所属目录同样限制。
- 物理位置：

  | 候选 | 适用性 | 备注 |
  |------|--------|------|
  | macOS Keychain | 推荐主用 | 与登录会话绑定，支持 `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`；不进入 iCloud |
  | 本地加密文件（与 SQLCipher 集成） | 可用辅助 | 需要单独的密钥包装密钥；引入额外密钥 |
  | `.env` 文件 | 不接受 | 容易被 `git status`、日志、合并冲突暴露；且与全局密钥政策冲突 |
  | LaunchAgent 环境变量 | 不接受 | 重启可见于 `launchctl print`/`ps`；与全局密钥政策冲突 |

- 备份策略：默认不进入备份；如需进入 Time Machine，必须在 `tmutil isexcluded` 路径白名单内。

### 3.3 分发

- 仅本地，无网络分发；D6.15.2 假设仅本机。
- 跨设备同步必须单独审批；本评估不预设方案。
- 任何调试导出都必须经脱敏（仅 `key_id` 与元数据），导出流程独立审批。

### 3.4 使用

- 摘要运算只读 `key` + 字段值；运算路径禁止日志全量。
- `feedback_event` 写入 SQLCipher 前应校验 schema，禁止录入 `key` / `key_material` / `keyfile` 等字段。
- 摘要调用统一抽到一个 `feedback_hmac` 包装层，便于后续审计与轮换。

### 3.5 轮换

- 周期：90 天为基线，可被以下事件触发提前轮换：
  - 设备物理/账户变更（修机、转岗、离职）；
  - 任何疑似密钥泄露的安全事件；
  - 调试导出后未在 24h 内撤销；
  - 合规/政策强制要求。
- 轮换过渡期：旧密钥仍可校验历史 `feedback_event`，但不允许新事件使用旧密钥；该窗口 ≤ 7 天。
- 轮换必须落审计日志（含 `old_key_id` / `new_key_id` / `reason` / `actor`），日志位置与脱敏规则同 D6.13.3。

### 3.6 销毁

- 主动销毁：删除本地密钥文件 + Keychain 项；记录 `destroyed_at` 审计。
- 销毁后历史 `feedback_event` 仍按当时 `key_id` 保留；摘要不可逆，旧事件校验依旧有效。
- 设备退役：执行密钥级 `destroy`；备份退役需另走 `tmutil`/磁盘擦除流程。

### 3.7 审计

- 审计事件最小集：`key.generated`、`key.rotated`、`key.destroyed`、`key.accessed`、`key.exported_redacted`、`key.imported_denied`。
- 审计字段：`actor`、`key_id`、`reason`、`source`，禁止含密钥本体。
- 审计持久化复用 D6.13.3 SLO 与 v0.1 反馈事件的本机落库方案；不允许新设独立通道。

## 4. 推荐落点（与现有架构对齐）

| 维度 | 建议 | 主要理由 |
|------|------|----------|
| 主存储 | macOS Keychain（`kSecClassGenericPassword` 或自有 item class） | 与登录会话绑定、防误入 iCloud、API 成熟 |
| 访问时机 | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` | 设备首次解锁后可用；不随备份泄露 |
| 包装层 | 单一 `feedback_hmac` 工具模块，封装 Keychain 访问 + 摘要运算 | 限制扩散面、便于轮换与审计替换 |
| 写入校验 | `feedback_event` schema 校验器显式拒绝密钥相关字段 | 与 D6.15.2 schema fail-closed 一致 |
| 轮换触发 | 90 天周期 + 安全事件触发；保留旧密钥只读 7 天 | 短轮换窗口 + 可读性兼容 |
| 审计写入 | 复用 D6.13.3 SLO 审计通道 | 统一通道、单一事实表 |
| 销毁 | Keychain `SecItemDelete` + 文件硬删除 | 最小破坏面；避免残留 |

每项均与当前 `main` 已有契约不冲突；不需要改 SLO doc、Feature Flag、Feedback schema 原文。

## 5. 不采纳方案与理由

| 方案 | 不采纳理由 |
|------|------------|
| 写入 `.env` 或 LaunchAgent env | 与全局密钥政策直接冲突；与 P3 观察期“密钥变更需独立审批”冲突 |
| 走 SQLCipher 加密文件而非 Keychain | 需另一密钥（密钥包装密钥）；引入新密钥面，仅在 Keychain 不可用时作为兜底选项，不作主路径 |
| 远程/集中式密钥管理服务 | 与 D6.15.2 “本地严格校验、摘要、append feedback_event” 明确冲突 |
| 应用启动时随机生成并仅存活进程 | 与 `feedback_event` 跨重启校验/差分诉求冲突；不满足持久性 |
| 同步到 iCloud Keychain | 跨设备暴露面增加；当前架构不授权跨设备摘要 |

## 6. 与其他模块的依赖

| 模块 | 关系 | 约束 |
|------|------|------|
| D6.13.3 SLO | 复用其审计通道与 SLO 报告 | 不得新增独立的 SLO 维度 |
| D6.11.2 Feature Flag | 摘要密钥启用必须经 Feature Flag 才能读取真实密钥 | 与 Feature Flag 设计大纲的 `runtime.credential_access` gate 对齐 |
| D6.15.2 Feedback schema | schema 不录密钥字段；`before/after_hash` 校验时不依赖密钥外泄 | schema 校验器是最后防线 |
| v1.1-A readiness | 本评估属于 docs，不影响 burn-in 与 7d/30d 窗口 | 不会破坏 readiness 状态 |
| SAP/财务/权限 | 不涉及 | n/a |

## 7. 验收清单（设计文档层面，本轮即检查）

- [x] 阶段契约覆盖 生成 / 存储 / 分发 / 使用 / 轮换 / 销毁 / 审计。
- [x] 给出主路径（Keychain）与兜底（SQLCipher 封装）的差异。
- [x] 显式拒绝 `.env`、LaunchAgent env、远程密钥服务。
- [x] 与 D6.13.3 SLO、D6.11.2 Feature Flag、D6.15.2 schema 的接口有接口级描述。
- [x] 给出审计事件最小集，且不含密钥本体。
- [x] 轮换窗口与销毁路径独立可执行地写出“满足什么才算合规”。
- [x] 不涉及对 `main` 已合入文档（SLO、Feature Flag、Feedback）的实施变更。

## 8. 未决问题与下一步

1. 跨设备摘要是否需求：当前 main 不主张跨设备摘要；若用户后续提出，需另开设备同步凭据审批。
2. Keychain 不可用时的回退行为：需要在实施任务中明确，例如 SQLCipher 包装密钥的派生与恢复流程。
3. `diff_summary` 与白名单标签的运维入口：与 D6.15.2 schema 同源另开治理任务。
4. 审计通道复用 D6.13.3 是否会被合并到主 SLO 报告：与 SLO 维护者再确认一次写入形态。
5. 与 LaunchAgent（WIP 下的 `ops/run-claude-p3-watch.sh` 等）冲突：摘要密钥 Keychain 项在 headless 启动下的可见性需要单独审批（与 LaunchAgent 设计 task 关联）。

> 本评估不应被视为对任何密钥管理代码、PList、LaunchAgent 或 SQLCipher 操作的实施授权；其结论只对未来“凭据审批任务”做设计输入。

## 9. 与 P3/v1.1-A readiness 的影响

| 门槛 | 当前 | 本任务后 | 说明 |
|------|------|---------|------|
| 30-fixture privacy/ID guards | PASS | PASS | 不涉及 |
| D6.13.3 SLO design-only | PASS | PASS | 不涉及 |
| 7d attention | FAIL | FAIL | docs-only 无法变更 |
| 30d attention | FAIL | FAIL | docs-only 无法变更 |
| D6.11.2 Feature Flag docs 集成 | FAIL | FAIL | 不涉及 |
| D6.15.2 Feedback schema docs 集成 | 待 `11f92ef` 集成审批 | 不变 | 本评估不替代 schema 集成 |
| 摘要密钥凭据审批 | n/a | 待发起 | 本评估是凭据审批的前置 docs 输入，非实施 |

docs-only 评估不会推进 readiness 数字；其作用是为下一阶段“凭据审批任务”提供统一的生命周期契约。

---
*评估人：Codex 协调主 Agent（gpt-5.6-luna，max）。*
*模型调用：SOL=未唤醒；TERRA=未唤醒；LUNA=主 Agent 自身；M3=无法通过 Codex 原生通道调用，本轮 docs-only 不触发 external bridge。*
*无外部写入；不动用户 WIP；未触发 push。*
