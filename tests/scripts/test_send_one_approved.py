"""send_one_approved.py — SMTP 真发门控单元测试."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.send_one_approved import _CONFIRM_PHRASE, _validate_gate  # noqa: E402


def test_gate_rejects_without_smtp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMTP_REAL_NETWORK", raising=False)
    err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="a@b.com")
    assert err is not None
    assert "SMTP_REAL_NETWORK=1" in err


def test_gate_accepts_when_env_and_confirm_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="a@b.com")
    assert err is None
