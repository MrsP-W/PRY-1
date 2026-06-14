"""D5.3 — EmailSendAdapter 业务层接入测试(+36 cases).

承接 D5.1 SMTP transport(connectors/smtp.py:SmtpLibTransport + InMemorySmtpTransport)
+ D5.2 状态机扩值(0005_outbox_sending_state migration + ALLOWED_TRANSITIONS 6 状态白名单)
+ D5.3 EmailSendAdapter 三入口(send_and_emit / record_send_business_blocked_and_emit /
  record_send_failure_and_emit) + 3 DecisionReport dataclass + 4 SMTP 异常类.

7 段测试覆盖(36 cases):
    A. 5 helper / factory / acceptance(7 tests)
       - compute_send_acceptance 3 条 AC(4)
       - build_send_policy_context 双向强一致(1)
       - 2 业务阻断/技术失败 白名单冻结集(2)
    B. 3 DecisionReport dataclass 双层防御(3 tests)
       - SendDecisionReport / SendBlockedDecisionReport / SendFailureDecisionReport 最小构造
    C. EmailSendAdapter 三入口(26 tests)
       - send_and_emit 8(成功/异常分流/严判)
       - record_send_business_blocked_and_emit 9(白名单/严判/状态机)
       - record_send_failure_and_emit 9(白名单/严判/状态机)

合计 36 cases。

D5.3 vs D5 启动计划文档偏差(报告必标注):
    D5 启动计划: EmailSendAdapter 三入口 → 36 cases 状态机白名单严判
    D5.3 实际:   36 cases 全绿(沿 D4.7.3 v1.0.6 25 教训应用)

Fixture 复用 tests/db/test_outbox.py 范本(tmp_db_path + fake_keychain +
db_with_schema + session_factory + store),加 smtp_transport 替身 fixture。
"""

from __future__ import annotations

import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.connectors.smtp import (  # noqa: E402
    SMTP_SEND_OK,
    SMTP_SEND_PERMANENT_BOUNCE,
    SMTP_SEND_TRANSPORT_ERROR,
    InMemorySmtpTransport,
)
from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.db.outbox import OutboxStore  # noqa: E402
from my_ai_employee.policy.exceptions import (  # noqa: E402
    SMTPSendIllegalTransitionError,
    SMTPSendRecipientsRefusedError,
    SMTPSendSenderRefusedError,
    SMTPSendTransportError,
)
from my_ai_employee.policy.send_adapter import (  # noqa: E402
    SEND_BLOCK_REASON_VALUES,
    SEND_FAILURE_ERROR_CATEGORIES,
    EmailSendAdapter,
    SendBlockedDecisionReport,
    SendDecisionReport,
    SendFailureDecisionReport,
    build_send_policy_context,
    compute_send_acceptance,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ===== Fixtures(复用 tests/db/test_outbox.py 范本)====


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """测试用临时 DB 路径(不污染真实 ~/Library/Application Support)。"""
    return tmp_path / "test.db"


@pytest.fixture
def fake_keychain(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """用 in-memory dict 模拟 Keychain(避免污染真实 macOS Keychain)。"""
    store: dict[tuple[str, str], str] = {}

    def fake_get() -> keychain.KeychainResult:
        key = (keychain.SERVICE_DB, "data.db")
        if key in store:
            return keychain.KeychainResult(ok=True, value=store[key])
        return keychain.KeychainResult(ok=False, error="not found")

    def fake_set(password: str) -> keychain.KeychainResult:
        store[(keychain.SERVICE_DB, "data.db")] = password
        return keychain.KeychainResult(ok=True)

    monkeypatch.setattr(keychain, "get_db_password", fake_get)
    monkeypatch.setattr(keychain, "set_db_password", fake_set)
    return store


@pytest.fixture
def db_with_schema(tmp_db_path: Path, fake_keychain: dict) -> Iterator[Database]:
    """打开 DB + Base.metadata.create_all + yield(测试后自动 close)。"""
    db = Database.open(db_path=tmp_db_path)
    engine = make_sqlalchemy_engine(db)
    from my_ai_employee.core.models import Base
    from my_ai_employee.events import models as _events_models  # noqa: F401

    Base.metadata.create_all(engine)
    yield db
    db.close()


def make_sqlalchemy_engine(db: Database):  # type: ignore[no-untyped-def]
    """复用 connectors/smtp.py 同款 SQLCipher engine 工厂。"""
    from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine as _make

    return _make(db)


@pytest.fixture
def session_factory(db_with_schema: Database):  # type: ignore[no-untyped-def]
    """返回 SQLAlchemy sessionmaker(绑 SQLCipher engine)。"""
    from sqlalchemy.orm import sessionmaker

    engine = make_sqlalchemy_engine(db_with_schema)
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory) -> OutboxStore:  # type: ignore[no-untyped-def]
    """OutboxStore 实例(注入 session_factory)。"""
    return OutboxStore(session_factory)


@pytest.fixture
def smtp_transport() -> InMemorySmtpTransport:
    """InMemorySmtpTransport 替身(D5.1 测试用, 不真发 SMTP)。"""
    return InMemorySmtpTransport()


@pytest.fixture
def adapter(store: OutboxStore, smtp_transport: InMemorySmtpTransport) -> EmailSendAdapter:
    """EmailSendAdapter 实例(注入 store + smtp_transport, 默认 heartbeat/board)."""
    return EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )


