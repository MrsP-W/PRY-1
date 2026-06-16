"""v0.2 B4.1 迁移 — recipient_blacklist 表(6 字段 + UNIQUE + 1 INDEX).

Revision ID: 0010_recipient_blacklist
Revises: 0009_sla_due_at
Create Date: 2026-06-16

承接 v0.1.0 post-tag 阶段 + v0.2 B4.1 启动。
本迁移设计:新建 recipient_blacklist 表(6 字段 + 1 UNIQUE 约束 + 1 INDEX)。

业务背景(沿 docs/v0.2-b1-b2-implementation-readiness.md + outbox_adapter.py:56-61):
    B4.1 v0.2 启动: 收件人黑名单配置表落子层
        - 现有 outbox_adapter 已有 OUTBOX_BLOCK_REASON_VALUES 白名单预留 'blacklisted_recipient'
        - B4.1 落表(本迁移),B4.2 OutboxAdapter store_and_emit 入口调 is_blocked()
        - B4.3 SMTP 发送路径接入校验
        - added_by 3 类来源: 'manual' / 'auto_spam' / 'auto_bounce'(预留自动拉黑)
        - is_active 软删除字段(deactivate() 走 is_active=0,审计可追溯)

字段选型(6 列 + D3.2 8 雷区严判):
    1. id              INTEGER PK AUTOINCREMENT
    2. recipient_email TEXT NOT NULL UNIQUE                  # 收件人邮箱(L1 硬约束)
    3. reason          TEXT NOT NULL DEFAULT ''              # 拉黑原因(允许空)
    4. added_by        TEXT NOT NULL DEFAULT 'manual'        # 来源 3 选 1 枚举
    5. added_at_ms     INTEGER NOT NULL                      # 入库时间戳
    6. is_active       INTEGER NOT NULL DEFAULT 1            # 0/1 BOOLEAN 走 Integer

约束:
    - UNIQUE(recipient_email) — L1 硬约束(防重复拉黑)

索引:
    - idx_recipient_blacklist_active(added_at_ms DESC) — 按拉黑时间倒序(管理员查询热路径)

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本表无金额字段)
    2. BOOLEAN 走 Integer + server_default="0/1"(SQLite 无 BOOLEAN 类型)
    3. DATE 走 Date — N/A(本字段用 ms INTEGER)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)
    5. 文件名 0010_recipient_blacklist.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("added_at_ms DESC")(D3.2.3 修复)

D3.3.3 教训应用:
    - 本迁移无 DML 异常风险(纯 DDL,CREATE TABLE + CREATE INDEX)
    - 应用层 RecipientBlacklistStore.insert 严判 IntegrityError 范围窄化(只接 UNIQUE 冲突)

D4.7.3 教训应用:
    - P1-1 跨字段校验: 应用层 _validate_added_by 严判 3 选 1 枚举
    - P1-2 双向强一致: is_active INTEGER(0/1) DDL 严判,BOOLEAN 走 Integer 是 SQLite 唯一可行方案
    - P2-1 type 严判: is_active bool 入参严判 type() is bool(非 int 子类陷阱)
    - P2-2 异常范围窄化(D3.3.3): RecipientBlacklistStore.insert 拒绝 SQLAlchemyError 基类

固化哲学(沿 D5.6.3 P1-1 范本):
    - migration + ORM + Store 3 处改动同 commit 提交
    - RecipientBlacklist ORM 已加(db/blacklist.py)
    - RecipientBlacklistStore.insert 内部走 IntegrityError 窄化(db/blacklist.py)
    - 本 alembic migration(0010_recipient_blacklist.py)
    3 处同 commit 落地
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_recipient_blacklist"
down_revision: str | Sequence[str] | None = "0009_sla_due_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v0.2 B4.1:新建 recipient_blacklist 表(6 列 + UNIQUE + 1 INDEX)。"""
    # ===== recipient_blacklist (B4.1 新增) =====
    op.create_table(
        "recipient_blacklist",
        # 1. id: PK AUTOINCREMENT(D3.2 雷区 #4: 非 AUTO_INCREMENT)
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # 2. recipient_email: 收件人邮箱(L1 硬约束)
        # 严判 必填 + 含 '@' + ≤ 254 字符 — 应用层 _validate_recipient_email
        sa.Column("recipient_email", sa.Text(), nullable=False),
        # 3. reason: 拉黑原因(允许空字符串,≤ 500 字符)
        sa.Column("reason", sa.Text(), nullable=False, default="", server_default=""),
        # 4. added_by: 来源 3 选 1 枚举 ('manual' / 'auto_spam' / 'auto_bounce')
        sa.Column("added_by", sa.Text(), nullable=False, default="manual", server_default="manual"),
        # 5. added_at_ms: 入库时间戳(必传 int >= 0)
        sa.Column("added_at_ms", sa.Integer(), nullable=False),
        # 6. is_active: 0/1 BOOLEAN 走 Integer(D3.2 雷区 #2)
        # 应用层严判 type() is bool(非 int 子类陷阱,沿 D4.7.3 v1.0.5 P2-1 范本)
        sa.Column(
            "is_active",
            sa.Integer(),
            nullable=False,
            default=1,
            server_default="1",
        ),
        # UNIQUE 约束(L1 硬约束:recipient_email 唯一)— 在 create_table 阶段直接声明
        # SQLite 不支持 ALTER CONSTRAINT(NotImplementedError),必须在建表时声明
        sa.UniqueConstraint("recipient_email", name="uq_recipient_blacklist_email"),
    )

    # ===== 索引(D3.2 雷区 #8: DESC 索引用 sa.text 包裹) =====
    # 管理员查询热路径:按拉黑时间倒序
    op.create_index(
        "idx_recipient_blacklist_active",
        "recipient_blacklist",
        [sa.text("added_at_ms DESC")],
    )


def downgrade() -> None:
    """v0.2 B4.1:删除 recipient_blacklist 表(干净回滚).

    顺序与 upgrade 相反:索引 → 表(UNIQUE 约束在表里,drop_table 自动删除)
    """
    op.drop_index("idx_recipient_blacklist_active", table_name="recipient_blacklist")
    op.drop_table("recipient_blacklist")
