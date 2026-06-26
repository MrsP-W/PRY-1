"""v0.2.53.16 AnomalyDismissal 迁移 — anomaly_dismissals 表(沿 v0.2.53.14 §5.3 设计).

Revision ID: 0015_anomaly_dismissal
Revises: 0014_note_l2_cross_source
Create Date: 2026-06-26

承接 docs/v0.2.53.14-business-writer-design-2026-06-26.md §5.3 AnomalyDismissalService 存储设计:
    - finance.dismiss_anomaly 是 v0.2.53.11 ApprovalGate 契约白名单的 4 类动作之一
    - 但 AnomalyDetector / ExpenseService 都没有 dismiss_anomaly 方法
    - 本迁移创建 anomaly_dismissals 表 + 索引,Real 留 v0.2.53.17+ 接入

业务背景:
    - 财务异常(detect_amount_anomaly / detect_frequency_anomaly / detect_duplicate_charge / detect_merchant_profile_drift)
      由 AnomalyDetector 检测,异常提示在 Dashboard `/api/finance/anomalies` 展示
    - 用户 dismiss 异常后,需要落档避免重复提示(类似 D8.3 异常告警)
    - anomaly_id 编码格式: {date}|{counterparty}|{amount}  例: 2026-06-26|星巴克|38.50
    - UNIQUE(anomaly_id) 保证同 ID 只 dismiss 1 次(避免重复落档)

字段选型:
    id              INTEGER PRIMARY KEY AUTOINCREMENT
    anomaly_id      TEXT NOT NULL              # date|counterparty|amount
    reason          TEXT NOT NULL DEFAULT ''   # 用户 dismiss 原因(限 240 字符,AnomalyDismissalServiceStub 严判)
    actor           TEXT NOT NULL DEFAULT 'local_dashboard'  # 审计字段(沿 v0.2.53.11 actor 默认值)
    dismissed_at_ms INTEGER NOT NULL            # ms 时间戳(沿现有 store 范本)
    UNIQUE(anomaly_id)                         # 同 ID 只 dismiss 1 次

索引:
    idx_dismissed_at(dismissed_at_ms DESC) — 按时间倒序查询热路径

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本表非金额表)
    2. BOOLEAN 走 Integer + server_default="0" — N/A(本表无 BOOLEAN 字段)
    3. DATE 走 Date — N/A(本表无日期字段,只用 INTEGER ms 时间戳)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)— ✅
    5. 文件名 0015_anomaly_dismissal.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("...")— ✅(idx_dismissed_at DESC)

0014 范本应用(无 FK 软标记):
    本表无 FK 引用其他表(纯 dismiss audit log),不涉及 SQLite 自引用 FK 的 batch mode 限制。

撞坑 #65 边界应用(本迁移配套):
    - AnomalyDismissalService 默认 Stub(is_enabled=False,dismiss 返回 not_enabled)
    - Real(AnomalyDismissalServiceImpl) 留 v0.2.53.17+ 接入
    - 默认不真写 DB(本迁移是 schema 定义,不执行实际数据写入)
    - 默认不真发 SMTP / 不读 Keychain 明文
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015_anomaly_dismissal"
down_revision: str | Sequence[str] | None = "0014_note_l2_cross_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v0.2.53.16 AnomalyDismissal 迁移: 创建 anomaly_dismissals 表 + idx_dismissed_at 索引.

    SQLite ALTER TABLE 限制(沿 env.py render_as_batch=True):
        - CREATE TABLE 支持所有约束(无限制)
        - 旧表无影响(新表,纯增量)
    """
    # ===== anomaly_dismissals 表 =====
    op.create_table(
        "anomaly_dismissals",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "anomaly_id",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "actor",
            sa.Text(),
            nullable=False,
            server_default="local_dashboard",
        ),
        sa.Column(
            "dismissed_at_ms",
            sa.Integer(),
            nullable=False,
        ),
        sa.UniqueConstraint("anomaly_id", name="uq_anomaly_dismissals_anomaly_id"),
    )

    # ===== idx_dismissed_at 索引(DESC)=====
    # 按时间倒序查询热路径(Dashboard `/api/finance/anomalies` + 月报聚合)
    # DESC 索引用 sa.text("...")(沿 D3.2 雷区 #8)
    op.create_index(
        "idx_dismissed_at",
        "anomaly_dismissals",
        [sa.text("dismissed_at_ms DESC")],
    )


def downgrade() -> None:
    """v0.2.53.16 AnomalyDismissal 迁移: 删除 anomaly_dismissals 表 + idx_dismissed_at 索引(干净回滚).

    顺序与 upgrade 相反:索引 → 表。
    """
    op.drop_index("idx_dismissed_at", table_name="anomaly_dismissals")
    op.drop_table("anomaly_dismissals")
