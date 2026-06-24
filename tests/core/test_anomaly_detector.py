"""v0.2 D8.2 — RuleBasedAnomalyDetector + AnomalyResult 测试(12 cases).

承接 D8.1 MerchantProfile + Store + D6.4 TransactionStore + D7 跨源去重。
本测试覆盖 12 cases:

    1. AnomalyResult 数据类严判(3 tests) — kind 白名单 / context dict / detected_at_ms 类型
    2. detect_amount_anomaly 源内 σ 检测(2 tests) — 异常触发 / 冷启动 < 30 笔 fallback
    3. detect_frequency_anomaly 频率检测(2 tests) — 异常触发 / 边界 = 5 笔
    4. detect_duplicate_charge 重复扣款(2 tests) — 同 fingerprint 多笔 / 边界
    5. detect_merchant_profile_drift 商家画像漂移(2 tests) — new_merchant / amount_drift
    6. detect_all 综合(1 test) — 单笔触发 2 类异常

D8 docs 评估决策应用:
    - 6 类异常阈值硬编码(σ=3.0 / 5tx/h)
    - 不调 LLM,纯本地 SQL 聚合
    - 失败透传到调用方(OperationalError 不捕获)

D3.3.3 教训应用:
    - except 范围窄化(Detector 不捕获 OperationalError)

D4.7.3 教训应用:
    - 数据类 dataclass(frozen=True) 强一致契约
    - 公共 API 入口严判 + 数据类 __post_init__ 双层防御
    - type() is bool 检查在 isinstance 前

Fixture 复用 tests/db/test_transactions.py 范本:
    - InMemory SQLite 模式(不依赖真 SQLCipher,快)
    - 测试间用 rollback 隔离
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== Fixtures(D8.2 范本:InMemory SQLite + 2 ORM create_all,function-scope 隔离)=====


@pytest.fixture
def engine() -> Iterator:
    """InMemory SQLite + MerchantProfile + Transaction 2 ORM create_all."""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.merchant_profile import MerchantProfile  # noqa: F401
    from my_ai_employee.db.transactions import Transaction  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    """返回 sessionmaker(expire_on_commit=False 避免 commit 后 attribute 过期)."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def stores(session_factory: Any) -> Any:
    """返回 (TransactionStore, MerchantProfileStore) 元组(供多测试复用)."""
    from my_ai_employee.db.merchant_profile import MerchantProfileStore
    from my_ai_employee.db.transactions import TransactionStore

    tx_store = TransactionStore(session_factory)
    profile_store = MerchantProfileStore(session_factory, transaction_store=tx_store)
    return tx_store, profile_store


@pytest.fixture
def detector(stores: Any) -> Any:
    """RuleBasedAnomalyDetector 实例."""
    from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector

    tx_store, profile_store = stores
    return RuleBasedAnomalyDetector(
        transaction_store=tx_store,
        merchant_profile_store=profile_store,
    )


# ===== Helpers =====


def _make_fp(seed: str) -> str:
    """生成 32 chars 小写 hex fingerprint(沿 D6.2 范本)."""
    import hashlib

    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def _seed_baseline(
    tx_store: Any, counterparty: str, n: int, base_amount: Decimal = Decimal("50.00")
) -> None:
    """插 n 笔 baseline(默认 ¥50)."""
    from my_ai_employee.db.transactions import Transaction

    with tx_store._session_factory() as session:
        for i in range(n):
            session.add(
                Transaction(
                    source="wechat",
                    external_transaction_id=f"{counterparty}-{i:04d}",
                    transaction_date=date(2026, 5, 1 + i % 28),
                    amount=base_amount,
                    counterparty=counterparty,
                    category="dining",
                    normalized_fingerprint=_make_fp(f"{counterparty}-{i:04d}"),
                    status="categorized",
                    imported_at_ms=1_700_000_000_000 + i * 1000,
                    raw_row_json="{}",
                )
            )
        session.commit()


# ===== Segment 1: AnomalyResult 数据类严判(3 tests)=====


def test_anomaly_result_kind_whitelist_validates() -> None:
    """Case 1 — AnomalyResult kind 必 ∈ 6 类白名单."""
    from my_ai_employee.core.anomaly_detector import AnomalyResult
    from my_ai_employee.db.transactions import Transaction

    # 构造一个临时 Transaction(必传字段)
    tx = Transaction(
        source="wechat",
        external_transaction_id="test-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("100.00"),
        counterparty="test",
        normalized_fingerprint=_make_fp("test-001"),
        status="categorized",
        imported_at_ms=1_700_000_000_000,
        raw_row_json="{}",
    )
    # 非法 kind → ValueError
    with pytest.raises(ValueError, match="kind 必 ∈ 6 类白名单"):
        AnomalyResult(kind="invalid_kind", tx=tx, context={}, detected_at_ms=0)  # type: ignore[arg-type]
    # 非法 kind 类型 → TypeError
    with pytest.raises(TypeError, match="kind 必须是 str"):
        AnomalyResult(kind=123, tx=tx, context={}, detected_at_ms=0)  # type: ignore[arg-type]


