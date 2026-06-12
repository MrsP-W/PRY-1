"""D5.5 — 指数退避公式:根据连续失败次数计算下次重试等待时间.

承接:
  - D4.7.3 v1.0.5 P1-2 范本:跨字段双向强一致
  - D4.7.3 v1.0.4 P1-2 范本:边界值上下对称严判
  - D4.7.3 v1.0.5 P2-2 范本:bool 子类是 int 陷阱,type() is int 严判
  - D4.7.3 v1.0.3 P2-2 范本:依赖注入 is None 不用 or

公式(D5 启动计划锁定):
    retry_after_ms = min(2^(consecutive_send_failures - 1) * 60_000, 3_600_000)
    (cf=0 时 0,cf>=1 时 2^(cf-1) * 60_000 封顶 1h)

    consecutive_send_failures=0  → 0           (未失败,不延迟)
    consecutive_send_failures=1  → 60_000      (2^0 * 60s, 1 分钟)
    consecutive_send_failures=2  → 120_000     (2^1 * 60s, 2 分钟)
    consecutive_send_failures=3  → 240_000     (2^2 * 60s, 4 分钟)
    consecutive_send_failures=4  → 480_000     (2^3 * 60s, 8 分钟)
    consecutive_send_failures=5  → 960_000     (2^4 * 60s, 16 分钟)
    consecutive_send_failures=6  → 1_920_000   (2^5 * 60s, 32 分钟)
    consecutive_send_failures=7  → 3_600_000   (2^6 * 60s = 3_840_000 → 封顶 1h)
    consecutive_send_failures>=7 → 3_600_000   (封顶 1h)

设计:
  - 纯函数式(无内部状态,线程安全)
  - consecutive_send_failures 严判原生 int(非 bool)且 >= 0
  - 边界值上下对称(0 起步,封顶 1h)
  - 模块级常量 Final 化(避免运行时修改)

应用:
  - D5.5 OutboxDispatcher._process_one_entry 失败时调
      retry_after_ms = compute_retry_after_ms(consecutive_send_failures)
    传给 record_send_failure_and_emit(...)
  - Dispatcher 内存状态追踪 per-outbox_id 的 cf + last_failed_at(避免重复重试)
"""

from __future__ import annotations

# ===== 退避常量(模块级 Final)=====

_BASE_DELAY_MS: int = 60_000  # 1 分钟(2^0 * 60s)
_MAX_DELAY_MS: int = 60 * 60 * 1000  # 3_600_000(1 小时封顶)


# ===== 纯函数 — 模块级直接调 =====


def compute_retry_after_ms(consecutive_send_failures: int) -> int:
    """D5.5 指数退避公式 — 2^cf * 60s 封顶 1h.

    Args:
        consecutive_send_failures: 连续失败次数(原生 int 非 bool, >= 0)

    Returns:
        int: retry_after_ms(>= 0, <= 3_600_000)

    Raises:
        ValueError: consecutive_send_failures 非法

    Examples:
        >>> compute_retry_after_ms(0)
        0
        >>> compute_retry_after_ms(1)
        60000
        >>> compute_retry_after_ms(7)
        3600000
        >>> compute_retry_after_ms(100)
        3600000
    """
    # 1. consecutive_send_failures 严判(bool 子类陷阱 + int 边界)
    if (
        type(consecutive_send_failures) is bool
        or not isinstance(consecutive_send_failures, int)
        or consecutive_send_failures < 0
    ):
        raise ValueError(
            f"consecutive_send_failures 必须是原生 int(非 bool) >= 0, 实际 "
            f"{type(consecutive_send_failures).__name__}={consecutive_send_failures!r}"
        )
    # 2. 公式:min(2^(cf-1) * 60_000, 3_600_000)
    # cf=0 特判 0(未失败,不延迟)
    # cf>=1:指数退避,封顶 1h
    if consecutive_send_failures == 0:
        return 0
    # 2^(cf-1) 可能很大,但 Python int 无溢出,min() 截到 MAX_DELAY_MS
    delay = _BASE_DELAY_MS * (2 ** (consecutive_send_failures - 1))
    return int(min(delay, _MAX_DELAY_MS))


# ===== 模块导出 =====


__all__ = ["compute_retry_after_ms"]
