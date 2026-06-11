"""D4.8 — OutboxStore: outbox 表读写封装.

承接 D4.8.1 outbox migration 0004(11 字段 + UNIQUE + 2 索引 + 2 FK)
+ D4.8.2 OutboxEntry ORM(11 字段 + 3 个 StrEnum).

设计(沿用 D4.3 EventStore 范本):
  - insert(): 走 D4.8 契约(入库 + IntegrityError 窄化 → 业务阻断)
  - by_email_id / by_status / by_priority: 3 类热路径查询
  - update_status: 状态机更新(D4.8 范围:仅 pending_send → 其他,D5+ 扩转换)
  - 严判只放在 D4.8.4 Adapter 层(契约层 OutboxStore 接受已校验参数,不再二次严判)

D3.3.3 教训应用:
  - except 范围窄化: 只接 sqlalchemy.exc.IntegrityError, 不接 SQLAlchemyError 基类
  - 失败状态透明化: UNIQUE(email_id) 冲突是正常业务阻断(走 record_store_business_blocked_and_emit),
    用 raise OutboxEmailDuplicateError 让 Adapter 上层接住
  - 反范本: D3.3.2 (SQLAlchemyError, _sqlcipher_dbapi.IntegrityError) 过宽,
    会把 OperationalError / DB 锁 / InterfaceError / DataError 误算为业务阻断,
    掩盖真实生产问题
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from my_ai_employee.core.models.outbox import (
    OutboxEntry,
    OutboxStatus,
    _OUTBOX_STATUS_CHOICES,
)


# ===== 自定义异常(D4.8 契约 4 — UNIQUE 冲突 → 业务阻断入口)=====


class OutboxEmailDuplicateError(Exception):
    """UNIQUE(email_id) 冲突异常(D4.8 契约 4 — 业务阻断入口)。

    Adapter 层 EmailOutboxAdapter.record_store_business_blocked_and_emit
    接住此异常,转写 event_metadata(kind=business_blocked, reason="duplicate_email_id"),
    **不**走 record_store_failure_and_emit(技术失败入口)。

    异常信息包含 email_id 便于 audit 追溯。
    """

    def __init__(self, email_id: int, original_error: IntegrityError) -> None:
        self.email_id = email_id
        self.original_error = original_error
        super().__init__(
            f"UNIQUE(email_id) 冲突: email_id={email_id} "
            f"(已存在 outbox 条目,入库幂等性触发 — 走业务阻断入口)"
        )


# ===== OutboxStore =====


class OutboxStore:
    """outbox 表读写封装(D4.8 业务层契约 — D4.8.4 Adapter 依赖此 Store)。

    Usage:
        store = OutboxStore(session_factory)
        # 入库(D4.8.4 Adapter 严判入参后调用)
        entry = store.insert(
            email_id=123,
            subject="客户投诉全额退款处理",
            body="针对您的投诉...",
            tone="FORMAL",
            recipient_email="customer@example.com",
        )
        assert entry.id is not None
        assert entry.status == "pending_send"
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # ===== insert =====

    def insert(
        self,
        email_id: int,
        subject: str,
        body: str,
        tone: str,
        recipient_email: str,
        *,
        reviewer_decision_event_id: int | None = None,
        drafter_decision_event_id: int | None = None,
        priority: str = "normal",
        status: str = "pending_send",
        created_at: int | None = None,
    ) -> OutboxEntry:
        """插入一条 outbox 条目(D4.8 入库入口)。

        Args:
            email_id: 关联 emails.id,UNIQUE 约束实现入库幂等性
            subject: 草稿主题(D4.8.4 Adapter 严判 1-200 字符 strip() 后非空)
            body: 草稿正文(D4.8.4 Adapter 严判 10-8000 字符 strip() 后非空)
            tone: 草稿语气(OutboxTone 3 选 1,Adapter 严判)
            recipient_email: 收件人邮箱(Adapter 严判含 @)
            reviewer_decision_event_id: FK → events.id(D4.7.4 审阅通过事件,可空)
            drafter_decision_event_id: FK → events.id(D4.7.3 草稿生成事件,可空)
            priority: OutboxPriority 3 选 1,默认 "normal"
            status: OutboxStatus 4 选 1,默认 "pending_send"
            created_at: Unix epoch ms(默认 = 当前时间)

        Returns:
            新插入的 OutboxEntry(已 refresh,id/status/created_at 都可读)

        Raises:
            OutboxEmailDuplicateError: UNIQUE(email_id) 冲突(D4.8 契约 4 — 业务阻断)
            ValueError: 业务层严判失败(Adapter 已严判,Store 层不再二次严判)
            sqlalchemy.exc.OperationalError / DataError / InterfaceError: 技术失败(透传给 Adapter 走 record_store_failure_and_emit)

        D3.3.3 教训应用:
            - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突)
            - OperationalError / DataError / InterfaceError **不**捕获,透传给 Adapter 走技术失败入口
            - 拒绝 D3.3.2 反范本(SQLAlchemyError 基类过宽,会掩盖真实生产问题)
        """
        # 1. created_at 默认 = 当前时间(epoch ms,便于排序)
        if created_at is None:
            created_at = int(time.time() * 1000)

        # 2. 插入(D3.3.3 教训: 窄 except, 只接 IntegrityError)
        with self._session_factory() as session:
            try:
                row = OutboxEntry(
                    email_id=email_id,
                    subject=subject,
                    body=body,
                    tone=tone,
                    reviewer_decision_event_id=reviewer_decision_event_id,
                    drafter_decision_event_id=drafter_decision_event_id,
                    status=status,
                    created_at=created_at,
                    recipient_email=recipient_email,
                    priority=priority,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return row
            except IntegrityError as err:
                session.rollback()
                # 业务阻断: UNIQUE(email_id) 冲突 → 业务阻断入口
                # 严判:必须 UNIQUE 约束冲突才视为业务阻断
                if "UNIQUE constraint failed: outbox.email_id" in str(err.orig):
                    raise OutboxEmailDuplicateError(email_id=email_id, original_error=err) from err
                # 其他 IntegrityError(FK 约束 / CHECK 约束) 走技术失败
                raise

    # ===== 查询方法(热路径) =====

    def by_email_id(self, email_id: int) -> OutboxEntry | None:
        """按 email_id 查单条(走 UNIQUE 索引,O(1))。

        用于入库前查重(D4.8 契约 4 — 幂等性),也可用于业务层 audit。
        """
        with self._session_factory() as session:
            stmt = select(OutboxEntry).where(OutboxEntry.email_id == email_id)
            return session.execute(stmt).scalar_one_or_none()

    def by_id(self, outbox_id: int) -> OutboxEntry | None:
        """按 outbox.id 查单条(走 PK 索引,O(1))。"""
        with self._session_factory() as session:
            return session.get(OutboxEntry, outbox_id)

    def by_status(
        self,
        status: str | OutboxStatus,
        limit: int = 100,
    ) -> list[OutboxEntry]:
        """按 status 查多条(走 idx_outbox_status_created_at 索引,O(log n))。

        Args:
            status: OutboxStatus 4 选 1(enum 或字符串,严判 + 归一)
            limit: 返回上限,默认 100(D5+ 调度器轮询典型场景)

        Returns:
            按 created_at DESC 排序的 OutboxEntry 列表

        Raises:
            ValueError: status 非法(不在 _OUTBOX_STATUS_CHOICES 4 选 1)
            TypeError: status 类型非法(非 str / OutboxStatus)
        """
        status_value = self._normalize_status(status)
        with self._session_factory() as session:
            stmt = (
                select(OutboxEntry)
                .where(OutboxEntry.status == status_value)
                .order_by(OutboxEntry.created_at.desc())
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def by_priority(
        self,
        priority: str,
        limit: int = 100,
    ) -> list[OutboxEntry]:
        """按 priority 查多条(走 idx_outbox_priority_created_at 索引,O(log n))。

        Args:
            priority: OutboxPriority 3 选 1(字符串,严判)
            limit: 返回上限,默认 100

        Returns:
            按 created_at DESC 排序的 OutboxEntry 列表

        Raises:
            ValueError: priority 非法
        """
        priority_value = self._normalize_priority(priority)
        with self._session_factory() as session:
            stmt = (
                select(OutboxEntry)
                .where(OutboxEntry.priority == priority_value)
                .order_by(OutboxEntry.created_at.desc())
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    # ===== 状态机更新 =====

    def update_status(
        self,
        outbox_id: int,
        new_status: str | OutboxStatus,
    ) -> OutboxEntry:
        """更新 outbox 条目 status(状态机更新入口)。

        Args:
            outbox_id: OutboxEntry.id
            new_status: 目标 status(OutboxStatus 4 选 1)

        Returns:
            更新后的 OutboxEntry(已 refresh)

        Raises:
            ValueError: new_status 非法 / outbox_id 不存在
            TypeError: new_status 类型非法

        状态机转换规则(D4.8 范围):
            - pending_send → approved(显式批准,D5+ 业务调度器)
            - pending_send → cancelled(用户取消,D5+ 业务调度器)
            - approved → sent(SMTP 发送成功,D5+)
            - D4.8 范围:仅入库到 pending_send,update_status 留 D5+ 业务调度器调用
        """
        new_status_value = self._normalize_status(new_status)
        with self._session_factory() as session:
            row = session.get(OutboxEntry, outbox_id)
            if row is None:
                raise ValueError(
                    f"outbox_id={outbox_id} 不存在,无法 update_status 为 {new_status_value!r}"
                )
            row.status = new_status_value
            session.commit()
            session.refresh(row)
            return row

    # ===== 私有 helper(D4.7.3 v1.0.5 P2-1 范本: type 严判在 hash 前) =====

    @staticmethod
    def _normalize_status(value: Any) -> str:
        """严判 status 字符串(防 list/dict/set 触发 TypeError)。

        严判范本(D4.7.3 v1.0.5 P2-1):type() is str 在 in frozenset 前,
        拒 list / dict / set 等不可哈希 / 非 str 类型。
        """
        if type(value) is not str:
            raise TypeError(
                f"status 必须是 str 或 OutboxStatus 枚举,实际 {type(value).__name__}={value!r}"
            )
        if value not in _OUTBOX_STATUS_CHOICES:
            raise ValueError(
                f"status 必须是 OutboxStatus 4 选 1 {_OUTBOX_STATUS_CHOICES!r},实际 {value!r}"
            )
        return value

    @staticmethod
    def _normalize_priority(value: Any) -> str:
        """严判 priority 字符串(同上严判范本)。"""
        if type(value) is not str:
            raise TypeError(
                f"priority 必须是 str 或 OutboxPriority 枚举,实际 {type(value).__name__}={value!r}"
            )
        from my_ai_employee.core.models.outbox import _OUTBOX_PRIORITY_CHOICES

        if value not in _OUTBOX_PRIORITY_CHOICES:
            raise ValueError(
                f"priority 必须是 OutboxPriority 3 选 1 {_OUTBOX_PRIORITY_CHOICES!r},实际 {value!r}"
            )
        return value


__all__ = [
    "OutboxStore",
    "OutboxEmailDuplicateError",
]
