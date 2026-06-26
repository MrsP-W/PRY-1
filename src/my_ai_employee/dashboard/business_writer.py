"""L5 Dashboard BusinessWriter — 写操作 Protocol + Stub(沿 v0.2.53.14 设计).

本模块定义:
    - `AuditContext` 审计上下文 dataclass(actor/reason/source/timestamp_ms)
    - `WriteResult` 实际写入结果 dataclass(success/affected_id/error/...)
    - `WriteDecision` dry-run 决策 dataclass(write_executed=False 恒定)
    - `BusinessAction` 白名单常量(与 v0.2.53.11 ApprovalGate 契约对齐)
    - `BusinessWriter` Protocol 接口(dry_run + 4 类动作方法)
    - `BusinessWriterStub` 默认 Stub 实现(全返回 `write_not_implemented`)

边界(沿 v0.2.53.14 设计骨架):
    - 默认全 Stub,无真实写入
    - 不写 DB / 不发 SMTP / 不读 Keychain 明文
    - 所有 dry_run 响应保证 write_executed=False
    - 4 类动作方法实现抛出 NotImplementedError(占位,留 v0.2.53.17 接入)

承接:
    - v0.2.53.11 ApprovalGate 契约(`approval_gate.py:_decision()`)
    - v0.2.53.14 BusinessWriter 设计骨架(`docs/v0.2.53.14-...md`)
    - 撞坑 #65 opt-in 4 阶段范本(env gate + 默认 Stub + 失败降级)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol

from my_ai_employee.dashboard.action_contracts import (
    ACTION_FINANCE_DISMISS_ANOMALY,
    ACTION_NOTES_CONFIRM,
    ACTION_OUTBOX_APPROVE,
    ACTION_OUTBOX_CANCEL,
    SUPPORTED_ACTIONS,
)

# --- 4 类动作白名单(与 action_contracts 共用) ---


@dataclass(frozen=True, slots=True)
class AuditContext:
    """审计上下文 — 每一次写操作必须携带.

    边界(沿 v0.2.53.11 ApprovalGate 契约 + 撞坑 #64 公共 API 一致性):
        - actor ≤ 80 字符(超长 ValueError)
        - reason ≤ 240 字符(超长 ValueError)
        - source 默认 "dashboard"
        - timestamp_ms 默认 None(由 writer 实际写入时填充 now_ms)
    """

    actor: str
    reason: str
    source: str = "dashboard"
    timestamp_ms: int | None = None

    MAX_ACTOR_LEN: ClassVar[int] = 80
    MAX_REASON_LEN: ClassVar[int] = 240

    def __post_init__(self) -> None:
        if len(self.actor) > self.MAX_ACTOR_LEN:
            raise ValueError(
                f"actor 超长({len(self.actor)}>{self.MAX_ACTOR_LEN}):{self.actor[:40]}..."
            )
        if len(self.reason) > self.MAX_REASON_LEN:
            raise ValueError(
                f"reason 超长({len(self.reason)}>{self.MAX_REASON_LEN}):{self.reason[:40]}..."
            )

    @classmethod
    def default(cls) -> AuditContext:
        """默认审计上下文(沿 v0.2.53.11 actor 默认 'local_dashboard')."""
        return cls(actor="local_dashboard", reason="")


@dataclass(frozen=True, slots=True)
class WriteResult:
    """写操作实际结果 — 真实写入后由 Impl 返回.

    边界:
        - success=True 时 write_executed=True,affected_id 必填
        - success=False 时 write_executed=True(失败也算执行过),error 必填
        - audit_id 可选(后续 v0.2.53.20 落档 audit log 时填充)
    """

    success: bool
    affected_id: str | None
    error: str | None
    reason: str | None
    audit_id: str | None = None
    write_executed: bool = True


@dataclass(frozen=True, slots=True)
class WriteDecision:
    """dry-run 决策 — 不实际写入,只校验 + 预览.

    边界(沿 v0.2.53.11 `_decision()` 响应字段):
        - write_executed 恒为 False(dry-run 不真写)
        - action / target_id 由调用方传入
        - write_enabled = env+confirm 双门是否齐全
        - would_allow = writer 实现是否就绪(env+confirm+writer 全部齐全)
        - required 列出当前还缺什么(空 tuple = 完全就绪)
    """

    action: str
    target_id: str
    write_enabled: bool
    would_allow: bool
    write_executed: Literal[False]
    dry_run: bool
    audit: AuditContext
    error: str | None = None
    reason: str | None = None
    required: tuple[str, ...] = ()


class BusinessWriter(Protocol):
    """写操作 Protocol — 默认全 no-op,只接契约不接真实写入.

    4 类动作方法签名与 v0.2.53.11 ApprovalGate 白名单对齐.
    """

    def dry_run(
        self,
        action: str,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteDecision: ...

    def approve_outbox(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult: ...

    def cancel_outbox(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult: ...

    def confirm_note(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult: ...

    def dismiss_anomaly(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult: ...


class BusinessWriterStub:
    """默认 Stub 实现 — 所有动作返回 `write_not_implemented`.

    边界(沿撞坑 #65 + v0.2.53.6):
        - 默认全 Stub,无真实写入
        - dry_run 返回 WriteDecision(write_executed=False, would_allow=False)
        - 4 类动作方法抛 NotImplementedError(占位,留 v0.2.53.17 接入)
    """

    def __init__(self) -> None:
        pass

    def dry_run(
        self,
        action: str,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteDecision:
        """dry-run 默认决策 — 全部未启用."""
        return WriteDecision(
            action=action,
            target_id=target_id,
            write_enabled=False,
            would_allow=False,
            write_executed=False,
            dry_run=True,
            audit=audit,
            error="write_not_implemented",
            reason="BusinessWriter 默认 Stub;需 v0.2.53.17+ 接入 BusinessWriterImpl",
            required=(
                "DASHBOARD_WRITE_API=1",
                "confirm_text=CONFIRM_WRITE",
                "BUSINESS_WRITER_ENABLED=1",
                "business_writer_implementation",
            ),
        )

    def approve_outbox(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """占位 — Stub 不实现,留 v0.2.53.17 接入."""
        raise NotImplementedError(
            "BusinessWriterStub.approve_outbox 占位 · 留 v0.2.53.17 BusinessWriterImpl 接入"
        )

    def cancel_outbox(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """占位 — Stub 不实现,留 v0.2.53.17 接入."""
        raise NotImplementedError(
            "BusinessWriterStub.cancel_outbox 占位 · 留 v0.2.53.17 BusinessWriterImpl 接入"
        )

    def confirm_note(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """占位 — Stub 不实现,留 v0.2.53.17 接入."""
        raise NotImplementedError(
            "BusinessWriterStub.confirm_note 占位 · 留 v0.2.53.17 BusinessWriterImpl 接入"
        )

    def dismiss_anomaly(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """占位 — Stub 不实现,留 v0.2.53.17 接入(同时需要 v0.2.53.16 AnomalyDismissalService)."""
        raise NotImplementedError(
            "BusinessWriterStub.dismiss_anomaly 占位 · 留 v0.2.53.17 BusinessWriterImpl 接入"
        )

    @classmethod
    def get_default_stub(cls) -> BusinessWriterStub:
        """默认 Stub 工厂(沿 `OutboxDraftServiceStub.get_default_stub` 范本)."""
        return cls()


__all__ = [
    "ACTION_FINANCE_DISMISS_ANOMALY",
    "ACTION_NOTES_CONFIRM",
    "ACTION_OUTBOX_APPROVE",
    "ACTION_OUTBOX_CANCEL",
    "SUPPORTED_ACTIONS",
    "AuditContext",
    "BusinessWriter",
    "BusinessWriterStub",
    "WriteDecision",
    "WriteResult",
]
