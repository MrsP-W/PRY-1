"""v0.2.1 #5 NoteStore L2/L3 跨源去重迁移 — notes 表加 normalized_fingerprint 列。

Revision ID: 0013_note_fingerprint
Revises: 0012_note_sync_status
Create Date: 2026-06-17

承接 v0.2.1 启动候选 #5 NoteStore L2/L3 跨源去重(沿 [[v0.2.1-candidates-2026-06-17]] §6)。
本迁移设计:notes 表加 normalized_fingerprint 列(可空,旧 notes 条目 NULL)+ idx_notes_fingerprint 索引。

业务背景(沿 [[v0.2.1-candidates-2026-06-17]] §6.2 L2/L3 去重模型):
    v0.2.1 #5 启动: Note L2/L3 跨源去重
        - L1 源内幂等(UNIQUE(apple_note_id))— D9.1 已落
        - L2 跨源候选(INDEX(normalized_fingerprint))— 本轮新增
        - L3 模糊匹配(商家名 + 日期 ±1 天)— 后续迭代

    fingerprint 派生字段(Note 专用):
        1. title 归一化: strip + lower(防 "Meeting" vs "meeting")
        2. folder 归一化: strip + lower
        3. updated_at_ms date 归一化: YYYY-MM-DD(只取日期,忽略时分秒)

    沿 D6.4 transactions 范本:
        - transactions fingerprint: date + amount + counterparty(SHA-256 前 32 chars)
        - notes fingerprint: title + folder + updated_at_date(SHA-256 前 32 chars)
        - NoteStore.find_candidates_by_fingerprint(fingerprint) 找跨源候选

字段选型:
    normalized_fingerprint TEXT NULL  # 旧 notes 条目 NULL(异步 job 算),新条目同步写

索引:
    idx_notes_fingerprint(normalized_fingerprint) — L2 跨源候选查询热路径

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本字段非金额)
    2. BOOLEAN 走 Integer + server_default="0" — N/A(本字段非 BOOLEAN)
    3. DATE 走 Date — N/A(本字段用 ms INTEGER)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)— N/A(本字段是 TEXT 加列)
    5. 文件名 0013_note_fingerprint.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("...")— 本索引无 DESC,无影响

D3.3.3 教训应用:
    - 本迁移无 DML 异常风险(纯 DDL,ALTER TABLE + CREATE INDEX)
    - 应用层 NoteStore.find_candidates_by_fingerprint 严判 fingerprint 32 chars hex

D4.7.3 教训应用:
    - type 严判在 hash 操作前(fingerprint 白名单 32 chars hex)
    - 公共 API 入口严判 + 数据类 __post_init__ 双层防御

固化哲学(沿 D5.6.3 P1-1 范本):
    - migration + ORM + Store 3 处改动同 commit 提交
    - Note.normalized_fingerprint 字段已加(db/notes.py)
    - NoteStore.insert 自动派生 fingerprint
    - NoteStore.find_candidates_by_fingerprint 新方法
    - 本 alembic migration(0013_note_fingerprint.py)
    5 处同 commit 落地

v0.2.1 #5 范围边界:
    - 本轮只做 L2(INDEX 跨源候选查询),L3 模糊匹配留 v0.2.2+
    - 本轮不动 NoteStructurerService(下个候选接入)
    - 本轮不动 NoteStore L2 跨源写入(insert 时自动派生)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_note_fingerprint"
down_revision: str | Sequence[str] | None = "0012_note_sync_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v0.2.1 #5: notes 表加 normalized_fingerprint 列(可空)+ idx_notes_fingerprint 索引。

    SQLite ALTER TABLE 限制(沿 env.py render_as_batch=True):
        - ADD COLUMN 支持 NULL(同步填充旧 row 为 NULL)
        - 旧 notes 表 row 填 normalized_fingerprint=NULL
        - 应用层 NoteStore.insert 自动派生(新写入 row 必填)
    """
    # ===== normalized_fingerprint 列 =====
    op.add_column(
        "notes",
        sa.Column(
            "normalized_fingerprint",
            sa.Text(),
            nullable=True,
            default=None,
            server_default=None,
        ),
    )

    # ===== idx_notes_fingerprint 索引 =====
    # L2 跨源候选查询热路径:
    #   find_candidates_by_fingerprint(fingerprint) → 同 fingerprint 跨 source notes
    #   注意:L1 UNIQUE(apple_note_id) 已存在,L2 用 INDEX(非 UNIQUE,跨源可能重复)
    op.create_index(
        "idx_notes_fingerprint",
        "notes",
        ["normalized_fingerprint"],
    )


def downgrade() -> None:
    """v0.2.1 #5: 删除 normalized_fingerprint 列 + idx_notes_fingerprint 索引(干净回滚)。

    顺序与 upgrade 相反:索引 → 列。
    """
    op.drop_index("idx_notes_fingerprint", table_name="notes")
    op.drop_column("notes", "normalized_fingerprint")
