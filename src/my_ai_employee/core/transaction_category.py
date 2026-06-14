"""D6.3 — TransactionCategory StrEnum 5 类(纯枚举,无业务).

承接 docs/v0.1-launch-plan.md §D6.3 categorizer + merchants 500 + 状态机:

    - 5 类 StrEnum: DINING / TRANSPORT / SHOPPING / HOME / OTHER
    - D6.3 落定 5 类,D6.5 TransactionAdapter 写 transactions.category
    - D7 兼容: dict[str, Category] 而非 dict[Source, Category](plan §7)
    - 顺序固定,业务层做"按分类分组"时可直接用 list(TransactionCategory) 排序

设计参考(plan §4 8 范本):
    - OutboxTone 独立枚举不复用 DraftTone: core/outbox.py:150-160
    - StrEnum 范本: 业务层做"按状态分组"用 list(Enum) 排序

D8 智能分类(LLM) B 类延后:
    - D6.3 走关键词规则 + 商家表兜底(plan §3 D6.3)
    - D8 LLM 智能分类 v0.2 再实现
"""

from __future__ import annotations

from enum import StrEnum


class TransactionCategory(StrEnum):
    """交易分类 5 类 StrEnum(D6.3 落定).

    顺序固定(DINING → TRANSPORT → SHOPPING → HOME → OTHER),
    业务层做"按分类分组"时可直接用 list(TransactionCategory) 排序。

    DDL 走 TEXT(SQLite 不支持 ENUM 类型),ORM 走 StrEnum 严判。
    D6.4 transactions 表 category TEXT 列存 5 选 1。

    D7 兼容: 跨源共用同一分类枚举(alipay / jd / 其他未来源),
    分类键是商家字符串而非 source 字符串(plan §7 D7 兼容 5 扩展点)。
    """

    DINING = "dining"  # 餐饮(星巴克/麦当劳/肯德基 等)
    TRANSPORT = "transport"  # 交通(滴滴/出租车/高铁/加油 等)
    SHOPPING = "shopping"  # 购物(淘宝/京东/超市 等)
    HOME = "home"  # 居家(房租/水电/物业/外卖到家 等)
    OTHER = "other"  # 其他(关键词表 + 商家表都没命中,兜底)


# 5 类枚举值集合(O(1) 校验)
_TRANSACTION_CATEGORY_CHOICES: frozenset[str] = frozenset(c.value for c in TransactionCategory)


__all__ = [
    "TransactionCategory",
]
