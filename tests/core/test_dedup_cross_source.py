"""D7.2 — fingerprint + 3 层去重模型跨源复用验证(wechat + alipay).

承接 docs/v0.1-launch-plan.md §D7 5 扩展点 + D7.2 plan:

D7 启动 0 schema 变更,验证 D6 的 fingerprint + dedup 跨源兼容:
    1. `normalize_fingerprint` 无 source 维度,跨源共用
    2. `check_l1_duplicate` 接 `source: str`,D6='wechat' / D7='alipay' 都 OK
    3. `find_l2_candidates` 默认跨源查询(不指定 source_filter 命中 wechat+alipay)
    4. `mark_l3_needs_confirm` 跨源标记 needs_confirm + candidate_match_id

6 cases:
    1. test_fingerprint_cross_source_same_signature — 微信+支付宝同日同金额同商家 → 同 fp
    2. test_fingerprint_cross_source_different_amount — 微信+支付宝同商家但金额差 0.01 → 不同 fp
    3. test_l1_duplicate_alipay_blocks_alipay — L1 同源 UNIQUE 命中(alipay 阻塞 alipay)
    4. test_l2_candidates_cross_source_default — L2 跨源候选(wechat 行 + alipay 行)
    5. test_l2_candidates_same_source_no_match — L2 同源查询不命中(防自命中)
    6. test_l3_mark_cross_source_candidate — L3 跨源标记 needs_confirm

跑法:
    pytest tests/core/test_dedup_cross_source.py -v
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if True:  # type: ignore[has-type]
    from collections.abc import Iterator


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


def test_fingerprint_cross_source_same_signature() -> None:
    """Case 1 — 微信+支付宝同日同金额同商家 → 同 fingerprint.

    D7 兼容验证:`normalize_fingerprint` 无 source 维度,跨源共用同一指纹算法。
    真实场景:同一天在微信和支付宝都用 38.50 买了星巴克 → 同一 fp,L2 命中。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp_wechat = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)")
    fp_alipay = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)")

    assert (
        fp_wechat == fp_alipay
    ), f"D7 跨源 fingerprint 应相同(无 source 维度),wechat={fp_wechat} != alipay={fp_alipay}"
    assert len(fp_wechat) == 32


def test_fingerprint_cross_source_different_amount() -> None:
    """Case 2 — 微信+支付宝同商家但金额差 0.01 → 不同 fp(严判金额精度)."""
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp1 = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡")
    fp2 = normalize_fingerprint(date(2026, 6, 14), Decimal("38.51"), "星巴克咖啡")

    assert fp1 != fp2, "D7 跨源 fingerprint:金额差 0.01 应不命中"


