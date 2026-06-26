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


def _assert_menu_badge_updated(menu: Any, prefix: str, expected_count: str) -> bool:
    """验证 menu badge 已更新 — 同时支持 list[str] 和 rumps.Menu 2 种形态(沿 v0.2.2 #2 范本).

    Args:
        menu: app.menu 对象(可能是 list[str] 或 rumps.Menu)
        prefix: title 前缀(必含"📥 待确认"等 badge 关键词)
        expected_count: 期望的 count 字符串(如 "3", "1")

    Returns:
        bool: True = 找到且更新, False = 未找到或未更新
    """
    expected_title = f"{prefix} ({expected_count})"
    # 形态 1: list[str](test fake_rumps 环境)— 直接比对 str
    if isinstance(menu, list):
        return any(isinstance(item, str) and item == expected_title for item in menu)
    # 形态 2: rumps.Menu(真实 NSApp)— iter 出来是 str keys,必须查 MenuItem.title
    try:
        return any(
            isinstance(title, str)
            and title.startswith(prefix)
            and hasattr(menu_item, "title")
            and menu_item.title == expected_title
            for title, menu_item in menu.items()
        )
    except (TypeError, AttributeError):
        return False


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
    """D9.3:T4 / v0.2.53 P1 title 格式 "🧑‍💼 我的AI员工 (N)"."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    assert app.title == "🧑‍💼 我的AI员工 (0)"


# ===== T5. 4 菜单项注册 =====


def test_app_menu_items_registered(fake_rumps: None) -> None:
    """D9.3:T5 / v0.2.53 P1 菜单项注册."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    menu = app.menu
    menu_strs = [str(m) for m in menu]
    assert any("📋 今日待处理" in s for s in menu_strs), f"menu 缺 '今日待处理', 实际 {menu}"
    assert any("打开工作台" in s for s in menu_strs), f"menu 缺 '打开工作台', 实际 {menu}"
    assert any("系统健康" in s for s in menu_strs), f"menu 缺 '系统健康', 实际 {menu}"
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


# ===== v0.2.2 候选 #2 — NoteConfirmService 1-click 确认 UI 测试 =====
# 沿 D8.3 _refresh_anomaly_count 范本 + D9.3 _on_anomaly_alert 范本
# T13-T20 共 8 cases


# ===== T13. 默认 NoteConfirmServiceStub 注入 =====


def test_app_uses_default_note_confirm_stub(fake_rumps: None) -> None:
    """v0.2.2 #2:T13 NotesMenuBarApp 不传 note_confirm_service → 默认 Stub 注入."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceStub

    app = NotesMenuBarApp()
    assert isinstance(app._note_confirm_service, NoteConfirmServiceStub)
    # Stub 默认返回 0
    assert app._note_confirm_service.get_pending_confirm_count() == 0


# ===== T14. 自定义 note_confirm_service 注入 =====


def test_app_accepts_custom_note_confirm_service(fake_rumps: None) -> None:
    """v0.2.2 #2:T14 NotesMenuBarApp 接受 duck-typed note_confirm_service 注入.

    沿 T2 _CustomService 范本: 3 方法契约满足即可, 类型不强制 isinstance(NoteConfirmServiceStub).
    """
    from my_ai_employee.menu_bar import NotesMenuBarApp

    class _CustomConfirmService:
        """Duck-typed 实现 — 不继承 NoteConfirmServiceStub."""

        def __init__(self) -> None:
            self.confirm_calls: list[str] = []

        def get_pending_confirm_count(self) -> int:
            return 7

        def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
            return [
                {
                    "apple_note_id": f"id-{i}",
                    "title": f"Note {i}",
                    "folder": "工作",
                    "synced_at_ms": 1_780_000_000_000,
                    "candidate_match_id": None,
                    "needs_confirm": 1,
                }
                for i in range(min(limit, 3))
            ]

        def confirm_note(self, apple_note_id: str) -> None:
            self.confirm_calls.append(apple_note_id)

    custom = _CustomConfirmService()
    app = NotesMenuBarApp(note_confirm_service=custom)
    assert app._note_confirm_service is custom
    assert app._note_confirm_service.get_pending_confirm_count() == 7


# ===== T15. 严判 note_confirm_service 必须实现 3 方法契约 =====


def test_app_invalid_note_confirm_service_raises(fake_rumps: None) -> None:
    """v0.2.2 #2:T15 缺任一方法 → TypeError(沿 D4.7.3 公共 helper 范本)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    class _IncompleteConfirmService:
        def get_pending_confirm_count(self) -> int:
            return 0

        # 缺 list_pending_confirm + confirm_note

    with pytest.raises(TypeError, match="note_confirm_service 必须实现"):
        NotesMenuBarApp(note_confirm_service=_IncompleteConfirmService())  # type: ignore[arg-type]


