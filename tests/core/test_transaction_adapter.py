"""D6.5 TransactionAdapter 导入管线测试.

覆盖:
    1. 微信 CSV 首次导入:解析 → 分类 → 指纹 → 入库 → categorized
    2. 同源重复导入:L1 预检跳过,不新增行
    3. 跨源同 fingerprint:L2 命中后只标记 needs_confirm + candidate_match_id
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    from collections.abc import Iterator


_WECHAT_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "wechat_faker"


@pytest.fixture
def engine() -> Iterator:
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.transactions import Transaction  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def adapter(session_factory):
    from my_ai_employee.core.transaction_adapter import TransactionAdapter

    return TransactionAdapter(session_factory)


def test_import_wechat_csv_inserts_categorized_transactions(adapter, session_factory) -> None:
    """Case 1 — 2024 微信样本 5 行全部入库,分类 + 状态机推进到 categorized."""
    from my_ai_employee.db.transactions import TransactionStore

    result = adapter.import_wechat_csv(_WECHAT_FIXTURES / "wechat_2024_sample.csv")

    assert result.source == "wechat"
    assert result.parsed == 5
    assert result.inserted == 5
    assert result.categorized == 5
    assert result.duplicates == 0
    assert result.needs_confirm == 0
    assert result.failed == 0
    assert len(result.imported_ids) == 5

    store = TransactionStore(session_factory)
    rows = store.list_by_source("wechat", limit=10)
    assert len(rows) == 5
    assert {row.status for row in rows} == {"categorized"}
    assert {row.category for row in rows} >= {"dining", "transport", "home", "other"}
    assert all(len(row.normalized_fingerprint) == 32 for row in rows)


def test_import_wechat_csv_duplicate_second_run_skips(adapter, session_factory) -> None:
    """Case 2 — 同一份微信 CSV 导两次:第二次 5 条全走 duplicate,表内仍 5 条."""
    from my_ai_employee.db.transactions import TransactionStore

    first = adapter.import_wechat_csv(_WECHAT_FIXTURES / "wechat_2025_sample.csv")
    second = adapter.import_wechat_csv(_WECHAT_FIXTURES / "wechat_2025_sample.csv")

    assert first.inserted == 5
    assert second.parsed == 5
    assert second.inserted == 0
    assert second.duplicates == 5
    assert len(second.duplicate_external_ids) == 5

    store = TransactionStore(session_factory)
    assert len(store.list_by_source("wechat", limit=10)) == 5


def test_cross_source_candidate_marks_needs_confirm(adapter, session_factory) -> None:
    """Case 3 — 跨源同日同金额同商家:新交易只标记 needs_confirm,不自动合并."""
    from my_ai_employee.connectors.wechat_csv import RawTransaction
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克")
    existing = store.insert(
        source="alipay",
        external_transaction_id="alipay-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    raw = RawTransaction(
        date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        type="支出",
        payment_method="微信零钱",
        external_transaction_id="wechat-001",
        raw_row_hash="a" * 32,
    )
    result = adapter.import_raw_transactions([raw], source="wechat")

    assert result.parsed == 1
    assert result.inserted == 1
    assert result.needs_confirm == 1
    assert result.categorized == 0

    new_tx = store.by_external_id("wechat", "wechat-001")
    assert new_tx is not None
    assert new_tx.status == "needs_confirm"
    assert new_tx.needs_confirm == 1
    assert new_tx.candidate_match_id == existing.id
    assert store.get_by_id(existing.id) is not None