def _make_email_message() -> EmailMessage:
    """构造一个简单的 EmailMessage(测试用)."""
    msg = EmailMessage()
    msg["Subject"] = "测试邮件主题"
    msg["From"] = "test@example.com"
    msg["To"] = "customer@example.com"
    msg.set_content("测试邮件正文内容,超过十个字符。")
    return msg


def _insert_pending_entry(store: OutboxStore, *, email_id: int) -> int:
    """插入一条 PENDING_SEND 状态的 outbox 条目,返回 outbox_id."""
    entry = store.insert(
        email_id=email_id,
        subject="测试邮件主题",
        body="测试邮件正文内容,超过十个字符。",
        tone="FORMAL",
        recipient_email=f"customer{email_id}@example.com",
    )
    assert entry.id is not None  # noqa: S101 — insert 必返回 id
    return entry.id


# ===== A. 5 helper / factory / acceptance(7 tests)=====


def test_compute_send_acceptance_three_passes() -> None:
    """compute_send_acceptance 3 条 AC 全过(沿 D4.8 范本)."""
    result = compute_send_acceptance(
        subject_length=10,
        body_length=100,
        recipient_email="customer@example.com",
    )
    assert result == [True, True, True]


def test_compute_send_acceptance_subject_too_long() -> None:
    """compute_send_acceptance subject 超 200 字符 → False."""
    result = compute_send_acceptance(
        subject_length=201,
        body_length=100,
        recipient_email="customer@example.com",
    )
    assert result == [False, True, True]


def test_compute_send_acceptance_body_too_short() -> None:
    """compute_send_acceptance body 短于 10 字符 → False."""
    result = compute_send_acceptance(
        subject_length=10,
        body_length=5,
        recipient_email="customer@example.com",
    )
    assert result == [True, False, True]


def test_compute_send_acceptance_recipient_no_at() -> None:
    """compute_send_acceptance recipient 不含 @ → False."""
    result = compute_send_acceptance(
        subject_length=10,
        body_length=100,
        recipient_email="customer.example.com",
    )
    assert result == [True, True, False]


def test_build_send_policy_context_consistent() -> None:
    """build_send_policy_context 双向强一致(last_send_failed ↔ cf 严判).

    成功路径: last_send_failed=False → cf=0(双向强一致)
    """
    ctx = build_send_policy_context(
        outbox_id=1,
        tone="FORMAL",
        priority="normal",
        subject_length=10,
        body_length=100,
        last_send_failed=False,
        consecutive_send_failures=0,
        now_ms=1_000_000,
    )
    assert ctx["last_send_failed"] is False
    assert ctx["consecutive_send_failures"] == 0

    # 反向: last_send_failed=True → cf=1(技术失败场景)
    ctx2 = build_send_policy_context(
        outbox_id=2,
        tone="FORMAL",
        priority="normal",
        subject_length=10,
        body_length=100,
        last_send_failed=True,
        consecutive_send_failures=1,
        now_ms=1_000_000,
    )
    assert ctx2["last_send_failed"] is True
    assert ctx2["consecutive_send_failures"] == 1

    # 矛盾状态: last_send_failed=True 但 cf=0 → 抛 ValueError
    with pytest.raises(ValueError, match="双向强一致"):
        build_send_policy_context(
            outbox_id=3,
            tone="FORMAL",
            priority="normal",
            subject_length=10,
            body_length=100,
            last_send_failed=True,
            consecutive_send_failures=0,  # 矛盾
            now_ms=1_000_000,
        )


def test_send_block_reason_values_whitelist() -> None:
    """SEND_BLOCK_REASON_VALUES 冻结集含 3 类白名单(沿 D4.8 范本)."""
    assert isinstance(SEND_BLOCK_REASON_VALUES, frozenset)
    assert "recipients_refused" in SEND_BLOCK_REASON_VALUES
    assert "sender_refused" in SEND_BLOCK_REASON_VALUES
    assert "data_error" in SEND_BLOCK_REASON_VALUES
    assert len(SEND_BLOCK_REASON_VALUES) == 3


