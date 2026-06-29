"""v0.2.2 #3 — L3 模糊匹配 ±1 day 测试(find_l3_fuzzy_candidates + NoteStore L3 fallback).

承接 [[v0.2.1-candidates-2026-06-17]] §6 候选 #5 L3 模糊匹配(商家名 + 日期 ±1 天):

设计要点:
    1. 复用 _normalize_counterparty_value / _normalize_note_title_value 做归一化
    2. 日期窗口: 默认 ±1 day,允许 0-7 范围
    3. 严格归一化匹配(不做 fuzzy_equals,误匹配 > 漏匹配)
    4. 绝不 delete/update 候选(沿 D6.2 防误合并 5 重点)
    5. 候选集按 id ASC 排序(沿 L2 范本,选最早 id)

3 段测试覆盖(24 cases):
    1. find_l3_fuzzy_candidates 严判 + 归一化(8 tests)
    2. find_l3_fuzzy_candidates ±N day 边界 + 多候选(6 tests)
    3. NoteStore.insert L3 fallback(10 tests)

跑法:
    pytest tests/core/test_dedup_l3_fuzzy.py -v
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if True:
    from collections.abc import Iterator


# ===== Fixtures(沿 test_dedup_cross_source.py:41-55 范本)=====


@pytest.fixture
def engine() -> Iterator[Any]:
    """InMemory SQLite + Transaction ORM create_all."""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.transactions import Transaction  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    return sessionmaker[Any](bind=engine)


# ===== 1. find_l3_fuzzy_candidates 严判 + 归一化(8 tests)=====


def test_l3_fuzzy_basic_match_same_day(session_factory: Any) -> None:
    """L3 模糊匹配:同日期同商家名应命中候选."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)")
    existing = store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-basic-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡(国贸店)",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 14),
            counterparty="星巴克咖啡(国贸店)",
        )
        assert len(candidates) == 1, "L3:同日期同商家名应命中候选"
        assert candidates[0]["id"] == existing.id
        assert candidates[0]["source"] == "alipay"
        assert candidates[0]["counterparty"] == "星巴克咖啡(国贸店)"


def test_l3_fuzzy_match_with_whitespace_and_fuzzy_mark(session_factory: Any) -> None:
    """L3 模糊匹配:归一化应容忍空白 + 模糊符 *(沿 _normalize_counterparty_value)."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    # 已有交易:counterparty 包含模糊符和多余空白
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("13.14"), "星巴克  * ")
    existing = store.insert(
        source="wechat",
        external_transaction_id="wechat-l3-fuzzy-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("13.14"),
        counterparty="星巴克  * ",  # 多余空白 + 模糊符
        category="dining",
        payment_method="微信支付",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "wechat"}',
    )

    with session_factory() as session:
        # 查询:无模糊符无多余空白 → 归一化后相等
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 14),
            counterparty="星巴克",
        )
        assert len(candidates) == 1, "L3:归一化后应命中(去模糊符+去空白)"
        assert candidates[0]["id"] == existing.id


def test_l3_fuzzy_match_plus_minus_one_day(session_factory: Any) -> None:
    """L3 模糊匹配:日期 ±1 day 应命中(±1 day 默认窗口)."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    # 候选日期 6/14,查询日期 6/15(差 1 day)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("50.00"), "美团外卖")
    existing = store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-pm-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("50.00"),
        counterparty="美团外卖",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        # +1 day
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 15),
            counterparty="美团外卖",
        )
        assert len(candidates) == 1, "L3:+1 day 应命中"
        assert candidates[0]["id"] == existing.id

        # -1 day
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 13),
            counterparty="美团外卖",
        )
        assert len(candidates) == 1, "L3:-1 day 应命中"
        assert candidates[0]["id"] == existing.id


