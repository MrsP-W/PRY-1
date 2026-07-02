"""v0.2.2 候选 #2 — NoteConfirmService 接口 + Stub + Real(沿 ExpenseService 范本).

承接 docs/v0.2.1-candidates-2026-06-17.md §6 v0.2.2 启动候选 #2 + D6.4 transactions L2 待确认范本:
    - 菜单栏 App 展示"📥 待确认 (N)"菜单项
    - 1-click 确认: 弹窗显示 top 待确认 note, 用户点确认 → mark_archived(终态)
    - 阶段 1(本 commit): 3 方法接口 + Stub 默认 + Real(NoteStore 接入)
    - 阶段 2(后续): 接入 web dashboard / 月报聚合

设计决策(2026-06-17 锁定):
    - 抽象 NoteConfirmService Protocol 类(3 方法) + Stub 硬编码实现
    - 注入到 NotesMenuBarApp(note_confirm_service=...),默认构造 Stub
    - Real(NoteConfirmServiceImpl) 从 NoteStore 接入,无需新建 ORM
    - 1-click 动作语义: confirm_note(apple_note_id) → NoteStore.mark_archived

D4.7.3 教训应用(沿 ExpenseService 范本):
    - Protocol 类型用 Protocol 类(非 ABC,鸭子类型友好)
    - 3 方法返回值用 `Final` 常量(避免硬编码分散)
    - 严判 type 严格(不 isinstance,避免 bool/int 互窜)
    - Real 实现的异常收容(沿 D8.3 _on_anomaly_alert 范本): 列表查询失败 → 返回 []
      (静默降级, 菜单栏不崩)

D5.6.3 P1-1 范本应用:
    - 1 commit 4 文件落地: note_confirm_service.py + menu_bar/__init__.py
      + menu_bar/app.py + tests/menu_bar/test_note_confirm_service.py
"""

from __future__ import annotations

from typing import Any, Final, Protocol

# ===== NoteConfirmService Protocol 3 方法契约 =====


class NoteConfirmService(Protocol):
    """菜单栏 1-click 确认服务接口(v0.2.2 候选 #2 — 沿 ExpenseService 7 方法范本).

    3 方法契约:
        - get_pending_confirm_count  → "📥 待确认 (N)" 菜单 badge
        - list_pending_confirm       → 点击菜单项弹窗列表(待确认笔记标题/日期)
        - confirm_note               → 1-click 确认: mark_archived(终态)
    """

    def get_pending_confirm_count(self) -> int: ...

    def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]: ...

    def confirm_note(self, apple_note_id: str) -> None: ...


# ===== Stub 默认值常量(避免硬编码分散)=====


_PENDING_CONFIRM_COUNT_DEFAULT: Final[int] = 0
_LIST_PENDING_CONFIRM_DEFAULT: Final[list[dict[str, Any]]] = []


