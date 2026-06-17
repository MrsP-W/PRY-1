"""v0.2.1 #4 NoteStore 状态机化迁移 — notes 表加 sync_status 列。

Revision ID: 0012_note_sync_status
Revises: 0011_merchant_profile
Create Date: 2026-06-17

承接 v0.2.1 启动候选 #4 NoteStore 状态机化(沿 [[v0.2.1-candidates-2026-06-17]] §5)。
本迁移设计:notes 表加 sync_status 列(默认 'NEW')+ idx_notes_sync_status 索引。

业务背景(沿 [[v0.2.1-candidates-2026-06-17]] §5.2 状态机设计):
    v0.2.1 #4 启动: Note 状态机 5 状态
        - NEW(初始入库,默认)
        - STRUCTURED(LLM 结构化完成,结构化 tags 已写入)
        - PRIVATE_SKIP(私人笔记业务阻断,沿 D9.6 业务阻断范本)
        - FAILED(LLM 失败,沿 D4.7.3 v1.0.6 技术失败入口)
        - ARCHIVED(用户归档,终态)

    状态转换:
        NEW → STRUCTURED    (mark_structured, 成功路径)
        NEW → PRIVATE_SKIP  (mark_private_skip, is_private=True 触发)
        NEW → FAILED        (mark_failed, LLM/DB 错误触发)
        FAILED → STRUCTURED (mark_structured, 重试成功)
        STRUCTURED → ARCHIVED (mark_archived, 用户主动归档)
        其他转换 → ValueError(状态机守卫)

字段选型:
    sync_status TEXT NOT NULL DEFAULT 'NEW'  # 5 状态枚举

索引:
    idx_notes_sync_status(sync_status) — 按状态过滤热路径(月报统计 + 失败重试)

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本字段非金额)
    2. BOOLEAN 走 Integer + server_default="0/1" — N/A(本字段非 BOOLEAN,走 TEXT 状态字符串)
    3. DATE 走 Date — N/A(本字段非日期)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)— N/A(本字段是 TEXT 加列)
    5. 文件名 0012_note_sync_status.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("...")— 本索引无 DESC,无影响

D3.3.3 教训应用:
    - 本迁移无 DML 异常风险(纯 DDL,ALTER TABLE + CREATE INDEX)
    - 应用层 NoteStore 状态转换方法严判 state machine 守卫(D6.6 P2 修复范本)

D4.7.3 教训应用:
    - type 严判在 hash 操作前(状态枚举白名单)
    - 公共 API 入口严判 + 数据类 `__post_init__` 双层防御
    - 状态机守卫: 拒绝非法状态转换(NEW → ARCHIVED 直接报 ValueError)

固化哲学(沿 D5.6.3 P1-1 范本):
    - migration + ORM + Store 3 处改动同 commit 提交
    - Note.sync_status 字段已加(db/notes.py)
    - NoteStore 新增 3 方法(mark_private_skip / mark_failed / mark_archived)
    - NoteStore.mark_structured 扩展同步 sync_status='STRUCTURED'
    - 本 alembic migration(0012_note_sync_status.py)
    5 处同 commit 落地

v0.2.1 #4 范围边界:
    - 本轮不动 NoteStore L2/L3 跨源去重(在 #5)
    - 本轮不动 NoteStructurerService 接入(下个 commit)
    - 本轮不动 ExpenseServiceStub 实化(在 #3)
    - Store 层 mark_private_skip / mark_failed / mark_archived 严格守门状态机
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012_note_sync_status"
down_revision: str | Sequence[str] | None = "0011_merchant_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v0.2.1 #4: notes 表加 sync_status 列(默认 'NEW')+ idx_notes_sync_status 索引。

    SQLite ALTER TABLE 限制(沿 env.py render_as_batch=True):
        - ADD COLUMN 支持 NOT NULL + DEFAULT(同步填充所有旧 row)
        - 旧 notes 表 row 自动填 sync_status='NEW'
    """
    # ===== sync_status 列 =====
    op.add_column(
        "notes",
        sa.Column(
            "sync_status",
            sa.Text(),
            nullable=False,
            default="NEW",
            server_default="NEW",
        ),
    )

    # ===== idx_notes_sync_status 索引 =====
    # 按状态过滤热路径:
    #   - 月报统计: SELECT count(*) FROM notes WHERE sync_status = ?
    #   - 失败重试: SELECT * FROM notes WHERE sync_status = 'FAILED' ORDER BY synced_at_ms
    op.create_index(
        "idx_notes_sync_status",
        "notes",
        ["sync_status"],
    )


def downgrade() -> None:
    """v0.2.1 #4: 删除 sync_status 列 + idx_notes_sync_status 索引(干净回滚)。

    顺序与 upgrade 相反:索引 → 列(避免外键引用问题)。
    """
    op.drop_index("idx_notes_sync_status", table_name="notes")
    op.drop_column("notes", "sync_status")
