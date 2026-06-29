"""D5.6.3 — OutboxDispatcher 拉批审批凭据严判专项测试(+4 cases)。

D5.6.3 P1-1 修复:Dispatcher 拉批前严判 entry.last_approved_at_ms is not None,
防 PENDING_SEND → FAILED → APPROVED → SENT 路径绕过用户审批契约。

测试覆盖(4 cases):
    M1. test_failed_without_approval_provenance_skipped
        FAILED 条目无审批凭据(last_approved_at_ms=None)→ 必 skipped
    M2. test_pending_send_without_approval_provenance_skipped
        业务层 PENDING_SEND → FAILED 路径无审批凭据 → 必 skipped
    M3. test_approved_with_approval_provenance_processed
        APPROVED + 有审批凭据 → 必被发送
    M4. test_pending_send_with_approval_provenance_also_skipped
        PENDING_SEND 即使有审批凭据 → 仍 skipped(D5.6.2 P1.2 拉批契约)

设计原则(沿 D4.7.3 v1.0.6 范本 + D5.6.2 教训):
- 复用 test_outbox_dispatcher_approval.py 范本 fixtures
- 通过 _insert_entry 显式控 last_approved_at_ms
- 严判 last_approved_at_ms is None 必触发 skipped,不是 technical_failed
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.outbox import OutboxStatus  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import OutboxStore  # noqa: E402
from my_ai_employee.policy.heartbeat import Heartbeat  # noqa: E402
from my_ai_employee.policy.send_adapter import EmailSendAdapter  # noqa: E402
from my_ai_employee.scheduler.outbox_dispatcher import OutboxDispatcher  # noqa: E402

# ===== Fixtures(沿 test_outbox_dispatcher_approval.py 范本)=====


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
        source="test-dispatcher-provenance",
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


def _insert_entry_raw(
    store: OutboxStore,
    *,
    email_id: int,
    status: str,
    last_approved_at_ms: int | None = None,
) -> int:
    """原样插入 outbox 条目(D5.6.4 P1:insert 强制 PENDING_SEND,目标状态走 update_status).

    用于测试边界 — 模拟"特定状态无审批凭据"等场景(commit 2 后 caller 不能直接 insert APPROVED).
    注意:本 helper **不**自动填 last_approved_at_ms,完全由 caller 控制(边界测试需要 None).

    Args:
        store: OutboxStore
        email_id: 关联 emails.id
        status: 目标状态
        last_approved_at_ms: D5.6.3 P1-1 审批凭据(完全 caller 控制)
    """
    # D5.6.4 P1:先 insert 默认 PENDING_SEND
    entry = store.insert(
        email_id=email_id,
        subject="测试邮件主题",
        body="测试邮件正文内容,超过十个字符。",
        tone="FORMAL",
        recipient_email=f"customer{email_id}@example.com",
    )
    assert entry.id is not None
    if status == OutboxStatus.PENDING_SEND.value:
        return cast(int, entry.id)
    # D5.6.3 P1-1:FAILED 状态需要 last_approved_at_ms 走 APPROVED 中转保留
    if status == OutboxStatus.FAILED.value:
        if last_approved_at_ms is not None:
            # 先经 APPROVED(写入审批凭据)+ 再 FAILED(走 APPROVED → FAILED 白名单,保留凭据)
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
        # caller 显式 None 走"用户取消"场景: PENDING_SEND → FAILED 无审批
        store.update_status(
            entry.id,
            OutboxStatus.FAILED.value,
            from_status=OutboxStatus.PENDING_SEND.value,
            last_approved_at_ms=None,
        )
        return cast(int, entry.id)
    # APPROVED:走 PENDING_SEND → APPROVED(必传 last_approved_at_ms,D5.6.3 P1-1)
    store.update_status(
        entry.id,
        status,
        from_status=OutboxStatus.PENDING_SEND.value,
        last_approved_at_ms=last_approved_at_ms,
    )
    return cast(int, entry.id)


# ===== M. D5.6.3 P1-1 拉批审批凭据严判专项测试(4 cases)=====


def test_failed_without_approval_provenance_skipped(
    dispatcher: OutboxDispatcher,
) -> None:
    """D5.6.3 P1-1:FAILED 无审批凭据(last_approved_at_ms=None)→ 必 skipped。

    业务背景:状态机白名单允许 PENDING_SEND → FAILED → APPROVED → SENT,
    业务层可以走 PENDING_SEND → FAILED 路径(用户取消等场景),但
    last_approved_at_ms 仍为 None,这种 FAILED 必须被 dispatcher 拒收,
    否则"未审批"邮件可绕过审批契约。
    """
    store = dispatcher._outbox_store  # noqa: SLF001
    assert store is not None
    # 模拟业务层: PENDING_SEND → FAILED(无审批,last_approved_at_ms=None)
    failed_id = _insert_entry_raw(
        store, email_id=1, status=OutboxStatus.FAILED.value, last_approved_at_ms=None
    )

    result = dispatcher.run_once()
    # 关键: 无审批凭据必 skipped,不是 sent,也不是 technical_failed
    assert result.sent == 0, (
        f"D5.6.3 P1-1:FAILED 无审批凭据必 skipped,实际 sent={result.sent}(绕过尝试!)"
    )
    assert result.skipped == 1, (
        f"D5.6.3 P1-1:FAILED 无审批凭据必 skipped,实际 skipped={result.skipped}"
    )
    assert result.technical_failed == 0, (
        f"D5.6.3 P1-1:FAILED 无审批凭据不应被当 technical_failed,实际 {result.technical_failed}"
    )

    # 验证 FAILED 状态保持(没被推到 SENT/FAILED 之外的任何状态)
    entry = store.by_id(failed_id)
    assert entry is not None
    assert entry.status == OutboxStatus.FAILED.value, (
        f"D5.6.3 P1-1:无审批凭据 FAILED 必保持 FAILED 状态,实际 {entry.status!r}"
    )


def test_pending_send_without_approval_provenance_skipped(
    dispatcher: OutboxDispatcher,
) -> None:
    """D5.6.3 P1-1 兼容性验证:D5.6.2 P1.2 已禁止 PENDING_SEND 拉批,本测试守门。

    即使 PENDING_SEND 条目有审批凭据(测试用,真实业务不会),Dispatcher
    仍不应拉批(D5.6.2 P1.2 拉批契约),只 APPROVED/FAILED 进 dispatcher。
    """
    store = dispatcher._outbox_store  # noqa: SLF001
    assert store is not None
    now_ms = int(time.time() * 1000)
    # PENDING_SEND + 有审批凭据(异常场景,真实不会)
    pending_id = _insert_entry_raw(
        store,
        email_id=1,
        status=OutboxStatus.PENDING_SEND.value,
        last_approved_at_ms=now_ms,
    )

    result = dispatcher.run_once()
    assert result.sent == 0, f"D5.6.2 P1.2:PENDING_SEND 永不被拉批,实际 sent={result.sent}"
    assert result.total_picked == 0, (
        f"D5.6.2 P1.2:PENDING_SEND 不入批,实际 total_picked={result.total_picked}"
    )

    # 验证 PENDING_SEND 状态保持
    entry = store.by_id(pending_id)
    assert entry is not None
    assert entry.status == OutboxStatus.PENDING_SEND.value, (
        f"D5.6.2 P1.2:PENDING_SEND 必保持 PENDING_SEND,实际 {entry.status!r}"
    )


def test_approved_with_approval_provenance_processed(
    dispatcher: OutboxDispatcher,
) -> None:
    """D5.6.3 P1-1 正面验证:APPROVED + 有审批凭据 → 必被发送。

    这是 commit 1 修复后的正常路径(用户审批 → dispatcher 消费 → SENT)。
    """
    store = dispatcher._outbox_store  # noqa: SLF001
    assert store is not None
    now_ms = int(time.time() * 1000)
    approved_id = _insert_entry_raw(
        store,
        email_id=1,
        status=OutboxStatus.APPROVED.value,
        last_approved_at_ms=now_ms,
    )

    result = dispatcher.run_once()
    assert result.sent == 1, f"D5.6.3 P1-1:APPROVED + 有审批凭据必被发送,实际 sent={result.sent}"

    # 验证 APPROVED → SENT
    entry = store.by_id(approved_id)
    assert entry is not None
    assert entry.status == OutboxStatus.SENT.value, (
        f"D5.6.3 P1-1:APPROVED 应变 SENT,实际 {entry.status!r}"
    )


def test_failed_with_approval_provenance_retries(
    dispatcher: OutboxDispatcher,
) -> None:
    """D5.6.3 P1-1:FAILED + 有审批凭据 → 退避重试走 FAILED → APPROVED → SENT。

    业务背景:这是 D5.6.2 P1.2 + D5.6.3 P1-1 的合流:
    - D5.6.2:FAILED → APPROVED 状态机白名单扩(保留原审批标记)
    - D5.6.3:必须有审批凭据才能走 FAILED → APPROVED → SENT 路径
    - 真实流程:用户审批 → APPROVED → 发送失败 → FAILED(凭据保留)→
      退避结束 → dispatcher 拉批 → FAILED → APPROVED(凭据透传)→ SENT
    """
    store = dispatcher._outbox_store  # noqa: SLF001
    assert store is not None
    now_ms = int(time.time() * 1000)
    failed_id = _insert_entry_raw(
        store,
        email_id=1,
        status=OutboxStatus.FAILED.value,
        last_approved_at_ms=now_ms,
    )

    result = dispatcher.run_once()
    assert result.sent == 1, (
        f"D5.6.3 P1-1:FAILED + 有审批凭据退避重试必被发送,实际 sent={result.sent}"
    )

    # 验证 FAILED → SENT(走 FAILED → APPROVED → SENT 路径)
    entry = store.by_id(failed_id)
    assert entry is not None
    assert entry.status == OutboxStatus.SENT.value, (
        f"D5.6.3 P1-1:FAILED 重试后应变 SENT,实际 {entry.status!r}"
    )
