"""为 Notes 增加 Codex 对话摘要来源隔离。

Revision ID: 0017_codex_conversation_notes
Revises: 0016_approval_gate_audits
Create Date: 2026-07-19

设计边界：
    - 仅新增 ``note_source``，旧笔记统一回填为 ``note``；不重写 title/body，
      因此不触碰任何已有明文或加密内容。
    - ``codex_conversation`` 只用于本地显式导入的会话摘要，查询走来源+更新时间索引。
    - 不创建外键、不读取 Codex 桌面端、不触发 Apple Notes 同步。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_codex_conversation_notes"
down_revision: str | Sequence[str] | None = "0016_approval_gate_audits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为旧 notes 行增加安全的默认来源，并创建当日查询索引。"""
    op.add_column(
        "notes",
        sa.Column(
            "note_source",
            sa.Text(),
            nullable=False,
            default="note",
            server_default="note",
        ),
    )
    op.create_index(
        "idx_notes_source_updated",
        "notes",
        ["note_source", sa.text("updated_at_ms DESC")],
    )


def downgrade() -> None:
    """移除来源列与索引；原笔记正文、标题和候选字段保持不变。"""
    op.drop_index("idx_notes_source_updated", table_name="notes")
    op.drop_column("notes", "note_source")
