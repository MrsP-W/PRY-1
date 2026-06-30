"""Dashboard 只读上下文 — 注入 menu_bar 服务 Stub(沿 P1 范本).

v0.2.53.7 opt-in 真实数据:
    - 默认全 Stub(沿 v0.2.53.6 行为不变)
    - 设 `DASHBOARD_REAL_DB=1` 时,`DashboardContext.default()` 尝试注入真实
      `OutboxDraftServiceImpl(OutboxStore(session_factory))`
    - 任何失败(Keychain 缺密码 / DB 不存在 / SQLCipher 错 / 网络错)静默降级 Stub,
      不阻塞 Dashboard 启动

v0.2.53.8 扩展:
    - 同一 env 门控 + 同一 session_factory,继续注入
      `NoteConfirmServiceImpl(NoteStore)` 与 `ExpenseServiceImpl`(只读 anomaly 链路)
    - 各服务独立 try/except;单项失败不影响其余服务降级
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from my_ai_employee import __version__

# v0.2.53.18 BusinessWriter 集成(沿 v0.2.53.14 §8 DashboardContext 集成)
#   - 默认 None → 解析为 BusinessWriterStub(撞坑 #65 默认 Stub 边界)
#   - with_business_writer() 不可变更新(沿 #64 公共 API 范本)
from my_ai_employee.dashboard.business_writer import BusinessWriter, BusinessWriterStub
from my_ai_employee.menu_bar.approval_gate_audit import (
    ApprovalGateAuditStore,
    ApprovalGateAuditStoreStub,
)
from my_ai_employee.menu_bar.expense_service import ExpenseService, ExpenseServiceStub
from my_ai_employee.menu_bar.note_confirm_service import (
    NoteConfirmService,
    NoteConfirmServiceImpl,
    NoteConfirmServiceStub,
)
from my_ai_employee.menu_bar.outbox_draft_service import (
    OutboxDraftService,
    OutboxDraftServiceImpl,
    OutboxDraftServiceStub,
)
from my_ai_employee.quality_snapshot import DEFAULT_QUALITY_GATES, QualityGateSnapshot

GitHeadResolver = Callable[[], str]
KeychainProbe = Callable[[str], bool]

# v0.2.53.7 opt-in 真实 DB env 门控
#   - 未设或 "0" / "false" / "no" → 默认全 Stub(沿 v0.2.53.6 行为)
#   - "1" / "true" / "yes" → 尝试注入 Outbox / NoteConfirm / Expense 真实 Impl
_DASHBOARD_REAL_DB_ENV = "DASHBOARD_REAL_DB"

# v0.2.53.27 opt-in BusinessWriterImpl env 门控(沿 DASHBOARD_REAL_DB=1 范本)
#   - 未设或 "0" / "false" / "no" → 默认 BusinessWriterStub(沿 v0.2.53.18 行为)
#   - "1" / "true" / "yes" → 尝试注入 BusinessWriterImpl(session_factory)
#   - 单项失败静默降级 Stub(沿 v0.2.53.8 单项失败降级范本)
_BUSINESS_WRITER_ENABLED_ENV = "BUSINESS_WRITER_ENABLED"
_ENABLE_PATH_4_WRITE_ENV = "ENABLE_PATH_4_WRITE"
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}


@dataclass(slots=True)
class DashboardContext:
    """Dashboard API 依赖注入容器."""

    expense_service: ExpenseService = field(default_factory=ExpenseServiceStub.get_default_stub)
    note_confirm_service: NoteConfirmService = field(
        default_factory=NoteConfirmServiceStub.get_default_stub
    )
    outbox_draft_service: OutboxDraftService = field(
        default_factory=OutboxDraftServiceStub.get_default_stub
    )
    business_writer: BusinessWriter | None = field(
        default=None  # 默认 None 表示使用 BusinessWriterStub.get_default_stub()
    )
    # v0.2.53.52 audit_store 注入(沿 v0.2.53.51 + 撞坑 #65 opt-in 4 阶段范本)
    #   - 默认 ApprovalGateAuditStoreStub(等效 is_enabled=False,record 永远不成功)
    #   - DASHBOARD_REAL_DB=1 + BUSINESS_WRITER_ENABLED=1 + session_factory 成功
    #     → 尝试注入 InMemoryApprovalGateAuditStore(测试场景用)
    #   - 单项失败静默降级 Stub(沿 v0.2.53.7 范本)
    audit_store: ApprovalGateAuditStore = field(
        default_factory=ApprovalGateAuditStoreStub.get_default_stub
    )
    version: str = __version__
    quality_gates: QualityGateSnapshot = field(default_factory=lambda: DEFAULT_QUALITY_GATES)
    git_head_resolver: GitHeadResolver = field(default=lambda: _default_git_head())
    keychain_probe: KeychainProbe = field(default=lambda s: _default_keychain_probe(s))

    @classmethod
    def default(cls) -> DashboardContext:
        """默认上下文 — 默认全 Stub;`DASHBOARD_REAL_DB=1` 时 opt-in 真实服务.

        边界(沿 v0.2.53.6 + v0.2.53.7 + v0.2.53.8):
            - 未设 env → 全 Stub(行为不变)
            - 设 env 但 session_factory 失败 → 全 Stub
            - session_factory 成功 → 分别尝试 Outbox / NoteConfirm / Expense Impl
              (单项失败静默降级 Stub,不阻塞其余服务)
            - Outbox 只读 pending_send + approved,不含 body
            - 不真发 SMTP / 不写 DB / 不移动 v0.1.0 tag / 不打 v0.2.x tag
        """
        ctx = cls()
        if not _is_real_db_enabled():
            return ctx
        session_factory = _try_build_real_session_factory()
        if session_factory is None:
            return ctx
        outbox = _try_build_outbox_from_session_factory(session_factory)
        if outbox is not None:
            ctx = ctx.with_outbox_drafts(outbox)
        note_confirm = _try_build_note_confirm_from_session_factory(session_factory)
        if note_confirm is not None:
            ctx = ctx.with_note_confirm(note_confirm)
        expense = _try_build_expense_from_session_factory(session_factory)
        if expense is not None:
            ctx = ctx.with_expense(expense)
        # v0.2.53.27 opt-in BusinessWriterImpl(沿 DASHBOARD_REAL_DB=1 范本)
        #   - BUSINESS_WRITER_ENABLED 未设 → 保持默认 BusinessWriterStub(沿 v0.2.53.18)
        #   - 已设 + session_factory 可用 → 尝试注入 Impl
        #   - 任一失败 → 静默降级 Stub(沿 v0.2.53.8 单项失败降级)
        #   - dry-run write_executed 恒 False;实写仍由 Path 4 五门严判
        if _is_business_writer_enabled():
            # v0.2.53.54 audit_store 同源修复:
            #   - 先构造 audit_store,再传给 BusinessWriterImpl
            #   - ctx.audit_store 与 writer._audit_store 必须指向同一个对象
            #   - _try_build_audit_store 失败时复用默认 Stub,保持单对象同源
            audit_store = _try_build_audit_store() or ctx.audit_store
            writer = _try_build_business_writer_from_session_factory(
                session_factory, audit_store=audit_store
            )
            if writer is not None:
                ctx = ctx.with_audit_store(audit_store)
                ctx = ctx.with_business_writer(writer)
        return ctx

    def with_outbox_drafts(self, service: OutboxDraftService) -> DashboardContext:
        """返回替换 outbox_draft_service 的新 ctx(不可变更新)."""
        return DashboardContext(
            expense_service=self.expense_service,
            note_confirm_service=self.note_confirm_service,
            outbox_draft_service=service,
            business_writer=self.business_writer,
            audit_store=self.audit_store,
            version=self.version,
            quality_gates=self.quality_gates,
            git_head_resolver=self.git_head_resolver,
            keychain_probe=self.keychain_probe,
        )

    def with_note_confirm(self, service: NoteConfirmService) -> DashboardContext:
        """返回替换 note_confirm_service 的新 ctx(不可变更新)."""
        return DashboardContext(
            expense_service=self.expense_service,
            note_confirm_service=service,
            outbox_draft_service=self.outbox_draft_service,
            business_writer=self.business_writer,
            audit_store=self.audit_store,
            version=self.version,
            quality_gates=self.quality_gates,
            git_head_resolver=self.git_head_resolver,
            keychain_probe=self.keychain_probe,
        )

    def with_expense(self, service: ExpenseService) -> DashboardContext:
        """返回替换 expense_service 的新 ctx(不可变更新)."""
        return DashboardContext(
            expense_service=service,
            note_confirm_service=self.note_confirm_service,
            outbox_draft_service=self.outbox_draft_service,
            business_writer=self.business_writer,
            audit_store=self.audit_store,
            version=self.version,
            quality_gates=self.quality_gates,
            git_head_resolver=self.git_head_resolver,
            keychain_probe=self.keychain_probe,
        )

    def with_business_writer(self, writer: BusinessWriter | None) -> DashboardContext:
        """返回替换 business_writer 的新 ctx(不可变更新,沿 #64 公共 API 范本).

        Args:
            writer: BusinessWriter 实例,None 表示还原为默认 BusinessWriterStub.
        """
        return DashboardContext(
            expense_service=self.expense_service,
            note_confirm_service=self.note_confirm_service,
            outbox_draft_service=self.outbox_draft_service,
            business_writer=writer if writer is not None else BusinessWriterStub(),
            audit_store=self.audit_store,
            version=self.version,
            quality_gates=self.quality_gates,
            git_head_resolver=self.git_head_resolver,
            keychain_probe=self.keychain_probe,
        )

    def with_audit_store(self, store: ApprovalGateAuditStore) -> DashboardContext:
        """返回替换 audit_store 的新 ctx(不可变更新,沿 #64 公共 API 范本).

        v0.2.53.52:P2 联动 — BusinessWriterImpl 注入成功时配套注入 audit_store.

        Args:
            store: ApprovalGateAuditStore 实例(默认 ApprovalGateAuditStoreStub).
        """
        return DashboardContext(
            expense_service=self.expense_service,
            note_confirm_service=self.note_confirm_service,
            outbox_draft_service=self.outbox_draft_service,
            business_writer=self.business_writer,
            audit_store=store,
            version=self.version,
            quality_gates=self.quality_gates,
            git_head_resolver=self.git_head_resolver,
            keychain_probe=self.keychain_probe,
        )

    def resolve_business_writer(self) -> BusinessWriter:
        """解析 business_writer — None 时返回 BusinessWriterStub(撞坑 #65 默认 Stub).

        Returns:
            BusinessWriter 实例(始终非 None).
        """
        return self.business_writer if self.business_writer is not None else BusinessWriterStub()

    def is_business_writer_env_enabled(self) -> bool:
        """第三道门 env 开关 — `BUSINESS_WRITER_ENABLED=1`(不等于 Impl 已注入)."""
        return _is_business_writer_enabled()

    def is_business_writer_impl_injected(self) -> bool:
        """BusinessWriterImpl 是否已通过 `with_business_writer()` / default() 注入.

        v0.2.53.30:显式识别 `BusinessWriterImpl.is_runtime_impl`,避免 Stub 被误判为已注入。
        """
        writer = self.business_writer
        if writer is None:
            return False
        return getattr(writer, "is_runtime_impl", False) is True

    def is_business_writer_ready(self) -> bool:
        """第三道门运行时就绪 — env + `DASHBOARD_REAL_DB` session + Impl 已注入.

        完整写路径还需 POST 级 `DASHBOARD_WRITE_API=1` 与 `confirm_text=CONFIRM_WRITE`。
        """
        return self.is_business_writer_env_enabled() and self.is_business_writer_impl_injected()

    def is_path4_write_env_enabled(self) -> bool:
        """第 5 门 env 开关 — `ENABLE_PATH_4_WRITE=1`."""
        return _is_path4_write_enabled()

    def is_path4_write_ready(self) -> bool:
        """Path 4 实写运行时就绪 — writer ready + 第 5 门显式开启."""
        return self.is_business_writer_ready() and self.is_path4_write_env_enabled()


def _is_real_db_enabled() -> bool:
    """`DASHBOARD_REAL_DB=1` opt-in 判定 — 仅识别 truthy 字面量,避免意外触发."""
    raw = os.environ.get(_DASHBOARD_REAL_DB_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _is_business_writer_enabled() -> bool:
    """`BUSINESS_WRITER_ENABLED=1` opt-in env 判定 — 仅识别 truthy 字面量.

    边界(v0.2.53.28 语义收口):
        - env 设真值 ≠ writer 就绪;Impl 注入还需 `DASHBOARD_REAL_DB=1` +
          `_try_build_real_session_factory()` 成功 + 构造 BusinessWriterImpl 成功
        - `DashboardContext.default()` 在 `DASHBOARD_REAL_DB` 未开时早返回 Stub
        - 运行时就绪以 `DashboardContext.is_business_writer_ready()` 为准
    """
    raw = os.environ.get(_BUSINESS_WRITER_ENABLED_ENV, "").strip().lower()
    return raw in _TRUTHY_ENV_VALUES


def _is_path4_write_enabled() -> bool:
    """`ENABLE_PATH_4_WRITE=1` 第 5 门判定 — 默认关闭,仅识别 truthy 字面量."""
    raw = os.environ.get(_ENABLE_PATH_4_WRITE_ENV, "").strip().lower()
    return raw in _TRUTHY_ENV_VALUES


def _try_build_real_session_factory() -> Any | None:
    """打开 SQLCipher DB 并返回 sessionmaker;失败返回 None(降级 Stub).

    失败模式(全部静默降级):
        - ImportError:缺少依赖
        - PermissionError / OSError:Keychain 不可访问或 DB 锁
        - FileNotFoundError:DB 文件不存在(首次未 init_schema)
        - sqlcipher3.DatabaseError:密码错
        - 其他 Exception:兜底降级
    """
    try:
        from sqlalchemy.orm import sessionmaker

        from my_ai_employee.core.db import Database
        from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine
    except ImportError:
        return None
    try:
        with Database.open() as db:
            engine = make_sqlalchemy_engine(db)
        if engine is None:
            return None
        return sessionmaker(bind=engine, expire_on_commit=False)
    except Exception:  # noqa: BLE001 — 任何失败都降级 Stub,不阻塞 Dashboard
        return None


def _try_build_outbox_from_session_factory(session_factory: Any) -> OutboxDraftService | None:
    try:
        from my_ai_employee.db.outbox import OutboxStore

        return OutboxDraftServiceImpl(OutboxStore(session_factory))
    except Exception:  # noqa: BLE001
        return None


def _try_build_note_confirm_from_session_factory(
    session_factory: Any,
) -> NoteConfirmService | None:
    try:
        from my_ai_employee.db.notes import NoteStore

        return NoteConfirmServiceImpl(NoteStore(session_factory))
    except Exception:  # noqa: BLE001
        return None


def _try_build_expense_from_session_factory(session_factory: Any) -> ExpenseService | None:
    try:
        from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector
        from my_ai_employee.core.expense_service import ExpenseServiceImpl
        from my_ai_employee.db.merchant_profile import MerchantProfileStore
        from my_ai_employee.db.notes import NoteStore
        from my_ai_employee.db.transactions import TransactionStore

        note_store = NoteStore(session_factory)
        tx_store = TransactionStore(session_factory)
        profile_store = MerchantProfileStore(session_factory, transaction_store=tx_store)
        detector = RuleBasedAnomalyDetector(
            transaction_store=tx_store,
            merchant_profile_store=profile_store,
        )
        return ExpenseServiceImpl(
            note_store=note_store,
            tx_store=tx_store,
            anomaly_detector=detector,
        )
    except Exception:  # noqa: BLE001
        return None


def _try_build_business_writer_from_session_factory(
    session_factory: Any,
    *,
    audit_store: ApprovalGateAuditStore | None = None,
) -> Any | None:
    """v0.2.53.27 opt-in BusinessWriterImpl 构造 — 失败返回 None 降级 Stub.

    边界(沿 v0.2.53.27 + v0.2.53.17 + v0.2.53.18):
        - 构造注入 session_factory + audit_store(其他依赖可选,None 表示不接)
        - 任一 ImportError / Exception → 静默降级 None(由 caller 走默认 Stub)
        - 不接 SMTP / 不读 Keychain 明文
        - Impl 4 类动作只有 Path 4 五门全开后才实写
    """
    try:
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl
        from my_ai_employee.db.notes import NoteStore
        from my_ai_employee.db.outbox import OutboxStore

        outbox_store = OutboxStore(session_factory)
        note_confirm_service = (
            NoteConfirmServiceImpl(NoteStore(session_factory))
            if callable(session_factory)
            else None
        )
        return BusinessWriterImpl(
            session_factory=session_factory,
            outbox_store=outbox_store,
            note_confirm_service=note_confirm_service,
            anomaly_dismissal_service=None,
            audit_store=audit_store,
            real_write_handler_enabled=_is_path4_write_enabled(),
            enable_path_4_write=_is_path4_write_enabled(),
        )
    except Exception:  # noqa: BLE001 — 单项失败静默降级,不阻塞 Dashboard
        return None


def _try_build_audit_store() -> ApprovalGateAuditStore | None:
    """v0.2.53.52 opt-in InMemoryApprovalGateAuditStore 构造 — 失败返回 None 降级 Stub.

    边界(沿撞坑 #65 opt-in 4 阶段 + v0.2.53.51):
        - 测试场景下使用 InMemoryApprovalGateAuditStore(无 DB 接入)
        - 任何 Exception → 静默降级 None(由 caller 走默认 Stub)
        - 当前 InMemory 实现仅供 Dashboard 进程内 audit 展示
        - 默认 ApprovalGateAuditStoreStub(is_enabled=False,record 永远失败)
    """
    try:
        from my_ai_employee.menu_bar.approval_gate_audit import InMemoryApprovalGateAuditStore

        return InMemoryApprovalGateAuditStore()
    except Exception:  # noqa: BLE001 — 单项失败静默降级,不阻塞 Dashboard
        return None


def _try_build_real_outbox_drafts() -> OutboxDraftService | None:
    """尝试构造真实 OutboxDraftServiceImpl;失败返回 None(降级 Stub).

    沿 v0.2.53.7 公开 API 保留;内部复用 `_try_build_real_session_factory`.
    """
    session_factory = _try_build_real_session_factory()
    if session_factory is None:
        return None
    return _try_build_outbox_from_session_factory(session_factory)


def _default_git_head() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _default_keychain_probe(service: str) -> bool:
    """Keychain 项是否存在(不读密码,不用 -w)."""
    import sys

    if sys.platform != "darwin":
        return False
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def safe_count(getter: Callable[[], int]) -> int:
    """单项计数静默降级 → 0."""
    try:
        return int(getter())
    except Exception:  # noqa: BLE001 — API 层不崩
        return 0


def safe_list(getter: Callable[[], list[Any]]) -> list[Any]:
    """列表查询静默降级 → []."""
    try:
        result = getter()
        return list(result) if isinstance(result, list) else []
    except Exception:  # noqa: BLE001 — API 层不崩
        return []


def parse_limit(raw: str | None, *, default: int = 10, maximum: int = 100) -> int:
    """解析 ?limit= 查询参数(严判范围)."""
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < 1:
        return 1
    if value > maximum:
        return maximum
    return value


__all__ = [
    "DashboardContext",
    "QualityGateSnapshot",
    "_is_path4_write_enabled",
    "parse_limit",
    "safe_count",
    "safe_list",
]
