"""D3.2 — SQLAlchemy 2.0 ORM 模型（6 个 Model 类）。

设计（[docs/week1-mvp.md §D3.2 ORM + Migrations]）：

    - **6 个 Model**：Email / Attachment / Label / EmailLabel / SyncState / AuditLog
        - 完全 mirror schema.sql（D3.1）的字段和约束
        - 字段类型 / nullable / default / index 与 schema.sql 1:1 对应
    - **关系**：
        - Email.attachments (1→N) / Email.labels (M→N via EmailLabel)
        - Attachment.email (N→1)
        - Label.emails (M→N via EmailLabel)
        - EmailLabel.email + EmailLabel.label (多对多关联表)
    - **级联**：Attachment / EmailLabel 配 `cascade="all, delete-orphan"`
        （对应 schema.sql 的 `ON DELETE CASCADE` FK）
    - **时间字段**：epoch ms INTEGER（D3 阶段不引入 datetime / 时区复杂性）
    - **JSON 字段**：recipients / labels 存 TEXT，Model 层 `JSONList` TypeDecorator[Any]
        做序列化（D3 阶段实际存空 list[Any] 即可，API 先实现）

注意：
    - 本文件 **不** import `db.py`（避免循环依赖；alembic env.py 负责连接）
    - Model 用 declarative_base() 必须能被 alembic 反射到 metadata
    - 6 个 Model 都注册到同一个 `Base`（一个 metadata）
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

# ===== Base =====


class Base(DeclarativeBase):
    """所有 Model 的基类（共享 metadata，alembic 反射用）。"""

    pass


# ===== 字段类型辅助 =====


class JSONList(TypeDecorator[Any]):
    """list[Any] ↔ JSON 文本（D3 阶段 mirror schema.sql TEXT DEFAULT '[]'）。

    设计：
        - DDL 层面是 TEXT（D3.1 schema.sql 决策 — 避免 SQLAlchemy JSON 在 SQLite
          走 TEXT 存 JSON 文本时和 schema.sql 不一致；schema.sql 是真理之源）
        - ORM 层面是 list[str]（TypeDecorator[Any] 透明处理 dumps/loads）
        - server_default="[]"（DDL） + default=list[Any]（Python）配对

    用法：
        recipients: Mapped[list[str]] = mapped_column(
            JSONList, nullable=False, default=list[Any], server_default="[]"
        )
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: list[Any] | None, dialect: Any) -> str | None:
        """ORM → DB：list[Any] 序列化为 JSON 文本。None → None（用 NULL 还是 [] 看业务）。"""
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value: str | None, dialect: Any) -> list[Any]:
        """DB → ORM：JSON 文本 → list[Any]。空字符串/None 一律视作 []。"""
        if not value:
            return []
        result = json.loads(value)
        if isinstance(result, list):
            return result
        return []


# 别名（保持与之前 D3.2.0 JSON_FIELD 命名兼容 — 内部用更准确的 JSONList）
JSON_FIELD = JSONList


