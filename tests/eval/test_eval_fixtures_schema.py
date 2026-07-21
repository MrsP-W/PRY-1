"""Contract checks for v1.1 offline eval fixtures (no production runner yet)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"
REQUIRED = {
    "id",
    "suite",
    "capability_id",
    "input",
    "expected",
    "feedback_label",
    "desensitized",
    "source",
}
ALLOWED_FEEDBACK = {"adopt", "modify", "reject", "unknown"}
ALLOWED_SOURCE = {"synthetic", "user_redacted"}


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURES_ROOT.rglob("*.json"))


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: str(p.relative_to(FIXTURES_ROOT)))
def test_eval_fixture_schema(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED - set(data)
    assert not missing, f"{path.name} missing fields: {sorted(missing)}"
    assert data["desensitized"] is True
    assert data["feedback_label"] in ALLOWED_FEEDBACK
    assert data["source"] in ALLOWED_SOURCE
    assert isinstance(data["input"], dict)
    assert isinstance(data["expected"], dict)


def test_eval_fixture_count_floor() -> None:
    """Keep at least a few synthetic fixtures while the 30+ corpus grows."""
    assert len(_fixture_paths()) >= 4
