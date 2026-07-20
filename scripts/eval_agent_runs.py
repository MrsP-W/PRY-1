#!/usr/bin/env python3
"""AgentRun 脱敏回归 Eval（无外网）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.runtime.models import AgentRunRecord  # noqa: F401
from my_ai_employee.runtime.store import AgentRunStore
from my_ai_employee.runtime.workflows.email_to_draft import EmailToDraftInput, run_email_to_draft

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIR = ROOT / "tests" / "runtime" / "fixtures" / "email_to_draft"


def _run_case(store: AgentRunStore, case: dict) -> None:
    email = case["email"]
    expected_steps = case["expected_steps"]
    expected_status = case["expected_status"]
    result = run_email_to_draft(
        store,
        EmailToDraftInput(
            email=email,
            dry_run=True,
            approval_decision=case.get("approval_decision"),
        ),
    )
    if result.status != expected_status:
        raise AssertionError(f"status {result.status!r} != {expected_status!r}")
    for step in expected_steps:
        if step not in result.steps and step not in (result.steps or []):
            # finalize may be only on approve path
            if step == "finalize" and expected_status == "awaiting_approval":
                continue
            if step not in result.steps:
                raise AssertionError(f"missing step {step!r} in {result.steps!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eval AgentRun fixtures")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURE_DIR)
    args = parser.parse_args(argv)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = AgentRunStore(sessionmaker(bind=engine))

    cases = sorted(args.fixtures.glob("*.json"))
    if not cases:
        print(f"no fixtures in {args.fixtures}", file=sys.stderr)
        return 2
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        _run_case(store, case)
        print(f"PASS {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
