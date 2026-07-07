"""process_inbox.py CLI + 流水线单元测试."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from my_ai_employee.ai.capability import TaskType  # noqa: E402
from my_ai_employee.ai.providers import LLMResponse  # noqa: E402
from my_ai_employee.core.models import Base, Email  # noqa: E402
from my_ai_employee.events import models as _events_models  # noqa: E402, F401
from scripts import process_inbox  # noqa: E402
from scripts.process_inbox import (  # noqa: E402
    _normalize_recipient,
    list_candidate_emails,
    main,
    run_pipeline,
)
from scripts.process_inbox_gate import REQUIRED_CONFIRM  # noqa: E402


class _FakeDatabase:
    def __init__(self, path: Path) -> None:
        self._path = path

    def close(self) -> None:
        pass


def _make_plain_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        conn.execute("DELETE FROM alembic_version")
        conn.execute(
            "INSERT INTO alembic_version (version_num) VALUES ('0016_approval_gate_audits')"
        )
    finally:
        conn.close()
    from sqlalchemy import create_engine

    eng = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    eng.dispose()


def _plain_engine(db_path: Path) -> Any:
    from sqlalchemy import create_engine

    return create_engine(f"sqlite:///{db_path}")


def _seed_email(db_path: Path, *, source: str = "qq", uid: int = 1) -> int:
    from sqlalchemy.orm import sessionmaker

    eng = _plain_engine(db_path)
    sf = sessionmaker(bind=eng)
    with sf() as session:
        row = Email(
            source=source,
            uid=uid,
            subject="测试主题",
            sender="user@example.com",
            body_text="这是一封测试邮件正文。",
            fetched_at=1_700_000_000_000,
            received_at=1_700_000_000_000,
        )
        session.add(row)
        session.commit()
        email_id = int(row.id)
    eng.dispose()
    return email_id


def _run_with_plain_db(db_path: Path, fn: Any) -> Any:
    fake_db = _FakeDatabase(db_path)
    plain_engine = _plain_engine(db_path)
    with (
        patch.object(process_inbox, "Database") as mock_db_class,
        patch.object(process_inbox, "make_sqlalchemy_engine", return_value=plain_engine),
    ):
        mock_db_class.open.return_value = fake_db
        return fn()


class _MockRouter:
    def route(
        self,
        *,
        task_type: Any,
        messages: Any,
        temperature: Any,
        max_tokens: Any,
    ) -> LLMResponse:
        if task_type == TaskType.CLASSIFY:
            return LLMResponse(
                content='{"category": "TODO", "confidence": 0.91}',
                model_full_id="mock-classifier",
                input_tokens=10,
                output_tokens=5,
                latency_ms=12,
            )
        return LLMResponse(
            content=(
                '{"subject": "Re: 测试", "body": "您好，已收到您的邮件，我们会尽快处理。", '
                '"tone": "FORMAL"}'
            ),
            model_full_id="mock-drafter",
            input_tokens=20,
            output_tokens=30,
            latency_ms=18,
        )


class _BadDraftRouter:
    def route(
        self,
        *,
        task_type: Any,
        messages: Any,
        temperature: Any,
        max_tokens: Any,
    ) -> LLMResponse:
        if task_type == TaskType.CLASSIFY:
            return LLMResponse(
                content='{"category": "TODO", "confidence": 0.91}',
                model_full_id="mock-classifier",
                input_tokens=10,
                output_tokens=5,
                latency_ms=12,
            )
        return LLMResponse(
            content="<think>not bare json</think>",
            model_full_id="mock-drafter",
            input_tokens=20,
            output_tokens=30,
            latency_ms=18,
        )


def test_normalize_recipient_extracts_email() -> None:
    assert _normalize_recipient("Alice <alice@example.com>") == "alice@example.com"
    assert _normalize_recipient("bob@test.qq.com") == "bob@test.qq.com"


def test_dry_run_lists_candidates_without_llm(tmp_path: Path) -> None:
    db_path = tmp_path / "inbox.db"
    _make_plain_db(db_path)
    _seed_email(db_path)

    code, counters = _run_with_plain_db(
        db_path,
        lambda: run_pipeline(source="qq", limit=5, execute=False, db_path=db_path),
    )
    assert code == 0
    assert counters.candidates == 1


def test_execute_writes_outbox_with_mock_router(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inbox.db"
    _make_plain_db(db_path)
    _seed_email(db_path)
    monkeypatch.setenv("PROCESS_INBOX_EXECUTE", "1")

    from my_ai_employee.ai.classifier import EmailClassifier
    from my_ai_employee.ai.drafter import EmailDrafter

    router = _MockRouter()
    classifier = EmailClassifier(router=router)  # type: ignore[arg-type]
    drafter = EmailDrafter(router=router)  # type: ignore[arg-type]

    code, counters = _run_with_plain_db(
        db_path,
        lambda: run_pipeline(
            source="qq",
            limit=1,
            execute=True,
            db_path=db_path,
            classifier=classifier,
            drafter=drafter,
        ),
    )
    assert code == 0
    assert counters.outbox_stored == 1

    from sqlalchemy import text

    eng = _plain_engine(db_path)
    with eng.connect() as conn:
        outbox_count = conn.execute(text("SELECT COUNT(*) FROM outbox")).scalar()
    assert outbox_count == 1
    eng.dispose()


def test_execute_records_draft_response_error_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "inbox.db"
    _make_plain_db(db_path)
    _seed_email(db_path)
    monkeypatch.setenv("PROCESS_INBOX_EXECUTE", "1")

    from my_ai_employee.ai.classifier import EmailClassifier
    from my_ai_employee.ai.drafter import EmailDrafter

    router = _BadDraftRouter()
    classifier = EmailClassifier(router=router)  # type: ignore[arg-type]
    drafter = EmailDrafter(router=router)  # type: ignore[arg-type]

    code, counters = _run_with_plain_db(
        db_path,
        lambda: run_pipeline(
            source="qq",
            limit=1,
            execute=True,
            db_path=db_path,
            classifier=classifier,
            drafter=drafter,
        ),
    )
    assert code == 2
    assert counters.draft_failed == 1
    assert counters.outbox_stored == 0

    from sqlalchemy import text

    eng = _plain_engine(db_path)
    with eng.connect() as conn:
        outbox_count = conn.execute(text("SELECT COUNT(*) FROM outbox")).scalar()
    assert outbox_count == 0
    eng.dispose()


def test_cli_rejects_execute_without_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROCESS_INBOX_EXECUTE", raising=False)
    code = main(["--source", "qq", "--limit", "1", "--execute", "--confirm", REQUIRED_CONFIRM])
    assert code == 1


def test_list_candidate_emails_excludes_outboxed(tmp_path: Path) -> None:
    db_path = tmp_path / "inbox.db"
    _make_plain_db(db_path)
    email_id = _seed_email(db_path)

    from sqlalchemy.orm import sessionmaker

    from my_ai_employee.core.outbox import OutboxEntry, OutboxStatus, OutboxTone

    eng = _plain_engine(db_path)
    sf = sessionmaker(bind=eng)
    with sf() as session:
        session.add(
            OutboxEntry(
                email_id=email_id,
                subject="已有草稿",
                body="正文足够长用于通过契约校验。",
                tone=OutboxTone.FORMAL.value,
                recipient_email="user@example.com",
                status=OutboxStatus.PENDING_SEND.value,
                created_at=1,
            )
        )
        session.commit()
    candidates = list_candidate_emails(sf, source="qq", limit=5)
    assert candidates == []
    eng.dispose()


# ===== 撞坑 #85 Layer 2: process_inbox system sender 短路 =====


def test_system_sender_short_circuits_drafter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """撞坑 #85 Layer 2: system sender 邮件 process_inbox 不调 drafter,不入 outbox.

    撞坑 #85 案例: 原邮件 sender=root@systemmail.yunwu.ai,即使分类 TODO,
    process_inbox 不调 drafter(避免 LLM 幻觉草稿入 outbox)。

    关键: 本测试用 mock classifier 直接返回 TODO(绕过 Layer 1 短路),验证
    Layer 2 兜底生效。Layer 1 + Layer 2 是双层防御,任一层都能拦截。
    """
    from sqlalchemy import text

    from my_ai_employee.ai.drafter import EmailDrafter

    db_path = tmp_path / "inbox.db"
    _make_plain_db(db_path)

    # seed system sender 邮件(撞坑 #85 案例)
    from sqlalchemy.orm import sessionmaker

    eng = _plain_engine(db_path)
    sf = sessionmaker(bind=eng)
    with sf() as session:
        row = Email(
            source="qq",
            uid=812,
            subject="周报",
            sender="root@systemmail.yunwu.ai",  # system-style sender
            body_text="本周工作周报请查收。",  # body 长(避免 Layer 1 主题黑名单词命中)
            fetched_at=1_700_000_000_000,
            received_at=1_700_000_000_000,
        )
        session.add(row)
        session.commit()
    eng.dispose()

    monkeypatch.setenv("PROCESS_INBOX_EXECUTE", "1")

    # Mock classifier 强制返 TODO(绕过 Layer 1 短路,验证 Layer 2 兜底)
    class _ForceTodoClassifier:
        def classify(
            self,
            *,
            subject: str,
            sender: str,
            body_excerpt: str,
        ) -> Any:
            from my_ai_employee.ai.classifier import (
                ClassificationResult,
                EmailCategory,
            )

            return ClassificationResult(
                category=EmailCategory.TODO,
                confidence=0.8,
                model_full_id="mock-force-todo",
                latency_ms=0,
                raw_content='{"category": "TODO", "confidence": 0.8}',
            )

    router = _MockRouter()
    classifier = _ForceTodoClassifier()  # type: ignore[assignment,arg-type]
    drafter = EmailDrafter(router=router)

    code, counters = _run_with_plain_db(
        db_path,
        lambda: run_pipeline(
            source="qq",
            limit=1,
            execute=True,
            db_path=db_path,
            classifier=classifier,  # type: ignore[arg-type]
            drafter=drafter,
        ),
    )

    # 关键: classifier 返 TODO(绕过 Layer 1),但 Layer 2 兜底 system sender,
    # skipped_system_sender=1,outbox_stored=0
    assert code == 0
    assert counters.candidates == 1
    assert counters.skipped_spam == 0  # 不是 SPAM,是被 Layer 2 兜底
    assert counters.skipped_system_sender == 1
    assert counters.outbox_stored == 0
    assert counters.draft_failed == 0

    # outbox 表应为空(没生成草稿)
    eng2 = _plain_engine(db_path)
    with eng2.connect() as conn:
        outbox_count = conn.execute(text("SELECT COUNT(*) FROM outbox")).scalar()
    assert outbox_count == 0
    eng2.dispose()


def test_system_sender_with_classifier_short_circuit_layer1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """撞坑 #85 Layer 1 + Layer 2 协同: system sender + 紧急主题 + body 空
    Layer 1 短路 SPAM(不算 system_sender_skip),但如果分类器漏判(返回 TODO),
    Layer 2 兜底系统发件人短路。

    本测试模拟 Layer 1 漏判(返回 TODO),验证 Layer 2 兜底生效。
    """
    from my_ai_employee.ai.classifier import EmailClassifier
    from my_ai_employee.ai.drafter import EmailDrafter

    db_path = tmp_path / "inbox.db"
    _make_plain_db(db_path)

    # seed 普通 user 邮件(非 system sender),body 短,主题含"紧急"
    # 模拟 Layer 1 漏判: sender 是普通用户,但主题 + body 短不足以触发 Layer 1
    from sqlalchemy.orm import sessionmaker

    eng = _plain_engine(db_path)
    sf = sessionmaker(bind=eng)
    with sf() as session:
        row = Email(
            source="qq",
            uid=900,
            subject="[紧急] API 服务异常需立即处理",
            sender="alerts@partner.example.com",  # 非 system sender
            body_text="简短",  # 12 字符(< 30 阈值)
            fetched_at=1_700_000_000_000,
            received_at=1_700_000_000_000,
        )
        session.add(row)
        session.commit()
    eng.dispose()

    monkeypatch.setenv("PROCESS_INBOX_EXECUTE", "1")
    router = _MockRouter()
    classifier = EmailClassifier(router=router)  # type: ignore[arg-type]
    drafter = EmailDrafter(router=router)  # type: ignore[arg-type]

    code, counters = _run_with_plain_db(
        db_path,
        lambda: run_pipeline(
            source="qq",
            limit=1,
            execute=True,
            db_path=db_path,
            classifier=classifier,
            drafter=drafter,
        ),
    )

    # Layer 1 应该短路 SPAM(alerts@ + 紧急 + body 短 → 双信号命中)
    assert code == 0
    assert counters.candidates == 1
    # Layer 1 短路 → 走 skipped_spam 路径(不是 skipped_system_sender)
    assert counters.skipped_spam == 1
    assert counters.skipped_system_sender == 0
    assert counters.outbox_stored == 0


def test_normal_sender_not_short_circuited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """撞坑 #85 反向验证: 普通 user sender → 不短路,正常走 drafter + outbox."""
    from sqlalchemy import text

    from my_ai_employee.ai.classifier import EmailClassifier
    from my_ai_employee.ai.drafter import EmailDrafter

    db_path = tmp_path / "inbox.db"
    _make_plain_db(db_path)
    # 默认 _seed_email 用 sender="user@example.com"(非 system)
    _seed_email(db_path)
    monkeypatch.setenv("PROCESS_INBOX_EXECUTE", "1")

    router = _MockRouter()
    classifier = EmailClassifier(router=router)  # type: ignore[arg-type]
    drafter = EmailDrafter(router=router)  # type: ignore[arg-type]

    code, counters = _run_with_plain_db(
        db_path,
        lambda: run_pipeline(
            source="qq",
            limit=1,
            execute=True,
            db_path=db_path,
            classifier=classifier,
            drafter=drafter,
        ),
    )

    # 普通 sender → 走完整 drafter + outbox
    assert code == 0
    assert counters.skipped_system_sender == 0
    assert counters.outbox_stored == 1

    eng = _plain_engine(db_path)
    with eng.connect() as conn:
        outbox_count = conn.execute(text("SELECT COUNT(*) FROM outbox")).scalar()
    assert outbox_count == 1
    eng.dispose()