def test_l3_fuzzy_no_match_outside_window(session_factory: Any) -> None:
    """L3 模糊匹配:超出 ±1 day 窗口不应命中."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("100.00"), "京东商城")
    store.insert(
        source="wechat",
        external_transaction_id="wechat-l3-far-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("100.00"),
        counterparty="京东商城",
        category="shopping",
        payment_method="微信支付",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "wechat"}',
    )

    with session_factory() as session:
        # 差 2 day(超出默认 ±1 day 窗口)
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 16),
            counterparty="京东商城",
        )
        assert len(candidates) == 0, "L3:±2 day 超出窗口不应命中"


def test_l3_fuzzy_no_match_different_merchant(session_factory: Any) -> None:
    """L3 模糊匹配:不同商家名不应命中(严格归一化匹配)."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡")
    store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-different-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        # 查询:星巴克咖啡店(不同商家名,归一化后不同)
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 14),
            counterparty="星巴克咖啡店",
        )
        assert len(candidates) == 0, (
            "L3:不同商家名(归一化后不同)不应命中 — 宁可漏匹配,不要误匹配(1-click 信任基础)"
        )


def test_l3_fuzzy_returns_sorted_by_id(session_factory: Any) -> None:
    """L3 模糊匹配:多候选应按 id ASC 排序(沿 L2 范本)."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp1 = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克")
    fp2 = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克")
    fp3 = normalize_fingerprint(date(2026, 6, 15), Decimal("38.50"), "星巴克")

    tx1 = store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-multi-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp1,
        raw_row_json='{"source": "alipay"}',
    )
    tx2 = store.insert(
        source="wechat",
        external_transaction_id="wechat-l3-multi-002",
        transaction_date=date(2026, 6, 15),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        category="dining",
        payment_method="微信支付",
        normalized_fingerprint=fp2,
        raw_row_json='{"source": "wechat"}',
    )
    tx3 = store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-multi-003",
        transaction_date=date(2026, 6, 15),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp3,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        # 查询 6/15 ±1 day 窗口(覆盖 6/14, 6/15, 6/16)
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 15),
            counterparty="星巴克",
        )
        assert len(candidates) == 3, f"L3:±1 day 窗口应命中 3 条,实际 {len(candidates)}"
        assert candidates[0]["id"] == tx1.id, "L3:候选应按 id ASC 排序(最早)"
        assert candidates[1]["id"] == tx2.id
        assert candidates[2]["id"] == tx3.id


def test_l3_fuzzy_exclude_tx_id(session_factory: Any) -> None:
    """L3 模糊匹配:exclude_tx_id 应排除自身(防自命中)."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克")
    tx1 = store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-exclude-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        # 排除自身
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 14),
            counterparty="星巴克",
            exclude_tx_id=tx1.id,
        )
        assert len(candidates) == 0, "L3:exclude_tx_id 应排除自身"


def test_l3_fuzzy_source_filter(session_factory: Any) -> None:
    """L3 模糊匹配:source_filter 应限定 source(单源查询)."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp1 = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克")
    fp2 = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克")
    alipay_tx = store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-filter-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp1,
        raw_row_json='{"source": "alipay"}',
    )
    wechat_tx = store.insert(  # noqa: F841  # 用于制造 2 条候选的副作用
        source="wechat",
        external_transaction_id="wechat-l3-filter-002",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        category="dining",
        payment_method="微信支付",
        normalized_fingerprint=fp2,
        raw_row_json='{"source": "wechat"}',
    )

    with session_factory() as session:
        # source_filter='alipay' → 只命中 alipay_tx
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 14),
            counterparty="星巴克",
            source_filter="alipay",
        )
        assert len(candidates) == 1, f"L3:source_filter 应只命中 1 条,实际 {len(candidates)}"
        assert candidates[0]["id"] == alipay_tx.id
        assert candidates[0]["source"] == "alipay"


# ===== 2. find_l3_fuzzy_candidates ±N day 边界 + 严判(6 tests)=====


def test_l3_fuzzy_date_tolerance_zero_exact_only(session_factory: Any) -> None:
    """L3 模糊匹配:date_tolerance_days=0 时只命中同日期(等同 L2 容错为 0)."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克")
    store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-tol0-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        # 差 1 day + tolerance=0 → 不命中
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 15),
            counterparty="星巴克",
            date_tolerance_days=0,
        )
        assert len(candidates) == 0, "L3:tolerance=0 + 差 1 day 不应命中"


