"""D9.3+D9.5 — NotesMenuBarApp(rumps 菜单栏 UI + ⌥⌘N 全局快捷键).

承接 docs/v0.1-launch-plan.md §D9.3 + §D9.5:
    - 菜单栏常驻图标(📝 Notes (N),N = 总笔记数)
    - 4 菜单项:
        1. "立即同步"   → subprocess 调 scripts/sync_notes.py sync
        2. "打开 Notes" → 打开 Apple Notes.app
        3. "授权引导"   → 打开 系统设置→隐私与安全性→自动化
        4. "退出"       → 退出 menu bar
    - ExpenseService 状态展示(title 数字 + 子菜单"最近笔记" + 剪贴板/TCC 状态)
    - ⌥⌘N 全局快捷键(D9.5 双进程范本):
        * 子进程 HotkeyListenerProcess 跑 pynput.keyboard.GlobalHotKeys
        * 主进程 _poll_hotkey_queue 轮询 Queue 收事件
        * pynput 拒授权 → 弹 notification 引导 TCC 授权

设计决策(2026-06-15 锁定):
    - rumps 主进程跑 NSApp 主循环
    - ExpenseService 依赖注入(默认 ExpenseServiceStub,D10 替换)
    - 子进程调 sync_notes.py(沿 D5 业务调度范本,不 in-process 调)
    - macOS TCC 风险:同步/打开 Notes 需"自动化"授权,失败时弹 rumps.notification
    - 双进程范本:rumps NSApp + pynput 子进程,Queue 通信(沿 D4.7.3 v1.0.5)
    - 测试用 monkeypatch 隔离 NSApp 拉起(rumps.App 替换为 fake class)
    - 测试用 monkeypatch 隔离子进程 start(沿 D5 业务调度范本)

D4.7.3 教训应用:
    - subprocess.run 严格 4 退出码契约(沿 C1 sync_notes.py)
    - 异常类型统一 (RuntimeError 透传,不静默)
    - 私有属性 _ 前缀(避免与 rumps 公共 API 冲突)
    - 跨进程通信用 multiprocessing.Queue(不 pickle 自定义对象,沿 D5)
"""

from __future__ import annotations

import multiprocessing as _mp
import queue as _queue
import subprocess
import sys
import threading as _threading
from typing import Any

import rumps as _rumps

from my_ai_employee.menu_bar.clipboard_listener import (
    _EVENT_HOTKEY,
    _EVENT_TCC_DENIED,
    HotkeyListenerProcess,
)
from my_ai_employee.menu_bar.expense_service import (
    ExpenseService,
    ExpenseServiceStub,
)
from my_ai_employee.menu_bar.tcc import TCCPermissionError

# rumps.App 基类提取为模块级变量(测试可 monkeypatch 替换,避免 NSApp 拉起)
# Python 类继承在 class 定义时解析基类,直接 `class X(rumps.App):` 不可 mock
# 改用 `class X(_RumpsAppBase):` 让 test 替换 _RumpsAppBase 即可
_RumpsAppBase: type = _rumps.App
_clicked_decorator = _rumps.clicked
_notification_func = _rumps.notification

# 菜单栏同步脚本相对路径(沿 scripts/ 目录范本)
_SYNC_SCRIPT_MODULE: str = "my_ai_employee.scripts.sync_notes"
_SYNC_TIMEOUT_SECONDS: int = 120

# macOS 隐私与安全性 URL scheme(打开 系统设置→自动化 授权)
_PRIVACY_URL: str = "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"

# 菜单栏 title 模板
_TITLE_TEMPLATE: str = "📝 Notes ({count})"

# ExpenseService 5 方法签名(注入校验用,沿 D4.7.3 公共常量范本)
_EXPENSE_SERVICE_METHODS: tuple[str, ...] = (
    "get_total_notes_count",
    "get_unsynced_count",
    "get_recent_note_titles",
    "is_clipboard_listener_running",
    "get_tcc_authorization_status",
)


def _validate_expense_service(obj: object) -> None:
    """严判 obj 满足 ExpenseService 接口(5 方法齐全).

    Args:
        obj: 任意对象(None / ExpenseServiceStub 实例 / duck-typed 实现)

    Raises:
        TypeError: obj 非 None 也非 ExpenseServiceStub,且缺任一方法
    """
    if obj is None or isinstance(obj, ExpenseServiceStub):
        return
    if not all(hasattr(obj, m) for m in _EXPENSE_SERVICE_METHODS):
        raise TypeError(
            f"expense_service 必须实现 ExpenseService 5 方法接口,实际 type={type(obj).__name__}"
        )


