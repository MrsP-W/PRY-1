"""v0.2.53.51 ApprovalGate Audit Service — 写操作真实落档 store(沿 v0.2.53.20 §5.3 design).

承接 docs/v0.2.53.20-html-real-write-flow-design-2026-06-26.md §5.3:
    - 写操作(路径 4 启用后)必须留痕,即便失败也要落档
    - audit 是「写操作的真实落档记录」,与 dry-run 决策分离(撞坑 #18 风险门控)
    - 默认 BusinessWriterImpl 写保护锁锁定,实际写入路径留 8/1 后
    - audit 表是「日志」(不阻塞业务),即便 store 失败也不应影响业务返回

设计决策(2026-06-29 锁定):
    - 抽象 ApprovalGateAuditStore Protocol 类(3 方法)+ Stub 硬编码 + InMemory fake
    - audit_id 字符串格式: "audit:{id}" — 与 anomaly_dismissals "dismissal:{id}" 对齐(撞坑 #64 公共 API 范本)
    - AuditRecord dataclass: 8 字段(action/target_id/actor/reason/write_executed/affected_id/error/executed_at_ms)
    - AuditRecordResult dataclass: success / audit_id / error / reason / executed_at_ms
    - record() 严判:action 必须非空 str,target_id 必须非空 str,write_executed 必须 bool
    - list_recent() 按 executed_at_ms DESC 倒序返回(沿 idx_audit_executed_at 索引)

撞坑 #65 边界应用(默认禁写):
    - Stub: is_enabled() 恒返回 False
    - Real: DASHBOARD_REAL_DB=1 opt-in,构造失败静默降级 Stub(沿 v0.2.53.7 范本)
    - record() 失败不抛异常(返回 AuditRecordResult(success=False, error=...))

撞坑 #18 边界应用(实际写入留 8/1 后):
    - 默认 BusinessWriterImpl 写保护锁锁定,audit_store 不被调用
    - 即便 audit_store 失败,业务 WriteResult 仍正常返回(audit 落档是「日志」语义)

撞坑 #64 公共 API 一致性:
    - AuditRecord 字段顺序与 SQL 表 approval_gate_audits 字段顺序一致
    - audit_id 字符串格式 "audit:{id}" 与 anomaly_dismissals "dismissal:{id}" 对齐

沿用边界:
    - 本棒 Protocol + Stub + InMemory fake,不动真实 DB
    - Real(ApprovalGateAuditStoreImpl) 留 v0.2.53.51+ 接入(DASHBOARD_REAL_DB=1 opt-in)
    - 不接 BusinessWriter(沿 v0.2.53.49 写保护锁锁定)
    - 默认不真写 DB / 不发 SMTP / 不读 Keychain 明文
    - dry-run 决策不落档(只路径 4 实际执行才落档,沿 v0.2.53.49 范本)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

# ===== 字段长度常量(沿 AuditContext / WriteResult) =====

MAX_ACTOR_LEN: Final = 80
MAX_REASON_LEN: Final = 240
MAX_LIST_RECENT: Final = 100  # list_recent 严判上限(防滥用)

# audit_id 字符串格式(撞坑 #64 公共 API 范本)
_AUDIT_ID_PREFIX: Final = "audit:"


# ===== AuditRecord dataclass(沿 v0.2.53.20 §5.3 字段)=====


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Audit 落档记录 — 一次写操作的真实落档.

    字段(对齐 SQL 表 approval_gate_audits):
        action:          approve_outbox / cancel_outbox / confirm_note / dismiss_anomaly / decide
        target_id:       写操作的目标 ID(str 表示)
        actor:           操作者(限 80 字符,默认 'local_dashboard')
        reason:          操作原因(限 240 字符,默认 '')
        write_executed:  True = 实际写入;False = 失败但已尝试(非 dry-run,dry-run 不落档)
        affected_id:     成功时填(str 表示的 int 或 str 本身);失败时 None
        error:           失败时填 error code;成功时 None
        executed_at_ms:  Unix epoch ms 时间戳
        decision:        v0.2.57 / Day 8 候选 B 新增:决策语义("approve" / "reject" / None);
                        4 类 action 走 /api/approval-gate/actions 端点时为 None;
                        走 /api/approval-gate/decide 端点时必填
    """

    action: str
    target_id: str
    actor: str
    reason: str
    write_executed: bool
    affected_id: str | None
    error: str | None
    executed_at_ms: int
    decision: str | None = None

    def __post_init__(self) -> None:
        # 严判 type(撞坑 #65 严判 type 严格)
        if not isinstance(self.action, str) or not self.action:
            raise ValueError(f"action 必须为非空 str,实际 type={type(self.action).__name__}")
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError(
                f"target_id 必须为非空 str(非纯空白),实际 type={type(self.target_id).__name__}"
            )
        if not isinstance(self.actor, str):
            raise ValueError(f"actor 必须为 str,实际 type={type(self.actor).__name__}")
        if not isinstance(self.reason, str):
            raise ValueError(f"reason 必须为 str,实际 type={type(self.reason).__name__}")
        if not isinstance(self.write_executed, bool):
            raise ValueError(
                f"write_executed 必须为 bool,实际 type={type(self.write_executed).__name__}"
            )
        if not isinstance(self.executed_at_ms, int):
            raise ValueError(
                f"executed_at_ms 必须为 int,实际 type={type(self.executed_at_ms).__name__}"
            )
        # decision 字段严判(沿 v0.2.57 / Day 8 候选 B)
        if self.decision is not None:
            if not isinstance(self.decision, str):
                raise ValueError(
                    f"decision 必须为 str 或 None,实际 type={type(self.decision).__name__}"
                )
            if self.decision and self.decision not in {"approve", "reject"}:
                raise ValueError(
                    f"decision 必须为 'approve' / 'reject' 或 None,实际={self.decision!r}"
                )
        # 严判长度(沿 AuditContext 范本)
        if len(self.actor) > MAX_ACTOR_LEN:
            raise ValueError(f"actor 超长({len(self.actor)}>{MAX_ACTOR_LEN}):{self.actor[:40]}...")
        if len(self.reason) > MAX_REASON_LEN:
            raise ValueError(
                f"reason 超长({len(self.reason)}>{MAX_REASON_LEN}):{self.reason[:40]}..."
            )

    def to_dict(self) -> dict[str, Any]:
        """AuditRecord → dict(API 层 / 测试 fixture 用).

        Returns:
            9 字段 dict(键名与 SQL 列名一致,便于 JSON 序列化)。
            v0.2.57 / Day 8 候选 B 新增 `decision` 字段(可选)。
        """
        return {
            "action": self.action,
            "target_id": self.target_id,
            "actor": self.actor,
            "reason": self.reason,
            "write_executed": self.write_executed,
            "affected_id": self.affected_id,
            "error": self.error,
            "executed_at_ms": self.executed_at_ms,
            "decision": self.decision,
        }


