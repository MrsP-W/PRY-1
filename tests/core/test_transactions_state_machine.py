"""D6.3 transactions.py 状态机白名单测试(12 cases).

承接 docs/v0.1-launch-plan.md §D6.3 categorizer + merchants 500 + 状态机:

    5 状态 × 各 2 双向(合法转换 + 非法转换)= 10 cases
    + 终态 ARCHIVED 严判 1 case
    + assert_transition 入参严判 1 case
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== 合法转换(正向 6 cases)=====


def test_state_machine_imported_to_categorized() -> None:
    """Case 1 — IMPORTED → CATEGORIZED 合法(D6.5 categorizer 完成后推)."""
    from my_ai_employee.core.transactions import (
        ALLOWED_TRANSITIONS,
        TransactionStatus,
        assert_transition,
    )

    assert TransactionStatus.CATEGORIZED in ALLOWED_TRANSITIONS[TransactionStatus.IMPORTED]
    # 不抛错
    assert_transition("imported", "categorized")


def test_state_machine_categorized_to_needs_confirm() -> None:
    """Case 2 — CATEGORIZED → NEEDS_CONFIRM 合法(L2 命中后推)."""
    from my_ai_employee.core.transactions import (
        ALLOWED_TRANSITIONS,
        TransactionStatus,
        assert_transition,
    )

    assert TransactionStatus.NEEDS_CONFIRM in ALLOWED_TRANSITIONS[TransactionStatus.CATEGORIZED]
    assert_transition("categorized", "needs_confirm")


def test_state_machine_categorized_to_confirmed() -> None:
    """Case 3 — CATEGORIZED → CONFIRMED 合法(用户主动确认,跳过 NEEDS_CONFIRM 直通)."""
    from my_ai_employee.core.transactions import (
        ALLOWED_TRANSITIONS,
        TransactionStatus,
        assert_transition,
    )

    assert TransactionStatus.CONFIRMED in ALLOWED_TRANSITIONS[TransactionStatus.CATEGORIZED]
    assert_transition("categorized", "confirmed")


def test_state_machine_needs_confirm_to_confirmed() -> None:
    """Case 4 — NEEDS_CONFIRM → CONFIRMED 合法(用户 1-click 确认 L3 命中)."""
    from my_ai_employee.core.transactions import (
        ALLOWED_TRANSITIONS,
        TransactionStatus,
        assert_transition,
    )

    assert TransactionStatus.CONFIRMED in ALLOWED_TRANSITIONS[TransactionStatus.NEEDS_CONFIRM]
    assert_transition("needs_confirm", "confirmed")


def test_state_machine_confirmed_to_archived() -> None:
    """Case 5 — CONFIRMED → ARCHIVED 合法(对账完成 / 月报核销)."""
    from my_ai_employee.core.transactions import (
        ALLOWED_TRANSITIONS,
        TransactionStatus,
        assert_transition,
    )

    assert TransactionStatus.ARCHIVED in ALLOWED_TRANSITIONS[TransactionStatus.CONFIRMED]
    assert_transition("confirmed", "archived")


def test_state_machine_archived_is_terminal() -> None:
    """Case 6 — ARCHIVED 终态: 不可转出,ALLOWED_TRANSITIONS[ARCHIVED] == frozenset()."""
    from my_ai_employee.core.transactions import ALLOWED_TRANSITIONS, TransactionStatus

    assert ALLOWED_TRANSITIONS[TransactionStatus.ARCHIVED] == frozenset()


# ===== 非法转换(反向 6 cases)=====


def test_state_machine_archived_to_anything_raises() -> None:
    """Case 7 — ARCHIVED → CONFIRMED 非法(终态不可转出)."""
    from my_ai_employee.core.transactions import (
        TransactionIllegalTransitionError,
        assert_transition,
    )

    with pytest.raises(TransactionIllegalTransitionError, match="状态机非法转换"):
        assert_transition("archived", "confirmed")


def test_state_machine_imported_to_confirmed_skip_needs_confirm() -> None:
    """Case 8 — IMPORTED → CONFIRMED 非法(必须先 → CATEGORIZED)."""
    from my_ai_employee.core.transactions import (
        TransactionIllegalTransitionError,
        assert_transition,
    )

    with pytest.raises(TransactionIllegalTransitionError, match="状态机非法转换"):
        assert_transition("imported", "confirmed")


def test_state_machine_imported_to_imported_self_loop_raises() -> None:
    """Case 9 — IMPORTED → IMPORTED 自循环非法(状态机不容纳自循环)."""
    from my_ai_employee.core.transactions import (
        TransactionIllegalTransitionError,
        assert_transition,
    )

    with pytest.raises(TransactionIllegalTransitionError, match="状态机非法转换"):
        assert_transition("imported", "imported")


def test_state_machine_categorized_to_imported_rollback_raises() -> None:
    """Case 10 — CATEGORIZED → IMPORTED 回滚非法(状态机单向不可逆)."""
    from my_ai_employee.core.transactions import (
        TransactionIllegalTransitionError,
        assert_transition,
    )

    with pytest.raises(TransactionIllegalTransitionError, match="状态机非法转换"):
        assert_transition("categorized", "imported")


def test_state_machine_confirmed_to_categorized_rollback_raises() -> None:
    """Case 11 — CONFIRMED → CATEGORIZED 回滚非法(状态机单向不可逆)."""
    from my_ai_employee.core.transactions import (
        TransactionIllegalTransitionError,
        assert_transition,
    )

    with pytest.raises(TransactionIllegalTransitionError, match="状态机非法转换"):
        assert_transition("confirmed", "categorized")


def test_state_machine_needs_confirm_to_imported_rollback_raises() -> None:
    """Case 12 — NEEDS_CONFIRM → IMPORTED 回滚非法(状态机单向不可逆)."""
    from my_ai_employee.core.transactions import (
        TransactionIllegalTransitionError,
        assert_transition,
    )

    with pytest.raises(TransactionIllegalTransitionError, match="状态机非法转换"):
        assert_transition("needs_confirm", "imported")


# ===== 异常构造(沿 outbox IllegalTransitionError 范本)+ 异常属性 =====


def test_illegal_transition_error_attributes() -> None:
    """Case 13 — TransactionIllegalTransitionError 异常属性完整."""
    from my_ai_employee.core.transactions import (
        TransactionIllegalTransitionError,
        TransactionStatus,
    )

    exc = TransactionIllegalTransitionError(
        tx_id=42,
        from_status="imported",
        to_status="confirmed",
        allowed=frozenset({TransactionStatus.CATEGORIZED, TransactionStatus.ARCHIVED}),
    )
    assert exc.tx_id == 42
    assert exc.from_status == "imported"
    assert exc.to_status == "confirmed"
    assert exc.actual_status is None
    assert exc.allowed is not None
    assert TransactionStatus.CATEGORIZED in exc.allowed
    assert "状态机非法转换" in str(exc)
    assert "imported" in str(exc)
    assert "confirmed" in str(exc)


def test_illegal_transition_error_actual_status_drift_message() -> None:
    """Case 14 — 状态漂移检测(场景 1)message 区别."""
    from my_ai_employee.core.transactions import TransactionIllegalTransitionError

    exc = TransactionIllegalTransitionError(
        tx_id=42,
        from_status="imported",
        to_status="confirmed",
        actual_status="categorized",  # 与 from_status 不一致 → 漂移
    )
    assert "状态机漂移" in str(exc)
    assert "imported" in str(exc)
    assert "categorized" in str(exc)


# ===== assert_transition 入参严判 =====


def test_assert_transition_invalid_status_raises_value_error() -> None:
    """Case 15 — assert_transition 非法 from_status / to_status 抛 ValueError."""
    from my_ai_employee.core.transactions import assert_transition

    with pytest.raises(ValueError, match="from_status 必为 TransactionStatus"):
        assert_transition("invalid_status", "imported")

    with pytest.raises(ValueError, match="to_status 必为 TransactionStatus"):
        assert_transition("imported", "invalid_status")