def test_l1_duplicate_alipay_blocks_alipay(session_factory) -> None:
    """Case 3 — L1 同源 UNIQUE 命中:alipay 重复 alipay 应被业务阻断.

    D7 兼容验证:`check_l1_duplicate(session, source='alipay', ...)` 工作正常。
    """
    from my_ai_employee.core.dedup import check_l1_duplicate
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("50.00"), "测试商家")
    store.insert(
        source="alipay",
        external_transaction_id="alipay-l1-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("50.00"),
        counterparty="测试商家",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        is_dup = check_l1_duplicate(session, "alipay", "alipay-l1-001")
        assert is_dup is True, "D7 L1:alipay 同源重复 ID 应被预检命中"

        # 跨源查询 wechat 同 ID 不命中(防误阻断)
        is_dup_wechat = check_l1_duplicate(session, "wechat", "alipay-l1-001")
        assert is_dup_wechat is False, "D7 L1:不同 source 同 ID 不应被预检命中"


def test_l2_candidates_cross_source_default(session_factory) -> None:
    """Case 4 — L2 跨源候选(默认不传 source_filter):wechat + alipay 同时命中.

    D7 兼容验证:`find_l2_candidates` 默认查所有 source 跨源候选。
    """
    from my_ai_employee.core.dedup import find_l2_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)")

    # 插入微信 1 条 + 支付宝 1 条(同 fingerprint 跨源)
    wechat_tx = store.insert(
        source="wechat",
        external_transaction_id="wechat-l2-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡(国贸店)",
        category="dining",
        payment_method="微信支付",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "wechat"}',
    )
    alipay_tx = store.insert(
        source="alipay",
        external_transaction_id="alipay-l2-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡(国贸店)",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        # 默认跨源查询(不传 source_filter)
        candidates = find_l2_candidates(session, fp, limit=10)
        assert len(candidates) == 2, f"D7 L2 跨源应命中 2 候选,实际 {len(candidates)}"
        sources = {c["source"] for c in candidates}
        assert sources == {"wechat", "alipay"}, f"D7 L2 跨源候选 source 集合错误: {sources}"
        ids = {c["id"] for c in candidates}
        assert ids == {wechat_tx.id, alipay_tx.id}, f"D7 L2 ID 集合错误: {ids}"


def test_l2_candidates_same_source_no_match(session_factory) -> None:
    """Case 5 — L2 同源查询(指定 source_filter='alipay'):只命中 alipay 不命中 wechat.

    D7 兼容验证:`source_filter` 参数工作正常(限制单源查询)。
    """
    from my_ai_employee.core.dedup import find_l2_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)")

    # 插入微信 1 条 + 支付宝 1 条
    store.insert(
        source="wechat",
        external_transaction_id="wechat-l2-002",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡(国贸店)",
        category="dining",
        payment_method="微信支付",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "wechat"}',
    )
    alipay_tx = store.insert(
        source="alipay",
        external_transaction_id="alipay-l2-002",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡(国贸店)",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    with session_factory() as session:
        # 限定 source_filter='alipay':只命中 alipay
        candidates = find_l2_candidates(session, fp, source_filter="alipay", limit=10)
        assert len(candidates) == 1
        assert candidates[0]["source"] == "alipay"
        assert candidates[0]["id"] == alipay_tx.id


def test_l3_mark_cross_source_candidate(session_factory) -> None:
    """Case 6 — L3 跨源标记 needs_confirm:wechat 新交易标记 alipay 老候选.

    D7 兼容验证:`mark_l3_needs_confirm` 跨源标记工作正常。
    """
    from my_ai_employee.core.dedup import mark_l3_needs_confirm
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)")

    # 已有 alipay 交易(老候选)
    alipay_tx = store.insert(
        source="alipay",
        external_transaction_id="alipay-l3-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡(国贸店)",
        category="dining",
        payment_method="余额宝",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "alipay"}',
    )

    # 微信新交易(同日同金额同商家)
    wechat_tx = store.insert(
        source="wechat",
        external_transaction_id="wechat-l3-001",
        transaction_date=date(2026, 6, 14),
        amount=Decimal("38.50"),
        counterparty="星巴克咖啡(国贸店)",
        category="dining",
        payment_method="微信支付",
        normalized_fingerprint=fp,
        raw_row_json='{"source": "wechat"}',
    )

    # 跨源标记:微信新交易 → 候选 alipay 老交易
    with session_factory() as session:
        mark_l3_needs_confirm(session, wechat_tx.id, alipay_tx.id)
        session.commit()

    # 验证标记
    updated_wechat = store.by_external_id("wechat", "wechat-l3-001")
    assert updated_wechat is not None
    assert updated_wechat.needs_confirm == 1, "D7 L3:跨源标记 wechat 应 needs_confirm=1"
    assert (
        updated_wechat.candidate_match_id == alipay_tx.id
    ), f"D7 L3:candidate_match_id 应指向 alipay 老交易,实际 {updated_wechat.candidate_match_id}"

    # alipay 老交易不应被改动(防"误合并")
    alipay_unchanged = store.get_by_id(alipay_tx.id)
    assert alipay_unchanged is not None
    assert alipay_unchanged.needs_confirm == 0, "D7 L3:alipay 老候选不应被改"