# ===== AuditRecordResult dataclass(沿 DismissalResult 范本)=====


@dataclass(frozen=True, slots=True)
class AuditRecordResult:
    """Audit 落档结果.

    边界:
        - success=True 时 audit_id 必填(executed_at_ms 必填)
        - success=False 时 error 必填(audit_id=None,executed_at_ms=None)
    """

    success: bool
    audit_id: str | None
    executed_at_ms: int | None
    error: str | None
    reason: str | None


# ===== ApprovalGateAuditStore Protocol(撞坑 #64 公共 API 范本)=====


class ApprovalGateAuditStore(Protocol):
    """Audit 落档服务接口(v0.2.53.51 沿 v0.2.53.20 §5.3 设计).

    3 方法契约:
        - is_enabled → 是否启用(撞坑 #65 opt-in 4 阶段)
        - record     → 落档 1 条 audit(成功/失败都落档,dry-run 不调)
        - list_recent → 最近 audit 列表(按 executed_at_ms DESC 倒序,limit 严判 1-100)
    """

    def is_enabled(self) -> bool: ...

    def record(self, record: AuditRecord) -> AuditRecordResult: ...

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]: ...


# ===== Stub 默认值常量(避免硬编码分散,撞坑 #64 范本)=====

_IS_ENABLED_DEFAULT: Final[bool] = False
_LIST_RECENT_DEFAULT: Final[list[dict[str, Any]]] = []


