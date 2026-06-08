-- D3.1 — SQLCipher 数据库 schema（v1.1 — D3.1.1 修正）
-- 文件：data.db（位于 ~/Library/Application Support/my-ai-employee/data.db）
-- 加密：PRAGMA key = <32 字节随机串>
--       Keychain service=my-ai-employee.db account=data.db
--       首次启动自动生成 + 写入 Keychain（D3.1.1 决策，不再要求用户手动）
-- 迁移：alembic（D3.2 引入）— 本文件是 v1 起点，alembic 后续基于本 schema 增量
-- 幂等：所有 CREATE 都用 IF NOT EXISTS，重复跑不爆（覆盖式 init 路径）

-- ===== emails =====
-- 邮件主表。
-- 唯一性：UNIQUE(source, uid) — IMAP UID 是协议级唯一键（D3.1.1 修正）
--   原因：RFC 5322 Message-ID 经常缺失（垃圾邮件 / 某些 server 不生成），
--   用 (source, message_id) 当唯一键会导致无 message_id 邮件互相冲突。
--   IMAP UID 是协议分配的递增整数，server 内单调递增，无缺失风险。
-- message_id 改为可空：保留为普通索引（部分查询用）。
-- received_at 改为可空：D2 IMAPConnector.envelope.date 可能为 None，
--   D3.3 入库映射层 fallback 到 fetched_at（D3.1.1 决策）。
-- 索引：received_at 倒序检索是热路径
CREATE TABLE IF NOT EXISTS emails (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,                    -- "qq" / "outlook" / "gmail"
    uid             INTEGER NOT NULL,                    -- IMAP UID（协议级唯一）
    message_id      TEXT,                                -- RFC 5322 Message-ID（可空）
    subject         TEXT    NOT NULL DEFAULT '',         -- 解码后的主题
    sender          TEXT    NOT NULL DEFAULT '',         -- 发件人（mailbox@host）
    recipients      TEXT    NOT NULL DEFAULT '[]',       -- JSON array（D3 阶段先存空）
    received_at     INTEGER,                             -- Unix epoch ms（可空 — envelope date 可能缺失）
    raw_size        INTEGER NOT NULL DEFAULT 0,          -- 字节数
    body_text       TEXT    NOT NULL DEFAULT '',         -- plain text（D3 阶段先不下载 body）
    body_html       TEXT    NOT NULL DEFAULT '',         -- html（D3 阶段先不下载 body）
    fetched_at      INTEGER NOT NULL,                    -- 入库时间（Unix epoch ms，received_at 缺失时 fallback）
    labels          TEXT    NOT NULL DEFAULT '[]',       -- JSON array of label names
    UNIQUE(source, uid)
);

CREATE INDEX IF NOT EXISTS idx_emails_received_at ON emails(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_source_received ON emails(source, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);
CREATE INDEX IF NOT EXISTS idx_emails_message_id ON emails(message_id);


-- ===== attachments =====
-- 附件元数据。文件本身不存 DB（路径指向本地加密存储，sha256 去重）
-- D3 阶段只下载元数据，正文 D4/D5 再扩展
CREATE TABLE IF NOT EXISTS attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id        INTEGER NOT NULL,                    -- FK → emails.id
    filename        TEXT    NOT NULL DEFAULT '',
    content_type    TEXT    NOT NULL DEFAULT '',
    size            INTEGER NOT NULL DEFAULT 0,
    local_path      TEXT    NOT NULL DEFAULT '',         -- 下载到本地的路径
    sha256          TEXT    NOT NULL DEFAULT '',         -- 内容 hash
    FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_attachments_email_id ON attachments(email_id);


-- ===== labels =====
-- 标签字典。name 唯一（不分大小写 — 用 COLLATE NOCASE）
-- source: 哪个邮箱（"qq" / "system" / "user"）
CREATE TABLE IF NOT EXISTS labels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL COLLATE NOCASE,
    source          TEXT    NOT NULL DEFAULT 'system',   -- "qq" / "system" / "user"
    color           TEXT    NOT NULL DEFAULT '#808080',
    UNIQUE(name, source)
);

CREATE INDEX IF NOT EXISTS idx_labels_source ON labels(source);


