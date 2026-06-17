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


def _expected_wechat_rows(filename: str) -> int:
    from my_ai_employee.connectors.wechat_csv import WeChatCSVConnector

    return len(WeChatCSVConnector().safe_parse(_WECHAT_FIXTURES / filename))


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
    expected = _expected_wechat_rows("wechat_2024_sample.csv")
    assert result.parsed == expected
    assert result.inserted == expected
    assert result.categorized == expected
    assert result.duplicates == 0
    assert result.needs_confirm == 0
    assert result.failed == 0
    assert len(result.imported_ids) == expected

    store = TransactionStore(session_factory)
    rows = store.list_by_source("wechat", limit=expected + 1)
    assert len(rows) == expected
    assert {row.status for row in rows} == {"categorized"}
    assert {row.category for row in rows} >= {"dining", "transport", "home", "other"}
    assert all(len(row.normalized_fingerprint) == 32 for row in rows)


def test_import_wechat_csv_duplicate_second_run_skips(adapter, session_factory) -> None:
    """Case 2 — 同一份微信 CSV 导两次:第二次 5 条全走 duplicate,表内仍 5 条."""
    from my_ai_employee.db.transactions import TransactionStore

    first = adapter.import_wechat_csv(_WECHAT_FIXTURES / "wechat_2025_sample.csv")
    second = adapter.import_wechat_csv(_WECHAT_FIXTURES / "wechat_2025_sample.csv")

    expected = _expected_wechat_rows("wechat_2025_sample.csv")
    assert first.inserted == expected
    assert second.parsed == expected
    assert second.inserted == 0
    assert second.duplicates == expected
    assert len(second.duplicate_external_ids) == expected

    store = TransactionStore(session_factory)
    assert len(store.list_by_source("wechat", limit=expected + 1)) == expected


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


# ===== D6.6 P2 修复 3 专项测试(Case 4-6)=====


def test_multi_candidate_selects_min_id_intentionally(adapter, session_factory) -> None:
    """Case 4 (D6.6 P2) — 多候选时选最小 id 是有意设计:测试锁定契约.

    验证:
        - candidate_count 累加正确
        - candidate_ids 列表含全部候选
        - 选定的 candidate_match_id == 最小 id(find_candidates_by_fingerprint 按 id ASC)
        - 多个候选时 logger.info(本测试不验日志内容,只验行为契约)
    """
    from my_ai_employee.connectors.wechat_csv import RawTransaction
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("50.00"), "测试商家")
    # 插入 3 条跨源同 fingerprint 候选
    alipay1 = store.insert(
        source="alipay",
        external_transaction_id="alipay-multi-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("50.00"),
        counterparty="测试商家",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay", "id": 1}',
    )
    alipay2 = store.insert(
        source="alipay",
        external_transaction_id="alipay-multi-002",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("50.00"),
        counterparty="测试商家",
        category="dining",
        payment_method="花呗",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay", "id": 2}',
    )
    alipay3 = store.insert(
        source="alipay",
        external_transaction_id="alipay-multi-003",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("50.00"),
        counterparty="测试商家",
        category="dining",
        payment_method="银行卡",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay", "id": 3}',
    )

    raw = RawTransaction(
        date=date(2026, 6, 14),
        amount=Decimal("50.00"),
        counterparty="测试商家",
        type="支出",
        payment_method="微信零钱",
        external_transaction_id="wechat-multi-001",
        raw_row_hash="b" * 32,
    )
    result = adapter.import_raw_transactions([raw], source="wechat")

    # 行为契约:3 候选 → candidate_count=3 + 选最小 id
    assert result.candidate_count == 3, (
        f"D6.6 P2:多候选 candidate_count 应=3,实际 {result.candidate_count}"
    )
    assert set(result.candidate_ids) == {alipay1.id, alipay2.id, alipay3.id}

    new_tx = store.by_external_id("wechat", "wechat-multi-001")
    assert new_tx is not None
    assert new_tx.needs_confirm == 1
    assert new_tx.candidate_match_id == alipay1.id, (
        f"D6.6 P2:多候选应选最小 id={alipay1.id} (有意设计:id ASC 排序),"
        f"实际 selected={new_tx.candidate_match_id}"
    )