class ApprovalGateAuditStoreStub:
    """ApprovalGateAuditStore Stub — 3 方法全部返回硬编码默认值(无 DB 接入).

    设计取舍(沿 AnomalyDismissalServiceStub 范本):
        - 不调 DB / 完全解耦(测试零依赖)
        - 单例 (`get_default_stub()`),避免每次 new
        - 类型签名与 Protocol 100% 对齐(Real 实现可直接替换)

    撞坑 #65 边界(默认禁写):
        - is_enabled() 恒返回 False
        - record() 恒返回失败结果(success=False, error='not_enabled')
        - list_recent() 恒返回 []
    """

    def is_enabled(self) -> bool:
        """是否启用 — Stub 默认 False(撞坑 #65 opt-in 范本).

        Real 实现需检查 DASHBOARD_REAL_DB=1 + approval_gate_audits 表构造成功.
        """
        return _IS_ENABLED_DEFAULT

    def record(self, record: AuditRecord) -> AuditRecordResult:
        """no-op + 失败返回(Stub 阶段不真落档).

        Args:
            record: AuditRecord 实例(类型校验已在 dataclass __post_init__ 完成)

        Returns:
            AuditRecordResult(success=False, error='not_enabled') — Stub 永远不成功.
        """
        return AuditRecordResult(
            success=False,
            audit_id=None,
            executed_at_ms=None,
            error="not_enabled",
            reason="ApprovalGateAuditStore 默认 Stub;需 v0.2.53.51+ 接入 Real(Impl)",
        )

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回 [] (Stub 阶段无 DB 接入).

        Args:
            limit: 最大返回条数(Stub 不校验,直接返回 [])
        """
        del limit  # 显式声明 unused(API 一致性)
        return list(_LIST_RECENT_DEFAULT)

    @staticmethod
    def get_default_stub() -> ApprovalGateAuditStoreStub:
        """默认 Stub 工厂(沿 AnomalyDismissalServiceStub.get_default_stub 范本)."""
        return ApprovalGateAuditStoreStub()


# ===== InMemory fake(测试场景用,撞坑 #18 风险门控 + 撞坑 #65 opt-in 4 阶段)=====


@dataclass
class InMemoryApprovalGateAuditStore:
    """In-Memory 内存版 fake — 用于 fake store 测试,验证整条 audit 落档链.

    设计取舍(沿撞坑 #18 + 撞坑 #65):
        - is_enabled() 恒 True(测试场景下走通整条链)
        - record() 累加到内部 list(每次分配自增 id),返回 audit_id 字符串
        - list_recent(limit) 按 executed_at_ms DESC 倒序返回(默认最近 10 条)
        - 不调 DB(纯内存,撞坑 #18 风险门控:实际写入留 8/1 后)

    适用场景:
        - BusinessWriterImpl 11 个 fake store 测试(沿 v0.2.53.49 范本)
        - P1 新增 audit 落档测试(成功/失败/dry-run 不落档/写保护锁 raise 不落档)

    设计注意:
        - 字段 `_enabled` 用下划线前缀避开与 Protocol `is_enabled()` 方法同名冲突
          (撞坑 #65 公共 API 一致性 + 沿 v0.2.53.7 Stub 范本)
    """

    _enabled: bool = True
    _next_id: int = 0
    _records: list[AuditRecord] = field(default_factory=list)

    def is_enabled(self) -> bool:
        """是否启用 — InMemory 默认 True(测试场景走通整条链)."""
        return self._enabled

    def record(self, record: AuditRecord) -> AuditRecordResult:
        """记录 audit 到内存 list,返回 audit_id 字符串.

        Args:
            record: AuditRecord 实例(类型校验已在 dataclass __post_init__ 完成)

        Returns:
            AuditRecordResult(success=True, audit_id=f"audit:{id}", executed_at_ms=record.executed_at_ms)
        """
        self._next_id += 1
        self._records.append(record)
        return AuditRecordResult(
            success=True,
            audit_id=f"{_AUDIT_ID_PREFIX}{self._next_id}",
            executed_at_ms=record.executed_at_ms,
            error=None,
            reason=None,
        )

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """返回最近 N 条 audit(按 executed_at_ms DESC 倒序).

        Args:
            limit: 最大返回条数(严判 1-100,沿 MAX_LIST_RECENT)

        Returns:
            list[dict],每条 dict 由 AuditRecord.to_dict() 构造.
        """
        if not isinstance(limit, int) or limit < 1 or limit > MAX_LIST_RECENT:
            limit = 10
        # 按 executed_at_ms DESC 倒序(沿 idx_audit_executed_at 索引)
        sorted_records = sorted(self._records, key=lambda r: r.executed_at_ms, reverse=True)
        return [r.to_dict() for r in sorted_records[:limit]]

    def count(self) -> int:
        """返回已落档总数(测试断言用)."""
        return len(self._records)


__all__ = [
    "AuditRecord",
    "AuditRecordResult",
    "ApprovalGateAuditStore",
    "ApprovalGateAuditStoreStub",
    "InMemoryApprovalGateAuditStore",
    "MAX_ACTOR_LEN",
    "MAX_LIST_RECENT",
    "MAX_REASON_LEN",
]


# ===== 自检(开发期,测试用)=====

# 注:实际测试由 tests/dashboard/test_approval_gate_audit.py 覆盖


def _now_ms() -> int:
    """Unix epoch 毫秒时间戳(沿 v0.2.53.11 actor 默认值时间戳)."""
    return int(time.time() * 1000)
