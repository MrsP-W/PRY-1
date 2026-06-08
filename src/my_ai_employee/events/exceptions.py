"""D4.3 — Events 业务异常（4 类窄化 + 编程错误透传）。

参考 D3.3.3 教训: 异常范围要窄化到真要处理的类型.
- EventContractError    — event/status 字段非法(枚举值不在白名单)
- EventMetadataError    — metadata 缺 6 必含字段或类型错
- EventFingerprintConflictError — UNIQUE(fingerprint) 冲突 (D4.3.1 复检 P1 修复: 旧 4 字段 UNIQUE 改 fingerprint 全局唯一)
- EventError            — 基类(不是 Exception 兜底)

ValueError / TypeError (编程错误) 透传, 不包装.
"""

from __future__ import annotations


class EventError(Exception):
    """Events 业务异常基类.

    不继承具体业务类, 而是用 isinstance 判断细类.
    """


class EventContractError(EventError):
    """event/status 字段非法(枚举值不在白名单).

    例: event="invalid.event" 不在 EventType 枚举 → EventContractError
        status="unknown" 不在 EventStatus 枚举 → EventContractError
    """


class EventMetadataError(EventError):
    """metadata 字段缺 6 必含字段或类型错.

    6 必含字段: seq / timestamp_ms / session_id / ownership / provenance / fingerprint
    """


class EventFingerprintConflictError(EventError):
    """UNIQUE(fingerprint) 冲突 (D4.3.1 复检 P1 修复: 旧 4 字段 UNIQUE 改全局唯一).

    EventStore.insert() 检测到已有同 fingerprint 行 → 抛此异常(可选, 默认静默去重).
    抛 vs 静默 由调用方决定(upsert 静默, 严格模式抛).
    """
