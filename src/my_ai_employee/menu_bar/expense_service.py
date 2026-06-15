"""D9.3 — ExpenseService 接口与 Stub 实现(沿 D10 留接口).

承接 docs/v0.1-launch-plan.md §D9.3:
    - NotesMenuBarApp 展示"今日未读 / 今日待办 / 本月支出"等状态
    - 阶段 1(D9.3)先建 5 方法 stub(返回 0 / [] / False)
    - 阶段 2(D10 启动)替换为真实 ExpenseService 实现(沿 S6.3
      `core/expense_aggregate.current_month_expense` 范本接入)

设计决策(2026-06-15 锁定):
    - 抽象 ExpenseService Protocol 类(5 方法) + Stub 硬编码实现
    - 注入到 NotesMenuBarApp(expense_service=...),默认构造 Stub
    - D10 替换时仅改 NotesMenuBarApp 构造点,菜单栏逻辑不动

D4.7.3 教训应用:
    - Protocol 类型用 Protocol 类(非 ABC,鸭子类型友好)
    - 5 方法返回值用 `Final` 常量(避免硬编码分散)
    - 严判 type 严格(不 isinstance,避免 bool/int 互窜)
"""

from __future__ import annotations

from typing import Final, Protocol


class ExpenseService(Protocol):
    """菜单栏状态服务接口(D9.3 Protocol + D10 真实实现).

    5 方法契约:
        - get_total_notes_count       → 菜单栏 title 数字(N)
        - get_unsynced_count          → "立即同步" 菜单 badge
        - get_recent_note_titles      → 子菜单"最近笔记"列表
        - is_clipboard_listener_running → "剪贴板监听" 状态项
        - get_tcc_authorization_status  → "授权引导" 高亮提示
    """

    def get_total_notes_count(self) -> int: ...

    def get_unsynced_count(self) -> int: ...

    def get_recent_note_titles(self, limit: int = 5) -> list[str]: ...

    def is_clipboard_listener_running(self) -> bool: ...

    def get_tcc_authorization_status(self) -> bool: ...


# ===== Stub 默认值常量(避免硬编码分散) =====

_TOTAL_NOTES_DEFAULT: Final[int] = 0
_UNSYNCED_DEFAULT: Final[int] = 0
_RECENT_TITLES_DEFAULT: Final[list[str]] = []
_CLIPBOARD_LISTENER_DEFAULT: Final[bool] = False
_TCC_AUTHORIZED_DEFAULT: Final[bool] = False


class ExpenseServiceStub:
    """D9.3 Stub 实现 — 5 方法全部返回硬编码默认值(沿 D10 留接口).

    设计取舍:
        - 不调 DB / 不调 rumps(完全解耦,测试零依赖)
        - 单例 (`get_default_stub()`),避免每次 new(可热替换)
        - 类型签名与 Protocol 100% 对齐(D10 真实实现可直接替换)

    D10 替换范本(在 app.py 构造点):
        # 旧(D9.3):
        self._service: ExpenseService = ExpenseServiceStub.get_default_stub()
        # 新(D10):
        self._service: ExpenseService = ExpenseServiceImpl.from_settings()

    Examples:
        >>> svc = ExpenseServiceStub.get_default_stub()
        >>> svc.get_total_notes_count()
        0
        >>> svc.get_recent_note_titles(limit=3)
        []
    """

    def get_total_notes_count(self) -> int:
        """返回 0(stub 阶段无 DB 接入)."""
        return _TOTAL_NOTES_DEFAULT

    def get_unsynced_count(self) -> int:
        """返回 0(stub 阶段无 DB 接入)."""
        return _UNSYNCED_DEFAULT

    def get_recent_note_titles(self, limit: int = 5) -> list[str]:
        """返回 [] (stub 阶段无 DB 接入)."""
        return list(_RECENT_TITLES_DEFAULT)

    def is_clipboard_listener_running(self) -> bool:
        """返回 False (stub 阶段 ⌥⌘N 监听器未启动)."""
        return _CLIPBOARD_LISTENER_DEFAULT

    def get_tcc_authorization_status(self) -> bool:
        """返回 False (stub 阶段未申请 TCC 授权)."""
        return _TCC_AUTHORIZED_DEFAULT

    @staticmethod
    def get_default_stub() -> ExpenseServiceStub:
        """返回 Stub 单例(沿 D5.6.4 工厂范本)."""
        return _DEFAULT_STUB


_DEFAULT_STUB: Final[ExpenseServiceStub] = ExpenseServiceStub()


__all__ = [
    "ExpenseService",
    "ExpenseServiceStub",
]
