-- D3.1 — SQLCipher 数据库 schema（v1）
-- 文件：my-ai-employee.db（位于 ~/Library/Application Support/my-ai-employee/data.db）
-- 加密：PRAGMA key = <32 字节随机串，存 Keychain service=my-ai-employee.db account=master>
-- 迁移：alembic（D3.2 引入）— 本文件是 v1 起点，alembic 后续基于本 schema 增量
-- 幂等：所有 CREATE 都用 IF NOT EXISTS，重复跑不爆（覆盖式 init 路径）

-- ===== emails =====
-- 邮件主表。
-- 唯一性：UNIQUE(source, message_id) — 同一邮件不会重复入库
-- 索引：received_at 倒序检索是热路径
CREATE TABLE IF NOT EXISTS emails (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT    NOT NULL,                    -- "qq" / "outlook" / "gmail"
    uid             INTEGER NOT NULL,                    -- IMAP UID
    message_id      TEXT    NOT NULL,                    -- RFC 5322 Message-ID
    subject         TEXT    NOT NULL DEFAULT '',         -- 解码后的主题
    sender          TEXT    NOT NULL DEFAULT '',         -- 发件人（mailbox@host）
    recipients      TEXT    NOT NULL DEFAULT '[]',       -- JSON array（D3 阶段先存空）
    received_at     INTEGER NOT NULL,                    -- Unix epoch ms（IMAP 协议无 tz）
    raw_size        INTEGER NOT NULL DEFAULT 0,          -- 字节数
    body_text       TEXT    NOT NULL DEFAULT '',         -- plain text（D3 阶段先不下载 body）
    body_html       TEXT    NOT NULL DEFAULT '',         -- html（D3 阶段先不下载 body）
    fetched_at      INTEGER NOT NULL,                    -- 入库时间（Unix epoch ms）
    labels          TEXT    NOT NULL DEFAULT '[]',       -- JSON array of label names
    UNIQUE(source, message_id)
);

CREATE INDEX IF NOT EXISTS idx_emails_received_at ON emails(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_source_received ON emails(source, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);


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
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event           TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT '',
    detail          TEXT    NOT NULL DEFAULT '{}',      -- JSON
    created_at      INTEGER NOT NULL                     -- Unix epoch ms
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON audit_log(event);
