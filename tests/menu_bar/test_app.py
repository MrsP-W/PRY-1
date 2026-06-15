"""D9.3 — NotesMenuBarApp 测试(8 cases,沿 D4.7.3 严判范本 + D5.6.4 rumps 隔离).

设计原则:
    - `monkeypatch.setattr(rumps, "App", _FakeRumpsApp)` 隔离 NSApp 拉起
    - `monkeypatch.setattr(sys, "executable", "/usr/bin/python3")` 替换 python 路径
    - `monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)` mock 子进程
    - 私有方法 _on_sync_now / _on_open_privacy 直接调(白盒测试)
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

# ===== 隔离 helper =====


class _FakeRumpsApp:
    """rumps.App 替身 — 跳过 NSApp 拉起,只记录 super().__init__ 入参."""

    def __init__(self, name: str, *, title: str = "") -> None:
        self._name = name
        self.title = title
        self.menu: list[Any] = []

    # 注解 @rumps.events.clicked 走过的回调入口 — 我们的 _on_* 不需要


class _FakeMenuItem:
    """rumps.MenuItem 替身."""

    def __init__(self, title: str) -> None:
        self.title = title


@pytest.fixture
def fake_rumps(monkeypatch: pytest.MonkeyPatch) -> None:
    """monkeypatch rumps.App 为 _FakeRumpsApp(隔离 NSApp 拉起)."""
    monkeypatch.setattr("rumps.App", _FakeRumpsApp)
    # rumps 0.4.0:clicked 装饰器在主模块(非 rumps.events 子模块)
    # 用 lambda 装饰器原样返回函数,避免 rumps 内部 NSApp 注册
    import rumps as _rumps

    monkeypatch.setattr(
        _rumps,
        "clicked",
        lambda _name: lambda func: func,
    )
    # app.py 顶部 import 时已锁定 _notification_func = _rumps.notification
    # 直接 mock app 模块的 _notification_func(rumps.notification 改不到模块级变量)
    monkeypatch.setattr(
        "my_ai_employee.menu_bar.app._notification_func",
        MagicMock(),
    )


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """monkeypatch subprocess.run 为收集调用参数的 fake.

    Returns:
        list[dict] — 每次调用的入参记录(test 可 assert)
    """
    calls: list[dict[str, Any]] = []

    def _fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        calls.append({"args": args, "kwargs": kwargs})
        # 默认 returncode=0(stdout/stderr 空)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    return calls


# ===== T1. 默认 ExpenseServiceStub 注入 =====


def test_app_uses_default_stub(fake_rumps: None) -> None:
    """D9.3:T1 NotesMenuBarApp 不传 expense_service → 默认 Stub 注入."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar.expense_service import ExpenseServiceStub

    app = NotesMenuBarApp()
    assert isinstance(app._service, ExpenseServiceStub)
    assert app._notes_count == 0  # Stub 默认 0


# ===== T2. 自定义 expense_service 注入 =====


def test_app_accepts_custom_service(fake_rumps: None) -> None:
    """D9.3:T2 NotesMenuBarApp 接受 duck-typed ExpenseService 实现."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    class _CustomService:
        def get_total_notes_count(self) -> int:
            return 42

        def get_unsynced_count(self) -> int:
            return 7

        def get_recent_note_titles(self, limit: int = 5) -> list[str]:
            return ["Note A", "Note B"]

        def is_clipboard_listener_running(self) -> bool:
            return True

        def get_tcc_authorization_status(self) -> bool:
            return False

    app = NotesMenuBarApp(expense_service=_CustomService())  # type: ignore[arg-type]
    assert app._notes_count == 42
    assert app._service.get_unsynced_count() == 7
    assert app._service.get_recent_note_titles() == ["Note A", "Note B"]
    assert app._service.is_clipboard_listener_running() is True
    assert app._service.get_tcc_authorization_status() is False


# ===== T3. 非 ExpenseService 抛 TypeError =====


def test_app_invalid_service_raises(fake_rumps: None) -> None:
    """D9.3:T3 注入非 ExpenseService 实现 → TypeError(沿 D4.7.3 严判范本)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    class _NotExpenseService:
        pass

    with pytest.raises(TypeError, match="必须实现 ExpenseService 5 方法接口"):
        NotesMenuBarApp(expense_service=_NotExpenseService())  # type: ignore[arg-type]


# ===== T4. 初始 title 格式 =====


def test_app_title_format_initial(fake_rumps: None) -> None:
    """D9.3:T4 title 格式 "📝 Notes (N)"."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    assert app.title == "📝 Notes (0)"


# ===== T5. 4 菜单项注册 =====


def test_app_menu_items_registered(fake_rumps: None) -> None:
    """D9.3:T5 菜单项 4 个 + 1 分隔符."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    menu = app.menu
    assert "立即同步" in menu
    assert "打开 Notes" in menu
    assert "授权引导" in menu
    assert "退出" in menu
    assert None in menu  # 分隔符


# ===== T6. 同步成功路径 =====


def test_on_sync_now_success_path(fake_rumps: None, fake_subprocess: list[dict[str, Any]]) -> None:
    """D9.3:T6 同步 exit 0 → _refresh_title,无 notification."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    app._on_sync_now(_FakeMenuItem("立即同步"))

    # 1 次 subprocess.run(同步)
    assert len(fake_subprocess) == 1
    call_args = fake_subprocess[0]["args"][0]
    assert call_args[0] == sys.executable
    assert call_args[1] == "-m"
    assert call_args[2] == "my_ai_employee.scripts.sync_notes"
    assert call_args[3] == "sync"
    assert fake_subprocess[0]["kwargs"]["timeout"] == 120
    assert fake_subprocess[0]["kwargs"]["capture_output"] is True
    assert fake_subprocess[0]["kwargs"]["text"] is True


# ===== T7. 同步失败 → rumps.notification =====


def test_on_sync_now_failure_notification(
    fake_rumps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D9.3:T7 同步 exit != 0 → rumps.notification(沿 D5 范本)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    # subprocess.run 返回非 0
    failed_result = MagicMock(returncode=2, stdout="", stderr="DB 锁 / OperationalError")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: failed_result,
    )

    app = NotesMenuBarApp()
    app._on_sync_now(_FakeMenuItem("立即同步"))

    # _notification_func 被调(由 fake_rumps fixture 的 monkeypatch 注入 MagicMock)
    from my_ai_employee.menu_bar import app as app_module

    app_module._notification_func.assert_called_once()
    call_args = app_module._notification_func.call_args
    assert call_args[0][0] == "Notes 同步失败"
    # stderr 截断到 200 字符
    assert "DB 锁" in call_args[0][2]


# ===== T8. 授权引导 subprocess 调通 =====


def test_on_open_privacy_subprocess(
    fake_rumps: None, fake_subprocess: list[dict[str, Any]]
) -> None:
    """D9.3:T8 授权引导调 `open x-apple.systempreferences:...Privacy_Automation`."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    app._on_open_privacy(_FakeMenuItem("授权引导"))

    # 1 次 subprocess.run(打开 系统设置)
    assert len(fake_subprocess) == 1
    call_args = fake_subprocess[0]["args"][0]
    assert call_args[0] == "open"
    assert "x-apple.systempreferences" in call_args[1]
    assert "Privacy_Automation" in call_args[1]
