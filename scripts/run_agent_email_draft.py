#!/usr/bin/env python3
"""邮件→草稿 AgentRun CLI（默认 dry-run，默认不 SMTP）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.runtime.models import AgentRunRecord  # noqa: F401 — register metadata
from my_ai_employee.runtime.store import AgentRunStore
from my_ai_employee.runtime.workflows.email_to_draft import EmailToDraftInput, run_email_to_draft


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentRun email_to_draft（默认 dry-run）")
    parser.add_argument("--email-json", type=Path, required=True, help="脱敏邮件 JSON 文件")
    parser.add_argument("--db", type=Path, default=None, help="SQLite 路径；默认 :memory:")
    parser.add_argument("--resume", type=str, default=None, help="已有 run_id")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="审批通过并 finalize（仍不 SMTP）",
    )
    parser.add_argument("--cancel", action="store_true", help="审批拒绝")
    parser.add_argument(
        "--write-outbox",
        action="store_true",
        help="非 dry-run：允许调用 outbox 插入钩子（本 CLI 默认仍用 stub id）",
    )
    args = parser.parse_args(argv)

    email = json.loads(args.email_json.read_text(encoding="utf-8"))
    if not isinstance(email, dict):
        print("email-json 必须是 object", file=sys.stderr)
        return 2

    url = f"sqlite:///{args.db}" if args.db else "sqlite:///:memory:"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    store = AgentRunStore(factory)

    decision = None
    if args.approve:
        decision = "approve"
    elif args.cancel:
        decision = "cancel"

    result = run_email_to_draft(
        store,
        EmailToDraftInput(
            email=email,
            dry_run=not args.write_outbox,
            approval_decision=decision,
        ),
        existing_run_id=args.resume,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
