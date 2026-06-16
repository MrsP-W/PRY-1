"""D5.5 — SLAEvaluator + SLAEvaluation dataclass 16 cases 测试.

SLA 阈值(per D5 启动计划):
    URGENT:  threshold=5min(300_000ms),  warning=3min(180_000ms)
    NORMAL:  threshold=4h(14_400_000ms), warning=2h(7_200_000ms)
    LOW:     threshold=24h(86_400_000ms),warning=12h(43_200_000ms)

8 段测试覆盖(16 cases):
    A. SLAEvaluation dataclass 构造 + __post_init__ 跨字段强一致(4 tests)
    B. SLAEvaluator.evaluate() 3 状态 — URGENT / NORMAL / LOW(3 tests)
    C. 边界值 — 临界 warning / 临界 threshold(3 tests)
    D. 异常 — priority 非法 / age_ms 非法 / bool 子类陷阱(3 tests)
    E. 跨字段一致性 — 数据类 vs evaluate() 双重校验(3 tests)

合计 16 cases。
"""

from __future__ import annotations

import pytest

from my_ai_employee.scheduler.sla import (
    SLAEvaluation,
    SLAEvaluator,
    SLAStatus,
)

# ===== A. SLAEvaluation dataclass 构造 + __post_init__ 跨字段强一致(4 tests)=====


def test_sla_evaluation_ok_creation() -> None:
    """SLAEvaluation OK 状态 — priority=urgent + age_ms=100_000(在 warning 阈值内)。"""
    e = SLAEvaluation(priority="urgent", age_ms=100_000, status=SLAStatus.OK)
    assert e.priority == "urgent"
    assert e.age_ms == 100_000
    assert e.status == SLAStatus.OK


def test_sla_evaluation_warning_creation() -> None:
    """SLAEvaluation WARNING 状态 — priority=urgent + age_ms=200_000(超 warning,未超 threshold)。"""
    e = SLAEvaluation(priority="normal", age_ms=7_500_000, status=SLAStatus.WARNING)
    assert e.status == SLAStatus.WARNING


def test_sla_evaluation_breach_creation() -> None:
    """SLAEvaluation BREACH 状态 — priority=urgent + age_ms=400_000(超 threshold)。"""
    e = SLAEvaluation(priority="low", age_ms=86_500_000, status=SLAStatus.BREACH)
    assert e.status == SLAStatus.BREACH


def test_sla_evaluation_cross_field_breach_violates_raises() -> None:
    """SLAEvaluation 跨字段违反:status=BREACH 但 age_ms < threshold → ValueError。"""
    with pytest.raises(ValueError, match="跨字段违反"):
        # urgent BREACH 必 age_ms >= 300_000,但给 100_000
        SLAEvaluation(priority="urgent", age_ms=100_000, status=SLAStatus.BREACH)


# ===== B. SLAEvaluator.evaluate() 3 状态 — URGENT / NORMAL / LOW(3 tests)=====


def test_evaluator_urgent_ok_status() -> None:
    """SLAEvaluator.evaluate(urgent, 100_000) → OK(未超 warning 180_000)。"""
    e = SLAEvaluator.evaluate(priority="urgent", age_ms=100_000)
    assert e.status == SLAStatus.OK
    assert e.priority == "urgent"
    assert e.age_ms == 100_000


def test_evaluator_normal_warning_status() -> None:
    """SLAEvaluator.evaluate(normal, 7_300_000) → WARNING(超 warning 7_200_000,未超 threshold 14_400_000)。"""
    e = SLAEvaluator.evaluate(priority="normal", age_ms=7_300_000)
    assert e.status == SLAStatus.WARNING


def test_evaluator_low_breach_status() -> None:
    """SLAEvaluator.evaluate(low, 90_000_000) → BREACH(超 threshold 86_400_000)。"""
    e = SLAEvaluator.evaluate(priority="low", age_ms=90_000_000)
    assert e.status == SLAStatus.BREACH


# ===== C. 边界值 — 临界 warning / 临界 threshold(3 tests)=====


def test_evaluator_urgent_at_warning_boundary() -> None:
    """SLAEvaluator.evaluate(urgent, 180_000) — age_ms == warning → WARNING(>= 取闭区间)。"""
    e = SLAEvaluator.evaluate(priority="urgent", age_ms=180_000)
    assert e.status == SLAStatus.WARNING


def test_evaluator_urgent_at_threshold_boundary() -> None:
    """SLAEvaluator.evaluate(urgent, 300_000) — age_ms == threshold → BREACH(>= 取闭区间)。"""
    e = SLAEvaluator.evaluate(priority="urgent", age_ms=300_000)
    assert e.status == SLAStatus.BREACH


def test_evaluator_normal_below_warning() -> None:
    """SLAEvaluator.evaluate(normal, 7_199_999) — age_ms < warning → OK。"""
    e = SLAEvaluator.evaluate(priority="normal", age_ms=7_199_999)
    assert e.status == SLAStatus.OK


# ===== D. 异常 — priority 非法 / age_ms 非法 / bool 子类陷阱(3 tests)=====


def test_evaluator_invalid_priority_raises() -> None:
    """SLAEvaluator.evaluate 完全非法 priority → ValueError(白名单外)。

    v0.2 B1.1 扩 6 类后,"high" 已是合法 priority(HIGH=4),改为测真正非法的 "superduper"。
    """
    with pytest.raises(ValueError, match="priority 必须是"):
        SLAEvaluator.evaluate(priority="superduper", age_ms=1000)


def test_evaluator_negative_age_raises() -> None:
    """SLAEvaluator.evaluate age_ms=-1 → ValueError(必 >= 0)。"""
    with pytest.raises(ValueError, match="age_ms 必须是原生 int"):
        SLAEvaluator.evaluate(priority="urgent", age_ms=-1)


def test_evaluator_bool_age_rejected() -> None:
    """SLAEvaluator.evaluate age_ms=True → ValueError(bool 子类是 int,严判必须拒收)。"""
    with pytest.raises(ValueError, match="age_ms 必须是原生 int"):
        SLAEvaluator.evaluate(priority="urgent", age_ms=True)  # type: ignore[arg-type]


# ===== E. 跨字段一致性 — 数据类 vs evaluate() 双重校验(3 tests)=====


def test_evaluation_constructor_accepts_computed_status() -> None:
    """SLAEvaluation 构造 + 严判:用 evaluate() 算出的 status 应能直接构造(算路 1:1)。"""
    age_ms = 200_000
    e = SLAEvaluator.evaluate(priority="urgent", age_ms=age_ms)
    # 重新构造同字段应通过(数据类契约与工厂 1:1)
    e2 = SLAEvaluation(priority=e.priority, age_ms=e.age_ms, status=e.status)
    assert e2 == e


def test_evaluation_constructor_rejects_lying_status() -> None:
    """SLAEvaluation 构造 + 严判:伪造 status 必拒收(防数据类单独构造绕过 evaluate)。"""
    # age_ms=100_000 应是 OK,但传 BREACH → 跨字段拒绝
    with pytest.raises(ValueError, match="跨字段违反"):
        SLAEvaluation(priority="urgent", age_ms=100_000, status=SLAStatus.BREACH)


def test_evaluation_priority_not_str_raises() -> None:
    """SLAEvaluation 构造 priority 非 str → ValueError(数据类 __post_init__ 严判)。"""
    with pytest.raises(ValueError, match="priority 必须是 str"):
        SLAEvaluation(priority=123, age_ms=1000, status=SLAStatus.OK)  # type: ignore[arg-type]
