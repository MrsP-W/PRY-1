"""D5.6.2 — OutboxDispatcher 审批契约测试(+3 cases)。

D5.6.1 检查员反馈 P1.2:Dispatcher 同时消费 PENDING_SEND/APPROVED/FAILED,
未审批邮件可绕过用户审批直接发送。

D5.6.2 修复:
    - Dispatcher 拉批只消费 APPROVED + FAILED(不再拉 PENDING_SEND)
    - FAILED 退避重试通过 FAILED → APPROVED 状态机白名单保留原审批标记
    - From 地址用 smtp_username(已认证邮箱),不再硬编码 .test.local

测试覆盖(3 cases):
    L1. test_dispatcher_only_consumes_approved   — 拉批只取 APPROVED 状态
    L2. test_dispatcher_skips_pending_send      — PENDING_SEND 必不被拉批
    L3. test_from_address_uses_smtp_username     — From 用 smtp_username(已认证邮箱)

设计原则(沿 D4.7.3 v1.0.6 范本 + D5.5.4/5 教训):
    - 复用 test_outbox_dispatcher.py 范本 fixtures (store / adapter / heartbeat / dispatcher)
    - 通过 _insert_entry 控状态
    - 严判 type + 状态字段值(防止 PENDING_SEND 蒙混过关)
"""

from __future__ import annotations

from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

import pytest

from my_ai_employee.core import keychain
from my_ai_employee.core.db import Database
from my_ai_employee.core.models import Base
from my_ai_employee.core.outbox import OutboxStatus
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine
from my_ai_employee.db.outbox import OutboxStore
from my_ai_employee.policy.heartbeat import Heartbeat
from my_ai_employee.policy.send_adapter import EmailSendAdapter
from my_ai_employee.scheduler.outbox_dispatcher import OutboxDispatcher

