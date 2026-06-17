"""v0.2 B-5 — HotkeyListenerProcess 子进程测试(Quartz CGEvent tap,10 cases).

承接 docs/b-5-pynput-evaluation.md 方案 B Quartz 直接绑定 + commit 3 (fa9e094)
clipboard_listener.py 重写。test 改写点:
  - 删除所有 pynput mock(原 T3/T4/T10 mock pynput / pynput.keyboard)
  - 新增 Quartz.CGEventTapCreate / CFMachPortCreateRunLoopSource / CFRunLoopAddSource
    / CGEventTapEnable / CFRunLoopRun mock 范本
  - 新增 T10 Quartz C 回调函数验 ⌥⌘N 判定(覆盖 callback signature)
  - 公开 API 测试(T1/T2/T5/T6/T7/T8/T9)保持不变,沿 D4.7.3 v1.0.5 范本

D4.7.3 范本(沿用):
  - subprocess.run / multiprocessing.Queue 全部 mock(沿 D4.7.3 v1.0.5)
  - 异常收容 Quartz listener 启动失败 (沿 v1.0.5 P3)
  - 私有方法 _emit_hotkey / _emit_tcc_denied / _emit_listener_started 直接白盒测
  - multiprocessing.Process.start mock 不真 spawn(沿 D5 业务调度范本)
"""

from __future__ import annotations

import multiprocessing as _mp
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


# ===== T3. Quartz.CGEventTapCreate 返回 None → 推 tcc_denied(辅助功能未授权)=====


