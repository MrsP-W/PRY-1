"""D5.6.3 迁移 — outbox 表加 `last_approved_at_ms` 字段(审批凭据)。

Revision ID: 0006_outbox_approval_provenance
Revises: 0005_outbox_sending_state
Create Date: 2026-06-13

承接 D5.5.5 收口(commit `a866810` + `caf021f`)
+ D5.6 v1 被驳回(commit `c4a7d01`,措辞失实)
+ D5.6.1 修复 5 项(commit `fdf44c6`,被检查员二次驳回)
+ D5.6.2 修复 7 项(commit `819affb` + `8fdc088`,**被检查员第三轮驳回**)
+ D5.6.3 修复 7 项(**本迁移**,检查员第三轮 7 项新缺陷全部修复)

**本迁移设计**:加 `last_approved_at_ms INTEGER NULL` 字段(D5.6.3 P1-1 修复)。

业务背景(检查员第三轮 P1-1 反馈):
    状态机白名单 ALLOWED_TRANSITIONS[PENDING_SEND] = {SENDING, APPROVED, FAILED, CANCELLED}
    允许业务直接 PENDING_SEND → FAILED(例如用户取消场景),然后
    FAILED → APPROVED(检查员 P1.2 D5.6.2 新加白名单) → SENT,走 dispatcher
    直接发送,完全绕过用户审批契约。

    修复:引入"审批凭据"概念,记录"本条目曾被显式审批过的时间戳"。
    - 写入时机:update_status(..., new_status=APPROVED) 时必传 last_approved_at_ms
    - 保留时机:SENDING → SENT / SENDING → FAILED 都不动(避免重试时丢审批标记)
    - 严判:OutboxDispatcher 拉批时 entry.last_approved_at_ms is not None
      否则 skipped(且 loguru.warning 记录绕过尝试,防审计盲点)

字段选型(沿 D4.8 + D5.2 范本):
    - 字段名:last_approved_at_ms
    - 类型:INTEGER NULL(SQLite 不支持 DATETIME)
    - 单位:Unix epoch ms(与 created_at / failed_at 等字段一致)
    - 索引:无(调度器拉批不在此字段上查询)
    - UNIQUE 约束:无
    - FK:无
    - DEFAULT:NULL(新插入条目默认无审批)
    - 注释:nullable,允许 PENDING_SEND 默认无审批

D5.6.3 P1-1 修复前后行为对比:
    修复前:
        1. 业务 PENDING_SEND → FAILED(update_status, from_status=PENDING_SEND)
        2. Dispatcher 拉 FAILED(by_status)
        3. Dispatcher FAILED → APPROVED(update_status, from_status=FAILED, D5.6.2 新加)
        4. Dispatcher 直接 SENDING → SENT 发送
        缺陷:任何 PENDING_SEND 都可以借 FAILED → APPROVED 路径绕过审批

    修复后:
        1. 业务 PENDING_SEND → FAILED(update_status, from_status=PENDING_SEND)
           - 此时 last_approved_at_ms 仍 NULL(从未审批过)
        2. Dispatcher 拉 FAILED(by_status)
        3. Dispatcher 严判 entry.last_approved_at_ms is not None
           - 失败 → skipped, loguru.warning(防绕过尝试)
           - 通过 → FAILED → APPROVED → SENDING → SENT(走正常路径)
        4. 修复:D5.6.2 新加的 FAILED → APPROVED 白名单,仅在"曾被审批过"前提下
           才生效(沿用 D4.7.3 v1.0.6 范本 — 状态机白名单 + 业务层审批凭据双层防御)

向下兼容(D4.8 v1.0.1 + D5.1-D5.5 已有契约):
    - 已有 PENDING_SEND 条目 last_approved_at_ms = NULL(DDL 默认值)
    - D5.6.3 落地后,新插入条目默认无审批,需 _approve_all_pending 显式
      调 update_status(APPROVED, from_status=PENDING_SEND, last_approved_at_ms=now_ms)
    - D4.8 v1.0.1 test_update_status_pending_to_approved 兼容(只测状态转换,不测字段写入)
    - 已有 D5.6.1 + D5.6.2 spike + test_outbox_dispatcher_approval.py 需
      在 commit 2 同步更新(显式传 last_approved_at_ms)

教训应用(沿 D4.7.3 v1.0.6 25 教训):
    - P1-1 跨字段校验: dispatcher 拉批时 last_approved_at_ms is not None 必严判
    - P1-2 双向强一致: OutboxStore.update_status 写入 + SENDING→SENT/FAILED 保留
    - P2-1 type 严判: last_approved_at_ms 字段 type() is int(非 bool) + >= 0
    - P2-3 字段名级别硬区分: last_approved_at_ms(审批) vs last_failed_at_ms(技术失败)
    - 固化哲学: migration + ORM + Store + Dispatcher 4 处改动同 commit 提交
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_outbox_approval_provenance"
down_revision: str | Sequence[str] | None = "0005_outbox_sending_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """D5.6.3 P1-1:outbox 表加 last_approved_at_ms 字段(审批凭据)。"""
    # ===== DDL 改动 =====
    # 加 last_approved_at_ms INTEGER NULL 列
    # - nullable(允许 PENDING_SEND 默认无审批)
    # - 无 server_default(应用层 _approve_all_pending 显式传值)
    # - 无 UNIQUE(每条 entry 仅 1 个审批时间戳,无去重需求)
    # - 无 FK(纯时间戳字段)
    # - 无 INDEX(调度器不在此字段上查询,只读 row 内存)
    op.add_column(
        "outbox",
        sa.Column(
            "last_approved_at_ms",
            sa.Integer(),
            nullable=True,
            comment=(
                "D5.6.3 P1-1 审批凭据: 显式审批时间戳(Unix epoch ms)。"
                "仅在 update_status(new_status=APPROVED) 时写入;"
                "SENDING → SENT / SENDING → FAILED 时保留(不动)。"
                "OutboxDispatcher 拉批严判 is not None,否则 skipped。"
            ),
        ),
    )


def downgrade() -> None:
    """D5.6.3 P1-1 倒序:删 outbox.last_approved_at_ms 字段。"""
    op.drop_column("outbox", "last_approved_at_ms")