# ===== Fixtures(沿 test_outbox_dispatcher.py 范本)=====


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def fake_keychain(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
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
def db_with_schema(tmp_db_path: Path, fake_keychain: dict[Any, Any]) -> Iterator[Database]:
    db = Database.open(db_path=tmp_db_path)
    engine = make_sqlalchemy_engine(db)
    from my_ai_employee.events import models as _events_models  # noqa: F401

    Base.metadata.create_all(engine)
    yield db
    db.close()


@pytest.fixture
def session_factory(db_with_schema: Database):  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import sessionmaker

    engine = make_sqlalchemy_engine(db_with_schema)
    return sessionmaker[Any](bind=engine)


@pytest.fixture
def store(session_factory) -> OutboxStore:  # type: ignore[no-untyped-def]
    return OutboxStore(session_factory)


@pytest.fixture
def adapter(store: OutboxStore) -> EmailSendAdapter:
    from my_ai_employee.connectors.smtp import InMemorySmtpTransport

    return EmailSendAdapter(
        outbox_store=store,
        source="test-dispatcher-approval",
        smtp_transport=InMemorySmtpTransport(),
    )


@pytest.fixture
def heartbeat() -> Heartbeat:
    return Heartbeat(idle_threshold_ms=30_000)


@pytest.fixture
def dispatcher(
    store: OutboxStore,
    adapter: EmailSendAdapter,
    heartbeat: Heartbeat,
) -> OutboxDispatcher:
    """D5.6.2:smtp_username 用真实邮箱格式(不再 .test.local 占位)。"""
    return OutboxDispatcher(
        source="test-dispatcher",
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_username="real_user@qq.com",
        smtp_password="real-test-password",
        send_adapter=adapter,
        outbox_store=store,
        heartbeat=heartbeat,
        batch_size=10,
    )


def _insert_entry(
    store: OutboxStore,
    *,
    email_id: int,
    status: str,
    priority: str = "normal",
    last_approved_at_ms: int | None = None,  # D5.6.3 P1-1:仅 APPROVED 必传审批凭据
) -> int:
    # D5.6.3 P1-1:测试时为 APPROVED/FAILED 条目模拟"已审批"状态(caller 显式 None 才走"无审批")
    if last_approved_at_ms is None and status in (
        OutboxStatus.APPROVED.value,
        OutboxStatus.FAILED.value,
    ):
        import time as _time

        last_approved_at_ms = int(_time.time() * 1000)
    # D5.6.4 P1:insert 强制 PENDING_SEND + 不接受 last_approved_at_ms,先 insert 再 update_status
    entry = store.insert(
        email_id=email_id,
        subject="测试邮件主题",
        body="测试邮件正文内容,超过十个字符。",
        tone="FORMAL",
        recipient_email=f"customer{email_id}@example.com",
        priority=priority,
    )
    assert entry.id is not None  # noqa: S101
    if status == OutboxStatus.PENDING_SEND.value:
        return cast(int, entry.id)
    # D5.6.3 P1-1:FAILED 也需 last_approved_at_ms(防绕过重试),先经 APPROVED 中转
    if status == OutboxStatus.FAILED.value:
        store.update_status(
            entry.id,
            OutboxStatus.APPROVED.value,
            from_status=OutboxStatus.PENDING_SEND.value,
            last_approved_at_ms=last_approved_at_ms,
        )
        store.update_status(
            entry.id,
            OutboxStatus.FAILED.value,
            from_status=OutboxStatus.APPROVED.value,
            last_approved_at_ms=None,
        )
        return cast(int, entry.id)
    # APPROVED:走 PENDING_SEND → APPROVED
    store.update_status(
        entry.id,
        status,
        from_status=OutboxStatus.PENDING_SEND.value,
        last_approved_at_ms=last_approved_at_ms,
    )
    return cast(int, entry.id)


# ===== L. D5.6.2 P1.2 审批契约修复专项测试 =====


def test_dispatcher_only_consumes_approved(dispatcher: OutboxDispatcher) -> None:
    """D5.6.2 P1.2:Dispatcher 拉批只消费 APPROVED + FAILED 状态(PENDING_SEND 必不被拉)。

    准备 1 封 APPROVED + 1 封 PENDING_SEND + 1 封 FAILED(退避已过),
    期望:run_once 后 APPROVED + FAILED 都变 SENT(PENDING_SEND 仍保持 PENDING_SEND)。
    """
    store = dispatcher._outbox_store  # noqa: SLF001 — 测试需要直接访问 fixture store
    assert store is not None, "D5.6.2:dispatcher._outbox_store 必非 None(fixture 已注入)"
    approved_id = _insert_entry(store, email_id=1, status=OutboxStatus.APPROVED.value)
    pending_id = _insert_entry(store, email_id=2, status=OutboxStatus.PENDING_SEND.value)
    failed_id = _insert_entry(store, email_id=3, status=OutboxStatus.FAILED.value)

    result = dispatcher.run_once()
    # APPROVED 直接发 + FAILED 退避解锁后发(沿 D5.6.2 P1.2 设计)
    assert result.sent == 2, f"D5.6.2:APPROVED + FAILED 必被发送,实际 sent={result.sent}"
    # PENDING_SEND 必不被拉批
    assert result.skipped == 0, (
        f"D5.6.2:本场景 PENDING_SEND 不入批不计数,实际 skipped={result.skipped}"
    )

    # 验证 PENDING_SEND 状态保持
    pending_entry = store.by_id(pending_id)
    assert pending_entry is not None
    assert pending_entry.status == OutboxStatus.PENDING_SEND.value, (
        f"D5.6.2 P1.2:Dispatcher 必不消费 PENDING_SEND,实际状态 {pending_entry.status!r}"
    )
    # 验证 APPROVED 已变 SENT
    approved_entry = store.by_id(approved_id)
    assert approved_entry is not None
    assert approved_entry.status == OutboxStatus.SENT.value, (
        f"D5.6.2:APPROVED 必被发送变 SENT,实际 {approved_entry.status!r}"
    )
    # 验证 FAILED 退避后变 SENT(解锁 → APPROVED → SENT)
    failed_entry = store.by_id(failed_id)
    assert failed_entry is not None
    assert failed_entry.status == OutboxStatus.SENT.value, (
        f"D5.6.2:FAILED 退避后必被处理变 SENT,实际 {failed_entry.status!r}"
    )


def test_dispatcher_skips_pending_send(dispatcher: OutboxDispatcher) -> None:
    """D5.6.2 P1.2:Dispatcher 拉批明确不拉 PENDING_SEND(用户审批契约硬保障)。

    准备 5 封 PENDING_SEND(全未审批),期望:0 发送,5 仍 PENDING_SEND。
    """
    store = dispatcher._outbox_store  # noqa: SLF001
    assert store is not None, "D5.6.2:dispatcher._outbox_store 必非 None(fixture 已注入)"
    pending_ids = [
        _insert_entry(store, email_id=i + 1, status=OutboxStatus.PENDING_SEND.value)
        for i in range(5)
    ]

    result = dispatcher.run_once()
    assert result.sent == 0, f"D5.6.2 P1.2:PENDING_SEND 必不被发送,实际 sent={result.sent}"
    assert result.total_picked == 0, (
        f"D5.6.2 P1.2:PENDING_SEND 必不被拉批,实际 total_picked={result.total_picked}"
    )

    # 验证 5 封全保持 PENDING_SEND 状态
    for pid in pending_ids:
        entry = store.by_id(pid)
        assert entry is not None
        assert entry.status == OutboxStatus.PENDING_SEND.value, (
            f"D5.6.2 P1.2:outbox_id={pid} 必保持 PENDING_SEND,实际 {entry.status!r}"
        )


def test_from_address_uses_smtp_username(dispatcher: OutboxDispatcher) -> None:
    """D5.6.2 P1.1:From 地址必须用 smtp_username(已认证邮箱),不再 .test.local。

    验证 Dispatcher 构造 EmailMessage 时 msg['From'] = self._smtp_username。
    """
    # 直接验证 Dispatcher 内部字段
    assert dispatcher._smtp_username == "real_user@qq.com", (
        f"D5.6.2 P1.1:smtp_username 必为 'real_user@qq.com',实际 {dispatcher._smtp_username!r}"
    )

    # 构造 EmailMessage 验证 From 字段(沿 D5.5.5 范本,直接走 dispatcher._build_message 不可见
    # 所以通过准备 1 封 APPROVED 触发 run_once,捕获 adapter 看到的 email_message)
    store = dispatcher._outbox_store  # noqa: SLF001
    assert store is not None, "D5.6.2:dispatcher._outbox_store 必非 None(fixture 已注入)"
    approved_id = _insert_entry(store, email_id=100, status=OutboxStatus.APPROVED.value)

    # 模拟 send_and_emit 捕获 email_message
    captured_messages: list[EmailMessage] = []

    def capture_send(*args, **kwargs):  # type: ignore[no-untyped-def]
        email_message = kwargs.get("email_message")
        if email_message is not None:
            captured_messages.append(email_message)
        # 调真实实现完成状态机推进
        # D5.6.2 修复:用 SendDecisionReport 真实字段(13 字段透传)
        from my_ai_employee.policy.heartbeat import Liveness  # noqa: PLC0415
        from my_ai_employee.policy.policy_engine import PolicyEvaluation  # noqa: PLC0415
        from my_ai_employee.policy.send_adapter import SendDecisionReport

        # 构造最小可用的 PolicyEvaluation mock(实际值 dispatcher 不会校验)
        mock_eval = PolicyEvaluation(status="succeeded")
        return SendDecisionReport(
            evaluation=mock_eval,
            event_id=None,
            lane_entry_id="test-lane",
            liveness=Liveness.HEALTHY,
            outbox_id=approved_id,
            email_id=100,
            subject="测试邮件主题",
            body="测试邮件正文内容,超过十个字符。",
            tone="FORMAL",
            recipient_email="customer100@example.com",
            priority="NORMAL",
            subject_length=6,
            body_length=14,
            latency_ms=10,
            smtp_code=250,
            send_succeeded=True,
        )

    send_adapter = dispatcher._send_adapter
    assert send_adapter is not None, "D5.6.2:dispatcher._send_adapter 必非 None(fixture 已注入)"
    send_adapter.send_and_emit = capture_send

    dispatcher.run_once()

    assert len(captured_messages) == 1, (
        f"D5.6.2 P1.1:应捕获 1 个 EmailMessage,实际 {len(captured_messages)}"
    )
    msg = captured_messages[0]
    from_addr = msg.get("From", "")
    assert from_addr == "real_user@qq.com", (
        f"D5.6.2 P1.1:From 必为 smtp_username='real_user@qq.com',实际 {from_addr!r}"
    )
    assert "@test.local" not in from_addr, f"D5.6.2 P1.1:From 必不含 .test.local,实际 {from_addr!r}"