-- ===== email_labels =====
-- 多对多关联表（一个邮件可以多个标签，一个标签下多个邮件）
CREATE TABLE IF NOT EXISTS email_labels (
    email_id        INTEGER NOT NULL,
    label_id        INTEGER NOT NULL,
    PRIMARY KEY (email_id, label_id),
    FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE CASCADE,
    FOREIGN KEY (label_id) REFERENCES labels(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_email_labels_label_id ON email_labels(label_id);


-- ===== sync_state =====
-- 增量同步游标（每 source 一行）
-- last_sync_at: 上次成功同步的最大 received_at
-- last_uid: 上次同步的最大 IMAP UID（与 last_sync_at 二选一，看 IMAP server 行为）
-- last_status: "ok" / "failed"
CREATE TABLE IF NOT EXISTS sync_state (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    source                  TEXT    NOT NULL UNIQUE,     -- "qq" / "outlook" / "gmail"
    last_sync_at            INTEGER NOT NULL DEFAULT 0, -- Unix epoch ms
    last_uid                INTEGER NOT NULL DEFAULT 0,
    last_status             TEXT    NOT NULL DEFAULT 'pending',  -- "ok" / "failed" / "pending"
    last_error              TEXT    NOT NULL DEFAULT '',
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    updated_at              INTEGER NOT NULL             -- Unix epoch ms
);


-- ===== audit_log =====
-- 审计日志（D3 阶段主要记 sync 事件）
-- event: "sync_started" / "sync_completed" / "sync_failed" / "email_inserted" / "db_opened" / "db_closed"
-- detail: JSON string（事件相关上下文）
-- 注：D4.3 不动 audit_log — sync 审计保持简化；D4.3 新增 events 表承载 g004 4 不变量
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event           TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT '',
    detail          TEXT    NOT NULL DEFAULT '{}',      -- JSON
    created_at      INTEGER NOT NULL                     -- Unix epoch ms
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON audit_log(event);


-- ===== events (D4.3 新增) =====
-- 结构化事件流（g004-events-reports-contract.md 4 大不变量落地）
-- 区别于 audit_log：events 走 typed event + status + 6 必含 metadata 字段 + fingerprint 去重
-- 职责：智能层 (LLM/MCP/分类/草稿) 的结构化事件流；audit_log 继续做 D3 sync 审计
--
-- 不变量（g004 4 条）:
--   1. event — typed name (EventType StrEnum, 例: "llm.call.started" / "mcp.server.connected")
--   2. status — 7 枚举 (EventStatus StrEnum: started/succeeded/failed/degraded/skipped/blocked/cancelled)
--   3. metadata — JSON 必含 6 字段:
--         seq                : 单调递增序号(同 session 内唯一)
--         timestamp_ms       : 事件发生 Unix epoch ms
--         session_id         : 会话身份(空字符串 = 全局)
--         ownership          : "act" / "observe" / "ignore" (是否触发 side effect)
--         provenance         : "live" / "test" / "replay" / "healthcheck" (数据来源)
--         fingerprint        : SHA-256 派生键(冗余于 events.fingerprint 列,用于跨表查找)
--      负向证据 first-class: status=failed/skipped/blocked + metadata.redaction_reason
--   4. structured-event-trumps-prose — if event 存在, 不从 prose 推断; UI/CLI 优先消费 events 表
--
-- 唯一性: UNIQUE(fingerprint) — 全局唯一
--   - fingerprint = SHA-256 派生键(物理去重键), 同 fingerprint 即"同一业务事件"
--   - g004 Rust 端 `compute_event_fingerprint(event, status, data)` 入参不含 source/subject_id,
--     即 fingerprint = "事件身份" 与 source/subject_id 无关
--   - 但 fallback 跨源场景(deepseek 失败 → openai 重试): compute_fingerprint 入参含 source,
--     不同 source → 不同 fingerprint, 各自 1 条, 不被误判重复
--   - 不用 UNIQUE(event, source, subject_id, fingerprint) 4 字段联合: SQLite UNIQUE 允许多行
--     subject_id=NULL, 同 fingerprint 重复 subject_id=NULL 会被认为是不同行, 破坏去重 (D4.3.1 复检 P1)
--   - fingerprint 提为独立列(DDL 真理之源), SQLite UNIQUE 不支持函数表达式
--   - 冗余原因: fingerprint 既要"物理去重键"(DDL), 又要"应用层引用键"(metadata JSON)
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event           TEXT    NOT NULL,                    -- EventType 枚举值(typed name)
    status          TEXT    NOT NULL,                    -- EventStatus 枚举值(7 选 1)
    source          TEXT    NOT NULL DEFAULT '',         -- 事件源头(例: "minimax" / "mcp.filesystem" / "classifier")
    subject_id      TEXT,                                -- 关联实体 ID(例: email_id / llm_request_id / task_id, 可空)
    fingerprint     TEXT    NOT NULL DEFAULT '',         -- SHA-256 派生键(冗余于 metadata.fingerprint, 物理去重键, 全局唯一)
    event_metadata  TEXT    NOT NULL DEFAULT '{}',       -- JSON 字符串(必含 6 必含字段,见上)
                                                        -- 列名 event_metadata 避开 SQLAlchemy Declarative 保留属性 metadata
    created_at      INTEGER NOT NULL,                    -- Unix epoch ms(冗余于 metadata.timestamp_ms,便于排序)
    UNIQUE(fingerprint)                                 -- fingerprint 全局唯一(同业务事件 dedupe, 与 subject_id=NULL 兼容)
);

CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_subject_id ON events(subject_id);
CREATE INDEX IF NOT EXISTS idx_events_fingerprint ON events(fingerprint);
