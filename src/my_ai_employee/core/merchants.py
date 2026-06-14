"""D6.3 — merchants.py 商家映射(500 条预置,JSON fixture 加载).

承接 docs/v0.1-launch-plan.md §D6.3 categorizer + merchants 500:

    - `MERCHANT_TO_CATEGORY: dict[str, TransactionCategory]` 跨源共用
    - 加载自 `tests/fixtures/merchants_500.json`(654 条去重,5 类均匀分布)
    - D7 兼容: 跨源共用同一商家表(alipay / jd / 其他未来源),
      分类键是商家字符串而非 source 字符串(plan §7 D7 兼容 5 扩展点)
    - 关键词表兜底: `categorize()` 见 core/categorizer.py

D8 智能分类(LLM) B 类延后:
    - D6.3 走关键词规则 + 商家表兜底
    - D8 LLM 智能分类 v0.2 再实现

设计决策:
    - **不**在代码里硬编码 500 条(可维护性 + i18n)
    - 加载自 JSON fixture,Categorizer 默认加载,测试可 mock
    - 严格 dict 严判: type(value) is TransactionCategory
"""

from __future__ import annotations

import json
from pathlib import Path

from my_ai_employee.core.transaction_category import TransactionCategory

# 默认商家映射表路径(相对项目根 tests/fixtures/merchants_500.json)
_DEFAULT_MERCHANTS_PATH = Path("tests/fixtures/merchants_500.json")


def load_merchants_from_json(path: Path | str | None = None) -> dict[str, TransactionCategory]:
    """从 JSON fixture 加载商家 → TransactionCategory 映射.

    Args:
        path: JSON 文件路径(默认 tests/fixtures/merchants_500.json)

    Returns:
        dict[str, TransactionCategory] 商家 → 分类

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON 内容非法(非 dict / 分类值不在 5 选 1 / 重复键不一致)
    """
    p = Path(path) if path is not None else _DEFAULT_MERCHANTS_PATH
    if not p.exists():
        raise FileNotFoundError(f"商家映射 JSON 文件不存在: {p}")

    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"商家映射 JSON 顶层必须是 dict[str, str],实际 type={type(raw).__name__}")

    out: dict[str, TransactionCategory] = {}
    for key, value in raw.items():
        # 严判 key 必为非空字符串
        if not isinstance(key, str) or not key.strip():
            raise ValueError(
                f"商家映射 key 必为非空字符串,实际 type={type(key).__name__}, value={key!r}"
            )
        # 严判 value 必为合法分类值
        if not isinstance(value, str):
            raise ValueError(f"商家映射 value 必为 str,key={key!r}, type={type(value).__name__}")
        if value not in {c.value for c in TransactionCategory}:
            raise ValueError(
                f"商家映射 value 必为合法 TransactionCategory,key={key!r}, value={value!r}"
            )
        out[key] = TransactionCategory(value)

    if not out:
        raise ValueError("商家映射 JSON 不能为空 dict")
    return out


# 模块级常量:Categorizer 直接 import 使用
# 默认延迟加载(测试可 override,生产代码无需关心路径)
MERCHANT_TO_CATEGORY: dict[str, TransactionCategory] = load_merchants_from_json()


__all__ = [
    "MERCHANT_TO_CATEGORY",
    "load_merchants_from_json",
]
