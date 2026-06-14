"""D6.3 — transactions.py 状态机(5 状态 + ALLOWED_TRANSITIONS 白名单).

承接 docs/v0.1-launch-plan.md §D6.3 categorizer + merchants 500 + 状态机:

    - `TransactionStatus` StrEnum 5 状态(IMPORTED / CATEGORIZED / NEEDS_CONFIRM
      / CONFIRMED / ARCHIVED)
    - `ALLOWED_TRANSITIONS` 状态机白名单(沿 outbox 范本,嵌套 frozenset dict)
    - `TransactionIllegalTransitionError` 异常(沿 db/outbox.py:74-121 范本)
    - 终态 ARCHIVED,不可转出

设计参考(plan §4 8 范本):
    - OutboxStatus 6 状态: core/outbox.py:78-106
    - ALLOWED_TRANSITIONS: core/outbox.py:123-147
    - IllegalTransitionError: db/outbox.py:74-121

状态机契约:
    IMPORTED     → {CATEGORIZED, NEEDS_CONFIRM, ARCHIVED}
    CATEGORIZED  → {NEEDS_CONFIRM, CONFIRMED, ARCHIVED}
    NEEDS_CONFIRM→ {CONFIRMED, ARCHIVED}
    CONFIRMED    → {ARCHIVED}
    ARCHIVED     → {}  (终态)

D6.5 业务层用 `assert_transition(from_status, to_status)` 严判入参,
D6.4 TransactionStore.update_status 严判 from_status 漂移 + 白名单外转换。
"""

from __future__ import annotations

from enum import StrEnum


class TransactionStatus(StrEnum):
    """交易状态 5 状态 StrEnum(D6.3 落定).

    顺序固定(IMPORTED → CATEGORIZED → NEEDS_CONFIRM → CONFIRMED → ARCHIVED),
    业务层做"按状态分组"时可直接用 list(TransactionStatus) 排序。

    DDL 走 TEXT(SQLite 不支持 ENUM 类型),ORM 走 StrEnum 严判。
    D6.4 transactions 表 status TEXT NOT NULL DEFAULT 'IMPORTED'。

    状态机白名单 ALLOWED_TRANSITIONS(见下方模块级常量):
        IMPORTED      → {CATEGORIZED, NEEDS_CONFIRM, ARCHIVED}
        CATEGORIZED   → {NEEDS_CONFIRM, CONFIRMED, ARCHIVED}
        NEEDS_CONFIRM → {CONFIRMED, ARCHIVED}
        CONFIRMED     → {ARCHIVED}
        ARCHIVED      → {}  (终态)
    """

    IMPORTED = "imported"  # 默认:D6.5 Adapter 写入 transactions.status 初值
    CATEGORIZED = "categorized"  # D6.5 categorizer() 已分类
    NEEDS_CONFIRM = "needs_confirm"  # L2 命中 + 软标记,等用户 1-click 确认
    CONFIRMED = "confirmed"  # 用户已确认(同源同金额同商家,或 L3 1-click)
    ARCHIVED = "archived"  # 终态:已归档(对账完成 / 退款核销 / 永久留存)


# 5 状态枚举值集合(O(1) 校验)
_TRANSACTION_STATUS_CHOICES: frozenset[str] = frozenset(s.value for s in TransactionStatus)


# ===== D6.3 状态机白名单 ALLOWED_TRANSITIONS(模块级常量)=====
# 5 状态 × 各自合法目标集,显式枚举,无推导逻辑。
# 任何状态机严判都查这张表,不在表内的转换直接 TransactionIllegalTransitionError。
#
# 设计原则:
#   1. 显式优于隐式: 白名单硬编码,不靠运行时推导
#   2. 终态空集: ARCHIVED 不可转出(显式 frozenset() 表达)
#   3. 单向不可逆: CATEGORIZED → CONFIRMED 跳过 NEEDS_CONFIRM 直通(用户主动确认)
#   4. 跨 L2 触发 NEEDS_CONFIRM: L2 命中后状态从 CATEGORIZED 推到 NEEDS_CONFIRM
#      (等待用户 1-click 确认,沿 D6.2 L3 软标记)
ALLOWED_TRANSITIONS: dict[TransactionStatus, frozenset[TransactionStatus]] = {
    TransactionStatus.IMPORTED: frozenset(
        {
            TransactionStatus.CATEGORIZED,
            TransactionStatus.NEEDS_CONFIRM,
            TransactionStatus.ARCHIVED,
        }
    ),
    TransactionStatus.CATEGORIZED: frozenset(
        {
            TransactionStatus.NEEDS_CONFIRM,
            TransactionStatus.CONFIRMED,
            TransactionStatus.ARCHIVED,
        }
    ),
    TransactionStatus.NEEDS_CONFIRM: frozenset(
        {TransactionStatus.CONFIRMED, TransactionStatus.ARCHIVED}
    ),
    TransactionStatus.CONFIRMED: frozenset({TransactionStatus.ARCHIVED}),
    TransactionStatus.ARCHIVED: frozenset(),  # 终态
}


