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

from my_ai_employee.ai.note_structurer import (
    FailureDecisionReport,
    PrivateSkipDecisionReport,
)
from my_ai_employee.menu_bar.clipboard_capture import (
    ClipboardCaptureService,
)
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


def _build_default_capture_service() -> ClipboardCaptureService:
    """构造默认 ClipboardCaptureService(沿 D4.7.3 v1.0.6 default_singleton 范本).

    生产 NotesMenuBarApp() 无 capture_service 注入时,自动用 NoteStore + NoteStructurerService
    默认实例建一个。注意: NoteStore + NoteStructurerService 的默认构造会触发 DB session
    初始化,生产环境允许(启动菜单栏时本就要连 DB),test fixture 必须显式注入 capture_service
    或 monkeypatch _build_default_capture_service 避免 DB / LLM 副作用。

    Returns:
        ClipboardCaptureService: 默认实例(store + structurer 默认)
    """
    from sqlalchemy.orm import sessionmaker

    from my_ai_employee.ai.note_structurer import NoteStructurerService
    from my_ai_employee.ai.router import get_router
    from my_ai_employee.core.db import Database
    from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine
    from my_ai_employee.db.notes import NoteStore

    db = Database.open()
    engine = make_sqlalchemy_engine(db)
    sf = sessionmaker(bind=engine, expire_on_commit=False)
    store = NoteStore(sf)
    structurer = NoteStructurerService(store=store, llm_provider=get_router())
    return ClipboardCaptureService(store=store, structurer=structurer)


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
        capture_service: ClipboardCaptureService | None = None,
    ) -> None:
        """初始化菜单栏 App.

        Args:
            expense_service: 状态服务接口,None 时使用 ExpenseServiceStub 默认单例
            capture_service: 剪贴板捕获服务(D9.6.1 沿 D4.7.3 v1.0.6 注入,None 时
                              用 _build_default_capture_service 懒构造,test fixture
                              必须显式注入以避免真读剪贴板 / 连 DB)
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

        # 剪贴板捕获服务(D9.6.1 沿 D4.7.3 v1.0.6 注入 + 懒构造)
        # 显式 None = 用 default;显式非 None = 用注入值
        self._capture_service: ClipboardCaptureService | None = capture_service
        self._capture_service_built: bool = capture_service is not None

        # 调 rumps.App.__init__ 启动 NSApp 主循环
        super().__init__("Notes", title=self._format_title(self._notes_count))

        # 注册 6 菜单项(rumps 范本:list[str] 形式注册,D8.3 加"⚠️ 异常告警")
        self.menu: list[Any] = [
            "立即同步",
            "打开 Notes",
            "⚠️ 异常告警 (0)",
            "授权引导",
            None,  # 分隔符
            "退出",
        ]

        # 启动子进程 + 轮询 thread(放最末,即便失败也不影响主进程 NSApp)
        self._start_hotkey_listener()

    @property
    def capture_service(self) -> ClipboardCaptureService:
        """懒构造剪贴板捕获服务(沿 D4.7.3 v1.0.6 default_singleton 范本).

        首次访问时才连 DB + 构 NoteStructurerService(避免 __init__ 副作用)。

        Returns:
            ClipboardCaptureService: 显式注入的实例,或 _build_default_capture_service() 默认实例
        """
        if not self._capture_service_built:
            self._capture_service = _build_default_capture_service()
            self._capture_service_built = True
        assert self._capture_service is not None  # 严判编译期
        return self._capture_service

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

    # ===== D8.3 异常告警菜单项(不弹通知,用户主动查询)=====

    @_clicked_decorator("⚠️ 异常告警")
    def _on_anomaly_alert(self, _sender: Any) -> None:
        """点击"⚠️ 异常告警" — 弹窗显示本月异常列表(D8.3 接入 RuleBasedAnomalyDetector).

        设计决策(沿 D8 docs 评估决策 #5):
            - 用户主动查询 vs 被动打扰(只接入"已确认"异常不弹每笔)
            - Stub 阶段:返回空 list,弹窗提示"暂无异常"
            - D10 后:替换为真实 ExpenseServiceImpl,接 AnomalyDetector 真实链路
        """
        try:
            anomalies = self._service.get_recent_anomalies(limit=10)
        except Exception as e:  # noqa: BLE001 — Stub 异常不能让菜单崩
            _notification_func(
                "⚠️ 异常告警",
                "获取异常列表失败",
                f"{type(e).__name__}: {str(e)[:100]}",
            )
            return
        if not anomalies:
            _notification_func(
                "⚠️ 异常告警",
                "暂无异常",
                "本月无金额 / 频率 / 重复扣款 / 商家画像漂移异常",
            )
            return
        body = "\n".join(
            f"• {a.get('date', '?')} | {a.get('counterparty', '?')} | "
            f"¥{a.get('amount', '?')} | {a.get('kinds', '?')}"
            for a in anomalies
        )
        _notification_func(
            f"⚠️ 异常告警 ({len(anomalies)} 笔)",
            "本月检测到以下异常:",
            body[:200],
        )

    def _refresh_anomaly_count(self) -> None:
        """刷新异常告警菜单项 badge (D8.3 stub 阶段 0, D10 后真实计数)."""
        try:
            count = self._service.get_anomaly_count()
        except Exception:  # noqa: BLE001 — 静默降级,不影响主流程
            return
        # 找到异常告警菜单项更新 title
        for item in self.menu:
            title = getattr(item, "title", None)
            if isinstance(title, str) and title.startswith("⚠️ 异常告警"):
                item.title = f"⚠️ 异常告警 ({count})"

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
        """⌥⌘N 触发后处理(D9.6.1 — ClipboardCaptureService 真链路接入).

        业务流程(沿 D9.6.1 + D4.7.3 v1.0.6 范本):
          1. 调 self.capture_service.capture_and_emit() 读剪贴板 + 落 NoteStore + 走 LLM
             (capture_service 是 lazy property,首次访问时才连 DB)
          2. isinstance 区分 3 类决策报告 → 弹不同 notification
        """
        result = self.capture_service.capture_and_emit()
        if isinstance(result, PrivateSkipDecisionReport):
            _notification_func(
                "⌥⌘N 业务阻断",
                "私人笔记已跳过 LLM",
                result.apple_note_id[:40],
            )
        elif isinstance(result, FailureDecisionReport):
            _notification_func(
                "⌥⌘N 失败",
                f"reason={result.reason}",
                str(result.last_error)[:100],
            )
        else:
            # StructuredNote 成功
            _notification_func(
                "⌥⌘N 入库成功",
                f"category={result.category}",
                f"tags={len(result.tags)}",
            )


__all__ = ["NotesMenuBarApp"]