def test_send_failure_error_categories_whitelist() -> None:
    """SEND_FAILURE_ERROR_CATEGORIES 冻结集含 4 类白名单(沿 D4.8 范本)."""
    assert isinstance(SEND_FAILURE_ERROR_CATEGORIES, frozenset)
    assert "transport_error" in SEND_FAILURE_ERROR_CATEGORIES
    assert "ssl_error" in SEND_FAILURE_ERROR_CATEGORIES
    assert "timeout" in SEND_FAILURE_ERROR_CATEGORIES
    assert "smtp_other" in SEND_FAILURE_ERROR_CATEGORIES
    assert len(SEND_FAILURE_ERROR_CATEGORIES) == 4


# ===== B. 3 DecisionReport dataclass(3 tests)=====
# 注: 完整构造需要 PolicyEngine.evaluate() 的真实结果, 这里用最小 _FakeEvaluation 替身


class _FakeEvaluation:
    """测试替身 — 模拟 PolicyEngine.evaluate() 返回结果(满足 Protocol 期望)."""

    def __init__(self) -> None:
        self.event_id = 1
        self.decision = "ALLOW"
        self.context_signals: dict[str, object] = {}


def test_send_decision_report_basic() -> None:
    """SendDecisionReport 最小构造(成功发送, send_succeeded=True 必锁)."""
    report = SendDecisionReport(
        evaluation=_FakeEvaluation(),  # type: ignore[arg-type]
        event_id=1,
        lane_entry_id="send:test:run1",
        liveness="healthy",  # type: ignore[arg-type]
        outbox_id=1,
        email_id=100,
        subject="测试邮件主题",
        body="测试邮件正文内容,超过十个字符。",
        tone="FORMAL",
        recipient_email="customer@example.com",
        priority="normal",
        subject_length=10,
        body_length=20,
        latency_ms=100,
        smtp_code=250,
    )
    assert report.send_succeeded is True
    assert report.outbox_id == 1
    assert report.smtp_code == 250


def test_send_blocked_decision_report_basic() -> None:
    """SendBlockedDecisionReport 最小构造(业务阻断, send_blocked=True 必锁)."""
    report = SendBlockedDecisionReport(
        evaluation=_FakeEvaluation(),  # type: ignore[arg-type]
        event_id=1,
        lane_entry_id="send:test:run1",
        liveness="healthy",  # type: ignore[arg-type]
        last_error="SMTP 收件人拒收: 550 mailbox not found",
        reason="recipients_refused",
        outbox_id=1,
        email_id=100,
        subject="测试邮件主题",
        body="测试邮件正文内容,超过十个字符。",
        tone="FORMAL",
        recipient_email="customer@example.com",
    )
    assert report.send_blocked is True
    assert report.kind == "business_blocked"
    assert report.reason == "recipients_refused"
    assert report.consecutive_send_failures == 0


def test_send_failure_decision_report_basic() -> None:
    """SendFailureDecisionReport 最小构造(技术失败, send_failed=True 必锁)."""
    report = SendFailureDecisionReport(
        evaluation=_FakeEvaluation(),  # type: ignore[arg-type]
        event_id=1,
        lane_entry_id="send:test:run1",
        liveness="healthy",  # type: ignore[arg-type]
        last_error="SMTP 服务器断连: ConnectionResetError",
        error_category="transport_error",
        outbox_id=1,
        email_id=100,
        subject="测试邮件主题",
        body="测试邮件正文内容,超过十个字符。",
        tone="FORMAL",
        recipient_email="customer@example.com",
        consecutive_send_failures=1,
        retry_after_ms=60_000,
    )
    assert report.send_failed is True
    assert report.error_category == "transport_error"
    assert report.consecutive_send_failures == 1
    assert report.retry_after_ms == 60_000


# ===== C.1 EmailSendAdapter.send_and_emit(8 tests)=====


def test_send_and_emit_success_approved_to_sent_pending_path(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """send_and_emit 成功路径: APPROVED → SENDING → SENT(D5.6.4 P1 — PENDING_SEND 收窄)."""
    outbox_id = _insert_pending_entry(store, email_id=1000)
    # D5.6.4 P1: send_and_emit 收窄至 APPROVED only,先推 APPROVED(带 last_approved_at_ms 凭据)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(time.time() * 1000),
    )
    smtp_transport.inject_status = SMTP_SEND_OK  # 默认就是 OK, 显式标

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.send_and_emit(
        outbox_id=outbox_id,
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_username="test@qq.com",
        smtp_password="test_authcode_16",
        email_message=_make_email_message(),
    )
    assert report.send_succeeded is True
    assert report.outbox_id == outbox_id
    # 状态机推进正确
    entry = store.by_id(outbox_id)
    assert entry is not None
    assert entry.status == "sent"


