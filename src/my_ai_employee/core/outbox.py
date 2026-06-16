"""D4.8 草稿入库/发送 ORM 模型 — outbox 表 + 3 个 StrEnum 枚举。

位置说明:本文件位于 `core/outbox.py`(与 `core/models.py` 单文件平级),
  原因:`core/models.py` 是 432 行单文件(6 Model + Base),Python 解释器会优先选
  单文件而非同名 `core/models/` 子目录,导致 `core/models/outbox.py` 命名空间
  不可达。解决方案是把 outbox 提到 `core/` 顶层,与 `core/sync.py` / `core/db.py`
  平级,3 个 import 改 `from my_ai_employee.core.outbox import ...` 即可(sync.py
  / env.py / events/models.py 仍 import `core.models`,不受影响)。

承接 D4.8.1 outbox migration 0004(11 字段 + UNIQUE(email_id) + 2 索引 + 2 FK)。

3 个 StrEnum 枚举(顺序固定,业务层做"按状态分组"时可直接用 list(Enum) 排序):
    - OutboxStatus: 6 状态(pending_send / approved / sending / sent / failed / cancelled)
                    D4.8 4 状态 → D5.2 6 状态(加 sending / failed,B5 解封项)
    - OutboxTone: 3 语气(FORMAL / FRIENDLY / CONCISE),与 D4.7.3 DraftTone 字段值一致
                  (独立枚举,业务边界清晰:outbox 是入库产物,draft 是生成过程)
    - OutboxPriority: 6 优先级(v0.2 B1.1 扩 3→6:urgent / high / normal / low / batch / digest)

状态机白名单 ALLOWED_TRANSITIONS(D5.2 B5 解封项 — 6 状态 × 各自目标集):
    PENDING_SEND → {SENDING, APPROVED, FAILED, CANCELLED}
                   (D5.2 vs D5 启动计划文档偏差: 启动计划不含 APPROVED,
                    实际保留 APPROVED 以兼容 D4.8 v1.0.1 test_update_status_pending_to_approved 契约)
    APPROVED     → {SENDING, FAILED, CANCELLED}
    SENDING      → {SENT, FAILED}
    SENT         → {}    (终态)
    FAILED       → {PENDING_SEND, CANCELLED}  # 重试回 PENDING_SEND
    CANCELLED    → {}    (终态)

OutboxEntry 12 字段(0004 11 字段 + 0006 加 last_approved_at_ms,D5.6.3 P1-1 审批凭据):
    - id                  INTEGER PK AUTOINCREMENT
    - email_id            INTEGER NOT NULL UNIQUE — 入库幂等性键
    - subject             TEXT NOT NULL — 1-200 字符(应用层 _validate_outbox_subject 严判)
    - body                TEXT NOT NULL — 10-8000 字符(应用层 _validate_outbox_body 严判)
    - tone                TEXT NOT NULL — OutboxTone 3 选 1
    - reviewer_decision_event_id  INTEGER NULL — FK → events.id
    - drafter_decision_event_id   INTEGER NULL — FK → events.id
    - status              TEXT NOT NULL DEFAULT 'pending_send' — OutboxStatus 6 选 1(D5.2 扩)
    - created_at          INTEGER NOT NULL — Unix epoch ms
    - recipient_email     TEXT NOT NULL — 含 @ 即可
    - priority            TEXT NOT NULL DEFAULT 'normal' — OutboxPriority 6 选 1(v0.2 B1.1 扩 3→6:urgent/high/normal/low/batch/digest)
    - last_approved_at_ms INTEGER NULL — D5.6.3 P1-1 审批凭据(显式审批时间戳,Unix epoch ms)
                          应用层 OutboxDispatcher 拉批严判 is not None,防 FAILED 绕过审批契约

约束 + 索引(与 0004 migration 一致):
    - UNIQUE(email_id)
    - idx_outbox_status_created_at(status, created_at DESC)
    - idx_outbox_priority_created_at(priority, created_at DESC)
    - 2 FK → events.id (reviewer / drafter, ON DELETE SET NULL)

D4.7.3 v1.0.6 教训应用:
    - 顺序固定(FORMAL → FRIENDLY → CONCISE),业务层做"按语气分组"时可直接用 list(Enum) 排序
    - frozenset 严判白名单 _OUTBOX_TONE_CHOICES / _OUTBOX_STATUS_CHOICES / _OUTBOX_PRIORITY_CHOICES
    - DDL 走 TEXT(SQLite 不支持 ENUM 类型),ORM 走 StrEnum 严判
    - OutboxTone 独立枚举不复用 DraftTone(业务边界清晰 + 字段名级别硬区分 D4.7.3 v1.0.3 P2-1 范本)
    - 跨字段校验 priority=urgent ↔ email_category=URGENT 在应用层 _validate_outbox_priority 严判
      (D4.7.3 v1.0.4 P1-1 范本,ORM 层不表达跨表约束)
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import (
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from my_ai_employee.core.models import Base

# ===== 3 个 StrEnum 枚举(契约层) =====


class OutboxStatus(StrEnum):
    """Outbox 6 状态枚举(D5.2 业务层契约 — D5.2 从 4 状态扩 6 状态,B5 解封)。

    D5.2 状态机白名单 ALLOWED_TRANSITIONS(见下方模块级常量):
        PENDING_SEND → {SENDING, APPROVED, FAILED, CANCELLED}
        APPROVED     → {SENDING, FAILED, CANCELLED}
        SENDING      → {SENT, FAILED}
        SENT         → {}    (终态)
        FAILED       → {PENDING_SEND, CANCELLED}  # 重试回 PENDING_SEND
        CANCELLED    → {}    (终态)

    顺序固定,业务层做"按状态分组"时可直接用 list(OutboxStatus) 排序
    (pending_send 最先 / cancelled 最后)。

    D5.2 vs D5 启动计划文档偏差(报告必标注):
        D5 启动计划文档 PENDING_SEND → {SENDING, FAILED, CANCELLED}(3 目标)
        D5.2 实际白名单 PENDING_SEND → {SENDING, APPROVED, FAILED, CANCELLED}(4 目标)
        偏差原因: 保留 APPROVED 兼容 D4.8 v1.0.1 test_update_status_pending_to_approved 契约
        (D4.8 L498-509 锁定),D5 业务调度器可走快路径(SENDING 直接)或
        显式批准路径(APPROVED → SENDING)
    """

    PENDING_SEND = "pending_send"  # 默认:D4.8 入库产物
    APPROVED = "approved"  # 显式批准,D5+ 调度器可走显式批准路径
    SENDING = "sending"  # D5.2 新增:SMTP 发送中(中间态,避免"假发送"风险)
    SENT = "sent"  # SMTP 发送成功,D5+ 才进入此状态(D4.8 不真发)
    FAILED = "failed"  # D5.2 新增:SMTP 发送失败(可重试回 PENDING_SEND 或转 CANCELLED)
    CANCELLED = "cancelled"  # 用户取消,D5+ 调度器


# 6 状态枚举值集合(O(1) 校验,D5.2 扩 4→6)
_OUTBOX_STATUS_CHOICES: frozenset[str] = frozenset(s.value for s in OutboxStatus)


# ===== D5.2 状态机白名单 ALLOWED_TRANSITIONS(模块级常量,业务层严判依据)=====
# 6 状态 × 各自合法目标集,显式枚举,无推导逻辑。
# 任何状态机严判都查这张表,不在表内的转换直接 OutboxIllegalTransitionError。
#
# 设计原则(D5.2 B5 解封):
#   1. 显式优于隐式: 白名单硬编码,不靠运行时推导(沿 D4.7.3 v1.0.4 P1-2 范本)
#   2. 终态空集: SENT/CANCELLED 不可转出(显式 frozenset() 表达)
#   3. 重试回路: FAILED → PENDING_SEND(指数退避后重试,D5.5 退避公式应用)
#   4. 显式批准: APPROVED 作为 PENDING_SEND 合法目标,保留 D4.8 v1.0.1 契约
#
# D5.2 vs D5 启动计划文档偏差: PENDING_SEND 目标集加 APPROVED(决策理由见 OutboxStatus docstring)
ALLOWED_TRANSITIONS: dict[OutboxStatus, frozenset[OutboxStatus]] = {
    OutboxStatus.PENDING_SEND: frozenset(
        {OutboxStatus.SENDING, OutboxStatus.APPROVED, OutboxStatus.FAILED, OutboxStatus.CANCELLED}
    ),
    OutboxStatus.APPROVED: frozenset(
        {OutboxStatus.SENDING, OutboxStatus.FAILED, OutboxStatus.CANCELLED}
    ),
    OutboxStatus.SENDING: frozenset(
        {OutboxStatus.SENT, OutboxStatus.FAILED, OutboxStatus.CANCELLED}
    ),
    # 业务阻断链路: SMTPRecipientsRefused / SMTPSenderRefused / SMTPDataError /
    # SMTPAuthenticationError 在 SENDING 中间态触发永久退信 → SENDING → CANCELLED
    # (D5.3 P1 硬收口: D5.4 Dispatcher 必须能捕获业务阻断异常, 就地推 SENDING → CANCELLED,
    #  避免 dangling SENDING 状态; 否则 ALLOWED_TRANSITIONS 会挡死)
    OutboxStatus.SENT: frozenset(),  # 终态
    # D5.6.2 P1.2 修复:FAILED 退避重试新增 → APPROVED 直通转换
    # 之前 FAILED 只能 → PENDING_SEND,然后 dispatcher 又被 P1.2 修复禁拉批 PENDING_SEND
    # (用户审批契约),陷入"必须先批 PENDING_SEND → APPROVED 才能发,但 FAILED 重试
    # 又必须先 PENDING_SEND"死锁。新增 FAILED → APPROVED 直通,让退避后重试保留
    # 原审批标记(同用户已审批过),无需用户重新审批。
    OutboxStatus.FAILED: frozenset(
        {OutboxStatus.PENDING_SEND, OutboxStatus.APPROVED, OutboxStatus.CANCELLED}
    ),
    OutboxStatus.CANCELLED: frozenset(),  # 终态
}


class OutboxTone(StrEnum):
    """Outbox 3 类语气枚举(与 D4.7.3 DraftTone 字段值一致,独立枚举)。

    独立枚举不复用 DraftTone 的理由:
        - 业务边界清晰:outbox 是入库产物,draft 是生成过程
        - 字段名级别硬区分(D4.7.3 v1.0.3 P2-1 范本,防通用 `if enum == DraftTone` 误用)
        - 未来扩枚举(outbox 可能加"自动/AUTO"等业务专属 tone)不会跨模块污染

    顺序固定(FORMAL → FRIENDLY → CONCISE),业务层做"按语气分组"时可直接用
    list(OutboxTone) 排序。
    """

    FORMAL = "FORMAL"  # 正式:商务 / 官方 / 客户沟通
    FRIENDLY = "FRIENDLY"  # 友好:同事 / 熟人 / 协作
    CONCISE = "CONCISE"  # 简洁:通知 / 确认 / 单点沟通


# 3 类语气枚举值集合(O(1) 校验)
_OUTBOX_TONE_CHOICES: frozenset[str] = frozenset(t.value for t in OutboxTone)


class OutboxPriority(StrEnum):
    """Outbox 6 优先级枚举(D5+ 发送调度器排序用,v0.2 B1 扩展)。

    跨字段校验(应用层 _validate_outbox_priority 严判,D4.7.3 v1.0.4 P1-1 范本):
        - priority=urgent ↔ email_category=URGENT(D4.7.4 联动契约)
        - 不允许 priority=urgent + email_category ∈ {TODO, FYI, SPAM, PERSONAL}
          (D5+ 调度器会把 urgent 当作高优先级,误标会浪费调度资源)

    顺序固定(urgent 最先 / digest 最后),业务层做"按优先级排序"时可直接用
    list(OutboxPriority) 排序(urgent 在前)。

    v0.2 B1 扩展(2026-06-16 上午):
      - URGENT/NORMAL/LOW 原 3 类(D5 沿用)
      - 新增 HIGH(URGENT 之下 NORMAL 之上,30min SLA,v0.2 B1.1)
      - 新增 BATCH(批量发送,24h SLA,可错峰,v0.2 B1.1)
      - 新增 DIGEST(摘要合并,7d SLA,v0.2 B1.1)
      - BATCH/DIGEST 是子分类(批量/摘要),不是优先级提升(决策沿 v0.2-substage-mapping.md §1.5)
    """

    URGENT = "urgent"  # 紧急:D4.7.4 联动 email_category=URGENT 触发,D5+ 优先发送
    HIGH = "high"  # 高优(v0.2 B1.1 新增,30min SLA,URGENT 之下 NORMAL 之上)
    NORMAL = "normal"  # 普通:默认,大多数邮件
    LOW = "low"  # 低优:D5+ 调度器排到最后
    BATCH = "batch"  # 批量(v0.2 B1.1 新增,24h SLA,可错峰)
    DIGEST = "digest"  # 摘要(v0.2 B1.1 新增,7d SLA,合并发送)


# 6 优先级枚举值集合(O(1) 校验,v0.2 B1.1 扩展)
_OUTBOX_PRIORITY_CHOICES: frozenset[str] = frozenset(p.value for p in OutboxPriority)


# ===== ORM Model =====


class OutboxEntry(Base):
    """Outbox 入库表(草稿审阅通过后入库,等待 D5+ 发送调度器轮询)。

    业务语义:
        - D4.7.4 草稿审阅通过 + D4.7.3 草稿生成产物 → OutboxEntry.store_and_emit
        - email_id 唯一索引 → 入库幂等性(同 email_id 二次入库走业务阻断入口)
        - status DEFAULT 'pending_send' → D4.8 仅入库到此状态
        - priority DEFAULT 'normal' → 大多数邮件 normal,urgent 需 D4.7.4 联动触发
        - last_approved_at_ms NULL 默认(D5.6.3 P1-1 审批凭据)→ 调度器拉批严判 is not None
          防 PENDING_SEND → FAILED → APPROVED → SENT 绕过用户审批契约

    字段注解(完全 mirror 0004_outbox_table migration + 0006 字段 + 0009_sla_due_at v0.2 B2.1):
        - id:                     INTEGER PK AUTOINCREMENT
        - email_id:               INTEGER NOT NULL UNIQUE — 关联 emails.id
        - subject:                TEXT NOT NULL — 1-200 字符,strip() 后非空
        - body:                   TEXT NOT NULL — 10-8000 字符,strip() 后非空
        - tone:                   TEXT NOT NULL — OutboxTone 3 选 1
        - reviewer_decision_event_id:  INTEGER NULL — FK → events.id,D5+ 收紧为 NOT NULL
        - drafter_decision_event_id:   INTEGER NULL — FK → events.id,D5+ 收紧为 NOT NULL
        - status:                 TEXT NOT NULL DEFAULT 'pending_send' — OutboxStatus 6 选 1(D5.2 扩)
        - created_at:             INTEGER NOT NULL — Unix epoch ms
        - recipient_email:        TEXT NOT NULL — 含 @ 即可
        - priority:               TEXT NOT NULL DEFAULT 'normal' — OutboxPriority 6 选 1(v0.2 B1.1 扩 3→6)
        - last_approved_at_ms:    INTEGER NULL — D5.6.3 P1-1 审批凭据,Unix epoch ms,
                                   OutboxDispatcher 拉批严判 is not None
        - sla_due_at_ms:          INTEGER NULL — v0.2 B2.1 新增,OutboxStore.insert 时预计算
                                   (= created_at + sla_threshold_ms(priority)),用于调度器
                                   优先 SLA 临近(避免每次实时算 age_ms)。旧 outbox 条目
                                   NULL 表示未预计算,OutboxStore.update 不强制更新(向后兼容)。

    约束:
        - UNIQUE(email_id) — 入库幂等性(D4.8 契约 4)

    索引:
        - idx_outbox_status_created_at(status, created_at DESC) — D5+ 调度器轮询
        - idx_outbox_priority_created_at(priority, created_at DESC) — 紧急优先排序
        - idx_outbox_sla_due_at(sla_due_at_ms) — v0.2 B2.1 新增,SLA 临近查询热路径
    """

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_id: Mapped[int] = mapped_column(Integer, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_decision_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drafter_decision_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending_send", server_default="pending_send"
    )
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_email: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(
        Text, nullable=False, default="normal", server_default="normal"
    )
    # D5.6.3 P1-1 审批凭据:显式审批时间戳(Unix epoch ms)
    # - nullable=True:默认无审批(PENDING_SEND 入库时 NULL)
    # - 写入时机:OutboxStore.update_status(new_status=APPROVED, last_approved_at_ms=now_ms)
    # - 保留时机:SENDING → SENT / SENDING → FAILED 时不动(避免重试时丢审批标记)
    # - 严判:OutboxDispatcher 拉批时 is not None,否则 skipped(防 PENDING_SEND → FAILED
    #   → APPROVED → SENT 绕过用户审批契约)
    last_approved_at_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # v0.2 B2.1 新增:SLA 截止时间预计算(created_at + sla_threshold_ms(priority))
    # - nullable=True:旧 outbox 条目 NULL 表示未预计算(向后兼容)
    # - 写入时机:OutboxStore.insert 内部预计算(B2.1)
    # - 应用层使用:OutboxDispatcher 优先 sla_due_at_ms < now_ms + 5min 的紧急项
    sla_due_at_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 约束 + 索引(与 0004_outbox_table migration 一致,D3.2.3 DESC 索引用 text() 表达)
    __table_args__ = (
        UniqueConstraint("email_id", name="uq_outbox_email_id"),
        ForeignKeyConstraint(
            ["reviewer_decision_event_id"],
            ["events.id"],
            name="fk_outbox_reviewer_event",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["drafter_decision_event_id"],
            ["events.id"],
            name="fk_outbox_drafter_event",
            ondelete="SET NULL",
        ),
        Index("idx_outbox_status_created_at", "status", text("created_at DESC")),
        Index("idx_outbox_priority_created_at", "priority", text("created_at DESC")),
        # v0.2 B2.1 新增:SLA 临近查询热路径
        Index("idx_outbox_sla_due_at", "sla_due_at_ms"),
    )


__all__ = [
    "OutboxStatus",
    "OutboxTone",
    "OutboxPriority",
    "OutboxEntry",
    "ALLOWED_TRANSITIONS",  # D5.2 新增:状态机白名单(模块级常量)
    "_OUTBOX_STATUS_CHOICES",
    "_OUTBOX_TONE_CHOICES",
    "_OUTBOX_PRIORITY_CHOICES",
]
