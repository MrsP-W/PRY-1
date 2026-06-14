"""D6.2 normalized_fingerprint 指纹算法测试(10 cases).

承接 docs/v0.1-launch-plan.md §D6 3 层去重模型 + §D6.2 详细 plan:

    1. test_fingerprint_基本结构_32_chars_hex
    2. test_fingerprint_同日同金额同商家_命中
    3. test_fingerprint_跨日不命中
    4. test_fingerprint_同金额不同商家不命中
    5. test_fingerprint_金额绝对值归一化
    6. test_fingerprint_商家模糊符_去星号
    7. test_fingerprint_商家大小写不敏感
    8. test_fingerprint_商家空白归一化
    9. test_fingerprint_date对象与字符串等价
    10. test_fingerprint_入参严判异常

跑法:
    pytest tests/core/test_fingerprint.py -v
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def test_fingerprint_basic_structure_32_chars_hex() -> None:
    """Case 1 — 指纹基本结构:32 chars hex(16 字节).

    验证:
        - 长度 == 32
        - 全部是小写 hex 字符
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克")
    assert isinstance(fp, str)
    assert len(fp) == 32, f"fingerprint 长度必须 32,实际 {len(fp)}"
    assert all(c in "0123456789abcdef" for c in fp), f"fingerprint 必须是 lowercase hex,实际 {fp!r}"


def test_fingerprint_same_day_amount_merchant_hits() -> None:
    """Case 2 — 同日同金额同商家指纹相同(v0.1-launch-plan.md:260-263 关键用例)."""
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克")
    fp2 = normalize_fingerprint("2026-06-14 12:30:00", Decimal("13.140"), "星巴克")
    assert fp1 == fp2, f"同日同金额同商家必须同指纹,实际 {fp1!r} vs {fp2!r}"


def test_fingerprint_cross_day_misses() -> None:
    """Case 3 — 跨日(2026-06-14 vs 2026-06-15)即使同金额同商家也不命中.

    防 v0.1-launch-plan.md 防误合并 #2:日期相邻 ±1 天的相同交易误命中。
    指纹算法严格只取日期不取时间,跨日不命中。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克")
    fp2 = normalize_fingerprint("2026-06-15", Decimal("13.14"), "星巴克")
    assert fp1 != fp2, f"跨日不应命中,实际 {fp1!r} vs {fp2!r}"


def test_fingerprint_same_amount_different_merchant_misses() -> None:
    """Case 4 — 同金额不同商家不命中(防误合并 #1:13.14 红包 vs 13.14 午餐)."""
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克")
    fp2 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "麦当劳")
    assert fp1 != fp2, f"同金额不同商家不应命中,实际 {fp1!r} vs {fp2!r}"


def test_fingerprint_amount_absolute_value_normalized() -> None:
    """Case 5 — 金额绝对值归一化(+13.14 vs -13.14 同指纹).

    v0.1-launch-plan.md:262 锁定的 abs(round(amount, 2))。
    退款(-13.14)与原交易(+13.14)同指纹 → L2 命中 → L3 needs_confirm 触发用户确认。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克")
    fp2 = normalize_fingerprint("2026-06-14", Decimal("-13.14"), "星巴克")
    assert fp1 == fp2, f"金额绝对值归一化失败,实际 {fp1!r} vs {fp2!r}"


def test_fingerprint_merchant_fuzzy_marker_strip() -> None:
    """Case 6 — 商家模糊符"星巴克" vs "星巴克*" 命中(v0.1-launch-plan.md 防误合并 #3)."""
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克")
    fp2 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克*")
    fp3 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克***")
    assert fp1 == fp2, f"单星号模糊符应归一化,实际 {fp1!r} vs {fp2!r}"
    assert fp1 == fp3, f"多星号模糊符应归一化,实际 {fp1!r} vs {fp3!r}"


def test_fingerprint_merchant_case_insensitive() -> None:
    """Case 7 — 商家大小写不敏感(Starbucks vs starbucks vs STARBUCKS 命中)."""
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "Starbucks")
    fp2 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "starbucks")
    fp3 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "STARBUCKS")
    assert fp1 == fp2 == fp3, f"大小写不敏感归一化失败,实际 {fp1!r} / {fp2!r} / {fp3!r}"


def test_fingerprint_merchant_whitespace_normalized() -> None:
    """Case 8 — 商家空白归一化("星巴克 咖啡" vs "星巴克咖啡" vs "  星巴克咖啡  " 命中)."""
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克咖啡")
    fp2 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克 咖啡")
    fp3 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "  星巴克咖啡  ")
    assert fp1 == fp2, f"中间空白应归一化,实际 {fp1!r} vs {fp2!r}"
    assert fp1 == fp3, f"前后空白应归一化,实际 {fp1!r} vs {fp3!r}"


def test_fingerprint_date_object_equiv_str() -> None:
    """Case 9 — date 对象与 ISO 字符串等价(沿 v0.1-launch-plan.md:260 范本)."""
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint("2026-06-14", Decimal("13.14"), "星巴克")
    fp2 = normalize_fingerprint(date(2026, 6, 14), Decimal("13.14"), "星巴克")
    fp3 = normalize_fingerprint(datetime(2026, 6, 14, 12, 30), Decimal("13.14"), "星巴克")
    assert fp1 == fp2, f"date 对象与字符串不等价,实际 {fp1!r} vs {fp2!r}"
    assert fp1 == fp3, f"datetime 对象(取日期)与字符串不等价,实际 {fp1!r} vs {fp3!r}"


def test_fingerprint_input_validation_raises() -> None:
    """Case 10 — 入参严判:type / 空字符串 / 非法格式 抛 ValueError 或 TypeError."""
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    # 1. date 类型非法
    with __import__("pytest").raises(TypeError, match="date 必须是"):
        normalize_fingerprint(20260614, Decimal("13.14"), "星巴克")  # type: ignore[arg-type]

    # 2. date 空字符串
    with __import__("pytest").raises(ValueError, match="日期必填"):
        normalize_fingerprint("", Decimal("13.14"), "星巴克")

    # 3. date 格式非法
    with __import__("pytest").raises(ValueError, match="日期无法解析"):
        normalize_fingerprint("not-a-date", Decimal("13.14"), "星巴克")

    # 4. amount 类型非法(bool 是 int 子类陷阱)
    with __import__("pytest").raises(TypeError, match="bool"):
        normalize_fingerprint("2026-06-14", True, "星巴克")  # type: ignore[arg-type]

    # 5. amount 空字符串
    with __import__("pytest").raises(ValueError, match="amount 必填"):
        normalize_fingerprint("2026-06-14", "", "星巴克")

    # 6. counterparty 类型非法
    with __import__("pytest").raises(TypeError, match="counterparty 必须是 str"):
        normalize_fingerprint("2026-06-14", Decimal("13.14"), 123)  # type: ignore[arg-type]

    # 7. counterparty 空字符串
    with __import__("pytest").raises(ValueError, match="counterparty 必填"):
        normalize_fingerprint("2026-06-14", Decimal("13.14"), "")

    # 8. counterparty 全模糊符(归一化后为空)
    with __import__("pytest").raises(ValueError, match="归一化后为空"):
        normalize_fingerprint("2026-06-14", Decimal("13.14"), "****")
