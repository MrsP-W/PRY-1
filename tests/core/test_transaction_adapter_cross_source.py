"""D7.4 — TransactionAdapter 跨源集成测试(wechat + alipay).

承接 docs/v0.1-launch-plan.md §D7 5 扩展点 + D7.4 plan:

D7 验证:复用 D6.5 adapter,跨源不破契约:
    1. `import_alipay_csv(path)` 解析 + 分类 + 指纹 + 去重 + 入库
    2. 跨源同 fingerprint:wechat 已有,alipay 触发 L2 needs_confirm
    3. 跨源同 fingerprint:alipay 已有,wechat 触发 L2 needs_confirm
    4. 跨源 L1 UNIQUE 不误判(wechat 已有 ID 'wechat-001' 不阻塞 alipay 'alipay-001')

6 cases:
    1. test_import_alipay_csv_inserts_categorized — 支付宝 5 行首次导入
    2. test_import_alipay_csv_duplicate_second_run — 支付宝重复导入全 duplicate
    3. test_cross_source_alipay_triggers_wechat_candidate — alipay 触发 wechat 候选
    4. test_cross_source_wechat_triggers_alipay_candidate — wechat 触发 alipay 候选
    5. test_l1_unique_not_cross_source_confused — L1 跨源不误判
    6. test_unified_dispatcher_pattern — 演示 import_raw_transactions(source="alipay") 复用

跑法:
    pytest tests/core/test_transaction_adapter_cross_source.py -v
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    from collections.abc import Iterator

_ALIPAY_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "alipay_faker"


def _expected_alipay_rows(filename: str) -> int:
    from my_ai_employee.connectors.alipay_csv import AlipayCSVConnector

    return len(AlipayCSVConnector().safe_parse(_ALIPAY_FIXTURES / filename))


@pytest.fixture
def engine() -> Iterator:
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.transactions import Transaction  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    return sessionmaker(bind=engine)


@pytest.fixture
def adapter(session_factory: Any) -> Any:
    from my_ai_employee.core.transaction_adapter import TransactionAdapter

    return TransactionAdapter(session_factory)


def test_import_alipay_csv_inserts_categorized(adapter: Any, session_factory: Any) -> None:
    """Case 1 — 支付宝 2024 样本 5 行全部入库,分类 + 状态机推进到 categorized."""
    from my_ai_employee.db.transactions import TransactionStore

    result = adapter.import_alipay_csv(_ALIPAY_FIXTURES / "alipay_2024_sample.csv")

    assert result.source == "alipay"
    expected = _expected_alipay_rows("alipay_2024_sample.csv")
    assert result.parsed == expected
    assert result.inserted == expected
    assert result.categorized == expected
    assert result.duplicates == 0
    assert result.needs_confirm == 0
    assert result.failed == 0
    assert len(result.imported_ids) == expected

    store = TransactionStore(session_factory)
    rows = store.list_by_source("alipay", limit=expected + 1)
    assert len(rows) == expected
    assert {row.status for row in rows} == {"categorized"}
    assert {row.source for row in rows} == {"alipay"}
    assert all(len(row.normalized_fingerprint) == 32 for row in rows)


def test_import_alipay_csv_duplicate_second_run(adapter: Any, session_factory: Any) -> None:
    """Case 2 — 同一份支付宝 CSV 导两次:第二次 5 条全走 duplicate,表内仍 5 条."""
    from my_ai_employee.db.transactions import TransactionStore

    first = adapter.import_alipay_csv(_ALIPAY_FIXTURES / "alipay_2025_sample.csv")
    second = adapter.import_alipay_csv(_ALIPAY_FIXTURES / "alipay_2025_sample.csv")

    expected = _expected_alipay_rows("alipay_2025_sample.csv")
    assert first.inserted == expected
    assert second.parsed == expected
    assert second.inserted == 0
    assert second.duplicates == expected
    assert len(second.duplicate_external_ids) == expected

    store = TransactionStore(session_factory)
    assert len(store.list_by_source("alipay", limit=expected + 1)) == expected


def test_cross_source_alipay_triggers_wechat_candidate(adapter: Any, session_factory: Any) -> None:
    """Case 3 — alipay 导入触发 wechat 已有候选:L2 命中 + needs_confirm 标记.

    D7 关键验证:跨源去重链路贯通(alipay → wechat 候选)。
    v0.2.28 升级:fp_existing 用 sign=+1(支出方向),与 alipay 导入时 transaction_adapter 派生
    的 sign=+1 一致,确保 L2 fingerprint 命中。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    # v0.2.28 L2 sign-lock:支付宝 `支` 对应 type=支出 → sign=+1,fp_existing 必须用相同 sign
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)", sign=+1)
    existing = store.insert(
        source="wechat",
        external_transaction_id="wechat-cross-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡(国贸店)",
        category="dining",
        payment_method="微信支付",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "wechat"}',
    )

    # 支付宝导入(沿 D7.4 unified 入口)
    from my_ai_employee.connectors.alipay_csv import AlipayCSV2024Parser  # noqa: F401

    AlipayCSV2024Parser()
    # 构造一个临时 CSV(只有一行 + 跨源同 fingerprint)
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
    ) as f:
        f.write("付款时间,交易分类,收/支,金额,支付方式,交易对方,交易号\n")
        f.write("2026-06-14 12:00:00,购物,支,38.50,余额宝,星巴克咖啡(国贸店),alipay-cross-001\n")
        alipay_path = Path(f.name)

    try:
        result = adapter.import_alipay_csv(alipay_path)
    finally:
        alipay_path.unlink(missing_ok=True)

    assert result.parsed == 1
    assert result.inserted == 1
    assert result.needs_confirm == 1
    assert result.categorized == 0
    assert result.candidate_count >= 1

    new_tx = store.by_external_id("alipay", "alipay-cross-001")
    assert new_tx is not None
    assert new_tx.status == "needs_confirm"
    assert new_tx.needs_confirm == 1
    assert new_tx.candidate_match_id == existing.id


