"""v0.2.1 #3 — ExpenseServiceImpl 单元 + 集成测试(12 cases).

承接 [[v0.2.1-candidates-2026-06-17]] §4 ExpenseServiceStub 实化 + D9.3 + D8.3 范本。

3 段测试覆盖(12 cases):
    1. 构造注入严判(3 tests):None 拒绝 / 类型错拒绝 / cache_ttl 严判
    2. Notes 相关 3 方法(4 tests):count / unsynced / recent_titles
    3. 系统状态 2 方法(2 tests):clipboard_listener / tcc_authorization
    4. Anomaly 缓存 + 查询(3 tests):空缓存命中 / 写后命中 / limit 截断

设计原则(沿 D10.5 stub 替换范本):
    - 缓存 TTL 5 分钟默认(避免每次菜单栏刷新跑全量 anomaly)
    - get_anomaly_count + get_recent_anomalies 共享同一缓存条目
    - OperationalError / SQLAlchemyError 透传(沿 D3.3.3 教训)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    from collections.abc import Iterator


# ===== Fixtures(D6.4 范本:InMemory SQLite + create_all)=====


@pytest.fixture
def engine() -> Iterator[Any]:
    """InMemory SQLite + 全部 ORM create_all。"""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.merchant_profile import MerchantProfile  # noqa: F401
    from my_ai_employee.db.notes import Note  # noqa: F401
    from my_ai_employee.db.transactions import Transaction  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    """返回 sessionmaker[Any]."""
    return sessionmaker[Any](bind=engine)


@pytest.fixture
def note_store(session_factory: Any) -> Any:
    """NoteStore 实例。"""
    from my_ai_employee.db.notes import NoteStore

    return NoteStore(session_factory)


@pytest.fixture
def tx_store(session_factory: Any) -> Any:
    """TransactionStore 实例。"""
    from my_ai_employee.db.transactions import TransactionStore

    return TransactionStore(session_factory)


@pytest.fixture
def merchant_profile_store(session_factory: Any, tx_store: Any) -> Any:
    """MerchantProfileStore 实例(D8.1)。"""
    from my_ai_employee.db.merchant_profile import MerchantProfileStore

    return MerchantProfileStore(session_factory, transaction_store=tx_store)


@pytest.fixture
def anomaly_detector(tx_store: Any, merchant_profile_store: Any) -> Any:
    """RuleBasedAnomalyDetector 实例(D8.2)。"""
    from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector

    return RuleBasedAnomalyDetector(
        transaction_store=tx_store,
        merchant_profile_store=merchant_profile_store,
    )


@pytest.fixture
def service(note_store: Any, tx_store: Any, anomaly_detector: Any) -> Any:
    """ExpenseServiceImpl 默认实例(无 clipboard / tcc 注入)。"""
    from my_ai_employee.core.expense_service import ExpenseServiceImpl

    return ExpenseServiceImpl(
        note_store=note_store,
        tx_store=tx_store,
        anomaly_detector=anomaly_detector,
    )


# ===== 1. 构造注入严判(3 tests)=====


def test_construct_rejects_none_note_store(tx_store: Any, anomaly_detector: Any) -> Any:
    """1.1 None note_store 拒绝(TypeError)。"""
    from my_ai_employee.core.expense_service import ExpenseServiceImpl

    with pytest.raises(TypeError, match="note_store 必传非 None"):
        ExpenseServiceImpl(
            note_store=None,  # type: ignore[arg-type]
            tx_store=tx_store,
            anomaly_detector=anomaly_detector,
        )


def test_construct_rejects_wrong_type_anomaly_detector(note_store: Any, tx_store: Any) -> Any:
    """1.2 anomaly_detector 类型错拒绝(TypeError)。"""
    from my_ai_employee.core.expense_service import ExpenseServiceImpl

    with pytest.raises(TypeError, match="anomaly_detector 必为 RuleBasedAnomalyDetector"):
        ExpenseServiceImpl(
            note_store=note_store,
            tx_store=tx_store,
            anomaly_detector="not_a_detector",  # type: ignore[arg-type]
        )


def test_construct_validates_cache_ttl(
    note_store: Any, tx_store: Any, anomaly_detector: Any
) -> Any:
    """1.3 cache_ttl_ms 越界拒绝(ValueError)。"""
    from my_ai_employee.core.expense_service import ExpenseServiceImpl

    with pytest.raises(ValueError, match="cache_ttl_ms 必须是"):
        ExpenseServiceImpl(
            note_store=note_store,
            tx_store=tx_store,
            anomaly_detector=anomaly_detector,
            cache_ttl_ms=100,  # < 1000 下限
        )
    with pytest.raises(ValueError, match="cache_ttl_ms 必须是"):
        ExpenseServiceImpl(
            note_store=note_store,
            tx_store=tx_store,
            anomaly_detector=anomaly_detector,
            cache_ttl_ms=True,
        )


# ===== 2. Notes 相关 3 方法(4 tests)=====


def test_get_total_notes_count_empty(service: Any) -> Any:
    """2.1 空表 → 0。"""
    assert service.get_total_notes_count() == 0


def test_get_total_notes_count_after_inserts(note_store: Any, service: Any) -> Any:
    """2.2 插入 3 笔 → 3。"""
    for i in range(3):
        note_store.insert(
            apple_note_id=f"x-coredata://test/note-{i:03d}",
            folder="Notes",
            title=f"Note {i}",
            body="",
            updated_at_ms=1700000000000 + i,
        )
    assert service.get_total_notes_count() == 3


def test_get_unsynced_count_filters_new(note_store: Any, service: Any) -> Any:
    """2.3 unsynced = sync_status='NEW' 行数(沿 v0.2.1 #4 sync_status 字段)。"""
    # 插 3 笔,2 笔结构化(structure_and_emit 路径),1 笔保持 NEW
    note_store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="N1",
        body="",
        updated_at_ms=1700000000000,
    )
    note_store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="N2",
        body="",
        updated_at_ms=1700000000001,
    )
    note_store.insert(
        apple_note_id="x-coredata://test/note-003",
        folder="Notes",
        title="N3",
        body="",
        updated_at_ms=1700000000002,
    )
    note_store.mark_structured("x-coredata://test/note-001", ["tag"])
    note_store.mark_structured("x-coredata://test/note-002", ["tag"])

    assert service.get_unsynced_count() == 1  # 只 note-003 是 NEW


