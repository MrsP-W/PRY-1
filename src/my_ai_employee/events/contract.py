"""D4.3 — Events 契约 helpers (g004 4 大不变量核心).

参考 g004-events-reports-contract.md §Lane event contract:
  - 6 必含 metadata 字段: seq / timestamp_ms / session_id / ownership / provenance / fingerprint
  - fingerprint 是 SHA-256 派生键(去重)
  - structured-event-trumps-prose: if event 存在, 不从 prose 推断

设计:
  - build_event_metadata(): 工厂函数, 强制生成 6 必含字段(避免漏字段)
  - assert_event_invariants(): 校验函数, 不通过抛 EventContractError / EventMetadataError
  - compute_fingerprint(): SHA-256 派生键(去重 + 跨表查找)

失败模式 (D3.3.3 教训):
  - 字段缺失 / 类型错 → EventMetadataError
  - event/status 非法枚举 → EventContractError
  - 编程错误 (TypeError/ValueError) 透传
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from my_ai_employee.events.exceptions import (
    EventContractError,
    EventMetadataError,
)
from my_ai_employee.events.models import (
    EventOwnership,
    EventProvenance,
    EventStatus,
    EventType,
)

# ===== 常量 =====

# 6 必含 metadata 字段 (g004 不变量 3)
REQUIRED_METADATA_KEYS: tuple[str, ...] = (
    "seq",
    "timestamp_ms",
    "session_id",
    "ownership",
    "provenance",
    "fingerprint",
)


# ===== build_event_metadata =====


def build_event_metadata(
    seq: int,
    session_id: str = "",
    ownership: EventOwnership | str = EventOwnership.OBSERVE,
    provenance: EventProvenance | str = EventProvenance.LIVE,
    extra: dict[str, Any] | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """构造 metadata 字典(强制含 6 必含字段).

    Args:
        seq: 单调递增序号(同 session 内唯一; 跨 session 全局唯一更好)
        session_id: 会话身份(空字符串 = 全局)
        ownership: 事件所有权(act/observe/ignore)
        provenance: 事件来源(live/test/replay/healthcheck)
        extra: 业务扩展字段(可包含 task_id / tokens / latency_ms 等;
              **禁止**包含 6 必含字段 (seq/timestamp_ms/session_id/ownership/provenance/fingerprint),
              否则抛 ValueError — D4.3.2 复检 P1 修复)
        timestamp_ms: Unix epoch ms(默认 = 当前时间, 便于测试时注入固定值)

    Returns:
        metadata 字典(已含 6 必含字段, fingerprint 暂时为空字符串 —
        真正的 fingerprint 由 compute_fingerprint() 计算后由 caller 写回)

    Raises:
        ValueError:
            - seq < 0 (编程错误, 透传)
            - ownership / provenance 非法枚举 (编程错误, 透传)
            - **extra 包含契约保留字段** (D4.3.2 复检 P1 修复 — 防覆盖)
    """
    if seq < 0:
        raise ValueError(f"seq 必须 >= 0, 实际 {seq}")
    # 枚举值归一 (支持 enum 实例 / 字符串)
    own_value = _normalize_enum(ownership, EventOwnership, "ownership")
    prov_value = _normalize_enum(provenance, EventProvenance, "provenance")
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)

    meta: dict[str, Any] = {
        "seq": seq,
        "timestamp_ms": ts,
        "session_id": session_id,
        "ownership": own_value,
        "provenance": prov_value,
        "fingerprint": "",  # 占位, 由 caller 调 compute_fingerprint 后写回
    }
    # D4.3.2 复检 P1 修复 (contract.py:92): 禁止 extra 覆盖 6 必含字段
    # 旧实现 `meta.update(extra)` 允许 extra={"seq": -1, "timestamp_ms": -5} 覆盖已校验字段,
    # 绕过 seq>=0 / timestamp_ms 类型检查. 现拒绝包含 REQUIRED_METADATA_KEYS 的 extra.
    if extra:
        forbidden = set(REQUIRED_METADATA_KEYS) & set(extra.keys())
        if forbidden:
            raise ValueError(
                f"extra 包含契约保留字段: {sorted(forbidden)}; "
                f"如需传 seq/timestamp_ms/session_id/ownership/provenance, "
                f"请用 build_event_metadata 的命名参数, extra 仅用于业务 payload"
            )
        meta.update(extra)
    return meta


# ===== assert_event_invariants =====


def assert_event_invariants(
    event: str | EventType,
    status: str | EventStatus,
    metadata: dict[str, Any],
) -> None:
    """校验事件满足 g004 4 大不变量.

    Args:
        event: 事件类型(enum 或字符串)
        status: 事件状态(enum 或字符串)
        metadata: 6 必含字段 + 业务 payload

    Raises:
        EventContractError: event/status 非法枚举
        EventMetadataError: metadata 缺字段 / 类型错
        ValueError / TypeError: 编程错误(透传)
    """
    # 不变量 1: event 必须在 EventType 枚举
    _validate_enum(event, EventType, "event")
    # 不变量 2: status 必须在 EventStatus 枚举
    _validate_enum(status, EventStatus, "status")
    # 不变量 3: metadata 必含 6 字段 + 类型校验
    if not isinstance(metadata, dict):
        raise EventMetadataError(f"metadata 必须是 dict, 实际 {type(metadata).__name__}")
    missing = [k for k in REQUIRED_METADATA_KEYS if k not in metadata]
    if missing:
        raise EventMetadataError(f"metadata 缺必含字段: {missing}")
    # 字段类型校验
    if not isinstance(metadata["seq"], int):
        raise EventMetadataError(f"seq 必须是 int, 实际 {type(metadata['seq']).__name__}")
    if not isinstance(metadata["timestamp_ms"], int):
        raise EventMetadataError(
            f"timestamp_ms 必须是 int, 实际 {type(metadata['timestamp_ms']).__name__}"
        )
    if not isinstance(metadata["session_id"], str):
        raise EventMetadataError(
            f"session_id 必须是 str, 实际 {type(metadata['session_id']).__name__}"
        )
    if not isinstance(metadata["ownership"], str):
        raise EventMetadataError(
            f"ownership 必须是 str, 实际 {type(metadata['ownership']).__name__}"
        )
    if not isinstance(metadata["provenance"], str):
        raise EventMetadataError(
            f"provenance 必须是 str, 实际 {type(metadata['provenance']).__name__}"
        )
    if not isinstance(metadata["fingerprint"], str):
        raise EventMetadataError(
            f"fingerprint 必须是 str, 实际 {type(metadata['fingerprint']).__name__}"
        )
    # 嵌套枚举校验
    if metadata["ownership"] not in {e.value for e in EventOwnership}:
        raise EventMetadataError(
            f"ownership 非法: {metadata['ownership']!r} 不在 EventOwnership 枚举"
        )
    if metadata["provenance"] not in {e.value for e in EventProvenance}:
        raise EventMetadataError(
            f"provenance 非法: {metadata['provenance']!r} 不在 EventProvenance 枚举"
        )


# ===== compute_fingerprint =====


def compute_fingerprint(
    event: str | EventType,
    status: str | EventStatus,
    source: str,
    subject_id: str | None,
    metadata: dict[str, Any],
) -> str:
    """计算 SHA-256 fingerprint(物理去重键, g004 不变量 4).

    Args:
        event: 事件类型
        status: 事件状态
        source: 事件源头
        subject_id: 关联实体 ID
        metadata: 6 必含字段 + 业务 payload

    Returns:
        SHA-256 十六进制字符串(64 字符)

    设计:
        - fingerprint = 事件身份(同业务事件 dedupe, 与时间无关)
        - 哈希字段: event / status / source / subject_id /
          metadata 中"非运行时"字段(ownership / provenance / session_id / extra payload)
        - 排除运行时字段: timestamp_ms / seq / fingerprint 自身
          (同一业务事件多次重试 timestamp_ms/seq 不同, 不应导致 fingerprint 漂移)
    """
    event_value = _normalize_enum(event, EventType, "event")
    status_value = _normalize_enum(status, EventStatus, "status")
    # 提取"事件身份"相关字段(排除运行时变量)
    runtime_fields = {"timestamp_ms", "seq", "fingerprint"}
    identity_meta = {k: v for k, v in metadata.items() if k not in runtime_fields}
    import json as _json

    payload = {
        "event": event_value,
        "status": status_value,
        "source": source,
        "subject_id": subject_id,
        "metadata": identity_meta,
    }
    canonical = _json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ===== 内部 helpers =====


def _normalize_enum(value: Any, enum_cls: type, field_name: str) -> str:
    """归一 enum/str → str 值, 非法枚举抛 EventContractError."""
    if isinstance(value, enum_cls):
        # mypy: isinstance 已收窄, 但 .value 是 enum 属性, 需显式断言
        return str(value.value)  # type: ignore[attr-defined]
    if isinstance(value, str):
        # 迭代 enum_cls 成员(用 vars() 走 __members__, isinstance 用 enum_cls 自身)
        valid = {str(e.value) for e in vars(enum_cls).values() if isinstance(e, enum_cls)}  # type: ignore[attr-defined]
        if value not in valid:
            raise EventContractError(
                f"{field_name} 非法: {value!r} 不在 {enum_cls.__name__} 枚举 ({valid})"
            )
        return value
    raise EventContractError(
        f"{field_name} 类型错: 期望 {enum_cls.__name__} 或 str, 实际 {type(value).__name__}"
    )


def _validate_enum(value: Any, enum_cls: type, field_name: str) -> None:
    """校验 value 是合法 enum 值(纯校验, 不返回)."""
    _normalize_enum(value, enum_cls, field_name)


# ===== 模块导出 =====


__all__ = [
    "REQUIRED_METADATA_KEYS",
    "build_event_metadata",
    "assert_event_invariants",
    "compute_fingerprint",
]
