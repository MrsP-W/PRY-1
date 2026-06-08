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
    - **JSON 字段**：recipients / labels 存 TEXT，Model 层 `JSONList` TypeDecorator
        做序列化（D3 阶段实际存空 list 即可，API 先实现）

注意：
    - 本文件 **不** import `db.py`（避免循环依赖；alembic env.py 负责连接）
    - Model 用 declarative_base() 必须能被 alembic 反射到 metadata
    - 6 个 Model 都注册到同一个 `Base`（一个 metadata）
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ===== Base =====


class Base(DeclarativeBase):
    """所有 Model 的基类（共享 metadata，alembic 反射用）。"""

    pass


# ===== 字段类型辅助 =====


class JSONList:
    """JSON list 字段 type decorator（D3 阶段简化版：用 SA 内置 JSON）。

    设计：
        - 用 SQLAlchemy 内置 `JSON` 类型（SQLite 走 TEXT 存 JSON 文本）
        - D3.3 同步脚本写入 list[recipient] / list[label_name]
        - 读取时 ORM 自动 json.loads 还原
    """

    pass


# 注：D3 阶段 Model 用内置 JSON 即可（无需自定义 TypeDecorator）
# 显式标注用：Mapped[list[str]] = mapped_column(JSON, default=list)
# 此处只预留一个具名常量供未来扩展
JSON_FIELD = JSON


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
    message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    sender: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    recipients: Mapped[list[str]] = mapped_column(
        JSON_FIELD, nullable=False, default=list, server_default="[]"
    )
    received_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    body_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    body_html: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    fetched_at: Mapped[int] = mapped_column(Integer, nullable=False)
    labels: Mapped[list[str]] = mapped_column(
        JSON_FIELD, nullable=False, default=list, server_default="[]"
    )

    # 关系
    attachments: Mapped[list[Attachment]] = relationship(
        "Attachment",
        back_populates="email",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    email_labels: Mapped[list[EmailLabel]] = relationship(
        "EmailLabel",
        back_populates="email",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # 约束 + 索引
    __table_args__ = (
        UniqueConstraint("source", "uid", name="uq_emails_source_uid"),
        Index("idx_emails_received_at", "received_at"),
        Index("idx_emails_source_received", "source", "received_at"),
        Index("idx_emails_sender", "sender"),
        Index("idx_emails_message_id", "message_id"),
    )

    def __repr__(self) -> str:
        return f"<Email id={self.id} source={self.source!r} uid={self.uid} subject={self.subject!r}>"


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
    filename: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    content_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    local_path: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    sha256: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )

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
    SQLAlchemy 用 `Column(..., sqlite_collation="NOCASE")`（D3.2 简化版省略，
    实际唯一性由应用层负责 — D3 阶段标签量小）。
    """

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
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
    last_uid: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    last_error: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
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
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    detail: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)

    # 索引
    __table_args__ = (
        Index("idx_audit_log_created_at", "created_at"),
        Index("idx_audit_log_event", "event"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} event={self.event!r} source={self.source!r}>"


# ===== 模块导出 =====


__all__ = [
    "Base",
    "Email",
    "Attachment",
    "Label",
    "EmailLabel",
    "SyncState",
    "AuditLog",
]


# ===== 自检（开发期） =====


def list_tables() -> list[str]:
    """列出所有 Model 注册的表名（调试 / 测试用）。"""
    return sorted(Base.metadata.tables.keys())


def to_dict(obj: Any) -> dict[str, Any]:
    """ORM 对象 → dict（D3.3 同步脚本批量入库用）。

    跳过 SQLAlchemy 内部状态（_sa_instance_state）。
    处理 JSON 字段：recipients / labels 已经是 list[dict]，直接序列化。
    """
    result: dict[str, Any] = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.name)
        # JSON 字段已经由 SQLAlchemy JSON 类型自动处理（list ↔ JSON 文本）
        result[col.name] = value
    return result
