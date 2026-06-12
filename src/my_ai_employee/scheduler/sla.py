"""D5.5 — SLAEvaluator: outbox 条目 SLA 状态评估.

承接:
  - D4.7.3 v1.0.5 P1-2 范本:跨字段双向强一致
  - D4.7.3 v1.0.4 P2-4 范本:strip() 严判语义非空
  - D4.7.3 v1.0.3 P2-2 范本:依赖注入 is None 不用 or
  - D4.7.3 v1.0.5 P2-2 范本:bool 子类是 int 陷阱,type() is int 严判

SLA 阈值表(per D5 启动计划):
    URGENT:  threshold=5min,    warning=3min
    HIGH:    threshold=30min,   warning=15min
    NORMAL:  threshold=4hour,   warning=2hour

状态机:
    OK       — 邮件未超 SLA 阈值一半(未进 WARNING 区间)
    WARNING  — 已超 warning 阈值,未超 threshold
    BREACH   — 已超 threshold 阈值,需 ESCALATE_REQUIRED 决策

OutboxPriority 与 SLA 映射:
    URGENT → threshold=300_000ms (5min),   warning=180_000ms (3min)
    NORMAL → threshold=14_400_000ms (4h),  warning=7_200_000ms (2h)
    LOW    → threshold=86_400_000ms (24h),  warning=43_200_000ms (12h)
    (D5 阶段没有 HIGH 优先级,但保留 30min/15min 阈值表作为 API 占位,见 B 类延后)

设计原则:
  - age_ms = now_ms - created_at(必 >= 0, 倒流抛 ValueError)
  - priority 严判(白名单 + type 严判在 hash 前)
  - 工厂层 + __post_init__ 双层防御(沿 D4.7.3 v1.0.5 P1-1 范本)
  - 跨字段强一致(age_ms >= warning_ms → status ∈ {WARNING, BREACH})
  - 边界对称严判(threshold > warning > 0)
  - 模块级常量 Final 化(避免运行时修改)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from my_ai_employee.core.outbox import OutboxPriority

# ===== SLA 阈值常量(模块级 Final,见 B 类决策延后清单 — HIGH 阈值未启用)=====

# URGENT 优先级 SLA:5 分钟硬超,3 分钟预警
_URGENT_THRESHOLD_MS: int = 5 * 60 * 1000  # 300_000
_URGENT_WARNING_MS: int = 3 * 60 * 1000  # 180_000

# NORMAL 优先级 SLA:4 小时硬超,2 小时预警
_NORMAL_THRESHOLD_MS: int = 4 * 60 * 60 * 1000  # 14_400_000
_NORMAL_WARNING_MS: int = 2 * 60 * 60 * 1000  # 7_200_000

# LOW 优先级 SLA:24 小时硬超,12 小时预警
_LOW_THRESHOLD_MS: int = 24 * 60 * 60 * 1000  # 86_400_000
_LOW_WARNING_MS: int = 12 * 60 * 60 * 1000  # 43_200_000

# 优先级 → (threshold_ms, warning_ms) 映射
_SLA_THRESHOLDS: dict[str, tuple[int, int]] = {
    OutboxPriority.URGENT.value: (_URGENT_THRESHOLD_MS, _URGENT_WARNING_MS),
    OutboxPriority.NORMAL.value: (_NORMAL_THRESHOLD_MS, _NORMAL_WARNING_MS),
    OutboxPriority.LOW.value: (_LOW_THRESHOLD_MS, _LOW_WARNING_MS),
}


# ===== SLA 状态枚举 =====


class SLAStatus(enum.StrEnum):
    """D5.5 SLA 评估状态(3 态 — 沿 Heartbeat.Liveness 范本).

    OK:      邮件未超 SLA 阈值一半(age_ms < warning_ms)
    WARNING: 邮件已超 warning 但未超 threshold(age_ms >= warning_ms && age_ms < threshold_ms)
    BREACH:  邮件已超 threshold(age_ms >= threshold_ms, 需 ESCALATE_REQUIRED 决策)
    """

    OK = "ok"
    WARNING = "warning"
    BREACH = "breach"


# ===== SLAEvaluation dataclass(3 字段 — 沿 Heartbeat Liveness 范本)=====


@dataclass(frozen=True)
class SLAEvaluation:
    """D5.5 单次 SLA 评估结果(3 字段 — 业务数据单维度).

    跨字段强一致(D4.7.3 v1.0.5 P1-2 范本):
        status == SLAStatus.BREACH  ↔  age_ms >= threshold_ms
        status == SLAStatus.WARNING ↔  warning_ms <= age_ms < threshold_ms
        status == SLAStatus.OK      ↔  age_ms < warning_ms

    Attributes:
        priority:     邮件优先级(str 严判白名单)
        age_ms:       邮件自创建以来时长(>= 0)
        status:       SLA 状态(OK / WARNING / BREACH)
    """

    priority: str
    age_ms: int
    status: SLAStatus

    def __post_init__(self) -> None:
        """D5.5 字段契约自洽校验(4 范本全应用)."""
        # 1. priority 白名单(D4.7.3 v1.0.5 P2-1 范本:type 严判在 hash 操作前)
        if not isinstance(self.priority, str):
            raise ValueError(
                f"priority 必须是 str, 实际 {type(self.priority).__name__}={self.priority!r}"
            )
        if self.priority not in _SLA_THRESHOLDS:
            raise ValueError(
                f"priority 必须是 {_SLA_THRESHOLDS.keys()!r} 之一, 实际 {self.priority!r}"
            )
        # 2. age_ms 严判(bool 子类陷阱 + int 边界)
        if type(self.age_ms) is bool or not isinstance(self.age_ms, int) or self.age_ms < 0:
            raise ValueError(
                f"age_ms 必须是原生 int(非 bool) >= 0, 实际 "
                f"{type(self.age_ms).__name__}={self.age_ms!r}"
            )
        # 3. status 严判(白名单)
        if not isinstance(self.status, SLAStatus):
            raise ValueError(
                f"status 必须是 SLAStatus 枚举, 实际 {type(self.status).__name__}={self.status!r}"
            )
        # 4. 跨字段强一致(D4.7.3 v1.0.5 P1-2 范本)
        _threshold_ms, _warning_ms = _SLA_THRESHOLDS[self.priority]
        if self.status == SLAStatus.BREACH and self.age_ms < _threshold_ms:
            raise ValueError(
                f"SLAEvaluation 跨字段违反: status=BREACH 必 age_ms >= "
                f"threshold_ms({_threshold_ms}), 实际 age_ms={self.age_ms}"
            )
        if self.status == SLAStatus.WARNING and (
            self.age_ms < _warning_ms or self.age_ms >= _threshold_ms
        ):
            raise ValueError(
                f"SLAEvaluation 跨字段违反: status=WARNING 必 warning_ms({_warning_ms}) <= "
                f"age_ms < threshold_ms({_threshold_ms}), 实际 age_ms={self.age_ms}"
            )
        if self.status == SLAStatus.OK and self.age_ms >= _warning_ms:
            raise ValueError(
                f"SLAEvaluation 跨字段违反: status=OK 必 age_ms < warning_ms({_warning_ms}), "
                f"实际 age_ms={self.age_ms}"
            )


# ===== SLAEvaluator 主类(纯函数范本 — 无状态,可直接当 module function 调)=====


class SLAEvaluator:
    """D5.5 SLA 评估器(纯函数式 — 无状态).

    用法:
        evaluation = SLAEvaluator.evaluate(priority="urgent", age_ms=200_000)
        if evaluation.status == SLAStatus.BREACH:
            # ESCALATE_REQUIRED 决策
            ...

    设计:
      - 单方法 evaluate() 接受 priority + age_ms(纯输入)
      - 无内部状态(线程安全)
      - 边界值严判(age_ms == threshold_ms 视为 BREACH)
      - priority == HIGH 不在 D5 范围(B 类决策延后)→ 抛 ValueError
    """

    @staticmethod
    def evaluate(priority: str, age_ms: int) -> SLAEvaluation:
        """评估 outbox 条目 SLA 状态.

        Args:
            priority: 邮件优先级(必填,白名单内)
            age_ms:  邮件自创建以来时长(ms, 必 >= 0)

        Returns:
            SLAEvaluation: 3 字段(priority / age_ms / status)

        Raises:
            ValueError: priority 非法 / age_ms 非法
        """
        # 1. priority 白名单(type 严判在 hash 前)
        if not isinstance(priority, str):
            raise ValueError(f"priority 必须是 str, 实际 {type(priority).__name__}={priority!r}")
        if priority not in _SLA_THRESHOLDS:
            raise ValueError(
                f"priority 必须是 {list(_SLA_THRESHOLDS.keys())!r} 之一, 实际 {priority!r}"
            )
        # 2. age_ms 严判
        if type(age_ms) is bool or not isinstance(age_ms, int) or age_ms < 0:
            raise ValueError(
                f"age_ms 必须是原生 int(非 bool) >= 0, 实际 {type(age_ms).__name__}={age_ms!r}"
            )
        # 3. 阈值对照
        _threshold_ms, _warning_ms = _SLA_THRESHOLDS[priority]
        if age_ms >= _threshold_ms:
            status = SLAStatus.BREACH
        elif age_ms >= _warning_ms:
            status = SLAStatus.WARNING
        else:
            status = SLAStatus.OK
        return SLAEvaluation(priority=priority, age_ms=age_ms, status=status)


# ===== 模块导出 =====


__all__ = [
    "SLAEvaluation",
    "SLAEvaluator",
    "SLAStatus",
]
