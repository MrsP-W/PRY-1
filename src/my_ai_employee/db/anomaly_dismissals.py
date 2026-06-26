"""v0.2.53.16 AnomalyDismissal ORM — anomaly_dismissals 表(沿 v0.2.53.14 §5.3 设计).

承接 docs/v0.2.53.14-business-writer-design-2026-06-26.md §5.3 AnomalyDismissalService 存储设计:
    - finance.dismiss_anomaly 是 v0.2.53.11 ApprovalGate 契约白名单的 4 类动作之一
    - AnomalyDismissalService Protocol + Stub 已落地(v0.2.53.16)
    - 本文件定义 ORM 模型(0015_anomaly_dismissal migration 已建表),Real 留 v0.2.53.17+

字段注解:
    - id:              INTEGER PK AUTOINCREMENT
    - anomaly_id:      TEXT NOT NULL                  # date|counterparty|amount 编码格式
    - reason:          TEXT NOT NULL DEFAULT ''       # 用户 dismiss 原因(限 240 字符,Stub 严判)
    - actor:           TEXT NOT NULL DEFAULT 'local_dashboard'  # 审计字段(沿 v0.2.53.11 actor 默认)
    - dismissed_at_ms: INTEGER NOT NULL               # ms 时间戳

约束:
    - UNIQUE(anomaly_id) — 同 ID 只 dismiss 1 次(避免重复落档)

索引:
    - idx_dismissed_at(dismissed_at_ms DESC) — 按时间倒序查询热路径

D3.2 8 雷区严判(本 ORM 全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本表非金额)
    2. BOOLEAN 走 Integer — N/A(本表无 BOOLEAN)
    3. DATE 走 Date — N/A(本表无日期,只用 INTEGER ms)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)— ✅
    5. 字段与 0015 migration 严格对齐(后续 schema 漂移检测会校验)
    6. (迁移侧)downgrade() 干净回滚
    7. render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
    8. DESC 索引用 sa.text("...")(D3.2 雷区 #8) — ✅

撞坑 #65 边界应用(本 ORM 配套):
    - 默认 AnomalyDismissalServiceStub(is_enabled=False)
    - Real(AnomalyDismissalServiceImpl) 留 v0.2.53.17+
    - 默认不真写 DB / 不发 SMTP / 不读 Keychain 明文
"""

from __future__ import annotations

from sqlalchemy import Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from my_ai_employee.core.models import Base


class AnomalyDismissal(Base):
    """财务异常 dismiss 落档表(mirror 0015 alembic migration)."""

    __tablename__ = "anomaly_dismissals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    actor: Mapped[str] = mapped_column(Text, nullable=False, server_default="local_dashboard")
    dismissed_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # 约束 + 索引(D3.2 雷区 #8: DESC 索引用 sa.text 包裹)
    __table_args__ = (
        UniqueConstraint("anomaly_id", name="uq_anomaly_dismissals_anomaly_id"),
        Index("idx_dismissed_at", text("dismissed_at_ms DESC")),
    )

    def __repr__(self) -> str:
        return (
            f"<AnomalyDismissal id={self.id} anomaly_id={self.anomaly_id!r} "
            f"actor={self.actor!r} dismissed_at_ms={self.dismissed_at_ms}>"
        )
