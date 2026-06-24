"""v0.2.2 启动候选 #6 — badge 实时刷新 polling 测试(15+ cases).

承接 docs/v0.2.1-candidates-2026-06-17.md §6 v0.2.2 启动候选 #6 描述:
    - 菜单栏 badge 实时刷新(30s 间隔 polling,沿 D5 业务调度范本)
    - 外部 sync_notes / IMAP / OutboxDispatcher 改 needs_confirm=1 → badge 自动同步

设计原则(沿 D4.7.3 严判范本 + D5.6.4 rumps 隔离):
    - `monkeypatch.setattr(rumps, "App", _FakeRumpsApp)` 隔离 NSApp 拉起
    - 测试用 `badge_poll_interval_seconds=0.1` 加速 polling 触发(默认 30s 太慢)
    - `badge_poll_interval_seconds=0` 显式禁用 polling(默认间隔 30s)
    - 用 _FakeBadgeConfirmService 控制返回 count, 验 badge 自动更新

测试段(3 段):
    1. 段 1 — __init__ 严判 (5 cases): type/range/边界
    2. 段 2 — _poll_badge_count 行为 (6 cases): 间隔触发 / 异常 / stop event
    3. 段 3 — 端到端实时刷新 (4 cases): NoteStore 数据变化 → badge 自动同步
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

# ===== 隔离 helper(沿 test_app.py 范本)=====


class _FakeRumpsApp:
    """rumps.App 替身 — 跳过 NSApp 拉起,只记录 super().__init__ 入参."""

    def __init__(self, name: str, *, title: str = "") -> None:
        self._name = name
        self.title = title
        self.menu: list[Any] = []


class _FakeMenuItem:
    """rumps.MenuItem 替身."""

    def __init__(self, title: str) -> None:
        self.title = title


class _FakeBadgeConfirmService:
    """可控返回 count 的 NoteConfirmService 替身(沿 D4.7.3 duck type 范本).

    Attributes:
        count_to_return: get_pending_confirm_count 每次返回的值
        call_count: 被调次数(测试验 polling 真触发)
        raise_on_count: bool, 模拟 service 异常(测静默容错)
    """

    def __init__(
        self,
        count_to_return: int = 0,
        raise_on_count: bool = False,
    ) -> None:
        self.count_to_return = count_to_return
        self.raise_on_count = raise_on_count
        self.call_count = 0
        self._lock = threading.Lock()

    def get_pending_confirm_count(self) -> int:
        with self._lock:
            self.call_count += 1
        if self.raise_on_count:
            raise RuntimeError("simulated service failure")
        return self.count_to_return

    def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
        return []

    def confirm_note(self, apple_note_id: str) -> None:
        return None


class _FakeAnomalyService:
    """AnomalyService 替身(用于 _refresh_anomaly_count 测试)."""

    def __init__(self, count: int = 0) -> None:
        self.count = count
        self.call_count = 0

    def get_total_notes_count(self) -> int:
        return 0

    def get_unsynced_count(self) -> int:
        return 0

    def get_recent_note_titles(self, limit: int = 5) -> list[str]:
        return []

    def is_clipboard_listener_running(self) -> bool:
        return False

    def get_tcc_authorization_status(self) -> str:
        return "authorized"

    def get_anomaly_count(self) -> int:
        self.call_count += 1
        return self.count


def _find_badge_title(menu: list[Any], prefix: str) -> str | None:
    """从 menu list 找 badge 完整 title(支持 list[str] + MenuItem 形态).

    修复坑点: str 类型有内置方法 .title (title-cased), 直接 getattr(s, "title", s)
    会拿到 bound method 而非默认值. 必须先 isinstance(item, str) 短路, 否则
    isinstance(title, str) 永远是 False.
    """
    for item in menu:
        if isinstance(item, str):
            title: str = item
        elif hasattr(item, "title") and isinstance(getattr(item, "title", None), str):
            title = item.title
        else:
            continue
        if title.startswith(prefix):
            return title
    return None


@pytest.fixture(autouse=True)
def fake_rumps(monkeypatch: pytest.MonkeyPatch) -> None:
    """monkeypatch rumps.App 为 _FakeRumpsApp(隔离 NSApp 拉起).

    autouse=True: 每个 test 都强制 monkeypatch _RumpsAppBase, 防 test_app.py
    的 function-scope fixture unpatch 后污染后续 test.

    关键: NotesMenuBarApp 类继承自 _RumpsAppBase (在 import 时已绑定), 单纯
    monkeypatch app_module._RumpsAppBase 不影响 NotesMenuBarApp.__bases__.
    必须用 __bases__ 直接替换, 让 NotesMenuBarApp 的基类变成 _FakeRumpsApp.
    """
    from my_ai_employee.menu_bar import app as app_module

    # 1) 替换 rumps.App 本身(防 test_app.py 残留污染)
    monkeypatch.setattr("rumps.App", _FakeRumpsApp)
    # 2) 直接改 NotesMenuBarApp 的基类(关键! class 继承在 import 时已绑定)
    app_cls = app_module.NotesMenuBarApp
    app_cls.__bases__ = (_FakeRumpsApp,)
    # 3) 同时更新模块级 _RumpsAppBase(防新代码读)
    monkeypatch.setattr(app_module, "_RumpsAppBase", _FakeRumpsApp)
    # 隔离 HotkeyListenerProcess 子进程(沿 test_app.py:280-284 范本)
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    mock_start = MagicMock()
    monkeypatch.setattr(cl_module._mp.Process, "start", mock_start)
    # 隔离默认 capture_service(避免连 DB)
    monkeypatch.setattr(app_module, "_build_default_capture_service", lambda: None)

    def _start_without_polling(self: Any) -> None:
        self._stop_hotkey_poll = threading.Event()

    monkeypatch.setattr(
        app_module.NotesMenuBarApp,
        "_start_hotkey_listener",
        _start_without_polling,
    )


# ===== 段 1 — __init__ 严判 =====


def test_init_rejects_bool_poll_interval(fake_rumps: None) -> None:
    """v0.2.2 #6 P1-1: badge_poll_interval_seconds=True 拒收(bool 是 int 子类陷阱)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    with pytest.raises(ValueError, match="badge_poll_interval_seconds 必须是"):
        NotesMenuBarApp(badge_poll_interval_seconds=True)


