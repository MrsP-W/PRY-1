# 我的AI员工 — 架构详解

> **目的**：把 5 层架构、关键决策理由、适配器契约、数据流、安全模型、失败模式讲清楚，作为 D1+ 所有编码的参考。
>
> **状态**：D1-D5.6.3 已完成(D5.6.3 commit `007a6be`+`2bc5b3b`+`3de03ed` 第三轮 7 项反馈全部修复收口,2026-06-13:1554 passed / 8 质量门 8/8 全绿 / 90.3% 覆盖,2026-06-12 D5.5.3 调度公平性补完 + Heartbeat 恢复 + D5.5.4 P1 配额浪费/单槽饥饿修复 + P3 refresh_last_seen bool 严判 + D5.5.5 P1 单槽轮换条件修复 + P2 测试断言升级 + P3 K 段单池边界测试 + 文档数据同步 + D5.6 v1 措辞失实被驳回 + D5.6.1 5 项修复被驳回 + D5.6.2 7 项二次修复被第三轮驳回 + D5.6.3 migration 0006 加 last_approved_at_ms 审批凭据 + dispatcher 拉批严判 + 10 新 tests + spike 5 项收口)。D5 业务调度器推进中(下一步 D5.6.4 真实 1 封实测 + D5.7 docs 收口),CalDAV / 菜单栏 / launchd 顺延 D6+。

---

## 1. 5 层架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  L4 Agent 层（复用 Agent Assistant 7 角色 + Skill 生态,D5.5.3 起改为 5 复制）     │
│  @信息员 @日报员 @教练员 @检查员 @SAP顾问 @回顾员 ...        │
│  + 新增 @管家 @审计员（Week 2 实施）                         │
├─────────────────────────────────────────────────────────────┤
│  L3 智能层 — minimax M3（统一 LLM）+ 规则引擎 fallback        │
│  (分类/草稿/对账/结构化 — 关键路径 fallback 到本地规则)        │
├─────────────────────────────────────────────────────────────┤
│  L2 数据层 — SQLite 加密（sqlcipher3，coleifer 活跃 fork）+ 向量索引（sqlite-vss）│
│  (邮件/日程/账本/笔记 — 全部本地存储)                        │
├─────────────────────────────────────────────────────────────┤
│  L1 适配器层 — IMAP/CalDAV/AppleScript/微信账单/银行 webhook │
│  (每个适配器独立，失败隔离 — 借鉴应急版范本)                  │
├─────────────────────────────────────────────────────────────┤
│  L0 设备层 — macOS（AppleScript/Mail.app/Calendar/Notes）    │
│           + iOS 伴侣（Shortcuts 触发 + 只读镜像）            │
└─────────────────────────────────────────────────────────────┘
```

**层间关系**：

- L0 → L1：物理设备能力（文件系统 / AppleScript / 进程）
- L1 → L2：适配器把外部数据写入加密数据库
- L2 → L3：智能层从数据库读数据 → 调用 LLM → 写回
- L3 → L4：智能层产出"信号" → Agent 决定是否触发
- L4 → 用户：Agent 产出最终输出（菜单栏 / 通知 / 文档）

**依赖方向**：只允许向下依赖（L4 → L3 → L2 → L1 → L0），**禁止反向**。

---

## 2. 各层详解

### L0 设备层

**职责**：操作系统原生能力封装

| 组件 | 用途 | 技术 |
|------|------|------|
| macOS 文件系统 | SQLite 数据库 / 配置 / 日志 | 路径：`~/Library/Application Support/我的AI员工/` |
| AppleScript | Mail.app / Calendar / Notes / Reminders 桥接 | osascript 命令 |
| launchd | 系统级保活（避免被 macOS 杀掉）| `~/Library/LaunchAgents/com.myaiemployee.agent.plist` |
| Keychain | 凭证加密存储（IMAP 密码 / API Key）| `security` 命令 |

**关键约束**：

- macOS 12+（AppleScript 权限稳定性）
- 用户必须授权 "Automation / Full Disk Access"（首次启动向导引导）

### L1 适配器层

**职责**：把外部数据源接入 L2 数据库

**6 个适配器**（Week 1+2 MVP 范围）：

| 适配器 | 数据源 | 协议 | 频率 | 实施时间 |
|--------|--------|------|------|----------|
| **imap** | QQ / Outlook / Gmail | IMAP4 + OAuth 2.0 | 5 min 轮询 | Week 1 D2 |
| **caldav** | iCloud（**优先**）/ Google Calendar | CalDAV | 5 min 轮询 | **D6+ 顺延**(原 Week 1 D5,2026-06-11 重新定义) |
| **wechat_csv** | 微信账单 | CSV 文件导入 | 用户手动 / 每日 | Week 2 D6 |
| **alipay_csv** | 支付宝账单 | CSV 文件导入 | 用户手动 / 每日 | Week 2 D7 |
| **apple_notes** | Apple Notes | AppleScript 读取 | 事件触发 | Week 2 D9 |
| **apple_reminders** | Reminders（复用 Agent Assistant）| AppleScript | 5 min 轮询 | **D6+ 顺延**(原 Week 1 D5,2026-06-11 重新定义) |

**适配器接口契约**（abstract）：

```python
# connectors/base.py
class BaseConnector(ABC):
    @abstractmethod
    async def fetch(self, since: datetime) -> list[dict]: ...

    @abstractmethod
    async def healthcheck(self) -> bool: ...

    @property
    @abstractmethod
    def source_name(self) -> str: ...

    # 失败隔离（来自应急版范本）
    async def safe_fetch(self, since: datetime) -> list[dict]:
        try:
            return await self.fetch(since)
        except Exception as e:
            log.error(f"{self.source_name} fetch failed: {e}")
            notify_admin(f"适配器 {self.source_name} 失败，已隔离")
            return []