def test_anomaly_result_context_must_be_dict() -> None:
    """Case 2 — AnomalyResult context 必 dict 类型."""
    from my_ai_employee.core.anomaly_detector import AnomalyResult
    from my_ai_employee.db.transactions import Transaction

    tx = Transaction(
        source="wechat",
        external_transaction_id="test-002",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("100.00"),
        counterparty="test",
        normalized_fingerprint=_make_fp("test-002"),
        status="categorized",
        imported_at_ms=1_700_000_000_000,
        raw_row_json="{}",
    )
    # 非 dict → TypeError
    with pytest.raises(TypeError, match="context 必须是 dict"):
        AnomalyResult(
            kind="amount_3sigma",
            tx=tx,
            context="not a dict",  # type: ignore[arg-type]
            detected_at_ms=0,
        )


def test_anomaly_result_detected_at_ms_rejects_bool() -> None:
    """Case 3 — AnomalyResult detected_at_ms 拒 bool(D4.7.3 v1.0.4 P2-2 范本)."""
    from my_ai_employee.core.anomaly_detector import AnomalyResult
    from my_ai_employee.db.transactions import Transaction

    tx = Transaction(
        source="wechat",
        external_transaction_id="test-003",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("100.00"),
        counterparty="test",
        normalized_fingerprint=_make_fp("test-003"),
        status="categorized",
        imported_at_ms=1_700_000_000_000,
        raw_row_json="{}",
    )
    # bool 子类 → ValueError(D4.7.3 范本:type() is bool 拒 True/False)
    with pytest.raises(ValueError, match="detected_at_ms 必须是原生 int"):
        AnomalyResult(
            kind="amount_3sigma",
            tx=tx,
            context={},
            detected_at_ms=True,  # type: ignore[arg-type]
        )
    # 负数 → ValueError
    with pytest.raises(ValueError, match="detected_at_ms 必须是原生 int"):
        AnomalyResult(
            kind="amount_3sigma",
            tx=tx,
            context={},
            detected_at_ms=-1,
        )


# ===== Segment 2: detect_amount_anomaly(2 tests)=====


def test_detect_amount_anomaly_triggers_on_large_amount(detector: Any, stores: Any) -> None:
    """Case 4 — detect_amount_anomaly 触发 amount_3sigma(35 笔 ¥50 + 1 笔 ¥888)."""
    tx_store, _ = stores
    _seed_baseline(tx_store, "星巴克", n=35, base_amount=Decimal("50.00"))

    # 待检测 ¥888 远大于均值 + 3σ(σ=0 → avg + 3σ = 50)
    from my_ai_employee.db.transactions import Transaction

    target = Transaction(
        source="wechat",
        external_transaction_id="starbucks-anomaly",
        transaction_date=date(2026, 6, 1),
        amount=Decimal("888.00"),
        counterparty="星巴克",
        category="dining",
        normalized_fingerprint=_make_fp("starbucks-anomaly"),
        status="categorized",
        imported_at_ms=1_716_000_000_000,
        raw_row_json="{}",
    )
    result = detector.detect_amount_anomaly(target)
    assert result is not None
    assert result.kind == "amount_3sigma"
    assert result.tx is target
    assert result.context["amount"] == 888.0
    assert result.detected_at_ms > 0


def test_detect_amount_anomaly_returns_none_for_cold_start(detector: Any, stores: Any) -> None:
    """Case 5 — detect_amount_anomaly < 30 笔历史 → None(冷启动 fallback)."""
    tx_store, _ = stores
    _seed_baseline(tx_store, "新商家", n=10, base_amount=Decimal("50.00"))

    from my_ai_employee.db.transactions import Transaction

    target = Transaction(
        source="wechat",
        external_transaction_id="new-merchant-test",
        transaction_date=date(2026, 6, 1),
        amount=Decimal("888.00"),
        counterparty="新商家",
        category="dining",
        normalized_fingerprint=_make_fp("new-merchant-test"),
        status="categorized",
        imported_at_ms=1_716_000_000_000,
        raw_row_json="{}",
    )
    # < 30 笔(< MIN_HISTORY_FOR_SIGMA)→ None
    result = detector.detect_amount_anomaly(target)
    assert result is None


