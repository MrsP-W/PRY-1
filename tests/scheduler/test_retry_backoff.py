"""D5.5 — compute_retry_after_ms 退避公式 12 cases 测试.

公式:min(2^cf * 60_000, 3_600_000)
    cf=0 → 0(不延迟,调用方应短路)
    cf=1 → 60_000
    cf=2 → 120_000
    cf=3 → 240_000
    cf=4 → 480_000
    cf=5 → 960_000
    cf=6 → 1_920_000
    cf=7 → 3_600_000(封顶 1h)
    cf=100 → 3_600_000(封顶 1h)

5 段测试覆盖(12 cases):
    A. 基础公式 — cf=0..6 数值正确(3 tests)
    B. 封顶 — cf>=7 都返回 3_600_000(2 tests)
    C. 边界值 — cf=7 vs cf=8 同值(1 test)
    D. 异常 — bool 子类陷阱 / 负数 / 非 int(3 tests)
    E. 模块导出 — compute_retry_after_ms 可导入(1 test)
    F. 实战验算 — 2^cf * 60s 公式表全表校对(2 tests)

合计 12 cases。
"""

from __future__ import annotations

import pytest

from my_ai_employee.scheduler.backoff import compute_retry_after_ms

# ===== A. 基础公式 — cf=0..6 数值正确(3 tests)=====


def test_retry_cf_zero() -> None:
    """cf=0 → 0(不延迟,调用方应短路)。"""
    assert compute_retry_after_ms(0) == 0


def test_retry_cf_one() -> None:
    """cf=1 → 60_000(1 分钟)。"""
    assert compute_retry_after_ms(1) == 60_000


def test_retry_cf_six() -> None:
    """cf=6 → 1_920_000(32 分钟,未达 1h 封顶)。"""
    assert compute_retry_after_ms(6) == 1_920_000


# ===== B. 封顶 — cf>=7 都返回 3_600_000(2 tests)=====


def test_retry_cf_seven_caps_at_one_hour() -> None:
    """cf=7 → 3_600_000(2^7 * 60s = 7_680_000 > 1h,被 min() 截到 3_600_000)。"""
    assert compute_retry_after_ms(7) == 3_600_000


def test_retry_cf_huge_caps_at_one_hour() -> None:
    """cf=100 → 3_600_000(2^100 * 60s 巨大,封顶 1h)。"""
    assert compute_retry_after_ms(100) == 3_600_000


# ===== C. 边界值 — cf=7 vs cf=8 同值(1 test)=====


def test_retry_cf_seven_and_eight_same() -> None:
    """cf=7 vs cf=8 同为封顶值(封顶后无差异)。"""
    assert compute_retry_after_ms(7) == compute_retry_after_ms(8) == 3_600_000


# ===== D. 异常 — bool 子类陷阱 / 负数 / 非 int(3 tests)=====


def test_retry_cf_bool_rejected() -> None:
    """cf=True → ValueError(bool 子类是 int,严判必须拒收,D4.7.3 v1.0.5 P2-2 范本)。"""
    with pytest.raises(ValueError, match="consecutive_send_failures 必须是原生 int"):
        compute_retry_after_ms(True)


def test_retry_cf_negative_rejected() -> None:
    """cf=-1 → ValueError(必 >= 0)。"""
    with pytest.raises(ValueError, match="consecutive_send_failures 必须是原生 int"):
        compute_retry_after_ms(-1)


def test_retry_cf_non_int_rejected() -> None:
    """cf=1.5 → ValueError(必须 int,拒 float)。"""
    with pytest.raises(ValueError, match="consecutive_send_failures 必须是原生 int"):
        compute_retry_after_ms(1.5)


# ===== E. 模块导出 — compute_retry_after_ms 可导入(1 test)=====


def test_retry_function_importable() -> None:
    """compute_retry_after_ms 可从 scheduler.backoff 顶层导入(沿 D4.7.3 顶层导出范本)。"""
    from my_ai_employee.scheduler.backoff import compute_retry_after_ms as func

    assert func is compute_retry_after_ms
    assert callable(func)


# ===== F. 实战验算 — 2^cf * 60s 公式表全表校对(2 tests)=====


def test_retry_formula_table_full() -> None:
    """退避公式全表校对(2^cf * 60_000 封顶 3_600_000)— cf=0..10 全表。"""
    expected = {
        0: 0,
        1: 60_000,
        2: 120_000,
        3: 240_000,
        4: 480_000,
        5: 960_000,
        6: 1_920_000,
        7: 3_600_000,  # 封顶
        8: 3_600_000,  # 封顶
        9: 3_600_000,  # 封顶
        10: 3_600_000,  # 封顶
    }
    for cf, exp in expected.items():
        actual = compute_retry_after_ms(cf)
        assert actual == exp, f"cf={cf} expected {exp}, got {actual}"


def test_retry_growth_doubles_until_cap() -> None:
    """退避增长曲线 — 封顶前每次翻倍(60_000 → 120_000 → 240_000 → 480_000 → 960_000 → 1_920_000)。"""
    # cf=1..5 全部未达封顶,cf=6 翻倍到 cf=7 时被 min() 截到 3_600_000
    for cf in range(1, 6):
        # 封顶前:compute(cf+1) == 2 * compute(cf)
        assert compute_retry_after_ms(cf + 1) == 2 * compute_retry_after_ms(cf), f"cf={cf} 翻倍失败"