class BytesToStr(TypeDecorator[str]):
    """bytes/str → TEXT(utf-8 decode, errors="replace")。

    设计动机(D13.x P0 修复,2026-07-07,撞坑 #71 业务代码改动日破例):
        - sqlcipher3 driver 对 TEXT 列返回 bytes(不是 str,跟 pysqlcipher3 加密层行为有关)
        - imapclient 3.x ENVELOPE 字段也是 bytes(subject / from_.mailbox / host / message_id)
        - SQLAlchemy ORM `Mapped[str]` 期望 str,实际拿到 bytes
        - 下游 classifier.classify 严判 `type(subject) is not str` → ValueError → classify_failed

    范本(JSONList TypeDecorator):
        - impl = Text(DDL 不变,schema.sql 不改,alembic 不生成迁移)
        - cache_ok = True(类型缓存安全 — impl 不变)
        - process_bind_param: ORM → DB,bytes/str → utf-8 str
        - process_result_value: DB → ORM,bytes → utf-8 str(防御 sqlcipher3 driver 返回 bytes)

    用途:
        subject: Mapped[str] = mapped_column(BytesToStr, nullable=False, default="", server_default="")
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        """ORM → DB:bytes/str 统一 utf-8 编码为 str。None → None。"""
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        """DB → ORM:bytes 自动 decode(防御 sqlcipher3 driver)。str 透传。None 透传。"""
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)


# ===== 1. Email =====


class Email(Base):
    """邮件主表（mirror schema.sql emails）。

    字段注解（[core/schema.sql emails](../../schema.sql)）：
        - id:           INTEGER PK AUTOINCREMENT
        - source:       TEXT NOT NULL          # "qq" / "outlook" / "gmail"
        - uid:          INTEGER NOT NULL       # IMAP UID（协议级唯一）
        - message_id:   TEXT                   # RFC 5322 Message-ID（可空）
        - subject:      TEXT NOT NULL DEFAULT ''
        - sender:       TEXT NOT NULL DEFAULT ''
        - recipients:   JSON  NOT NULL DEFAULT []  # list[str]
        - received_at:  INTEGER                # Unix epoch ms（可空）
        - raw_size:     INTEGER NOT NULL DEFAULT 0
        - body_text:    TEXT NOT NULL DEFAULT ''
        - body_html:    TEXT NOT NULL DEFAULT ''
        - fetched_at:   INTEGER NOT NULL       # Unix epoch ms
        - labels:       JSON  NOT NULL DEFAULT []  # list[str]（D3 阶段实际存空）

    约束：
        - UNIQUE(source, uid)
    索引：
        - idx_emails_received_at (received_at DESC)
        - idx_emails_source_received (source, received_at DESC)
        - idx_emails_sender (sender)
        - idx_emails_message_id (message_id)
    """

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    uid: Mapped[int] = mapped_column(Integer, nullable=False)
    # ⚠️ D13.x P0 修复(2026-07-07,撞坑 #71 业务代码改动日破例):
    # 改用 BytesToStr TypeDecorator 防御 sqlcipher3 driver 对 TEXT 列返回 bytes 的问题。
    # 配合 connect.imap._envelope_to_dict 的 _to_str helper,入库前 + 读取后双层 decode。
    # DDL 不变(impl=Text),alembic 不生成迁移。
    message_id: Mapped[str | None] = mapped_column(BytesToStr, nullable=True)
    subject: Mapped[str] = mapped_column(BytesToStr, nullable=False, default="", server_default="")
    sender: Mapped[str] = mapped_column(BytesToStr, nullable=False, default="", server_default="")
    recipients: Mapped[list[str]] = mapped_column(
        JSONList, nullable=False, default=list[Any], server_default="[]"
    )
    received_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    body_text: Mapped[str] = mapped_column(
        BytesToStr, nullable=False, default="", server_default=""
    )
    body_html: Mapped[str] = mapped_column(
        BytesToStr, nullable=False, default="", server_default=""
    )
    fetched_at: Mapped[int] = mapped_column(Integer, nullable=False)
    labels: Mapped[list[str]] = mapped_column(
        JSONList, nullable=False, default=list[Any], server_default="[]"
    )

    # 关系
    attachments: Mapped[list[Attachment]] = relationship(
        "Attachment",
        back_populates="email",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # 多对多规范化（关系表 EmailLabel）— D4+ 复杂 join / 级联删除用
    # 与上方 JSON 字段 labels 互为冗余：JSON 快速过滤、EmailLabel 规范化 join
    email_labels: Mapped[list[EmailLabel]] = relationship(
        "EmailLabel",
        back_populates="email",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # 约束 + 索引（DESC 倒序与 D3.1 schema.sql 对齐：D3 阶段热路径"按时间倒序取最近邮件"）
    __table_args__ = (
        UniqueConstraint("source", "uid", name="uq_emails_source_uid"),
        Index("idx_emails_received_at", text("received_at DESC")),
        Index(
            "idx_emails_source_received",
            "source",
            text("received_at DESC"),
        ),
        Index("idx_emails_sender", "sender"),
        Index("idx_emails_message_id", "message_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Email id={self.id} source={self.source!r} uid={self.uid} subject={self.subject!r}>"
        )


# ===== 2. Attachment =====


class Attachment(Base):
    """附件元数据（mirror schema.sql attachments）。

    字段注解：
        - id:           INTEGER PK AUTOINCREMENT
        - email_id:     INTEGER NOT NULL          # FK → emails.id
        - filename:     TEXT NOT NULL DEFAULT ''
        - content_type: TEXT NOT NULL DEFAULT ''
        - size:         INTEGER NOT NULL DEFAULT 0
        - local_path:   TEXT NOT NULL DEFAULT ''
        - sha256:       TEXT NOT NULL DEFAULT ''

    约束：
        - FK email_id → emails.id ON DELETE CASCADE（schema.sql 已配）
    索引：
        - idx_attachments_email_id
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("emails.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    content_type: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    local_path: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    sha256: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    # 关系
    email: Mapped[Email] = relationship("Email", back_populates="attachments")

    # 索引
    __table_args__ = (Index("idx_attachments_email_id", "email_id"),)

    def __repr__(self) -> str:
        return f"<Attachment id={self.id} email_id={self.email_id} filename={self.filename!r}>"


# ===== 3. Label =====


class Label(Base):
    """标签字典（mirror schema.sql labels）。

    字段注解：
        - id:      INTEGER PK AUTOINCREMENT
        - name:    TEXT NOT NULL  # COLLATE NOCASE
        - source:  TEXT NOT NULL DEFAULT 'system'  # "qq" / "system" / "user"
        - color:   TEXT NOT NULL DEFAULT '#808080'

    约束：
        - UNIQUE(name, source)
    索引：
        - idx_labels_source

    注：SQLite 的 COLLATE NOCASE 在 schema.sql 是列级 collation，
    SQLAlchemy 正确写法：`sa.Text(collation="NOCASE")`（collation 是类型参数，
    **不是** `Column(..., sqlite_collation=...)` —— 后者会报
    `ArgumentError: 'sqlite_collation' is not accepted by dialect 'sqlite'`）。

    唯一性：UNIQUE(name, source) + name COLLATE NOCASE → "Inbox" 和 "inbox" 视为同名
    """

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        Text(collation="NOCASE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="system", server_default="system"
    )
    color: Mapped[str] = mapped_column(
        Text, nullable=False, default="#808080", server_default="#808080"
    )

    # 关系
    email_labels: Mapped[list[EmailLabel]] = relationship(
        "EmailLabel",
        back_populates="label",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # 约束 + 索引
    __table_args__ = (
        UniqueConstraint("name", "source", name="uq_labels_name_source"),
        Index("idx_labels_source", "source"),
    )

    def __repr__(self) -> str:
        return f"<Label id={self.id} name={self.name!r} source={self.source!r}>"


# ===== 4. EmailLabel（多对多关联表）=====


class EmailLabel(Base):
    """多对多关联表（mirror schema.sql email_labels）。

    字段注解：
        - email_id: INTEGER NOT NULL  # PK + FK → emails.id
        - label_id: INTEGER NOT NULL  # PK + FK → labels.id

    约束：
        - PRIMARY KEY (email_id, label_id)
        - FK email_id → emails.id ON DELETE CASCADE
        - FK label_id → labels.id ON DELETE CASCADE

    索引：
        - idx_email_labels_label_id（schema.sql 中只对 label_id 建索引）
    """

    __tablename__ = "email_labels"

    email_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("emails.id", ondelete="CASCADE"),
        primary_key=True,
    )
    label_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("labels.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # 关系
    email: Mapped[Email] = relationship("Email", back_populates="email_labels")
    label: Mapped[Label] = relationship("Label", back_populates="email_labels")

    # 索引
    __table_args__ = (Index("idx_email_labels_label_id", "label_id"),)

    def __repr__(self) -> str:
        return f"<EmailLabel email_id={self.email_id} label_id={self.label_id}>"


# ===== 5. SyncState =====


class SyncState(Base):
    """增量同步游标（mirror schema.sql sync_state）。

    字段注解：
        - id:                   INTEGER PK AUTOINCREMENT
        - source:               TEXT NOT NULL UNIQUE  # "qq" / "outlook" / "gmail"
        - last_sync_at:         INTEGER NOT NULL DEFAULT 0  # Unix epoch ms
        - last_uid:             INTEGER NOT NULL DEFAULT 0
        - last_status:          TEXT NOT NULL DEFAULT 'pending'  # "ok" / "failed" / "pending"
        - last_error:           TEXT NOT NULL DEFAULT ''
        - consecutive_failures: INTEGER NOT NULL DEFAULT 0
        - updated_at:           INTEGER NOT NULL  # Unix epoch ms

    约束：
        - UNIQUE(source)
    """

    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    last_sync_at: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_uid: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<SyncState source={self.source!r} "
            f"last_sync_at={self.last_sync_at} status={self.last_status!r}>"
        )


# ===== 6. AuditLog =====


class AuditLog(Base):
    """审计日志（mirror schema.sql audit_log）。

    字段注解：
        - id:         INTEGER PK AUTOINCREMENT
        - event:      TEXT NOT NULL  # "sync_started" / "sync_completed" / ...
        - source:     TEXT NOT NULL DEFAULT ''
        - detail:     TEXT NOT NULL DEFAULT '{}'  # JSON 字符串（D3 阶段不展开）
        - created_at: INTEGER NOT NULL  # Unix epoch ms

    索引：
        - idx_audit_log_created_at (created_at DESC)
        - idx_audit_log_event
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)

    # 索引（DESC 倒序与 D3.1 schema.sql 对齐：审计日志热路径"按时间倒序取最近事件"）
    __table_args__ = (
        Index("idx_audit_log_created_at", text("created_at DESC")),
        Index("idx_audit_log_event", "event"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} event={self.event!r} source={self.source!r}>"


# ===== 7. ApprovalGateAudit(v0.2.53.51 — 沿 v0.2.53.20 §5.3 落档 design)=====


class ApprovalGateAudit(Base):
    """ApprovalGate 写操作审计日志(mirror schema.sql approval_gate_audits).

    字段注解([docs/v0.2.53.20-html-real-write-flow-design-2026-06-26.md §5.3]):
        - id:              INTEGER PK AUTOINCREMENT
        - action:          TEXT NOT NULL              # approve_outbox / cancel_outbox / confirm_note / dismiss_anomaly
        - target_id:       TEXT NOT NULL              # str 表示的 int / str 本身
        - actor:           TEXT NOT NULL DEFAULT 'local_dashboard'  # 审计字段(沿 v0.2.53.11 actor 默认值)
        - reason:          TEXT NOT NULL DEFAULT ''   # 用户操作原因(限 240 字符,AuditContext 严判)
        - write_executed:  INTEGER NOT NULL            # 0=False, 1=True(BOOLEAN → Integer, 沿 D3.2 雷区 #2)
        - affected_id:     TEXT NULL                   # 成功时填(str 表示的 int / str 本身)
        - error:           TEXT NULL                   # 失败时填(error code 字符串)
        - executed_at_ms:  INTEGER NOT NULL            # ms 时间戳(沿现有 store 范本)

    索引:
        - idx_audit_executed_at (executed_at_ms DESC) — 按时间倒序查询热路径(Dashboard /api/approval-gate/audits)
        - idx_audit_action_at (action, executed_at_ms DESC) — 按 action 过滤 + 时间倒序

    撞坑 #64 公共 API 一致性:
        - 字段顺序与 alembic 0016 migration 严格对齐
        - audit_id 字符串格式 "audit:{id}"(撞坑 #64 范本)
    """

    __tablename__ = "approval_gate_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(
        Text, nullable=False, default="local_dashboard", server_default="local_dashboard"
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    write_executed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    affected_id: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    executed_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # 索引(DESC 倒序与 0016 migration 对齐:Dashboard 审计热路径"按时间倒序取最近")
    __table_args__ = (
        Index("idx_audit_executed_at", text("executed_at_ms DESC")),
        Index("idx_audit_action_at", "action", text("executed_at_ms DESC")),
    )

    def __repr__(self) -> str:
        return (
            f"<ApprovalGateAudit id={self.id} action={self.action!r} "
            f"target_id={self.target_id!r} write_executed={self.write_executed}>"
        )


# ===== 模块导出 =====


__all__ = [
    "ApprovalGateAudit",
    "AuditLog",
    "Base",
    "Email",
    "Attachment",
    "EmailLabel",
    "Label",
    "SyncState",
]


# ===== 自检（开发期） =====


def list_tables() -> list[str]:
    """列出所有 Model 注册的表名（调试 / 测试用）。"""
    return sorted(Base.metadata.tables.keys())


def to_dict(obj: Any) -> dict[str, Any]:
    """ORM 对象 → dict[Any, Any]（D3.3 同步脚本批量入库用）。

    跳过 SQLAlchemy 内部状态（_sa_instance_state）。
    处理 JSON 字段：recipients / labels 已由 JSONList TypeDecorator[Any]
    转换为 list[Any]（DDL 走 TEXT，ORM 走 list[Any] ↔ JSON 文本）— 直接序列化。
    """
    result: dict[str, Any] = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.name)
        # JSONList TypeDecorator[Any] 已完成 list[Any] ↔ JSON 文本的转换（D3.2.3 修复）
        result[col.name] = value
    return result