def test_cross_source_wechat_triggers_alipay_candidate(adapter: Any, session_factory: Any) -> None:
    """Case 4 — wechat 导入触发 alipay 已有候选:L2 命中 + needs_confirm 标记.

    D7 关键验证:跨源去重链路贯通(wechat → alipay 候选,反方向)。
    v0.2.28 升级:fp_existing 用 sign=+1(支出方向),与 wechat 导入时 transaction_adapter 派生
    的 sign=+1 一致,确保 L2 fingerprint 命中。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    # v0.2.28 L2 sign-lock:微信 `付` 对应 type=支出 → sign=+1,fp_existing 必须用相同 sign
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("42.00"), "麦当劳(朝阳店)", sign=+1)
    existing = store.insert(
        source="alipay",
        external_transaction_id="alipay-cross-002",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("42.00"),
        counterparty="麦当劳(朝阳店)",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    # 微信导入(用 D6.5 范本)
    from my_ai_employee.connectors.wechat_csv import WeChatCSV2024Parser  # noqa: F401

    WeChatCSV2024Parser()
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
    ) as f:
        f.write("交易时间,交易类型,收/付,金额,支付方式,交易对方,交易号\n")
        f.write("2026-06-14 12:00:00,支出,付,42.00,微信支付,麦当劳(朝阳店),wechat-cross-002\n")
        wechat_path = Path(f.name)

    try:
        result = adapter.import_wechat_csv(wechat_path)
    finally:
        wechat_path.unlink(missing_ok=True)

    assert result.parsed == 1
    assert result.needs_confirm == 1
    assert result.candidate_count >= 1

    new_tx = store.by_external_id("wechat", "wechat-cross-002")
    assert new_tx is not None
    assert new_tx.status == "needs_confirm"
    assert new_tx.candidate_match_id == existing.id


def test_l1_unique_not_cross_source_confused(adapter: Any, session_factory: Any) -> None:
    """Case 5 — L1 UNIQUE 不跨源误判(wechat 'tx-001' 不阻塞 alipay 'tx-001').

    D7 关键验证:UNIQUE(source, external_transaction_id) 是 source 维度的,
    不同 source 的同一 external_transaction_id 不应阻塞。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp_wechat = normalize_fingerprint(date(2026, 6, 14), Decimal("10.00"), "测试商家A")
    store.insert(
        source="wechat",
        external_transaction_id="tx-shared-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("10.00"),
        counterparty="测试商家A",
        category="dining",
        payment_method="微信支付",
        normalized_fingerprint=fp_wechat,
        raw_row_json='{"source": "wechat"}',
    )

    # 支付宝导入时用同一个 external_transaction_id 'tx-shared-001'
    # L1 应不命中(不同 source),L2 也不命中(不同 fingerprint)

    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
    ) as f:
        f.write("付款时间,交易分类,收/支,金额,支付方式,交易对方,交易号\n")
        f.write("2026-06-14 12:00:00,购物,支,20.00,余额宝,测试商家B,tx-shared-001\n")
        alipay_path = Path(f.name)

    try:
        result = adapter.import_alipay_csv(alipay_path)
    finally:
        alipay_path.unlink(missing_ok=True)

    # 应成功插入(不被 L1 阻塞)
    assert result.inserted == 1, (
        f"D7 L1 跨源不误判:alipay tx-shared-001 应被允许插入(不同 source),"
        f"实际 inserted={result.inserted}"
    )
    assert result.duplicates == 0
    alipay_tx = store.by_external_id("alipay", "tx-shared-001")
    assert alipay_tx is not None
    # 微信老交易不应被改
    wechat_tx = store.by_external_id("wechat", "tx-shared-001")
    assert wechat_tx is not None


def test_unified_dispatcher_pattern(adapter: Any, session_factory: Any) -> None:
    """Case 6 — 演示 D7 复用 import_raw_transactions(source="alipay") 单一入口.

    D7 关键验证:微信/支付宝共用同一编排层,仅 source 参数不同。
    """
    from my_ai_employee.connectors.alipay_csv import RawTransaction
    from my_ai_employee.db.transactions import TransactionStore

    raw = RawTransaction(
        date=date(2026, 6, 14),
        amount=Decimal("99.00"),
        counterparty="测试商家(支付宝)",
        type="支出",
        payment_method="余额宝",
        external_transaction_id="alipay-unified-001",
        raw_row_hash="z" * 32,
    )
    result = adapter.import_raw_transactions([raw], source="alipay")

    assert result.source == "alipay"
    assert result.parsed == 1
    assert result.inserted == 1

    store = TransactionStore(session_factory)
    alipay_tx = store.by_external_id("alipay", "alipay-unified-001")
    assert alipay_tx is not None
    assert alipay_tx.source == "alipay"
