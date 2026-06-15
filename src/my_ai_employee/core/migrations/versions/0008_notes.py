"""D9.1 迁移 — notes 表(10 字段 + 完整版 schema).

Revision ID: 0008_notes
Revises: 0007_transactions
Create Date: 2026-06-15

承接 D6.4 0007_transactions + D7 跨源去重 + D9.1 启动。
本迁移设计:新建 notes 表(10 字段 + 1 UNIQUE 约束 + 2 INDEX)。

业务背景(沿 docs/v0.1-launch-plan.md §D9):
    D9 Apple Notes 同步链路落子层:
        - L1 源内幂等: UNIQUE(apple_note_id) — 业务阻断入口
        - is_private INTEGER 0/1 — 标记私密笔记,跳过 LLM(沿 D4.7.2 v1.0.6 SPAM 阻断范本)
        - tags TEXT — note_structurer 输出(逗号分隔)
        - attachments_json TEXT — 附件元数据 JSON 列表(不含二进制,避免 DB 膨胀)
        - folder TEXT — Apple Notes 文件夹名(默认 "Notes")

字段选型(10 列 + D3.2 8 雷区严判):
    1. id                    INTEGER PK AUTOINCREMENT
    2. apple_note_id         TEXT NOT NULL                  # Apple ID(L1 硬约束)
    3. folder                TEXT NOT NULL DEFAULT 'Notes'  # 文件夹名
    4. title                 TEXT NOT NULL DEFAULT ''       # 笔记标题
    5. body                  TEXT NOT NULL DEFAULT ''       # 笔记正文(HTML 转纯文本)
    6. attachments_json      TEXT NULL                      # 附件元数据 JSON list
    7. is_private            INTEGER NOT NULL DEFAULT 0    # 0/1 BOOLEAN 走 Integer(SQLite 无 BOOLEAN)
    8. tags                  TEXT NULL                      # note_structurer 输出(逗号分隔)
    9. synced_at_ms          INTEGER NOT NULL               # Unix epoch ms(同步时间)
    10. updated_at_ms        INTEGER NOT NULL               # Unix epoch ms(Apple 修改时间)

约束:
    - UNIQUE(apple_note_id) — L1 硬约束(防同源重复同步)

索引:
    - idx_notes_folder_synced(folder, synced_at_ms DESC) — 状态机热路径(按文件夹最新优先)
    - idx_notes_updated(updated_at_ms DESC) — 增量同步热路径(按 Apple 修改时间倒序)

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本表无金额字段)
    2. BOOLEAN 走 Integer + server_default="0"(SQLite 无 BOOLEAN 类型)
    3. DATE 走 Date(非 DateTime,指纹算法只取日期)— N/A(本表用 ms INTEGER)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)
    5. 文件名 0008_notes.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("synced_at_ms DESC")(D3.2.3 修复)

D3.3.3 教训应用:
    - 本迁移无 DML 异常风险(纯 DDL,CREATE TABLE + CREATE INDEX)
    - 应用层 NoteStore.insert 严判 IntegrityError 范围窄化(只接 UNIQUE 冲突)

D4.7.3 教训应用:
    - P1-1 跨字段校验: 应用层 _validate_* 严判 apple_note_id / folder / title / body
    - P1-2 双向强一致: is_private INTEGER(0/1) DDL 严判,BOOLEAN 走 Integer 是 SQLite 唯一可行方案
    - P2-1 type 严判: is_private bool 入参严判 type() is bool(非 int 子类陷阱)
    - P2-2 异常范围窄化(D3.3.3): NoteStore.insert 拒绝 SQLAlchemyError 基类
    - 固化哲学: migration + ORM + Store 3 处改动同 commit 提交(沿 D5.6.3 P1-1 范本)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_notes"
down_revision: str | Sequence[str] | None = "0007_transactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """D9.1:新建 notes 表(10 列 + UNIQUE + 2 INDEX)。"""
    # ===== notes (D9.1 新增) =====
    op.create_table(
        "notes",
        # 1. id: PK AUTOINCREMENT(D3.2 雷区 #4: 非 AUTO_INCREMENT)
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # 2. apple_note_id: Apple ID(L1 硬约束)
        # 严判 ^[a-zA-Z0-9._:-]{1,128}$ — 应用层 _validate_apple_note_id
        sa.Column("apple_note_id", sa.Text(), nullable=False),
        # 3. folder: 文件夹名(默认 "Notes")
        sa.Column("folder", sa.Text(), nullable=False, default="Notes", server_default="Notes"),
        # 4. title: 笔记标题(允许空字符串兜底)
        sa.Column("title", sa.Text(), nullable=False, default="", server_default=""),
        # 5. body: 笔记正文(HTML 转纯文本,允许空字符串)
        sa.Column("body", sa.Text(), nullable=False, default="", server_default=""),
        # 6. attachments_json: 附件元数据 JSON list(不含二进制)
        sa.Column("attachments_json", sa.Text(), nullable=True),
        # 7. is_private: 0/1 BOOLEAN 走 Integer(D3.2 雷区 #2)
        # 应用层严判 type() is bool(非 int 子类陷阱,沿 D4.7.3 v1.0.5 P2-1 范本)
        sa.Column(
            "is_private",
            sa.Integer(),
            nullable=False,
            default=0,
            server_default="0",
        ),
        # 8. tags: note_structurer 输出(逗号分隔,NULL 表示未结构化)
        sa.Column("tags", sa.Text(), nullable=True),
        # 9. synced_at_ms: 同步时间戳(必传 int >= 0)
        sa.Column("synced_at_ms", sa.Integer(), nullable=False),
        # 10. updated_at_ms: Apple 修改时间(必传 int >= 0)
        sa.Column("updated_at_ms", sa.Integer(), nullable=False),
        # UNIQUE 约束(L1 硬约束:apple_note_id 唯一)— 在 create_table 阶段直接声明
        # SQLite 不支持 ALTER CONSTRAINT(NotImplementedError),必须在建表时声明
        sa.UniqueConstraint("apple_note_id", name="uq_notes_apple_note_id"),
    )

    # ===== 索引(D3.2 雷区 #8: DESC 索引用 sa.text 包裹) =====
    # 状态机热路径:按文件夹最新优先
    op.create_index(
        "idx_notes_folder_synced",
        "notes",
        ["folder", sa.text("synced_at_ms DESC")],
    )
    # 增量同步热路径:按 Apple 修改时间倒序
    op.create_index(
        "idx_notes_updated",
        "notes",
        [sa.text("updated_at_ms DESC")],
    )


def downgrade() -> None:
    """D9.1:删除 notes 表(干净回滚).

    顺序与 upgrade 相反:索引 → 表(UNIQUE 约束在表里,drop_table 自动删除)
    """
    op.drop_index("idx_notes_updated", table_name="notes")
    op.drop_index("idx_notes_folder_synced", table_name="notes")
    op.drop_table("notes")
