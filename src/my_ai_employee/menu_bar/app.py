"""D9.3+D9.5 — NotesMenuBarApp(rumps 菜单栏 UI + ⌥⌘N 全局快捷键).

承接 docs/v0.1-launch-plan.md §D9.3 + §D9.5 + v0.2.53 P1 Codex 信息架构:
    - 菜单栏 title: 🧑‍💼 我的AI员工 (N),N = 今日待处理合计(邮件草稿 + Notes待确认 + 财务异常)
    - P1 菜单结构(沿 docs/v0.2.53-codex-style-ui-design-2026-06-25.md §8.2):
        今日待处理 / 邮件草稿 / Notes待确认 / 财务异常 / 快捷捕获 / 打开工作台 / 系统健康
    - 保留 D9.3 能力项: 立即同步 / 打开 Notes / 授权引导 / 退出 / 📥 确认第 1 条
    - ExpenseService 状态展示(title 数字 + 子菜单"最近笔记" + 剪贴板/TCC 状态)
    - ⌥⌘N 全局快捷键(D9.5 双进程范本):
        * 子进程 HotkeyListenerProcess 跑 pynput.keyboard.GlobalHotKeys
        * 主进程 _poll_hotkey_queue 轮询 Queue[Any] 收事件
        * pynput 拒授权 → 弹 notification 引导 TCC 授权

设计决策(2026-06-15 锁定):
    - rumps 主进程跑 NSApp 主循环
    - ExpenseService 依赖注入(默认 ExpenseServiceStub,D10 替换)
    - 子进程调 sync_notes.py(沿 D5 业务调度范本,不 in-process 调)
    - macOS TCC 风险:同步/打开 Notes 需"自动化"授权,失败时弹 rumps.notification
    - 双进程范本:rumps NSApp + pynput 子进程,Queue[Any] 通信(沿 D4.7.3 v1.0.5)
    - 测试用 monkeypatch 隔离 NSApp 拉起(rumps.App 替换为 fake class)
    - 测试用 monkeypatch 隔离子进程 start(沿 D5 业务调度范本)

D4.7.3 教训应用:
    - subprocess.run 严格 4 退出码契约(沿 C1 sync_notes.py)
    - 异常类型统一 (RuntimeError 透传,不静默)
    - 私有属性 _ 前缀(避免与 rumps 公共 API 冲突)
    - 跨进程通信用 multiprocessing.Queue[Any](不 pickle 自定义对象,沿 D5)
"""

from __future__ import annotations

import contextlib
import multiprocessing as _mp
import queue as _queue
import subprocess
import sys
import threading as _threading
from pathlib import Path
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
from my_ai_employee.menu_bar.note_confirm_service import (
    NoteConfirmService,
    NoteConfirmServiceStub,
)
from my_ai_employee.menu_bar.outbox_draft_service import (
    OutboxDraftService,
    OutboxDraftServiceStub,
)
from my_ai_employee.menu_bar.tcc import TCCPermissionError
from my_ai_employee.quality_snapshot import format_system_health_body

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

# 菜单栏 title 模板(v0.2.53 P1: 今日待处理合计)
_TITLE_TEMPLATE: str = "🧑‍💼 我的AI员工 ({count})"

# P1 菜单 badge 前缀(沿 _update_menu_badge 范本,decorator 绑前缀不含计数)
_MENU_TODAY_PENDING: str = "📋 今日待处理"
_MENU_MAIL_DRAFT: str = "  ✉️ 邮件草稿"
_MENU_NOTES_CONFIRM: str = "  📝 Notes待确认"
_MENU_FINANCE_ANOMALY: str = "  💰 财务异常"

# P0 静态工作台 HTML(只 open 本地文件,不接真实 DB)
_DASHBOARD_HTML: Path = (
    Path(__file__).resolve().parents[3] / "docs" / "ui" / "codex-style-dashboard.html"
)

# v0.2.2 启动候选 #6 — badge 实时刷新轮询间隔(秒)
# 沿 D5 业务调度 polling 范本(30s 平衡响应速度与性能)
# 0 = 禁用 polling(测试可显式设 0 关闭)
_DEFAULT_BADGE_POLL_INTERVAL_SECONDS: float = 30.0
_BADGE_POLL_SLEEP_GRANULARITY_SECONDS: float = 1.0

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


