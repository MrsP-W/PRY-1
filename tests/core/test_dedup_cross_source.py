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

    assert fp_wechat == fp_alipay, (
        f"D7 跨源 fingerprint 应相同(无 source 维度),wechat={fp_wechat} != alipay={fp_alipay}"
    )
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
    v0.2.28 升级:fp 用 sign=+1(支出方向)与 transaction_adapter 行为对齐。
    """
    from my_ai_employee.core.dedup import find_l2_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)", sign=+1)

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
    v0.2.28 升级:fp 用 sign=+1(支出方向)与 transaction_adapter 行为对齐。
    """
    from my_ai_employee.core.dedup import find_l2_candidates
    from my_ai_employee.core.fingerprint import normalize_fingerprint
    from my_ai_employee.db.transactions import TransactionStore

    store = TransactionStore(session_factory)
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)", sign=+1)

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
    # v0.2.28 L2 sign-lock:fp 用 sign=+1(支出方向)与 transaction_adapter 行为对齐
    fp = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡(国贸店)", sign=+1)

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
    assert updated_wechat.candidate_match_id == alipay_tx.id, (
        f"D7 L3:candidate_match_id 应指向 alipay 老交易,实际 {updated_wechat.candidate_match_id}"
    )

    # alipay 老交易不应被改动(防"误合并")
    alipay_unchanged = store.get_by_id(alipay_tx.id)
    assert alipay_unchanged is not None
    assert alipay_unchanged.needs_confirm == 0, "D7 L3:alipay 老候选不应被改"


# ===== v0.2.28 L2 fingerprint sign-lock 专项测试(2026-06-23) =====
# 沿 v0.2.27 真实账单 spike 暴露的 267 对偶然跨源 L2 命中风险:
#   normalize_fingerprint(date, abs(amount), counterparty) 升级为
#   normalize_fingerprint(date, amount_with_sign, counterparty, *, sign=±1)
#   - sign=+1(支出):微信 `付` / 支付宝 `支` 共用
#   - sign=-1(收入):微信 `收` / 支付宝 `收` 共用
#   - sign=None(默认):向后兼容 abs(amount),D6.2/D7.2 已有测试零破坏


def test_fingerprint_sign_lock_same_sign_cross_source_match() -> None:
    """v0.2.28 Case 1 — 跨源 sign 一致 → 命中(构造跨源 100 对全部命中).

    场景:微信(支出 -38.50)↔ 支付宝(支出 +38.50) — 同一商家同日同金额,sign 一致 → fp 相同。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp_wechat = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=+1)
    fp_alipay = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=+1)

    assert fp_wechat == fp_alipay, (
        f"v0.2.28 sign-lock:跨源 sign 一致应同 fp,wechat={fp_wechat} != alipay={fp_alipay}"
    )
    assert len(fp_wechat) == 32


def test_fingerprint_sign_lock_different_sign_cross_source_no_match() -> None:
    """v0.2.28 Case 2 — 跨源 sign 不一致 → 不命中(消除 267 对偶然跨源).

    场景:微信(收入 -38.50)↔ 支付宝(支出 +38.50) — 同 (date, abs(amount), counterparty) 但 sign 不同。
    关键:消除 v0.2.27 spike 暴露的偶然跨源 L2 命中风险(267 对额外命中)。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp_income = normalize_fingerprint(date(2026, 6, 14), Decimal("-38.50"), "星巴克咖啡", sign=-1)
    fp_expense = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=+1)

    assert fp_income != fp_expense, (
        f"v0.2.28 sign-lock:跨源 sign 不一致应不同 fp(消除偶然跨源),"
        f"income={fp_income} == expense={fp_expense}"
    )


