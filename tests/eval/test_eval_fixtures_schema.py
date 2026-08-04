"""Contract checks for v1.1 offline eval fixtures (no production runner yet)."""

from __future__ import annotations

import json
import re
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
RESERVED_EMAIL_DOMAINS = {
    "example.com",
    "example.invalid",
    "example.net",
    "example.org",
    "example.test",
}
EMAIL_PATTERN = re.compile(
    r"(?i)(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@"
    r"(?P<domain>[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+)(?![\w.-])"
)
LONG_DIGIT_SEQUENCE = re.compile(r"(?<!\d)\d{11,}(?!\d)")


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURES_ROOT.rglob("*.json"))


def _string_values(value: object) -> list[str]:
    """Flatten JSON values so privacy guards cover nested inputs and outputs."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _string_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _string_values(nested)]
    return []


def _is_reserved_email_domain(domain: str) -> bool:
    normalized = domain.lower()
    return any(
        normalized == reserved or normalized.endswith(f".{reserved}")
        for reserved in RESERVED_EMAIL_DOMAINS
    )


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


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: str(p.relative_to(FIXTURES_ROOT)))
def test_eval_fixture_id_matches_suite(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    expected_prefix = f"{data['suite']}_"
    assert data["id"].startswith(expected_prefix), (
        f"{path.name} id must start with its suite prefix: {expected_prefix}"
    )


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: str(p.relative_to(FIXTURES_ROOT)))
def test_eval_fixture_emails_use_reserved_domains(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for value in _string_values(data):
        for match in EMAIL_PATTERN.finditer(value):
            domain = match.group("domain")
            assert _is_reserved_email_domain(domain), (
                f"{path.name} contains a non-reserved email domain: {domain}"
            )


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: str(p.relative_to(FIXTURES_ROOT)))
def test_eval_fixture_strings_have_no_long_digit_sequences(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for value in _string_values(data):
        assert LONG_DIGIT_SEQUENCE.search(value) is None, (
            f"{path.name} contains a possible phone/card number: {value!r}"
        )


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("example.com", True),
        ("mail.example.org", True),
        ("partner.example.net", True),
        ("company.example.com.attacker.test", False),
        ("company.com", False),
    ],
)
def test_reserved_email_domain_guard(domain: str, expected: bool) -> None:
    assert _is_reserved_email_domain(domain) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("SAP document 19000000001", True),
        ("invoice INV-2026-07-1234", False),
        ("split number 12345-678901", False),
    ],
)
def test_long_digit_sequence_guard(value: str, expected: bool) -> None:
    assert bool(LONG_DIGIT_SEQUENCE.search(value)) is expected


def test_eval_fixture_count_floor() -> None:
    """Keep at least a few synthetic fixtures while the 30+ corpus grows."""
    assert len(_fixture_paths()) >= 4
