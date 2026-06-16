"""v0.2 D8.1 迁移 — merchant_profile 表(8 字段 + UNIQUE + 1 INDEX).

Revision ID: 0011_merchant_profile
Revises: 0010_recipient_blacklist
Create Date: 2026-06-22

承接 v0.1.0 post-tag 阶段 + v0.2 D8 智能财务异常检测启动。
本迁移设计:新建 merchant_profile 表(8 字段 + 1 UNIQUE 约束 + 1 INDEX)。

业务背景(沿 docs/d8-anomaly-detector-evaluation.md + docs/v0.2-substage-mapping.md §6):
    D8.1 v0.2 启动: 商家画像漂移检测落子层
        - 现有 transactions 表 16 列已含 counterparty(D6.4 已落)
        - D8.1 新建 merchant_profile 表,缓存每商家的历史画像
        - D8.2 AnomalyDetector 调 MerchantProfileStore.compute_profile()
        - D8.3 月报异常告警段 + 菜单栏异常告警菜单项接入
        - 商家画像由 (avg_amount, amount_std, category_distribution) 3 字段 + tx_count 派生
        - 冷启动 < 5 笔返回 None,D8.2 走 new_merchant 标记路径

字段选型(8 列 + D3.2 8 雷区严判):
    1. id                    INTEGER PK AUTOINCREMENT
    2. counterparty          TEXT NOT NULL UNIQUE              # 商家名(L1 硬约束)
    3. avg_amount            NUMERIC(10, 2) NOT NULL            # 历史平均消费(Decimal 精度)
    4. amount_std            NUMERIC(10, 2) NOT NULL            # 历史金额 σ(Decimal 精度)
    5. category_distribution TEXT NOT NULL                       # JSON: {category: count}
    6. tx_count              INTEGER NOT NULL                    # 历史笔数
    7. last_seen_ms          INTEGER NOT NULL                    # 最后一次出现时间戳
    8. updated_at_ms         INTEGER NOT NULL                    # 画像更新时间戳

约束:
    - UNIQUE(counterparty) — L1 硬约束(防同一商家重复画像)

索引:
    - idx_merchant_profile_last_seen(last_seen_ms DESC) — 最近活跃商家热路径(D8.2 异常检测)

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — avg_amount / amount_std 走 Numeric
    2. BOOLEAN 走 Integer + server_default="0/1" — N/A(本表无 BOOLEAN)
    3. DATE 走 Date — N/A(本表用 ms INTEGER)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)
    5. 文件名 0011_merchant_profile.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("last_seen_ms DESC")(D3.2.3 修复)

D3.3.3 教训应用:
    - 本迁移无 DML 异常风险(纯 DDL,CREATE TABLE + CREATE INDEX)
    - 应用层 MerchantProfileStore.upsert_profile 严判 IntegrityError 范围窄化(只接 UNIQUE 冲突)

D4.7.3 教训应用:
    - type 严判在 hash 操作前
    - 公共 API 入口严判 + 数据类 __post_init__ 双层防御
    - ms 字段严判 type() is bool,拒 int 子类陷阱

固化哲学(沿 D5.6.3 P1-1 范本):
    - migration + ORM + Store 3 处改动同 commit 提交
    - MerchantProfile ORM 已加(db/merchant_profile.py)
    - MerchantProfileStore.upsert_profile 内部走 IntegrityError 窄化
    - 本 alembic migration(0011_merchant_profile.py)
    3 处同 commit 落地

D8.1 范围边界:
    - 本轮不动 AnomalyDetector(在 D8.2)
    - 本轮不动 monthly_report.py 异常告警段(在 D8.3)
    - 本轮不动 menu_bar 异常告警菜单项(在 D8.3)
    - Store 层只暴露 compute_profile / upsert_profile / get_profile 3 方法
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_merchant_profile"
down_revision: str | Sequence[str] | None = "0010_recipient_blacklist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v0.2 D8.1:新建 merchant_profile 表(8 列 + UNIQUE + 1 INDEX)。"""
    # ===== merchant_profile (D8.1 新增) =====
    op.create_table(
        "merchant_profile",
        # 1. id: PK AUTOINCREMENT(D3.2 雷区 #4: 非 AUTO_INCREMENT)
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # 2. counterparty: 商家名(L1 硬约束)
        # 严判 必填非空白 + ≤ 128 字符 — 应用层 _validate_counterparty
        sa.Column("counterparty", sa.Text(), nullable=False),
        # 3. avg_amount: 历史平均消费(D3.2 雷区 #1: Numeric 非 Float)
        # 应用层 _validate_amount 严判 >= 0 + 2 位小数
        sa.Column("avg_amount", sa.Numeric(10, 2), nullable=False),
        # 4. amount_std: 历史金额 σ(D3.2 雷区 #1: Numeric 非 Float)
        # 应用层 _validate_amount 严判 >= 0 + 2 位小数
        sa.Column("amount_std", sa.Numeric(10, 2), nullable=False),
        # 5. category_distribution: 类别分布 JSON 字符串
        # 应用层 _validate_category_distribution 严判合法 JSON + ≤ 2000 字符
        sa.Column("category_distribution", sa.Text(), nullable=False),
        # 6. tx_count: 历史笔数
        # 应用层 _validate_tx_count 严判 int >= 0
        sa.Column("tx_count", sa.Integer(), nullable=False),
        # 7. last_seen_ms: 最后一次出现时间戳
        sa.Column("last_seen_ms", sa.Integer(), nullable=False),
        # 8. updated_at_ms: 画像更新时间戳
        sa.Column("updated_at_ms", sa.Integer(), nullable=False),
        # UNIQUE 约束(L1 硬约束:counterparty 唯一)— 在 create_table 阶段直接声明
        # SQLite 不支持 ALTER CONSTRAINT(NotImplementedError),必须在建表时声明
        sa.UniqueConstraint("counterparty", name="uq_merchant_profile_counterparty"),
    )

    # ===== 索引(D3.2 雷区 #8: DESC 索引用 sa.text 包裹) =====
    # 异常检测热路径:按最后出现时间倒序查最近活跃商家
    op.create_index(
        "idx_merchant_profile_last_seen",
        "merchant_profile",
        [sa.text("last_seen_ms DESC")],
    )


def downgrade() -> None:
    """v0.2 D8.1:删除 merchant_profile 表(干净回滚).

    顺序与 upgrade 相反:索引 → 表(UNIQUE 约束在表里,drop_table 自动删除)
    """
    op.drop_index("idx_merchant_profile_last_seen", table_name="merchant_profile")
    op.drop_table("merchant_profile")
