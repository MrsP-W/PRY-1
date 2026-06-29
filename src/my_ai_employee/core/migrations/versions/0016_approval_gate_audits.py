"""v0.2.53.51 ApprovalGate Audit 迁移 — approval_gate_audits 表(沿 v0.2.53.20 §5.3 落档 design).

Revision ID: 0016_approval_gate_audits
Revises: 0015_anomaly_dismissal
Create Date: 2026-06-29

承接 docs/v0.2.53.20-html-real-write-flow-design-2026-06-26.md §5.3 + v0.2.53.51 audit 真实落档:
    - 写操作(路径 4 启用后)必须留痕,即便失败也要落档
    - audit 是「写操作的真实落档记录」,与 dry-run 决策分离
    - 默认 BusinessWriterImpl 写保护锁锁定,实际写入路径留 8/1 后
    - audit 表是「日志」(不阻塞业务),即便 store 失败也不应影响业务返回

字段选型(沿用户 P1 spec + 撞坑 #64 公共 API 一致性):
    id              INTEGER PRIMARY KEY AUTOINCREMENT
    action          TEXT NOT NULL              # approve_outbox / cancel_outbox / confirm_note / dismiss_anomaly
    target_id       TEXT NOT NULL              # 与 WriteResult.target_id 对齐(str 表示)
    actor           TEXT NOT NULL DEFAULT 'local_dashboard'  # 审计字段(沿 v0.2.53.11 actor 默认值)
    reason          TEXT NOT NULL DEFAULT ''   # 用户操作原因(限 240 字符,AuditContext 严判)
    write_executed  INTEGER NOT NULL            # 0=False, 1=True(BOOLEAN → Integer, 沿 D3.2 雷区 #2)
    affected_id     TEXT NULL                   # 成功时填(str 表示的 int / str 本身)
    error           TEXT NULL                   # 失败时填(error code 字符串)
    executed_at_ms  INTEGER NOT NULL            # ms 时间戳(沿现有 store 范本)

索引:
    idx_audit_executed_at(executed_at_ms DESC) — 按时间倒序查询热路径(Dashboard /api/approval-gate/audits)
    idx_audit_action_action_at(action, executed_at_ms DESC) — 按 action 过滤 + 时间倒序

D3.2 8 雷区严判(本迁移全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本表非金额表)
    2. BOOLEAN 走 Integer + server_default="0" — ✅(write_executed 字段)
    3. DATE 走 Date — N/A(本表无日期字段,只用 INTEGER ms 时间戳)
    4. AUTOINCREMENT(非 AUTO_INCREMENT) — ✅
    5. 文件名 0016_approval_gate_audits.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("...") — ✅(idx_audit_executed_at DESC)

0014 范本应用(无 FK 软标记):
    本表无 FK 引用其他表(纯 audit log),不涉及 SQLite 自引用 FK 的 batch mode 限制。

撞坑 #18 边界应用(本迁移配套):
    - ApprovalGateAuditStore 默认 Stub(record 返回空 audit_id=None)
    - Real(ApprovalGateAuditStoreImpl) 留 v0.2.53.51+ 接入(DASHBOARD_REAL_DB=1 opt-in)
    - 默认不真写 DB(本迁移是 schema 定义,不执行实际数据写入)
    - 默认不真发 SMTP / 不读 Keychain 明文
    - 写保护锁未开时 BusinessWriterImpl 不落档(沿 v0.2.53.49 范本)

撞坑 #64 公共 API 一致性:
    - approval_gate_audits 与 anomaly_dismissals 字段风格一致(都无 FK,INTEGER ms,server_default 默认值)
    - audit_id 字符串格式 "audit:{id}",与 anomaly_dismissals 的 "dismissal:{id}" 对齐
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_approval_gate_audits"
down_revision: str | Sequence[str] | None = "0015_anomaly_dismissal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v0.2.53.51 ApprovalGate Audit 迁移: 创建 approval_gate_audits 表 + 2 索引.

    SQLite ALTER TABLE 限制(沿 env.py render_as_batch=True):
        - CREATE TABLE 支持所有约束(无限制)
        - 旧表无影响(新表,纯增量)
    """
    # ===== approval_gate_audits 表 =====
    op.create_table(
        "approval_gate_audits",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "action",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "actor",
            sa.Text(),
            nullable=False,
            server_default="local_dashboard",
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "write_executed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "affected_id",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "error",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "executed_at_ms",
            sa.Integer(),
            nullable=False,
        ),
    )

    # ===== idx_audit_executed_at 索引(DESC)=====
    # 按时间倒序查询热路径(Dashboard /api/approval-gate/audits?limit=10)
    # DESC 索引用 sa.text("...")(沿 D3.2 雷区 #8)
    op.create_index(
        "idx_audit_executed_at",
        "approval_gate_audits",
        [sa.text("executed_at_ms DESC")],
    )

    # ===== idx_audit_action_at 索引(action + DESC)=====
    # 按 action 过滤 + 时间倒序(P2 Dashboard 详情页可选过滤)
    op.create_index(
        "idx_audit_action_at",
        "approval_gate_audits",
        ["action", sa.text("executed_at_ms DESC")],
    )


def downgrade() -> None:
    """v0.2.53.51 ApprovalGate Audit 迁移: 删除 approval_gate_audits 表 + 2 索引(干净回滚).

    顺序与 upgrade 相反:索引 → 表。
    """
    op.drop_index("idx_audit_action_at", table_name="approval_gate_audits")
    op.drop_index("idx_audit_executed_at", table_name="approval_gate_audits")
    op.drop_table("approval_gate_audits")
