"""v0.2 B-5 — ⌥⌘N 全局快捷键监听子进程(双进程范本 + Quartz CGEvent tap + TCC 引导).

承接 docs/b-5-pynput-evaluation.md 方案 B Quartz 直接绑定(根因解决 macOS Sequoia
pynput 1.7.7 不接收 bug,见 pynput/pynput#554):

    - 删除 pynput.keyboard.GlobalHotKeys
    - 改用 Quartz.CoreGraphics.CGEvent.tapCreate 注册全局事件 tap
    - 保留 HotkeyListenerProcess 双进程范本(沿 D4.7.3 v1.0.5 范本)
    - CGEvent.tapCreate 返回 None → 推 tcc_denied(沿 D9.6 实测范本)
    - 公开 API 不变(menu_bar/app.py 零改动)

设计要点(2026-06-16 锁定):
    - 双进程范本(沿 D4.7.3 v1.0.5 范本): rumps 主进程跑 NSApp 主循环 →
      本子进程跑 Quartz CGEvent tap → Queue[Any] 通信
    - Quartz CFRunLoopRun() 阻塞(daemon=True 主进程退出自动 kill)
    - 异常收容:Quartz tap=None / listener 启动失败 → 推 tcc_denied 后退出
    - emit_hotkey() 入口段:严判 queue 必非 None(沿 D4.7.3 范本)

不做:
    - 不在子进程内调 NoteStore(本步只 emit 事件,主进程决定怎么消费,沿
      D4.7.3 EmailDrafterAdapter 3 入口分离范本)
    - 不监听多组快捷键(本步只 ⌥⌘N,D10 扩多组)
    - 不写文件不调网络(子进程崩溃不污染主进程)

D9.6 降级路径不撤(沿 B-5 docs 评估决策 #3):
    D9.6 P1-1 业务层 3 入口 ClipboardCaptureService 仍保留,作为 Quartz 触发后
    业务层失败的兜底(沿 D4.7.3 范本)。
"""

from __future__ import annotations

import multiprocessing as _mp
from typing import Any

import Quartz

# ===== 全局快捷键组合(沿 v0.1-launch-plan.md:129 锁定)=====

_HOTKEY_COMBO: str = "<alt>+<cmd>+n"

# Quartz keycode(沿 Quartz.CoreGraphics.CGKeyCode)
# kVK_ANSI_N = 0x2D (macOS Carbon HIToolbox)
_KEY_CODE_N: int = 0x2D

# Quartz modifier flags(沿 Quartz.CoreGraphics)
_KC_MOD_ALT: int = Quartz.kCGEventFlagMaskAlternate
_KC_MOD_CMD: int = Quartz.kCGEventFlagMaskCommand

# Queue[Any] 事件 schema(主进程据此分发,B-5 沿用 D9.5 三类事件)
_EVENT_HOTKEY: str = "hotkey"
_EVENT_TCC_DENIED: str = "tcc_denied"
_EVENT_LISTENER_STARTED: str = "listener_started"


# ===== 子进程主体 =====


