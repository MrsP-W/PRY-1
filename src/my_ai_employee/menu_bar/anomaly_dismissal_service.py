"""v0.2.53.16 AnomalyDismissalService 接口 + Stub(沿 v0.2.53.14 设计 + NoteConfirmService 范本).

承接 docs/v0.2.53.14-business-writer-design-2026-06-26.md §5 `AnomalyDismissalService` 设计:
    - finance.dismiss_anomaly 是 v0.2.53.11 ApprovalGate 契约白名单的 4 类动作之一
    - 但 AnomalyDetector / ExpenseService 都没有 dismiss_anomaly 方法
    - 本模块填补该缺口(Protocol + Stub,Real 留 v0.2.53.17+)

设计决策(2026-06-26 锁定):
    - 抽象 AnomalyDismissalService Protocol 类(3 方法) + Stub 硬编码实现
    - anomaly_id 格式: {date}|{counterparty}|{amount}  例: 2026-06-26|星巴克|38.50
    - DismissalResult dataclass: success / anomaly_id / dismissed_at_ms / error / reason
    - 1-click 动作语义: dismiss(anomaly_id, reason='') → DB 落档(后续 v0.2.53.16+ alembic 0015 migration 落地)

D4.7.3 教训应用(沿 NoteConfirmService 范本):
    - Protocol 类型用 Protocol 类(非 ABC,鸭子类型友好)
    - 3 方法返回值用 `Final` 常量(避免硬编码分散)
    - 严判 type 严格(不 isinstance,避免 bool/int 互窜)
    - Stub 异常收容: dismiss 失败 → 返回 DismissalResult(success=False, error=...)

撞坑 #65 边界应用:
    - 默认全 Stub,无真实写入
    - is_enabled() 默认 False(需要 DASHBOARD_REAL_DB=1 opt-in)
    - 不写 DB / 不发 SMTP / 不读 Keychain 明文

沿用边界:
    - 本棒 docs-only + Protocol + Stub,不动真实 DB
    - Real(AnomalyDismissalServiceImpl) 留 v0.2.53.17+
    - 不接 BusinessWriter(留 v0.2.53.17 BusinessWriterImpl 接入)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol

# ===== AnomalyDismissalService Protocol 3 方法契约 =====


class AnomalyDismissalService(Protocol):
    """财务异常 dismiss 服务接口(v0.2.53.16 沿 v0.2.53.14 §5.2 设计).

    3 方法契约:
        - is_enabled             → 是否启用(撞坑 #65 opt-in 4 阶段)
        - dismiss                → 1-click dismiss: 落档 anomaly_dismissals 表(后续 alembic 0015)
        - list_recent_dismissals → 最近 dismissals 列表(查询用)
    """

    def is_enabled(self) -> bool: ...

    def dismiss(
        self,
        anomaly_id: str,
        *,
        reason: str = "",
    ) -> DismissalResult: ...

    def list_recent_dismissals(
        self,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...


# ===== DismissalResult dataclass(沿 v0.2.53.14 §5.2 设计)=====


@dataclass(frozen=True, slots=True)
class DismissalResult:
    """财务异常 dismiss 结果.

    边界:
        - success=True 时 anomaly_id 必填,dismissed_at_ms 必填
        - success=False 时 error 必填
    """

    success: bool
    anomaly_id: str | None
    dismissed_at_ms: int | None
    error: str | None
    reason: str | None


# ===== Stub 默认值常量(避免硬编码分散)=====

_IS_ENABLED_DEFAULT: Final[bool] = False
_DISMISSAL_LIST_DEFAULT: Final[list[dict[str, Any]]] = []
_MAX_REASON_LEN: Final[int] = 240


class AnomalyDismissalServiceStub:
    """AnomalyDismissalService Stub 实现 — 3 方法全部返回硬编码默认值(无 DB 接入).

    设计取舍(沿 NoteConfirmServiceStub 范本):
        - 不调 DB / 不调 OutboxStore(完全解耦,测试零依赖)
        - 单例 (`get_default_stub()`),避免每次 new(可热替换)
        - 类型签名与 Protocol 100% 对齐(Real 实现可直接替换)

    撞坑 #65 边界(默认禁写):
        - is_enabled() 恒返回 False(opt-in 才会变为 True)
        - dismiss() 恒返回失败结果(success=False, error='not_enabled')
        - list_recent_dismissals() 恒返回 []
    """

    def is_enabled(self) -> bool:
        """是否启用 — Stub 默认 False(撞坑 #65 opt-in 范本).

        Real 实现需检查 DASHBOARD_REAL_DB=1 + AnomalyDismissalStore 构造成功.
        """
        return _IS_ENABLED_DEFAULT

    def dismiss(
        self,
        anomaly_id: str,
        *,
        reason: str = "",
    ) -> DismissalResult:
        """no-op + 失败返回(stub 阶段不真 dismiss).

        Args:
            anomaly_id: 异常唯一 ID(str 格式 {date}|{counterparty}|{amount})
            reason: dismiss 原因(限 240 字符)

        Returns:
            DismissalResult(success=False, error='not_enabled') — Stub 永远不成功.
        """
        if not isinstance(anomaly_id, str) or not anomaly_id:
            return DismissalResult(
                success=False,
                anomaly_id=None,
                dismissed_at_ms=None,
                error="invalid_anomaly_id",
                reason="anomaly_id 必须为非空 str",
            )
        if not isinstance(reason, str):
            return DismissalResult(
                success=False,
                anomaly_id=None,
                dismissed_at_ms=None,
                error="invalid_reason",
                reason="reason 必须为 str",
            )
        if len(reason) > _MAX_REASON_LEN:
            return DismissalResult(
                success=False,
                anomaly_id=None,
                dismissed_at_ms=None,
                error="reason_too_long",
                reason=f"reason 超长({len(reason)}>{_MAX_REASON_LEN})",
            )
        # 默认禁写:返回 not_enabled(沿撞坑 #65 边界)
        return DismissalResult(
            success=False,
            anomaly_id=None,
            dismissed_at_ms=None,
            error="not_enabled",
            reason="AnomalyDismissalService 默认 Stub;需 v0.2.53.17+ 接入 Real(Impl)",
        )

    def list_recent_dismissals(
        self,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """返回 [] (stub 阶段无 DB 接入).

        Args:
            limit: 最大返回条数(stub 不校验,直接返回 [])
        """
        return list(_DISMISSAL_LIST_DEFAULT)

    @staticmethod
    def get_default_stub() -> AnomalyDismissalServiceStub:
        """默认 Stub 工厂(沿 NoteConfirmServiceStub.get_default_stub 范本)."""
        return AnomalyDismissalServiceStub()