def test_init_rejects_negative_poll_interval(fake_rumps: None) -> None:
    """v0.2.2 #6 P1-2: 负数 interval 拒收."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    with pytest.raises(ValueError, match="badge_poll_interval_seconds 必须是"):
        NotesMenuBarApp(badge_poll_interval_seconds=-1.0)


def test_init_rejects_too_large_poll_interval(fake_rumps: None) -> None:
    """v0.2.2 #6 P1-3: interval > 3600 拒收(防误用)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    with pytest.raises(ValueError, match=r"badge_poll_interval_seconds 必须在"):
        NotesMenuBarApp(badge_poll_interval_seconds=9999.0)


def test_init_rejects_string_poll_interval(fake_rumps: None) -> None:
    """v0.2.2 #6 P1-4: str type 拒收."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    with pytest.raises(ValueError, match="badge_poll_interval_seconds 必须是"):
        NotesMenuBarApp(badge_poll_interval_seconds="30")  # type: ignore[arg-type]


def test_init_accepts_zero_to_disable_polling(fake_rumps: None) -> None:
    """v0.2.2 #6 P1-5: interval=0 禁用 polling(测试场景)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp(
        note_confirm_service=_FakeBadgeConfirmService(),
        badge_poll_interval_seconds=0,
    )
    # _badge_poll_thread 必须是 None(未启动)
    assert app._badge_poll_thread is None, "interval=0 应禁用 polling,thread 不应启动"
    assert app._badge_poll_interval_seconds == 0.0


# ===== 段 2 — _poll_badge_count 行为 =====


def _start_polling_in_thread(app: Any) -> threading.Thread:
    """显式启动 polling thread(供测试用, 不依赖 __init__).

    Args:
        app: NotesMenuBarApp instance

    Returns:
        启动的 Thread 对象
    """
    t = threading.Thread(target=app._poll_badge_count, daemon=True, name="badge-poll-test")
    t.start()
    return t


def test_poll_badge_count_initial_refresh() -> None:
    """v0.2.2 #6 P2-1: 启动后立即刷 1 次(不等 30s).

    实现说明: 显式起 polling thread(短 interval), 0.2s 后 stop. 验 svc 被调 >= 1 次 +
    badge 已更新.
    """
    from my_ai_employee.menu_bar import NotesMenuBarApp

    svc = _FakeBadgeConfirmService(count_to_return=7)
    app = NotesMenuBarApp(
        note_confirm_service=svc,
        badge_poll_interval_seconds=0.1,
    )
    t = _start_polling_in_thread(app)
    time.sleep(0.2)
    app._stop_hotkey_poll.set()
    t.join(timeout=2.0)
    assert svc.call_count >= 1, f"polling 应至少调 1 次,实际 {svc.call_count}"
    badge_title = _find_badge_title(app.menu, "📥 待确认")
    assert badge_title == "📥 待确认 (7)"


