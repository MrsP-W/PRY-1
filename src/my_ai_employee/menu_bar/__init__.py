"""Mac 菜单栏 UI（rumps）。

D5 实施。Week 1 D5 显示：今日未读 / 今日待办 / 本月支出。
D9.3 实施：Notes 菜单栏 App(沿 D10 留 ExpenseService 注入点)。
D9.5 实施：⌥⌘N 全局快捷键(双进程范本 + pynput + TCC 引导)。
D9.6.1 实施：ClipboardCaptureService 业务层 3 入口(沿 D4.7.3 v1.0.6 同构)。
v0.2.2 候选 #2 实施:NoteConfirmService 接口 + Stub + Real(NoteStore 接入),
             菜单栏新增 "  📝 Notes待确认 (N)" 1-click 确认入口。
v0.2.53 P1 实施:Codex 信息架构菜单栏升级 + OutboxDraftService Stub。
v0.2.2 启动候选 #6 实施:badge 实时刷新 polling(沿 D5 业务调度范本,
             独立 daemon thread 30s 间隔调 _refresh_*_count, 0 = 禁用)。
"""

from my_ai_employee.menu_bar.app import NotesMenuBarApp
from my_ai_employee.menu_bar.clipboard_capture import ClipboardCaptureService
from my_ai_employee.menu_bar.clipboard_listener import HotkeyListenerProcess
from my_ai_employee.menu_bar.expense_service import (
    ExpenseService,
    ExpenseServiceStub,
)
from my_ai_employee.menu_bar.note_confirm_service import (
    NoteConfirmService,
    NoteConfirmServiceImpl,
    NoteConfirmServiceStub,
)
from my_ai_employee.menu_bar.outbox_draft_service import (
    OutboxDraftService,
    OutboxDraftServiceStub,
)
from my_ai_employee.menu_bar.tcc import TCCPermissionError, open_privacy_settings

__all__ = [
    "ClipboardCaptureService",
    "ExpenseService",
    "ExpenseServiceStub",
    "HotkeyListenerProcess",
    "NoteConfirmService",
    "NoteConfirmServiceImpl",
    "NoteConfirmServiceStub",
    "NotesMenuBarApp",
    "OutboxDraftService",
    "OutboxDraftServiceStub",
    "TCCPermissionError",
    "open_privacy_settings",
]