```

**失败隔离原则**：

- 单个适配器失败 → 不影响其他适配器
- 单个适配器连续失败 3 次 → 进入熔断（30 min 后再试）
- 失败计数 + 时间戳写入 `data/health.log`（加密）

### L2 数据层

**职责**：加密存储 + 快速查询

**Schema 概览**（详细 SQL 见 `core/schema.sql`，D3 实施）：

```sql
-- 邮件
CREATE TABLE emails (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,           -- 'qq' / 'outlook' / 'gmail'
    message_id TEXT UNIQUE,
    subject TEXT,
    sender TEXT,
    received_at TIMESTAMP,
    body_encrypted BLOB,            -- sqlcipher3 AES-256 加密
    body_plaintext_hash TEXT,       -- 用于去重
    category TEXT,                  -- 'work' / 'finance' / 'subscription' / 'spam' / 'pending'
    priority INTEGER DEFAULT 0,
    embedding BLOB,                 -- sqlite-vss 向量
    indexed_at TIMESTAMP
);

-- 日程
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    calendar_source TEXT,           -- 'icloud' / 'google'
    external_id TEXT,
    title TEXT,
    start_at TIMESTAMP,
    end_at TIMESTAMP,
    attendees TEXT,                 -- JSON
    notes_encrypted BLOB,
    reminder_minutes INTEGER
);

-- 交易
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    source TEXT,                    -- 'wechat' / 'alipay' / 'bank'
    occurred_at TIMESTAMP,
    amount_cents INTEGER,           -- 分（避免浮点）
    currency TEXT DEFAULT 'CNY',
    category TEXT,
    merchant TEXT,
    note_encrypted BLOB,
    raw_hash TEXT UNIQUE            -- 去重
);

-- 笔记
CREATE TABLE notes (
    id INTEGER PRIMARY KEY,
    source TEXT,                    -- 'apple_notes' / 'clipboard' / 'manual'
    external_id TEXT,
    title TEXT,
    content_encrypted BLOB,
    content_plaintext_hash TEXT,
    tags TEXT,                      -- JSON array
    embedding BLOB,
    created_at TIMESTAMP,
    modified_at TIMESTAMP
);

