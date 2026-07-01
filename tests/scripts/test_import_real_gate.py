"""import_real_gate — 4 重防误发门控单元测试."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_real_gate import REQUIRED_CONFIRM, validate_real_import_gate  # noqa: E402


def test_gate_rejects_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WECHAT_REAL_IMPORT", raising=False)
    err = validate_real_import_gate(
        env_name="WECHAT_REAL_IMPORT",
        confirm=REQUIRED_CONFIRM,
        count=1,
        max_rows=1,
    )
    assert err is not None
    assert "WECHAT_REAL_IMPORT=1" in err


def test_gate_rejects_missing_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WECHAT_REAL_IMPORT", "1")
    err = validate_real_import_gate(
        env_name="WECHAT_REAL_IMPORT",
        confirm="",
        count=1,
        max_rows=1,
    )
    assert err is not None
    assert "--confirm" in err


def test_gate_accepts_full_quad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALIPAY_REAL_IMPORT", "1")
    err = validate_real_import_gate(
        env_name="ALIPAY_REAL_IMPORT",
        confirm=REQUIRED_CONFIRM,
        count=1,
        max_rows=1,
    )
    assert err is None