class NotesMenuBarApp(_RumpsAppBase):
    """Apple Notes 菜单栏 App(D9.3 — 沿 D10 留 ExpenseService 注入点).

    Attributes:
        expense_service: 状态服务接口(默认 ExpenseServiceStub)
                         D10 替换为 ExpenseServiceImpl(真实 DB 接入)

    Menu items:
        1. "立即同步" — subprocess 调 sync_notes.py sync,4 退出码契约
        2. "打开 Notes" — `open -a Notes` 打开 Apple Notes.app
        3. "授权引导" — 打开 系统设置→自动化,引导用户授权
        4. "退出" — 退出 menu bar
    """

    def __init__(
        self,
        *,
        expense_service: ExpenseService | None = None,
    ) -> None:
        """初始化菜单栏 App.

        Args:
            expense_service: 状态服务接口,None 时使用 ExpenseServiceStub 默认单例
        """
        # 严判 expense_service(沿 D4.7.3 公共 helper 范本,避免嵌套 if)
        _validate_expense_service(expense_service)

        # 状态先记下,super().__init__() 之前不能调任何 rumps 回调
        self._service: ExpenseService = expense_service or ExpenseServiceStub.get_default_stub()
        self._notes_count: int = self._service.get_total_notes_count()

        # ⌥⌘N 全局快捷键子进程(D9.5 双进程范本)
        # Queue 必须在子进程 start 之前创建(子进程会推到这)
        self._hotkey_queue: _mp.Queue = _mp.Queue()
        self._hotkey_proc: HotkeyListenerProcess | None = None
        # 轮询 thread 守护标记(测试可显式停掉)
        self._stop_hotkey_poll: _threading.Event = _threading.Event()

        # 调 rumps.App.__init__ 启动 NSApp 主循环
        super().__init__("Notes", title=self._format_title(self._notes_count))

        # 注册 5 菜单项(rumps 范本:list[str] 形式注册)
        self.menu: list[Any] = [
            "立即同步",
            "打开 Notes",
            "授权引导",
            None,  # 分隔符
            "退出",
        ]

        # 启动子进程 + 轮询 thread(放最末,即便失败也不影响主进程 NSApp)
        self._start_hotkey_listener()

    def _format_title(self, count: int) -> str:
        """格式化菜单栏 title(数字 → 表情 + 数字).

        Args:
            count: 总笔记数

        Returns:
            "📝 Notes (N)" 格式字符串
        """
        return _TITLE_TEMPLATE.format(count=count)

    def _refresh_title(self) -> None:
        """刷新菜单栏 title(同步后调,沿 D5 范本)."""
        self._notes_count = self._service.get_total_notes_count()
        self.title = self._format_title(self._notes_count)

    @_clicked_decorator("立即同步")
    def _on_sync_now(self, _sender: Any) -> None:
        """点击"立即同步" — subprocess 调 sync_notes.py sync(4 退出码契约).

        Returns:
            None(结果通过 menu title 刷新 / rumps.notification 反馈)
        """
        result = subprocess.run(  # noqa: S603 — 同步场景必传 list,eval 风险为零
            [sys.executable, "-m", _SYNC_SCRIPT_MODULE, "sync"],
            capture_output=True,
            text=True,
            timeout=_SYNC_TIMEOUT_SECONDS,
        )
        if result.returncode == 0:
            self._refresh_title()
        else:
            _notification_func(
                "Notes 同步失败",
                "",
                (result.stderr or "未知错误")[:200],
            )

    @_clicked_decorator("打开 Notes")
    def _on_open_notes(self, _sender: Any) -> None:
        """点击"打开 Notes" — `open -a Notes` 启动 Apple Notes.app."""
        subprocess.run(  # noqa: S603
            ["open", "-a", "Notes"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    @_clicked_decorator("授权引导")
    def _on_open_privacy(self, _sender: Any) -> None:
        """点击"授权引导" — 打开 系统设置→自动化 引导用户授权."""
        subprocess.run(  # noqa: S603
            ["open", _PRIVACY_URL],
            capture_output=True,
            text=True,
            timeout=10,
        )

    # ===== D9.5 ⌥⌘N 全局快捷键(双进程范本主入口)=====

    def _start_hotkey_listener(self) -> None:
        """启动 ⌥⌘N 监听子进程 + Queue 轮询 thread.

        异常收容(沿 D4.7.3 v1.0.5 P3):
            - 子进程 start 失败(多进程资源不足) → 静默(主进程仍可同步)
            - pynput TCC 拒授权 → 子进程推 Queue,主进程弹 notification
        """
        try:
            self._hotkey_proc = HotkeyListenerProcess(self._hotkey_queue)
            self._hotkey_proc.start()
        except (OSError, ValueError, TCCPermissionError) as e:
            _notification_func(
                "Notes 快捷键子进程启动失败",
                "",
                f"{type(e).__name__}: {str(e)[:200]}",
            )
            return
        # 启动轮询 thread(daemon=True,主进程退出自动停)
        _threading.Thread(
            target=self._poll_hotkey_queue,
            daemon=True,
            name="hotkey-poll",
        ).start()

    def _poll_hotkey_queue(self) -> None:
        """轮询 Queue 收子进程事件(沿 D5 业务调度范本).

        事件类型:
            - hotkey       → ⌥⌘N 按下 → 调 _on_clipboard_capture()
            - tcc_denied   → pynput 拒授权 → 弹 notification 引导授权
        """
        while not self._stop_hotkey_poll.is_set():
            try:
                event: dict[str, Any] = self._hotkey_queue.get(timeout=1.0)
            except _queue.Empty:
                continue
            except (EOFError, OSError):
                # 子进程已死或 Queue 关闭 → 退出轮询
                return
            event_type = event.get("event")
            if event_type == _EVENT_HOTKEY:
                self._on_clipboard_capture()
            elif event_type == _EVENT_TCC_DENIED:
                _notification_func(
                    "⌥⌘N 快捷键未授权",
                    "请到 系统设置 → 隐私与安全性 → 辅助功能 授权",
                    str(event.get("reason", ""))[:200],
                )

    def _on_clipboard_capture(self) -> None:
        """⌥⌘N 触发后处理(本步先弹 notification 占位,S7 e2e 实化消费).

        后续(D10 / C5)会替换为:
            1. 读 pyperclip.paste()
            2. 调 NoteStructurerService.structure_and_emit(clip_id)
            3. 写 NoteStore.insert(...)
        本轮仅占位,弹 notification 让用户知道快捷键响应了。
        """
        _notification_func(
            "⌥⌘N 触发",
            "剪贴板内容即将结构化入 Notes",
            "D9.5 链路验证通过(S7 e2e 待 C5 实化消费)",
        )


__all__ = ["NotesMenuBarApp"]