-- 健康日志
CREATE TABLE health_log (
    id INTEGER PRIMARY KEY,
    connector TEXT,
    status TEXT,                    -- 'ok' / 'degraded' / 'failed' / 'circuit_open'
    error TEXT,
    occurred_at TIMESTAMP
);
```

**关键决策**：

- **金额用分（cents）** — 避免浮点精度问题
- **敏感字段加密**（BLOB）+ **明文哈希**用于去重 — 平衡隐私 + 功能
- **向量索引**（sqlite-vss）— 本地语义搜索，**不依赖云端 embedding 服务**

### L3 智能层

**职责**：把数据变"信息" + 触发 Agent

**4 个核心服务**：

| 服务 | 输入 | 输出 | LLM |
|------|------|------|-----|
| **classifier** | 邮件正文 | 5 类标签 + 优先级 | minimax M3 |
| **drafter** | 邮件 + 用户历史 | 回复草稿 | minimax M3 |
| **finance_analyzer** | 当月交易 | 异常检测 + 月度报告 | minimax M3 |
| **note_structurer** | 剪贴板/Notes 内容 | Markdown + tags | minimax M3 |

**LLM 路由策略**（✅ 2026-06-07 决策：**统一 minimax M3，不做本地 Ollama**）：

| 数据类型 | 主路由 | Fallback | 说明 |
|----------|--------|----------|------|
| 邮件正文（不含凭证）| minimax M3 | 规则引擎（关键词/正则）| 统一 LLM 调用 |
| 邮件正文（含敏感词：身份证/银行卡/密码）| **跳过 LLM** | 仅存原文 + 标记 `pending` | 留待用户确认 |
| 交易数据（仅金额/类别/时间）| minimax M3 | 本地统计 | 不含敏感信息 |
| 笔记（用户标记为"私密"）| **跳过 LLM** | 仅存原文 | 留待用户确认 |
| 笔记（用户标记为"普通"）| minimax M3 | 规则引擎 | 正常流程 |

**关键设计选择**（与原 PersonalOS 不同）：

- ❌ **不实施本地 Ollama** — 减少 D1-D10 工作量，与 Agent Assistant 链路统一
- ✅ **敏感数据 → 跳过 LLM** — 不是走本地，而是直接不调用，由用户后续手动处理
- ✅ **Fallback = 规则引擎** — 关键词/正则匹配（紧急场景可用）

**为什么放弃本地 Ollama**：

1. **复杂度成本** — 装包 + 模型下载（7B 模型 ≈ 4-5GB）+ 性能调优
2. **质量成本** — qwen2.5:7b 中文分类比 minimax M3 差 1-2 个量级
3. **数据量小** — 个人日均邮件 50-100 封，月报 1 次，敏感数据占比 < 5%
4. **Phase 2 可加** — 如果发现某类敏感场景频繁，可针对性加本地 LLM

### L4 Agent 层

**职责**：跨任务协调 + 主动提醒

**复用模式**（不重复造轮子）：

- 5 核心角色从 Agent Assistant **复制**过来(D5.5.3 起,原软链导致 uv build 失败已改复制)
  + 2 本项目专属角色(@管家 / @审计员)
  = 7 个角色
- 通过 `📌 下一棒` 协议传递任务
- SAP 顾问仍处理 FICO 业务（PersonalOS 财务模块触发）

**新增角色**（2 个，Week 2）：

- **@管家** — 全天候主动提醒（"你 3 封邮件未回" / "本月支出超预算 80%"）
- **@审计员** — 每月 1 号生成"数字生活月报"（邮件/账本/笔记统计）

---

## 3. 关键设计决策（带理由）

| 决策 | 选择 | 拒绝方案 | 理由 |
|------|------|----------|------|
| **数据库** | SQLite 加密（**sqlcipher3**，D1.1 从 pysqlcipher3 切换）| PostgreSQL / MySQL | 零运维 + 跨设备同步用 iCloud Drive + 单用户场景 |
| **LLM 主路由** | **minimax M3**（统一）| 多 LLM 路由 | 与 Agent Assistant 链路统一 + 减少复杂度 |
| **LLM Fallback** | 规则引擎（关键词/正则）| 本地 Ollama | 隐私数据"跳过 LLM"而非"走本地" + 减少安装量 |
| **GUI** | Mac 菜单栏（rumps）+ Web Dashboard | Electron / Tauri | 菜单栏省注意力 + Web 适合深度操作 |
| **任务调度** | APScheduler + launchd | Celery / cron | 单机场景 + Python 生态 + launchd 保活 |
| **凭证管理** | macOS Keychain | .env / config.json | 系统级加密 + 跨应用隔离 |
| **依赖管理** | **PEP 621 + uv**（D1.1 从 Poetry 切换）| Poetry / pip | 标准 pyproject 格式 + uv.lock 提交可复现 + 比 Poetry 快 10× |
| **Python** | **3.12**（D1.1 固定，避开 3.14 wheel 风险）| 3.11 / 3.13 / 3.14 | sqlcipher3/keyring/rumps 在 3.12 上 wheel 齐全 |
| **CalDAV 优先** | iCloud | Google Calendar | 用户已选 + Apple 生态整合 + iCloud 同步更稳 |
| **测试** | pytest + 真实数据脱敏 | mock / fixture | 财务/邮件场景 mock 失真 |

---

## 4. 数据流示例（4 个核心场景）

### 场景 1：新邮件到达 → 分类 + 通知

```
[IMAP Server]
  ↓ (5 min 轮询)
