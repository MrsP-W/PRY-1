"""Mac 菜单栏 UI（rumps）。

D5 实施。Week 1 D5 显示：今日未读 / 今日待办 / 本月支出。
D9.3 实施：Notes 菜单栏 App(沿 D10 留 ExpenseService 注入点)。
"""

from my_ai_employee.menu_bar.app import NotesMenuBarApp
from my_ai_employee.menu_bar.expense_service import (
    ExpenseService,
    ExpenseServiceStub,
)

__all__ = [
    "ExpenseService",
    "ExpenseServiceStub",
    "NotesMenuBarApp",
]
