"""v0.2.1+ NoteStore L2 跨源写入迁移 — notes 表加 needs_confirm + candidate_match_id 列.

Revision ID: 0014_note_l2_cross_source
Revises: 0013_note_fingerprint
Create Date: 2026-06-17

承接 [[v0.2.1-candidates-2026-06-17]] §9.4 NoteStore L2 跨源写入(沿 D9.6 留口业务落地):
    v0.2.1 #5 NoteStore L2/L3 跨源去重落地后,notes 表有 normalized_fingerprint 字段 + NoteStore.find_candidates_by_fingerprint 方法。
    本迁移添加 needs_confirm + candidate_match_id 字段,让 NoteStore.insert 在结构化时自动标记 L2 跨源重复 note。

业务背景:
    - Notes 没有"source"维度(不像 transactions 有 wechat/alipay 区分)
    - 但同一个 Apple Note 可能被用户多次同步(同一 apple_note_id 重复导入 → L1 UNIQUE 拦截)
    - 跨 folder / 跨 device 同步同一笔记(不同 apple_note_id 但同 fingerprint)→ L2 候选标记
    - L2 候选语义:needs_confirm=1 + candidate_match_id=earliest.id(沿 D6.4 transactions L2 范本)

字段选型:
    needs_confirm        INTEGER NOT NULL DEFAULT 0  # 0=无候选,1=有 L2 候选待 1-click 确认
    candidate_match_id   INTEGER NULL                 # 候选最早 note.id(沿 0013 范本无 FK,应用层保引用一致)

索引:
    idx_notes_needs_confirm(needs_confirm) — 按待确认候选过滤热路径(用户 1-click 确认列表)

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本字段非金额)
    2. BOOLEAN 走 Integer + server_default="0" — ✅(needs_confirm 字段)
    3. DATE 走 Date — N/A
    4. AUTOINCREMENT(非 AUTO_INCREMENT)— N/A
    5. 文件名 0014_note_l2_cross_source.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("...")— 本索引无 DESC,无影响

D3.3.3 教训应用:
    - 本迁移无 DML 异常风险(纯 DDL,ALTER TABLE + CREATE INDEX)
    - 应用层 NoteStore.insert 严判 needs_confirm / candidate_match_id 字段类型

D4.7.3 教训应用:
    - type 严判在 hash 操作前(candidate_match_id 严判 int(非 bool))
    - 公共 API 入口严判 + 数据类 __post_init__ 双层防御

固化哲学(沿 D5.6.3 P1-1 范本):
    - migration + ORM + Store + 业务方法 4 处改动同 commit 提交
    - Note.needs_confirm / candidate_match_id 字段已加(db/notes.py)
    - NoteStore.insert 自动派生 needs_confirm(新写入 note 时检查 L2 候选)
    - NoteStore.list_by_needs_confirm 新方法(用户 1-click 确认列表)
    - 本 alembic migration(0014_note_l2_cross_source.py)

v0.2.1+ NoteStore L2 跨源写入范围边界:
    - 本轮只做 Notes 写入侧 L2 candidate 自动标记
    - 用户 1-click 确认留 v0.2.2+(不在本轮范围)
    - L3 模糊匹配 ±1 day 留 v0.2.2+(不在本轮范围)

0013 范本应用(无 FK 软标记):
    v0.2.1 #5 (0013) 已定调"L2 软标记 + 无 FK"——避免 SQLite 自引用 FK 的 batch mode 限制。
    本迁移沿同一范本:candidate_match_id 纯 Integer 字段,引用一致性由应用层
    (NoteStore.insert 派生时 select Note.id)负责,不引入 op.create_foreign_key。

设计调整记录(2026-06-17):
    初版 0014 包含 op.create_foreign_key self-reference,跑 alembic upgrade head --sql
    报错"NotImplementedError: No support for ALTER of constraints in SQLite dialect.
    Please refer to the batch mode feature which allows for SQLite migrations using a
    copy-and-move strategy."
    修复:去掉 FK,沿 0013 范本纯 ADD COLUMN + 注释指明语义。理由:
    1) SQLite + alembic 的 batch mode 在自引用 FK + 临时表重建组合下行为复杂易错
    2) 0013 范本已经定调"L2 软标记 + 无 FK" + "L1 UNIQUE 已做硬约束,L2 是软标记"
    3) 候选 id 存在性由应用层 NoteStore.insert 派生时校验(已 select Note.id 查)
    4) 跨源去重的"硬"约束靠 normalized_fingerprint 索引 + L1 UNIQUE(apple_note_id)二层
    FK 加在 candidate_match_id 上是装饰,实际保护力由应用层 + 索引提供
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014_note_l2_cross_source"
down_revision: str | Sequence[str] | None = "0013_note_fingerprint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v0.2.1+ NoteStore L2 跨源写入: notes 表加 needs_confirm + candidate_match_id 列(沿 0013 范本无 FK).

    SQLite ALTER TABLE 限制(沿 env.py render_as_batch=True):
        - ADD COLUMN 支持 NOT NULL + DEFAULT(同步填充旧 row)
        - ADD COLUMN 支持 NULL(候选 id 字段,旧 row 自动填 NULL)
        - 旧 notes 表 row 自动填 needs_confirm=0 / candidate_match_id=NULL
    """
    # ===== needs_confirm 列 =====
    # BOOLEAN 走 Integer(0/1),server_default="0"(沿 D3.2 雷区 #2)
    op.add_column(
        "notes",
        sa.Column(
            "needs_confirm",
            sa.Integer(),
            nullable=False,
            default=0,
            server_default="0",
        ),
    )

    # ===== candidate_match_id 列(纯 Integer 字段,无 FK,沿 0013 范本)=====
    # 设计选择:不自引用 FK to notes.id,理由见 docstring "0013 范本应用(无 FK 软标记)" 段
    # 应用层 NoteStore.insert 派生时通过 select Note.id 校验存在性
    op.add_column(
        "notes",
        sa.Column(
            "candidate_match_id",
            sa.Integer(),
            nullable=True,
            default=None,
            server_default=None,
        ),
    )

    # ===== idx_notes_needs_confirm 索引 =====
    # 按待确认候选过滤热路径(用户 1-click 确认列表 + 月报)
    op.create_index(
        "idx_notes_needs_confirm",
        "notes",
        ["needs_confirm"],
    )


def downgrade() -> None:
    """v0.2.1+ NoteStore L2 跨源写入: 删除 needs_confirm + candidate_match_id + 索引(干净回滚)。

    顺序与 upgrade 相反:索引 → 列。
    """
    op.drop_index("idx_notes_needs_confirm", table_name="notes")
    op.drop_column("notes", "candidate_match_id")
    op.drop_column("notes", "needs_confirm")
