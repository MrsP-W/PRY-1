"""v0.2.53.17 BusinessWriterImpl — 写操作 Impl 接入骨架(默认 raise NotImplementedError).

承接 docs/v0.2.53.14-business-writer-design-2026-06-26.md §10 v0.2.53.17 范围:
    - 接入 BusinessWriterImpl(approve_outbox / cancel_outbox / confirm_note 3 类已有 Service)
    - 单项失败降级(沿 v0.2.53.8 单项失败降级范本)
    - 默认行为 = raise NotImplementedError(沿撞坑 #65 默认 Stub 边界)

设计决策(2026-06-26 锁定):
    - 抽象 BusinessWriterImpl 类(3 已有 Service + dismiss_anomaly 占位)
    - 构造函数接受可选依赖(OutboxStore / NoteConfirmServiceImpl / AnomalyDismissalServiceStub)
    - 默认所有方法 raise NotImplementedError(等待 v0.2.53.19 handler 路径 4 启用)
    - 仅 dry_run 实现(返回 WriteDecision)
    - 异常收窄(沿 note_confirm_service.py:113-115):用户主动操作异常必须透传

D4.7.3 教训应用(沿撞坑 #65 + v0.2.53.8):
    - Protocol 类型鸭子类型友好(无需 isinstance)
    - 严判 type 严格(避免 bool/int 互窜)
    - 单项失败不传播(approve_outbox 失败不影响 cancel_outbox)
    - 异常收容:dry_run 失败 → WriteDecision(error="internal_error");真实写入异常透传

撞坑 #65 边界应用(默认禁写):
    - 默认 raise NotImplementedError(等同 Stub 行为)
    - 不接 SMTP / 不读 Keychain 明文
    - 真实写入路径(env+confirm+writer 三道门齐全)留 v0.2.53.19 handler 启用

沿用边界:
    - 本棒默认 raise NotImplementedError,不真写 DB
    - 真实写入需 v0.2.53.19 handler 路径 4 启用 + 用户明确授权
    - 不接真实 SMTP / 不读 Keychain 明文
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from my_ai_employee.dashboard.action_contracts import is_supported_action
from my_ai_employee.dashboard.business_writer import (
    AuditContext,
    WriteDecision,
    WriteResult,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from my_ai_employee.db.outbox import OutboxStore
    from my_ai_employee.menu_bar.anomaly_dismissal_service import AnomalyDismissalServiceStub
    from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl


def _now_ms() -> int:
    """Unix epoch 毫秒时间戳(沿 v0.2.53.11 actor 默认值时间戳)."""
    return int(time.time() * 1000)


class BusinessWriterImpl:
    """BusinessWriter 真实实现骨架 — 默认所有方法 raise NotImplementedError.

    边界(沿撞坑 #65 + v0.2.53.14 设计 + v0.2.53.17 范围):
        - 默认行为 = raise NotImplementedError(等同 Stub)
        - 真实写入路径留 v0.2.53.19 handler 启用
        - 单项失败不传播(dry_run 内 try/except 容错)
        - 异常收窄:真实写入异常透传(沿 note_confirm_service.py:113-115)
        - 不接 SMTP / 不读 Keychain 明文
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Any] | None = None,
        outbox_store: OutboxStore | None = None,
        note_confirm_service: NoteConfirmServiceImpl | None = None,
        anomaly_dismissal_service: AnomalyDismissalServiceStub | None = None,
    ) -> None:
        """构造 — 所有依赖可选(默认 None 表示 raise NotImplementedError)."""
        self._session_factory = session_factory
        self._outbox_store = outbox_store
        self._note_confirm_service = note_confirm_service
        self._anomaly_dismissal_service = anomaly_dismissal_service

    def dry_run(
        self,
        action: str,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteDecision:
        """dry-run 决策 — 默认 would_allow=False(等待 v0.2.53.19 启用).

        边界(沿 v0.2.53.14 §2.1):
            - 4 类动作白名单严判(未知 action → error="unsupported_action")
            - 默认 would_allow=False(Impl 已构造但 handler 未启用)
            - write_executed=False 恒定
            - required 列出当前还缺什么
        """
        try:
            if not is_supported_action(action):
                return WriteDecision(
                    action=action,
                    target_id=target_id,
                    write_enabled=False,
                    would_allow=False,
                    write_executed=False,
                    dry_run=True,
                    audit=audit,
                    error="unsupported_action",
                    reason=f"未知 action:{action}",
                )

            # 默认 would_allow=False — real_write_handler 启用后改为 True
            return WriteDecision(
                action=action,
                target_id=target_id,
                write_enabled=False,
                would_allow=False,
                write_executed=False,
                dry_run=True,
                audit=audit,
                error="write_not_implemented",
                reason="BusinessWriterImpl 骨架就绪,real_write_handler 未启用",
                required=(
                    "DASHBOARD_WRITE_API=1",
                    "confirm_text=CONFIRM_WRITE",
                    "BUSINESS_WRITER_ENABLED=1",
                    "real_write_handler_enabled",
                ),
            )
        except Exception as e:
            # dry_run 异常收容(沿 v0.2.53.14 §7.4)
            return WriteDecision(
                action=action,
                target_id=target_id,
                write_enabled=False,
                would_allow=False,
                write_executed=False,
                dry_run=True,
                audit=audit,
                error="internal_error",
                reason=f"dry_run 异常:{type(e).__name__}:{e}",
            )

    def approve_outbox(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """默认 raise — handler 路径 4 启用后改为调 OutboxStore.update_status.

        Raises:
            NotImplementedError: 默认行为,留 v0.2.53.19 启用.
        """
        raise NotImplementedError("BusinessWriterImpl.approve_outbox real_write_handler 未启用")

    def cancel_outbox(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """默认 raise — handler 路径 4 启用后改为调 OutboxStore.update_status."""
        raise NotImplementedError("BusinessWriterImpl.cancel_outbox real_write_handler 未启用")

    def confirm_note(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """默认 raise — handler 路径 4 启用后改为调 NoteConfirmServiceImpl.confirm_note.

        异常收窄(沿 note_confirm_service.py:113-115):用户主动操作异常必须透传.
        """
        raise NotImplementedError("BusinessWriterImpl.confirm_note real_write_handler 未启用")

    def dismiss_anomaly(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """默认 raise — handler 路径 4 启用后改为调 AnomalyDismissalServiceStub.dismiss."""
        raise NotImplementedError("BusinessWriterImpl.dismiss_anomaly real_write_handler 未启用")

    @staticmethod
    def _audit_timestamp(audit: AuditContext) -> int:
        """审计时间戳 — audit.timestamp_ms 或 now_ms()."""
        return audit.timestamp_ms if audit.timestamp_ms is not None else _now_ms()
