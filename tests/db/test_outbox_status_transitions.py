"""D5.2 — Outbox 状态机白名单 + from_status 严判测试(+18 cases)。

承接 D5.2 outbox sending state migration 0005 + ALLOWED_TRANSITIONS 模块级常量
+ OutboxIllegalTransitionError 新异常 + update_status(*, from_status) 必传严判。

7 段测试覆盖(18 cases):
    A. 6 状态枚举扩值(3 tests)
       - SENDING / FAILED 已加入 OutboxStatus
       - _OUTBOX_STATUS_CHOICES 含 6 元素
    B. ALLOWED_TRANSITIONS 白名单结构(4 tests)
       - 6 键完整
       - SENT / CANCELLED 终态空集
       - SENDING 仅可转 SENT / FAILED
       - PENDING_SEND 目标集含 APPROVED(D5.2 vs D5 启动计划文档偏差保留)
    C. update_status from_status 严判(3 tests)
       - 缺 from_status 抛 TypeError
       - from_status 匹配 → 成功
       - from_status 不匹配 → OutboxIllegalTransitionError(状态漂移检测)
    D. 合法转换矩阵(4 tests)
       - PENDING_SEND → SENDING
       - APPROVED → SENDING
       - SENDING → SENT
       - FAILED → PENDING_SEND(重试路径)
    E. 非法转换严判(3 tests)
       - PENDING_SEND → SENT 跳级
       - SENDING → APPROVED 逆向
       - CANCELLED 终态 → 任何状态
    F. OutboxIllegalTransitionError 数据类(1 test)
       - 异常信息含 outbox_id + from/to status

合计 18 cases。

D5.2 vs D5 启动计划文档偏差(报告必标注):
    D5 启动计划 PENDING_SEND → {SENDING, FAILED, CANCELLED}(3 目标)
    D5.2 实际    PENDING_SEND → {SENDING, APPROVED, FAILED, CANCELLED}(4 目标)
    偏差原因:    保留 APPROVED 兼容 D4.8 v1.0.1 test_update_status_pending_to_approved 契约

Fixture 复用 tests/db/test_outbox.py 范本(tmp_db_path + fake_keychain +
db_with_schema + session_factory + store)。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.outbox import (  # noqa: E402
    _OUTBOX_STATUS_CHOICES,
    ALLOWED_TRANSITIONS,
    OutboxStatus,
)
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import (  # noqa: E402
    OutboxIllegalTransitionError,
    OutboxStore,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


# ===== Fixtures(复用 test_outbox.py 范本)====


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """测试用临时 DB 路径(不污染真实 ~/Library/Application Support)。"""
    return tmp_path / "test.db"


@pytest.fixture
def fake_keychain(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """用 in-memory dict[Any, Any] 模拟 Keychain(避免污染真实 macOS Keychain)。"""
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
    """打开 DB + Base.metadata.create_all + yield(测试后自动 close)。"""
    db = Database.open(db_path=tmp_db_path)
    engine = make_sqlalchemy_engine(db)
    # 显式 import 触发 SQLAlchemy 注册到 Base.metadata(否则 FK 找不到目标表)
    from my_ai_employee.core.models import Base
    from my_ai_employee.events import models as _events_models  # noqa: F401

    Base.metadata.create_all(engine)
    yield db
    db.close()


@pytest.fixture
def session_factory(db_with_schema: Database):  # type: ignore[no-untyped-def]
    """返回 SQLAlchemy sessionmaker[Any](绑 SQLCipher engine)。"""
    from sqlalchemy.orm import sessionmaker

    engine = make_sqlalchemy_engine(db_with_schema)
    return sessionmaker[Any](bind=engine)


@pytest.fixture
def store(session_factory) -> OutboxStore:  # type: ignore[no-untyped-def]
    """OutboxStore 实例(注入 session_factory)。"""
    return OutboxStore(session_factory)


# ===== A. 6 状态枚举扩值(3 tests)=====


def test_outbox_status_includes_sending() -> None:
    """OutboxStatus 包含 SENDING 状态(D5.2 新增,沿 B5 解封项)。"""
    assert hasattr(OutboxStatus, "SENDING")
    assert OutboxStatus.SENDING.value == "sending"


def test_outbox_status_includes_failed() -> None:
    """OutboxStatus 包含 FAILED 状态(D5.2 新增,沿 B5 解封项)。"""
    assert hasattr(OutboxStatus, "FAILED")
    assert OutboxStatus.FAILED.value == "failed"


def test_outbox_status_choices_has_6_elements() -> None:
    """_OUTBOX_STATUS_CHOICES 含 6 元素(D5.2 扩 4→6,加 sending + failed)。"""
    assert len(_OUTBOX_STATUS_CHOICES) == 6
    assert "sending" in _OUTBOX_STATUS_CHOICES
    assert "failed" in _OUTBOX_STATUS_CHOICES
    # D4.8 4 状态仍保留
    assert "pending_send" in _OUTBOX_STATUS_CHOICES
    assert "approved" in _OUTBOX_STATUS_CHOICES
    assert "sent" in _OUTBOX_STATUS_CHOICES
    assert "cancelled" in _OUTBOX_STATUS_CHOICES


# ===== B. ALLOWED_TRANSITIONS 白名单结构(4 tests)=====


def test_allowed_transitions_dict_has_6_keys() -> None:
    """ALLOWED_TRANSITIONS 6 状态 × 各自目标集(无遗漏,无冗余)。"""
    assert isinstance(ALLOWED_TRANSITIONS, dict)
    assert len(ALLOWED_TRANSITIONS) == 6
    # 6 状态都作为 key 出现
    for status in OutboxStatus:
        assert status in ALLOWED_TRANSITIONS, f"{status} 不在 ALLOWED_TRANSITIONS"


def test_allowed_transitions_terminal_states_have_empty_frozenset() -> None:
    """SENT / CANCELLED 终态空集(显式 frozenset() 表达,不可转出)。"""
    assert ALLOWED_TRANSITIONS[OutboxStatus.SENT] == frozenset()
    assert ALLOWED_TRANSITIONS[OutboxStatus.CANCELLED] == frozenset()


def test_allowed_transitions_sending_to_sent_failed_cancelled() -> None:
    """SENDING 状态可转 SENT / FAILED / CANCELLED(D5.3 业务阻断链路硬收口)。

    D5.2 锁定版仅 {SENT, FAILED} 2 目标; D5.3 P1 收口加 CANCELLED:
    SMTPRecipientsRefused / SMTPSenderRefused / SMTPDataError / SMTPAuthenticationError
    在 SENDING 中间态触发永久退信 → 业务阻断入口 record_send_business_blocked_and_emit
    必须能推 SENDING → CANCELLED, 否则 ALLOWED_TRANSITIONS 会挡死业务阻断链路。
    """
    sending_targets = ALLOWED_TRANSITIONS[OutboxStatus.SENDING]
    assert sending_targets == frozenset(
        {OutboxStatus.SENT, OutboxStatus.FAILED, OutboxStatus.CANCELLED}
    )


def test_allowed_transitions_pending_send_includes_approved() -> None:
    """PENDING_SEND 目标集含 APPROVED(D5.2 vs D5 启动计划文档偏差,保留 D4.8 契约)。"""
    pending_targets = ALLOWED_TRANSITIONS[OutboxStatus.PENDING_SEND]
    # D5 启动计划文档不含 APPROVED,D5.2 保留以兼容 D4.8 v1.0.1 契约
    assert OutboxStatus.APPROVED in pending_targets
    # D5 启动计划文档含 SENDING / FAILED / CANCELLED
    assert OutboxStatus.SENDING in pending_targets
    assert OutboxStatus.FAILED in pending_targets
    assert OutboxStatus.CANCELLED in pending_targets


# ===== C. update_status from_status 严判(3 tests)=====


def test_update_status_requires_from_status_keyword(store: OutboxStore) -> None:
    """update_status 缺 from_status 抛 TypeError(D5.2 严判必传关键字)。"""
    entry = store.insert(
        email_id=1000,
        subject="from_status 必传测试",
        body="测试 from_status 必传,正文超过十个字符。",
        tone="FORMAL",
        recipient_email="fs@example.com",
    )
    with pytest.raises(TypeError, match="from_status"):
        store.update_status(entry.id, "approved")


def test_update_status_matching_from_status_succeeds(store: OutboxStore) -> None:
    """update_status from_status 匹配 row.status → 成功(PENDING_SEND → APPROVED,D4.8 路径)。"""
    entry = store.insert(
        email_id=1001,
        subject="from_status 匹配测试",
        body="测试 from_status 匹配的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="match@example.com",
    )
    # 入库后 row.status = "pending_send"
    updated = store.update_status(
        entry.id, "approved", from_status="pending_send", last_approved_at_ms=1781355844417
    )
    assert updated.status == "approved"


def test_update_status_mismatched_from_status_raises_illegal_transition(
    store: OutboxStore,
) -> None:
    """update_status from_status 不匹配 → OutboxIllegalTransitionError(状态漂移检测)。"""
    entry = store.insert(
        email_id=1002,
        subject="from_status 漂移测试",
        body="测试 from_status 漂移检测,正文超过十个字符。",
        tone="FORMAL",
        recipient_email="drift@example.com",
    )
    # 故意传错的 from_status(实际 row.status="pending_send",传 "approved")
    with pytest.raises(OutboxIllegalTransitionError, match="状态机漂移"):
        store.update_status(
            entry.id, "cancelled", from_status="approved", last_approved_at_ms=None
        )  # 实际是 pending_send


# ===== D. 合法转换矩阵(4 tests)=====


def test_pending_send_to_sending_allowed(store: OutboxStore) -> None:
    """状态机:PENDING_SEND → SENDING(D5 业务调度器快路径)。"""
    entry = store.insert(
        email_id=1100,
        subject="状态机 - pending_send→sending",
        body="测试 PENDING_SEND → SENDING 的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="ps@example.com",
    )
    updated = store.update_status(
        entry.id, "sending", from_status="pending_send", last_approved_at_ms=None
    )
    assert updated.status == "sending"


def test_approved_to_sending_allowed(store: OutboxStore) -> None:
    """状态机:APPROVED → SENDING(D5 业务调度器显式批准路径)。"""
    entry = store.insert(
        email_id=1101,
        subject="状态机 - approved→sending",
        body="测试 APPROVED → SENDING 的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="as@example.com",
    )
    store.update_status(
        entry.id, "approved", from_status="pending_send", last_approved_at_ms=1781355844417
    )
    updated = store.update_status(
        entry.id, "sending", from_status="approved", last_approved_at_ms=None
    )
    assert updated.status == "sending"


def test_sending_to_sent_allowed(store: OutboxStore) -> None:
    """状态机:SENDING → SENT(D5 SMTP 发送成功)。"""
    entry = store.insert(
        email_id=1102,
        subject="状态机 - sending→sent",
        body="测试 SENDING → SENT 的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="ss@example.com",
    )
    store.update_status(entry.id, "sending", from_status="pending_send", last_approved_at_ms=None)
    updated = store.update_status(entry.id, "sent", from_status="sending", last_approved_at_ms=None)
    assert updated.status == "sent"


def test_sending_to_cancelled_allowed(store: OutboxStore) -> None:
    """状态机:SENDING → CANCELLED(D5.3 业务阻断链路硬收口)。

    真实路径: SMTPRecipientsRefused / SMTPSenderRefused / SMTPDataError /
    SMTPAuthenticationError 在 SENDING 中间态触发永久退信, D5.4 Dispatcher
    捕获后调 record_send_business_blocked_and_emit, 此时 entry.status=SENDING,
    必须能转 CANCELLED(否则白名单挡死业务阻断链路, dangling SENDING 状态)。

    D5.2 锁定版 SENDING 目标集 {SENT, FAILED} 不含 CANCELLED 是 P1 硬阻塞,
    D5.3 P1 收口必须把 CANCELLED 加进 SENDING 目标集。
    """
    entry = store.insert(
        email_id=1104,
        subject="状态机 - sending→cancelled 业务阻断",
        body="测试 SENDING → CANCELLED 业务阻断链路的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="sc@example.com",
    )
    # 模拟 SENDING 中间态
    store.update_status(entry.id, "sending", from_status="pending_send", last_approved_at_ms=None)
    # 永久退信后,业务阻断入口推 CANCELLED
    updated = store.update_status(
        entry.id, "cancelled", from_status="sending", last_approved_at_ms=None
    )
    assert updated.status == "cancelled"


def test_failed_to_pending_send_allowed(store: OutboxStore) -> None:
    """状态机:FAILED → PENDING_SEND(D5 退避重试回路)。"""
    entry = store.insert(
        email_id=1103,
        subject="状态机 - failed→pending_send",
        body="测试 FAILED → PENDING_SEND 重试回路的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="fp@example.com",
    )
    # 模拟发送失败:PENDING_SEND → SENDING → FAILED → PENDING_SEND
    store.update_status(entry.id, "sending", from_status="pending_send", last_approved_at_ms=None)
    store.update_status(entry.id, "failed", from_status="sending", last_approved_at_ms=None)
    updated = store.update_status(
        entry.id, "pending_send", from_status="failed", last_approved_at_ms=None
    )
    assert updated.status == "pending_send"


# ===== E. 非法转换严判(3 tests)=====


def test_pending_send_to_sent_raises_illegal_transition(store: OutboxStore) -> None:
    """状态机:PENDING_SEND → SENT 跳级非法(必须经 SENDING 中间态)。"""
    entry = store.insert(
        email_id=1200,
        subject="非法转换 - pending_send→sent 跳级",
        body="测试 PENDING_SEND → SENT 跳级非法的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="js@example.com",
    )
    with pytest.raises(OutboxIllegalTransitionError, match="状态机非法转换"):
        store.update_status(entry.id, "sent", from_status="pending_send", last_approved_at_ms=None)


def test_sending_to_approved_raises_illegal_transition(store: OutboxStore) -> None:
    """状态机:SENDING → APPROVED 逆向非法(APPROVED 必须在 SENDING 之前)。"""
    entry = store.insert(
        email_id=1201,
        subject="非法转换 - sending→approved 逆向",
        body="测试 SENDING → APPROVED 逆向非法的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="sa@example.com",
    )
    store.update_status(entry.id, "sending", from_status="pending_send", last_approved_at_ms=None)
    with pytest.raises(OutboxIllegalTransitionError, match="状态机非法转换"):
        store.update_status(
            entry.id, "approved", from_status="sending", last_approved_at_ms=1781355844417
        )  # 逆向非法


def test_cancelled_to_anything_raises_illegal_transition(store: OutboxStore) -> None:
    """状态机:CANCELLED 终态 → 任何状态非法(防 cancelled 复活 bug)。"""
    entry = store.insert(
        email_id=1202,
        subject="非法转换 - cancelled 终态",
        body="测试 CANCELLED 终态的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="ct@example.com",
    )
    store.update_status(entry.id, "cancelled", from_status="pending_send", last_approved_at_ms=None)
    # 终态不能转出
    with pytest.raises(OutboxIllegalTransitionError, match="状态机非法转换"):
        store.update_status(
            entry.id, "pending_send", from_status="cancelled", last_approved_at_ms=None
        )  # 复活非法


# ===== F. OutboxIllegalTransitionError 数据类(1 test)=====


def test_outbox_illegal_transition_error_contains_outbox_id(
    store: OutboxStore,
) -> None:
    """OutboxIllegalTransitionError 异常信息含 outbox_id + from/to status(便于 audit)。

    关键:异常信息含的是 entry.id(OutboxEntry.id 自增主键),不是 email_id。
    D5.3 Adapter audit 时用 err.outbox_id 关联 event_metadata。
    """
    entry = store.insert(
        email_id=1300,
        subject="异常信息测试",
        body="测试异常信息含 outbox_id 的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="err@example.com",
    )
    with pytest.raises(OutboxIllegalTransitionError) as exc_info:
        store.update_status(entry.id, "sent", from_status="pending_send", last_approved_at_ms=None)
    err = exc_info.value
    # 异常属性完整(D5.3 Adapter audit 用)
    assert err.outbox_id == entry.id  # entry.id 是 OutboxEntry.id 自增主键
    assert err.from_status == "pending_send"
    assert err.to_status == "sent"
    # 异常信息含 outbox_id(entry.id 而非 email_id)
    assert f"outbox_id={entry.id}" in str(err)
    # 异常信息含 from/to status
    assert "'pending_send'" in str(err)
    assert "'sent'" in str(err)