# ===== Segment 3: detect_frequency_anomaly(2 tests)=====


def test_detect_frequency_anomaly_triggers_over_threshold(detector: Any, stores: Any) -> None:
    """Case 6 — detect_frequency_anomaly 触发(1 小时 6 笔 > 5 笔阈值)."""
    from my_ai_employee.db.transactions import Transaction

    tx_store, _ = stores
    now_ms = 1_716_000_000_000  # 2024-06-01 某个时间
    # 插 5 笔 1 小时内(同 source)
    with tx_store._session_factory() as session:
        for i in range(5):
            session.add(
                Transaction(
                    source="alipay",
                    external_transaction_id=f"alipay-{i:03d}",
                    transaction_date=date(2024, 6, 1),
                    amount=Decimal("10.00"),
                    counterparty="测试商家",
                    category="dining",
                    normalized_fingerprint=_make_fp(f"alipay-{i:03d}"),
                    status="categorized",
                    imported_at_ms=now_ms - i * 60_000,  # 间隔 1 分钟
                    raw_row_json="{}",
                )
            )
        # 第 6 笔(同 source 同小时)→ 待检测
        target = Transaction(
            source="alipay",
            external_transaction_id="alipay-trigger",
            transaction_date=date(2024, 6, 1),
            amount=Decimal("10.00"),
            counterparty="测试商家",
            category="dining",
            normalized_fingerprint=_make_fp("alipay-trigger"),
            status="categorized",
            imported_at_ms=now_ms,
            raw_row_json="{}",
        )
        session.add(target)
        session.commit()

    result = detector.detect_frequency_anomaly(target)
    assert result is not None
    assert result.kind == "frequency_5tx_per_hour"
    assert result.context["count"] >= 5  # 含自身共 6 笔
    assert result.context["window"] == "1h"


def test_detect_frequency_anomaly_returns_none_under_threshold(detector: Any, stores: Any) -> None:
    """Case 7 — detect_frequency_anomaly 边界 = 5 笔 → None(< 5 阈值要求 > 5)."""
    from my_ai_employee.db.transactions import Transaction

    tx_store, _ = stores
    now_ms = 1_716_000_000_000
    # 插 4 笔 1 小时内 + 1 笔待检测(同 source)→ 共 5 笔
    with tx_store._session_factory() as session:
        for i in range(4):
            session.add(
                Transaction(
                    source="wechat",
                    external_transaction_id=f"wx-{i:03d}",
                    transaction_date=date(2024, 6, 1),
                    amount=Decimal("10.00"),
                    counterparty="test",
                    category="dining",
                    normalized_fingerprint=_make_fp(f"wx-{i:03d}"),
                    status="categorized",
                    imported_at_ms=now_ms - i * 60_000,
                    raw_row_json="{}",
                )
            )
        target = Transaction(
            source="wechat",
            external_transaction_id="wx-trigger",
            transaction_date=date(2024, 6, 1),
            amount=Decimal("10.00"),
            counterparty="test",
            category="dining",
            normalized_fingerprint=_make_fp("wx-trigger"),
            status="categorized",
            imported_at_ms=now_ms,
            raw_row_json="{}",
        )
        session.add(target)
        session.commit()

    result = detector.detect_frequency_anomaly(target)
    # 5 笔 = 阈值,不触发(>,非 >=)
    assert result is None


# ===== Segment 4: detect_duplicate_charge(2 tests)=====


def test_detect_duplicate_charge_triggers_with_same_fingerprint(detector: Any, stores: Any) -> None:
    """Case 8 — detect_duplicate_charge 同 fingerprint 多笔 → 触发."""
    from my_ai_employee.db.transactions import Transaction

    tx_store, _ = stores
    dup_fp = _make_fp("duplicate-test")
    with tx_store._session_factory() as session:
        # 2 笔同 fingerprint 已 categorized
        for i in range(2):
            session.add(
                Transaction(
                    source="wechat",
                    external_transaction_id=f"dup-{i}",
                    transaction_date=date(2026, 6, 14),
                    amount=Decimal("100.00"),
                    counterparty="重复扣款商家",
                    category="dining",
                    normalized_fingerprint=dup_fp,
                    status="categorized",
                    imported_at_ms=1_700_000_000_000 + i * 1000,
                    raw_row_json="{}",
                )
            )
        # 第 3 笔同 fingerprint 待检测
        target = Transaction(
            source="wechat",
            external_transaction_id="dup-target",
            transaction_date=date(2026, 6, 14),
            amount=Decimal("100.00"),
            counterparty="重复扣款商家",
            category="dining",
            normalized_fingerprint=dup_fp,
            status="categorized",
            imported_at_ms=1_700_000_000_000 + 3000,
            raw_row_json="{}",
        )
        session.add(target)
        session.commit()

    result = detector.detect_duplicate_charge(target)
    assert result is not None
    assert result.kind == "duplicate_charge"
    assert result.context["categorized_count"] >= DUPLICATE_FINGERPRINT_THRESHOLD - 1


