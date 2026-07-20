"""AgentRun 持久化表。

Revision ID: 0018_agent_runs
Revises: 0017_codex_conversation_notes
Create Date: 2026-07-20

设计边界：
    - 仅新增 agent_runs，不触碰 outbox/events 既有行。
    - checkpoint/task_packet 以 JSON 文本存储；无密钥、无 SMTP 正文强制字段。
    - 不创建外键到 events（parent_event_id 软引用）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_agent_runs"
down_revision: str | Sequence[str] | None = "0017_codex_conversation_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 agent_runs 表与查询索引。"""
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("workflow", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="planned"),
        sa.Column("task_packet_json", sa.Text(), nullable=False),
        sa.Column("checkpoint_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("parent_event_id", sa.Integer(), nullable=True),
        sa.Column("created_at_ms", sa.Integer(), nullable=False),
        sa.Column("updated_at_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs"),
        sa.UniqueConstraint("run_id", name="uq_agent_runs_run_id"),
    )
    op.create_index("idx_agent_runs_trace", "agent_runs", ["trace_id"])
    op.create_index(
        "idx_agent_runs_status_updated",
        "agent_runs",
        ["status", sa.text("updated_at_ms DESC")],
    )


def downgrade() -> None:
    """删除 agent_runs。"""
    op.drop_index("idx_agent_runs_status_updated", table_name="agent_runs")
    op.drop_index("idx_agent_runs_trace", table_name="agent_runs")
    op.drop_table("agent_runs")
