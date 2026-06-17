"""v0.2 D8.2 — 基于规则的异常检测器(沿 D8 docs 评估方案 A+C 组合).

承接 v0.1.0 post-tag 阶段 + v0.2 D8 智能财务异常检测启动。
D8 docs 评估决策(2026-06-16 锁定):
    - 方案 A (规则基础): 6 类异常硬编码阈值,纯本地 SQL 聚合
    - 方案 C (商家画像增强): D8.1 MerchantProfile 表存储历史画像
    - 不选方案 B (LLM): 违反"数据不出本机"铁律 + 月成本 ¥10 + 隐私风险

6 类异常:
    1. amount_3sigma          — 消费金额异常(amount > avg + 3σ,源内)
    2. frequency_5tx_per_hour — 频率异常(同 source 1 小时 > 5 笔)
    3. duplicate_charge       — 重复扣款(同 fingerprint 多笔 categorized)
    4. new_merchant           — 商家画像冷启动(< 5 笔历史 → 不画像)
    5. amount_drift           — 商家画像金额漂移(|amount - avg| > 3σ)
    6. category_drift         — 商家画像类目漂移(actual ∉ profile 分布)

设计权衡(沿 D8 docs 评估决策):
    - 不调 LLM(数据不出本机铁律)
    - 阈值硬编码(SIGMA_THRESHOLD=3.0 / HOURLY_TX_THRESHOLD=5)
    - 纯函数 + 依赖注入 TransactionStore + MerchantProfileStore
    - 不阻塞业务层:异常检测结果仅作业务信号,失败不能让月报崩(沿 D4.7.3 v1.0.1 范本)

D3.3.3 教训应用:
    - except 范围窄化: 不在 Detector 层捕获 OperationalError(让 Adapter 走技术失败入口)
    - DB 锁透传到调用方

D4.7.3 教训应用:
    - 数据类 dataclass(frozen=True) 强一致契约
    - 公共 API 入口严判 + 数据类 __post_init__ 双层防御
    - type() is bool 检查在 isinstance 前
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Literal

from my_ai_employee.db.transactions import Transaction

if TYPE_CHECKING:
    from my_ai_employee.db.merchant_profile import MerchantProfileStore
    from my_ai_employee.db.transactions import TransactionStore

# ===== 异常类型枚举(6 类,Literal 严判)=====

AnomalyKind = Literal[
    "amount_3sigma",
    "frequency_5tx_per_hour",
    "duplicate_charge",
    "new_merchant",
    "amount_drift",
    "category_drift",
]

# ===== 阈值硬编码(D8 docs 评估决策 #2:阈值放常量方便复用)=====

SIGMA_THRESHOLD: Decimal = Decimal("3.0")  # 3σ 离群点检测
HOURLY_TX_THRESHOLD: int = 5  # 1 小时最多 5 笔
DUPLICATE_FINGERPRINT_THRESHOLD: int = 2  # 同 fingerprint ≥ 2 笔触发重复扣款
MIN_HISTORY_FOR_SIGMA: int = 30  # 源内 σ 检测最小样本数


# ===== AnomalyResult 数据类(沿 D4.7.3 v1.0.6 范本:frozen=True 强一致契约)=====


@dataclass(frozen=True)
class AnomalyResult:
    """异常检测结果.

    Attributes:
        kind: 6 类异常之一(AnomalyKind Literal)
        tx: 触发异常的 Transaction
        context: 异常上下文(avg/std/count/profile 等)
        detected_at_ms: 检测时间戳(Unix epoch ms)
    """

    kind: AnomalyKind
    tx: Transaction
    context: dict[str, Any] = field(default_factory=dict)
    detected_at_ms: int = 0

    def __post_init__(self) -> None:
        """双层防御:数据类层级字段严判(沿 D4.7.3 v1.0.4 P1-1 范本)."""
        # 1. kind 必 ∈ 6 类白名单(用 frozenset 严判,type 严判在 hash 前)
        valid_kinds: frozenset[str] = frozenset(
            {
                "amount_3sigma",
                "frequency_5tx_per_hour",
                "duplicate_charge",
                "new_merchant",
                "amount_drift",
                "category_drift",
            }
        )
        if not isinstance(self.kind, str):
            raise TypeError(
                f"kind 必须是 str,实际 type={type(self.kind).__name__}, value={self.kind!r}"
            )
        if self.kind not in valid_kinds:
            raise ValueError(f"kind 必 ∈ 6 类白名单 {sorted(valid_kinds)!r}, 实际 {self.kind!r}")
        # 2. tx 必 Transaction 实例
        if not isinstance(self.tx, Transaction):
            raise TypeError(f"tx 必须是 Transaction,实际 type={type(self.tx).__name__}")
        # 3. context 必 dict
        if not isinstance(self.context, dict):
            raise TypeError(f"context 必须是 dict,实际 type={type(self.context).__name__}")
        # 4. detected_at_ms 必 int >= 0(拒 bool 子类)
        if (
            type(self.detected_at_ms) is bool
            or not isinstance(self.detected_at_ms, int)
            or self.detected_at_ms < 0
        ):
            raise ValueError(
                f"detected_at_ms 必须是原生 int(非 bool) >= 0, "
                f"实际 type={type(self.detected_at_ms).__name__}, value={self.detected_at_ms!r}"
            )


# ===== 工具函数 =====


def _now_ms() -> int:
    """当前时间 Unix epoch ms(便于测试 mock,沿 D5.5.4 范本)."""
    return int(time.time() * 1000)


# ===== RuleBasedAnomalyDetector(主类)=====


class RuleBasedAnomalyDetector:
    """基于规则的异常检测器(沿 D8 docs 评估方案 A + C 组合).

    6 类检测方法:
        - detect_amount_anomaly: 源内 σ 检测(amount_3sigma)
        - detect_frequency_anomaly: 1 小时频率检测(frequency_5tx_per_hour)
        - detect_duplicate_charge: 同 fingerprint 重复扣款(duplicate_charge)
        - detect_merchant_profile_drift: 商家画像漂移(3 子类)

    入口:
        - detect_all(tx): 综合检测,返回 list[AnomalyResult](同笔可能触发 2+ 类)

    注入依赖:
        - transaction_store: TransactionStore(读历史交易)
        - merchant_profile_store: MerchantProfileStore(读商家画像)
        - sigma_threshold: σ 阈值(默认 3.0)
        - hourly_tx_threshold: 频率阈值(默认 5)

    异常透传:
        - DB 锁 / OperationalError 不捕获,透传到调用方(沿 D3.3.3 教训)
        - 业务层(月报/菜单栏)接住异常走 fallback,不阻塞主流程(沿 D4.7.3 v1.0.1 范本)
    """

    def __init__(
        self,
        *,
        transaction_store: TransactionStore,
        merchant_profile_store: MerchantProfileStore,
        sigma_threshold: Decimal = SIGMA_THRESHOLD,
        hourly_tx_threshold: int = HOURLY_TX_THRESHOLD,
    ) -> None:
        """初始化。

        Args:
            transaction_store: TransactionStore 实例(注入依赖)
            merchant_profile_store: MerchantProfileStore 实例(注入依赖)
            sigma_threshold: σ 阈值(默认 3.0,可调)
            hourly_tx_threshold: 1 小时频率阈值(默认 5,可调)

        Raises:
            TypeError: 任一 store 缺失或非 None
            ValueError: 阈值越界
        """
        # 依赖注入严判(沿 D4.7.3 v1.0.5 P2-2 范本)
        if transaction_store is None:
            raise TypeError("transaction_store 必传非 None")
        if merchant_profile_store is None:
            raise TypeError("merchant_profile_store 必传非 None")
        if not isinstance(sigma_threshold, Decimal) or sigma_threshold <= 0:
            raise ValueError(f"sigma_threshold 必须是 Decimal > 0,实际 {sigma_threshold!r}")
        if (
            type(hourly_tx_threshold) is bool
            or not isinstance(hourly_tx_threshold, int)
            or hourly_tx_threshold < 1
        ):
            raise ValueError(
                f"hourly_tx_threshold 必须是原生 int(非 bool) >= 1,"
                f"实际 type={type(hourly_tx_threshold).__name__}, value={hourly_tx_threshold!r}"
            )
        self._tx_store = transaction_store
        self._profile_store = merchant_profile_store
        self._sigma = sigma_threshold
        self._hourly = hourly_tx_threshold

    # ===== 4 类检测方法(每类独立,可单独调)=====

    def detect_amount_anomaly(self, tx: Transaction) -> AnomalyResult | None:
        """源内 σ 检测(消费金额 > avg + 3σ).

        Args:
            tx: 待检测的 Transaction

        Returns:
            AnomalyResult 或 None(无异常或冷启动 < MIN_HISTORY_FOR_SIGMA)

        Raises:
            OperationalError / DataError / InterfaceError: 技术失败透传(D3.3.3 教训)
        """
        history = self._tx_store.list_by_source(tx.source, limit=200)
        if len(history) < MIN_HISTORY_FOR_SIGMA:
            return None  # 冷启动,样本不足
        amounts = [Decimal(h.amount) for h in history if Decimal(h.amount) > 0]
        if not amounts:
            return None
        # 平均值 + σ(Decimal 精度,防 0.1 + 0.2 漂移)
        avg = sum(amounts, Decimal("0")) / Decimal(len(amounts))
        variance = sum((a - avg) ** 2 for a in amounts) / Decimal(len(amounts))
        std = variance ** Decimal("0.5")
        if Decimal(tx.amount) > avg + self._sigma * std:
            return AnomalyResult(
                kind="amount_3sigma",
                tx=tx,
                context={
                    "avg": float(avg),
                    "std": float(std),
                    "amount": float(tx.amount),
                    "threshold": float(avg + self._sigma * std),
                },
                detected_at_ms=_now_ms(),
            )
        return None

    def detect_frequency_anomaly(self, tx: Transaction) -> AnomalyResult | None:
        """同 source 1 小时 > 5 笔频率检测.

        Args:
            tx: 待检测的 Transaction(tx.source 决定 source,tx.imported_at_ms 决定时窗起点)

        Returns:
            AnomalyResult 或 None

        Raises:
            OperationalError / DataError / InterfaceError: 技术失败透传
        """
        now_ms = tx.imported_at_ms or _now_ms()
        hour_ago = now_ms - 3600 * 1000
        # since = hour_ago 前 1 天(确保覆盖完整 1 小时)
        since_date = (datetime.fromtimestamp(hour_ago / 1000) - timedelta(days=1)).date()
        recent = self._tx_store.list_by_source(tx.source, since=since_date, limit=200)
        recent_in_hour = [r for r in recent if r.imported_at_ms >= hour_ago]
        if len(recent_in_hour) > self._hourly:
            return AnomalyResult(
                kind="frequency_5tx_per_hour",
                tx=tx,
                context={
                    "count": len(recent_in_hour),
                    "window": "1h",
                    "threshold": self._hourly,
                },
                detected_at_ms=_now_ms(),
            )
        return None

    def detect_duplicate_charge(self, tx: Transaction) -> AnomalyResult | None:
        """同 fingerprint 多笔 categorized(去重失败 = 重复扣款).

        Args:
            tx: 待检测的 Transaction

        Returns:
            AnomalyResult 或 None

        Raises:
            OperationalError / DataError / InterfaceError: 技术失败透传
        """
        candidates = self._tx_store.find_candidates_by_fingerprint(
            tx.normalized_fingerprint,
            exclude_tx_id=tx.id,
            limit=10,
        )
        # 候选中已 categorized / confirmed 状态的算"已入库"的同 fingerprint
        categorized = [c for c in candidates if c.status in ("categorized", "confirmed")]
        if len(categorized) >= DUPLICATE_FINGERPRINT_THRESHOLD - 1:
            return AnomalyResult(
                kind="duplicate_charge",
                tx=tx,
                context={
                    "fingerprint": tx.normalized_fingerprint[:16] + "...",
                    "candidate_count": len(candidates),
                    "categorized_count": len(categorized),
                    "threshold": DUPLICATE_FINGERPRINT_THRESHOLD,
                },
                detected_at_ms=_now_ms(),
            )
        return None

    def detect_merchant_profile_drift(self, tx: Transaction) -> list[AnomalyResult]:
        """商家画像漂移检测(3 子类:new_merchant / amount_drift / category_drift).

        Args:
            tx: 待检测的 Transaction

        Returns:
            list[AnomalyResult](0-3 个)

        Raises:
            OperationalError / DataError / InterfaceError: 技术失败透传
        """
        results: list[AnomalyResult] = []
        # 优先读已存的 MerchantProfile(手工 upsert),fallback 到 compute_profile 实时算
        existing_profile = self._profile_store.get_profile(tx.counterparty)
        if existing_profile is None:
            # 没存画像 → compute_profile(冷启动 < 5 笔返 None)
            profile = self._profile_store.compute_profile(tx.counterparty)
            if profile is None:
                results.append(
                    AnomalyResult(
                        kind="new_merchant",
                        tx=tx,
                        context={
                            "counterparty": tx.counterparty,
                            "tx_count": 0,
                            "threshold": 5,
                        },
                        detected_at_ms=_now_ms(),
                    )
                )
                return results
            profile_avg = profile["avg_amount"]
            profile_std = profile["amount_std"]
            category_dist_str = profile["category_distribution"]
        else:
            # 用已存画像字段(Decimal ORM 属性)
            profile_avg = existing_profile.avg_amount
            profile_std = existing_profile.amount_std
            category_dist_str = existing_profile.category_distribution

        # 类目漂移检测
        if tx.category:
            try:
                parsed = json.loads(category_dist_str)
                dist = (
                    {str(k): int(v) for k, v in parsed.items() if isinstance(v, (int, float))}
                    if isinstance(parsed, dict)
                    else {}
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                dist = {}
            if dist and tx.category not in dist:
                results.append(
                    AnomalyResult(
                        kind="category_drift",
                        tx=tx,
                        context={
                            "counterparty": tx.counterparty,
                            "profile_distribution": dist,
                            "actual_category": tx.category,
                        },
                        detected_at_ms=_now_ms(),
                    )
                )

        # 金额漂移检测(|amount - avg| > 3σ)
        try:
            profile_avg_dec = Decimal(str(profile_avg))
            profile_std_dec = Decimal(str(profile_std))
        except (ValueError, TypeError, InvalidOperation):
            return results  # 画像字段异常,不报金额漂移
        if (
            profile_std_dec > 0
            and abs(Decimal(tx.amount) - profile_avg_dec) > self._sigma * profile_std_dec
        ):
            results.append(
                AnomalyResult(
                    kind="amount_drift",
                    tx=tx,
                    context={
                        "counterparty": tx.counterparty,
                        "profile_avg": float(profile_avg_dec),
                        "profile_std": float(profile_std_dec),
                        "amount": float(tx.amount),
                    },
                    detected_at_ms=_now_ms(),
                )
            )
        return results

    # ===== 综合入口 =====

    def detect_all(self, tx: Transaction) -> list[AnomalyResult]:
        """综合检测 — 调 4 类检测方法 + 聚合结果.

        Args:
            tx: 待检测的 Transaction

        Returns:
            list[AnomalyResult](0-6 个,同笔可能触发 2+ 类)

        Raises:
            OperationalError / DataError / InterfaceError: 技术失败透传
        """
        results: list[AnomalyResult] = []
        r1 = self.detect_amount_anomaly(tx)
        if r1 is not None:
            results.append(r1)
        r2 = self.detect_frequency_anomaly(tx)
        if r2 is not None:
            results.append(r2)
        r3 = self.detect_duplicate_charge(tx)
        if r3 is not None:
            results.append(r3)
        profile_results = self.detect_merchant_profile_drift(tx)
        results.extend(profile_results)
        return results


# ===== helpers =====


__all__ = [
    "AnomalyKind",
    "AnomalyResult",
    "RuleBasedAnomalyDetector",
    "SIGMA_THRESHOLD",
    "HOURLY_TX_THRESHOLD",
    "MIN_HISTORY_FOR_SIGMA",
]