[L1 imap connector]
  ↓ INSERT INTO emails
[L2 SQLite]
  ↓ 触发器 (TRIGGER on INSERT)
[L3 classifier]
  ↓ 调用 minimax M3 → 标签 + 优先级
  ↓ UPDATE emails
  ↓ 若 priority > 0.7
[L4 @管家 Agent]
  ↓ 发送 macOS 通知
[User 看到通知]
```

**耗时**：端到端 2-5 秒（IMAP 轮询间隔决定感知延迟）

### 场景 2：用户点"1-click 回复"

```
[User 点击菜单栏 "草稿建议"]
  ↓
[L4 @管家 Agent]
  ↓ 读取 email.body_encrypted (解密)
  ↓ 提取历史回复模式 (从 L2)
[L3 drafter]
  ↓ 调用 minimax M3 → 草稿
  ↓ 写入 drafts 表
[AppleScript: 在 Mail.app 创建草稿窗口]
  ↓
[User 编辑 + 发送]
```

### 场景 3：每月 1 号财务月报

```
[launchd 定时任务: 每月 1 号 09:00(D6+ 顺延)]
  ↓
[L4 @审计员 Agent]
  ↓ 查询 transactions (当月)
[L3 finance_analyzer]
  ↓ minimax M3 分析消费模式
  ↓ 生成 Markdown 报告
  ↓ 写入 output/YYYY-MM/财务月报.md
[Mac 通知 + 菜单栏更新]
```

### 场景 4：剪贴板笔记自动结构化

```
[User 按 ⌥⌘N]
  ↓
[L4 @内容编辑员 Agent]
  ↓ 读取 NSPasteboard
[L3 note_structurer]
  ↓ minimax M3 → Markdown + tags
  ↓ INSERT INTO notes