def test_send_and_emit_success_approved_to_sent(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """send_and_emit 成功路径: APPROVED → SENDING → SENT(D4.8 显式批准路径)."""
    import time as _t

    outbox_id = _insert_pending_entry(store, email_id=1001)
    # 先推到 APPROVED(D5.6.3 P1-1:update_status(new_status=APPROVED) 必传 last_approved_at_ms)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(_t.time() * 1000),
    )

    smtp_transport.inject_status = SMTP_SEND_OK
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.send_and_emit(
        outbox_id=outbox_id,
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_username="test@qq.com",
        smtp_password="test_authcode_16",
        email_message=_make_email_message(),
    )
    assert report.send_succeeded is True
    entry = store.by_id(outbox_id)
    assert entry is not None
    assert entry.status == "sent"


def test_send_and_emit_recipients_refused_raises(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """send_and_emit SMTPRecipientsRefused → 业务阻断入口异常."""
    outbox_id = _insert_pending_entry(store, email_id=1002)
    # D5.6.4 P1: 收窄至 APPROVED,先推 APPROVED(带 last_approved_at_ms 凭据)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(time.time() * 1000),
    )
    smtp_transport.inject_status = SMTP_SEND_PERMANENT_BOUNCE

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(SMTPSendRecipientsRefusedError, match="永久退信"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


def test_send_and_emit_transport_error_raises(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """send_and_emit transport 返回 transport_error → 技术失败入口异常."""
    outbox_id = _insert_pending_entry(store, email_id=1003)
    # D5.6.4 P1: 收窄至 APPROVED,先推 APPROVED(带 last_approved_at_ms 凭据)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(time.time() * 1000),
    )
    smtp_transport.inject_status = SMTP_SEND_TRANSPORT_ERROR

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(SMTPSendTransportError, match="传输错误"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


def test_send_and_emit_outbox_not_found_raises(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """send_and_emit outbox_id 不存在 → ValueError."""
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="不存在"):
        adapter.send_and_emit(
            outbox_id=99999,  # 不存在
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


def test_send_and_emit_invalid_outbox_status_raises(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """send_and_emit 状态非 APPROVED → ValueError(D5.6.4 P1 收窄)."""
    outbox_id = _insert_pending_entry(store, email_id=1004)
    # 推到 SENT(已发送)
    store.update_status(outbox_id, "sending", from_status="pending_send")
    store.update_status(outbox_id, "sent", from_status="sending")

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="APPROVED"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


def test_send_and_emit_no_smtp_transport_raises(store: OutboxStore) -> None:
    """send_and_emit smtp_transport 未注入 → ValueError."""
    outbox_id = _insert_pending_entry(store, email_id=1005)
    # D5.6.4 P1: 收窄至 APPROVED,先推 APPROVED(带 last_approved_at_ms 凭据)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(time.time() * 1000),
    )
    adapter = EmailSendAdapter(source="test-send", outbox_store=store)  # 不传 smtp_transport
    with pytest.raises(ValueError, match="smtp_transport 未注入"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


def test_send_and_emit_state_machine_illegal_transition_raises(
    store: OutboxStore,
    smtp_transport: InMemorySmtpTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """send_and_emit 状态机非法转换(并发写导致 row.status 已变)→ SMTPSendIllegalTransitionError.

    模拟: 调用 store.update_status 时 row.status 已被另一 process 改掉(漂移),
    D5.2 OutboxIllegalTransitionError 抛出 → D5.3 包装为 SMTPSendIllegalTransitionError.

    D5.6.4 P1: 入口已收窄至 APPROVED,先推 APPROVED(带 last_approved_at_ms 凭据),
    然后模拟 SENDING→SENT 状态机漂移(并发写推到 SENT 后另一 process 推到 FAILED).
    """
    from my_ai_employee.db.outbox import OutboxIllegalTransitionError

    outbox_id = _insert_pending_entry(store, email_id=1006)
    # 先推 APPROVED(D5.6.4 P1 收窄)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(time.time() * 1000),
    )

    # monkeypatch store.update_status 让它抛漂移异常(模拟并发写)
    def fake_update(*args: object, **kwargs: object) -> object:
        raise OutboxIllegalTransitionError(
            outbox_id=outbox_id,
            from_status="approved",
            to_status="sending",
            actual_status="sent",  # 另一 process 已推到 sent
        )

    monkeypatch.setattr(store, "update_status", fake_update)

    smtp_transport.inject_status = SMTP_SEND_OK
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(SMTPSendIllegalTransitionError, match="状态机非法转换"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


# ===== C.2 EmailSendAdapter.record_send_business_blocked_and_emit(9 tests)=====


def test_record_blocked_recipients_refused(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit reason=recipients_refused → 业务阻断 + CANCELLED."""
    outbox_id = _insert_pending_entry(store, email_id=1100)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.record_send_business_blocked_and_emit(
        outbox_id=outbox_id,
        reason="recipients_refused",
        last_error="550 mailbox not found",
    )
    assert report.send_blocked is True
    assert report.kind == "business_blocked"
    assert report.reason == "recipients_refused"
    assert report.consecutive_send_failures == 0
    # 状态机推进: PENDING_SEND → CANCELLED
    entry = store.by_id(outbox_id)
    assert entry is not None
    assert entry.status == "cancelled"


def test_record_blocked_sender_refused(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit reason=sender_refused → 业务阻断."""
    outbox_id = _insert_pending_entry(store, email_id=1101)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.record_send_business_blocked_and_emit(
        outbox_id=outbox_id,
        reason="sender_refused",
        last_error="550 sender refused",
    )
    assert report.reason == "sender_refused"


def test_record_blocked_data_error(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit reason=data_error → 业务阻断."""
    outbox_id = _insert_pending_entry(store, email_id=1102)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.record_send_business_blocked_and_emit(
        outbox_id=outbox_id,
        reason="data_error",
        last_error="SMTP 4xx data error",
    )
    assert report.reason == "data_error"


# ===== D5.3 业务阻断链路硬收口 — 异常窄化补 3 测试 =====


def test_send_and_emit_smtp_data_error_raises_business_block(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """send_and_emit SMTPDataError(4xx) → SMTPSendRecipientsRefusedError(业务阻断入口).

    D5.3 P2 异常窄化收口:D5.2 锁定版 send_adapter.py:797 用 SMTPException 基类兜底,
    SMTPDataError 会被吞算作技术失败(SMTP_SEND_TRANSPORT_ERROR)。修复:
    显式接 smtplib.SMTPDataError → 业务阻断(4xx DATA 阶段数据错误是永久退信,
    不是瞬态网络问题, 不应重试)。

    真实路径:smtplib.SMTPDataError 在 send_message 阶段由 transport 抛,
    send_and_emit 捕获后包装为 SMTPSendRecipientsRefusedError(reason="data_error")。

    D5.6.4 P1: 收窄至 APPROVED,先推 APPROVED(带 last_approved_at_ms 凭据).
    """
    outbox_id = _insert_pending_entry(store, email_id=1200)
    # D5.6.4 P1: 收窄至 APPROVED,先推 APPROVED(带 last_approved_at_ms 凭据)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(time.time() * 1000),
    )
    smtp_transport.inject_exception = smtplib.SMTPDataError(452, b"Insufficient storage")

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(SMTPSendRecipientsRefusedError, match="SMTP 数据错误"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


def test_send_and_emit_smtp_authentication_error_raises_business_block(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """send_and_emit SMTPAuthenticationError → SMTPSendSenderRefusedError(业务阻断入口).

    D5.3 P3 异常窄化收口:认证失败是永久错(授权码错/过期), 永不重试。
    D5.2 锁定版无 SMTPAuthenticationError 显式 catch, 落入 SMTPException 基类兜底
    被误算为技术失败, 触发错误重试, 浪费调度资源。

    真实路径:smtplib.SMTPAuthenticationError 在 transport.login() 阶段抛,
    send_and_emit 捕获后包装为 SMTPSendSenderRefusedError(reason="sender_refused")。

    D5.6.4 P1: 收窄至 APPROVED,先推 APPROVED(带 last_approved_at_ms 凭据).
    """
    outbox_id = _insert_pending_entry(store, email_id=1201)
    # D5.6.4 P1: 收窄至 APPROVED,先推 APPROVED(带 last_approved_at_ms 凭据)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=int(time.time() * 1000),
    )
    smtp_transport.inject_exception = smtplib.SMTPAuthenticationError(535, b"Authentication failed")

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(SMTPSendSenderRefusedError, match="SMTP 认证失败"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="wrong_authcode_xxx",
            email_message=_make_email_message(),
        )


def test_record_blocked_from_sending_state_pushes_cancelled(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit 从 SENDING 起始态也能推 CANCELLED(D5.3 P1 硬收口).

    真实路径(D5.4 OutboxDispatcher):
        1. send_and_emit 把 entry PENDING_SEND → SENDING
        2. SMTP 在 DATA 阶段抛 SMTPDataError(SMTP 4xx 永久退信)
        3. send_and_emit 抛 SMTPSendRecipientsRefusedError
        4. Dispatcher 捕获业务阻断异常, 调 record_send_business_blocked_and_emit
        5. 此时 entry.status = SENDING(步骤 1 的产物)
        6. record_send_business_blocked_and_emit 必须能推 SENDING → CANCELLED
        7. 否则 ALLOWED_TRANSITIONS 挡死业务阻断链路, entry 永远卡在 SENDING

    D5.3 P1 修复:ALLOWED_TRANSITIONS[OutboxStatus.SENDING] 加 CANCELLED。
    """
    outbox_id = _insert_pending_entry(store, email_id=1202)
    # 1. 推 PENDING_SEND → SENDING(模拟 send_and_emit 第一步)
    store.update_status(outbox_id, "sending", from_status="pending_send")

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    # 2. 业务阻断入口(此时 entry.status = SENDING)
    report = adapter.record_send_business_blocked_and_emit(
        outbox_id=outbox_id,
        reason="data_error",
        last_error="SMTP 4xx in SENDING state",
    )
    assert report.reason == "data_error"
    # 3. 状态机终点:CANCELLED
    final_entry = store.by_id(outbox_id)
    assert final_entry is not None
    assert final_entry.status == "cancelled"


def test_record_blocked_invalid_reason(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit reason 非法 → ValueError(白名单严判)."""
    outbox_id = _insert_pending_entry(store, email_id=1103)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="3 类白名单"):
        adapter.record_send_business_blocked_and_emit(
            outbox_id=outbox_id,
            reason="invalid_reason_xxx",
            last_error="test",
        )


def test_record_blocked_cf_must_be_zero(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit 数据类 cf 必为 0(双层防御 __post_init__).

    业务阻断不计入失败累加器(D4.7.3 v1.0.1 P1-1 范本).
    """
    outbox_id = _insert_pending_entry(store, email_id=1104)
    # 业务阻断走 entry, 内部构造 SendBlockedDecisionReport 时 cf 必为 0
    # 这里通过 __post_init__ 跨字段校验验证: 手动构造一个非法 cf=1 的 report 必抛 ValueError
    with pytest.raises(ValueError, match="consecutive_send_failures 业务阻断必为 0"):
        SendBlockedDecisionReport(
            evaluation=_FakeEvaluation(),  # type: ignore[arg-type]
            event_id=1,
            lane_entry_id="send:test:run1",
            liveness="healthy",  # type: ignore[arg-type]
            last_error="test",
            reason="recipients_refused",
            outbox_id=outbox_id,
            email_id=1104,
            subject="测试邮件主题",
            body="测试邮件正文内容,超过十个字符。",
            tone="FORMAL",
            recipient_email="customer1104@example.com",
            consecutive_send_failures=1,  # 非法: 业务阻断 cf 必为 0
        )


def test_record_blocked_outbox_not_found(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit outbox_id 不存在 → ValueError."""
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="不存在"):
        adapter.record_send_business_blocked_and_emit(
            outbox_id=99999,  # 不存在
            reason="recipients_refused",
            last_error="test",
        )


def test_record_blocked_state_machine_illegal_transition(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit 状态机非法转换 → SMTPSendIllegalTransitionError.

    模拟: 另一 process 已把 outbox 推到 SENT(终态),
    record_send_business_blocked 调 update_status(SENT→CANCELLED) 必败.
    """
    outbox_id = _insert_pending_entry(store, email_id=1105)
    # 推到 SENT(终态)
    store.update_status(outbox_id, "sending", from_status="pending_send")
    store.update_status(outbox_id, "sent", from_status="sending")

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(SMTPSendIllegalTransitionError, match="状态机非法转换"):
        adapter.record_send_business_blocked_and_emit(
            outbox_id=outbox_id,
            reason="recipients_refused",
            last_error="test",
        )


def test_record_blocked_no_outbox_store(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit outbox_store 未注入 → ValueError."""
    outbox_id = _insert_pending_entry(store, email_id=1106)
    adapter = EmailSendAdapter(
        source="test-send",
        smtp_transport=smtp_transport,  # 不传 outbox_store
    )
    with pytest.raises(ValueError, match="outbox_store 未注入"):
        adapter.record_send_business_blocked_and_emit(
            outbox_id=outbox_id,
            reason="recipients_refused",
            last_error="test",
        )


def test_record_blocked_transport_alive_must_be_bool(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_business_blocked_and_emit transport_alive 必须原生 bool."""
    outbox_id = _insert_pending_entry(store, email_id=1107)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="transport_alive 必须是原生 bool"):
        adapter.record_send_business_blocked_and_emit(
            outbox_id=outbox_id,
            reason="recipients_refused",
            last_error="test",
            transport_alive="not_bool",  # type: ignore[arg-type]
        )


# ===== C.3 EmailSendAdapter.record_send_failure_and_emit(9 tests)=====


def test_record_failure_transport_error(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_failure_and_emit error_category=transport_error → 技术失败 + FAILED."""
    outbox_id = _insert_pending_entry(store, email_id=1200)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.record_send_failure_and_emit(
        outbox_id=outbox_id,
        error_category="transport_error",
        last_error="SMTPServerDisconnected",
        consecutive_send_failures=1,
        retry_after_ms=60_000,
    )
    assert report.send_failed is True
    assert report.error_category == "transport_error"
    assert report.consecutive_send_failures == 1
    assert report.retry_after_ms == 60_000
    # 状态机推进: PENDING_SEND → SENDING → FAILED
    entry = store.by_id(outbox_id)
    assert entry is not None
    assert entry.status == "failed"


def test_record_failure_ssl_error(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_failure_and_emit error_category=ssl_error → 技术失败."""
    outbox_id = _insert_pending_entry(store, email_id=1201)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.record_send_failure_and_emit(
        outbox_id=outbox_id,
        error_category="ssl_error",
        last_error="SSLError handshake failed",
    )
    assert report.error_category == "ssl_error"


def test_record_failure_timeout(store: OutboxStore, smtp_transport: InMemorySmtpTransport) -> None:
    """record_send_failure_and_emit error_category=timeout → 技术失败."""
    outbox_id = _insert_pending_entry(store, email_id=1202)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.record_send_failure_and_emit(
        outbox_id=outbox_id,
        error_category="timeout",
        last_error="socket.timeout after 30s",
    )
    assert report.error_category == "timeout"


def test_record_failure_smtp_other(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_failure_and_emit error_category=smtp_other → 兜底技术失败."""
    outbox_id = _insert_pending_entry(store, email_id=1203)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    report = adapter.record_send_failure_and_emit(
        outbox_id=outbox_id,
        error_category="smtp_other",
        last_error="未识别 smtplib 异常",
    )
    assert report.error_category == "smtp_other"


def test_record_failure_invalid_error_category(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_failure_and_emit error_category 非法 → ValueError(白名单严判)."""
    outbox_id = _insert_pending_entry(store, email_id=1204)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="4 类白名单"):
        adapter.record_send_failure_and_emit(
            outbox_id=outbox_id,
            error_category="invalid_category_xxx",
            last_error="test",
        )


def test_record_failure_cf_must_be_positive(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_failure_and_emit consecutive_send_failures 必须 >= 1(技术失败累加器)."""
    outbox_id = _insert_pending_entry(store, email_id=1205)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="consecutive_send_failures 必须是原生 int"):
        adapter.record_send_failure_and_emit(
            outbox_id=outbox_id,
            error_category="transport_error",
            last_error="test",
            consecutive_send_failures=0,  # 非法: 技术失败 cf 必 >= 1
        )


def test_record_failure_retry_after_must_be_non_negative(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_failure_and_emit retry_after_ms 必须 >= 0(D5.5 退避公式联动)."""
    outbox_id = _insert_pending_entry(store, email_id=1206)
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="retry_after_ms 必须是原生 int"):
        adapter.record_send_failure_and_emit(
            outbox_id=outbox_id,
            error_category="transport_error",
            last_error="test",
            retry_after_ms=-1,  # 非法: retry_after_ms 必 >= 0
        )


def test_record_failure_invalid_outbox_state(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """record_send_failure_and_emit outbox 状态不在 SENDING → ValueError.

    模拟: outbox 已被推到 SENT(终态), 不能走技术失败路径(已离开 SENDING 中间态).
    """
    outbox_id = _insert_pending_entry(store, email_id=1207)
    # 推到 SENT
    store.update_status(outbox_id, "sending", from_status="pending_send")
    store.update_status(outbox_id, "sent", from_status="sending")

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    # entry.status="sent", 跳过 4a(PENDING/APPROVED), 进 4b 检查 != SENDING 抛 ValueError
    with pytest.raises(ValueError, match="不在 SENDING"):
        adapter.record_send_failure_and_emit(
            outbox_id=outbox_id,
            error_category="transport_error",
            last_error="test",
        )


def test_record_failure_state_machine_illegal_transition(
    store: OutboxStore,
    smtp_transport: InMemorySmtpTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """record_send_failure_and_emit 状态机非法转换 → SMTPSendIllegalTransitionError.

    模拟: outbox 已在 SENDING 中间态(另一 process 推到), SENDING→FAILED 转换时漂移
    (实际 row.status 已被另一 process 改成 SENT).
    """
    from my_ai_employee.db.outbox import OutboxIllegalTransitionError

    outbox_id = _insert_pending_entry(store, email_id=1208)
    # 推到 SENDING(模拟另一 process)
    store.update_status(outbox_id, "sending", from_status="pending_send")

    # monkeypatch: SENDING→FAILED 时抛漂移
    def fake_update(*args: object, **kwargs: object) -> object:
        # 提取 keyword args
        new_status = kwargs.get("new_status") or (args[1] if len(args) > 1 else None)
        if new_status == "failed":
            raise OutboxIllegalTransitionError(
                outbox_id=outbox_id,
                from_status="sending",
                to_status="failed",
                actual_status="sent",  # 另一 process 已推到 sent
            )
        # 其他走真实方法
        return store.__class__.update_status(store, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "update_status", fake_update)

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(SMTPSendIllegalTransitionError, match="状态机非法转换"):
        adapter.record_send_failure_and_emit(
            outbox_id=outbox_id,
            error_category="transport_error",
            last_error="test",
        )


# ===== D5.6.4 P1 收窄新增 3 测试 =====


def test_send_and_emit_rejects_pending_send(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """D5.6.4 P1 — send_and_emit 收窄: PENDING_SEND 直接调 → ValueError(防绕过审批).

    4th round 检查员反馈:"Adapter 仍可绕过审批 — EmailSendAdapter.send_and_emit() 仍接受 PENDING_SEND"
    修复:send_and_emit 入口严判 entry.status 必须 APPROVED,PENDING_SEND 直接 ValueError 拒收.
    """
    outbox_id = _insert_pending_entry(store, email_id=1300)  # PENDING_SEND
    smtp_transport.inject_status = SMTP_SEND_OK

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )
    with pytest.raises(ValueError, match="D5.6.4 收窄至 APPROVED"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


def test_send_and_emit_requires_approval_provenance(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """D5.6.4 P1 — APPROVED 但 last_approved_at_ms=None → ValueError(防审批凭据漏洞).

    4th round 检查员反馈:"审批凭据可直接伪造 — OutboxStore.insert() 允许调用方直接插入
    status=approved, last_approved_at_ms=任意整数"

    send_and_emit 入口严判:last_approved_at_ms is None → ValueError 拒收,即使 status=APPROVED.
    修复防御:即使 caller 绕过 insert 校验直接传 status=APPROVED, send_and_emit 仍会
    拦截 last_approved_at_ms=None 的非法 APPROVED 状态.
    """
    # 手动构造 APPROVED + last_approved_at_ms=None 的非法状态(模拟绕过 commit 2 修复)
    outbox_id = _insert_pending_entry(store, email_id=1301)
    # 用 monkeypatch 模拟 "APPROVED 但 last_approved_at_ms=None" 状态
    from sqlalchemy import update

    from my_ai_employee.core.outbox import OutboxEntry

    smtp_transport.inject_status = SMTP_SEND_OK
    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )

    # 直接修改 DB:status=APPROVED, last_approved_at_ms=None(模拟漏洞场景)
    with store._session_factory() as session:  # type: ignore[attr-defined]
        session.execute(
            update(OutboxEntry)
            .where(OutboxEntry.id == outbox_id)
            .values(status="approved", last_approved_at_ms=None)
        )
        session.commit()

    with pytest.raises(ValueError, match="last_approved_at_ms=None"):
        adapter.send_and_emit(
            outbox_id=outbox_id,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="test@qq.com",
            smtp_password="test_authcode_16",
            email_message=_make_email_message(),
        )


def test_send_and_emit_latency_ms_non_negative_with_injected_now_ms(
    store: OutboxStore, smtp_transport: InMemorySmtpTransport
) -> None:
    """D5.6.4 P0 — 注入虚拟时钟:now_ms 注入后 latency_ms 必 >= 0(防"时间倒流").

    4th round 检查员反馈:"虚拟 now_ms 比系统时间快 70 秒,send_and_emit() 用真实时间计算结束时间,
    产生负 latency_ms(实测 -699993ms)."

    修复:send_and_emit:900 改 is None 严判(沿 L1071/L1276 范本),now_ms 注入后,
    end_ms 也用注入值,latency_ms = end_ms - start_ms 必 >= 0(测试用相等 now_ms).

    校验链路:
    - start_ms = now_ms(注入)
    - end_ms = now_ms(注入,不再硬编码 int(time.time() * 1000))
    - latency_ms = end_ms - start_ms == 0(注入时间无差)
    """
    outbox_id = _insert_pending_entry(store, email_id=1302)
    store.update_status(
        outbox_id,
        "approved",
        from_status="pending_send",
        last_approved_at_ms=1_700_000_000_000,  # 固定凭据时间
    )
    smtp_transport.inject_status = SMTP_SEND_OK

    adapter = EmailSendAdapter(
        source="test-send",
        outbox_store=store,
        smtp_transport=smtp_transport,
    )

    # 注入固定的虚拟 now_ms
    virtual_now_ms = 1_700_000_001_000  # 比 last_approved_at_ms 晚 1s
    report = adapter.send_and_emit(
        outbox_id=outbox_id,
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_username="test@qq.com",
        smtp_password="test_authcode_16",
        email_message=_make_email_message(),
        now_ms=virtual_now_ms,
    )

    # 关键断言:latency_ms 必 >= 0(防"时间倒流")
    assert report.latency_ms >= 0, (
        f"D5.6.4 P0 修复失败:latency_ms={report.latency_ms} 负值,"
        f"说明 end_ms 还在用真实时间(系统时间 < 虚拟 now_ms)"
    )
    # 进一步断言:latency_ms 必为 0(注入时间无差)
    assert report.latency_ms == 0, (
        f"D5.6.4 P0 修复不完全:latency_ms={report.latency_ms} != 0,"
        f"说明 start_ms/end_ms 时间源不一致"
    )
