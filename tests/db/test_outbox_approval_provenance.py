"""D5.6.3 — outbox last_approved_at_ms 审批凭据专项测试(+6 cases)。

D5.6.3 P1-1 修复:引入 last_approved_at_ms 字段,作为"条目曾被显式审批过"的
业务凭据,OutboxDispatcher 拉批前严判 is not None,防 PENDING_SEND → FAILED
→ APPROVED → SENT 路径绕过用户审批契约。

测试覆盖(6 cases):
    A. 字段必传规则(2 tests)
       1. test_approved_must_pass_last_approved_at_ms_int
       2. test_approved_rejects_non_int_type
    B. 非 APPROVED 状态不传(2 tests)
       3. test_non_approved_must_pass_none_explicitly
       4. test_non_approved_preserves_existing_last_approved_at_ms
    C. 字段保留范本(2 tests)
       5. test_sending_to_sent_preserves_last_approved_at_ms
       6. test_sending_to_failed_preserves_last_approved_at_ms

设计原则(沿 D4.7.3 v1.0.6 范本 + D5.6.2 教训):
- 工厂层(OutboxStore.update_status) + 数据类(__post_init__)双层防御
- 严判 type() is int(非 bool) + >= 0
- 严判 type() is None 拒 list/dict/set 等非 None 类型
- 字段名硬区分:last_approved_at_ms(审批) vs last_failed_at_ms(技术失败)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import OutboxStore  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator


# ===== Fixtures(复用 tests/db/test_outbox.py 范本)=====


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
def db_with_schema(tmp_db_path: Path, fake_keychain: dict) -> Iterator[Database]:
    db = Database.open(db_path=tmp_db_path)
    engine = make_sqlalchemy_engine(db)
    from my_ai_employee.core.models import Base
    from my_ai_employee.events import models as _events_models  # noqa: F401

    Base.metadata.create_all(engine)
    yield db
    db.close()


@pytest.fixture
def session_factory(db_with_schema: Database):  # type: ignore[no-untyped-def]
    from sqlalchemy.orm import sessionmaker

    engine = make_sqlalchemy_engine(db_with_schema)
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory) -> OutboxStore:  # type: ignore[no-untyped-def]
    return OutboxStore(session_factory)


def _insert_pending(store: OutboxStore, *, email_id: int) -> int:
    """插入一条 PENDING_SEND 状态的 outbox 条目。"""
    entry = store.insert(
        email_id=email_id,
        subject="测试邮件主题",
        body="测试邮件正文内容,超过十个字符。",
        tone="FORMAL",
        recipient_email=f"customer{email_id}@example.com",
    )
    assert entry.id is not None
    return entry.id


# ===== A. APPROVED 必传规则(2 tests)=====


def test_approved_must_pass_last_approved_at_ms_int(store: OutboxStore) -> None:
    """D5.6.3 P1-1:update_status(new_status=APPROVED) 必传 int(last_approved_at_ms)。

    严判 type() is int(非 bool) + >= 0,Unix epoch ms。
    """
    outbox_id = _insert_pending(store, email_id=1)
    # 正常路径:int(Unix epoch ms)
    now_ms = int(time.time() * 1000)
    updated = store.update_status(
        outbox_id, "approved", from_status="pending_send", last_approved_at_ms=now_ms
    )
    assert updated.last_approved_at_ms == now_ms
    assert updated.status == "approved"


def test_approved_rejects_non_int_type(store: OutboxStore) -> None:
    """D5.6.3 P1-1:APPROVED 时 last_approved_at_ms 拒 bool / str / list / dict 等非 int。"""
    outbox_id = _insert_pending(store, email_id=2)
    # bool 子类是 int 子类陷阱:D4.7.3 v1.0.5 P2-2 范本, type() is int 不用 isinstance
    with pytest.raises(ValueError, match="原生 int"):
        store.update_status(
            outbox_id,
            "approved",
            from_status="pending_send",
            last_approved_at_ms=True,  # type: ignore[arg-type]
        )
    # str 拒收
    with pytest.raises(ValueError, match="原生 int"):
        store.update_status(
            outbox_id,
            "approved",
            from_status="pending_send",
            last_approved_at_ms="1234567890",  # type: ignore[arg-type]
        )
    # 负数拒收
    with pytest.raises(ValueError, match="原生 int"):
        store.update_status(
            outbox_id, "approved", from_status="pending_send", last_approved_at_ms=-1
        )


# ===== B. 非 APPROVED 状态必传 None(2 tests)=====


def test_non_approved_must_pass_none_explicitly(store: OutboxStore) -> None:
    """D5.6.3 P1-1:非 APPROVED 转换 last_approved_at_ms 必传 None(显式 None 拒误传)。"""
    outbox_id = _insert_pending(store, email_id=3)
    # APPROVED 先传 now_ms
    now_ms = int(time.time() * 1000)
    store.update_status(
        outbox_id, "approved", from_status="pending_send", last_approved_at_ms=now_ms
    )
    # 之后转 SENDING,last_approved_at_ms 必传 None(显式 None,不允许误传 int 覆盖原值)
    with pytest.raises(ValueError, match="必传 None"):
        store.update_status(
            outbox_id, "sending", from_status="approved", last_approved_at_ms=now_ms
        )


def test_non_approved_preserves_existing_last_approved_at_ms(
    store: OutboxStore,
) -> None:
    """D5.6.3 P1-1:非 APPROVED 转换显式传 None → 原 last_approved_at_ms 保留(不动)。

    业务背景:D5.6.2 FAILED → APPROVED 重试回路由 dispatcher 触发,沿 D5.6.2 P1.2
    重试保留原审批时间戳设计。本测试验证 OutboxStore.update_status 严格遵守
    "非 APPROVED 必传 None,row.last_approved_at_ms 不动" 契约。
    """
    outbox_id = _insert_pending(store, email_id=4)
    # 先 PENDING_SEND → SENDING → FAILED,模拟退避重试链路
    store.update_status(
        outbox_id,
        "sending",
        from_status="pending_send",
        last_approved_at_ms=None,  # 非 APPROVED 必传 None
    )
    store.update_status(
        outbox_id,
        "failed",
        from_status="sending",
        last_approved_at_ms=None,
    )
    # 退避结束,FAILED → APPROVED(回填原审批时间戳)
    now_ms = int(time.time() * 1000)
    updated = store.update_status(
        outbox_id, "approved", from_status="failed", last_approved_at_ms=now_ms
    )
    assert updated.last_approved_at_ms == now_ms
    assert updated.status == "approved"


# ===== C. 字段保留范本(2 tests)=====


def test_sending_to_sent_preserves_last_approved_at_ms(store: OutboxStore) -> None:
    """D5.6.3 P1-1:SENDING → SENT 时 last_approved_at_ms 保留(不动,沿 D4.7.3 教训)。

    业务背景:审批时间戳是"曾被审批过"的凭据,SMTP 发送成功不应该清掉这个标记
    (否则重试时失去审批凭据,陷入"重新审批"死循环)。
    """
    outbox_id = _insert_pending(store, email_id=5)
    now_ms = int(time.time() * 1000)
    # PENDING_SEND → APPROVED 写入 last_approved_at_ms
    store.update_status(
        outbox_id, "approved", from_status="pending_send", last_approved_at_ms=now_ms
    )
    # APPROVED → SENDING 保留(传 None,不动 row)
    store.update_status(outbox_id, "sending", from_status="approved", last_approved_at_ms=None)
    # SENDING → SENT 保留(传 None,不动 row)
    updated = store.update_status(
        outbox_id, "sent", from_status="sending", last_approved_at_ms=None
    )
    assert (
        updated.last_approved_at_ms == now_ms
    ), f"D5.6.3 P1-1:SENDING → SENT 必须保留原 last_approved_at_ms,实际 {updated.last_approved_at_ms!r}"


def test_sending_to_failed_preserves_last_approved_at_ms(store: OutboxStore) -> None:
    """D5.6.3 P1-1:SENDING → FAILED 时 last_approved_at_ms 保留(不动,失败重试仍可走 FAILED → APPROVED)。"""
    outbox_id = _insert_pending(store, email_id=6)
    now_ms = int(time.time() * 1000)
    # PENDING_SEND → APPROVED 写入
    store.update_status(
        outbox_id, "approved", from_status="pending_send", last_approved_at_ms=now_ms
    )
    # APPROVED → SENDING 保留
    store.update_status(outbox_id, "sending", from_status="approved", last_approved_at_ms=None)
    # SENDING → FAILED 保留(退避重试凭据保留)
    updated = store.update_status(
        outbox_id, "failed", from_status="sending", last_approved_at_ms=None
    )
    assert (
        updated.last_approved_at_ms == now_ms
    ), f"D5.6.3 P1-1:SENDING → FAILED 必须保留原 last_approved_at_ms,实际 {updated.last_approved_at_ms!r}"
    assert updated.status == "failed"