def test_l3_fuzzy_date_tolerance_seven_cross_weekend(session_factory: Any) -> None:
    """L3 模糊匹配:date_tolerance_days=7 支持跨周末(防周末消费周一录入误匹配)."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    # 候选日期周六 6/13,查询周六 6/20(差 7 day)
    fp = normalize_fingerprint(date(2026, 6, 13), Decimal("200.00"), "周末聚餐")
    existing = store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-weekend-001",
        transaction_date=date(2026, 6, 13),
        amount=Decimal("200.00"),
        counterparty="周末聚餐",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        candidates = find_l3_fuzzy_candidates(
            session,
            transaction_date=date(2026, 6, 20),
            counterparty="周末聚餐",
            date_tolerance_days=7,
        )
        assert len(candidates) == 1, "L3:tolerance=7 应支持跨周末"
        assert candidates[0]["id"] == existing.id


def test_l3_fuzzy_rejects_invalid_date_tolerance(session_factory: Any) -> None:
    """L3 模糊匹配:date_tolerance_days 超出 [0, 7] → ValueError."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates

    with session_factory() as session:
        # 负数
        with pytest.raises(ValueError, match="date_tolerance_days 必须在"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date=date(2026, 6, 14),
                counterparty="星巴克",
                date_tolerance_days=-1,
            )
        # 超过 7
        with pytest.raises(ValueError, match="date_tolerance_days 必须在"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date=date(2026, 6, 14),
                counterparty="星巴克",
                date_tolerance_days=8,
            )


def test_l3_fuzzy_rejects_invalid_transaction_date_type(session_factory: Any) -> None:
    """L3 模糊匹配:transaction_date 必须是 date(非 str/datetime)→ TypeError."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates

    with session_factory() as session:
        # str
        with pytest.raises(TypeError, match="transaction_date 必须是 date"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date="2026-06-14",
                counterparty="星巴克",
            )
        # datetime
        with pytest.raises(TypeError, match="transaction_date 必须是 date"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date=datetime(2026, 6, 14, 12, 30),
                counterparty="星巴克",
            )


def test_l3_fuzzy_rejects_empty_counterparty(session_factory: Any) -> None:
    """L3 模糊匹配:counterparty 必填非空 → ValueError."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates

    with session_factory() as session:
        with pytest.raises(ValueError, match="counterparty 必填"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date=date(2026, 6, 14),
                counterparty="",
            )
        with pytest.raises(ValueError, match="counterparty 必填"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date=date(2026, 6, 14),
                counterparty="   ",
            )


def test_l3_fuzzy_rejects_invalid_limit(session_factory: Any) -> None:
    """L3 模糊匹配:limit 必须是 [1, 100] 的 int(非 bool)→ ValueError."""
    from my_ai_employee.core.dedup import find_l3_fuzzy_candidates

    with session_factory() as session:
        # bool(isinstance(True, int)==True 陷阱)
        with pytest.raises(ValueError, match="limit 必须是"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date=date(2026, 6, 14),
                counterparty="星巴克",
                limit=True,
            )
        # 超出范围
        with pytest.raises(ValueError, match="limit 必须是"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date=date(2026, 6, 14),
                counterparty="星巴克",
                limit=0,
            )
        with pytest.raises(ValueError, match="limit 必须是"):
            find_l3_fuzzy_candidates(
                session,
                transaction_date=date(2026, 6, 14),
                counterparty="星巴克",
                limit=101,
            )


# ===== 3. NoteStore.insert L3 fallback(10 tests)=====


@pytest.fixture
def notes_engine() -> Iterator[Any]:
    """InMemory SQLite + Note ORM create_all."""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.notes import Note  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def notes_session_factory(notes_engine: Any) -> Any:
    return sessionmaker[Any](bind=notes_engine)


@pytest.fixture
def notes_store(notes_session_factory: Any) -> Any:
    from my_ai_employee.db.notes import NoteStore

    return NoteStore(notes_session_factory)


