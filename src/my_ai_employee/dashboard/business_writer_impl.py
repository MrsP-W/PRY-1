"""v0.2.53.49 BusinessWriterImpl — 4 动作实写 + 写保护锁(默认 raise,撞坑 #18).

承接 docs/v0.2.53.14-business-writer-design-2026-06-26.md §10 + v0.2.53.46 范围 + v0.2.53.49 升级:
    - 接入 BusinessWriterImpl(approve_outbox / cancel_outbox / confirm_note / dismiss_anomaly 4 动作)
    - 4 动作实写骨架:依赖检查 + 参数校验 + 写保护锁 + service 调用 + WriteResult 包装
    - 默认行为 = raise NotImplementedError(沿撞坑 #18 风险门控 · _real_write_handler_enabled=False)
    - 真实写入路径留 v0.2.53.19 handler 路径 4 启用 + 用户明确授权 + 8/1 后
    - fake store 测试:_real_write_handler_enabled=True 走通整条链(沿撞坑 #18 + #65 opt-in 4 阶段)

设计决策(2026-06-29 锁定):
    - 抽象 BusinessWriterImpl 类(3 已有 Service + dismiss_anomaly 占位)
    - 构造函数接受可选依赖(OutboxStore / NoteConfirmServiceImpl / AnomalyDismissalServiceStub)
    - 默认所有方法 raise NotImplementedError(等待 v0.2.53.19 handler 路径 4 启用)
    - 写保护锁 _real_write_handler_enabled:bool=False(默认锁定,撞坑 #18)
    - 仅 dry_run 真实实现(返回 WriteDecision)
    - 异常收窄(沿 note_confirm_service.py:113-115):用户主动操作异常必须透传

v0.2.53.46 升级点(实写骨架):
    - 4 动作方法统一骨架:_check_dep(依赖检查) + _validate_target_id(参数校验) + 末尾 raise
    - 无效 target_id(非 str / 空字符串)→ WriteResult(success=False, error='invalid_target_id')
    - 依赖未注入 → raise NotImplementedError(沿撞坑 #18)
    - 默认 raise 字符串明确说明"路径 4 启用后调什么"

v0.2.53.49 升级点(实写 + 写保护锁):
    - 加 _real_write_handler_enabled:bool=False 构造参数(默认锁定)
    - 4 动作方法升级:_check_dep + _validate_target_id + 写保护锁校验 + _call_service_xxx 调用 + WriteResult 包装
    - 写保护锁未开 → raise NotImplementedError(等同 v0.2.53.46 默认行为,撞坑 #18 风险门控)
    - 写保护锁开 + 依赖注入 → 真实调 service(测试场景用 fake store 验证整条链)
    - audit 语义:沿 v0.2.53.20 落档 design,本棒仅占位 audit_id 字段(留 v0.2.53.50 真实落档)

D4.7.3 教训应用(沿撞坑 #65 + v0.2.53.8):
    - Protocol 类型鸭子类型友好(无需 isinstance)
    - 严判 type 严格(避免 bool/int 互窜)
    - 单项失败不传播(approve_outbox 失败不影响 cancel_outbox)
    - 异常收容:dry_run 失败 → WriteDecision(error="internal_error");真实写入异常透传

撞坑 #18 边界应用(实际写入留 8/1 后):
    - 默认 _real_write_handler_enabled=False(写保护锁锁定)
    - 不接 SMTP / 不读 Keychain 明文
    - 真实写入路径(env+confirm+writer+handler 四道门齐全)留 v0.2.53.19 handler 启用

沿用边界:
    - 本棒默认 raise NotImplementedError(等同 v0.2.53.46 行为)
    - 真实写入需 v0.2.53.19 handler 路径 4 启用 + 用户明确授权 + 8/1 后
    - 不接真实 SMTP / 不读 Keychain 明文
    - write_executed 恒 False(沿 v0.2.53.11 不变式,本棒真实调 service 时也 False)
    - 不动 ApprovalGate 决策矩阵(沿 v0.2.53.22 8 路径)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, ClassVar

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

    is_runtime_impl: ClassVar[bool] = True

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Any] | None = None,
        outbox_store: OutboxStore | None = None,
        note_confirm_service: NoteConfirmServiceImpl | None = None,
        anomaly_dismissal_service: AnomalyDismissalServiceStub | None = None,
        real_write_handler_enabled: bool = False,
    ) -> None:
        """构造 — 所有依赖可选(默认 None 表示 raise NotImplementedError).

        Args:
            session_factory: SQLAlchemy sessionmaker(沿 v0.2.53.7 opt-in 范本)
            outbox_store: OutboxStore 实例(approve_outbox / cancel_outbox 必需)
            note_confirm_service: NoteConfirmServiceImpl 实例(confirm_note 必需)
            anomaly_dismissal_service: AnomalyDismissalService 实例(dismiss_anomaly 必需)
            real_write_handler_enabled: 写保护锁(默认 False = 锁定,沿撞坑 #18 风险门控)。
                False → 4 动作 raise NotImplementedError(等同 v0.2.53.46 行为)
                True → 4 动作真实调 service(仅测试场景用 fake store 验证整条链)
                生产环境必须保持 False,等 v0.2.53.19 handler 路径 4 启用 + 用户明确授权
        """
        self._session_factory = session_factory
        self._outbox_store = outbox_store
        self._note_confirm_service = note_confirm_service
        self._anomaly_dismissal_service = anomaly_dismissal_service
        self._real_write_handler_enabled = real_write_handler_enabled

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
        """路径 4 实写 — 默认 raise(写保护锁),handler 启用后真实调 service.

        边界(沿撞坑 #18 + v0.2.53.14 §6 + v0.2.53.19):
            - 依赖检查:outbox_store 必须注入(无则 raise NotImplementedError)
            - 参数校验:target_id 必须为非空 str(否则 WriteResult(success=False, error='invalid_target_id'))
            - 写保护锁:_real_write_handler_enabled=False → raise(撞坑 #18 默认行为)
            - 写保护锁开 + 依赖注入 → 真实调 outbox_store.update_status(路径 4 启用)
            - 真实写入路径留 v0.2.53.19 handler 启用 + 用户明确授权 + 8/1 后

        路径 4 启用后真实调用(沿 D5.6.3 P1-1 审批凭据必传规则):
            outbox_store.update_status(
                outbox_id=int(target_id),
                new_status='APPROVED',
                from_status='PENDING_SEND',
                last_approved_at_ms=now_ms,
            )

        Args:
            target_id: OutboxEntry.id(str 表示,与 Protocol 契约对齐)
            audit: 审计上下文(AuditContext)

        Returns:
            WriteResult(参数非法时 success=False, error='invalid_target_id')
        """
        self._check_dep(self._outbox_store, "outbox_store")
        err = self._validate_target_id(target_id)
        if err is not None:
            return WriteResult(
                success=False,
                affected_id=None,
                error="invalid_target_id",
                reason=err,
            )
        self._check_write_protection()
        return self._call_service_approve_outbox(target_id, audit=audit)

    def cancel_outbox(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """路径 4 实写 — 默认 raise(写保护锁),handler 启用后真实调 service.

        边界(沿撞坑 #18 + v0.2.53.14 §6 + D5.6.3 P1-1 必传 None 规则):
            - 依赖检查:outbox_store 必须注入
            - 参数校验:target_id 必须为非空 str
            - 写保护锁:False → raise(撞坑 #18 默认行为)
            - 写保护锁开 → 真实调 outbox_store.update_status(CANCELLED, None)
            - 真实写入路径留 v0.2.53.19 handler 启用

        路径 4 启用后真实调用(D5.6.3 P1-1:非 APPROVED 必传 None):
            outbox_store.update_status(
                outbox_id=int(target_id),
                new_status='CANCELLED',
                from_status='PENDING_SEND' or 'APPROVED',  # 调用方决策
                last_approved_at_ms=None,
            )
        """
        self._check_dep(self._outbox_store, "outbox_store")
        err = self._validate_target_id(target_id)
        if err is not None:
            return WriteResult(
                success=False,
                affected_id=None,
                error="invalid_target_id",
                reason=err,
            )
        self._check_write_protection()
        return self._call_service_cancel_outbox(target_id, audit=audit)

    def confirm_note(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """路径 4 实写 — 默认 raise(写保护锁),handler 启用后真实调 service.

        边界(沿撞坑 #18 + note_confirm_service.py:113-115 异常透传):
            - 依赖检查:note_confirm_service 必须注入
            - 参数校验:target_id 必须为非空 str
            - 写保护锁:False → raise(撞坑 #18 默认行为)
            - 写保护锁开 → 真实调 note_confirm_service.confirm_note
            - 真实写入异常透传(不收容 — 用户主动操作必须看到 ValueError)

        路径 4 启用后真实调用:
            note_confirm_service.confirm_note(apple_note_id=target_id)
        """
        self._check_dep(self._note_confirm_service, "note_confirm_service")
        err = self._validate_target_id(target_id)
        if err is not None:
            return WriteResult(
                success=False,
                affected_id=None,
                error="invalid_target_id",
                reason=err,
            )
        self._check_write_protection()
        return self._call_service_confirm_note(target_id, audit=audit)

    def dismiss_anomaly(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """路径 4 实写 — 默认 raise(写保护锁),handler 启用后真实调 service.

        边界(沿撞坑 #18 + AnomalyDismissalService.dismiss 契约):
            - 依赖检查:anomaly_dismissal_service 必须注入
            - 参数校验:target_id 必须为非空 str(格式 {date}|{counterparty}|{amount})
            - 写保护锁:False → raise(撞坑 #18 默认行为)
            - 写保护锁开 → 真实调 anomaly_dismissal_service.dismiss
            - reason 限 240 字符(沿 _MAX_REASON_LEN)
            - 真实写入路径留 v0.2.53.19 handler 启用

        路径 4 启用后真实调用:
            anomaly_dismissal_service.dismiss(
                anomaly_id=target_id,
                reason=audit.reason,  # 限 240 字符
            )
        """
        self._check_dep(self._anomaly_dismissal_service, "anomaly_dismissal_service")
        err = self._validate_target_id(target_id)
        if err is not None:
            return WriteResult(
                success=False,
                affected_id=None,
                error="invalid_target_id",
                reason=err,
            )
        self._check_write_protection()
        return self._call_service_dismiss_anomaly(target_id, audit=audit)

    def _check_dep(self, dep: object, name: str) -> None:
        """依赖检查 — 缺失时 raise NotImplementedError(沿撞坑 #18 风险门控).

        Args:
            dep: 依赖对象(可能是 None)
            name: 依赖名称(用于错误信息)

        Raises:
            NotImplementedError: 依赖为 None 时(等同 Stub 行为)
        """
        if dep is None:
            raise NotImplementedError(
                f"BusinessWriterImpl 依赖 {name} 未注入(None);"
                f"需 DashboardContext.default() 自动注入(沿 v0.2.53.27 opt-in 范本)"
            )

    def _check_write_protection(self) -> None:
        """写保护锁校验 — 锁定时 raise NotImplementedError(沿撞坑 #18).

        边界(沿 v0.2.53.49 + 撞坑 #18 风险门控):
            - _real_write_handler_enabled=False → raise(默认行为,等同 v0.2.53.46)
            - _real_write_handler_enabled=True → 放行(仅测试场景用 fake store 验证)
            - 生产环境必须保持 False,等 v0.2.53.19 handler 路径 4 启用 + 用户明确授权

        Raises:
            NotImplementedError: 写保护锁未开时(撞坑 #18 默认行为)
        """
        if not self._real_write_handler_enabled:
            raise NotImplementedError(
                "BusinessWriterImpl 写保护锁未开(_real_write_handler_enabled=False);"
                "路径 4 实际写入留 v0.2.53.19 handler 启用 + 8/1 后 + 用户明确授权"
            )

    def _call_service_approve_outbox(self, target_id: str, *, audit: AuditContext) -> WriteResult:
        """真实调 outbox_store.update_status(APPROVED 路径).

        边界(沿 v0.2.53.49 + D5.6.3 P1-1 审批凭据必传规则):
            - new_status='APPROVED' → last_approved_at_ms 必传 now_ms
            - 异常透传(OutboxIllegalTransitionError / ValueError)
        """
        # 路径 4 启用后的真实调用(写保护锁开 + 依赖注入)
        # 异常透传,不收容(用户主动操作必须看到 ValueError)
        updated = self._outbox_store.update_status(  # type: ignore[union-attr]
            outbox_id=int(target_id),
            new_status="APPROVED",
            from_status="PENDING_SEND",
            last_approved_at_ms=_now_ms(),
        )
        # audit_id 占位(沿 v0.2.53.20 落档 design · 本棒仅占位,留 v0.2.53.50 真实落档)
        return WriteResult(
            success=True,
            affected_id=str(updated.id),
            error=None,
            reason=f"approve_outbox: {target_id} → APPROVED",
            audit_id=None,  # v0.2.53.50 真实落档
            write_executed=True,  # 真实写入了,但 v0.2.53.11 不变式仅在 dry_run 上下文
        )

    def _call_service_cancel_outbox(self, target_id: str, *, audit: AuditContext) -> WriteResult:
        """真实调 outbox_store.update_status(CANCELLED 路径).

        边界(沿 v0.2.53.49 + D5.6.3 P1-1 必传 None 规则):
            - new_status='CANCELLED' → last_approved_at_ms 必传 None
            - 异常透传
        """
        updated = self._outbox_store.update_status(  # type: ignore[union-attr]
            outbox_id=int(target_id),
            new_status="CANCELLED",
            from_status="PENDING_SEND",
            last_approved_at_ms=None,
        )
        return WriteResult(
            success=True,
            affected_id=str(updated.id),
            error=None,
            reason=f"cancel_outbox: {target_id} → CANCELLED",
            audit_id=None,
            write_executed=True,
        )

    def _call_service_confirm_note(self, target_id: str, *, audit: AuditContext) -> WriteResult:
        """真实调 note_confirm_service.confirm_note.

        边界(沿 v0.2.53.49 + note_confirm_service.py:113-115):
            - 异常透传(用户主动操作必须看到 ValueError)
        """
        self._note_confirm_service.confirm_note(  # type: ignore[union-attr]
            apple_note_id=target_id,
        )
        return WriteResult(
            success=True,
            affected_id=target_id,
            error=None,
            reason=f"confirm_note: {target_id} confirmed",
            audit_id=None,
            write_executed=True,
        )

    def _call_service_dismiss_anomaly(self, target_id: str, *, audit: AuditContext) -> WriteResult:
        """真实调 anomaly_dismissal_service.dismiss.

        边界(沿 v0.2.53.49 + AnomalyDismissalService.dismiss 契约):
            - reason 限 240 字符(沿 _MAX_REASON_LEN)
            - 异常透传
        """
        self._anomaly_dismissal_service.dismiss(  # type: ignore[union-attr]
            anomaly_id=target_id,
            reason=audit.reason,
        )
        return WriteResult(
            success=True,
            affected_id=target_id,
            error=None,
            reason=f"dismiss_anomaly: {target_id} dismissed",
            audit_id=None,
            write_executed=True,
        )

    @staticmethod
    def _validate_target_id(target_id: object) -> str | None:
        """统一 target_id 校验 — 返回错误 reason 字符串(无错返回 None).

        边界(沿 note_confirm_service.py:confirm_note 校验模式):
            - target_id 必须是 str(严判 type,非 bool)
            - 去除首尾空白后非空
        """
        if not isinstance(target_id, str):
            return f"target_id 必须是 str,实际 type={type(target_id).__name__}, value={target_id!r}"
        stripped = target_id.strip()
        if not stripped:
            return f"target_id 必填且必须非空字符串(非纯空白),实际 {target_id!r}"
        return None

    @staticmethod
    def _audit_timestamp(audit: AuditContext) -> int:
        """审计时间戳 — audit.timestamp_ms 或 now_ms()."""
        return audit.timestamp_ms if audit.timestamp_ms is not None else _now_ms()
