"""v0.2.53 P1/P2 — OutboxDraftService 接口与实现(菜单栏/Dashboard 邮件草稿).

承接 docs/v0.2.53-codex-style-ui-design-2026-06-25.md §P1 菜单栏:
    - "今日待处理" 子项 "邮件草稿 (N)" 展示 outbox 待审批草稿数
    - 阶段 1(P1):Stub 返回 0
    - 阶段 2(P2):OutboxDraftServiceImpl 接 OutboxStore.by_status 只读查询

边界:
    - Impl 通过注入 OutboxStore 接真实数据,本模块不主动打开 Database,避免默认读取
      Keychain 明文或创建 DB。
    - 列表输出不包含 body,避免 Dashboard 泄露邮件正文。
"""

from __future__ import annotations

from typing import Any, Final, Protocol


class OutboxDraftService(Protocol):
    """菜单栏 / Dashboard outbox 草稿待审批接口."""

    def get_pending_draft_count(self) -> int: ...

    def list_pending_drafts(self, limit: int = 10) -> list[dict[str, Any]]: ...


_PENDING_DRAFT_DEFAULT: Final[int] = 0
_LIST_PENDING_DRAFTS_DEFAULT: Final[list[dict[str, Any]]] = []
_PENDING_DRAFT_STATUSES: Final[tuple[str, str]] = ("pending_send", "approved")
_MAX_LIST_LIMIT: Final[int] = 100
_COUNT_SCAN_LIMIT: Final[int] = 10_000


class OutboxDraftServiceStub:
    """Stub — get_pending_draft_count 恒返回 0(沿 ExpenseServiceStub 范本)."""

    _default: OutboxDraftServiceStub | None = None

    @classmethod
    def get_default_stub(cls) -> OutboxDraftServiceStub:
        if cls._default is None:
            cls._default = cls()
        return cls._default

    def get_pending_draft_count(self) -> int:
        return _PENDING_DRAFT_DEFAULT

    def list_pending_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
        return list(_LIST_PENDING_DRAFTS_DEFAULT)[: max(0, limit)]


class _OutboxStoreLike(Protocol):
    """OutboxStore duck type — 只依赖 by_status 只读查询."""

    def by_status(self, status: str, limit: int = 100) -> list[Any]: ...


class OutboxDraftServiceImpl:
    """OutboxDraftService 真实实现 — 只读查询 OutboxStore.

    语义:
        - pending_send: AI 已生成草稿,等待用户审批
        - approved: 用户已审批,等待 Dispatcher 发送

    两者都属于"今日待处理邮件草稿",因此计数和列表合并展示。
    """

    def __init__(self, outbox_store: _OutboxStoreLike) -> None:
        if outbox_store is None:
            raise TypeError(f"outbox_store 必填(非 None),实际 type={type(outbox_store).__name__}")
        if not hasattr(outbox_store, "by_status"):
            raise TypeError(
                "outbox_store 必须实现 by_status(status, limit) 只读接口,"
                f" 实际 type={type(outbox_store).__name__}"
            )
        self._store = outbox_store

    def get_pending_draft_count(self) -> int:
        """返回 pending_send + approved 数量;异常静默降级为 0."""
        try:
            return len(self._list_entries(limit=_COUNT_SCAN_LIMIT))
        except Exception:  # noqa: BLE001 — 菜单栏/Dashboard 不因 DB 查询失败崩
            return 0

    def list_pending_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回待处理 outbox 草稿列表,不含正文 body.

        Args:
            limit: 最大返回条数,[1,100] int,严判避免过量读取。
        """
        if (
            type(limit) is bool
            or not isinstance(limit, int)
            or limit < 1
            or limit > _MAX_LIST_LIMIT
        ):
            raise ValueError(
                f"limit 必须是 [1, {_MAX_LIST_LIMIT}] 的 int(非 bool),"
                f" 实际 type={type(limit).__name__}, value={limit!r}"
            )
        try:
            entries = self._list_entries(limit=limit)
        except Exception:  # noqa: BLE001 — UI 查询失败返回空列表
            return []
        return [self._entry_to_dict(entry) for entry in entries[:limit]]

    def _list_entries(self, *, limit: int) -> list[Any]:
        entries: list[Any] = []
        for status in _PENDING_DRAFT_STATUSES:
            entries.extend(self._store.by_status(status, limit=limit))
        entries.sort(key=lambda entry: int(getattr(entry, "created_at", 0)))
        return entries[:limit]

    @staticmethod
    def _entry_to_dict(entry: Any) -> dict[str, Any]:
        """OutboxEntry → UI 安全 dict(不含 body)."""
        return {
            "outbox_id": getattr(entry, "id", None),
            "email_id": getattr(entry, "email_id", None),
            "subject": getattr(entry, "subject", ""),
            "recipient_email": getattr(entry, "recipient_email", ""),
            "status": getattr(entry, "status", ""),
            "priority": getattr(entry, "priority", ""),
            "created_at": getattr(entry, "created_at", None),
            "sla_due_at_ms": getattr(entry, "sla_due_at_ms", None),
            "last_approved_at_ms": getattr(entry, "last_approved_at_ms", None),
        }


__all__ = ["OutboxDraftService", "OutboxDraftServiceStub", "OutboxDraftServiceImpl"]
