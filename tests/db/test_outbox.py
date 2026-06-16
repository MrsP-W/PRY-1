"""D4.8 + D5.2 — OutboxStore + OutboxEntry ORM 测试(35 tests + 兼容性修订)。

承接 D4.8.1 outbox migration 0004(11 字段 + UNIQUE + 2 索引 + 2 FK)
+ D4.8.2 OutboxEntry ORM(11 字段 + 3 个 StrEnum)
+ D4.8.3 OutboxStore(4 公共方法 + IntegrityError 窄化 + OutboxEmailDuplicateError)
+ D5.2 outbox sending state migration 0005(OutboxStatus 4→6 + ALLOWED_TRANSITIONS
  + update_status(*, from_status) 必传严判 + OutboxIllegalTransitionError)

D5.2 兼容性修订(本文件):
    - test_outbox_status_has_4_states → test_outbox_status_has_6_states(加 SENDING + FAILED 断言)
    - _OUTBOX_STATUS_CHOICES 4 元素 → 6 元素(加 sending + failed)
    - 4 个 update_status 测试加 from_status 关键字(沿 D5.2 新签名)
    - test_normalize_status_rejects_invalid_value 字面量 4 选 1 → 6 选 1

7 段测试覆盖:
    1. 3 个 StrEnum 枚举值与 frozenset 选择(6 tests)
    2. OutboxEntry ORM 模型(8 tests)
    3. OutboxStore.insert 6 字段透传(6 tests)
    4. UNIQUE 冲突 → OutboxEmailDuplicateError(3 tests)
    5. by_email_id / by_id / by_status / by_priority 查询(5 tests)
    6. update_status 状态机(4 tests,D5.2 from_status 必传)
    7. _normalize 严判范本(3 tests)
合计 35 tests(D5.2 兼容性修订,数量不变)。

D3.3.3 教训应用:
    - UNIQUE 冲突严格区分业务阻断 vs 技术失败(OperationalError 透传)
    - 业务层严判放 OutboxStore._normalize(type 严判在 hash 前)

Fixture 复用 tests/core/test_models.py 范本(tmp_db_path + fake_keychain +
db_with_schema + session_factory)。
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.outbox import (  # noqa: E402
    _OUTBOX_PRIORITY_CHOICES,
    _OUTBOX_STATUS_CHOICES,
    _OUTBOX_TONE_CHOICES,
    OutboxEntry,
    OutboxPriority,
    OutboxStatus,
    OutboxTone,
)
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import OutboxEmailDuplicateError, OutboxStore  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator


# ===== Fixtures(复用 test_models.py 范本)=====


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """测试用临时 DB 路径(不污染真实 ~/Library/Application Support)。"""
    return tmp_path / "test.db"


@pytest.fixture
def fake_keychain(monkeypatch):
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
    # 显式 import 触发 SQLAlchemy 注册到 Base.metadata(否则 FK 找不到目标表)
    # events 表在 events/models.py,outbox FK → events.id 必须先 import
    from my_ai_employee.core.models import Base
    from my_ai_employee.events import models as _events_models  # noqa: F401

    Base.metadata.create_all(engine)
    yield db
    db.close()


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


# ===== 1. 3 个 StrEnum 枚举值与 frozenset 选择(6 tests)=====


def test_outbox_status_has_6_states() -> None:
    """OutboxStatus 6 状态枚举值(D5.2 扩 4→6,加 SENDING + FAILED,B5 解封)。"""
    assert OutboxStatus.PENDING_SEND.value == "pending_send"
    assert OutboxStatus.APPROVED.value == "approved"
    assert OutboxStatus.SENDING.value == "sending"  # D5.2 新增
    assert OutboxStatus.SENT.value == "sent"
    assert OutboxStatus.FAILED.value == "failed"  # D5.2 新增
    assert OutboxStatus.CANCELLED.value == "cancelled"
    assert len(OutboxStatus) == 6


def test_outbox_tone_has_3_values() -> None:
    """OutboxTone 3 语气枚举值(与 D4.7.3 DraftTone 字段值一致)。"""
    assert OutboxTone.FORMAL.value == "FORMAL"
    assert OutboxTone.FRIENDLY.value == "FRIENDLY"
    assert OutboxTone.CONCISE.value == "CONCISE"
    assert len(OutboxTone) == 3


def test_outbox_priority_has_6_values() -> None:
    """OutboxPriority 6 优先级枚举值(week1-mvp.md:846 锁定 + v0.2 B1.1 扩 3 类)。"""
    assert OutboxPriority.URGENT.value == "urgent"
    assert OutboxPriority.HIGH.value == "high"  # v0.2 B1.1 新增
    assert OutboxPriority.NORMAL.value == "normal"
    assert OutboxPriority.LOW.value == "low"
    assert OutboxPriority.BATCH.value == "batch"  # v0.2 B1.1 新增
    assert OutboxPriority.DIGEST.value == "digest"  # v0.2 B1.1 新增
    assert len(OutboxPriority) == 6


def test_outbox_status_choices_is_frozenset_6() -> None:
    """_OUTBOX_STATUS_CHOICES = frozenset 6 元素(O(1) 校验,D5.2 扩 4→6)。"""
    assert isinstance(_OUTBOX_STATUS_CHOICES, frozenset)
    assert (
        frozenset({"pending_send", "approved", "sending", "sent", "failed", "cancelled"})
        == _OUTBOX_STATUS_CHOICES
    )


def test_outbox_tone_choices_is_frozenset_3() -> None:
    """_OUTBOX_TONE_CHOICES = frozenset 3 元素。"""
    assert isinstance(_OUTBOX_TONE_CHOICES, frozenset)
    assert frozenset({"FORMAL", "FRIENDLY", "CONCISE"}) == _OUTBOX_TONE_CHOICES


def test_outbox_priority_choices_is_frozenset_6() -> None:
    """_OUTBOX_PRIORITY_CHOICES = frozenset 6 元素(v0.2 B1.1 扩 3→6)。"""
    assert isinstance(_OUTBOX_PRIORITY_CHOICES, frozenset)
    assert (
        frozenset({"urgent", "high", "normal", "low", "batch", "digest"})
        == _OUTBOX_PRIORITY_CHOICES
    )


# ===== 2. OutboxEntry ORM 模型(8 tests)=====


def test_outbox_entry_tablename_is_outbox() -> None:
    """OutboxEntry.__tablename__ = 'outbox'(与 0004 migration 一致)。"""
    assert OutboxEntry.__tablename__ == "outbox"


def test_outbox_entry_has_12_columns() -> None:
    """OutboxEntry 12 字段(v0.2 B2.1 加 sla_due_at_ms)。

    历史字段数:
      - 0004_outbox_table: 10 字段
      - 0006 last_approved_at_ms 加列: 11 字段
      - 0009_sla_due_at 加列: 12 字段(v0.2 B2.1)
    """
    expected_columns = {
        "id",
        "email_id",
        "subject",
        "body",
        "tone",
        "reviewer_decision_event_id",
        "drafter_decision_event_id",
        "status",
        "created_at",
        "recipient_email",
        "priority",
        "last_approved_at_ms",  # D5.6.3 P1-1 审批凭据(0006 migration 加)
        "sla_due_at_ms",  # v0.2 B2.1 SLA 截止时间预计算(0009_sla_due_at 加)
    }
    actual_columns = {c.name for c in OutboxEntry.__table__.columns}
    assert actual_columns == expected_columns


def test_outbox_entry_uniqueness_constraint_on_email_id() -> None:
    """UNIQUE 约束在 email_id 字段(D4.8 契约 4 — 入库幂等性)。"""
    from sqlalchemy import UniqueConstraint

    # Table.constraints 是 SA 内部属性, FromClause 上无声明(SA 类型分立)
    unique_constraints = [
        c
        for c in OutboxEntry.__table__.constraints  # type: ignore[attr-defined]
        if isinstance(c, UniqueConstraint) and getattr(c, "name", None) == "uq_outbox_email_id"
    ]
    assert len(unique_constraints) == 1
    uq = unique_constraints[0]
    # UniqueConstraint 用 c.columns 列表(非 Index 的 column_keys)
    uq_column_names = {col.name for col in uq.columns}  # type: ignore[attr-defined]
    assert "email_id" in uq_column_names


def test_outbox_entry_fk_to_events_reviewer_and_drafter() -> None:
    """2 FK → events.id(reviewer_decision_event_id + drafter_decision_event_id)。"""
    from sqlalchemy import ForeignKeyConstraint

    fk_constraints = [
        c
        for c in OutboxEntry.__table__.constraints  # type: ignore[attr-defined]
        if isinstance(c, ForeignKeyConstraint)
        and (
            getattr(c, "name", None) == "fk_outbox_reviewer_event"
            or getattr(c, "name", None) == "fk_outbox_drafter_event"
        )
    ]
    fk_columns: list[str] = []
    for fk in fk_constraints:
        for fk_col in fk.columns:  # type: ignore[attr-defined]
            fk_columns.append(fk_col.name)
    assert "reviewer_decision_event_id" in fk_columns
    assert "drafter_decision_event_id" in fk_columns


def test_outbox_entry_2_indexes_status_and_priority() -> None:
    """2 索引 idx_outbox_status_created_at + idx_outbox_priority_created_at。"""
    # Table.indexes 类型为 frozenset[Index](SA 内部用 frozenset)
    index_names = {idx.name for idx in OutboxEntry.__table__.indexes}  # type: ignore[attr-defined]
    assert "idx_outbox_status_created_at" in index_names
    assert "idx_outbox_priority_created_at" in index_names


def test_outbox_entry_default_status_is_pending_send(store: OutboxStore) -> None:
    """OutboxEntry.status server_default='pending_send'(D4.8 仅入库到此状态)。"""
    entry = store.insert(
        email_id=1,
        subject="测试主题",
        body="这是一封测试邮件的正文内容,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="test@example.com",
    )
    assert entry.status == "pending_send"


def test_outbox_entry_default_priority_is_normal(store: OutboxStore) -> None:
    """OutboxEntry.priority server_default='normal'(大多数邮件 default)。"""
    entry = store.insert(
        email_id=2,
        subject="测试主题 2",
        body="这是另一封测试邮件的正文内容,需要超过十个字符。",
        tone="FRIENDLY",
        recipient_email="user@example.com",
    )
    assert entry.priority == "normal"


def test_outbox_entry_nullable_fk_columns(store: OutboxStore) -> None:
    """reviewer_decision_event_id / drafter_decision_event_id 可空(D4.8 启动初期)。"""
    entry = store.insert(
        email_id=3,
        subject="测试主题 3",
        body="这是第三封测试邮件的正文内容,需要超过十个字符。",
        tone="CONCISE",
        recipient_email="staff@example.com",
    )
    assert entry.reviewer_decision_event_id is None
    assert entry.drafter_decision_event_id is None


# ===== 3. OutboxStore.insert 6 字段透传(6 tests)=====


def test_insert_returns_outbox_entry(store: OutboxStore) -> None:
    """insert 返回 OutboxEntry 实例(非 None)。"""
    entry = store.insert(
        email_id=100,
        subject="客户投诉全额退款处理",
        body="针对您的投诉,我们已安排全额退款,请查收。",
        tone="FORMAL",
        recipient_email="customer@example.com",
    )
    assert isinstance(entry, OutboxEntry)


def test_insert_entry_id_is_not_none(store: OutboxStore) -> None:
    """insert 后 entry.id 不为 None(SQLite AUTOINCREMENT 已分配)。"""
    entry = store.insert(
        email_id=101,
        subject="测试 ID 分配",
        body="测试 insert 后 ID 分配是否正确,正文超过十个字符。",
        tone="FORMAL",
        recipient_email="test@example.com",
    )
    assert entry.id is not None
    assert entry.id > 0


def test_insert_subject_persisted(store: OutboxStore) -> None:
    """insert subject 字段正确持久化(1-200 字符)。"""
    subject = "客户投诉全额退款处理 - 2026年6月11日"
    entry = store.insert(
        email_id=102,
        subject=subject,
        body="这是针对您投诉的全额退款处理邮件正文。",
        tone="FORMAL",
        recipient_email="customer@example.com",
    )
    assert entry.subject == subject


def test_insert_body_persisted(store: OutboxStore) -> None:
    """insert body 字段正确持久化(10-8000 字符)。"""
    body = "这是测试 insert body 字段持久化的邮件正文,需要超过十个字符。"
    entry = store.insert(
        email_id=103,
        subject="Body 持久化测试",
        body=body,
        tone="FRIENDLY",
        recipient_email="user@example.com",
    )
    assert entry.body == body


def test_insert_tone_persisted(store: OutboxStore) -> None:
    """insert tone 字段正确持久化(OutboxTone 3 选 1)。"""
    entry = store.insert(
        email_id=104,
        subject="Tone 持久化测试",
        body="这是测试 tone 字段持久化的邮件正文,超过十个字符。",
        tone="CONCISE",
        recipient_email="staff@example.com",
    )
    assert entry.tone == "CONCISE"


def test_insert_priority_explicit_override(store: OutboxStore) -> None:
    """insert priority 显式覆盖默认(urgent/normal/low 3 选 1)。"""
    entry = store.insert(
        email_id=105,
        subject="Priority 显式覆盖测试",
        body="这是测试 priority 显式覆盖的邮件正文,超过十个字符。",
        tone="FORMAL",
        recipient_email="vip@example.com",
        priority="urgent",
    )
    assert entry.priority == "urgent"


# ===== 4. UNIQUE 冲突 → OutboxEmailDuplicateError(3 tests)=====


def test_insert_duplicate_email_id_raises_duplicate_error(store: OutboxStore) -> None:
    """同 email_id 二次入库 → OutboxEmailDuplicateError(D4.8 契约 4 — 业务阻断)。"""
    store.insert(
        email_id=200,
        subject="第一次入库",
        body="第一次入库的邮件正文,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="first@example.com",
    )
    with pytest.raises(OutboxEmailDuplicateError):
        store.insert(
            email_id=200,  # 重复 email_id
            subject="第二次入库",
            body="第二次入库的邮件正文,需要超过十个字符。",
            tone="FRIENDLY",
            recipient_email="second@example.com",
        )


def test_duplicate_error_contains_email_id(store: OutboxStore) -> None:
    """OutboxEmailDuplicateError 异常信息包含 email_id 便于 audit。"""
    store.insert(
        email_id=201,
        subject="第一次入库",
        body="第一次入库的邮件正文,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="first@example.com",
    )
    with pytest.raises(OutboxEmailDuplicateError, match="email_id=201"):
        store.insert(
            email_id=201,
            subject="第二次入库",
            body="第二次入库的邮件正文,需要超过十个字符。",
            tone="FRIENDLY",
            recipient_email="second@example.com",
        )


def test_duplicate_insert_does_not_overwrite_original(store: OutboxStore) -> None:
    """UNIQUE 冲突后原条目未变(D3.3.3 教训:业务阻断 → 原状态保留)。"""
    first = store.insert(
        email_id=202,
        subject="原始主题",
        body="原始邮件正文,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="original@example.com",
    )
    with contextlib.suppress(OutboxEmailDuplicateError):
        store.insert(
            email_id=202,
            subject="新主题(应被拒)",
            body="新邮件正文(应被拒),需要超过十个字符。",
            tone="FRIENDLY",
            recipient_email="new@example.com",
        )
    # 验证原条目未变
    fetched = store.by_email_id(202)
    assert fetched is not None
    assert fetched.id == first.id
    assert fetched.subject == "原始主题"
    assert fetched.tone == "FORMAL"
    assert fetched.recipient_email == "original@example.com"


# ===== 5. by_email_id / by_id / by_status / by_priority 查询(5 tests)=====


def test_by_email_id_returns_none_when_not_found(store: OutboxStore) -> None:
    """by_email_id 不存在返回 None(非抛异常)。"""
    assert store.by_email_id(999) is None


def test_by_email_id_returns_entry_after_insert(store: OutboxStore) -> None:
    """by_email_id 存在时返回 OutboxEntry(走 UNIQUE 索引,O(1))。"""
    inserted = store.insert(
        email_id=300,
        subject="查询测试",
        body="查询测试的邮件正文,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="query@example.com",
    )
    fetched = store.by_email_id(300)
    assert fetched is not None
    assert fetched.id == inserted.id
    assert fetched.email_id == 300


def test_by_id_returns_none_when_not_found(store: OutboxStore) -> None:
    """by_id 不存在返回 None(走 PK 索引,O(1))。"""
    assert store.by_id(999) is None


def test_by_status_filters_correctly(store: OutboxStore) -> None:
    """by_status 走 idx_outbox_status_created_at 索引,正确过滤(week1-mvp.md:851 锁定)。"""
    for i in range(3):
        store.insert(
            email_id=400 + i,
            subject=f"Status 过滤测试 {i}",
            body=f"Status 过滤测试的邮件正文 {i},需要超过十个字符。",
            tone="FORMAL",
            recipient_email=f"user{i}@example.com",
        )
    pending = store.by_status("pending_send", limit=10)
    assert len(pending) == 3
    assert all(e.status == "pending_send" for e in pending)


def test_by_status_returns_oldest_first_fifo(store: OutboxStore) -> None:
    """D5.5.3:by_status 严格按 created_at ASC 升序返回(FIFO)。

    修复 P1-1 旧积压永远进不了候选池:
      修复前 DESC + limit → 只取最新 N 条,旧积压饿死
      修复后 ASC + limit → 严格 FIFO,旧积压优先出

    场景:插入 3 条 PENDING_SEND,中间 sleep 10ms 模拟时间差,
          limit=2 应返回最早 2 条(不是最新 2 条)。
    """
    import time as _time

    first_ids: list[int] = []
    for i in range(3):
        entry = store.insert(
            email_id=600 + i,
            subject=f"FIFO 测试 {i}",
            body=f"FIFO 测试邮件正文 {i},需要超过十个字符。",
            tone="FORMAL",
            recipient_email=f"fifo{i}@example.com",
        )
        first_ids.append(entry.id)
        _time.sleep(0.01)  # 10ms 时间差保证 created_at 严格递增
    # limit=2 必返回最早 2 条
    pending = store.by_status("pending_send", limit=2)
    assert len(pending) == 2
    # D5.5.3 修复:严格升序,最早 2 条(不是最新 2 条)
    assert pending[0].id == first_ids[0]
    assert pending[1].id == first_ids[1]


def test_by_priority_filters_correctly(store: OutboxStore) -> None:
    """by_priority 走 idx_outbox_priority_created_at 索引,正确过滤(week1-mvp.md:855 锁定)。"""
    # 2 个 normal,1 个 urgent
    store.insert(
        email_id=500,
        subject="Normal 1",
        body="Normal 邮件正文 1,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="n1@example.com",
        priority="normal",
    )
    store.insert(
        email_id=501,
        subject="Urgent 1",
        body="Urgent 邮件正文 1,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="u1@example.com",
        priority="urgent",
    )
    store.insert(
        email_id=502,
        subject="Normal 2",
        body="Normal 邮件正文 2,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="n2@example.com",
        priority="normal",
    )
    urgent = store.by_priority("urgent", limit=10)
    normal = store.by_priority("normal", limit=10)
    assert len(urgent) == 1
    assert len(normal) == 2
    assert urgent[0].priority == "urgent"
    assert normal[0].priority == "normal"


# ===== 6. update_status 状态机(4 tests)=====


def test_update_status_pending_to_approved(store: OutboxStore) -> None:
    """状态机:pending_send → approved(D5+ 显式批准,D5.2 ALLOWED_TRANSITIONS 保留)。"""
    entry = store.insert(
        email_id=600,
        subject="状态机测试 - 批准",
        body="状态机测试批准的邮件正文,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="approve@example.com",
    )
    assert entry.status == "pending_send"
    updated = store.update_status(
        entry.id, "approved", from_status="pending_send", last_approved_at_ms=1781356098319
    )
    assert updated.status == "approved"


def test_update_status_pending_to_cancelled(store: OutboxStore) -> None:
    """状态机:pending_send → cancelled(用户取消,D5.2 ALLOWED_TRANSITIONS 合法)。"""
    entry = store.insert(
        email_id=601,
        subject="状态机测试 - 取消",
        body="状态机测试取消的邮件正文,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="cancel@example.com",
    )
    updated = store.update_status(
        entry.id, "cancelled", from_status="pending_send", last_approved_at_ms=None
    )
    assert updated.status == "cancelled"


def test_update_status_approved_to_sending(store: OutboxStore) -> None:
    """状态机:approved → sending(D5+ 显式批准路径,D5.2 ALLOWED_TRANSITIONS 合法)。

    D5.2 修订说明: D4.8 旧版 test_update_status_approved_to_sent 走 approved → sent 直接
    跳级路径,D5.2 加 ALLOWED_TRANSITIONS 白名单后,APPROVED 只能转 SENDING(SENT 必须在
    SENDING 之后),改测试为 approved → sending 走 D5 显式批准路径。
    """
    entry = store.insert(
        email_id=602,
        subject="状态机测试 - 显式批准",
        body="状态机测试显式批准的邮件正文,需要超过十个字符。",
        tone="FORMAL",
        recipient_email="approve-send@example.com",
    )
    store.update_status(
        entry.id, "approved", from_status="pending_send", last_approved_at_ms=1781356098319
    )
    updated = store.update_status(
        entry.id, "sending", from_status="approved", last_approved_at_ms=None
    )
    assert updated.status == "sending"


def test_update_status_nonexistent_id_raises_value_error(store: OutboxStore) -> None:
    """update_status 不存在 outbox_id 抛 ValueError(防静默状态损坏)。"""
    with pytest.raises(ValueError, match="outbox_id=999"):
        store.update_status(999, "approved", from_status="pending_send")


# ===== 7. _normalize 严判范本(3 tests)=====


def test_normalize_status_rejects_non_str(store: OutboxStore) -> None:
    """_normalize_status type 严判(防 list/dict/set 触发 TypeError,D4.7.3 v1.0.5 P2-1)。"""
    with pytest.raises(TypeError, match="status 必须是 str"):
        store._normalize_status(123)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="status 必须是 str"):
        store._normalize_status(["pending_send"])  # type: ignore[arg-type]


def test_normalize_status_rejects_invalid_value(store: OutboxStore) -> None:
    """_normalize_status 白名单(invalid status → ValueError)。"""
    with pytest.raises(ValueError, match="status 必须是 OutboxStatus 6 选 1"):
        store._normalize_status("invalid_status")


def test_normalize_priority_rejects_non_str(store: OutboxStore) -> None:
    """_normalize_priority type 严判(同 status 范本)。"""
    with pytest.raises(TypeError, match="priority 必须是 str"):
        store._normalize_priority(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="priority 必须是 str"):
        store._normalize_priority({"priority": "normal"})  # type: ignore[arg-type]


# ===== 8. D5.6.4 P1:OutboxStore.insert 严判(2 tests)=====


def test_insert_rejects_last_approved_at_ms_non_none(store: OutboxStore) -> None:
    """D5.6.4 P1 修复:OutboxStore.insert() 严禁 caller 传 last_approved_at_ms=非 None。

    业务背景(4th round 检查员反馈 P1 漏洞):
        D5.6.3 P1-1 修复要求"审批必须经 update_status(APPROVED, last_approved_at_ms=...)",
        但 Store.insert() 仍接受 last_approved_at_ms=任意整数 → caller 可绕过审批契约
        直接伪造审批凭据。

    修复:insert() 入口严判 last_approved_at_ms is not None → 抛 ValueError,
    强制审批走状态机白名单(D5.2 落地)。
    """
    with pytest.raises(
        ValueError, match="D5\\.6\\.4 P1 修复.*OutboxStore\\.insert.*严禁传 last_approved_at_ms"
    ):
        store.insert(
            email_id=1,
            subject="测试主题",
            body="测试邮件正文内容,超过十个字符。",
            tone="FORMAL",
            recipient_email="customer1@example.com",
            last_approved_at_ms=1718000000000,  # D5.6.4 P1 漏洞 caller 伪造
        )


def test_insert_forces_status_pending_send(store: OutboxStore) -> None:
    """D5.6.4 P1 修复:OutboxStore.insert() 强制 status=PENDING_SEND,无 status 参数。

    业务背景(4th round 检查员反馈 P1 漏洞):
        旧签名 `def insert(*, status="pending_send", ...)` 允许 caller 直接传
        status="approved" → 绕过 update_status 状态机白名单。

    修复:status 参数已移除(查看 insert 签名),任何状态机推进必须经
    update_status(*, from_status=...) 走 ALLOWED_TRANSITIONS 白名单。

    本测试正面验证:
        1. insert() 签名无 status 参数(已通过参数名不存在抛 TypeError 间接验证)
        2. insert() 返回的 row.status 必为 "pending_send"(硬性契约)
        3. 真实业务路径必走 update_status(APPROVED, last_approved_at_ms=...)
    """
    # 1. status 参数已被移除(严判:尝试传 status= 必 TypeError)
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        store.insert(  # type: ignore[call-arg]
            email_id=2,
            subject="测试主题",
            body="测试邮件正文内容,超过十个字符。",
            tone="FORMAL",
            recipient_email="customer2@example.com",
            status="approved",  # D5.6.4 P1:该参数已移除
        )

    # 2. 正常 insert 必返回 PENDING_SEND
    row = store.insert(
        email_id=3,
        subject="测试主题",
        body="测试邮件正文内容,超过十个字符。",
        tone="FORMAL",
        recipient_email="customer3@example.com",
    )
    assert row.status == OutboxStatus.PENDING_SEND.value, (
        f"D5.6.4 P1:insert 强制 status=PENDING_SEND,实际 {row.status!r}"
    )
    assert row.last_approved_at_ms is None, (
        f"D5.6.4 P1:insert 后 last_approved_at_ms 必 None,实际 {row.last_approved_at_ms!r}"
    )


# ===== 9. B2.1 hotfix: insert 入口 priority 严判(3 tests,2026-06-16)=====
# v0.2 B2.1 hotfix:OutboxStore.insert 入口必须 _normalize_priority 把 priority
# 规约成合法白名单 6 选 1。
# - 修复前: insert() 直接把原始 priority 传给 _compute_sla_due_at_ms,helper 内
#   `if priority_value not in _SLA_THRESHOLDS: return None` 防御性返回 None
#   → priority="INVALID" 也能过 type 严判 + 走 None 分支 + 写入 INVALID + sla_due_at_ms=None
#   → 绕过 B1 6 类契约 + 污染 B2 SLA 字段
# - 修复后: insert() 入口调 _normalize_priority(沿 status 同款严判范本),INVALID 一律 ValueError
# - 双层防御: insert 入口 + helper 内 type 严判,任一层漏都不会放过非法值


def test_insert_rejects_invalid_priority_raises_valueerror(store: OutboxStore) -> None:
    """B2.1 hotfix P1-A:insert 入口严判 priority 必须在 _OUTBOX_PRIORITY_CHOICES 6 选 1。

    修复前(回归 bug): priority="INVALID" 可成功插入,entry.priority="INVALID" +
    entry.sla_due_at_ms=None,绕过 B1 6 类契约 + 污染 B2 SLA 字段。

    修复后: insert() 入口调 _normalize_priority → "INVALID" 不在 6 选 1 → ValueError,
    阻止写入,保证所有 outbox 条目 priority 字段必合法。
    """
    with pytest.raises(ValueError, match="priority 必须是 OutboxPriority 6 选 1"):
        store.insert(
            email_id=10,
            subject="测试非法 priority 拒收",
            body="测试非法 priority 必被 insert 入口 ValueError 拒绝,正文超过十个字符。",
            tone="FORMAL",
            recipient_email="reject@example.com",
            priority="INVALID",
        )
    # 大小写错误也必拒(严判是 _OUTBOX_PRIORITY_CHOICES 6 选 1,小写只接 normal/low)
    with pytest.raises(ValueError, match="priority 必须是 OutboxPriority 6 选 1"):
        store.insert(
            email_id=11,
            subject="测试 URGENT 大小写错误也拒收",
            body="_OUTBOX_PRIORITY_CHOICES 是小写集合,大写 URGENT 必拒收。",
            tone="FORMAL",
            recipient_email="case@example.com",
            priority="URGENT",  # 大写,小写集合不含
        )
    # 旧 3 类的 NORMAL(大写)同理必拒
    with pytest.raises(ValueError, match="priority 必须是 OutboxPriority 6 选 1"):
        store.insert(
            email_id=12,
            subject="测试 NORMAL 大写拒收",
            body="_OUTBOX_PRIORITY_CHOICES 是小写集合,大写 NORMAL 必拒收。",
            tone="FORMAL",
            recipient_email="normal-case@example.com",
            priority="NORMAL",
        )


def test_insert_rejects_non_str_priority_raises_typeerror(store: OutboxStore) -> None:
    """B2.1 hotfix P1-A:type 严判(沿 _normalize_priority 范本,type 严判在 hash 前)。

    非 str 类型(列表 / 字典 / 集合 / None / int / bool)必抛 TypeError,不抛 ValueError
    (D4.7.3 v1.0.5 P2-1 范本:type 严判在 hash 前,防 list/dict/set 触发 TypeError)。
    """
    # 1. 列表 — 非可哈希类型,严判 type 优先
    with pytest.raises(TypeError, match="priority 必须是 str"):
        store.insert(
            email_id=20,
            subject="测试列表 type 严判",
            body="测试 priority=[] 必被 _normalize_priority TypeError 拒绝。",
            tone="FORMAL",
            recipient_email="list@example.com",
            priority=[],  # type: ignore[arg-type]
        )
    # 2. 字典 — 非可哈希类型
    with pytest.raises(TypeError, match="priority 必须是 str"):
        store.insert(
            email_id=21,
            subject="测试字典 type 严判",
            body="测试 priority={} 必被 _normalize_priority TypeError 拒绝。",
            tone="FORMAL",
            recipient_email="dict@example.com",
            priority={},  # type: ignore[arg-type]
        )
    # 3. int — 非 str 类型
    with pytest.raises(TypeError, match="priority 必须是 str"):
        store.insert(
            email_id=22,
            subject="测试 int type 严判",
            body="测试 priority=123 必被 _normalize_priority TypeError 拒绝。",
            tone="FORMAL",
            recipient_email="int@example.com",
            priority=123,  # type: ignore[arg-type]
        )
    # 4. None — 非 str 类型
    with pytest.raises(TypeError, match="priority 必须是 str"):
        store.insert(
            email_id=23,
            subject="测试 None type 严判",
            body="测试 priority=None 必被 _normalize_priority TypeError 拒绝。",
            tone="FORMAL",
            recipient_email="none@example.com",
            priority=None,  # type: ignore[arg-type]
        )


def test_insert_accepts_all_6_priorities(store: OutboxStore) -> None:
    """B2.1 hotfix P1-A:6 类 priority 全接受(URGENT/HIGH/NORMAL/LOW/BATCH/DIGEST)。

    业务背景(沿 v0.2 B1.1):
        URGENT  紧急  5min SLA
        HIGH    高优  30min SLA  # v0.2 B1.1 新增
        NORMAL  普通  4h SLA
        LOW     低优  24h SLA
        BATCH   批量  24h SLA   # v0.2 B1.1 新增(可错峰)
        DIGEST  摘要  7d SLA    # v0.2 B1.1 新增(合并发送)

    本测试正面验证 6 类 priority 都能成功插入 + sla_due_at_ms 必非 None
    (因为 6 类全在 _SLA_THRESHOLDS 白名单内,不应返回 None)。
    """
    from my_ai_employee.scheduler.sla import _SLA_THRESHOLDS

    for idx, priority_value in enumerate(
        ["urgent", "high", "normal", "low", "batch", "digest"], start=30
    ):
        entry = store.insert(
            email_id=idx,
            subject=f"测试 {priority_value} priority 接受",
            body=f"测试 {priority_value} 6 类 priority 必被 insert 入口接受,正文超过十个字符。",
            tone="FORMAL",
            recipient_email=f"{priority_value}@example.com",
            priority=priority_value,
        )
        assert entry.priority == priority_value, (
            f"expected priority={priority_value!r}, got {entry.priority!r}"
        )
        # 6 类 priority 全在 _SLA_THRESHOLDS 白名单内,sla_due_at_ms 必非 None
        assert entry.sla_due_at_ms is not None, (
            f"{priority_value} 必算 sla_due_at_ms,不应返回 None(6 类全在 _SLA_THRESHOLDS 内)"
        )
        # 验证 sla_due_at_ms = created_at + threshold_ms(_SLA_THRESHOLDS[priority][0])
        expected_threshold_ms, _ = _SLA_THRESHOLDS[priority_value]
        assert entry.sla_due_at_ms == entry.created_at + expected_threshold_ms, (
            f"{priority_value} sla_due_at_ms 必 = created_at + threshold_ms,"
            f"got {entry.sla_due_at_ms} vs {entry.created_at} + {expected_threshold_ms}"
        )