def test_notes_insert_l3_fallback_no_match(notes_store: Any) -> None:
    """NoteStore.insert:无 L2/L3 候选时,needs_confirm=0, candidate_match_id=None."""
    note = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-001",
        folder="Notes",
        title="星巴克",
        body="买了一杯咖啡",
        updated_at_ms=1700000000000,
    )
    assert note.needs_confirm == 0, "首次写入无候选 → needs_confirm=0"
    assert note.candidate_match_id is None


def test_notes_insert_l2_match_first_priority(notes_store: Any) -> None:
    """NoteStore.insert:L2 fingerprint 命中时优先 L2(不触发 L3 fallback)."""

    base_ms = 1700000000000
    # 第一次写入
    notes_store.insert(
        apple_note_id="x-coredata://test/note-l2-001",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=base_ms,
    )
    # 第二次写入:完全同 title/folder/date → L2 fingerprint 命中
    note2 = notes_store.insert(
        apple_note_id="x-coredata://test/note-l2-002",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=base_ms,  # 同一秒,L2 命中
    )
    assert note2.needs_confirm == 1, "L2 命中 → needs_confirm=1"
    assert note2.candidate_match_id is not None


def test_notes_insert_l3_fallback_match(notes_store: Any) -> None:
    """NoteStore.insert:L2 不命中但 L3 模糊匹配时 → needs_confirm=1."""
    from datetime import datetime as _dt

    # 第一次写入:6/14
    base_ms = int(_dt(2026, 6, 14, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-fb-001",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=base_ms,
    )
    # 第二次写入:6/15(差 1 day)+ 完全相同 title → L2 不命中,L3 命中
    next_day_ms = int(_dt(2026, 6, 15, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    note2 = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-fb-002",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=next_day_ms,
    )
    assert note2.needs_confirm == 1, "L2 不命中但 L3 命中 → needs_confirm=1"
    assert note2.candidate_match_id is not None, "L3 命中应设置 candidate_match_id"


def test_notes_insert_l3_fallback_outside_window(notes_store: Any) -> None:
    """NoteStore.insert:超出 ±1 day 窗口时 L3 不命中 → needs_confirm=0."""
    from datetime import datetime as _dt

    # 第一次写入:6/14
    base_ms = int(_dt(2026, 6, 14, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-out-001",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=base_ms,
    )
    # 第二次写入:6/17(差 3 day,超出 ±1 day 默认窗口)+ 同 title → L3 不命中
    far_ms = int(_dt(2026, 6, 17, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    note2 = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-out-002",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=far_ms,
    )
    assert note2.needs_confirm == 0, "L3 超出窗口不命中 → needs_confirm=0"
    assert note2.candidate_match_id is None


def test_notes_insert_l3_fallback_different_title(notes_store: Any) -> None:
    """NoteStore.insert:不同 title 归一化后不等 → L3 不命中(误匹配防护)."""
    from datetime import datetime as _dt

    base_ms = int(_dt(2026, 6, 14, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-diff-001",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=base_ms,
    )
    # 同日期(同一天) + 不同 title → L3 归一化后不等 → 不命中
    note2 = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-diff-002",
        folder="Notes",
        title="星巴克咖啡店",  # 归一化后与"星巴克"不同
        body="",
        updated_at_ms=base_ms,
    )
    # 同一天,fp 完全不同(title 不同)→ L2 不命中
    # L3 同一天但 title 归一化不等 → 不命中
    assert note2.needs_confirm == 0, "L3 归一化不等 → needs_confirm=0"


def test_notes_insert_l3_fallback_title_normalized_equal(notes_store: Any) -> None:
    """NoteStore.insert:title 归一化相等但 L2 fp 不等(同日期不同大小写)→ L3 命中.

    注意:实际场景中 size/case 不同的 title 会让 L2 fp 不同(L2 是 strip+lower 的),
    所以 L2 不命中。但 L3 复用 _normalize_note_title_value 也是 strip+lower,
    这时 L2 和 L3 的归一化结果会一样。

    实际 L3 真正发挥作用的场景是:同 title 但日期 ±1 day(归一化后 L2 fp 不同)。
    """
    from datetime import datetime as _dt

    base_ms = int(_dt(2026, 6, 14, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-norm-001",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=base_ms,
    )
    # +1 day + 同 title → L2 fp 不等(日期不同)→ L3 命中
    next_ms = int(_dt(2026, 6, 15, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    note2 = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-norm-002",
        folder="Notes",
        title="星巴克",  # 同 title, L3 归一化相等
        body="",
        updated_at_ms=next_ms,
    )
    assert note2.needs_confirm == 1
    assert note2.candidate_match_id is not None


def test_notes_insert_l3_fallback_picks_earliest_id(notes_store: Any) -> None:
    """NoteStore.insert:L3 多候选时,选最早 id(沿 L2 范本 ORDER BY id ASC)."""
    from datetime import datetime as _dt

    base_ms = int(_dt(2026, 6, 14, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    earliest = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-early-001",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=base_ms,
    )
    second = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-early-002",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=int(_dt(2026, 6, 14, 11, 0, 0, tzinfo=UTC).timestamp() * 1000),
    )
    # 第三次写入:6/15(差 1 day)→ L2 不命中,L3 应命中 2 条,选 earliest.id
    next_ms = int(_dt(2026, 6, 15, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    note3 = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-early-003",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=next_ms,
    )
    assert note3.needs_confirm == 1
    assert note3.candidate_match_id == earliest.id, (
        f"L3 多候选应选最早 id,实际 {note3.candidate_match_id} (earliest={earliest.id}, second={second.id})"
    )


def test_notes_insert_l3_fallback_with_fuzzy_mark(notes_store: Any) -> None:
    """NoteStore.insert:title 含模糊符 * → L3 归一化后命中.

    实际场景:用户笔记写"星巴克*"(脱敏),原始 CSV 写"星巴克"→ L2 fp 不同
    (L2 归一化已去模糊符,但日期可能不同)。
    验证 L3 的归一化(复用 _normalize_note_title_value)也能正确匹配。
    """
    from datetime import datetime as _dt

    base_ms = int(_dt(2026, 6, 14, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-fuzz-001",
        folder="Notes",
        title="星巴克*",  # 模糊符
        body="",
        updated_at_ms=base_ms,
    )
    # +1 day + title "星巴克" → L2 fp 不等(归一化后日期不同)→ L3 归一化后 title 相等 → 命中
    next_ms = int(_dt(2026, 6, 15, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    note2 = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-fuzz-002",
        folder="Notes",
        title="星巴克",  # 无模糊符
        body="",
        updated_at_ms=next_ms,
    )
    assert note2.needs_confirm == 1, "L3 应容忍模糊符"
    assert note2.candidate_match_id is not None


def test_notes_l3_helper_validates_inputs(notes_store: Any) -> None:
    """NoteStore._find_l3_fuzzy_in_session:严判入参(沿 D4.7.3 范本)."""
    from my_ai_employee.core.fingerprint import _normalize_note_title_value

    # 验证 _normalize_note_title_value 严判
    with pytest.raises(TypeError, match="title 必须是 str"):
        _normalize_note_title_value(123)
    with pytest.raises(TypeError, match="title 必须是 str"):
        _normalize_note_title_value(None)


def test_notes_l3_helper_basic_usage(notes_store: Any) -> None:
    """NoteStore._find_l3_fuzzy_in_session:基本用法(直接调 helper)."""
    from datetime import datetime as _dt

    base_ms = int(_dt(2026, 6, 14, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
    existing = notes_store.insert(
        apple_note_id="x-coredata://test/note-l3-helper-001",
        folder="Notes",
        title="星巴克",
        body="",
        updated_at_ms=base_ms,
    )
    # 直接调 helper 验证 ±1 day 窗口

    with notes_store._sf() as session:
        candidates = notes_store._find_l3_fuzzy_in_session(
            session,
            title="星巴克",
            updated_at_ms=int(_dt(2026, 6, 15, 10, 0, 0, tzinfo=UTC).timestamp() * 1000),
            date_tolerance_days=1,
        )
        assert len(candidates) == 1
        assert candidates[0] == existing.id
