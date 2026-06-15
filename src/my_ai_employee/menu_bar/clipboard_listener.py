"""D9.5 — ⌥⌘N 全局快捷键监听子进程(双进程范本 + pynput + TCC 引导).

承接 docs/v0.1-launch-plan.md §D9.5 + plan §4 C4 决策 5:
    - HotkeyListenerProcess: multiprocessing.Process 子类,跑
      pynput.keyboard.GlobalHotKeys({"<alt>+<cmd>+n": _on_hotkey})
    - 通过 multiprocessing.Queue 把快捷键事件送到主进程(rumps 菜单栏回调)
    - TCC 拒授权(无 辅助功能 权限) → pynput 启动失败 → 推
      {"event": "tcc_denied"} 让主进程弹 rumps.notification 引导授权

设计要点(2026-06-15 锁定):
    - 双进程范本(沿 D4.7.3 v1.0.5 范本): rumps 主进程跑 NSApp 主循环 →
      本子进程跑 pynput listener → Queue 通信
    - 延迟 import pynput(子进程内 try: from pynput import keyboard,失败 raise
      TCCPermissionError 推 Queue)
    - daemon=True(主进程退出自动 kill 子进程,沿 D5 业务调度范本)
    - 异常收容:pynput 启动失败 / listener.join() 抛异常 → 推
      {"event": "tcc_denied"} 后退出(不静默吞,沿 D4.7.3 v1.0.5 P3)
    - emit_hotkey() 入口段:严判 queue 必非 None(沿 D4.7.3 范本)

不做:
    - 不在子进程内调 NoteStore(本步只 emit 事件,主进程决定怎么消费,沿
      D4.7.3 EmailDrafterAdapter 3 入口分离范本)
    - 不监听多组快捷键(本步只 ⌥⌘N,D10 扩多组)
    - 不写文件不调网络(子进程崩溃不污染主进程)
"""

from __future__ import annotations

import multiprocessing as _mp
from typing import Any

# ===== 全局快捷键组合(沿 v0.1-launch-plan.md:129 锁定)=====

_HOTKEY_COMBO: str = "<alt>+<cmd>+n"

# Queue 事件 schema(主进程据此分发)
_EVENT_HOTKEY: str = "hotkey"
_EVENT_TCC_DENIED: str = "tcc_denied"
_EVENT_LISTENER_STARTED: str = "listener_started"


# ===== 子进程主体 =====


class HotkeyListenerProcess(_mp.Process):
    """⌥⌘N 全局快捷键监听子进程(双进程范本主入口).

    Attributes:
        queue: multiprocessing.Queue,主进程创建的 Queue 实例(子进程推事件用)

    Lifecycle:
        1. 主进程: queue = multiprocessing.Queue()
                   proc = HotkeyListenerProcess(queue); proc.start()
        2. 子进程: try: from pynput import keyboard  # 延迟 import
                   if ImportError: queue.put({"event": "tcc_denied", ...}); return
                   with keyboard.GlobalHotKeys({hotkey: _on_hotkey}) as l:
                       queue.put({"event": "listener_started"}); l.join()
        3. 主进程: 轮询 queue.get(timeout=1.0) 收事件
        4. 退出: daemon=True,主进程退出自动 kill(无需手动 join)
    """

    def __init__(self, queue: _mp.Queue) -> None:
        """初始化子进程(严判 queue 必非 None,沿 D4.7.3 范本).

        Args:
            queue: 主进程创建的 Queue 实例

        Raises:
            ValueError: queue 为 None
        """
        # 严判 queue(沿 D4.7.3 v1.0.5 P1:type 严判)
        if queue is None:
            raise ValueError("queue 必传非 None(主进程需 Queue 收事件)")
        super().__init__(daemon=True, name="notes-hotkey-listener")
        self._queue: _mp.Queue = queue

    def run(self) -> None:
        """子进程主体(被 start() 自动调).

        流程:
            1. 延迟 import pynput,失败 → 推 tcc_denied 后退出
            2. 注册 ⌥⌘N hotkey,推 listener_started + 阻塞 join
            3. 异常收容:任何 pynput 异常 → 推 tcc_denied + reason 后退出
        """
        # 1. 延迟 import pynput(子进程隔离,失败不污染主进程)
        try:
            from pynput import keyboard  # type: ignore[import-not-found]  # noqa: PLC0415
        except ImportError as e:
            self._emit_tcc_denied(reason=f"pynput import 失败: {e}")
            return

        # 2. 注册 hotkey + 推 started 事件
        try:
            self._emit_listener_started()
            with keyboard.GlobalHotKeys({_HOTKEY_COMBO: self._on_hotkey}) as listener:
                listener.join()
        except Exception as e:  # noqa: BLE001 — pynput 内部异常需全收
            # 包含:辅助功能未授权 / 监听器启动失败 / 任何 pynput 内部错误
            self._emit_tcc_denied(reason=f"pynput listener 启动失败: {e}")

    def _on_hotkey(self) -> None:
        """⌥⌘N 按下时触发(推 hotkey 事件到主进程 Queue).

        pynput.GlobalHotKeys 回调签名固定为 0 参数,返回 None。
        """
        self._emit_hotkey()

    # ===== Queue emit helpers(严判 type 严判,沿 D4.7.3 范本)=====

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
    """构造事件 dict(供主进程消费 / 测试用).

    Args:
        event_type: 事件类型(_EVENT_HOTKEY / _EVENT_TCC_DENIED /
                    _EVENT_LISTENER_STARTED 三类之一)
        **fields: 额外字段(reason / combo 等)

    Returns:
        dict[str, Any] — 推到 Queue 的事件 payload

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