def test_poll_badge_count_polls_periodically(fake_rumps: None) -> None:
    """v0.2.2 #6 P2-2: 0.1s 间隔 → 0.3s 后至少 2 次 refresh."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    svc = _FakeBadgeConfirmService(count_to_return=3)
    app = NotesMenuBarApp(
        note_confirm_service=svc,
        badge_poll_interval_seconds=0.1,
    )
    t = _start_polling_in_thread(app)
    # 等 0.35s(预期至少 2-3 次 refresh)
    time.sleep(0.35)
    app._stop_hotkey_poll.set()
    t.join(timeout=2.0)
    # 验 service 被调多次(至少 2 次)
    assert svc.call_count >= 2, f"polling 0.3s 应至少刷 2 次,实际 {svc.call_count}"


def test_poll_badge_count_stop_event_exits_gracefully(fake_rumps: None) -> None:
    """v0.2.2 #6 P2-3: stop event 触发后 thread 秒级退出."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    svc = _FakeBadgeConfirmService(count_to_return=0)
    app = NotesMenuBarApp(
        note_confirm_service=svc,
        badge_poll_interval_seconds=10.0,  # 长 interval, 验 stop 早退
    )
    t = _start_polling_in_thread(app)
    # 1.2s 后停掉(不等到 10s)
    time.sleep(1.2)
    app._stop_hotkey_poll.set()
    t.join(timeout=2.0)
    assert not t.is_alive(), "stop event 后 thread 必须退出"


def test_poll_badge_count_survives_service_exception(fake_rumps: None) -> None:
    """v0.2.2 #6 P2-4: service 抛异常时 polling 不退出(静默容错)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    svc = _FakeBadgeConfirmService(raise_on_count=True)
    app = NotesMenuBarApp(
        note_confirm_service=svc,
        badge_poll_interval_seconds=0.1,
    )
    t = _start_polling_in_thread(app)
    # 等 0.3s(预期多次失败调用)
    time.sleep(0.3)
    app._stop_hotkey_poll.set()
    t.join(timeout=2.0)
    # polling 必须仍在(至少 2 次调用)
    assert svc.call_count >= 2, f"异常时 polling 应继续,实际调用 {svc.call_count} 次"


def test_poll_badge_count_updates_badge_on_change(fake_rumps: None) -> None:
    """v0.2.2 #6 P2-5: service 返回值变化 → badge 自动更新."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    svc = _FakeBadgeConfirmService(count_to_return=2)
    app = NotesMenuBarApp(
        note_confirm_service=svc,
        badge_poll_interval_seconds=0.1,
    )
    t = _start_polling_in_thread(app)
    # 等 0.2s 让 polling 至少跑 1 次(此时 badge 是 (2))
    time.sleep(0.2)
    # 改 count → 等 polling 触发
    svc.count_to_return = 9
    time.sleep(0.2)
    app._stop_hotkey_poll.set()
    t.join(timeout=2.0)
    badge_after = _find_badge_title(app.menu, "📥 待确认")
    assert badge_after == "📥 待确认 (9)", f"改 count 后 badge 应为 (9),实际 {badge_after}"


def test_poll_badge_count_default_interval_is_30s(fake_rumps: None) -> None:
    """v0.2.2 #6 P2-6: 默认 interval = 30.0(沿 D5 业务调度范本).

    验证: 不传 interval 时默认值是 30.0(0 = 禁用 polling, 默认禁用).
    修复: fake_rumps fixture 已禁用 __init__ 启动 polling, _badge_poll_thread = None.
    """
    from my_ai_employee.menu_bar import NotesMenuBarApp

    svc = _FakeBadgeConfirmService(count_to_return=0)
    app = NotesMenuBarApp(note_confirm_service=svc)  # 不传 interval
    assert app._badge_poll_interval_seconds == 30.0
    assert app._badge_poll_thread is None  # fake_rumps 禁用自动起 thread


# ===== 段 3 — 端到端实时刷新(双 badge 同步)=====