# NoteConfirmService 3 方法签名(注入校验用,沿 v0.2.2 候选 #2 范本)
_NOTE_CONFIRM_SERVICE_METHODS: tuple[str, ...] = (
    "get_pending_confirm_count",
    "list_pending_confirm",
    "confirm_note",
)

_OUTBOX_DRAFT_SERVICE_METHODS: tuple[str, ...] = (
    "get_pending_draft_count",
    "list_pending_drafts",
)


def _validate_outbox_draft_service(obj: object) -> None:
    """严判 obj 满足 OutboxDraftService 接口(1 方法)."""
    if obj is None or isinstance(obj, OutboxDraftServiceStub):
        return
    if not all(hasattr(obj, m) for m in _OUTBOX_DRAFT_SERVICE_METHODS):
        raise TypeError(
            f"outbox_draft_service 必须实现 OutboxDraftService 2 方法接口,"
            f" 实际 type={type(obj).__name__}"
        )


def _validate_note_confirm_service(obj: object) -> None:
    """严判 obj 满足 NoteConfirmService 接口(3 方法齐全).

    Args:
        obj: 任意对象(None / NoteConfirmServiceStub 实例 / duck-typed 实现)

    Raises:
        TypeError: obj 非 None 也非 NoteConfirmServiceStub,且缺任一方法
    """
    if obj is None or isinstance(obj, NoteConfirmServiceStub):
        return
    if not all(hasattr(obj, m) for m in _NOTE_CONFIRM_SERVICE_METHODS):
        raise TypeError(
            f"note_confirm_service 必须实现 NoteConfirmService 3 方法接口,"
            f" 实际 type={type(obj).__name__}"
        )


def _update_menu_badge(menu: Any, prefix: str, new_title: str) -> None:
    """更新菜单栏 badge — 支持 list[Any] 和 rumps.Menu 2 种形态(沿 v0.2.2 #2 范本).

    设计决策(2026-06-17 锁定):
        - rumps.Menu 内部是 OrderedDict[str, MenuItem],iter 出来是 str(title),
          menu.items() 返回 (str, MenuItem) tuple 对
        - 形态 1: list[str] (test fake_rumps 环境) — 直接 menu[idx] = new_title
        - 形态 2: rumps.Menu (真实 NSApp 环境) — 改 menu_item.title
          (OrderedDict key 保持不变, NSMenu 自动同步)

    Args:
        menu: self.menu 对象(list[Any] 或 rumps.Menu)
        prefix: 旧 title 前缀(用于匹配)
        new_title: 新 title(完整字符串,非前缀)
    """
    # 形态 1: 普通 list[str](test fake_rumps 环境)
    if isinstance(menu, list):
        for idx, item in enumerate(menu):
            if isinstance(item, str) and item.startswith(prefix):
                menu[idx] = new_title
        return
    # 形态 2: rumps.Menu(真实 NSApp 环境)— 内部 OrderedDict
    # menu.items() 返回 (str_title, MenuItem) tuple 对(沿 OrderedDict API)
    try:
        items_method = getattr(menu, "items", None)
        if not callable(items_method):
            return
        for title, menu_item in items_method():
            if isinstance(title, str) and title.startswith(prefix) and hasattr(menu_item, "title"):
                menu_item.title = new_title
    except (TypeError, AttributeError):
        # 防御性 fallback: 啥都不做(避免崩菜单栏)
        pass


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

    # hotkey-poll 是独立线程。先只取路径并关闭这条启动连接，再由 db_path
    # 构造 NullPool engine，让每次 session 在当前线程新建/关闭 SQLCipher 连接。
    # 不能传入单个 Database：默认 SingletonThreadPool 会复用它的 connection，
    # 在热键线程触发 #97 的 check_same_thread ProgrammingError。
    with Database.open() as db:
        db_path = db.db_path
    engine = make_sqlalchemy_engine(db_path=db_path)
    sf = sessionmaker[Any](bind=engine, expire_on_commit=False)
    store = NoteStore(sf)
    structurer = NoteStructurerService(store=store, llm_provider=get_router())
    return ClipboardCaptureService(store=store, structurer=structurer)