class NoteConfirmServiceStub:
    """NoteConfirmService Stub 实现 — 3 方法全部返回硬编码默认值(无 DB 接入).

    设计取舍(沿 ExpenseServiceStub 范本):
        - 不调 DB / 不调 NoteStore(完全解耦,测试零依赖)
        - 单例 (`get_default_stub()`),避免每次 new(可热替换)
        - 类型签名与 Protocol 100% 对齐(Real 实现可直接替换)

    沿 D8.3 _on_anomaly_alert 范本: 弹窗查询异常时返回 [], 弹"暂无待确认"占位
    (注: Stub 始终返回 0/[]/None, 无异常分支).
    """

    def get_pending_confirm_count(self) -> int:
        """返回 0(stub 阶段无 DB 接入)."""
        return _PENDING_CONFIRM_COUNT_DEFAULT

    def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回 [] (stub 阶段无 DB 接入).

        Args:
            limit: 最大返回条数(stub 不校验,直接返回 [])
        """
        return list(_LIST_PENDING_CONFIRM_DEFAULT)

    def confirm_note(self, apple_note_id: str) -> None:
        """no-op(stub 阶段不真归档).

        Args:
            apple_note_id: Apple Notes 唯一 ID(stub 忽略)
        """
        return None

    @staticmethod
    def get_default_stub() -> NoteConfirmServiceStub:
        """返回 Stub 单例(沿 D5.6.4 工厂范本)."""
        return _DEFAULT_STUB


_DEFAULT_STUB: Final[NoteConfirmServiceStub] = NoteConfirmServiceStub()


# ===== Real 实现 — NoteStore 接入(沿 D10 替换范本)=====


class NoteConfirmServiceImpl:
    """NoteConfirmService 真实实现 — 调 NoteStore 3 方法(沿 D8.3 ExpenseServiceImpl 范本).

    接入契约:
        - get_pending_confirm_count → NoteStore.count_by_needs_confirm()(SQL COUNT(*))
        - list_pending_confirm → NoteStore.list_by_needs_confirm(limit=limit) 转 dict 列表
          (UI 层需要 dict 而非 ORM 对象, 序列化字段)
        - confirm_note → NoteStore.mark_archived(apple_note_id)
          (1-click 确认 = 归档, 状态机 STRUCTURED → ARCHIVED 终态)

    异常收容(沿 D8.3 _on_anomaly_alert 范本):
        - get_pending_confirm_count 失败 → 返回 0(菜单栏不崩)
        - list_pending_confirm 失败 → 返回 [](弹"暂无待确认"占位)
        - confirm_note 失败 → 向上抛(用户主动操作, 必须看到错误)
    """

    def __init__(self, note_store: Any) -> None:
        """初始化 NoteConfirmServiceImpl.

        Args:
            note_store: NoteStore 实例(3 方法契约 duck type,不 isinstance 校验,
                       沿 D4.7.3 公共 helper 范本)

        Note: 延迟 NoteStore 类型导入避免循环引用(menu_bar → db.notes, db.notes 不引用 menu_bar).
        """
        if note_store is None:
            raise TypeError(f"note_store 必填(非 None),实际 type={type(note_store).__name__}")
        # 严判 duck type(沿 D4.7.3 公共 helper 范本)
        required_methods = (
            "count_by_needs_confirm",
            "list_by_needs_confirm",
            "mark_archived",
        )
        missing = [m for m in required_methods if not hasattr(note_store, m)]
        if missing:
            raise TypeError(
                f"note_store 必须实现 {required_methods} duck type,"
                f" 实际 type={type(note_store).__name__}, 缺方法: {missing}"
            )
        self._store = note_store

    def get_pending_confirm_count(self) -> int:
        """返回 needs_confirm=1 的 note 数(沿 D6.4 transactions L2 范本).

        异常收容: 任何异常 → 返回 0(菜单栏静默降级).
        """
        try:
            return int(self._store.count_by_needs_confirm())
        except Exception:  # noqa: BLE001 — Stub 异常不能让菜单崩(沿 D8.3 范本)
            return 0

    def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回 needs_confirm=1 的 note 列表(dict 形式, UI 序列化友好).

        Args:
            limit: 最大返回条数(必为 [1, 100] 的 int, 严判沿 NoteStore 范本)

        Returns:
            list[dict]: 每条 dict 含 apple_note_id / title / folder / synced_at_ms /
                       candidate_match_id / needs_confirm 6 字段(UI 弹窗展示用)

        异常收容: 任何异常 → 返回 [](弹"暂无待确认"占位).
        """
        if type(limit) is bool or not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError(
                f"limit 必须是 [1, 100] 的 int(非 bool),"
                f" 实际 type={type(limit).__name__}, value={limit!r}"
            )
        try:
            notes = self._store.list_by_needs_confirm(limit=limit)
        except Exception:  # noqa: BLE001 — Stub 异常不能让菜单崩
            return []
        return [
            {
                "apple_note_id": n.apple_note_id,
                "title": n.title,
                "folder": n.folder,
                "synced_at_ms": n.synced_at_ms,
                "candidate_match_id": n.candidate_match_id,
                "needs_confirm": n.needs_confirm,
            }
            for n in notes
        ]

    def confirm_note(self, apple_note_id: str) -> None:
        """1-click 确认: 调 NoteStore.mark_archived(apple_note_id)(终态).

        Args:
            apple_note_id: Apple Notes 唯一 ID(必为非空 str, type 严判)

        异常处理: 不收容 — 用户主动操作, 必须看到 ValueError(状态机不合法等).
        """
        if not isinstance(apple_note_id, str):
            raise TypeError(
                f"apple_note_id 必须是 str, 实际 type={type(apple_note_id).__name__},"
                f" value={apple_note_id!r}"
            )
        stripped = apple_note_id.strip()
        if not stripped:
            raise ValueError(
                f"apple_note_id 必填且必须非空字符串(非纯空白), 实际 {apple_note_id!r}"
            )
        self._store.mark_archived(stripped)


__all__ = [
    "NoteConfirmService",
    "NoteConfirmServiceStub",
    "NoteConfirmServiceImpl",
]
