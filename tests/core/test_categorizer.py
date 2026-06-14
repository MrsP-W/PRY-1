"""D6.3 categorizer.py 关键词规则分类测试(15 cases).

承接 docs/v0.1-launch-plan.md §D6.3 categorizer + merchants 500:

    5 类各 3 case + 异常路径:
    - DINING 3: 商家表命中 / 关键词命中(模糊大小写)
    - TRANSPORT 3: 商家表命中 / 关键词命中 / 子串匹配
    - SHOPPING 3: 商家表命中 / 关键词命中(英文)
    - HOME 3: 商家表命中 / 关键词命中(中文长串)
    - OTHER 3: 商家表兜底(未知商家) / 关键词命中(医院) / 完全未知
    - 异常 1: counterparty 类型非法
    - 异常 1: counterparty 空字符串
    - 异常 1: 关键词表 5 类正则(顺序严判) — 美食类优先
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== DINING 3 cases =====


def test_categorize_dining_merchant_table_exact_hit() -> None:
    """Case 1 — DINING 商家表精确匹配('星巴克' 在 MERCHANT_TO_CATEGORY 中)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("星巴克")
    assert result == TransactionCategory.DINING


def test_categorize_dining_keyword_substring() -> None:
    """Case 2 — DINING 关键词子串匹配('蜜雪冰城北京' 含 '蜜雪' 关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("蜜雪冰城北京五道口店")
    assert result == TransactionCategory.DINING


def test_categorize_dining_case_insensitive() -> None:
    """Case 3 — DINING 大小写不敏感('Starbucks' 含 'Starbucks' 关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("Starbucks Coffee")
    assert result == TransactionCategory.DINING


# ===== TRANSPORT 3 cases =====


def test_categorize_transport_merchant_table_exact_hit() -> None:
    """Case 4 — TRANSPORT 商家表精确匹配('滴滴' 在 MERCHANT_TO_CATEGORY 中)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("滴滴")
    assert result == TransactionCategory.TRANSPORT


def test_categorize_transport_keyword_substring() -> None:
    """Case 5 — TRANSPORT 关键词子串匹配('中石化北京加油站' 含 '中石化')."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("中石化北京加油站")
    assert result == TransactionCategory.TRANSPORT


def test_categorize_transport_english_substring() -> None:
    """Case 6 — TRANSPORT 英文关键词('Shell gas station' 含 'Shell')."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("Shell gas station")
    assert result == TransactionCategory.TRANSPORT


# ===== SHOPPING 3 cases =====


def test_categorize_shopping_merchant_table_exact_hit() -> None:
    """Case 7 — SHOPPING 商家表精确匹配('淘宝' 在 MERCHANT_TO_CATEGORY 中)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("淘宝")
    assert result == TransactionCategory.SHOPPING


def test_categorize_shopping_keyword_english() -> None:
    """Case 8 — SHOPPING 关键词英文('Apple Store' 含 'Apple Store' 关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("Apple Store Beijing")
    assert result == TransactionCategory.SHOPPING


def test_categorize_shopping_keyword_iphone() -> None:
    """Case 9 — SHOPPING 关键词子串匹配('iPhone 15 Pro Max 256G' 含 'iPhone' 关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("iPhone 15 Pro Max 256G")
    assert result == TransactionCategory.SHOPPING


# ===== HOME 3 cases =====


def test_categorize_home_merchant_table_exact_hit() -> None:
    """Case 10 — HOME 商家表精确匹配('链家' 在 MERCHANT_TO_CATEGORY 中)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("链家")
    assert result == TransactionCategory.HOME


def test_categorize_home_keyword_utility() -> None:
    """Case 11 — HOME 关键词子串匹配('国家电网北京公司' 含 '国家电网' 关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("国家电网北京公司")
    assert result == TransactionCategory.HOME


def test_categorize_home_keyword_takeout() -> None:
    """Case 12 — HOME 关键词子串匹配('美团外卖午餐' 含 '美团外卖' 关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("美团外卖午餐")
    assert result == TransactionCategory.HOME


# ===== OTHER 3 cases =====


def test_categorize_other_unknown_merchant_fallback() -> None:
    """Case 13 — OTHER 兜底(完全未知的商家,不在商家表也不在关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("某不知名的小作坊小店XYZ12345")
    assert result == TransactionCategory.OTHER


def test_categorize_other_keyword_hospital() -> None:
    """Case 14 — OTHER 关键词命中('北京协和医院' 含 '协和' 关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("北京协和医院")
    assert result == TransactionCategory.OTHER


def test_categorize_other_keyword_red_envelope() -> None:
    """Case 15 — OTHER 关键词命中('微信红包' 含 '红包' 关键词)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("微信红包")
    assert result == TransactionCategory.OTHER


# ===== 顺序严判(防止"通用词" 误命中)=====


def test_categorize_priority_order_merchant_first() -> None:
    """Case 16 — 商家表优先于关键词表('盒马' 在商家表里归 HOME,关键词也含 '盒马').

    商家表精确匹配先返回(不进入关键词表 search)。
    """
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result = categorize("盒马鲜生")
    assert result == TransactionCategory.HOME  # 商家表归 HOME,不是 SHOPPING


def test_categorize_amount_param_ignored() -> None:
    """Case 17 — amount 参数不参与分类(仅预留,严判不抛错)."""
    from my_ai_employee.core.categorizer import categorize
    from my_ai_employee.core.transaction_category import TransactionCategory

    result1 = categorize("星巴克", Decimal("38.00"))
    result2 = categorize("星巴克", 0)
    result3 = categorize("星巴克", None)
    assert result1 == result2 == result3 == TransactionCategory.DINING


# ===== 异常路径 =====


def test_categorize_input_validation_raises() -> None:
    """Case 18 — 入参严判: type / 空字符串 抛 ValueError 或 TypeError."""
    from my_ai_employee.core.categorizer import categorize

    # 1. counterparty 类型非法
    with pytest.raises(TypeError, match="counterparty 必须是 str"):
        categorize(123)  # type: ignore[arg-type]

    # 2. counterparty 空字符串
    with pytest.raises(ValueError, match="counterparty 必填"):
        categorize("")

    # 3. counterparty 全空白
    with pytest.raises(ValueError, match="counterparty 必填"):
        categorize("   ")