# ===== 异常类型(沿 db/outbox.py:74-121 IllegalTransitionError 范本)=====


class TransactionIllegalTransitionError(Exception):
    """状态机非法转换异常(D6.3 — 防 imported → confirmed 跳级 / archived → anything)。

    触发场景(任一):
      1. update_status 调用方 from_status 与 row.status 不一致(并发写状态漂移检测)
      2. update_status 调用方 from_status → new_status 不在 ALLOWED_TRANSITIONS 白名单
         (例 archived → confirmed, imported → confirmed 跳级)

    调用方(D6.5 TransactionAdapter)按业务语义区分:
      - 状态漂移检测: 走 record_transaction_failure_and_emit(concurrent write,需 retry|escalate)
      - 白名单外转换: 走 record_transaction_business_blocked_and_emit(bug,需人工 review)

    Attributes:
        tx_id: transactions.id
        from_status: 调用方传入的 from_status
        to_status: 目标 status
        actual_status: 实际 row.status(可能与 from_status 不一致)
        allowed: from_status 的合法目标集(从 ALLOWED_TRANSITIONS 查)
    """

    def __init__(
        self,
        tx_id: int,
        from_status: str,
        to_status: str,
        *,
        actual_status: str | None = None,
        allowed: frozenset[TransactionStatus] | None = None,
    ) -> None:
        self.tx_id = tx_id
        self.from_status = from_status
        self.to_status = to_status
        self.actual_status = actual_status
        self.allowed = allowed
        if actual_status is not None and actual_status != from_status:
            # 场景 1:状态漂移检测
            super().__init__(
                f"tx_id={tx_id} 状态机漂移: 调用方 from_status={from_status!r},"
                f"实际 row.status={actual_status!r} "
                f"(可能并发写导致,调用方应重读 row.status 再调 update_status)"
            )
        else:
            # 场景 2:白名单外转换
            allowed_str = sorted(s.value for s in allowed) if allowed is not None else "UNKNOWN"
            super().__init__(
                f"tx_id={tx_id} 状态机非法转换: {from_status!r} → {to_status!r} "
                f"(allowed from {from_status!r}: {allowed_str},见 ALLOWED_TRANSITIONS)"
            )


# ===== 公共 API 严判函数(供 D6.4 Store.update_status / D6.5 Adapter 调用)=====


def assert_transition(from_status: str, to_status: str) -> None:
    """状态机白名单严判(D6.3 公共 API).

    Args:
        from_status: 起始状态(必为 TransactionStatus 5 选 1 的 value)
        to_status: 目标状态(必为 TransactionStatus 5 选 1 的 value)

    Raises:
        ValueError: from_status / to_status 非合法枚举值
        TransactionIllegalTransitionError: 不在白名单
    """
    if not isinstance(from_status, str) or from_status not in _TRANSACTION_STATUS_CHOICES:
        raise ValueError(f"from_status 必为 TransactionStatus 5 选 1,实际 {from_status!r}")
    if not isinstance(to_status, str) or to_status not in _TRANSACTION_STATUS_CHOICES:
        raise ValueError(f"to_status 必为 TransactionStatus 5 选 1,实际 {to_status!r}")
    from_enum = TransactionStatus(from_status)
    to_enum = TransactionStatus(to_status)
    allowed_set = ALLOWED_TRANSITIONS[from_enum]
    if to_enum not in allowed_set:
        raise TransactionIllegalTransitionError(
            tx_id=0,  # 公共 API 层无 tx_id,调用方 Store/Adapter 应传真实 tx_id
            from_status=from_status,
            to_status=to_status,
            allowed=allowed_set,
        )


__all__ = [
    "TransactionStatus",
    "ALLOWED_TRANSITIONS",
    "TransactionIllegalTransitionError",
    "assert_transition",
]
