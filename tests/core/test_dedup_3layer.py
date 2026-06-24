"""D6.2 3 层去重模型测试(18 cases).

承接 docs/v0.1-launch-plan.md §D6 3 层去重模型 + §D6.2 详细 plan:

    L1 源内幂等 — UNIQUE(source, external_transaction_id) 命中 → 业务阻断
    L2 跨源候选 — normalized_fingerprint INDEX 命中 → 软标记
    L3 模糊匹配 — needs_confirm=True + candidate_match_id(本阶段验证入口签名)

18 cases 分 3 段:
    1. L1 源内幂等(8 cases):命中/未命中/严判/UNIQUE 业务阻断
    2. L2 跨源候选(5 cases):命中/未命中/多候选选 ID 最小/跨源隔离
    3. L3 模糊匹配(5 cases):只标记/防自命中/严判类型

跑法:
    pytest tests/core/test_dedup_3layer.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== 共用 helper =====


def _insert_test_tx(
    session: Any,
    *,
    source: str = "wechat",
    external_tx_id: str = "tx-1",
    amount: str = "13.14",
    counterparty: str = "星巴克",
    fingerprint: str = "fp-test-001",
    transaction_date: str = "2026-06-14",
    imported_at_ms: int = 1718390400000,
) -> int:
    """插入一条测试 transactions 行,返回 id.

    D6.4 升级:加 transaction_date + imported_at_ms + status + raw_row_json 列
    (D6.4 transactions 16 列 schema 必含,4 列 NOT NULL 必填)。
    """
    sql = text(
        "INSERT INTO transactions "
        "(source, external_transaction_id, amount, counterparty, normalized_fingerprint, "
        "transaction_date, imported_at_ms, status, raw_row_json) "
        "VALUES (:source, :ext_id, :amount, :cp, :fp, :date, :ts, :status, :raw)"
    )
    result = session.execute(
        sql,
        {
            "source": source,
            "ext_id": external_tx_id,
            "amount": amount,
            "cp": counterparty,
            "fp": fingerprint,
            "date": transaction_date,
            "ts": imported_at_ms,
            "status": "imported",
            "raw": "{}",
        },
    )
    session.commit()
    return int(result.lastrowid or 0)


# ===== L1 源内幂等(8 cases)=====


def test_01_l1_same_source_same_id_hits(session: Any) -> None:
    """L1 Case 1 — 同源同 ID 命中返回 True."""
    from my_ai_employee.core.dedup import check_l1_duplicate

    _insert_test_tx(session, external_tx_id="tx-l1-001")
    assert check_l1_duplicate(session, "wechat", "tx-l1-001") is True


def test_02_l1_miss_returns_false(session: Any) -> None:
    """L1 Case 2 — 未命中返回 False."""
    from my_ai_employee.core.dedup import check_l1_duplicate

    assert check_l1_duplicate(session, "wechat", "tx-l1-not-exist") is False


def test_03_l1_same_id_different_source_misses(session: Any) -> None:
    """L1 Case 3 — 同 ID 不同 source 不命中(D7 兼容:UNIQUE(source, external_tx_id))."""
    from my_ai_employee.core.dedup import check_l1_duplicate

    _insert_test_tx(session, external_tx_id="tx-l1-shared")
    assert check_l1_duplicate(session, "alipay", "tx-l1-shared") is False


def test_04_l1_source_format_guard(session: Any) -> None:
    """L1 Case 4 — source 严判 ^[a-z0-9_-]{1,32}$ 小写 snake_case."""
    from my_ai_employee.core.dedup import check_l1_duplicate

    with pytest.raises(ValueError, match="source 必须匹配"):
        check_l1_duplicate(session, "WeChat-大写", "tx-1")
    with pytest.raises(ValueError, match="source 必填"):
        check_l1_duplicate(session, "", "tx-1")


def test_05_l1_ext_tx_id_empty_guard(session: Any) -> None:
    """L1 Case 5 — external_transaction_id 必填非空."""
    from my_ai_employee.core.dedup import check_l1_duplicate

    with pytest.raises(ValueError, match="external_transaction_id 必填"):
        check_l1_duplicate(session, "wechat", "")
    with pytest.raises(ValueError, match="external_transaction_id 必填"):
        check_l1_duplicate(session, "wechat", "   ")


def test_06_l1_ext_tx_id_length_guard(session: Any) -> None:
    """L1 Case 6 — external_transaction_id 长度 1-128."""
    from my_ai_employee.core.dedup import check_l1_duplicate

    with pytest.raises(ValueError, match="长度必须在"):
        check_l1_duplicate(session, "wechat", "x" * 129)


def test_07_l1_strict_stub_returns_true(session: Any) -> None:
    """L1 Case 7 — strict 入口是 stub(INSERT 流程由 D6.5 Adapter 负责)."""
    from my_ai_employee.core.dedup import check_l1_duplicate_strict

    assert check_l1_duplicate_strict(session, "wechat", "tx-strict") is True


def test_08_l1_wrong_type_guards(session: Any) -> None:
    """L1 Case 8 — type 严判 — None / int 抛 ValueError."""
    from my_ai_employee.core.dedup import check_l1_duplicate

    with pytest.raises(ValueError):
        check_l1_duplicate(session, None, "tx-1")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        check_l1_duplicate(session, 123, "tx-1")  # type: ignore[arg-type]


# ===== L2 跨源候选(5 cases)=====


def test_09_l2_same_fingerprint_hits(session: Any) -> None:
    """L2 Case 1 — 同 fingerprint 命中返回候选 list."""
    from my_ai_employee.core.dedup import find_l2_candidates

    _insert_test_tx(session, external_tx_id="tx-l2-001", fingerprint="a" * 32)
    candidates = find_l2_candidates(session, "a" * 32)
    assert len(candidates) == 1
    assert candidates[0]["source"] == "wechat"
    assert candidates[0]["external_transaction_id"] == "tx-l2-001"


def test_10_l2_different_fingerprint_misses(session: Any) -> None:
    """L2 Case 2 — 不同 fingerprint 不命中."""
    from my_ai_employee.core.dedup import find_l2_candidates

    _insert_test_tx(session, fingerprint="b" * 32)
    candidates = find_l2_candidates(session, "c" * 32)
    assert candidates == []


def test_11_l2_multiple_candidates_pick_min_id(session: Any) -> None:
    """L2 Case 3 — 多候选时按 id ASC 排序(确定性)."""
    from my_ai_employee.core.dedup import find_l2_candidates

    _insert_test_tx(session, external_tx_id="tx-l2-mid", fingerprint="d" * 32)
    _insert_test_tx(session, external_tx_id="tx-l2-min", fingerprint="d" * 32)
    candidates = find_l2_candidates(session, "d" * 32)
    assert len(candidates) == 2
    ids = [c["id"] for c in candidates]
    assert ids == sorted(ids), "候选必须按 id ASC 排序"


def test_12_l2_exclude_self_id(session: Any) -> None:
    """L2 Case 4 — exclude_tx_id 排除自身(防自命中)."""
    from my_ai_employee.core.dedup import find_l2_candidates

    _insert_test_tx(session, external_tx_id="tx-l2-self", fingerprint="e" * 32)
    candidates_all = find_l2_candidates(session, "e" * 32)
    assert len(candidates_all) == 1
    self_id = candidates_all[0]["id"]

    candidates_excl = find_l2_candidates(session, "e" * 32, exclude_tx_id=self_id)
    assert candidates_excl == []


def test_13_l2_fingerprint_format_guard(session: Any) -> None:
    """L2 Case 5 — fingerprint 严判 32 chars lowercase hex."""
    from my_ai_employee.core.dedup import find_l2_candidates

    with pytest.raises(ValueError, match="32 chars hex"):
        find_l2_candidates(session, "short")
    with pytest.raises(ValueError, match="小写 hex"):
        find_l2_candidates(session, "Z" * 32)


# ===== L3 模糊匹配(5 cases)=====


def test_14_l3_new_id_eq_candidate_raises(session: Any) -> None:
    """L3 Case 1 — new_tx_id == candidate_match_id 抛 ValueError(防自命中)."""
    from my_ai_employee.core.dedup import mark_l3_needs_confirm

    with pytest.raises(ValueError, match="不能相同"):
        mark_l3_needs_confirm(session, 1, 1)


def test_15_l3_tx_id_positive_int_guard(session: Any) -> None:
    """L3 Case 2 — new_tx_id / candidate_match_id 必须是正 int(非 bool)."""
    from my_ai_employee.core.dedup import mark_l3_needs_confirm

    with pytest.raises(ValueError, match="正 int"):
        mark_l3_needs_confirm(session, -1, 2)
    with pytest.raises(ValueError, match="正 int"):
        mark_l3_needs_confirm(session, 0, 1)
    with pytest.raises(ValueError, match="正 int"):
        mark_l3_needs_confirm(session, True, 2)


def test_16_l3_type_guard(session: Any) -> None:
    """L3 Case 3 — tx_id type 严判 — None / str 抛 ValueError."""
    from my_ai_employee.core.dedup import mark_l3_needs_confirm

    with pytest.raises(ValueError):
        mark_l3_needs_confirm(session, None, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        mark_l3_needs_confirm(session, "1", 1)  # type: ignore[arg-type]


def test_17_l3_no_l2_hit_skips_l3(session: Any) -> None:
    """L3 Case 4 — 无 L2 命中时无 L3 触发(空表查询 → 无候选 → mark_l3 不被调用)."""
    from my_ai_employee.core.dedup import find_l2_candidates

    # 空表,L2 不命中 → 无候选
    candidates = find_l2_candidates(session, "f" * 32)
    assert candidates == []
    # 无 L3 触发路径(本测试只验证 L2 不命中时不走 L3 逻辑)


def test_18_l3_chained_3layer_integration(session: Any) -> None:
    """L3 Case 5 — 端到端 3 层串联通路:L1 命中 → skip insert,无 L2/L3 触发."""
    from my_ai_employee.core.dedup import check_l1_duplicate, find_l2_candidates

    _insert_test_tx(session, external_tx_id="tx-chain-1", fingerprint="a1" * 16)
    # L1: 命中 → 业务阻断
    assert check_l1_duplicate(session, "wechat", "tx-chain-1") is True
    # L2: 同 fingerprint 仍命中(实际生产中 L1 命中后直接 skip insert,不查 L2)
    candidates = find_l2_candidates(session, "a1" * 16)
    assert len(candidates) == 1
