#!/usr/bin/env python3
"""Day 2 — 邮件收件箱流水线: 分类 → 草稿 → outbox 入库.

用法:
    # dry-run(默认, 只统计未处理邮件数, 不调 LLM / 不写库)
    uv run python scripts/process_inbox.py --source qq --limit 5

    # 真写 outbox(4 重门控)
    PROCESS_INBOX_EXECUTE=1 uv run python scripts/process_inbox.py \\
        --source qq --limit 5 --execute \\
        --confirm yes-i-understand-this-writes-outbox

退出码:
    0 = 成功(含 dry-run)
    1 = 参数 / 门控失败
    2 = 业务失败(至少 1 封 classify/draft/outbox 失败)
    3 = 技术失败(DB / 致命错误)
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from my_ai_employee.ai.classifier import (  # noqa: E402
    ClassifierResponseError,
    EmailCategory,
    EmailClassifier,
)
from my_ai_employee.ai.drafter import (  # noqa: E402
    DrafterResponseError,
    DraftTone,
    EmailDrafter,
    SpamBlockedError,
)
from my_ai_employee.ai.providers import LLMError  # noqa: E402
from my_ai_employee.ai.safety import is_system_sender  # noqa: E402  # 撞坑 #85 Layer 2 短路
from my_ai_employee.core.config import load_env  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Email  # noqa: E402
from my_ai_employee.core.outbox import OutboxEntry, OutboxPriority  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import OutboxEmailDuplicateError, OutboxStore  # noqa: E402
from my_ai_employee.events.store import EventStore  # noqa: E402
from my_ai_employee.policy.integration import (  # noqa: E402
    EmailClassifierAdapter,
    EmailDrafterAdapter,
)
from my_ai_employee.policy.outbox_adapter import EmailOutboxAdapter  # noqa: E402
from scripts.process_inbox_gate import validate_process_inbox_gate  # noqa: E402

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


@dataclass(frozen=True)
class PipelineCounters:
    candidates: int = 0
    classified: int = 0
    drafted: int = 0
    outbox_stored: int = 0
    skipped_spam: int = 0
    skipped_duplicate: int = 0
    skipped_system_sender: int = 0  # 撞坑 #85 Layer 2: system sender 短路
    classify_failed: int = 0
    draft_failed: int = 0
    outbox_failed: int = 0


def _print(msg: str) -> None:
    print(msg)


def _print_err(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)


def _normalize_recipient(sender: str) -> str:
    sender = sender.strip()
    match = _EMAIL_RE.search(sender)
    if match:
        return match.group(0)
    return sender


def _category_priority(category: str) -> str:
    if category == EmailCategory.URGENT.value:
        return str(OutboxPriority.URGENT.value)
    return str(OutboxPriority.NORMAL.value)


def list_candidate_emails(
    session_factory: sessionmaker[Session],
    *,
    source: str,
    limit: int,
) -> list[Email]:
    with session_factory() as session:
        stmt = (
            select(Email)
            .outerjoin(OutboxEntry, OutboxEntry.email_id == Email.id)
            .where(Email.source == source)
            .where(OutboxEntry.id.is_(None))
            .order_by(Email.received_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())


def process_one_email(
    email: Email,
    *,
    source: str,
    execute: bool,
    classifier: EmailClassifier,
    classify_adapter: EmailClassifierAdapter,
    drafter: EmailDrafter,
    draft_adapter: EmailDrafterAdapter,
    outbox_adapter: EmailOutboxAdapter,
) -> str:
    """处理单封邮件; 返回 outcome 标签."""
    if not execute:
        return "dry_run"

    run_id = f"{email.id}-{uuid.uuid4().hex[:8]}"
    body_excerpt = (email.body_text or "")[: EmailDrafter.MAX_BODY_CHARS]
    recipient = _normalize_recipient(email.sender or "")

    try:
        classification = classifier.classify(
            subject=email.subject or "",
            sender=email.sender or "",
            body_excerpt=body_excerpt,
        )
    except (ClassifierResponseError, LLMError, ValueError) as e:
        classify_adapter.record_classify_failure_and_emit(
            email_id=email.id,
            last_error=str(e),
            consecutive_classify_failures=1,
            run_id=run_id,
        )
        return "classify_failed"

    classify_adapter.classify_and_emit(
        email_id=email.id,
        classification=classification,
        run_id=run_id,
    )

    category = classification.category.value
    if category == EmailCategory.SPAM.value:
        return "skipped_spam"

    # D13.x P2 修复(撞坑 #85 Layer 2 · 2026-07-07,业务代码改动日 撞坑 #71 边界破例):
    # system-style sender 即使分类非 SPAM,process_inbox 也不再调 drafter。
    # 撞坑 #85 案例: 原邮件 sender=root@systemmail.yunwu.ai,即使 Layer 1 漏判,
    # process_inbox 用 sender 当 recipient_email 直接入 outbox → LLM 幻觉草稿
    # 误发风险。Layer 2 兜底: 系统发件人邮件不调 drafter(无真人接管,无需 reply)。
    if is_system_sender(email.sender or ""):
        logger_obj = __import__("loguru").logger
        logger_obj.warning(
            f"[process_inbox] 撞坑 #85 Layer 2 短路: system sender 不调 drafter | "
            f"email_id={email.id} sender={email.sender!r} category={category}"
        )
        return "skipped_system_sender"

    try:
        draft_result = drafter.draft(
            subject=email.subject or "",
            sender=email.sender or "",
            body_excerpt=body_excerpt,
            email_category=category,
            tone=DraftTone.FORMAL,
            allow_spam_reply=False,
        )
    except SpamBlockedError as e:
        draft_adapter.record_draft_business_blocked_and_emit(
            email_id=email.id,
            tone=DraftTone.FORMAL.value,
            original_email_category=category,
            reason="spam_business_blocked",
            last_error=str(e),
            consecutive_draft_failures=0,
            spam_reply_authorized=False,
            run_id=run_id,
        )
        return "skipped_spam"
    except (DrafterResponseError, LLMError, ValueError) as e:
        draft_adapter.record_draft_failure_and_emit(
            email_id=email.id,
            last_error=str(e),
            consecutive_draft_failures=1,
            run_id=run_id,
        )
        return "draft_failed"

    draft_adapter.draft_and_emit(
        email_id=email.id,
        category=category,
        draft_result=draft_result,
        run_id=run_id,
    )

    try:
        outbox_report = outbox_adapter.store_and_emit(
            email_id=email.id,
            subject=draft_result.subject,
            body=draft_result.body,
            tone=draft_result.tone.value
            if hasattr(draft_result.tone, "value")
            else str(draft_result.tone),
            recipient_email=recipient,
            priority=_category_priority(category),
            run_id=run_id,
        )
    except OutboxEmailDuplicateError:
        return "skipped_duplicate"
    except ValueError as e:
        outbox_adapter.record_store_failure_and_emit(
            email_id=email.id,
            subject=draft_result.subject,
            body=draft_result.body,
            tone=draft_result.tone.value
            if hasattr(draft_result.tone, "value")
            else str(draft_result.tone),
            recipient_email=recipient,
            last_error=str(e),
            consecutive_outbox_failures=1,
            run_id=run_id,
        )
        return "outbox_failed"

    if not outbox_report.outbox_stored:
        return "outbox_failed"
    return "outbox_stored"


def run_pipeline(
    *,
    source: str,
    limit: int,
    execute: bool,
    db_path: Path | None = None,
    classifier: EmailClassifier | None = None,
    drafter: EmailDrafter | None = None,
) -> tuple[int, PipelineCounters]:
    db = Database.open(db_path=db_path)
    counters = PipelineCounters()
    try:
        engine = make_sqlalchemy_engine(db)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        candidates = list_candidate_emails(session_factory, source=source, limit=limit)
        counters = PipelineCounters(candidates=len(candidates))

        if not candidates:
            _print(f"process_inbox: source={source!r} candidates=0 execute={execute}")
            return 0, counters

        if not execute:
            _print(
                f"process_inbox dry-run: source={source!r} candidates={len(candidates)} "
                f"limit={limit} (未调 LLM / 未写 outbox)"
            )
            for email in candidates:
                _print(f"  - email_id={email.id} uid={email.uid} subject={email.subject!r}")
            return 0, counters

        event_store = EventStore(session_factory)
        outbox_store = OutboxStore(session_factory)
        classifier_impl = classifier or EmailClassifier()
        drafter_impl = drafter or EmailDrafter()
        classify_adapter = EmailClassifierAdapter(source=source, event_store=event_store)
        draft_adapter = EmailDrafterAdapter(source=source, event_store=event_store)
        outbox_adapter = EmailOutboxAdapter(source=source, outbox_store=outbox_store)

        outcomes: dict[str, int] = {}
        t0 = time.perf_counter()
        for email in candidates:
            outcome = process_one_email(
                email,
                source=source,
                execute=True,
                classifier=classifier_impl,
                classify_adapter=classify_adapter,
                drafter=drafter_impl,
                draft_adapter=draft_adapter,
                outbox_adapter=outbox_adapter,
            )
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

        classified = sum(
            outcomes.get(k, 0)
            for k in (
                "outbox_stored",
                "skipped_spam",
                "skipped_duplicate",
                "skipped_system_sender",  # 撞坑 #85 Layer 2 也算已分类
                "draft_failed",
                "outbox_failed",
            )
        )
        counters = PipelineCounters(
            candidates=len(candidates),
            classified=classified,
            drafted=outcomes.get("outbox_stored", 0)
            + outcomes.get("skipped_duplicate", 0)
            + outcomes.get("outbox_failed", 0),
            outbox_stored=outcomes.get("outbox_stored", 0),
            skipped_spam=outcomes.get("skipped_spam", 0),
            skipped_duplicate=outcomes.get("skipped_duplicate", 0),
            skipped_system_sender=outcomes.get("skipped_system_sender", 0),
            classify_failed=outcomes.get("classify_failed", 0),
            draft_failed=outcomes.get("draft_failed", 0),
            outbox_failed=outcomes.get("outbox_failed", 0),
        )
        elapsed = time.perf_counter() - t0
        _print(
            "process_inbox execute: "
            f"source={source!r} candidates={counters.candidates} "
            f"outbox_stored={counters.outbox_stored} "
            f"skipped_spam={counters.skipped_spam} "
            f"skipped_system_sender={counters.skipped_system_sender} "
            f"classify_failed={counters.classify_failed} "
            f"draft_failed={counters.draft_failed} "
            f"outbox_failed={counters.outbox_failed} "
            f"duration={elapsed:.2f}s"
        )

        if counters.classify_failed or counters.draft_failed or counters.outbox_failed:
            return 2, counters
        return 0, counters
    except OperationalError as e:
        _print_err(f"数据库技术失败: {e!r}")
        return 3, counters
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="邮件收件箱流水线: 分类 → 草稿 → outbox")
    parser.add_argument("--source", required=True, help='邮件来源, 如 "qq"')
    parser.add_argument("--limit", type=int, default=5, help="最多处理邮件数(默认 5)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="真写 outbox(默认 dry-run)",
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default="",
        help="真写确认文本(沿 process_inbox_gate)",
    )
    parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径, 默认主库")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env()
    args = _build_parser().parse_args(argv)

    gate_err = validate_process_inbox_gate(
        execute=args.execute,
        confirm=args.confirm,
        limit=args.limit,
    )
    if gate_err:
        _print_err(gate_err)
        return 1

    if not isinstance(args.source, str) or not args.source.strip():
        _print_err("--source 必填非空")
        return 1

    code, _counters = run_pipeline(
        source=args.source.strip(),
        limit=args.limit,
        execute=args.execute,
        db_path=args.db_path,
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