def test_detect_duplicate_charge_returns_none_for_unique_fingerprint(detector: Any) -> None:
    """Case 9 — detect_duplicate_charge 唯一 fingerprint → None."""
    from my_ai_employee.db.transactions import Transaction

    target = Transaction(
        source="wechat",
        external_transaction_id="unique",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("100.00"),
        counterparty="唯一商家",
        category="dining",
        normalized_fingerprint=_make_fp("unique-fingerprint"),
        status="categorized",
        imported_at_ms=1_700_000_000_000,
        raw_row_json="{}",
    )
    result = detector.detect_duplicate_charge(target)
    assert result is None


# ===== Segment 5: detect_merchant_profile_drift(2 tests)=====


def test_detect_merchant_profile_drift_new_merchant(detector: Any, stores: Any) -> None:
    """Case 10 — detect_merchant_profile_drift < 5 笔历史 → new_merchant."""
    tx_store, _ = stores
    # 插 3 笔(< 5 阈值)
    _seed_baseline(tx_store, "全新商家", n=3, base_amount=Decimal("30.00"))

    from my_ai_employee.db.transactions import Transaction

    target = Transaction(
        source="wechat",
        external_transaction_id="new-merchant-target",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("30.00"),
        counterparty="全新商家",
        category="dining",
        normalized_fingerprint=_make_fp("new-merchant-target"),
        status="categorized",
        imported_at_ms=1_700_000_000_000,
        raw_row_json="{}",
    )
    results = detector.detect_merchant_profile_drift(target)
    assert len(results) == 1
    assert results[0].kind == "new_merchant"
    assert results[0].context["counterparty"] == "全新商家"


def test_detect_merchant_profile_drift_amount_drift(detector: Any, stores: Any) -> None:
    """Case 11 — detect_merchant_profile_drift 金额漂移 → amount_drift."""
    tx_store, profile_store = stores
    # 插 10 笔 ¥50(均值 50,σ=0 → 无 σ 漂移)
    _seed_baseline(tx_store, "已知商家", n=10, base_amount=Decimal("50.00"))

    # 手工 upsert 一个 σ=5 的画像(避免 σ=0 导致 amount_drift 不触发)
    import json
    import time

    profile_store.upsert_profile(
        {
            "counterparty": "已知商家",
            "avg_amount": Decimal("50.00"),
            "amount_std": Decimal("5.00"),  # σ=5 让 ¥500 触发 3σ
            "category_distribution": json.dumps({"dining": 10}),
            "tx_count": 10,
            "last_seen_ms": int(time.time() * 1000),
        }
    )

    from my_ai_employee.db.transactions import Transaction

    target = Transaction(
        source="wechat",
        external_transaction_id="amount-drift-target",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("500.00"),  # 远超 avg + 3σ = 50 + 15 = 65
        counterparty="已知商家",
        category="dining",
        normalized_fingerprint=_make_fp("amount-drift-target"),
        status="categorized",
        imported_at_ms=1_700_000_000_000,
        raw_row_json="{}",
    )
    results = detector.detect_merchant_profile_drift(target)
    # 至少 1 个 amount_drift(类目一致不触发 category_drift)
    kinds = {r.kind for r in results}
    assert "amount_drift" in kinds
    assert all(r.context["counterparty"] == "已知商家" for r in results)


# ===== Segment 6: detect_all 综合(1 test)=====