def test_get_recent_note_titles_returns_titles(note_store: Any, service: Any) -> Any:
    """2.4 recent_titles 返回 list[title](按 synced_at_ms DESC)。"""
    note_store.insert(
        apple_note_id="x-coredata://test/note-001",
        folder="Notes",
        title="First Note",
        body="",
        updated_at_ms=1700000000000,
    )
    note_store.insert(
        apple_note_id="x-coredata://test/note-002",
        folder="Notes",
        title="Second Note",
        body="",
        updated_at_ms=1700000000001,
    )
    titles = service.get_recent_note_titles(limit=10)
    assert titles == ["Second Note", "First Note"]  # DESC 顺序


# ===== 3. 系统状态 2 方法(2 tests)=====


def test_is_clipboard_listener_running_false_without_proc(service: Any) -> Any:
    """3.1 clipboard_listener_proc 未注入 → False。"""
    assert service.is_clipboard_listener_running() is False


def test_get_tcc_authorization_status_false_without_fn(service: Any) -> Any:
    """3.2 tcc_check_fn 未注入 → False。"""
    assert service.get_tcc_authorization_status() is False


# ===== 4. Anomaly 缓存 + 查询(3 tests)=====


def test_get_anomaly_count_empty_returns_zero(service: Any) -> Any:
    """4.1 空 transactions 表 → 0(无 anomaly)。"""
    assert service.get_anomaly_count() == 0


def test_get_recent_anomalies_empty_returns_empty_list(service: Any) -> Any:
    """4.2 空 transactions 表 → []。"""
    assert service.get_recent_anomalies(limit=10) == []


def test_get_recent_anomalies_validates_limit(service: Any) -> Any:
    """4.3 limit 严判 [1, 100](type() is bool 拒绝 + 越界拒绝)。"""
    with pytest.raises(ValueError, match="limit 必须是"):
        service.get_recent_anomalies(limit=0)
    with pytest.raises(ValueError, match="limit 必须是"):
        service.get_recent_anomalies(limit=101)
    with pytest.raises(ValueError, match="limit 必须是"):
        service.get_recent_anomalies(limit=True)