def test_fingerprint_sign_lock_none_backward_compat() -> None:
    """v0.2.28 Case 3 — sign=None(默认)向后兼容 abs(amount).

    关键:D6.2 + D7.2 已有测试用 sign=None 不传,D6.2 + D7.2 fingerprint 应保持不变。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    fp_none = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡")
    fp_none_neg = normalize_fingerprint(date(2026, 6, 14), Decimal("-38.50"), "星巴克咖啡")

    # sign=None 走 abs() 路径,正负 amount 都归一化为 |38.50| → fp 相同
    assert fp_none == fp_none_neg, "v0.2.28 sign=None 向后兼容 abs():正负 amount 应归一化为相同 fp"

    # sign=None 与 sign=+1 应不同(显式区分语义)
    fp_plus = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=+1)
    assert fp_none != fp_plus, (
        f"v0.2.28:sign=None (abs) 应与 sign=+1 (有符号) 派生不同 fp,"
        f"none={fp_none} == plus={fp_plus}"
    )


def test_fingerprint_sign_lock_invalid_sign_raises() -> None:
    """v0.2.28 Case 4 — sign 非法值抛 ValueError(沿工厂层 type() is int 严判范本).

    边界:
        - sign=0(非法)
        - sign=2(超出 +1/-1)
        - sign="+1"(类型错)
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    # sign=0 → ValueError
    with pytest.raises(ValueError, match="sign 必须是 None / \\+1 / -1"):
        normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=0)

    # sign=2 → ValueError
    with pytest.raises(ValueError, match="sign 必须是 None / \\+1 / -1"):
        normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=2)

    # sign=字符串 → TypeError(type 严判,mypy 兼容 cast)
    from typing import cast  # noqa: PLC0415

    with pytest.raises(TypeError, match="sign 必须是 int 或 None"):
        normalize_fingerprint(
            date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=cast("int", "+1")
        )


def test_fingerprint_sign_lock_amount_sign_independent() -> None:
    """v0.2.28 Case 5 — sign 与 amount 符号独立:sign 锁定符号,amount 正负不影响.

    设计:业务侧 RawTransaction.amount 来自 parser 可能有 ±,而 sign 由 transaction_adapter
    从 raw.type 派生,二者独立。sign=+1 + amount=-38.50 应返回 +38.00(不是错误)。
    防坑:不让 sign 显式控制 amount 符号导致 ±38.50 双重编码。
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    # sign=+1 + amount=-38.50 → 返回 +38.50(sign 锁定,amount 符号被忽略)
    fp_pos_neg = normalize_fingerprint(date(2026, 6, 14), Decimal("-38.50"), "星巴克咖啡", sign=+1)
    fp_pos_pos = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=+1)
    assert fp_pos_neg == fp_pos_pos, (
        f"v0.2.28 sign=+1 应独立于 amount 符号:"
        f"fp(-38.50, +1)={fp_pos_neg} vs fp(+38.50, +1)={fp_pos_pos}"
    )

    # sign=-1 + amount=+38.50 → 返回 -38.50
    fp_neg_pos = normalize_fingerprint(date(2026, 6, 14), Decimal("38.50"), "星巴克咖啡", sign=-1)
    fp_neg_neg = normalize_fingerprint(date(2026, 6, 14), Decimal("-38.50"), "星巴克咖啡", sign=-1)
    assert fp_neg_pos == fp_neg_neg, (
        f"v0.2.28 sign=-1 应独立于 amount 符号:"
        f"fp(+38.50, -1)={fp_neg_pos} vs fp(-38.50, -1)={fp_neg_neg}"
    )


def test_fingerprint_sign_lock_realistic_eliminates_coincidental_cross_source() -> None:
    """v0.2.28 Case 6 — 真实账单场景验证 sign-lock 消除偶然跨源 L2 命中.

    沿 v0.2.27 spike_w3_realistic_faker.py 的 100 对构造跨源 + 267 对偶然跨源:
    - 构造跨源(lock sign=±1):sign-lock 后仍命中 100 对
    - 偶然跨源(sign 不一致):sign-lock 后**不命中**(消除 267 对)
    """
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    # 构造跨源:微信 `付` ↔ 支付宝 `支`,sign=+1 一致
    fp_constructed_wechat = normalize_fingerprint(
        date(2025, 3, 15), Decimal("88.00"), "麦当劳餐厅", sign=+1
    )
    fp_constructed_alipay = normalize_fingerprint(
        date(2025, 3, 15), Decimal("88.00"), "麦当劳餐厅", sign=+1
    )
    assert fp_constructed_wechat == fp_constructed_alipay, "v0.2.28 构造跨源(lock sign=+1)应命中"

    # 偶然跨源:微信 `收`(+88) ↔ 支付宝 `支`(+88),sign 不一致
    fp_coincidental_wechat = normalize_fingerprint(
        date(2025, 3, 15),
        Decimal("88.00"),
        "麦当劳餐厅",
        sign=-1,  # 收入方向
    )
    fp_coincidental_alipay = normalize_fingerprint(
        date(2025, 3, 15),
        Decimal("88.00"),
        "麦当劳餐厅",
        sign=+1,  # 支出方向
    )
    assert fp_coincidental_wechat != fp_coincidental_alipay, (
        "v0.2.28 偶然跨源(sign 不一致)应不命中 — 消除 v0.2.27 暴露的 267 对风险"
    )