class HotkeyListenerProcess(_mp.Process):
    """⌥⌘N 全局快捷键监听子进程(v0.2 B-5:Quartz CGEvent tap).

    Attributes:
        queue: multiprocessing.Queue[Any],主进程创建的 Queue[Any] 实例(子进程推事件用)

    Lifecycle:
        1. 主进程: queue = multiprocessing.Queue()
                   proc = HotkeyListenerProcess(queue); proc.start()
        2. 子进程: Quartz.CGEventTapCreate 注册全局事件 tap
                   tap None → 推 tcc_denied(reason="辅助功能未授权")
                   tap 非 None → CFRunLoopAddSource + CGEventTapEnable + CFRunLoopRun
        3. 主进程: 轮询 queue.get(timeout=1.0) 收事件
        4. 退出: daemon=True,主进程退出自动 kill(无需手动 join)
    """

    def __init__(self, queue: _mp.Queue[Any]) -> None:
        """初始化子进程(严判 queue 必非 None,沿 D4.7.3 v1.0.5 P1:type 严判).

        Args:
            queue: 主进程创建的 Queue[Any] 实例

        Raises:
            ValueError: queue 为 None
        """
        # 严判 queue(沿 D4.7.3 v1.0.5 P1:type 严判)
        if queue is None:
            raise ValueError("queue 必传非 None(主进程需 Queue[Any] 收事件)")
        super().__init__(daemon=True, name="notes-hotkey-listener")
        self._queue: _mp.Queue[Any] = queue

    def run(self) -> None:
        """子进程主体(被 start() 自动调).

        流程:
            1. Quartz.CGEventTapCreate 注册全局事件 tap
            2. tap None → 推 tcc_denied(reason="辅助功能未授权")
            3. tap 非 None → CFRunLoopAddSource + CGEventTapEnable + CFRunLoopRun
            4. 异常收容:任何 Quartz 异常 → 推 tcc_denied + reason 后退出
        """
        try:
            self._emit_listener_started()

            # Quartz C 回调函数(签名固定:(proxy, type, event, refcon) -> CGEvent)
            # 仅判 ⌥⌘N 组合(Alt + Cmd + N 按下) → 推 hotkey
            # 其他事件透传返回 event(沿 Quartz 文档)
            def _callback(proxy: Any, event_type: int, event: Any, refcon: Any) -> Any:
                if event_type != Quartz.kCGEventKeyDown:
                    return event
                flags = Quartz.CGEventGetFlags(event)
                keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                if keycode == _KEY_CODE_N and (flags & _KC_MOD_ALT) and (flags & _KC_MOD_CMD):
                    self._emit_hotkey()
                return event

            # 注册全局事件 tap(沿 Quartz 文档)
            tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,  # 会话级 tap(全系统范围)
                Quartz.kCGHeadInsertEventTap,  # 在事件流头部插入
                Quartz.kCGEventTapOptionDefault,  # 主动监听(可过滤)
                Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),  # 只监听键盘按下
                _callback,
                None,
            )
            if tap is None:
                # CGEvent.tapCreate 返回 None = 辅助功能未授权(沿 macOS TCC 范本)
                self._emit_tcc_denied(reason="Quartz CGEvent.tapCreate 返回 None(辅助功能未授权)")
                return

            # 把 tap 接入 CFRunLoop 主循环(子进程内)
            loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            Quartz.CFRunLoopAddSource(
                Quartz.CFRunLoopGetCurrent(),
                loop_source,
                Quartz.kCFRunLoopCommonModes,
            )
            Quartz.CGEventTapEnable(tap, True)  # 启用 tap
            Quartz.CFRunLoopRun()  # 阻塞直到 CFRunLoopStop / 子进程被 kill
        except Exception as e:  # noqa: BLE001 — Quartz 内部异常需全收
            # 包含:辅助功能未授权 / tap 启动失败 / CFRunLoop 异常 / 任何 Quartz 错误
            self._emit_tcc_denied(reason=f"Quartz listener 启动失败: {e}")

    def _on_hotkey(self) -> None:
        """⌥⌘N 按下时触发(Quartz 回调内部调)."""
        self._emit_hotkey()

    # ===== Queue[Any] emit helpers(严判 type 严判,沿 D4.7.3 范本)=====

    def _emit_hotkey(self) -> None:
        """推 ⌥⌘N hotkey 事件."""
        self._queue.put({"event": _EVENT_HOTKEY, "combo": _HOTKEY_COMBO})

    def _emit_tcc_denied(self, *, reason: str) -> None:
        """推 TCC 拒授权事件(主进程弹 notification 引导授权)."""
        if not reason or not reason.strip():
            raise ValueError("reason 必填非空白字符串")
        self._queue.put({"event": _EVENT_TCC_DENIED, "reason": reason})

    def _emit_listener_started(self) -> None:
        """推 listener 启动成功事件(主进程可据此判定子进程就绪)."""
        self._queue.put({"event": _EVENT_LISTENER_STARTED})


# ===== 公开 API(主进程用的事件消费辅助)=====


def build_event_dict(event_type: str, **fields: Any) -> dict[str, Any]:
    """构造事件 dict[Any, Any](供主进程消费 / 测试用).

    Args:
        event_type: 事件类型(_EVENT_HOTKEY / _EVENT_TCC_DENIED /
                    _EVENT_LISTENER_STARTED 三类之一)
        **fields: 额外字段(reason / combo 等)

    Returns:
        dict[str, Any] — 推到 Queue[Any] 的事件 payload

    Raises:
        ValueError: event_type 非法(非 3 类之一)
    """
    valid_events = {_EVENT_HOTKEY, _EVENT_TCC_DENIED, _EVENT_LISTENER_STARTED}
    if event_type not in valid_events:
        raise ValueError(f"event_type 必 ∈ {sorted(valid_events)}, 实际 {event_type!r}")
    return {"event": event_type, **fields}


__all__ = [
    "HotkeyListenerProcess",
    "build_event_dict",
]
