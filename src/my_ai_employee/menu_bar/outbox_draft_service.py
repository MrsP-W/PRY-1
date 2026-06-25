"""v0.2.53 P1 — OutboxDraftService 接口与 Stub(菜单栏邮件草稿待审批计数).

承接 docs/v0.2.53-codex-style-ui-design-2026-06-25.md §P1 菜单栏:
    - "今日待处理" 子项 "邮件草稿 (N)" 展示 outbox 待审批草稿数
    - 阶段 1(P1):Stub 返回 0,D10 后替换 OutboxDraftServiceImpl(接 OutboxStore.by_status)
"""

from __future__ import annotations

from typing import Final, Protocol


class OutboxDraftService(Protocol):
    """菜单栏 outbox 草稿待审批计数接口."""

    def get_pending_draft_count(self) -> int: ...


_PENDING_DRAFT_DEFAULT: Final[int] = 0


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


__all__ = ["OutboxDraftService", "OutboxDraftServiceStub"]
