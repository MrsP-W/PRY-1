"""D5/B2.1 迁移 — outbox 表加 sla_due_at_ms 列(预计算 SLA 截止时间)。

Revision ID: 0009_sla_due_at
Revises: 0008_notes
Create Date: 2026-06-16

承接 D5.5 SLA 评估 + D5.7 v0.1.0 正式发布 + v0.2 B2.1 启动。
本迁移设计:outbox 表加 sla_due_at_ms 列(可空,旧 outbox 条目 NULL)+ idx_outbox_sla_due_at 索引。

业务背景(沿 docs/v0.2-b1-b2-implementation-readiness.md):
    B2.1 v0.2 启动: SLA 截止时间预计算字段
        - 现有 SLAEvaluator 实时算 age_ms = now_ms - created_at(每次都算)
        - B2.1 预计算 sla_due_at_ms = created_at + sla_threshold_ms(priority)
        - 调度器优先 sla_due_at_ms < now_ms + 5min 的紧急项,无需每次实时算
        - 旧 outbox 条目 NULL 表示未预计算,OutboxStore.update 不强制更新(向后兼容)

字段选型:
    sla_due_at_ms INTEGER NULL  # 旧 outbox 条目 NULL,新条目预计算

索引:
    idx_outbox_sla_due_at(sla_due_at_ms) — SLA 临近查询热路径(OutboxDispatcher 优先 SLA)

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本表无金额字段)
    2. BOOLEAN 走 Integer + server_default="0" — N/A(本字段非 BOOLEAN)
    3. DATE 走 Date(非 DateTime,指纹算法只取日期)— N/A(本字段用 ms INTEGER)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)— N/A(本字段是 INTEGER 加列)
    5. 文件名 0009_sla_due_at.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("...")— 本索引无 DESC,无影响

D3.3.3 教训应用:
    - 本迁移无 DML 异常风险(纯 DDL,ALTER TABLE + CREATE INDEX)
    - 应用层 OutboxStore.insert 严判 IntegrityError 范围窄化(只接 UNIQUE 冲突)

D4.7.3 教训应用:
    - P1-1 跨字段校验: 应用层 _compute_sla_due_at_ms helper 严判 priority
    - P1-2 双向强一致: sla_due_at_ms = created_at + sla_threshold_ms(priority),priority 变更 → sla_due_at_ms 必重新计算
    - P2-1 type 严判: sla_due_at_ms type() is int(非 bool 子类陷阱)
    - P2-2 异常范围窄化(D3.3.3): OutboxStore.insert 拒绝 SQLAlchemyError 基类

固化哲学(沿 D5.6.3 P1-1 范本):
    - migration + ORM + Store 3 处改动同 commit 提交
    - OutBoxEntry.sla_due_at_ms 字段已加(core/outbox.py)
    - OutboxStore.insert 内部预计算 sla_due_at_ms(db/outbox.py)
    - 本 alembic migration(0009_sla_due_at.py)
    3 处同 commit 落地
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009_sla_due_at"
down_revision: str | Sequence[str] | None = "0008_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """D5/B2.1:outbox 表加 sla_due_at_ms 列 + idx_outbox_sla_due_at 索引。"""
    # ===== sla_due_at_ms 列加(outbox 表加列,可空)=====
    # nullable=True:旧 outbox 条目 NULL 表示未预计算(向后兼容)
    # server_default=None:无默认值,NULL 即 NULL(语义清晰)
    op.add_column(
        "outbox",
        sa.Column(
            "sla_due_at_ms",
            sa.Integer(),
            nullable=True,
            default=None,
            server_default=None,
        ),
    )

    # ===== idx_outbox_sla_due_at 索引(SLA 临近查询热路径)=====
    # 调度器优先 sla_due_at_ms < now_ms + 5min 的紧急项,无 DESC(SLA 临近即紧急)
    op.create_index(
        "idx_outbox_sla_due_at",
        "outbox",
        ["sla_due_at_ms"],
    )


def downgrade() -> None:
    """D5/B2.1:删除 sla_due_at_ms 列 + idx_outbox_sla_due_at 索引(干净回滚)。

    顺序与 upgrade 相反:索引 → 列(避免外键引用问题)。
    """
    op.drop_index("idx_outbox_sla_due_at", table_name="outbox")
    op.drop_column("outbox", "sla_due_at_ms")
