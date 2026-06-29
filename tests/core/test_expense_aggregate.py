"""S6.3 — expense_aggregate 单元测试(8 cases).

承接 S6.3 commit 2:
    - src/my_ai_employee/core/expense_aggregate.py(current_month_expense)
    - 8 cases:空表 / 单笔 / 多笔跨月 / 跨日 / Decimal 累加精度 / today=None 默认值
    - 验证 D9 启动预留:纯函数 + session_factory 注入
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

# ===== 8 cases =====


def test_empty_table_returns_zero(session_factory: sessionmaker[Session]) -> None:
    """1. 空表 → Decimal('0')(func.coalesce 防 NULL 累加)."""
    from my_ai_employee.core.expense_aggregate import current_month_expense

    total = current_month_expense(session_factory, today=date(2026, 6, 15))
    assert total == Decimal("0")


def test_single_transaction_returns_amount(session_factory: sessionmaker[Session]) -> None:
    """2. 单笔 → 等于该笔 amount(Decimal 累加精度,非 float)."""
    from my_ai_employee.connectors._types import RawTransaction
    from my_ai_employee.core.expense_aggregate import current_month_expense
    from my_ai_employee.core.transaction_adapter import TransactionAdapter

    raw = RawTransaction(
        date=date(2026, 6, 10),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡",
        type="支出",
        payment_method="微信支付",
        external_transaction_id="s63-single-001",
        raw_row_hash="0" * 32,
    )
    adapter = TransactionAdapter(session_factory)
    adapter.import_raw_transactions([raw], source="wechat")

    total = current_month_expense(session_factory, today=date(2026, 6, 30))
    assert total == Decimal("38.50")


def test_multiple_transactions_same_month_sum(session_factory: sessionmaker[Session]) -> None:
    """3. 多笔同月 → 累加 sum(Decimal 严格相等,防 float 漂移)."""
    from my_ai_employee.connectors._types import RawTransaction
    from my_ai_employee.core.expense_aggregate import current_month_expense
    from my_ai_employee.core.transaction_adapter import TransactionAdapter

    rows = [
        RawTransaction(
            date=date(2026, 6, x),
            amount=Decimal("13.14"),
            counterparty=f"商家-{x}",
            type="支出",
            payment_method="微信支付",
            external_transaction_id=f"s63-same-{x:03d}",
            raw_row_hash="0" * 32,
        )
        for x in (5, 10, 15, 20, 25)
    ]
    adapter = TransactionAdapter(session_factory)
    adapter.import_raw_transactions(rows, source="wechat")

    total = current_month_expense(session_factory, today=date(2026, 6, 30))
    # 5 笔 × 13.14 = 65.70(Decimal 严判 2 位小数,5×13.14 = 65.70)
    assert total == Decimal("65.70")


def test_cross_month_filters_by_date_range(session_factory: sessionmaker[Session]) -> None:
    """4. 跨月数据 → 仅累加当月范围 [first_day, today] 的笔(过滤掉其他月)."""
    from my_ai_employee.connectors._types import RawTransaction
    from my_ai_employee.core.expense_aggregate import current_month_expense
    from my_ai_employee.core.transaction_adapter import TransactionAdapter

    rows = [
        # 2026-05(上月末,不在 2026-06 范围)
        RawTransaction(
            date=date(2026, 5, 31),
            amount=Decimal("100.00"),
            counterparty="5月商家",
            type="支出",
            payment_method="微信支付",
            external_transaction_id="s63-may",
            raw_row_hash="0" * 32,
        ),
        # 2026-06(当月,在 2026-06 范围)
        RawTransaction(
            date=date(2026, 6, 15),
            amount=Decimal("50.00"),
            counterparty="6月商家",
            type="支出",
            payment_method="微信支付",
            external_transaction_id="s63-jun",
            raw_row_hash="0" * 32,
        ),
        # 2026-07(下月初,不在 2026-06 范围)
        RawTransaction(
            date=date(2026, 7, 1),
            amount=Decimal("200.00"),
            counterparty="7月商家",
            type="支出",
            payment_method="微信支付",
            external_transaction_id="s63-jul",
            raw_row_hash="0" * 32,
        ),
    ]
    adapter = TransactionAdapter(session_factory)
    adapter.import_raw_transactions(rows, source="wechat")

    # today=2026-06-30 → 仅 6月1笔 50.00
    total_jun = current_month_expense(session_factory, today=date(2026, 6, 30))
    assert total_jun == Decimal("50.00")
    # today=2026-05-31 → 仅 5月1笔 100.00
    total_may = current_month_expense(session_factory, today=date(2026, 5, 31))
    assert total_may == Decimal("100.00")


def test_decimal_precision_no_float_drift(session_factory: sessionmaker[Session]) -> None:
    """5. Decimal 累加精度(13.14 + 13.14 = 26.28,严判非 float 漂移).

    Float 0.1 + 0.2 = 0.30000000000000004 是经典 bug,
    验证 current_month_expense 走 Decimal 全程(Numeric(10, 2) + func.coalesce)。
    """
    from my_ai_employee.connectors._types import RawTransaction
    from my_ai_employee.core.expense_aggregate import current_month_expense
    from my_ai_employee.core.transaction_adapter import TransactionAdapter

    rows = [
        RawTransaction(
            date=date(2026, 6, x),
            amount=Decimal("13.14"),
            counterparty=f"商家-{x}",
            type="支出",
            payment_method="微信支付",
            external_transaction_id=f"s63-prec-{x:03d}",
            raw_row_hash="0" * 32,
        )
        for x in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)  # 10 笔
    ]
    adapter = TransactionAdapter(session_factory)
    adapter.import_raw_transactions(rows, source="wechat")

    total = current_month_expense(session_factory, today=date(2026, 6, 30))
    # 10 × 13.14 = 131.40(Decimal 严判)
    assert total == Decimal("131.40")
    # 严判:不是 float(若是 float 0.1 + 0.2 会有精度漂移)
    assert isinstance(total, Decimal)


def test_today_none_uses_default_today(session_factory: sessionmaker[Session]) -> None:
    """6. today=None → 默认 date.today()(调用方零配置即用)."""
    from datetime import date as _date

    from my_ai_employee.connectors._types import RawTransaction
    from my_ai_employee.core.expense_aggregate import current_month_expense
    from my_ai_employee.core.transaction_adapter import TransactionAdapter

    # 插入一笔"今天"日期的交易
    today = _date.today()
    raw = RawTransaction(
        date=today,
        amount=Decimal("99.00"),
        counterparty="今天商家",
        type="支出",
        payment_method="微信支付",
        external_transaction_id="s63-today",
        raw_row_hash="0" * 32,
    )
    adapter = TransactionAdapter(session_factory)
    adapter.import_raw_transactions([raw], source="wechat")

    # 不传 today → 走默认 date.today() → 99.00
    total = current_month_expense(session_factory)
    assert total == Decimal("99.00")


def test_session_factory_none_raises_type_error() -> None:
    """7. session_factory=None → TypeError(严判入口,防 NoneType 误调)."""
    from my_ai_employee.core.expense_aggregate import current_month_expense

    with pytest.raises(TypeError, match="session_factory"):
        current_month_expense(None, today=date(2026, 6, 15))


def test_today_non_date_raises_type_error() -> None:
    """8. today=非 date(str/int) → TypeError(严判入口,防 datetime 误传)."""
    from my_ai_employee.core.expense_aggregate import current_month_expense

    with pytest.raises(TypeError, match="today"):
        # 故意传一个非 date 字符串,应该被严判
        # 实际 session_factory 必传先严判,所以传个空 session_factory 配合字符串 today
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from my_ai_employee.core.models import Base

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        current_month_expense(sf, today="2026-06-15")
