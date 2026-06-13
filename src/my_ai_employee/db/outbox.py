"""D4.8 — OutboxStore: outbox 表读写封装.

承接 D4.8.1 outbox migration 0004(11 字段 + UNIQUE + 2 索引 + 2 FK)
+ D4.8.2 OutboxEntry ORM(11 字段 + 3 个 StrEnum)
+ D5.2 outbox sending state migration 0005(无 DDL,业务层 StrEnum 4→6 +
  ALLOWED_TRANSITIONS 状态机白名单 + OutboxIllegalTransitionError + update_status from_status 严判)

设计(沿用 D4.3 EventStore 范本):
  - insert(): 走 D4.8 契约(入库 + IntegrityError 窄化 → 业务阻断)
  - by_email_id / by_status / by_priority: 3 类热路径查询
  - update_status(D5.2 新签名): 必传 from_status + ALLOWED_TRANSITIONS 白名单严判
  - 严判只放在 D4.8.4 Adapter 层(契约层 OutboxStore 接受已校验参数,不再二次严判)

D5.2 状态机白名单(B5 解封):
  - 6 状态 PENDING_SEND / APPROVED / SENDING / SENT / FAILED / CANCELLED
  - ALLOWED_TRANSITIONS 见 core/outbox.py
  - update_status(*, from_status) 必传 from_status + from_status == row.status 严判
  - 不在白名单内 → OutboxIllegalTransitionError(状态机漂移检测)

D3.3.3 教训应用:
  - except 范围窄化: 只接 sqlalchemy.exc.IntegrityError, 不接 SQLAlchemyError 基类
  - 失败状态透明化: UNIQUE(email_id) 冲突是正常业务阻断(走 record_store_business_blocked_and_emit),
    用 raise OutboxEmailDuplicateError 让 Adapter 上层接住
  - 反范本: D3.3.2 (SQLAlchemyError, _sqlcipher_dbapi.IntegrityError) 过宽,
    会把 OperationalError / DB 锁 / InterfaceError / DataError 误算为业务阻断,
    掩盖真实生产问题

D4.7.3 v1.0.5/v1.0.6 25 教训应用:
  - P1-1 跨字段校验: from_status == row.status(D5.2 from_status 必传严判)
  - P1-2 双向强一致: ALLOWED_TRANSITIONS 6 状态 × 各自目标集完整(无遗漏)
  - P2-1 type 严判: _normalize_status 严判 type() is str + in frozenset
  - 注释同步是契约一部分: 本文件状态机段同步 ALLOWED_TRANSITIONS(D5.2)
"""

from __future__ import annotations

import time
from typing import Any

