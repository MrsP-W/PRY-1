"""S6.3 — expense_aggregate 独立模块(菜单栏支出总额聚合).

承接 S6 e2e 实化(D6+D7 已落 + S6.1+S6.2 e2e 真实断言 + 14dfb3c):
    - Transaction 表 16 列 ORM(D6.4 落定,db.transactions)
    - sessionmaker[Session] 工厂(由 e2e conftest 注入,D6.0 范本)
    - D9 menu_bar/expense_service.py 0 schema 变更可 import

设计哲学(沿 D6.6 docstring §15 编排层不重做业务逻辑):
  - 模块独立、纯函数、零外部依赖(DB 查询除外)
  - 类型严判:session_factory 必传(类型 is None / non-callable → TypeError);
              today 可选,默认 date.today()
  - Decimal 累加(Numeric(10, 2) 类型一致,不转 float 防精度漂移)
  - 当前月范围:[first_day, today](含首尾)

D9 启动预留:
  - menu_bar/expense_service.py 直接
    from my_ai_employee.core.expense_aggregate import current_month_expense
    def refresh_menu_bar(session_factory) -> None:
        total = current_month_expense(session_factory)
        rumps.MenuItem(f"本月支出: ¥{total:.2f}").set_menu(...)
  - 0 schema 变更、0 业务逻辑耦合

公共 API(沿 plan §S6.3 契约):
  - current_month_expense(session_factory, today=None) -> Decimal
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker


def current_month_expense(
    session_factory: sessionmaker[Session],
    today: _date | None = None,
) -> Decimal:
    """累加 Transaction.amount 在 [本月第一天, today] 范围(包含首尾)的总额.

    Args:
        session_factory: SQLAlchemy sessionmaker 工厂(e2e 用临时 sqlite,prod 用 SQLCipher)
        today: 计算截止日(含);None → date.today()(默认当月)

    Returns:
        当月支出总额(Decimal,Numeric(10, 2) 累加精度);空表 → Decimal("0")

    Raises:
        TypeError: session_factory 不是 sessionmaker,或 today 不是 date
    """
    if session_factory is None or not callable(session_factory):
        raise TypeError(
            f"session_factory 必为 SQLAlchemy sessionmaker(callable + 上下文管理),"
            f"实际 {type(session_factory).__name__}"
        )
    if today is not None and not isinstance(today, _date):
        raise TypeError(f"today 必为 date 或 None,实际 {type(today).__name__}")

    today = today or _date.today()
    first_day = today.replace(day=1)

    # 延迟 import 避免循环依赖 + 防 S6.3 模块 import 拖慢整个 core 包
    from my_ai_employee.db.transactions import Transaction

    with session_factory() as session:
        stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.transaction_date >= first_day,
            Transaction.transaction_date <= today,
        )
        result = session.execute(stmt).scalar_one()
        return Decimal(str(result))


__all__ = ["current_month_expense"]
