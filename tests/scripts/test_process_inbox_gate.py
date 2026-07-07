"""process_inbox_gate — 4 重防误发门控单元测试."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.process_inbox_gate import (  # noqa: E402
    MAX_EXECUTE_LIMIT,
    REQUIRED_CONFIRM,
    validate_process_inbox_gate,
)


def test_gate_allows_dry_run_without_env() -> None:
    err = validate_process_inbox_gate(execute=False, confirm="", limit=5)
    assert err is None


def test_gate_rejects_execute_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROCESS_INBOX_EXECUTE", raising=False)
    err = validate_process_inbox_gate(
        execute=True,
        confirm=REQUIRED_CONFIRM,
        limit=1,
    )
    assert err is not None
    assert "PROCESS_INBOX_EXECUTE=1" in err


def test_gate_rejects_bad_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROCESS_INBOX_EXECUTE", "1")
    err = validate_process_inbox_gate(execute=True, confirm="nope", limit=1)
    assert err is not None
    assert "--confirm" in err


def test_gate_rejects_limit_over_max(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROCESS_INBOX_EXECUTE", "1")
    err = validate_process_inbox_gate(
        execute=True,
        confirm=REQUIRED_CONFIRM,
        limit=MAX_EXECUTE_LIMIT + 1,
    )
    assert err is not None
    assert str(MAX_EXECUTE_LIMIT) in err


def test_gate_accepts_full_quad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROCESS_INBOX_EXECUTE", "1")
    err = validate_process_inbox_gate(
        execute=True,
        confirm=REQUIRED_CONFIRM,
        limit=3,
    )
    assert err is None
