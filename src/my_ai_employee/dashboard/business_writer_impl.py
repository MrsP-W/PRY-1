"""v0.2.53.51 BusinessWriterImpl — 4 动作实写 + 写保护锁 + audit 真实落档.

承接 docs/v0.2.53.14-business-writer-design-2026-06-26.md §10 + v0.2.53.46 范围 + v0.2.53.49 写保护锁
+ v0.2.53.51 audit 真实落档:
    - 接入 BusinessWriterImpl(approve_outbox / cancel_outbox / confirm_note / dismiss_anomaly 4 动作)
    - 4 动作实写骨架:依赖检查 + 参数校验 + 写保护锁 + service 调用 + audit 落档 + WriteResult 包装
    - 默认行为 = raise NotImplementedError(沿撞坑 #18 风险门控 · _real_write_handler_enabled=False)
    - Path 4 实写路径已提前接通,但必须写保护锁 + 第 5 门 + 用户确认全齐
    - audit 落档:写保护锁开 + 真实 service 调用(成功/失败)都落档;dry-run / 写保护锁 raise 不落档

设计决策(2026-06-29 锁定):
    - 抽象 BusinessWriterImpl 类(3 已有 Service + dismiss_anomaly + audit_store)
    - 构造函数接受可选依赖(OutboxStore / NoteConfirmServiceImpl / AnomalyDismissalServiceStub / ApprovalGateAuditStore)
    - 默认所有方法 raise NotImplementedError(等待显式五门全开)
    - 写保护锁 _real_write_handler_enabled:bool=False(默认锁定,撞坑 #18)
    - 仅 dry_run 真实实现(返回 WriteDecision)
    - 异常收窄(沿 note_confirm_service.py:113-115):用户主动操作异常必须透传
    - audit 落档:沿 v0.2.53.20 §5.3 design,撞坑 #18 风险门控 + 撞坑 #65 opt-in 4 阶段

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
    - audit 语义:沿 v0.2.53.20 落档 design,本棒仅占位 audit_id 字段

v0.2.53.51 升级点(audit 真实落档):
    - 构造函数加 audit_store: ApprovalGateAuditStore | None = None(可选,撞坑 #65 默认 Stub)
    - 4 动作方法升级:写保护锁开 + 真实 service 调用后,记录 audit
    - 成功路径:_call_service_xxx 返回值写入 audit(success=True, affected_id)
    - 失败路径:try/except 收容,service 抛异常时记录 audit(success=False, error)
    - WriteResult.audit_id 字段从 None 升级为真实 audit_id 字符串(格式 "audit:{id}")
    - 写保护锁 raise / dry-run / 依赖未注入 / invalid_target_id 都不落档

D4.7.3 教训应用(沿撞坑 #65 + v0.2.53.8):
    - Protocol 类型鸭子类型友好(无需 isinstance)
    - 严判 type 严格(避免 bool/int 互窜)
    - 单项失败不传播(approve_outbox 失败不影响 cancel_outbox)
    - 异常收容:dry_run 失败 → WriteDecision(error="internal_error");真实写入异常透传
    - audit 落档失败:返回 audit_id=None,但不抛异常(撞坑 #18 「日志语义」)

撞坑 #18 边界应用(Path 4 提前接通后的默认锁定):
    - 默认 _real_write_handler_enabled=False(写保护锁锁定)
    - 不接 SMTP / 不读 Keychain 明文
    - 真实写入路径需 env+confirm+writer+handler+ENABLE_PATH_4_WRITE 五门齐全
    - audit 落档仅在写保护锁开 + 真实 service 调用后发生(撞坑 #18 「日志」语义)

撞坑 #64 公共 API 一致性:
    - audit_id 字符串格式 "audit:{id}" 与 anomaly_dismissals "dismissal:{id}" 对齐
    - audit_store 是可选构造参数(默认 None = ApprovalGateAuditStoreStub,撞坑 #65 范本)

撞坑 #65 opt-in 4 阶段范本(env 门控 + 默认 Stub + 单项失败降级 + 不动 ApprovalGate 决策矩阵):
    - audit_store 默认 None → ApprovalGateAuditStoreStub(等效 is_enabled=False)
    - DashboardContext.default() 在 DASHBOARD_REAL_DB=1 时尝试构造 InMemoryApprovalGateAuditStore
    - 单项失败静默降级 Stub(沿 v0.2.53.7 范本)

沿用边界:
    - 默认 raise NotImplementedError(等同 v0.2.53.46 行为)
    - 真实写入需 Path 4 handler + 写保护锁 + 第 5 门 + 用户明确授权全齐
    - 不接真实 SMTP / 不读 Keychain 明文
    - write_executed 在 dry-run 恒 False;真实 service 调用后返回 True
    - 不动 ApprovalGate 决策矩阵(沿 v0.2.53.22 8 路径)
    - dry-run 不落档(沿 v0.2.53.51 范本)
    - 写保护锁 raise 不落档(沿 v0.2.53.51 范本)
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any, ClassVar

from my_ai_employee.dashboard.action_contracts import is_supported_action
from my_ai_employee.dashboard.business_writer import (
    AuditContext,
    WriteDecision,
    WriteResult,
)
from my_ai_employee.menu_bar.approval_gate_audit import (
    ApprovalGateAuditStore,
    ApprovalGateAuditStoreStub,
    AuditRecord,
    AuditRecordResult,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from my_ai_employee.db.outbox import OutboxStore
    from my_ai_employee.menu_bar.anomaly_dismissal_service import AnomalyDismissalServiceStub
    from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl


def _now_ms() -> int:
    """Unix epoch 毫秒时间戳(沿 v0.2.53.11 actor 默认值时间戳)."""
    return int(time.time() * 1000)


ENABLE_PATH_4_WRITE_ENV = "ENABLE_PATH_4_WRITE"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


def _is_enable_path_4_write_enabled() -> bool:
    """第 5 门 env 判定 — 默认关闭,仅识别 truthy 字面量."""
    raw = os.environ.get(ENABLE_PATH_4_WRITE_ENV, "").strip().lower()
    return raw in _TRUTHY_ENV_VALUES


class BusinessWriterImpl:
    """BusinessWriter 真实实现骨架 — 默认所有方法 raise NotImplementedError.

    边界(沿撞坑 #65 + v0.2.53.14 设计 + v0.2.53.17 范围 + v0.2.53.51 audit 落档):
        - 默认行为 = raise NotImplementedError(等同 Stub)
        - 真实写入路径留 v0.2.53.19 handler 启用
        - 单项失败不传播(dry_run 内 try/except 容错)
        - 异常收窄:真实写入异常透传(沿 note_confirm_service.py:113-115)
        - 不接 SMTP / 不读 Keychain 明文
        - audit 落档:写保护锁开 + 真实 service 调用后(成功/失败)落档;dry-run / 写保护锁 raise 不落档
    """

    is_runtime_impl: ClassVar[bool] = True

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Any] | None = None,
        outbox_store: OutboxStore | None = None,
        note_confirm_service: NoteConfirmServiceImpl | None = None,
        anomaly_dismissal_service: AnomalyDismissalServiceStub | None = None,
        audit_store: ApprovalGateAuditStore | None = None,
        real_write_handler_enabled: bool = False,
        enable_path_4_write: bool | None = None,
    ) -> None:
        """构造 — 所有依赖可选(默认 None 表示 raise NotImplementedError).

        Args:
            session_factory: SQLAlchemy sessionmaker(沿 v0.2.53.7 opt-in 范本)
            outbox_store: OutboxStore 实例(approve_outbox / cancel_outbox 必需)
            note_confirm_service: NoteConfirmServiceImpl 实例(confirm_note 必需)
            anomaly_dismissal_service: AnomalyDismissalService 实例(dismiss_anomaly 必需)
            audit_store: ApprovalGateAuditStore 实例(可选,默认 None = Stub,撞坑 #65 范本)
            real_write_handler_enabled: 写保护锁(默认 False = 锁定,沿撞坑 #18 风险门控)。
                False → 4 动作 raise NotImplementedError(等同 v0.2.53.46 行为)
                True → 4 动作真实调 service(仅测试场景用 fake store 验证整条链)
                生产环境必须只在第 5 门 + POST 确认 + 用户明确授权齐全时开启
            enable_path_4_write: 第 5 门。None 表示读取 `ENABLE_PATH_4_WRITE` env;
                True 表示测试/显式注入放行;False 表示锁定。
        """
        self._session_factory = session_factory
        self._outbox_store = outbox_store
        self._note_confirm_service = note_confirm_service
        self._anomaly_dismissal_service = anomaly_dismissal_service
        # 撞坑 #65 opt-in 4 阶段:audit_store 默认 None → ApprovalGateAuditStoreStub
        self._audit_store: ApprovalGateAuditStore = (
            audit_store if audit_store is not None else ApprovalGateAuditStoreStub()
        )
        self._real_write_handler_enabled = real_write_handler_enabled
        self._enable_path_4_write = (
            _is_enable_path_4_write_enabled()
            if enable_path_4_write is None
            else enable_path_4_write
        )

    def dry_run(
        self,
        action: str,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteDecision:
        """dry-run 决策 — 默认 would_allow=False(等待 v0.2.53.19 启用).

        边界(沿 v0.2.53.14 §2.1 + v0.2.53.51 audit 不落档):
            - 4 类动作白名单严判(未知 action → error="unsupported_action")
            - 默认 would_allow=False(Impl 已构造但 handler 未启用)
            - write_executed=False 恒定
            - required 列出当前还缺什么
            - dry-run 不落档(沿 v0.2.53.51 范本 · 撞坑 #18 「日志」语义)
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

            required = [
                "DASHBOARD_WRITE_API=1",
                "confirm_text=CONFIRM_WRITE",
                "BUSINESS_WRITER_ENABLED=1",
            ]
            if not self._real_write_handler_enabled:
                required.append("real_write_handler_enabled")
            if not self._enable_path_4_write:
                required.append(f"{ENABLE_PATH_4_WRITE_ENV}=1")
            write_ready = self._real_write_handler_enabled and self._enable_path_4_write
            return WriteDecision(
                action=action,
                target_id=target_id,
                write_enabled=write_ready,
                would_allow=write_ready,
                write_executed=False,
                dry_run=True,
                audit=audit,
                error=None if write_ready else "write_not_implemented",
                reason=(
                    "BusinessWriterImpl 5 门已齐,可执行 Path 4 实写"
                    if write_ready
                    else "BusinessWriterImpl 已构造,Path 4 实写门未全开"
                ),
                required=tuple(required),
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
        """路径 4 实写 — 默认 raise(写保护锁),handler 启用后真实调 service + audit 落档.

        边界(沿撞坑 #18 + v0.2.53.14 §6 + v0.2.53.19 + v0.2.53.51 audit 落档):
            - 参数校验:target_id 必须为非空 str(否则 WriteResult(success=False),无 audit)
            - 写保护锁:_real_write_handler_enabled=False → raise(撞坑 #18 默认行为,无 audit)
            - 依赖检查:outbox_store 必须注入(无则 raise NotImplementedError,无 audit)
            - 写保护锁开 + 依赖注入 → 真实调 outbox_store.update_status(路径 4 启用)
            - 成功后 audit 落档(success=True, affected_id, audit_id 真实字符串)
            - 失败后 audit 落档(success=False, error, audit_id 真实字符串)
            - 真实写入路径需 Path 4 handler + 第 5 门 + 用户明确授权全齐

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
        err = self._validate_target_id(target_id)
        if err is not None:
            return WriteResult(
                success=False,
                affected_id=None,
                error="invalid_target_id",
                reason=err,
            )
        self._check_write_protection()
        self._check_dep(self._outbox_store, "outbox_store")
        return self._call_service_approve_outbox(target_id, audit=audit)

    def cancel_outbox(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """路径 4 实写 — 默认 raise(写保护锁),handler 启用后真实调 service + audit 落档.

        边界(沿撞坑 #18 + v0.2.53.14 §6 + D5.6.3 P1-1 必传 None 规则 + v0.2.53.51 audit 落档):
            - 参数校验:target_id 必须为非空 str(否则 WriteResult(success=False),无 audit)
            - 写保护锁:False → raise(撞坑 #18 默认行为,无 audit)
            - 依赖检查:outbox_store 必须注入(无则 raise NotImplementedError,无 audit)
            - 写保护锁开 → 真实调 outbox_store.update_status(CANCELLED, None)
            - 成功后 audit 落档(success=True, affected_id)
            - 失败后 audit 落档(success=False, error)
            - 真实写入路径留 v0.2.53.19 handler 启用

        路径 4 启用后真实调用(D5.6.3 P1-1:非 APPROVED 必传 None):
            outbox_store.update_status(
                outbox_id=int(target_id),
                new_status='CANCELLED',
                from_status='PENDING_SEND' or 'APPROVED',  # 调用方决策
                last_approved_at_ms=None,
            )
        """
        err = self._validate_target_id(target_id)
        if err is not None:
            return WriteResult(
                success=False,
                affected_id=None,
                error="invalid_target_id",
                reason=err,
            )
        self._check_write_protection()
        self._check_dep(self._outbox_store, "outbox_store")
        return self._call_service_cancel_outbox(target_id, audit=audit)

    def confirm_note(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """路径 4 实写 — 默认 raise(写保护锁),handler 启用后真实调 service + audit 落档.

        边界(沿撞坑 #18 + note_confirm_service.py:113-115 异常透传 + v0.2.53.51 audit 落档):
            - 参数校验:target_id 必须为非空 str(否则 WriteResult(success=False),无 audit)
            - 写保护锁:False → raise(撞坑 #18 默认行为,无 audit)
            - 依赖检查:note_confirm_service 必须注入(无则 raise NotImplementedError,无 audit)
            - 写保护锁开 → 真实调 note_confirm_service.confirm_note
            - 成功后 audit 落档(success=True, affected_id=target_id)
            - 失败后 audit 落档(success=False, error)
            - 真实写入异常透传(不收容 — 用户主动操作必须看到 ValueError)
        """
        err = self._validate_target_id(target_id)
        if err is not None:
            return WriteResult(
                success=False,
                affected_id=None,
                error="invalid_target_id",
                reason=err,
            )
        self._check_write_protection()
        self._check_dep(self._note_confirm_service, "note_confirm_service")
        return self._call_service_confirm_note(target_id, audit=audit)

    def dismiss_anomaly(
        self,
        target_id: str,
        *,
        audit: AuditContext,
    ) -> WriteResult:
        """路径 4 实写 — 默认 raise(写保护锁),handler 启用后真实调 service + audit 落档.

        边界(沿撞坑 #18 + AnomalyDismissalService.dismiss 契约 + v0.2.53.51 audit 落档):
            - 参数校验:target_id 必须为非空 str(格式 {date}|{counterparty}|{amount})
            - 写保护锁:False → raise(撞坑 #18 默认行为,无 audit)
            - 依赖检查:anomaly_dismissal_service 必须注入(无则 raise NotImplementedError,无 audit)
            - 写保护锁开 → 真实调 anomaly_dismissal_service.dismiss
            - 成功后 audit 落档(success=True, affected_id=target_id)
            - 失败后 audit 落档(success=False, error)
            - reason 限 240 字符(沿 _MAX_REASON_LEN)
            - 真实写入路径留 v0.2.53.19 handler 启用
        """
        err = self._validate_target_id(target_id)
        if err is not None:
            return WriteResult(
                success=False,
                affected_id=None,
                error="invalid_target_id",
                reason=err,
            )
        self._check_write_protection()
        self._check_dep(self._anomaly_dismissal_service, "anomaly_dismissal_service")
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
            - 生产环境必须只在第 5 门 + POST 确认 + 用户明确授权齐全时开启
            - 写保护锁 raise 不落档(沿 v0.2.53.51 范本 · 撞坑 #18 「日志」语义)

        Raises:
            NotImplementedError: 写保护锁未开时(撞坑 #18 默认行为)
        """
        if not self._real_write_handler_enabled:
            raise NotImplementedError(
                "BusinessWriterImpl 写保护锁未开(_real_write_handler_enabled=False);"
                "Path 4 实写必须显式开启写保护锁 + 第 5 门 + 用户明确授权"
            )
        if not self._enable_path_4_write:
            raise NotImplementedError(
                f"BusinessWriterImpl 第 5 门未开({ENABLE_PATH_4_WRITE_ENV}=1);"
                "Path 4 实写必须显式启用第 5 门"
            )

    def _call_service_approve_outbox(self, target_id: str, *, audit: AuditContext) -> WriteResult:
        """真实调 outbox_store.update_status(APPROVED 路径) + audit 落档.

        边界(沿 v0.2.53.49 + D5.6.3 P1-1 审批凭据必传规则 + v0.2.53.51 audit 落档):
            - new_status='APPROVED' → last_approved_at_ms 必传 now_ms
            - 异常透传(OutboxIllegalTransitionError / ValueError)
            - audit 落档:成功 → success=True,affected_id;失败 → success=False,error
            - audit 落档失败:WriteResult.audit_id=None,但不抛异常
        """
        try:
            # 路径 4 启用后的真实调用(写保护锁开 + 依赖注入)
            # 异常透传,不收容(用户主动操作必须看到 ValueError)
            updated = self._outbox_store.update_status(  # type: ignore[union-attr]
                outbox_id=int(target_id),
                new_status="approved",
                from_status="pending_send",
                last_approved_at_ms=_now_ms(),
            )
            affected_id = str(updated.id)
            # audit 落档(成功)
            audit_id = self._record_audit(
                action="approve_outbox",
                target_id=target_id,
                audit=audit,
                write_executed=True,
                affected_id=affected_id,
                error=None,
            )
            return WriteResult(
                success=True,
                affected_id=affected_id,
                error=None,
                reason=f"approve_outbox: {target_id} → APPROVED",
                audit_id=audit_id,
                write_executed=True,  # 真实写入了,但 v0.2.53.11 不变式仅在 dry_run 上下文
            )
        except Exception as e:
            # audit 落档(失败) — 异常透传前记录
            audit_id = self._record_audit(
                action="approve_outbox",
                target_id=target_id,
                audit=audit,
                write_executed=True,
                affected_id=None,
                error=f"{type(e).__name__}:{e}",
            )
            # 异常透传(用户主动操作必须看到 ValueError)
            raise

    def _call_service_cancel_outbox(self, target_id: str, *, audit: AuditContext) -> WriteResult:
        """真实调 outbox_store.update_status(CANCELLED 路径) + audit 落档.

        边界(沿 v0.2.53.49 + D5.6.3 P1-1 必传 None 规则 + v0.2.53.51 audit 落档):
            - new_status='CANCELLED' → last_approved_at_ms 必传 None
            - 异常透传
            - audit 落档:成功 → success=True,affected_id;失败 → success=False,error
        """
        try:
            updated = self._outbox_store.update_status(  # type: ignore[union-attr]
                outbox_id=int(target_id),
                new_status="cancelled",
                from_status="pending_send",
                last_approved_at_ms=None,
            )
            affected_id = str(updated.id)
            audit_id = self._record_audit(
                action="cancel_outbox",
                target_id=target_id,
                audit=audit,
                write_executed=True,
                affected_id=affected_id,
                error=None,
            )
            return WriteResult(
                success=True,
                affected_id=affected_id,
                error=None,
                reason=f"cancel_outbox: {target_id} → CANCELLED",
                audit_id=audit_id,
                write_executed=True,
            )
        except Exception as e:
            audit_id = self._record_audit(
                action="cancel_outbox",
                target_id=target_id,
                audit=audit,
                write_executed=True,
                affected_id=None,
                error=f"{type(e).__name__}:{e}",
            )
            raise

    def _call_service_confirm_note(self, target_id: str, *, audit: AuditContext) -> WriteResult:
        """真实调 note_confirm_service.confirm_note + audit 落档.

        边界(沿 v0.2.53.49 + note_confirm_service.py:113-115 + v0.2.53.51 audit 落档):
            - 异常透传(用户主动操作必须看到 ValueError)
            - audit 落档:成功 → success=True,affected_id=target_id;失败 → success=False,error
        """
        try:
            self._note_confirm_service.confirm_note(  # type: ignore[union-attr]
                apple_note_id=target_id,
            )
            audit_id = self._record_audit(
                action="confirm_note",
                target_id=target_id,
                audit=audit,
                write_executed=True,
                affected_id=target_id,
                error=None,
            )
            return WriteResult(
                success=True,
                affected_id=target_id,
                error=None,
                reason=f"confirm_note: {target_id} confirmed",
                audit_id=audit_id,
                write_executed=True,
            )
        except Exception as e:
            audit_id = self._record_audit(
                action="confirm_note",
                target_id=target_id,
                audit=audit,
                write_executed=True,
                affected_id=None,
                error=f"{type(e).__name__}:{e}",
            )
            raise

    def _call_service_dismiss_anomaly(self, target_id: str, *, audit: AuditContext) -> WriteResult:
        """真实调 anomaly_dismissal_service.dismiss + audit 落档.

        边界(沿 v0.2.53.49 + AnomalyDismissalService.dismiss 契约 + v0.2.53.51 audit 落档):
            - reason 限 240 字符(沿 _MAX_REASON_LEN)
            - 异常透传
            - audit 落档:成功 → success=True,affected_id=target_id;失败 → success=False,error
        """
        try:
            self._anomaly_dismissal_service.dismiss(  # type: ignore[union-attr]
                anomaly_id=target_id,
                reason=audit.reason,
            )
            audit_id = self._record_audit(
                action="dismiss_anomaly",
                target_id=target_id,
                audit=audit,
                write_executed=True,
                affected_id=target_id,
                error=None,
            )
            return WriteResult(
                success=True,
                affected_id=target_id,
                error=None,
                reason=f"dismiss_anomaly: {target_id} dismissed",
                audit_id=audit_id,
                write_executed=True,
            )
        except Exception as e:
            audit_id = self._record_audit(
                action="dismiss_anomaly",
                target_id=target_id,
                audit=audit,
                write_executed=True,
                affected_id=None,
                error=f"{type(e).__name__}:{e}",
            )
            raise

    def _record_audit(
        self,
        *,
        action: str,
        target_id: str,
        audit: AuditContext,
        write_executed: bool,
        affected_id: str | None,
        error: str | None,
        decision: str | None = None,
    ) -> str | None:
        """Audit 落档辅助 — 包装 store.record + 异常收容(沿撞坑 #18 「日志」语义).

        边界(沿 v0.2.53.51 + 撞坑 #18):
            - 异常收容:audit 落档失败 → 返回 None,不抛异常(避免日志失败阻塞业务)
            - audit_id 字符串格式 "audit:{id}" 与 anomaly_dismissals "dismissal:{id}" 对齐
            - executed_at_ms 默认 = _now_ms()(沿 v0.2.53.11 actor 默认值时间戳)
            - write_executed=True 表示「写操作已尝试」(成功或失败都算)
            - v0.2.57 / Day 8 候选 B 新增 decision 字段(可选):走 /api/approval-gate/decide
              端点时填充 "approve" / "reject";走 /api/approval-gate/actions 端点时 None

        Args:
            action: 写操作类型(approve_outbox / cancel_outbox / confirm_note / dismiss_anomaly)
            target_id: 写操作的目标 ID
            audit: 审计上下文(AuditContext)
            write_executed: True = 写操作已尝试
            affected_id: 成功时填,失败时 None
            error: 失败时填 error code,成功时 None
            decision: v0.2.57 / Day 8 候选 B 新增,"approve" / "reject" / None

        Returns:
            audit_id 字符串(成功)或 None(失败)
        """
        try:
            record = AuditRecord(
                action=action,
                target_id=target_id,
                actor=audit.actor,
                reason=audit.reason,
                write_executed=write_executed,
                affected_id=affected_id,
                error=error,
                executed_at_ms=self._audit_timestamp(audit),
                decision=decision,
            )
            result: AuditRecordResult = self._audit_store.record(record)
            return result.audit_id
        except Exception:  # noqa: BLE001 — audit 落档是「日志」语义,失败不阻塞业务
            return None

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
