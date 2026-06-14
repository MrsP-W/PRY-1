"""D6.4 迁移 — transactions 表(3 层去重模型 + 状态机).

Revision ID: 0007_transactions
Revises: 0006_outbox_approval_provenance
Create Date: 2026-06-17

承接 D5.6.3 outbox approval provenance(0006)+ D6.1 微信 CSV 解析器(617526c)
+ D6.2 fingerprint + 3 层去重(ad4e076)+ D6.3 categorizer + merchants 500 + 状态机(85864df)。

**本迁移设计**:新建 transactions 表(16 列 + 1 UNIQUE 约束 + 2 INDEX + 1 FK)。

业务背景(沿 docs/v0.1-launch-plan.md §D6):
    D6 微信账单导入 3 层去重模型硬约束层:
        L1 源内幂等: UNIQUE(source, external_transaction_id) — 业务阻断入口
        L2 跨源候选: normalized_fingerprint INDEX — 软标记
        L3 模糊匹配: needs_confirm + candidate_match_id — 只标记,绝不 delete/update 候选

D7 兼容 schema 必含(沿 plan §7 D7 兼容 5 扩展点 #2):
    - candidate_match_id INTEGER NULL(D6 全 NULL,D7 触发跨源候选时写入)
    - needs_confirm INTEGER NOT NULL DEFAULT 0(D6 暂全 0,D7 触发跨源时设 1)

字段选型(16 列 + D3.2 8 雷区严判):
    1. id                    INTEGER PK AUTOINCREMENT
    2. source                TEXT NOT NULL                  # D6='wechat',D7='alipay'
    3. external_transaction_id TEXT NOT NULL                # 业务侧交易流水号
    4. transaction_date      DATE NOT NULL                   # 指纹算法只取日期(非 DATETIME)
    5. amount                NUMERIC(10, 2) NOT NULL         # 防精度漂移(非 Float)
    6. counterparty          TEXT NOT NULL
    7. category              TEXT NULL                       # TransactionCategory 5 选 1
    8. payment_method        TEXT NULL
    9. normalized_fingerprint TEXT NOT NULL                  # 32 chars SHA-256 hex
    10. needs_confirm        INTEGER NOT NULL DEFAULT 0     # BOOLEAN 走 Integer(SQLite 无 BOOLEAN)
    11. candidate_match_id   INTEGER NULL                    # D7 触发跨源,D6 全 NULL
    12. status               TEXT NOT NULL DEFAULT 'imported'  # TransactionStatus 5 选 1
    13. imported_at_ms       INTEGER NOT NULL                # Unix epoch ms
    14. confirmed_at_ms      INTEGER NULL                    # 用户确认时间戳
    15. raw_row_json         TEXT NOT NULL                   # 原始行 JSON(追溯)
    16. notes                TEXT NULL

约束:
    - UNIQUE(source, external_transaction_id) — L1 硬约束
    - 16 列中无外键 FK(纯 transactions 自包含,D6.5 Adapter 通过 events 表写 audit)

索引:
    - idx_transactions_fingerprint(normalized_fingerprint) — L2 软标记
    - idx_transactions_status_imported(status, imported_at_ms DESC) — 状态机热路径

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float(防精度漂移 13.14 == 13.140)
    2. BOOLEAN 走 Integer + server_default="0"(SQLite 无 BOOLEAN 类型)
    3. DATE 走 Date(非 DateTime,指纹算法只取日期)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)
    5. 文件名 0007_transactions.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("imported_at_ms DESC")(D3.2.3 修复)

D3.3.3 教训应用:
    - 本迁移无 DML 异常风险(纯 DDL,CREATE TABLE + CREATE INDEX)
    - 应用层 TransactionStore.insert 严判 IntegrityError 范围窄化(只接 UNIQUE 冲突)

D5.2/D6.3 状态机白名单(业务层,DDL 不持有):
    TransactionStatus 5 状态 + ALLOWED_TRANSITIONS — 见 core/transactions.py
    本迁移 status 列 DDL DEFAULT 'imported' 即可,业务层 StrEnum 严判 5 选 1

教训应用(沿 D4.7.3 v1.0.6 25 教训):
    - P1-1 跨字段校验: 应用层 _validate_* 严判 category 5 选 1 + status 5 选 1
    - P1-2 双向强一致: needs_confirm INTEGER(0/1) DDL 严判,BOOLEAN 走 Integer 是 SQLite 唯一可行方案
    - P2-1 type 严判: needs_confirm bool 入参严判 type() is bool(非 int 子类陷阱)
    - P2-2 异常范围窄化(D3.3.3): TransactionStore.insert 拒绝 SQLAlchemyError 基类
    - 固化哲学: migration + ORM + Store 3 处改动同 commit 提交(沿 D5.6.3 P1-1 范本)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_transactions"
down_revision: str | Sequence[str] | None = "0006_outbox_approval_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """D6.4:新建 transactions 表(16 列 + UNIQUE 复合 + 2 INDEX)。"""
    # ===== transactions (D6.4 新增) =====
    # 16 列 + 1 UNIQUE 约束 + 2 索引(无 FK — 纯 self-contained)
    op.create_table(
        "transactions",
        # 1. id: PK AUTOINCREMENT(D3.2 雷区 #4: 非 AUTO_INCREMENT)
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # 2. source: 业务源标识(D6='wechat',D7='alipay')
        # 严判 ^[a-z0-9_-]{1,32}$ — 应用层 _validate_source(D6.2 + D6.4 双层严判)
        sa.Column("source", sa.Text(), nullable=False),
        # 3. external_transaction_id: 业务侧交易流水号(1-128 字符)
        # 严判 _validate_external_tx_id
        sa.Column("external_transaction_id", sa.Text(), nullable=False),
        # 4. transaction_date: 交易日期(D3.2 雷区 #3: 非 DATETIME)
        # DATE 类型,指纹算法只取日期不取时间(沿 D6.2 fingerprint.normalize_fingerprint)
        sa.Column("transaction_date", sa.Date(), nullable=False),
        # 5. amount: 交易金额(D3.2 雷区 #1: NUMERIC(10,2) 非 Float,防精度漂移)
        # 严判 Decimal 2 位小数 — 应用层 _validate_amount
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        # 6. counterparty: 商家名(非空)
        sa.Column("counterparty", sa.Text(), nullable=False),
        # 7. category: TransactionCategory 5 选 1(D6.3 新建,DDL 走 TEXT)
        # 严判 5 选 1 — 应用层 _validate_category
        sa.Column("category", sa.Text(), nullable=True),
        # 8. payment_method: 支付方式(可空)
        sa.Column("payment_method", sa.Text(), nullable=True),
        # 9. normalized_fingerprint: 32 chars SHA-256 hex(L2 软标记用)
        # 严判 32 chars 小写 hex — 应用层 _validate_fingerprint(沿 D6.2 范本)
        sa.Column("normalized_fingerprint", sa.Text(), nullable=False),
        # 10. needs_confirm: L3 软标记(D3.2 雷区 #2: BOOLEAN 走 Integer + server_default="0")
        # SQLite 无 BOOLEAN 类型,DDL 用 INTEGER DEFAULT 0
        # 应用层严判 type() is bool(非 int 子类陷阱,沿 D4.7.3 v1.0.5 P2-1 范本)
        sa.Column(
            "needs_confirm",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment=(
                "D6.4 L3 软标记: BOOLEAN 走 Integer(0=False, 1=True)。"
                "D6 暂全 0,D7 触发跨源候选时设 1(needs_confirm=True + candidate_match_id)"
            ),
        ),
        # 11. candidate_match_id: L3 候选 ID(D6.4 D7 兼容 schema 必含,D6 全 NULL)
        sa.Column(
            "candidate_match_id",
            sa.Integer(),
            nullable=True,
            comment=(
                "D6.4 D7 兼容: L3 跨源候选匹配 ID。"
                "D6 全 NULL,D7 触发跨源候选时写入(find_l2_candidates 返回的最小 ID)"
            ),
        ),
        # 12. status: TransactionStatus 5 选 1(D6.3 新建,DDL 走 TEXT)
        # DEFAULT 'imported' — D6.5 Adapter 写入初值,后续调 update_status 流转
        # 严判 5 选 1 — 应用层 _normalize_status
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="imported",
            comment=(
                "D6.3 状态机 5 选 1: imported / categorized / needs_confirm / confirmed / archived。"
                "白名单 ALLOWED_TRANSITIONS 见 core/transactions.py"
            ),
        ),
        # 13. imported_at_ms: 导入时间戳(Unix epoch ms)
        sa.Column("imported_at_ms", sa.Integer(), nullable=False),
        # 14. confirmed_at_ms: 用户确认时间戳(可空,D6.4 update_status(CONFIRMED) 时写入)
        sa.Column(
            "confirmed_at_ms",
            sa.Integer(),
            nullable=True,
            comment=(
                "D6.4 状态机: 用户确认时间戳(Unix epoch ms)。"
                "仅在 update_status(new_status=CONFIRMED) 时写入;"
                "其他状态保留(不动,避免重试时丢确认标记)。"
            ),
        ),
        # 15. raw_row_json: 原始行 JSON(必传,保留供追溯)
        # 严判合法 JSON — 应用层 _validate_raw_row_json
        sa.Column("raw_row_json", sa.Text(), nullable=False),
        # 16. notes: 用户备注(可空)
        sa.Column("notes", sa.Text(), nullable=True),
        # L1 硬约束: UNIQUE(source, external_transaction_id) — 业务阻断入口
        # D3.3.3 异常窄化应用:UNIQUE 冲突走 TransactionDuplicateError,非技术失败
        sa.UniqueConstraint(
            "source",
            "external_transaction_id",
            name="uq_transactions_source_ext_id",
        ),
    )
    # 索引 1: idx_transactions_fingerprint — L2 软标记(非 UNIQUE,跨源可能重复)
    op.create_index(
        "idx_transactions_fingerprint",
        "transactions",
        ["normalized_fingerprint"],
    )
    # 索引 2: idx_transactions_status_imported — 状态机热路径(D3.2 雷区 #8: DESC 索引用 sa.text)
    op.create_index(
        "idx_transactions_status_imported",
        "transactions",
        ["status", sa.text("imported_at_ms DESC")],
    )


def downgrade() -> None:
    """D6.4 倒序:删 transactions 表(沿 outbox migration 范本)。"""
    # 倒序 drop (依赖关系反向)
    op.drop_index("idx_transactions_status_imported", table_name="transactions")
    op.drop_index("idx_transactions_fingerprint", table_name="transactions")
    op.drop_table("transactions")
