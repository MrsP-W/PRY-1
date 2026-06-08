"""D3.2 首次迁移 — 6 张表 + 9 索引（mirror schema.sql）。

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-07

源：[src/my_ai_employee/core/schema.sql](../../schema.sql)（D3.1 v1.1）

注意：
    - SQLite 不支持原生 `ALTER TABLE ... DROP COLUMN`（render_as_batch=True 自动改写）
    - `render_as_batch=True` 在 env.py 已配
    - 用 `sa.JSON()` 存 recipients / labels（D3 阶段简化版）
    - 用 `sa.Column(... , sqlite_collation="NOCASE")` 给 labels.name COLLATE NOCASE
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== emails =====
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("uid", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("sender", sa.Text(), nullable=False, server_default=""),
        sa.Column("recipients", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("received_at", sa.Integer(), nullable=True),
        sa.Column("raw_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
        sa.Column("fetched_at", sa.Integer(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("source", "uid", name="uq_emails_source_uid"),
    )
    op.create_index("idx_emails_received_at", "emails", ["received_at"])
    op.create_index(
        "idx_emails_source_received", "emails", ["source", "received_at"]
    )
    op.create_index("idx_emails_sender", "emails", ["sender"])
    op.create_index("idx_emails_message_id", "emails", ["message_id"])

    # ===== attachments =====
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "email_id",
            sa.Integer(),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_type", sa.Text(), nullable=False, server_default=""),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("local_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("sha256", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("idx_attachments_email_id", "attachments", ["email_id"])

    # ===== labels =====
    # labels.name 用 sqlite_collation="NOCASE"（D3.1 schema.sql 决策）
    op.create_table(
        "labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "name",
            sa.Text(),
            nullable=False,
            sqlite_collation="NOCASE",
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="system"),
        sa.Column("color", sa.Text(), nullable=False, server_default="#808080"),
        sa.UniqueConstraint("name", "source", name="uq_labels_name_source"),
    )
    op.create_index("idx_labels_source", "labels", ["source"])

    # ===== email_labels（多对多关联表）=====
    op.create_table(
        "email_labels",
        sa.Column(
            "email_id",
            sa.Integer(),
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "label_id",
            sa.Integer(),
            sa.ForeignKey("labels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("idx_email_labels_label_id", "email_labels", ["label_id"])

    # ===== sync_state =====
    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=False, unique=True),
        sa.Column("last_sync_at", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_uid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("updated_at", sa.Integer(), nullable=False),
    )

    # ===== audit_log =====
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Integer(), nullable=False),
    )
    op.create_index("idx_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("idx_audit_log_event", "audit_log", ["event"])


def downgrade() -> None:
    # 倒序 drop（依赖关系反向）
    op.drop_index("idx_audit_log_event", table_name="audit_log")
    op.drop_index("idx_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_table("sync_state")

    op.drop_index("idx_email_labels_label_id", table_name="email_labels")
    op.drop_table("email_labels")

    op.drop_index("idx_labels_source", table_name="labels")
    op.drop_table("labels")

    op.drop_index("idx_attachments_email_id", table_name="attachments")
    op.drop_table("attachments")

    op.drop_index("idx_emails_message_id", table_name="emails")
    op.drop_index("idx_emails_sender", table_name="emails")
    op.drop_index("idx_emails_source_received", table_name="emails")
    op.drop_index("idx_emails_received_at", table_name="emails")
    op.drop_table("emails")