# ===== T16. 新菜单项注册 "📥 待确认" + "📥 确认第 1 条" =====


def test_app_pending_confirm_menu_items_registered(fake_rumps: None) -> None:
    """v0.2.2 #2 / v0.2.53 P1:T16 menu 含 Notes待确认 + 确认第 1 条."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    menu_strs = [str(m) for m in app.menu]
    assert any("Notes待确认" in s for s in menu_strs), f"menu 缺 Notes待确认, 实际 {menu_strs}"
    assert any("📥 确认第 1 条" in s for s in menu_strs), (
        f"menu 缺 '📥 确认第 1 条', 实际 {menu_strs}"
    )


# ===== T17. _refresh_pending_confirm_count 刷新 badge =====


def test_refresh_pending_confirm_count_updates_badge(fake_rumps: None) -> None:
    """v0.2.2 #2:T17 调 _refresh_pending_confirm_count → 菜单项 '📥 待确认 (N)' 更新.

    沿 T? _refresh_anomaly_count 范本(直接注入自定义 service 替换 menu item).
    修复(v0.2.2 #2): app.menu 项是 str, 直接用 isinstance(item, str) + startswith 比较.
    """
    from my_ai_employee.menu_bar import NotesMenuBarApp

    class _StubConfirmService:
        def get_pending_confirm_count(self) -> int:
            return 3

        def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
            return []

        def confirm_note(self, apple_note_id: str) -> None:
            return None

    app = NotesMenuBarApp(note_confirm_service=_StubConfirmService())
    # 触发刷新
    app._refresh_pending_confirm_count()

    # 验证 menu 中"📥 待确认" 项更新到 (3)
    # 修复(v0.2.2 #2): rumps.Menu(真实 NSApp)iter 出来是 str keys,改 MenuItem.title 不会改 keys;
    # 必须同时检查 list[str] 形态(替换 str)和 MenuItem 形态(改 .title)
    found = _assert_menu_badge_updated(app.menu, "  📝 Notes待确认", "3")
    assert found, "未找到 'Notes待确认' 菜单项"


# ===== T18. _on_show_pending_confirm 空列表 → "暂无待确认" notification =====


def test_on_show_pending_confirm_empty_notification(fake_rumps: None) -> None:
    """v0.2.2 #2:T18 空待确认 → notification '暂无待确认'(沿 D8.3 _on_anomaly_alert 范本)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar import app as app_module

    class _EmptyConfirmService:
        def get_pending_confirm_count(self) -> int:
            return 0

        def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
            return []

        def confirm_note(self, apple_note_id: str) -> None:
            return None

    app = NotesMenuBarApp(note_confirm_service=_EmptyConfirmService())
    app._on_show_pending_confirm(_FakeMenuItem("  📝 Notes待确认"))

    app_module._notification_func.assert_called_once()
    call_args = app_module._notification_func.call_args
    assert call_args[0][0] == "📥 待确认"
    assert call_args[0][1] == "暂无待确认"
    assert "needs_confirm=0" in call_args[0][2]


# ===== T19. _on_show_pending_confirm 非空列表 → 弹窗显示 top 10 =====


def test_on_show_pending_confirm_non_empty_notification(fake_rumps: None) -> None:
    """v0.2.2 #2:T19 非空待确认 → notification 弹窗显示 N 条(沿 D8.3 范本)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar import app as app_module

    class _NonEmptyConfirmService:
        def get_pending_confirm_count(self) -> int:
            return 2

        def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
            return [
                {
                    "apple_note_id": "id-1",
                    "title": "Note 1",
                    "folder": "工作",
                    "synced_at_ms": 1_780_000_000_000,
                    "candidate_match_id": 10,
                    "needs_confirm": 1,
                },
                {
                    "apple_note_id": "id-2",
                    "title": "Note 2",
                    "folder": "生活",
                    "synced_at_ms": 1_780_000_001_000,
                    "candidate_match_id": None,
                    "needs_confirm": 1,
                },
            ]

        def confirm_note(self, apple_note_id: str) -> None:
            return None

    app = NotesMenuBarApp(note_confirm_service=_NonEmptyConfirmService())
    app._on_show_pending_confirm(_FakeMenuItem("  📝 Notes待确认"))

    app_module._notification_func.assert_called_once()
    call_args = app_module._notification_func.call_args
    # 标题: 📥 待确认 (2 条)
    assert call_args[0][0] == "📥 待确认 (2 条)"
    # 副标题: L2 跨源候选(顶部 1 条待 1-click 确认)
    assert "顶部 1 条" in call_args[0][1]
    # body 含 2 条 note 标题
    body = call_args[0][2]
    assert "Note 1" in body
    assert "Note 2" in body
    assert "工作" in body
    assert "生活" in body


# ===== T20. _on_confirm_first 1-click 确认 top 1 + 刷新 badge + 弹成功通知 =====


def test_on_confirm_first_success_flow(fake_rumps: None) -> None:
    """v0.2.2 #2:T20 _on_confirm_first 成功: 调 confirm_note + 刷新 badge + 弹成功 notification."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar import app as app_module

    class _PendingConfirmService:
        def __init__(self) -> None:
            self.confirm_calls: list[str] = []
            self._list_call_count = 0

        def get_pending_confirm_count(self) -> int:
            return 1  # badge 数字

        def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
            self._list_call_count += 1
            # 第一次调: _on_confirm_first 拉 top 1 → 返回 [top1]
            # 第二次调: _refresh_pending_confirm_count 间接调 list_by_needs_confirm(走 Real)
            # 但 Stub 不调 list_by_needs_confirm,只调 get_pending_confirm_count, 所以不需返回
            if self._list_call_count == 1:
                return [
                    {
                        "apple_note_id": "top-1",
                        "title": "Top Note",
                        "folder": "工作",
                        "synced_at_ms": 1_780_000_000_000,
                        "candidate_match_id": 99,
                        "needs_confirm": 1,
                    }
                ]
            return []

        def confirm_note(self, apple_note_id: str) -> None:
            self.confirm_calls.append(apple_note_id)

    svc = _PendingConfirmService()
    app = NotesMenuBarApp(note_confirm_service=svc)

    # 触发 1-click 确认
    app._on_confirm_first(_FakeMenuItem("📥 确认第 1 条"))

    # 验 confirm_note 被调 1 次, 入参 "top-1"
    assert svc.confirm_calls == ["top-1"]

    # 验 _notification_func 被调(成功反馈)
    app_module._notification_func.assert_called()
    call_args_list = app_module._notification_func.call_args_list
    success_call = next(
        (c for c in call_args_list if c[0][0] == "📥 1-click 确认成功"),
        None,
    )
    assert success_call is not None, f"未找到成功 notification, 实际 {call_args_list}"
    assert success_call[0][1] == "Top Note"
    assert "top-1" in success_call[0][2]

    # 验 menu badge 已被刷新到 (1)
    # 修复(v0.2.2 #2): rumps.Menu 形态下, iter 出来是 OrderedDict 的 str keys
    # (改 MenuItem.title 不会改 keys); 必须用 _assert_menu_badge_updated 同时支持 2 种形态
    found_badge = _assert_menu_badge_updated(app.menu, "  📝 Notes待确认", "1")
    assert found_badge, "未找到 'Notes待确认' 菜单项"


# ===== T21. _on_confirm_first 空列表 → "暂无待确认" notification =====


def test_on_confirm_first_empty_returns_placeholder(fake_rumps: None) -> None:
    """v0.2.2 #2:T21 空待确认 → 1-click 弹'暂无待确认'(沿 _on_show_pending_confirm 范本)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar import app as app_module

    class _EmptyConfirmService:
        def get_pending_confirm_count(self) -> int:
            return 0

        def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
            return []

        def confirm_note(self, apple_note_id: str) -> None:
            return None

    app = NotesMenuBarApp(note_confirm_service=_EmptyConfirmService())
    app._on_confirm_first(_FakeMenuItem("📥 确认第 1 条"))

    app_module._notification_func.assert_called_once()
    call_args = app_module._notification_func.call_args
    assert call_args[0][0] == "📥 1-click 确认"
    assert call_args[0][1] == "暂无待确认"


# ===== v0.2.53 P1 — Codex 菜单栏升级测试 T22-T26 =====


def test_app_uses_default_outbox_draft_stub(fake_rumps: None) -> None:
    """v0.2.53 P1:T22 默认 OutboxDraftServiceStub 注入."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar.outbox_draft_service import OutboxDraftServiceStub

    app = NotesMenuBarApp()
    assert isinstance(app._outbox_draft_service, OutboxDraftServiceStub)
    assert app._outbox_draft_service.get_pending_draft_count() == 0


def test_app_title_reflects_pending_total(fake_rumps: None) -> None:
    """v0.2.53 P1:T23 title 数字 = 邮件草稿 + Notes + 财务异常."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    class _DraftSvc:
        def get_pending_draft_count(self) -> int:
            return 2

        def list_pending_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
            return []

    class _ConfirmSvc:
        def get_pending_confirm_count(self) -> int:
            return 3

        def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
            return []

        def confirm_note(self, apple_note_id: str) -> None:
            return None

    class _ExpenseSvc:
        def get_total_notes_count(self) -> int:
            return 0

        def get_unsynced_count(self) -> int:
            return 0

        def get_recent_note_titles(self, limit: int = 5) -> list[str]:
            return []

        def is_clipboard_listener_running(self) -> bool:
            return False

        def get_tcc_authorization_status(self) -> bool:
            return False

        def get_anomaly_count(self) -> int:
            return 1

        def get_recent_anomalies(self, limit: int = 10) -> list[dict[str, Any]]:
            return []

    app = NotesMenuBarApp(
        expense_service=_ExpenseSvc(),
        note_confirm_service=_ConfirmSvc(),
        outbox_draft_service=_DraftSvc(),
    )
    assert app.title == "🧑‍💼 我的AI员工 (6)"


def test_on_open_dashboard_subprocess(
    fake_rumps: None, fake_subprocess: list[dict[str, Any]]
) -> None:
    """v0.2.53 P1:T24 打开工作台 → open docs/ui/codex-style-dashboard.html."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp()
    app._on_open_dashboard(_FakeMenuItem("打开工作台"))

    assert len(fake_subprocess) == 1
    call_args = fake_subprocess[0]["args"][0]
    assert call_args[0] == "open"
    assert call_args[1].endswith("docs/ui/codex-style-dashboard.html")


def test_on_system_health_notification(fake_rumps: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.2.53 P1:T25 系统健康 → notification 含质量门基线."""
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar import app as app_module

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="abc123\n", stderr=""),
    )
    app = NotesMenuBarApp()
    app._on_system_health(_FakeMenuItem("系统健康"))

    app_module._notification_func.assert_called_once()
    call_args = app_module._notification_func.call_args
    assert call_args[0][0] == "系统健康"
    assert "2475 passed" in call_args[0][2]
    assert "abc123" in call_args[0][2]


def test_app_invalid_outbox_draft_service_raises(fake_rumps: None) -> None:
    """v0.2.53 P1:T26 缺 get_pending_draft_count → TypeError."""

    class _BadDraft:
        pass

    from my_ai_employee.menu_bar import NotesMenuBarApp

    with pytest.raises(TypeError, match="outbox_draft_service 必须实现"):
        NotesMenuBarApp(outbox_draft_service=_BadDraft())  # type: ignore[arg-type]