[Apple Notes 同步（可选）]
```

---

## 5. 安全模型

### 5.1 数据保护

| 层级 | 措施 |
|------|------|
| **存储** | **sqlcipher3** AES-256 加密（密码从 Keychain 取，D1.1 替代 pysqlcipher3）|
| **传输** | TLS 1.3+（IMAP/OAuth/CalDAV）|
| **凭证** | Keychain 加密 + 进程级缓存（不落盘）|
| **日志** | 敏感字段脱敏（身份证 → 110***********0023）|

### 5.2 LLM 调用安全

- **白名单字段**：只发送已分类字段（如 `category='work'` 才发 body）
- **黑名单正则**：`身份证|银行卡|密码|API[_-]?key` 命中 → **跳过 LLM**
- **审计日志**：每次 LLM 调用记录 `data/llm_audit.log`（含 token 数 + 路由）

### 5.3 物理访问

- 数据库文件权限 600（仅当前用户）
- Keychain 项标记 "require user presence"
- 5 分钟无操作自动锁屏（macOS 系统设置）

---

## 6. 失败模式 + 隔离策略

> 借鉴 Agent Assistant "应急版" 5 级范本。

| 失败点 | 影响 | 隔离策略 |
|--------|------|----------|
| IMAP 服务器挂 | 新邮件延迟 | 熔断 30 min + 用本地缓存 |
| CalDAV 失败 | 日程不更新 | 不影响邮件/财务 |
| minimax M3 挂 | 智能功能降级 | 自动切到规则引擎 |
| SQLite 锁 | 全局阻塞 | WAL 模式 + 重试 3 次 |
| AppleScript 权限丢失 | 设备层失效 | 触发系统级引导 |

**降级路径**（4 级，对齐 Agent Assistant 但**去掉 Ollama**）：

1. **L1 主路径** — 全功能（minimax M3）
2. **L2 规则降级** — LLM → 关键词/正则
3. **L3 只读模式** — 写入暂停，只读历史
4. **L4 完全离线** — 仅本地数据，不联网

---

## 7. 与 Agent Assistant 的边界

**我的AI员工不重复造**：

- 5 角色 Agent（D5.5.3 起复制,本项目专属 2 个,共 7 个）
- Skill 生态（个人级 + 全局级）
- 应急版范本（降级路径）
- MD 维护纪律（MDLint）
- 跨会话记忆（`memory/`）

**我的AI员工新增**：

- 加密数据库
- 适配器层
- 主动触发（vs 晨晚链路定时）
- 菜单栏 UI
- iOS 伴侣

**冲突解决原则**：Agent Assistant 是"技能库"，我的AI员工是"执行器"。

---

## 8. 不确定项（待 Week 1 验证）

- [x] ~~pysqlcipher3 在 Python 3.14 上的安装~~ → **D1.1 已解决**：改用 sqlcipher3，Python 3.12
- [ ] IMAP OAuth 2.0 跨邮箱复杂度（**D2.5 spike**：Outlook/Gmail 推到 spike 阶段）
- [ ] minimax M3 调用稳定性（已知可用，待持续监控）
- [ ] sqlite-vss 向量索引中文支持
- [ ] launchd 保活效果（macOS 18+ 后台策略更严格,**D6+ 顺延**）

**Week 1 末决策点**（见 [week1-mvp.md](week1-mvp.md) 末尾）：技术栈通过 → 继续 Week 2；不通过 → 砍到最小可用 + 报告失败原因。

---

**最后更新**:2026-06-13(D5.6.3 commit `007a6be`+`2bc5b3b`+`3de03ed` 第三轮 7 项反馈全部修复收口,P1-1 审批凭据迁移 0006 + dispatcher 拉批严判 + 10 新 tests + spike 5 项收口,D5.6.3:1554 passed / 8 质量门全绿 / 90.3% 覆盖)
**状态**:D1-D5.6.3 已完成(D4.8 v1.0.1 commit `2e48179` + D5.1 `cce567a` + D5.1-fix `18284fa` + D5.2 `604f937` + D5.3 `192c215` + D5.4 `e9f3126` + D5.5 `3f449d9` + D5.5.1 + D5.5.2 `97b7605` + D5.5.3 `7e9bca0` + D5.5.4 `a7560c1` + D5.5.5 `a866810` + D5.6 v1 `c4a7d01` + D5.6.1 `fdf44c6` + D5.6.2 `819affb`+`8fdc088` + D5.6.3 `007a6be`+`2bc5b3b`+`3de03ed`),剩 D5 业务调度器 2 子阶段(D5.6.4 真实 1 封实测 + D5.7 docs 收口 8 件套)
**维护者**:Mr-PRY