class NotesMenuBarApp(_RumpsAppBase):  # type: ignore[misc]
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
        note_confirm_service: NoteConfirmService | None = None,
        outbox_draft_service: OutboxDraftService | None = None,
        badge_poll_interval_seconds: float = _DEFAULT_BADGE_POLL_INTERVAL_SECONDS,
    ) -> None:
        """初始化菜单栏 App.

        Args:
            expense_service: 状态服务接口,None 时使用 ExpenseServiceStub 默认单例
            capture_service: 剪贴板捕获服务(D9.6.1 沿 D4.7.3 v1.0.6 注入,None 时
                              用 _build_default_capture_service 懒构造,test fixture
                              必须显式注入以避免真读剪贴板 / 连 DB)
            note_confirm_service: 1-click 确认服务(v0.2.2 候选 #2 接入,None 时用
                              NoteConfirmServiceStub 默认单例)
            outbox_draft_service: outbox 草稿待审批计数(v0.2.53 P1,None 时用 Stub)
            badge_poll_interval_seconds: 实时刷新 badge 间隔(秒,v0.2.2 启动候选 #6 接入,
                              默认 30.0;0 = 禁用 polling,test fixture 设 0.1s 加快测试)
        """
        # 严判 expense_service(沿 D4.7.3 公共 helper 范本,避免嵌套 if)
        _validate_expense_service(expense_service)
        # 严判 note_confirm_service(沿 v0.2.2 候选 #2 范本)
        _validate_note_confirm_service(note_confirm_service)
        _validate_outbox_draft_service(outbox_draft_service)
        # 严判 badge_poll_interval_seconds(v0.2.2 启动候选 #6 沿 D4.7.3 v1.0.5 type 严判范本)
        if (
            type(badge_poll_interval_seconds) is bool
            or not isinstance(badge_poll_interval_seconds, (int, float))
            or badge_poll_interval_seconds < 0
        ):
            raise ValueError(
                f"badge_poll_interval_seconds 必须是 >= 0 的 int/float(非 bool),"
                f" 实际 type={type(badge_poll_interval_seconds).__name__},"
                f" value={badge_poll_interval_seconds!r}"
            )
        # 严判 __init__ 范围(沿 D4.7.3 v1.0.5 范围约定)
        if badge_poll_interval_seconds > 3600:
            raise ValueError(
                f"badge_poll_interval_seconds 必须在 [0, 3600] 内,"
                f" 实际 value={badge_poll_interval_seconds!r}"
            )

        # 状态先记下,super().__init__() 之前不能调任何 rumps 回调
        self._service: ExpenseService = expense_service or ExpenseServiceStub.get_default_stub()
        self._notes_count: int = self._service.get_total_notes_count()

        # v0.2.2 候选 #2 — 1-click 确认服务(沿 D4.7.3 v1.0.6 default_singleton 范本)
        self._note_confirm_service: NoteConfirmService = (
            note_confirm_service or NoteConfirmServiceStub.get_default_stub()
        )

        # v0.2.53 P1 — outbox 草稿待审批计数(Stub 阶段恒 0)
        self._outbox_draft_service: OutboxDraftService = (
            outbox_draft_service or OutboxDraftServiceStub.get_default_stub()
        )
        self._pending_total: int = self._compute_today_pending_total()

        # ⌥⌘N 全局快捷键子进程(D9.5 双进程范本)
        # Queue[Any] 必须在子进程 start 之前创建(子进程会推到这)
        self._hotkey_queue: _mp.Queue[Any] = _mp.Queue()
        self._hotkey_proc: HotkeyListenerProcess | None = None
        # 轮询 thread 守护标记(测试可显式停掉)
        self._stop_hotkey_poll: _threading.Event = _threading.Event()

        # 剪贴板捕获服务(D9.6.1 沿 D4.7.3 v1.0.6 注入 + 懒构造)
        # 显式 None = 用 default;显式非 None = 用注入值
        self._capture_service: ClipboardCaptureService | None = capture_service
        self._capture_service_built: bool = capture_service is not None

        # 调 rumps.App.__init__ 启动 NSApp 主循环
        super().__init__("MyAIEmployee", title=self._format_title(self._pending_total))

        # v0.2.2 启动候选 #6 — badge 实时刷新轮询(沿 D5 业务调度 polling 范本)
        # 独立 thread 定时调 _refresh_pending_confirm_count + _refresh_anomaly_count
        # 触发场景:外部 sync_notes / IMAP / AppleScript 等更新 needs_confirm=1 后
        # 用户无需点击菜单, badge 自动同步数字
        self._badge_poll_interval_seconds: float = float(badge_poll_interval_seconds)
        self._badge_poll_thread: _threading.Thread | None = None

        # v0.2.53 P1 Codex 信息架构菜单(保留 D9.3/D8.3/v0.2.2 能力项)
        self.menu: list[Any] = [
            f"{_MENU_TODAY_PENDING} (0)",
            f"{_MENU_MAIL_DRAFT} (0)",
            f"{_MENU_NOTES_CONFIRM} (0)",
            f"{_MENU_FINANCE_ANOMALY} (0)",
            "快捷捕获 ⌥⌘N",
            "📥 确认第 1 条",
            "立即同步",
            "打开 Notes",
            "打开工作台",
            "系统健康",
            None,
            "授权引导",
            "退出",
        ]
        self._refresh_all_badges()

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
        """格式化菜单栏 title(今日待处理合计 → 表情 + 数字).

        Args:
            count: 今日待处理合计(邮件草稿 + Notes待确认 + 财务异常)

        Returns:
            "🧑‍💼 我的AI员工 (N)" 格式字符串
        """
        return _TITLE_TEMPLATE.format(count=count)

    def _safe_pending_count(self, getter: Any) -> int:
        """单项待办计数(失败 → 0,不崩菜单栏)."""
        try:
            return int(getter())
        except Exception:  # noqa: BLE001
            return 0

    def _compute_today_pending_total(self) -> int:
        """今日待处理合计(静默降级:单项失败不计入,不崩菜单栏)."""
        return (
            self._safe_pending_count(self._outbox_draft_service.get_pending_draft_count)
            + self._safe_pending_count(self._note_confirm_service.get_pending_confirm_count)
            + self._safe_pending_count(lambda: self._service.get_anomaly_count())
        )

    def _refresh_title(self) -> None:
        """刷新菜单栏 title(同步后调,沿 D5 范本)."""
        self._notes_count = self._service.get_total_notes_count()
        self._pending_total = self._compute_today_pending_total()
        self.title = self._format_title(self._pending_total)

    def _refresh_all_badges(self) -> None:
        """刷新 P1 全部 badge + title(沿 v0.2.2 #6 polling 范本)."""
        self._refresh_mail_draft_count()
        self._refresh_pending_confirm_count()
        self._refresh_anomaly_count()
        self._refresh_today_pending_summary()
        self._pending_total = self._compute_today_pending_total()
        self.title = self._format_title(self._pending_total)

    @_clicked_decorator("立即同步")  # type: ignore[untyped-decorator]
    def _on_sync_now(self, _sender: Any) -> None:
        """点击"立即同步" — subprocess 调 sync_notes.py sync(4 退出码契约).

        Returns:
            None(结果通过 menu title 刷新 / rumps.notification 反馈)
        """
        result = subprocess.run(  # noqa: S603 — 同步场景必传 list[Any],eval 风险为零
            [sys.executable, "-m", _SYNC_SCRIPT_MODULE, "sync"],
            capture_output=True,
            text=True,
            timeout=_SYNC_TIMEOUT_SECONDS,
        )
        if result.returncode == 0:
            self._refresh_all_badges()
        else:
            _notification_func(
                "Notes 同步失败",
                "",
                (result.stderr or "未知错误")[:200],
            )

    @_clicked_decorator("打开 Notes")  # type: ignore[untyped-decorator]
    def _on_open_notes(self, _sender: Any) -> None:
        """点击"打开 Notes" — `open -a Notes` 启动 Apple Notes.app."""
        subprocess.run(  # noqa: S603
            ["open", "-a", "Notes"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    @_clicked_decorator("快捷捕获 ⌥⌘N")  # type: ignore[untyped-decorator]
    def _on_quick_capture(self, _sender: Any) -> None:
        """点击"快捷捕获 ⌥⌘N" — 与全局快捷键同链路."""
        self._on_clipboard_capture()

    @_clicked_decorator("打开工作台")  # type: ignore[untyped-decorator]
    def _on_open_dashboard(self, _sender: Any) -> None:
        """点击"打开工作台" — 用系统浏览器打开 P0 静态 HTML 原型."""
        if not _DASHBOARD_HTML.is_file():
            _notification_func(
                "打开工作台失败",
                "静态原型不存在",
                str(_DASHBOARD_HTML),
            )
            return
        subprocess.run(  # noqa: S603
            ["open", str(_DASHBOARD_HTML)],
            capture_output=True,
            text=True,
            timeout=10,
        )

    @_clicked_decorator("系统健康")  # type: ignore[untyped-decorator]
    def _on_system_health(self, _sender: Any) -> None:
        """点击"系统健康" — 弹窗展示质量门基线(只读,不跑 CI)."""
        head = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(_DASHBOARD_HTML.parents[2]),
        )
        head_str = head.stdout.strip() if head.returncode == 0 else "unknown"
        body = format_system_health_body(git_head=head_str)
        _notification_func("系统健康", "9/9 质量门基线(只读快照)", body[:200])

    @_clicked_decorator("📋 今日待处理")  # type: ignore[untyped-decorator]
    def _on_today_pending_summary(self, _sender: Any) -> None:
        """点击"今日待处理" — 弹窗展示三项 breakdown."""
        try:
            draft = self._outbox_draft_service.get_pending_draft_count()
            notes = self._note_confirm_service.get_pending_confirm_count()
            anomaly = self._service.get_anomaly_count()
        except Exception as e:  # noqa: BLE001
            _notification_func(
                "📋 今日待处理",
                "获取待办失败",
                f"{type(e).__name__}: {str(e)[:100]}",
            )
            return
        total = draft + notes + anomaly
        body = f"邮件草稿: {draft}\nNotes待确认: {notes}\n财务异常: {anomaly}\n合计: {total}"
        _notification_func(
            f"📋 今日待处理 ({total})",
            "等待你确认的高优先级项",
            body[:200],
        )

    def _refresh_today_pending_summary(self) -> None:
        """刷新"今日待处理"父项 badge."""
        total = self._compute_today_pending_total()
        _update_menu_badge(self.menu, _MENU_TODAY_PENDING, f"{_MENU_TODAY_PENDING} ({total})")

    def _refresh_mail_draft_count(self) -> None:
        """刷新邮件草稿菜单 badge."""
        try:
            count = self._outbox_draft_service.get_pending_draft_count()
        except Exception:  # noqa: BLE001
            return
        _update_menu_badge(self.menu, _MENU_MAIL_DRAFT, f"{_MENU_MAIL_DRAFT} ({count})")

    @_clicked_decorator("  ✉️ 邮件草稿")  # type: ignore[untyped-decorator]
    def _on_mail_draft_pending(self, _sender: Any) -> None:
        """点击"邮件草稿" — 占位:Stub 阶段提示 outbox 审批入口."""
        try:
            count = self._outbox_draft_service.get_pending_draft_count()
        except Exception as e:  # noqa: BLE001
            _notification_func(
                "  ✉️ 邮件草稿",
                "获取草稿数失败",
                f"{type(e).__name__}: {str(e)[:100]}",
            )
            return
        if count == 0:
            _notification_func(
                "  ✉️ 邮件草稿",
                "暂无待审批草稿",
                "outbox 无 pending_send/approved 待处理项(Stub 阶段)",
            )
            return
        _notification_func(
            f"  ✉️ 邮件草稿 ({count})",
            "请打开工作台审批",
            "沿 outbox 1-click 审批状态机,不自动发送",
        )

    @_clicked_decorator("授权引导")  # type: ignore[untyped-decorator]
    def _on_open_privacy(self, _sender: Any) -> None:
        """点击"授权引导" — 打开 系统设置→自动化 引导用户授权."""
        subprocess.run(  # noqa: S603
            ["open", _PRIVACY_URL],
            capture_output=True,
            text=True,
            timeout=10,
        )

    # ===== D8.3 财务异常菜单项(不弹通知,用户主动查询)=====

    @_clicked_decorator("  💰 财务异常")  # type: ignore[untyped-decorator]
    def _on_anomaly_alert(self, _sender: Any) -> None:
        """点击"⚠️ 异常告警" — 弹窗显示本月异常列表(D8.3 接入 RuleBasedAnomalyDetector).

        设计决策(沿 D8 docs 评估决策 #5):
            - 用户主动查询 vs 被动打扰(只接入"已确认"异常不弹每笔)
            - Stub 阶段:返回空 list[Any],弹窗提示"暂无异常"
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
        """刷新异常告警菜单项 badge (D8.3 stub 阶段 0, D10 后真实计数).

        v0.2.2 启动候选 #6 修复: 原代码用 `getattr(item, "title", None)` 在 str 形态
        下拿到 `str.title` 内置方法(非 None), 然后 `item.title = ...` 在 str 上
        抛 AttributeError 静默吞掉. 改用 _update_menu_badge helper(沿 #2 范本),
        同时支持 list[str] 和 rumps.Menu 2 种形态.
        """
        try:
            count = self._service.get_anomaly_count()
        except Exception:  # noqa: BLE001 — 静默降级,不影响主流程
            return
        new_title = f"{_MENU_FINANCE_ANOMALY} ({count})"
        _update_menu_badge(self.menu, _MENU_FINANCE_ANOMALY, new_title)

    # ===== v0.2.2 候选 #2 1-click 确认 UI(沿 D8.3 异常告警范本)=====

    @_clicked_decorator("  📝 Notes待确认")  # type: ignore[untyped-decorator]
    def _on_show_pending_confirm(self, _sender: Any) -> None:
        """点击"📥 待确认" — 弹窗显示 L2 跨源候选待确认列表(v0.2.2 候选 #2 接入).

        业务语义(沿 D6.4 transactions L2 范本):
            - 拉 needs_confirm=1 的 note 列表(最多 10 条)
            - 空列表 → 弹"暂无待确认"占位(沿 D8.3 _on_anomaly_alert 范本)
            - 非空 → 弹窗显示 apple_note_id / title / folder / synced_at 字段
        """
        try:
            pending = self._note_confirm_service.list_pending_confirm(limit=10)
        except Exception as e:  # noqa: BLE001 — Stub 异常不能让菜单崩
            _notification_func(
                "📥 待确认",
                "获取待确认列表失败",
                f"{type(e).__name__}: {str(e)[:100]}",
            )
            return
        if not pending:
            _notification_func(
                "📥 待确认",
                "暂无待确认",
                "无 L2 跨源候选(needs_confirm=0 全部已处理)",
            )
            return
        body = "\n".join(
            f"• {p.get('title', '?')} | {p.get('folder', '?')} | "
            f"synced_at={p.get('synced_at_ms', '?')}"
            for p in pending
        )
        # 1-click 提示: 用户可直接关闭弹窗后点"确认第 1 条"做 1-click 归档
        # (rumps.notification 是只读弹窗, 不支持按钮; 真 1-click 由 _on_confirm_first 触发)
        _notification_func(
            f"📥 待确认 ({len(pending)} 条)",
            "L2 跨源候选(顶部 1 条待 1-click 确认)",
            body[:200],
        )

    def _refresh_pending_confirm_count(self) -> None:
        """刷新待确认菜单项 badge (v0.2.2 候选 #2, 沿 _refresh_anomaly_count 范本).

        修复(v0.2.2 #2): 真实 rumps 环境下 self.menu 是 rumps.Menu 对象,项是
        tuple(str_title, MenuItem) 形式. 范本 _refresh_anomaly_count 用
        getattr(item, "title", None) 找不到(tuple 无 .title), 改用
        rumps_menu_helper 同时支持:
        - 普通 list[str] (test fake_rumps 环境, app._RumpsAppBase = _FakeRumpsApp)
        - rumps.Menu 项 (真实 NSApp 环境, app._RumpsAppBase = rumps.App)
        """
        try:
            count = self._note_confirm_service.get_pending_confirm_count()
        except Exception:  # noqa: BLE001 — 静默降级,不影响主流程
            return
        new_title = f"{_MENU_NOTES_CONFIRM} ({count})"
        _update_menu_badge(self.menu, _MENU_NOTES_CONFIRM, new_title)

    @_clicked_decorator("📥 确认第 1 条")  # type: ignore[untyped-decorator]
    def _on_confirm_first(self, _sender: Any) -> None:
        """点击"📥 确认第 1 条" — 1-click 确认 top 1 待确认 note(v0.2.2 候选 #2).

        业务语义(沿 D6.4 transactions L2 范本):
            - 拉 list[Any](limit=1)取 top 1
            - 空 → 弹"暂无待确认"
            - 非空 → confirm_note(apple_note_id) → NoteStore.mark_archived
            - 刷新 badge + 弹 notification 反馈结果
        """
        try:
            pending = self._note_confirm_service.list_pending_confirm(limit=1)
        except Exception as e:  # noqa: BLE001 — Stub 异常不能让菜单崩
            _notification_func(
                "📥 1-click 确认",
                "获取待确认列表失败",
                f"{type(e).__name__}: {str(e)[:100]}",
            )
            return
        if not pending:
            _notification_func(
                "📥 1-click 确认",
                "暂无待确认",
                "无需 1-click 确认(needs_confirm=0 全部已处理)",
            )
            return
        top = pending[0]
        apple_note_id = top.get("apple_note_id", "")
        try:
            self._note_confirm_service.confirm_note(apple_note_id)
        except Exception as e:  # noqa: BLE001 — confirm 失败需明确反馈
            _notification_func(
                "📥 1-click 确认失败",
                top.get("title", "?"),
                f"{type(e).__name__}: {str(e)[:200]}",
            )
            return
        # 成功: 刷新 badge + 反馈
        self._refresh_pending_confirm_count()
        _notification_func(
            "📥 1-click 确认成功",
            top.get("title", "?"),
            f"已归档: apple_note_id={apple_note_id[:32]}",
        )

    # ===== D9.5 ⌥⌘N 全局快捷键(双进程范本主入口)=====

    def _start_hotkey_listener(self) -> None:
        """启动 ⌥⌘N 监听子进程 + Queue[Any] 轮询 thread.

        异常收容(沿 D4.7.3 v1.0.5 P3):
            - 子进程 start 失败(多进程资源不足) → 静默(主进程仍可同步)
            - pynput TCC 拒授权 → 子进程推 Queue[Any],主进程弹 notification
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

        # v0.2.2 启动候选 #6 — 启动 badge 实时刷新 polling(沿 D5 业务调度范本)
        # 仅当 interval > 0 时启动(0 = 禁用, 测试场景用)
        if self._badge_poll_interval_seconds > 0:
            self._badge_poll_thread = _threading.Thread(
                target=self._poll_badge_count,
                daemon=True,
                name="badge-poll",
            )
            self._badge_poll_thread.start()

    def _poll_hotkey_queue(self) -> None:
        """轮询 Queue[Any] 收子进程事件(沿 D5 业务调度范本).

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
                # 子进程已死或 Queue[Any] 关闭 → 退出轮询
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

    def _poll_badge_count(self) -> None:
        """v0.2.2 启动候选 #6 — badge 实时刷新 polling(沿 D5 业务调度 polling 范本).

        设计决策(2026-06-17 锁定):
            - 独立 daemon thread, 与 _poll_hotkey_queue 平行
            - 复用 _stop_hotkey_poll Event 简化退出(主进程退 → 全停)
            - interval 默认 30s, 0 = 禁用(测试场景, 此时本方法不被启动)
            - 优雅 sleep: 1s 粒度 + Event.wait(支持秒级响应 stop, 不死等 30s)
            - 静默吞异常(单次失败不退出 polling, 沿 _refresh_*_count try/except 范本)
            - 首次启动立即刷 1 次(避免刚启动 30s 后才显示正确数字)
            - 用 time.monotonic() 精确测 elapsed(支持短 interval 测试场景如 0.1s)

        触发场景:
            - sync_notes.py 同步脚本导入新 note → needs_confirm=1
            - IMAP 邮件接入 → note(邮件内容) 标 needs_confirm
            - OutboxDispatcher 真实发送后 → 月报聚合 mark needs_confirm
        """
        interval = self._badge_poll_interval_seconds
        # 首次启动立即刷 1 次(避免刚启动 30s 后才显示正确数字)
        try:
            self._refresh_pending_confirm_count()
            self._refresh_anomaly_count()
            self._refresh_mail_draft_count()
            self._refresh_today_pending_summary()
            self._pending_total = self._compute_today_pending_total()
            self.title = self._format_title(self._pending_total)
        except Exception:  # noqa: BLE001 — 静默, 不影响主循环
            pass
        # 优雅 polling: time.monotonic() 精确测 elapsed + Event.wait 支持秒级 stop 响应
        import time as _time

        last_refresh_mono = _time.monotonic()
        # wait 粒度: min(1.0, interval) — 短 interval 测试场景(0.1s)也能响应
        # 长 interval 生产场景(30s)1s 粒度已足
        wait_granularity = min(_BADGE_POLL_SLEEP_GRANULARITY_SECONDS, interval)
        while not self._stop_hotkey_poll.is_set():
            now_mono = _time.monotonic()
            elapsed = now_mono - last_refresh_mono
            if elapsed >= interval:
                with contextlib.suppress(Exception):
                    self._refresh_all_badges()
                last_refresh_mono = _time.monotonic()
            # 短粒度 sleep + 早退(Event.set 后秒级响应)
            if self._stop_hotkey_poll.wait(timeout=wait_granularity):
                return  # stop event 已 set

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
