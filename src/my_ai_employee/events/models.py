"""D4.3 — Events ORM Model + 4 个 StrEnum + JSONDict TypeDecorator[Any].

参考 g004-events-reports-contract.md §Lane event contract:
  - event — typed name (EventType StrEnum, g004 不变量 1)
  - status — 7 枚举 (EventStatus StrEnum, g004 不变量 2)
  - metadata — JSON 必含 6 字段 (g004 不变量 3)
  - fingerprint — 物理去重键 (g004 不变量 4)

设计:
  - 4 个 StrEnum 集中管理, ORM 字段用 str 类型(不强制 enum 校验 — 校验由 contract.assert_event_invariants 做)
  - JSONDict TypeDecorator[Any] 参考 D3.2 JSONList (透明处理 dict[Any, Any] ↔ JSON 文本)
  - Event Model mirror schema.sql events (7 字段 + 1 UNIQUE + 6 索引)
  - 关系: 无 — events 表是事实流, 不外键关联其他表(subject_id 是软引用)
"""

from __future__ import annotations

import enum
import json
from typing import Any

from sqlalchemy import Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from my_ai_employee.core.models import Base  # 复用 D3.2 Base (单 metadata)

# ===== JSONDict TypeDecorator[Any] (mirror D3.2 JSONList 模式) =====


