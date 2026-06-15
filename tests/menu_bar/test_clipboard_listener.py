"""D9.5 — HotkeyListenerProcess 子进程测试(10 cases).

承接 D9.5 plan §4 C4:
  - 严判 queue 必非 None + 子进程 daemon=True + name 锁定
  - 双进程范本测试隔离:monkeypatch multiprocessing.Process.start 不真 spawn
  - 直接同步调 run() 模拟子进程主体(沿 D5 业务调度范本)
  - pynput import 失败 → 推 tcc_denied + reason
  - hotkey 按下 → 推 hotkey 事件 + combo 字段

D4.7.3 范本:
  - subprocess.run / multiprocessing.Queue 全部 mock(沿 D4.7.3 v1.0.5)
  - 异常收容 pynput listener 启动失败 (沿 v1.0.5 P3)
  - 私有方法 _emit_hotkey / _emit_tcc_denied / _emit_listener_started 直接白盒测
"""

from __future__ import annotations

import multiprocessing as _mp
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

# ===== Fixtures =====


@pytest.fixture
def event_queue() -> _mp.Queue:
    """真实 multiprocessing.Queue(子进程和主进程通信用)."""
    return _mp.Queue()


# ===== T1. 初始化严判 — queue=None 抛 ValueError =====


def test_init_rejects_none_queue() -> None:
    """T1: queue=None → ValueError(queue 必传非 None,沿 D4.7.3 范本)."""
    from my_ai_employee.menu_bar.clipboard_listener import HotkeyListenerProcess

    with pytest.raises(ValueError, match="queue 必传非 None"):
        HotkeyListenerProcess(queue=None)  # type: ignore[arg-type]


# ===== T2. 初始化正常路径 — daemon=True + name 锁定 =====


def test_init_daemon_and_name(event_queue: _mp.Queue) -> None:
    """T2: HotkeyListenerProcess.daemon=True + name='notes-hotkey-listener'."""
    from my_ai_employee.menu_bar.clipboard_listener import HotkeyListenerProcess

    proc = HotkeyListenerProcess(queue=event_queue)
    assert proc.daemon is True
    assert proc.name == "notes-hotkey-listener"
    assert proc._queue is event_queue  # type: ignore[attr-defined]


# ===== T3. pynput import 失败 → 推 tcc_denied + reason =====


def test_run_pynput_import_failure_pushes_tcc_denied(
    event_queue: _mp.Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T3: pynput import 失败 → 推 {"event":"tcc_denied", "reason":"..."} 后退出."""
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    # mock pynput import 失败(直接 monkeypatch builtins.__import__ 太重,改 mock sys.modules)
    monkeypatch.setitem(sys.modules, "pynput", None)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "pynput.keyboard", None)  # type: ignore[arg-type]

    proc = cl_module.HotkeyListenerProcess(queue=event_queue)
    proc.run()  # 同步跑(不真 spawn)

    event = event_queue.get(timeout=2.0)
    assert event["event"] == "tcc_denied"
    assert "pynput import 失败" in event["reason"]


# ===== T4. pynput listener 启动失败 → 推 tcc_denied + reason =====


def test_run_listener_start_failure_pushes_tcc_denied(
    event_queue: _mp.Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T4: pynput.listener 启动抛异常(辅助功能未授权) → 推 tcc_denied + reason."""
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    # mock pynput 模块
    fake_pynput_keyboard = MagicMock()
    fake_pynput_keyboard.GlobalHotKeys.side_effect = RuntimeError(
        "this process is not trusted!（辅助功能未授权）"
    )

    class _FakePynputModule:
        keyboard = fake_pynput_keyboard

    monkeypatch.setitem(sys.modules, "pynput", _FakePynputModule())
    monkeypatch.setitem(sys.modules, "pynput.keyboard", fake_pynput_keyboard)

    proc = cl_module.HotkeyListenerProcess(queue=event_queue)
    proc.run()

    # 收 2 个事件:listener_started + tcc_denied
    first = event_queue.get(timeout=2.0)
    assert first["event"] == "listener_started"
    second = event_queue.get(timeout=2.0)
    assert second["event"] == "tcc_denied"
    assert "pynput listener 启动失败" in second["reason"]
    assert "辅助功能未授权" in second["reason"]


# ===== T5. hotkey 按下 → 推 hotkey 事件 + combo 字段 =====


def test_on_hotkey_pushes_event(event_queue: _mp.Queue) -> None:
    """T5: _on_hotkey() → 推 {"event":"hotkey", "combo":"<alt>+<cmd>+n"}."""
    from my_ai_employee.menu_bar.clipboard_listener import HotkeyListenerProcess

    proc = HotkeyListenerProcess(queue=event_queue)
    proc._on_hotkey()  # 白盒测私有方法(沿 D4.7.3 范本)

    event = event_queue.get(timeout=2.0)
    assert event["event"] == "hotkey"
    assert event["combo"] == "<alt>+<cmd>+n"


# ===== T6. _emit_tcc_denied 严判 reason 非空白 =====


def test_emit_tcc_denied_rejects_empty_reason(event_queue: _mp.Queue) -> None:
    """T6: _emit_tcc_denied(reason="") 或 "   " → ValueError(沿 D4.7.3 范本)."""
    from my_ai_employee.menu_bar.clipboard_listener import HotkeyListenerProcess

    proc = HotkeyListenerProcess(queue=event_queue)
    with pytest.raises(ValueError, match="reason 必填非空白"):
        proc._emit_tcc_denied(reason="")
    with pytest.raises(ValueError, match="reason 必填非空白"):
        proc._emit_tcc_denied(reason="   \n\t")


# ===== T7. _emit_listener_started 推 started 事件 =====


def test_emit_listener_started_pushes_event(event_queue: _mp.Queue) -> None:
    """T7: _emit_listener_started() → 推 {"event":"listener_started"}."""
    from my_ai_employee.menu_bar.clipboard_listener import HotkeyListenerProcess

    proc = HotkeyListenerProcess(queue=event_queue)
    proc._emit_listener_started()

    event = event_queue.get(timeout=2.0)
    assert event["event"] == "listener_started"


# ===== T8. build_event_dict 严判 event_type 白名单 =====


def test_build_event_dict_validates_event_type() -> None:
    """T8: build_event_dict 3 类白名单,非法 event_type → ValueError."""
    from my_ai_employee.menu_bar.clipboard_listener import build_event_dict

    # 合法 3 类
    e1 = build_event_dict("hotkey", combo="<alt>+<cmd>+n")
    assert e1 == {"event": "hotkey", "combo": "<alt>+<cmd>+n"}
    e2 = build_event_dict("tcc_denied", reason="pynput 启动失败")
    assert e2 == {"event": "tcc_denied", "reason": "pynput 启动失败"}
    e3 = build_event_dict("listener_started")
    assert e3 == {"event": "listener_started"}

    # 非法 event_type
    with pytest.raises(ValueError, match="event_type 必 ∈"):
        build_event_dict("hot_key")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="event_type 必 ∈"):
        build_event_dict("other_event")  # type: ignore[arg-type]


