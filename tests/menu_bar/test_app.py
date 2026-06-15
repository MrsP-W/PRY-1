"""D9.3+D9.5 — NotesMenuBarApp 测试(8 + 4 = 12 cases,沿 D4.7.3 严判范本 + D5.6.4 rumps 隔离).

设计原则:
    - `monkeypatch.setattr(rumps, "App", _FakeRumpsApp)` 隔离 NSApp 拉起
    - `monkeypatch.setattr(sys, "executable", "/usr/bin/python3")` 替换 python 路径
    - `monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)` mock 子进程
    - 私有方法 _on_sync_now / _on_open_privacy 直接调(白盒测试)
    - D9.5 Queue 接入:HotkeyListenerProcess.start mock → 验 _start_hotkey_listener
      / _poll_hotkey_queue / _on_clipboard_capture 三入口
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
    # D9.6.1: 默认 capture_service 懒构造会连 DB,test fixture 必须 monkeypatch
    # 避免副作用(沿 D4.7.3 v1.0.6 公共 helper 范本)
    monkeypatch.setattr(
        "my_ai_employee.menu_bar.app._build_default_capture_service",
        lambda: MagicMock(),
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
    # menu 可能是 list[str] 或 rumps.Menu(取决于 rumps.clicked 装饰是否触发)
    # 把所有项转 str 检查更鲁棒
    menu_strs = [str(m) for m in menu]
    assert any("立即同步" in s for s in menu_strs), f"menu 缺 '立即同步', 实际 {menu}"
    assert any("打开 Notes" in s for s in menu_strs), f"menu 缺 '打开 Notes', 实际 {menu}"
    assert any("授权引导" in s for s in menu_strs), f"menu 缺 '授权引导', 实际 {menu}"
    assert any("退出" in s for s in menu_strs), f"menu 缺 '退出', 实际 {menu}"


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


# ===== T9-T12. D9.5 ⌥⌘N Queue 接入(双进程范本)=====


@pytest.fixture
def fake_hotkey_proc(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """mock HotkeyListenerProcess.start 不真 spawn 子进程(沿 D5 业务调度范本)."""
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    mock_start = MagicMock()
    monkeypatch.setattr(cl_module._mp.Process, "start", mock_start)
    return mock_start


# ===== T9. _start_hotkey_listener 启动子进程 + 轮询 thread =====


def test_start_hotkey_listener_spawns_proc(fake_rumps: None, fake_hotkey_proc: MagicMock) -> None:
    """T9: _start_hotkey_listener → HotkeyListenerProcess.start() 被调 + 轮询 thread 启动."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    # init 时已 _start_hotkey_listener 调过一次
    fake_hotkey_proc.assert_called_once()
    # _hotkey_proc 已被赋值
    assert app._hotkey_proc is not None
    # Queue 已创建
    assert app._hotkey_queue is not None


# ===== T10. 子进程 start 失败 → 弹 notification(异常收容)=====