def test_failed_items_tracks_value_error_per_row(adapter) -> None:
    """Case 5 (D6.6 P2) — 业务/严判失败时 failed_items 记录 ext_id + error_type,继续下一行.

    验证:
        - categorize 抛 ValueError(坏行)记入 failed_items
        - 后续正常行仍能 inserted(loop 继续)
        - failed > 0 但 loop 不中断
    """
    from my_ai_employee.connectors.wechat_csv import RawTransaction
    from my_ai_employee.core import transaction_adapter
    from my_ai_employee.core.transaction_category import TransactionCategory

    original_categorize = transaction_adapter.categorize

    def _selective_categorize(counterparty: str, amount):  # noqa: ARG001
        if counterparty == "坏数据行":
            raise ValueError("D6.6 测试故意失败")
        return TransactionCategory.OTHER  # 正常行返回有效分类

    # 1 行触发 ValueError + 1 行正常
    raws = [
        RawTransaction(
            date=date(2026, 6, 14),
            amount=Decimal("10.00"),
            counterparty="坏数据行",
            type="支出",
            payment_method="微信零钱",
            external_transaction_id="bad-001",
            raw_row_hash="c" * 32,
        ),
        RawTransaction(
            date=date(2026, 6, 14),
            amount=Decimal("20.00"),
            counterparty="正常行",
            type="支出",
            payment_method="微信零钱",
            external_transaction_id="ok-001",
            raw_row_hash="d" * 32,
        ),
    ]

    transaction_adapter.categorize = _selective_categorize  # type: ignore[assignment]
    try:
        result = adapter.import_raw_transactions(raws, source="wechat")
    finally:
        transaction_adapter.categorize = original_categorize  # type: ignore[assignment]

    # 行为契约:2 行 parsed + 1 行 failed + 1 行 inserted(loop 继续)
    assert result.parsed == 2
    assert result.failed == 1
    assert result.inserted == 1
    assert len(result.failed_items) == 1
    assert result.failed_items[0].external_transaction_id == "bad-001"
    assert result.failed_items[0].error_type == "ValueError"
    assert "D6.6 测试故意失败" in result.failed_items[0].error_message


def test_atomicity_insert_rollback_on_illegal_transition(
    adapter, session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Case 6 (D6.6 P2) — insert_and_advance_status 原子性:状态机非法转换 → insert 也回滚.

    验证:
        - 故意构造一个会让 update_status 抛 IllegalTransition 的场景
        - 整事务回滚,DB 不留半成品
    """
    from my_ai_employee.connectors.wechat_csv import RawTransaction
    from my_ai_employee.core.transactions import TransactionStatus
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)

    # Monkeypatch 必须在 class 层(否则 adapter._store 实例 bound method 不变)
    original_insert_and_advance = TransactionStore.insert_and_advance_status

    def _force_illegal_transition(self, **kwargs):  # noqa: ARG001
        # 强制传一个非法 from_status → assert_transition 抛 IllegalTransition
        return original_insert_and_advance(
            self,
            **{
                **kwargs,
                "from_status": TransactionStatus.ARCHIVED,  # 非法起点
                "new_status": TransactionStatus.CATEGORIZED,
            },
        )

    monkeypatch.setattr(TransactionStore, "insert_and_advance_status", _force_illegal_transition)

    raw = RawTransaction(
        date=date(2026, 6, 14),
        amount=Decimal("30.00"),
        counterparty="原子性测试",
        type="支出",
        payment_method="微信零钱",
        external_transaction_id="atomic-001",
        raw_row_hash="e" * 32,
    )
    result = adapter.import_raw_transactions([raw], source="wechat")

    # 行为契约:1 行 parsed + 1 行 failed(不 re-raise,记 failed_items)
    assert result.parsed == 1
    assert result.failed == 1
    assert result.inserted == 0
    assert len(result.failed_items) == 1
    assert result.failed_items[0].external_transaction_id == "atomic-001"
    assert result.failed_items[0].error_type == "TransactionIllegalTransitionError"

    # 关键:DB 不留半成品(整事务回滚)
    assert store.by_external_id("wechat", "atomic-001") is None, (
        "D6.6 P2 原子性:状态机非法转换 → insert 必须回滚,DB 不留半成品"
    )