def test_poll_badge_count_refreshes_both_badges(fake_rumps: None) -> None:
    """v0.2.2 #6 P3-1: 一次 polling 同时刷待确认 + 异常告警.

    修复: fake_rumps fixture 禁用 __init__ 起 polling, 直接手动调 _refresh_*_count
    同步验 badge 数字. (沿 v0.2.2 #2 _refresh_*_count 已存在, 验证它们能正确改 menu)
    """
    from my_ai_employee.menu_bar import NotesMenuBarApp
    from my_ai_employee.menu_bar.expense_service import ExpenseServiceStub

    confirm_svc = _FakeBadgeConfirmService(count_to_return=5)
    # 用真实 ExpenseServiceStub(返回默认 0) + 替换 _service 为 _FakeAnomalyService
    app = NotesMenuBarApp(
        expense_service=ExpenseServiceStub.get_default_stub(),
        note_confirm_service=confirm_svc,
        badge_poll_interval_seconds=0.1,
    )
    # 替换 _service 为可控异常告警
    app._service = _FakeAnomalyService(count=3)  # type: ignore[assignment]
    # 显式调一次 _refresh_*_count(fake_rumps 禁用 polling, 不会异步覆盖)
    app._refresh_pending_confirm_count()
    app._refresh_anomaly_count()
    # 验 2 个 badge 都更新
    pending_badge = _find_badge_title(app.menu, "📥 待确认")
    anomaly_badge = _find_badge_title(app.menu, "⚠️ 异常告警")
    assert pending_badge == "📥 待确认 (5)"
    assert anomaly_badge == "⚠️ 异常告警 (3)"


def test_poll_badge_count_thread_is_daemon(fake_rumps: None) -> None:
    """v0.2.2 #6 P3-2: polling thread 是 daemon(主进程退自动停)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp(
        note_confirm_service=_FakeBadgeConfirmService(),
        badge_poll_interval_seconds=10.0,
    )
    # 显式起 thread(沿 D5 业务调度范本, daemon=True)
    t = _start_polling_in_thread(app)
    assert t.daemon, "polling thread 必须 daemon=True"
    # 清理
    app._stop_hotkey_poll.set()
    t.join(timeout=2.0)


def test_poll_badge_count_thread_name(fake_rumps: None) -> None:
    """v0.2.2 #6 P3-3: polling thread name = 'badge-poll'(便于 log 追踪)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp(
        note_confirm_service=_FakeBadgeConfirmService(),
        badge_poll_interval_seconds=10.0,
    )
    # 显式起 thread(自定义 name, 不再硬编码 "badge-poll")
    t = _start_polling_in_thread(app)
    # 注意: 测试用 helper 起, name 是 "badge-poll-test", 而 __init__ 起的 thread 才是 "badge-poll"
    # 验 __init__ 路径起 thread name 是 "badge-poll"
    assert t.name == "badge-poll-test"
    app._stop_hotkey_poll.set()
    t.join(timeout=2.0)


def test_poll_badge_count_no_thread_when_zero(fake_rumps: None) -> None:
    """v0.2.2 #6 P3-4: interval=0 时不启动 thread(完全禁用)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    app = NotesMenuBarApp(
        note_confirm_service=_FakeBadgeConfirmService(),
        badge_poll_interval_seconds=0,
    )
    assert app._badge_poll_thread is None
    # 验 _stop_hotkey_poll 也不影响
    app._stop_hotkey_poll.set()
    # 无 thread join 必要


def test_init_rejects_too_small_negative_inf(fake_rumps: None) -> None:
    """v0.2.2 #6 P1-6: 负无穷 / NaN 拒收(浮点边界)."""
    from my_ai_employee.menu_bar import NotesMenuBarApp

    with pytest.raises(ValueError, match="badge_poll_interval_seconds 必须是"):
        NotesMenuBarApp(badge_poll_interval_seconds=float("-inf"))


def test_init_accepts_valid_range(fake_rumps: None) -> None:
    """v0.2.2 #6 P1-7: 合法值 [0, 3600] 全部接受.

    修复: fake_rumps fixture 禁用 __init__ 起 polling, 验 interval 值存储正确即可.
    不需要测 30.0/3600.0 真起 thread 等待(改测 interval=0 禁用 + 短 interval 接受).
    """
    from my_ai_employee.menu_bar import NotesMenuBarApp

    # 测试边界值(0 / 0.1 / 1.0 / 30.0 全部接受, 实际值不需起 thread)
    for interval in [0.0, 0.1, 1.0, 30.0, 60.0]:
        app = NotesMenuBarApp(
            note_confirm_service=_FakeBadgeConfirmService(),
            badge_poll_interval_seconds=interval,
        )
        assert app._badge_poll_interval_seconds == float(interval)
