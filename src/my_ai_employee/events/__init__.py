"""D4.3 — Events 表契约（g004 4 大不变量结构化事件流）。

参考: claw-code `g004-events-reports-contract.md`

D4.3 范围:
    - events 表 schema + ORM Model (mirror schema.sql)
    - 4 大不变量落地: typed event / status / 6 必含 metadata 字段 / fingerprint 去重
    - 4 类异常窄化 (D3.3.3 教训应用): EventContractError / EventMetadataError /
      EventFingerprintConflictError + EventError 基类
    - EventStore: insert / by_session / by_subject / by_event_type / by_status

D4.3 不含:
    - 真实 LLM/MCP/分类业务调用 — 这些是 D4.4+ 任务
    - 熔断器 (D4.4 任务策略板再加)
    - 报告 schema v1 (D4.4+ 投影层再加)

注: audit_log 表 (D3 sync 审计) 与 events 表 (D4+ 智能层结构化事件) 职责正交, 互不替代.
"""

from __future__ import annotations

from my_ai_employee.events.contract import (
    REQUIRED_METADATA_KEYS,
    assert_event_invariants,
    build_event_metadata,
    compute_fingerprint,
)
from my_ai_employee.events.exceptions import (
    EventContractError,
    EventError,
    EventFingerprintConflictError,
    EventMetadataError,
)
from my_ai_employee.events.models import (
    Event,
    EventOwnership,
    EventProvenance,
    EventStatus,
    EventType,
    JSONDict,
)
from my_ai_employee.events.store import EventStore

__all__ = [
    # 模型
    "Event",
    "EventType",
    "EventStatus",
    "EventProvenance",
    "EventOwnership",
    "JSONDict",
    # 契约
    "REQUIRED_METADATA_KEYS",
    "build_event_metadata",
    "assert_event_invariants",
    "compute_fingerprint",
    # 存储
    "EventStore",
    # 异常
    "EventError",
    "EventContractError",
    "EventMetadataError",
    "EventFingerprintConflictError",
]