class JSONDict(TypeDecorator[Any]):
    """dict[Any, Any] ↔ JSON 文本 TypeDecorator[Any] (D4.3 新增, 与 D3.2 JSONList 同模式).

    行为:
        - DB → ORM: 文本 → dict[Any, Any] (空字符串/None → {})
        - ORM → DB: dict[Any, Any] → JSON 文本 (None → None, 空 dict[Any, Any] → "{}")

    为什么单独类: dict[Any, Any] 与 list[Any] 业务语义不同(事件 payload vs 邮件收件人列表),
    独立类名让 import 更清晰, TypeDecorator[Any] 内部逻辑可独立演进.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def, override]
        """ORM → DB: dict[Any, Any] 序列化为 JSON 文本. None → None."""
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def, override]
        """DB → ORM: JSON 文本 → dict[Any, Any]. 空字符串/None 一律视作 {}."""
        if not value:
            return {}
        return json.loads(value)


# ===== 4 个 StrEnum (g004 4 不变量 + 2 辅助) =====


class EventType(enum.StrEnum):
    """事件类型 — typed name 枚举 (g004 不变量 1).

    命名约定: "<domain>.<entity>.<action>" (3 段式, g004 风格).
    阶段: D4.3 暂定 10 个值, D4.4+ 按需扩展.
    """

    # LLM 路由 (D4.0/D4.1)
    LLM_CALL_STARTED = "llm.call.started"
    LLM_CALL_SUCCEEDED = "llm.call.succeeded"
    LLM_CALL_FAILED = "llm.call.failed"
    LLM_CALL_DEGRADED = "llm.call.degraded"  # fallback 触发

    # MCP server (D4.2)
    MCP_SERVER_CONNECTED = "mcp.server.connected"
    MCP_SERVER_DEGRADED = "mcp.server.degraded"
    MCP_SERVER_DISCONNECTED = "mcp.server.disconnected"

    # 邮件分类 (D4.4-classifier 阶段预留)
    EMAIL_CLASSIFY_SUCCEEDED = "email.classify.succeeded"
    EMAIL_CLASSIFY_FAILED = "email.classify.failed"

    # 草稿生成 (D4.5-drafter 阶段预留)
    DRAFT_GENERATE_SUCCEEDED = "draft.generate.succeeded"
    DRAFT_GENERATE_FAILED = "draft.generate.failed"

    # 任务策略板 (D4.4 policy engine 决策事件)
    POLICY_DECISION_MADE = "policy.decision.made"
    POLICY_DECISION_DEGRADED = "policy.decision.degraded"

    # Note structuring (D9.4 + v0.2.2 P0 L2 跨源候选)
    NOTE_STRUCTURED_L2_CANDIDATE = (
        "note.structured.l2_candidate"  # v0.2.2 P0 接入:UI 层 1-click 确认定位用
    )


class EventStatus(enum.StrEnum):
    """事件状态 — 7 枚举 (g004 不变量 2).

    负向证据 first-class: failed / degraded / skipped / blocked / cancelled 都是独立状态,
    区别于"事件不存在" — D3.3.3 教训应用.
    """

    STARTED = "started"  # 任务开始
    SUCCEEDED = "succeeded"  # 任务成功完成
    FAILED = "failed"  # 任务失败(异常抛出)
    DEGRADED = "degraded"  # 部分功能降级(走 fallback)
    SKIPPED = "skipped"  # 主动跳过(业务决策)
    BLOCKED = "blocked"  # 被策略阻止(等 owner 审批)
    CANCELLED = "cancelled"  # 主动取消(用户/超时)


class EventProvenance(enum.StrEnum):
    """事件来源 — 4 枚举 (g004 metadata.provenance).

    区分: live(生产) / test(测试) / replay(回放) / healthcheck(健康检查).
    """

    LIVE = "live"
    TEST = "test"
    REPLAY = "replay"
    HEALTHCHECK = "healthcheck"


class EventOwnership(enum.StrEnum):
    """事件所有权 — 3 枚举 (g004 metadata.ownership).

    act(触发 side effect) / observe(只读) / ignore(忽略).
    """

    ACT = "act"
    OBSERVE = "observe"
    IGNORE = "ignore"


# ===== Event ORM Model =====


class Event(Base):
    """结构化事件流 ORM Model (mirror schema.sql events).

    字段注解:
        - id:          INTEGER PK AUTOINCREMENT
        - event:       TEXT NOT NULL              # EventType 枚举值
        - status:      TEXT NOT NULL              # EventStatus 枚举值
        - source:      TEXT NOT NULL DEFAULT ''   # 事件源头
        - subject_id:  TEXT                       # 关联实体 ID (可空)
        - fingerprint: TEXT NOT NULL DEFAULT ''   # SHA-256 派生键(物理去重)
        - event_metadata: JSON NOT NULL DEFAULT {}   # 6 必含字段 + 业务 payload
                                                    # (列名 event_metadata 避开 SA 保留属性 metadata)
        - created_at:  INTEGER NOT NULL           # Unix epoch ms

    约束:
        - UNIQUE(fingerprint) → fingerprint 全局唯一 (g004 不变量 4)
        - D4.3.1 复检 P1 修复: 旧 4 字段 UNIQUE 在 subject_id=NULL 时被 SQLite 视为不同行,
          破坏 dedupe. 改 fingerprint 全局唯一键. fallback 跨源场景由 compute_fingerprint
          入参含 source 保证 fingerprint 不同, 不被误判.

    索引:
        - idx_events_created_at (created_at DESC)  # 热路径: 倒序拉最近事件
        - idx_events_event
        - idx_events_status
        - idx_events_source
        - idx_events_subject_id
        - idx_events_fingerprint

    关系: 无 (subject_id 是软引用, 不外键)

    注意: 列名 / ORM 属性名 = event_metadata(避开 SQLAlchemy Declarative 保留属性 metadata).
    业务层 / contract / fingerprint 内部仍用 "metadata" 命名(g004 风格, 业务友好).
    """

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    subject_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONDict, nullable=False, default=dict[Any, Any], server_default="{}"
    )
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_events_fingerprint"),
        Index("idx_events_created_at", text("created_at DESC")),
        Index("idx_events_event", "event"),
        Index("idx_events_status", "status"),
        Index("idx_events_source", "source"),
        Index("idx_events_subject_id", "subject_id"),
        Index("idx_events_fingerprint", "fingerprint"),
    )

    def __repr__(self) -> str:
        return (
            f"<Event id={self.id} event={self.event!r} "
            f"status={self.status!r} source={self.source!r} subject_id={self.subject_id!r}>"
        )


# ===== 模块导出 =====


__all__ = [
    "Event",
    "EventType",
    "EventStatus",
    "EventProvenance",
    "EventOwnership",
    "JSONDict",
]
