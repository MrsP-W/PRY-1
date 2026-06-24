"""v0.2 D8.4 — S11 真链路 e2e 测试(3 cases).

承接 v0.1.0 post-tag 阶段 + v0.2 D8.4 S11 真链路 spike。
本 e2e 覆盖 3 cases:

    1. S11.1 amount_3sigma 检测(35 笔 baseline + 1 笔 ¥888)
    2. S11.2 frequency_5tx_per_hour 检测(6 笔/h 同 source)
    3. S11.3 商家画像冷启动(new_merchant 标记,< 5 笔历史)

设计原则(沿 D8 docs 评估决策):
    - 临时 SQLite + create_all(不跑 alembic,纯 create_all)
    - tmp_path fixture 隔离(测试间不污染)
    - 4 退出码契约:0 成功 / 1 解析 / 2 业务 / 3 技术

Fixture 复用 tests/db/test_transactions.py 范本:
    - InMemory SQLite 模式(快)
    - @pytest.mark.e2e 标记
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== Fixtures =====


@pytest.fixture
def engine() -> Iterator[Any]:
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
    """返回 sessionmaker[Any]."""
    return sessionmaker[Any](bind=engine, expire_on_commit=False)


@pytest.fixture
def detector(session_factory: Any) -> Any:
    """RuleBasedAnomalyDetector + 2 stores."""
    from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector
    from my_ai_employee.db.merchant_profile import MerchantProfileStore
    from my_ai_employee.db.transactions import TransactionStore

    tx_store = TransactionStore(session_factory)
    profile_store = MerchantProfileStore(session_factory, transaction_store=tx_store)
    return RuleBasedAnomalyDetector(
        transaction_store=tx_store,
        merchant_profile_store=profile_store,
    )


# ===== Helpers =====


def _make_fp(seed: str) -> str:
    """生成 32 chars 小写 hex fingerprint(沿 D6.2 范本)."""
    import hashlib

    return hashlib.sha256(seed.encode()).hexdigest()[:32]


# ===== E2E Cases =====


@pytest.mark.e2e
def test_s11_amount_3sigma_end_to_end(detector: Any, session_factory: Any) -> None:
    """S11.1 — 35 笔 ¥50 baseline + 1 笔 ¥888 → amount_3sigma 触发(端到端真链路)."""
    from my_ai_employee.db.transactions import Transaction

    base_date = date(2026, 5, 1)
    with session_factory() as session:
        # 35 笔 baseline
        for i in range(35):
            session.add(
                Transaction(
                    source="wechat",
                    external_transaction_id=f"baseline-{i:03d}",
                    transaction_date=base_date + timedelta(days=i % 28),
                    amount=Decimal("50.00"),
                    counterparty="星巴克",
                    category="dining",
                    normalized_fingerprint=_make_fp(f"baseline-{i:03d}"),
                    status="categorized",
                    imported_at_ms=1_700_000_000_000 + i * 1000,
                    raw_row_json="{}",
                )
            )
        # 异常笔 ¥888
        target = Transaction(
            source="wechat",
            external_transaction_id="anomaly-amount",
            transaction_date=date(2026, 6, 1),
            amount=Decimal("888.00"),
            counterparty="星巴克",
            category="dining",
            normalized_fingerprint=_make_fp("anomaly-amount"),
            status="categorized",
            imported_at_ms=1_700_000_000_000 + 35_000,
            raw_row_json="{}",
        )
        session.add(target)
        session.commit()

        target_row = (
            session.query(Transaction).filter_by(external_transaction_id="anomaly-amount").one()
        )

    # 跑异常检测(真链路)
    results = detector.detect_all(target_row)
    kinds = {r.kind for r in results}
    # amount_3sigma + new_merchant(< 5 笔独立商家,这里 36 笔同商家 → 不触发 new_merchant)
    # amount_drift(35 笔已有画像 + ¥888 偏离 avg + 3σ)
    assert "amount_3sigma" in kinds
    assert target_row.amount == Decimal("888.00")
    assert all(r.tx is target_row for r in results)


@pytest.mark.e2e
def test_s11_frequency_anomaly_end_to_end(detector: Any, session_factory: Any) -> None:
    """S11.2 — 1 小时 6 笔同 source → frequency_5tx_per_hour 触发(端到端真链路)."""
    from my_ai_employee.db.transactions import Transaction

    now_ms = 1_716_000_000_000
    with session_factory() as session:
        # 5 笔 1 小时内 + 1 笔待检测 = 共 6 笔(> 5 阈值)
        for i in range(5):
            session.add(
                Transaction(
                    source="alipay",
                    external_transaction_id=f"freq-{i}",
                    transaction_date=date(2024, 6, 1),
                    amount=Decimal("10.00"),
                    counterparty="测试商家",
                    category="dining",
                    normalized_fingerprint=_make_fp(f"freq-{i}"),
                    status="categorized",
                    imported_at_ms=now_ms - i * 60_000,
                    raw_row_json="{}",
                )
            )
        target = Transaction(
            source="alipay",
            external_transaction_id="freq-target",
            transaction_date=date(2024, 6, 1),
            amount=Decimal("10.00"),
            counterparty="测试商家",
            category="dining",
            normalized_fingerprint=_make_fp("freq-target"),
            status="categorized",
            imported_at_ms=now_ms,
            raw_row_json="{}",
        )
        session.add(target)
        session.commit()

        target_row = (
            session.query(Transaction).filter_by(external_transaction_id="freq-target").one()
        )

    # 跑异常检测
    results = detector.detect_all(target_row)
    kinds = {r.kind for r in results}
    # frequency_5tx_per_hour 必触发
    assert "frequency_5tx_per_hour" in kinds
    freq_result = next(r for r in results if r.kind == "frequency_5tx_per_hour")
    assert freq_result.context["count"] >= 5
    assert freq_result.context["window"] == "1h"


@pytest.mark.e2e
def test_s11_new_merchant_cold_start(detector: Any, session_factory: Any) -> None:
    """S11.3 — 全新商家(< 5 笔历史)→ new_merchant 标记(端到端真链路)."""
    from my_ai_employee.db.transactions import Transaction

    # 不插 baseline,直接跑 target(冷启动)
    with session_factory() as session:
        target = Transaction(
            source="wechat",
            external_transaction_id="cold-start",
            transaction_date=date(2026, 6, 1),
            amount=Decimal("30.00"),
            counterparty="全新商家",
            category="dining",
            normalized_fingerprint=_make_fp("cold-start"),
            status="categorized",
            imported_at_ms=1_700_000_000_000,
            raw_row_json="{}",
        )
        session.add(target)
        session.commit()

        target_row = (
            session.query(Transaction).filter_by(external_transaction_id="cold-start").one()
        )

    # 跑异常检测
    results = detector.detect_all(target_row)
    kinds = {r.kind for r in results}
    # 冷启动(< 5 笔)→ new_merchant 必触发
    assert "new_merchant" in kinds
    new_merchant = next(r for r in results if r.kind == "new_merchant")
    assert new_merchant.context["counterparty"] == "全新商家"
    assert new_merchant.context["tx_count"] == 0  # 冷启动无画像
