"""D4.8 迁移 — outbox 表(草稿入库/发送,业务层三入口契约 2)。

Revision ID: 0004_outbox
Revises: 0003_fix_events_fingerprint_unique
Create Date: 2026-06-11

承接 D4.7.3 v1.0.6(25 教训) + D4.7.4 v1.0.2(7 项核心契约) + D4.7.4.10 spike(100/100 跑通)。

5 项契约(2026-06-10 用户审批 D4.8 启动时确认):
    1. 三入口架构(成功 store_and_emit / 业务阻断 record_store_business_blocked_and_emit /
       技术失败 record_store_failure_and_emit,沿用 D4.7.3 v1.0.1 P1-1 范本)
    2. **本迁移**: outbox 表 11 字段 + UNIQUE(email_id) + 2 索引
    3. PermissionProfile = READ_WRITE(D4.8 首次引入,写库需要)
    4. 入库幂等性: UNIQUE(email_id) 冲突 → 业务阻断入口,not 技术失败(D3.3.3 异常窄化教训应用)
    5. 不真发 SMTP(避免 D4.8 越界,D5+ 业务调度器接管)

设计:
    - 11 字段 + 1 UNIQUE 约束 + 2 索引
    - 索引 1: idx_outbox_status_created_at(status, created_at DESC) — D5+ 调度器轮询
    - 索引 2: idx_outbox_priority_created_at(priority, created_at DESC) — 紧急邮件优先
    - DDL 走 TEXT(SQLite 不支持 ENUM 类型),ORM 走 OutboxStatus StrEnum 严判
    - reviewer_decision_event_id / drafter_decision_event_id FK 到 events.id(可空:
      D4.8 启动初期可能没有 reviewer/drafter event,后续 D5+ 必填)
    - subject 1-200 字符 / body 10-8000 字符 — 应用层 _validate_outbox_subject / _validate_outbox_body 严判
    - status DEFAULT 'pending_send' — D4.8 仅入库到 pending_send 状态
    - priority DEFAULT 'normal' — 大多数邮件 normal,urgent 需 D4.7.4 联动 category=URGENT 触发
    - recipient_email 含 @ — 应用层 _validate_outbox_recipient_email 严判(简单 str @ 检查)
    - tone ∈ {FORMAL, FRIENDLY, CONCISE} — 应用层 _validate_outbox_tone 严判

D3.2 沿用约定:
    - render_as_batch=True 在 env.py 已配
    - recipients/labels/metadata 用 sa.Text() + server_default, ORM 走 JSONList/JSONDict TypeDecorator
    - DESC 索引用 sa.text("created_at DESC") 表达(D3.2.3 修复 #3)

教训应用:
    - D3.2.3 NOCASE 写法:sa.Text() 不加 collation(D4.8 outbox 无大小写需求)
    - D3.2.3 JSON → TEXT:TEXT DEFAULT '[]'(outbox 字段都是标量,无 JSON 字段)
    - D3.2.3 DESC 索引:sa.text("created_at DESC")
    - D3.3.3 异常窄化:本迁移无 DML 异常风险
    - D4.7.3 v1.0.1 P1-1 跨字段校验:应用层 _validate_outbox_* 严判 priority ↔ category 等跨字段约束
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_outbox"
down_revision: str | Sequence[str] | None = "0003_fix_events_fingerprint_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== outbox (D4.8 新增) =====
    # 11 字段 + 1 UNIQUE 约束 + 2 索引
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # email_id: 关联 emails.id,UNIQUE 约束实现入库幂等性(D4.8 契约 4)
        sa.Column("email_id", sa.Integer(), nullable=False),
        # subject: 草稿主题,1-200 字符,strip() 后非空(应用层 _validate_outbox_subject 严判)
        sa.Column("subject", sa.Text(), nullable=False),
        # body: 草稿正文,10-8000 字符,strip() 后非空(应用层 _validate_outbox_body 严判)
        sa.Column("body", sa.Text(), nullable=False),
        # tone: OutboxTone 3 选 1 {FORMAL, FRIENDLY, CONCISE},DDL 走 TEXT
        # 应用层 _validate_outbox_tone 严判(type() is str + in frozenset + ValueError 统一)
        sa.Column("tone", sa.Text(), nullable=False),
        # reviewer_decision_event_id: FK → events.id,D4.7.4 审阅通过事件的 event.id
        # 可空:D4.8 启动初期可能无 reviewer(降级路径),D5+ 必填
        sa.Column("reviewer_decision_event_id", sa.Integer(), nullable=True),
        # drafter_decision_event_id: FK → events.id,D4.7.3 草稿生成事件的 event.id
        # 可空:D4.8 启动初期可能无 drafter event,D5+ 必填
        sa.Column("drafter_decision_event_id", sa.Integer(), nullable=True),
        # status: OutboxStatus 4 状态 {pending_send, approved, sent, cancelled}
        # DDL 走 TEXT,ORM 走 OutboxStatus StrEnum 严判
        # DEFAULT 'pending_send' — D4.8 仅入库到 pending_send 状态
        sa.Column("status", sa.Text(), nullable=False, server_default="pending_send"),
        # created_at: Unix epoch ms,冗余于 metadata.timestamp_ms,便于排序
        sa.Column("created_at", sa.Integer(), nullable=False),
        # recipient_email: 收件人邮箱,D4.8 2026-06-10 新增,避免 D5+ 发送时回查 emails 表
        # 含 @ 即可(应用层 _validate_outbox_recipient_email 严判,D5+ 接 SMTP 时再加完整 RFC 5322 校验)
        sa.Column("recipient_email", sa.Text(), nullable=False),
        # priority: OutboxPriority 3 选 1 {urgent, normal, low},2026-06-10 新增
        # DEFAULT 'normal',便于 D5+ 发送调度器排序(urgent 邮件优先)
        # 跨字段校验:priority=urgent ↔ email_category=URGENT(应用层 _validate_outbox_priority 严判)
        sa.Column("priority", sa.Text(), nullable=False, server_default="normal"),
        # UNIQUE 约束: email_id 全局唯一(D4.8 契约 4 — 入库幂等性)
        # UNIQUE 冲突 → 业务阻断入口 record_store_business_blocked_and_emit(reason="duplicate_email_id")
        # NOT 技术失败入口(D3.3.3 异常窄化教训应用)
        sa.UniqueConstraint("email_id", name="uq_outbox_email_id"),
        # FK 约束: reviewer_decision_event_id → events.id, drafter_decision_event_id → events.id
        # 可空 FK,允许 D4.8 启动初期无 reviewer/drafter event(D5+ 收紧为 NOT NULL)
        sa.ForeignKeyConstraint(
            ["reviewer_decision_event_id"],
            ["events.id"],
            name="fk_outbox_reviewer_event",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["drafter_decision_event_id"],
            ["events.id"],
            name="fk_outbox_drafter_event",
            ondelete="SET NULL",
        ),
    )
    # 索引 1: status + created_at DESC — D5+ 调度器轮询(status='pending_send' 的邮件按 created_at 排序)
    op.create_index(
        "idx_outbox_status_created_at",
        "outbox",
        ["status", sa.text("created_at DESC")],
    )
    # 索引 2: priority + created_at DESC — 紧急邮件优先(priority='urgent' 按 created_at 排序)
    op.create_index(
        "idx_outbox_priority_created_at",
        "outbox",
        ["priority", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    # 倒序 drop (依赖关系反向)
    op.drop_index("idx_outbox_priority_created_at", table_name="outbox")
    op.drop_index("idx_outbox_status_created_at", table_name="outbox")
    op.drop_table("outbox")