def test_detect_all_returns_multiple_anomalies_for_same_transaction(
    detector: Any, stores: Any
) -> None:
    """Case 12 — detect_all 单笔触发 2 类异常(amount_3sigma + frequency)."""
    tx_store, _ = stores
    # 35 笔 ¥50 baseline + 5 笔 1 小时内(同 source)
    _seed_baseline(tx_store, "综合", n=35, base_amount=Decimal("50.00"))
    now_ms = 1_716_000_000_000
    from my_ai_employee.db.transactions import Transaction

    with tx_store._session_factory() as session:
        for i in range(5):
            session.add(
                Transaction(
                    source="wechat",
                    external_transaction_id=f"combo-{i}",
                    transaction_date=date(2024, 6, 1),
                    amount=Decimal("10.00"),
                    counterparty="综合",
                    category="dining",
                    normalized_fingerprint=_make_fp(f"combo-{i}"),
                    status="categorized",
                    imported_at_ms=now_ms - i * 60_000,
                    raw_row_json="{}",
                )
            )
        # 待检测笔: ¥888(异常金额)+ 1 小时内(触发频率)
        target = Transaction(
            source="wechat",
            external_transaction_id="combo-trigger",
            transaction_date=date(2024, 6, 1),
            amount=Decimal("888.00"),
            counterparty="综合",
            category="dining",
            normalized_fingerprint=_make_fp("combo-trigger"),
            status="categorized",
            imported_at_ms=now_ms,
            raw_row_json="{}",
        )
        session.add(target)
        session.commit()

    results = detector.detect_all(target)
    kinds = {r.kind for r in results}
    # 至少 amount_3sigma + frequency_5tx_per_hour 触发
    assert "amount_3sigma" in kinds
    assert "frequency_5tx_per_hour" in kinds
    # 所有结果都关联同一笔 tx
    assert all(r.tx is target for r in results)


# ===== 阈值常量(测试用,供 assert 引用)=====
DUPLICATE_FINGERPRINT_THRESHOLD = 2  # 来自 core.anomaly_detector


# ===== Segment 7 (v0.2 D8.5.2): is_signal + frequency 修复验证(2 cases)=====


def test_anomaly_result_is_signal_validates_and_new_merchant_sets_true(
    detector: Any, stores: Any
) -> None:
    """Case 13 (D8.5.2) — is_signal 字段严判 + new_merchant 自动设 True."""
    from my_ai_employee.core.anomaly_detector import AnomalyResult
    from my_ai_employee.db.transactions import Transaction

    tx = Transaction(
        source="wechat",
        external_transaction_id="signal-test-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("30.00"),
        counterparty="全新商家",
        normalized_fingerprint=_make_fp("signal-test-001"),
        status="categorized",
        imported_at_ms=1_700_000_000_000,
        raw_row_json="{}",
    )
    # is_signal 非 bool(int)→ TypeError(D4.7.3 v1.0.5 P2-1 范本)
    with pytest.raises(TypeError, match="is_signal 必须是原生 bool"):
        AnomalyResult(
            kind="new_merchant",
            tx=tx,
            context={},
            detected_at_ms=0,
            is_signal=1,  # type: ignore[arg-type]
        )
    # 合法 AnomalyResult 默认 is_signal=False
    result = AnomalyResult(kind="amount_3sigma", tx=tx, context={}, detected_at_ms=0)
    assert result.is_signal is False

    # Detector 自动给 new_merchant 设 is_signal=True
    results = detector.detect_merchant_profile_drift(tx)
    assert len(results) == 1
    assert results[0].kind == "new_merchant"
    assert results[0].is_signal is True  # D8.5.2 修复:冷启动业务信号


def test_detect_frequency_anomaly_uses_precise_ms_time_window(
    detector: Any, session_factory: Any
) -> None:
    """Case 14 (D8.5.2) — detect_frequency_anomaly 改调精确毫秒时窗,跨天 5 笔不误报."""
    from my_ai_employee.db.transactions import Transaction

    base_ms = 1_715_000_000_000  # 2024-05-12 14:30 UTC ms
    # 5 笔跨日(每天 1 笔,跨 3 天),全部 > 1 小时间隔
    with session_factory() as session:
        for i in range(5):
            session.add(
                Transaction(
                    source="wechat",
                    external_transaction_id=f"freq-fix-{i}",
                    transaction_date=date(2024, 5, 12 + i),
                    amount=Decimal("30.00"),
                    counterparty="测试商家",
                    category="dining",
                    normalized_fingerprint=_make_fp(f"freq-fix-{i}"),
                    status="categorized",
                    imported_at_ms=base_ms + i * 86400 * 1000,  # +1 天
                    raw_row_json="{}",
                )
            )
        session.commit()

        target = session.query(Transaction).filter_by(external_transaction_id="freq-fix-4").one()

    # 5 笔全部跨日(> 1 小时间隔),精确时窗内只有 1 笔(自身)
    # 不应触发 frequency_5tx_per_hour(D8.5.2 修复验证)
    result = detector.detect_frequency_anomaly(target)
    assert result is None  # 跨日不误报