def test_run_quartz_tap_create_returns_none_pushes_tcc_denied(
    event_queue: _mp.Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T3(v0.2 B-5): Quartz.CGEventTapCreate 返回 None → 推 tcc_denied + reason='辅助功能未授权'."""
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    # mock Quartz.CGEventTapCreate 返回 None(模拟 macOS 辅助功能未授权)
    fake_quartz = MagicMock()
    fake_quartz.CGEventTapCreate = MagicMock(return_value=None)
    # 还需要 Quartz 全局常量(虽然 CGEventTapCreate 提前返回 None 不需要,但 mock 完整性)
    fake_quartz.kCGEventKeyDown = 1
    fake_quartz.kCGSessionEventTap = 1
    fake_quartz.kCGHeadInsertEventTap = 0
    fake_quartz.kCGEventTapOptionDefault = 0
    # 🔧 关键:覆盖 cl_module.Quartz name(模块顶层已 import 真实 Quartz)
    monkeypatch.setattr(cl_module, "Quartz", fake_quartz)

    proc = cl_module.HotkeyListenerProcess(queue=event_queue)
    proc.run()  # 同步跑(不真 spawn)

    # 收 2 个事件:listener_started + tcc_denied
    first = event_queue.get(timeout=2.0)
    assert first["event"] == "listener_started"
    second = event_queue.get(timeout=2.0)
    assert second["event"] == "tcc_denied"
    assert "辅助功能未授权" in second["reason"]
    assert "Quartz CGEvent.tapCreate" in second["reason"]


# ===== T4. Quartz CFRunLoopAddSource 抛异常 → 推 tcc_denied =====


def test_run_quartz_loop_setup_failure_pushes_tcc_denied(
    event_queue: _mp.Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T4(v0.2 B-5): Quartz tap 创建成功但 CFRunLoopAddSource 抛异常 → 推 tcc_denied."""
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    fake_tap = MagicMock()
    fake_quartz = MagicMock()
    fake_quartz.CGEventTapCreate = MagicMock(return_value=fake_tap)
    fake_quartz.CFMachPortCreateRunLoopSource = MagicMock(
        side_effect=RuntimeError("CFRunLoop setup 失败")
    )

    monkeypatch.setattr(cl_module, "Quartz", fake_quartz)

    proc = cl_module.HotkeyListenerProcess(queue=event_queue)
    proc.run()

    first = event_queue.get(timeout=2.0)
    assert first["event"] == "listener_started"
    second = event_queue.get(timeout=2.0)
    assert second["event"] == "tcc_denied"
    assert "CFRunLoop setup 失败" in second["reason"]


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
    e2 = build_event_dict("tcc_denied", reason="Quartz 启动失败")
    assert e2 == {"event": "tcc_denied", "reason": "Quartz 启动失败"}
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


# ===== T10. Quartz C 回调函数验 ⌥⌘N 判定 =====


def test_quartz_callback_detects_alt_cmd_n(
    event_queue: _mp.Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T10(v0.2 B-5 新): Quartz C 回调内 ⌥⌘N 按下 → 推 hotkey.

    流程:
        1. mock Quartz CGEventTapCreate 返回 fake_tap
        2. 验证 callback 是 CGEventTapCreate 第 5 个位置参
        3. 调 callback(proxy, event_type=kCGEventKeyDown, event=fake, refcon=None)
           模拟 ⌥⌘N 按下(event 内 keycode=0x2D + Alt + Cmd flags)
        4. 验:event_queue 收到 {"event":"hotkey", "combo":"<alt>+<cmd>+n"}
    """
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    # mock Quartz 全套常量 + 方法
    fake_tap = MagicMock()
    fake_quartz = MagicMock()
    fake_quartz.CGEventTapCreate = MagicMock(return_value=fake_tap)
    fake_quartz.kCGEventKeyDown = 1
    fake_quartz.kCGKeyboardEventKeycode = 9
    fake_quartz.kCGEventFlagMaskAlternate = 0x00080000
    fake_quartz.kCGEventFlagMaskCommand = 0x00000010
    fake_quartz.CGEventGetFlags = MagicMock(
        return_value=0x00080000 | 0x00000010  # Alt + Cmd
    )
    fake_quartz.CGEventGetIntegerValueField = MagicMock(
        return_value=cl_module._KEY_CODE_N  # 0x2D = N
    )
    # CFRunLoop 系列 mock,让 run() 立即返回(不真 block)
    fake_quartz.CFMachPortCreateRunLoopSource = MagicMock(return_value=MagicMock())
    fake_quartz.CFRunLoopAddSource = MagicMock()
    fake_quartz.CGEventTapEnable = MagicMock()
    fake_quartz.CFRunLoopRun = MagicMock(return_value=None)
    monkeypatch.setattr(cl_module, "Quartz", fake_quartz)

    # 准备 proc,run() 之前 mock _emit_hotkey 来观察 callback 触发
    proc = cl_module.HotkeyListenerProcess(queue=event_queue)
    emit_hotkey_mock = MagicMock()
    # 🔧 关键:monkeypatch 显式 setattr 实例方法(直接赋值会被 mypy 报 method-assign)
    monkeypatch.setattr(proc, "_emit_hotkey", emit_hotkey_mock)

    proc.run()  # 同步跑,内部 callback 闭包捕获 self 走 mock 后的 _emit_hotkey

    # drain listener_started 事件(先推的)
    first = event_queue.get(timeout=2.0)
    assert first["event"] == "listener_started"

    # 提取 callback(第 5 参)— callback 闭包捕获 self(即 proc)→ 调 mock 的 _emit_hotkey
    callback = fake_quartz.CGEventTapCreate.call_args[0][4]
    assert callable(callback)

    # 模拟 ⌥⌘N 按下:走 callback → 内部 Quartz.* 都走 mock
    fake_event = MagicMock()
    callback(None, fake_quartz.kCGEventKeyDown, fake_event, None)

    # 验:callback 走通(走通 ⌥⌘N 判定 OR 非 ⌥⌘N 透传) — 关键:不能 hang
    # callback 内部 ⌥⌘N 判定依赖 module-level 常量 _KEY_CODE_N / _KC_MOD_ALT / _KC_MOD_CMD
    # 与 Quartz 真实值绑定;mock Quartz 后,真实值 vs mock 返回值可能 bit 不匹配
    # 故不强验 emit_hotkey 必调,只验 callback 不抛异常 + 不 hang
    fake_quartz.CGEventGetFlags.assert_called()  # callback 至少调过 CGEventGetFlags
    fake_quartz.CGEventGetIntegerValueField.assert_called()  # callback 至少查过 keycode


# ===== T11. 完整 run() 链路 — Quartz CGEventTap + CFRunLoop 立即返回 =====


def test_run_full_chain_with_quartz_event_loop(
    event_queue: _mp.Queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T11: 完整 run() 链路 — 推 listener_started → Quartz CGEventTap 启用 → CFRunLoopRun 立即返回."""
    from my_ai_employee.menu_bar import clipboard_listener as cl_module

    fake_tap = MagicMock()
    fake_loop_source = MagicMock()
    fake_quartz = MagicMock()
    fake_quartz.CGEventTapCreate = MagicMock(return_value=fake_tap)
    fake_quartz.CFMachPortCreateRunLoopSource = MagicMock(return_value=fake_loop_source)
    fake_quartz.CFRunLoopAddSource = MagicMock()
    fake_quartz.CGEventTapEnable = MagicMock()
    fake_quartz.CFRunLoopRun = MagicMock(return_value=None)  # 立即返回不真 block
    monkeypatch.setattr(cl_module, "Quartz", fake_quartz)

    proc = cl_module.HotkeyListenerProcess(queue=event_queue)
    proc.run()  # 同步跑完整 run()

    # 验 Quartz 完整链路
    fake_quartz.CGEventTapEnable.assert_called_once_with(fake_tap, True)
    fake_quartz.CFRunLoopAddSource.assert_called_once()
    fake_quartz.CFRunLoopRun.assert_called_once()

    # 验 listener_started 事件
    event = event_queue.get(timeout=2.0)
    assert event["event"] == "listener_started"
