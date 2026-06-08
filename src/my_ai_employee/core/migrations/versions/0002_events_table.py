"""D4.3 迁移 — events 表（g004 4 大不变量结构化事件流）。

Revision ID: 0002_events
Revises: 0001_initial
Create Date: 2026-06-08

源: [src/my_ai_employee/core/schema.sql §events](../../schema.sql) (D4.3 新增段)

设计:
    - 不动 audit_log (D3 sync 审计保留)
    - events 表 7 字段 + 1 UNIQUE 约束 + 6 索引
    - DDL 走 TEXT (DDL 真理之源), ORM 用 JSONDict TypeDecorator 透明处理 metadata
    - fingerprint 提为独立列(物理去重键), 与 metadata.fingerprint 冗余(应用层引用)
    - 索引顺序: created_at DESC > event > status > source > subject_id > fingerprint
    - UNIQUE(event, source, subject_id, fingerprint) → 同 fingerprint 重复写入去重

D3.2 沿用约定:
    - render_as_batch=True 在 env.py 已配
    - recipients/labels/metadata 用 sa.Text() + server_default, ORM 走 JSONList/JSONDict TypeDecorator
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_events"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== events (D4.3 新增) =====
    # 7 字段 + 1 UNIQUE 约束
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # event: EventType 枚举值 (typed name, g004 不变量 1)
        sa.Column("event", sa.Text(), nullable=False),
        # status: EventStatus 7 枚举之一 (g004 不变量 2)
        sa.Column("status", sa.Text(), nullable=False),
        # source: 事件源头 (e.g. "minimax" / "mcp.filesystem" / "classifier")
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
        # subject_id: 关联实体 ID (e.g. email_id / llm_request_id / task_id, 可空)
        sa.Column("subject_id", sa.Text(), nullable=True),
        # fingerprint: SHA-256 派生键(物理去重键, g004 不变量 4)
        # 冗余于 metadata.fingerprint(JSON 内字段), 但 DDL 独立列才能做 UNIQUE 约束
        sa.Column("fingerprint", sa.Text(), nullable=False, server_default=""),
        # event_metadata: JSON 必含 6 字段 (g004 不变量 3: seq/timestamp_ms/session_id/ownership/provenance/fingerprint)
        # ORM 走 JSONDict TypeDecorator 透明处理 dict ↔ JSON 文本
        # 列名 event_metadata 避开 SQLAlchemy Declarative 保留属性 metadata
        sa.Column("event_metadata", sa.Text(), nullable=False, server_default="{}"),
        # created_at: Unix epoch ms (冗余于 metadata.timestamp_ms, 便于排序)
        sa.Column("created_at", sa.Integer(), nullable=False),
        # UNIQUE 约束: 同 fingerprint 重复写入去重 (g004 不变量 4)
        sa.UniqueConstraint(
            "event",
            "source",
            "subject_id",
            "fingerprint",
            name="uq_events_event_source_subject_fingerprint",
        ),
    )
    # 6 索引 (热路径: 倒序拉最近事件)
    op.create_index("idx_events_created_at", "events", [sa.text("created_at DESC")])
    op.create_index("idx_events_event", "events", ["event"])
    op.create_index("idx_events_status", "events", ["status"])
    op.create_index("idx_events_source", "events", ["source"])
    op.create_index("idx_events_subject_id", "events", ["subject_id"])
    op.create_index("idx_events_fingerprint", "events", ["fingerprint"])


def downgrade() -> None:
    # 倒序 drop (依赖关系反向)
    op.drop_index("idx_events_fingerprint", table_name="events")
    op.drop_index("idx_events_subject_id", table_name="events")
    op.drop_index("idx_events_source", table_name="events")
    op.drop_index("idx_events_status", table_name="events")
    op.drop_index("idx_events_event", table_name="events")
    op.drop_index("idx_events_created_at", table_name="events")
    op.drop_table("events")