# ===== T9. 子进程 start 调 multiprocessing.Process.start =====


def test_start_calls_super_start(event_queue: _mp.Queue, monkeypatch: pytest.MonkeyPatch) -> None:
    """T9: proc.start() 调 multiprocessing.Process.start(不真 spawn,沿 D5 范本)."""
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    proc = cl_module.HotkeyListenerProcess(queue=event_queue)
    # mock 父类 start,避免真子进程 spawn
    mock_super_start = MagicMock()
    monkeypatch.setattr(_mp.Process, "start", mock_super_start)

    proc.start()
    mock_super_start.assert_called_once()


# ===== T10. 完整 run() 链路 — pynput mock + GlobalHotKeys 上下文 =====


def test_run_full_chain_listener_started_then_joins(
    event_queue: _mp.Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T10: 完整 run() 链路 — 推 listener_started → 调 listener.join() 阻塞."""
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    # mock GlobalHotKeys 进入 context manager 后 join() 立即返回(不真 block)
    fake_listener = MagicMock()
    fake_listener.join = MagicMock(return_value=None)  # join() 立即返回

    fake_cm = MagicMock()
    fake_cm.__enter__ = MagicMock(return_value=fake_listener)
    fake_cm.__exit__ = MagicMock(return_value=False)

    fake_keyboard = MagicMock()
    fake_keyboard.GlobalHotKeys = MagicMock(return_value=fake_cm)

    class _FakePynputModule:
        keyboard = fake_keyboard

    monkeypatch.setitem(sys.modules, "pynput", _FakePynputModule())
    monkeypatch.setitem(sys.modules, "pynput.keyboard", fake_keyboard)

    proc = cl_module.HotkeyListenerProcess(queue=event_queue)
    proc.run()  # 同步跑完整 run()

    # 验 GlobalHotKeys 入参是 hotkey 字典
    call_args = fake_keyboard.GlobalHotKeys.call_args
    hotkey_dict: dict[str, Any] = call_args[0][0]
    assert "<alt>+<cmd>+n" in hotkey_dict
    assert callable(hotkey_dict["<alt>+<cmd>+n"])

    # 验 listener.join() 被调
    fake_listener.join.assert_called_once()

    # 验 listener_started 事件被推
    event = event_queue.get(timeout=2.0)
    assert event["event"] == "listener_started"