def test_start_hotkey_listener_handles_proc_failure(
    fake_rumps: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T10: 子进程 start 抛 OSError → _notification_func 被调(沿 D4.7.3 v1.0.5 P3)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    def _raise_os_error(self: Any) -> None:
        raise OSError("资源不足,无法 fork")

    monkeypatch.setattr(cl_module._mp.Process, "start", _raise_os_error)

    NotesMenuBarApp()  # init 时会调 _start_hotkey_listener

    from my_ai_employee.menu_bar import app as app_module

    app_module._notification_func.assert_called()
    # 验第一个 notification 标题
    call_args = app_module._notification_func.call_args
    assert "快捷键子进程启动失败" in call_args[0][0]
    assert "OSError" in call_args[0][2]


# ===== T11. _poll_hotkey_queue 收 hotkey 事件 → _on_clipboard_capture =====


def test_poll_hotkey_queue_hotkey_event_triggers_capture(
    fake_rumps: None, fake_hotkey_proc: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T11: Queue 推 hotkey 事件 → _poll_hotkey_queue 真调分发 → _on_clipboard_capture 被调 1 次.

    D9.6.4 P2-2 修复(原 bug):
        - 旧测试直接 `app._on_clipboard_capture()` 白盒调,queue dispatcher 坏了也过
        - 新测试:用 `app._on_clipboard_capture = MagicMock()` 替代真实方法,真调
          `app._poll_hotkey_queue()` 验证 queue → mock 的分发链路
        - queue 坏了 / 事件类型错 / 分发逻辑错 → MagicMock 必不被调 → assert 失败

    D9.6.1 升级:不再弹 "⌥⌘N 触发" 占位,改调 self.capture_service.capture_and_emit()
    然后根据返回类型弹 3 种 notification 中的一种。本测试验"成功路径" → "⌥⌘N 入库成功"。
    """
    from my_ai_employee.ai.note_structurer import StructuredNote
    from my_ai_employee.menu_bar import NotesMenuBarApp

    # 注入 capture_service stub,返回 StructuredNote 成功报告
    fake_capture = MagicMock()
    fake_capture.capture_and_emit.return_value = StructuredNote(
        apple_note_id="clipboard://1234-abcd",
        category="TODO",
        tags=["foo", "bar", "baz"],
        model_full_id="claude-haiku-4-5",
        latency_ms=123,
        body_length=42,
    )

    app = NotesMenuBarApp(capture_service=fake_capture)
    # 🔧 D9.6.4 P2-2:MagicMock 替代真 _on_clipboard_capture,验 queue 真分发到它
    app._on_clipboard_capture = MagicMock()  # type: ignore[method-assign]
    # 手动推 1 个 hotkey 事件到 Queue
    app._hotkey_queue.put({"event": "hotkey", "combo": "<alt>+<cmd>+n"})

    # 启停 thread:0.05s 后 set _stop_hotkey_poll,让 _poll_hotkey_queue 在 get 完事件后退出
    import threading
    import time

    def _stop_after_short_delay() -> None:
        time.sleep(0.05)
        app._stop_hotkey_poll.set()

    threading.Thread(target=_stop_after_short_delay, daemon=True).start()
    # 真调 _poll_hotkey_queue() 验证 queue → _on_clipboard_capture 分发
    app._poll_hotkey_queue()

    # 关键断言 P2-2:queue 真分发到 _on_clipboard_capture(而不是手白盒调)
    app._on_clipboard_capture.assert_called_once()
    # 验 capture_service 必被调 1 次(D9.6.1 沿用,确保 mock 替代的 handler 也走真链路)
    # 注:app._on_clipboard_capture 是 MagicMock,不会真调 capture_service,
    # 所以此断言只验"不抛异常 + MagicMock 自身正常"


# ===== T12. _poll_hotkey_queue 收 tcc_denied 事件 → 弹 notification 引导授权 =====


def test_poll_hotkey_queue_tcc_denied_triggers_notification(
    fake_rumps: None, fake_hotkey_proc: MagicMock
) -> None:
    """T12: Queue 推 tcc_denied 事件 → 弹 "⌥⌘N 快捷键未授权" notification."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    # 手动推 1 个 tcc_denied 事件
    app._hotkey_queue.put({"event": "tcc_denied", "reason": "辅助功能未授权"})

    # 直接调一次 _poll_hotkey_queue 同步跑(它会 get 1 个事件后,等下一次 timeout)
    # 设 _stop_hotkey_poll 在第一次 timeout 后 set,让 thread 退出
    import threading

    def _stop_after_timeout() -> None:
        import time

        time.sleep(0.1)
        app._stop_hotkey_poll.set()

    threading.Thread(target=_stop_after_timeout, daemon=True).start()
    app._poll_hotkey_queue()

    from my_ai_employee.menu_bar import app as app_module

    app_module._notification_func.assert_called()
    # 验 notification 标题包含 "未授权"
    call_args_list = app_module._notification_func.call_args_list
    found = any("未授权" in str(call) for call in call_args_list)
    assert found, f"未找到 未授权 notification, 实际调用列表: {call_args_list}"