import sqlcipher3.dbapi2 as _sqlcipher_dbapi  # D3.3.2 教训: 双层 except 防 SQLCipher dialect 不包装 dbapi 异常
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from my_ai_employee.core.outbox import (
    _OUTBOX_STATUS_CHOICES,
    ALLOWED_TRANSITIONS,
    OutboxEntry,
    OutboxStatus,
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


class OutboxIllegalTransitionError(Exception):
    """状态机非法转换异常(D5.2 B5 解封 — 防 cancelled → sent 等非法转换)。

    触发场景(任一):
      1. update_status 调用方 from_status 与 row.status 不一致(并发写状态漂移检测)
      2. update_status 调用方 from_status → new_status 不在 ALLOWED_TRANSITIONS 白名单
         (例 cancelled → sent, sent → anything, pending_send → sent 跳级)

    调用方(D5.3 EmailSendAdapter)按业务语义区分:
      - 状态漂移检测: 走 record_send_failure_and_emit(concurrent write,需 retry|escalate)
      - 白名单外转换: 走 record_send_business_blocked_and_emit(bug,需人工 review)

    Attributes:
        outbox_id: OutboxEntry.id
        from_status: 调用方传入的 from_status(可能与 row.status 不一致)
        to_status: 目标 status
        actual_status: 实际 row.status(可能与 from_status 不一致)
        allowed: from_status 的合法目标集(从 ALLOWED_TRANSITIONS 查)
    """

    def __init__(
        self,
        outbox_id: int,
        from_status: str,
        to_status: str,
        *,
        actual_status: str | None = None,
        allowed: frozenset[OutboxStatus] | None = None,
    ) -> None:
        self.outbox_id = outbox_id
        self.from_status = from_status
        self.to_status = to_status
        self.actual_status = actual_status
        self.allowed = allowed
        if actual_status is not None and actual_status != from_status:
            # 场景 1:状态漂移检测
            super().__init__(
                f"outbox_id={outbox_id} 状态机漂移: 调用方 from_status={from_status!r},"
                f"实际 row.status={actual_status!r} "
                f"(可能并发写导致,调用方应重读 row.status 再调 update_status)"
            )
        else:
            # 场景 2:白名单外转换
            allowed_str = sorted(s.value for s in allowed) if allowed is not None else "UNKNOWN"
            super().__init__(
                f"outbox_id={outbox_id} 状态机非法转换: {from_status!r} → {to_status!r} "
                f"(allowed from {from_status!r}: {allowed_str},见 ALLOWED_TRANSITIONS)"
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
        last_approved_at_ms: int | None = None,
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
            last_approved_at_ms: D5.6.3 P1-1 审批凭据(Unix epoch ms,默认 None =
                              "未审批",应用层 _approve_all_pending 写入 APPROVED 时传值)

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
                    last_approved_at_ms=last_approved_at_ms,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return row
            except (IntegrityError, _sqlcipher_dbapi.IntegrityError) as err:
                session.rollback()
                # 业务阻断: UNIQUE(email_id) 冲突 → 业务阻断入口
                # 严判:必须 UNIQUE 约束冲突才视为业务阻断
                # D3.3.2 教训: SQLCipher dialect 实际抛 sqlcipher3.dbapi2.IntegrityError(原始 err),
                #              sqlalchemy.exc.IntegrityError 反而是包装层(可能无 .orig)
                # D3.3.3 教训: 范围窄化, 拒 SQLAlchemyError 基类(会掩盖 OperationalError 等)
                err_str = str(getattr(err, "orig", err))
                if "UNIQUE constraint failed: outbox.email_id" in err_str:
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

        D5.5.3 修复旧积压永远进不了候选池(检查员 P1-1):
          修复前:`order_by(created_at DESC).limit(N)` → 只取最新 N 条,超 N 的旧条目
            永远进不了候选池(新增持续发生时老积压饿死)。
          修复后:`order_by(created_at ASC).limit(N)` → 严格按 FIFO 取最老 N 条,
            旧积压优先出,新邮件按到达顺序排队。
          业务影响:OutboxDispatcher 拉批时旧邮件不再被饿死,符合"先入先出"语义。

        Args:
            status: OutboxStatus 4 选 1(enum 或字符串,严判 + 归一)
            limit: 返回上限,默认 100(D5+ 调度器轮询典型场景)

        Returns:
            按 created_at ASC 排序的 OutboxEntry 列表(FIFO)

        Raises:
            ValueError: status 非法(不在 _OUTBOX_STATUS_CHOICES 4 选 1)
            TypeError: status 类型非法(非 str / OutboxStatus)
        """
        status_value = self._normalize_status(status)
        with self._session_factory() as session:
            stmt = (
                select(OutboxEntry)
                .where(OutboxEntry.status == status_value)
                .order_by(OutboxEntry.created_at.asc())  # D5.5.3 FIFO 严格升序
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    def by_priority(
        self,
        priority: str,
        limit: int = 100,
    ) -> list[OutboxEntry]:
        """按 priority 查多条(走 idx_outbox_priority_created_at 索引,O(log n))。

        D5.5.3:FIFO 一致性 — 与 by_status 保持相同排序方向(ASC)。
          旧积压优先出,新邮件按到达顺序排队。

        Args:
            priority: OutboxPriority 3 选 1(字符串,严判)
            limit: 返回上限,默认 100

        Returns:
            按 created_at ASC 排序的 OutboxEntry 列表(FIFO)

        Raises:
            ValueError: priority 非法
        """
        priority_value = self._normalize_priority(priority)
        with self._session_factory() as session:
            stmt = (
                select(OutboxEntry)
                .where(OutboxEntry.priority == priority_value)
                .order_by(OutboxEntry.created_at.asc())  # D5.5.3 FIFO 严格升序
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())

    # ===== 状态机更新(D5.2 — B5 解封,from_status 必传 + 白名单严判)=====

    def update_status(
        self,
        outbox_id: int,
        new_status: str | OutboxStatus,
        *,
        from_status: str | OutboxStatus,
        last_approved_at_ms: int | None = None,
    ) -> OutboxEntry:
        """更新 outbox 条目 status(D5.2 状态机更新入口 — 6 状态 × 白名单严判)。

        Args:
            outbox_id: OutboxEntry.id
            new_status: 目标 status(OutboxStatus 6 选 1)
            from_status: 调用方预期的当前 status(必传关键字,D5.2 严判一致性)
                         防止 concurrent 写导致状态机漂移(行已被其他调用方推到其他状态)
            last_approved_at_ms: D5.6.3 P1-1 审批凭据(Unix epoch ms)。
                必传规则:
                - new_status == APPROVED:必传,严判 type() is int(非 bool) + >= 0,
                  表示"此时刻被显式审批过"
                - new_status != APPROVED:必传 None(显式传 None,避免误传覆盖原审批时间戳),
                  row.last_approved_at_ms 保留原值(不动)
                写入 / 保留范本:
                - 写入: new_status == APPROVED 时 row.last_approved_at_ms = last_approved_at_ms
                - 保留: SENDING → SENT / SENDING → FAILED 时不动(避免重试时丢审批标记)
                - 用户取消 PENDING_SEND → CANCELLED:不动(从未审批过,保留 NULL)
                - 业务阻断 SENDING → CANCELLED:不动(已审批过,保留)
                - FAILED → APPROVED(D5.6.2 重试回路):必传(回填原审批时间戳或新的 now_ms,
                  调用方决策)

        Returns:
            更新后的 OutboxEntry(已 refresh)

        Raises:
            OutboxIllegalTransitionError: 状态机漂移(from_status != row.status)
                                          或 白名单外转换(ALLOWED_TRANSITIONS 不含 to_status)
            ValueError: new_status / from_status 非法枚举值 / outbox_id 不存在
                       或 last_approved_at_ms 必传规则违反(APPROVED 未传 / 非 APPROVED 误传)
            TypeError: new_status / from_status 类型非法 / last_approved_at_ms 非 int

        状态机白名单(ALLOWED_TRANSITIONS,D5.2 B5 解封 + D5.6.2 P1.2 扩 FAILED → APPROVED):
            PENDING_SEND → {SENDING, APPROVED, FAILED, CANCELLED}
            APPROVED     → {SENDING, FAILED, CANCELLED}
            SENDING      → {SENT, FAILED}
            SENT         → {}    (终态)
            FAILED       → {PENDING_SEND, APPROVED, CANCELLED}  # D5.6.2 加 APPROVED 直通
            CANCELLED    → {}    (终态)

        D5.2 决策(双层防御 — 工厂层 + 严判):
            1. from_status == row.status 严判 → 状态漂移检测(防 concurrent 写)
            2. ALLOWED_TRANSITIONS[from_status] ⊇ {to_status} 严判 → 白名单外转换
            3. 异常 OutboxIllegalTransitionError 含 actual_status / allowed 字段,
               调用方(D5.3 Adapter)按业务语义区分 concurrent write vs bug

        D5.6.3 P1-1 决策(审批凭据双层防御):
            1. last_approved_at_ms 必传规则(新_status == APPROVED 必传 / 其他必传 None)
            2. 严判 type() is int(非 bool) + >= 0
            3. 写入 / 保留逻辑:仅在 APPROVED 时写入,其他状态保留
        """
        new_status_value = self._normalize_status(new_status)
        from_status_value = self._normalize_status(from_status)
        with self._session_factory() as session:
            row = session.get(OutboxEntry, outbox_id)
            if row is None:
                raise ValueError(
                    f"outbox_id={outbox_id} 不存在,无法 update_status 为 {new_status_value!r}"
                )
            # D5.6.3 P1-1 严判:last_approved_at_ms 必传规则(必须在 row 存在后做,
            # 否则 nonexistent_id 测试期望"row 不存在"ValueError 而不是 last_approved_at_ms 错)
            # - new_status == APPROVED:必传 int(非 None) — 写入审批凭据
            # - new_status != APPROVED:必传 None(显式 None) — 不动 row.last_approved_at_ms
            if new_status_value == OutboxStatus.APPROVED.value:
                if last_approved_at_ms is None:
                    raise ValueError(
                        f"D5.6.3 P1-1 审批凭据:update_status(new_status=APPROVED) 必传 "
                        f"last_approved_at_ms(Unix epoch ms),实际 {last_approved_at_ms!r}"
                    )
                if (
                    type(last_approved_at_ms) is bool
                    or not isinstance(last_approved_at_ms, int)
                    or last_approved_at_ms < 0
                ):
                    raise ValueError(
                        f"D5.6.3 P1-1 审批凭据:last_approved_at_ms 必须是原生 int(非 bool) >= 0,"
                        f"实际 {type(last_approved_at_ms).__name__}={last_approved_at_ms!r}"
                    )
            else:
                if last_approved_at_ms is not None:
                    raise ValueError(
                        f"D5.6.3 P1-1 审批凭据:update_status(new_status={new_status_value!r}) "
                        f"时 last_approved_at_ms 必传 None(保留原审批时间戳),"
                        f"实际 {last_approved_at_ms!r}"
                    )
            # D5.2 严判 #1: 状态漂移检测(concurrent write 防护)
            if row.status != from_status_value:
                raise OutboxIllegalTransitionError(
                    outbox_id=outbox_id,
                    from_status=from_status_value,
                    to_status=new_status_value,
                    actual_status=row.status,
                )
            # D5.2 严判 #2: 白名单外转换严判
            from_enum = OutboxStatus(from_status_value)
            allowed = ALLOWED_TRANSITIONS[from_enum]
            new_enum = OutboxStatus(new_status_value)
            if new_enum not in allowed:
                raise OutboxIllegalTransitionError(
                    outbox_id=outbox_id,
                    from_status=from_status_value,
                    to_status=new_status_value,
                    allowed=allowed,
                )
            row.status = new_status_value
            # D5.6.3 P1-1 写入审批凭据:仅在 APPROVED 时写入,其他状态保留
            if new_status_value == OutboxStatus.APPROVED.value:
                # 严判已确保 last_approved_at_ms is not None
                assert last_approved_at_ms is not None  # noqa: S101
                row.last_approved_at_ms = last_approved_at_ms
            # else:不动 row.last_approved_at_ms(SENDING → SENT/FAILED/CANCELLED 等保留)
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
                f"status 必须是 OutboxStatus 6 选 1 {_OUTBOX_STATUS_CHOICES!r},实际 {value!r}"
            )
        return value

    @staticmethod
    def _normalize_priority(value: Any) -> str:
        """严判 priority 字符串(同上严判范本)。"""
        if type(value) is not str:
            raise TypeError(
                f"priority 必须是 str 或 OutboxPriority 枚举,实际 {type(value).__name__}={value!r}"
            )
        from my_ai_employee.core.outbox import _OUTBOX_PRIORITY_CHOICES

        if value not in _OUTBOX_PRIORITY_CHOICES:
            raise ValueError(
                f"priority 必须是 OutboxPriority 3 选 1 {_OUTBOX_PRIORITY_CHOICES!r},实际 {value!r}"
            )
        return value


__all__ = [
    "OutboxStore",
    "OutboxEmailDuplicateError",
    "OutboxIllegalTransitionError",  # D5.2 新增:状态机非法转换异常
]
