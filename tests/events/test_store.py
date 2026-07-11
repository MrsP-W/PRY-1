"""D4.3 — EventStore 测试 (insert + 4 类查询 + dedupe + 异常).

覆盖:
  - insert 正常: 返回 Event 含 id + fingerprint + event_metadata
  - insert dedupe: 同身份 → 静默返回原 Event
  - insert on_conflict="raise" → 抛 EventFingerprintConflictError
  - get_by_id / get_by_fingerprint
  - by_session / by_subject / by_event_type / by_status 4 类查询
  - 负向证据 first-class: FAILED/SKIPPED/BLOCKED 状态可独立查询
  - insert 异常窄化: 非法枚举 / 缺字段 → EventContractError / EventMetadataError
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.events import (  # noqa: E402
    EventContractError,
    EventFingerprintConflictError,
    EventStatus,
    EventStore,
    EventType,
)


class TestInsert:
    def test_insert_returns_event_with_id_and_fingerprint(self, store: EventStore) -> None:
        """insert 返回 Event, id + fingerprint + event_metadata 都填充好."""
        e = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id="req-1",
            seq=1,
            session_id="sess-A",
            extra={"tokens": 100},
        )
        assert e.id is not None
        assert e.fingerprint != ""
        assert e.event_metadata["session_id"] == "sess-A"
        assert e.event_metadata["tokens"] == 100

    def test_insert_invalid_event_raises_contract_error(self, store: EventStore) -> None:
        """非法 event 枚举 → EventContractError(不写入 DB)."""
        with pytest.raises(EventContractError, match="event 非法"):
            store.insert(
                event="bogus.event",
                status=EventStatus.STARTED,
                source="minimax",
            )
        assert store.count() == 0

    def test_insert_invalid_status_raises_contract_error(self, store: EventStore) -> None:
        """非法 status 枚举 → EventContractError(不写入 DB)."""
        with pytest.raises(EventContractError, match="status 非法"):
            store.insert(
                event=EventType.LLM_CALL_STARTED,
                status="bogus",
                source="minimax",
            )
        assert store.count() == 0

    def test_insert_programming_errors_raise_before_writing(self, store: EventStore) -> None:
        """非法 seq / on_conflict 都是编程错误，且不能写入 DB。"""
        with pytest.raises(ValueError, match="seq 必须 >= 0"):
            store.insert(
                event=EventType.LLM_CALL_STARTED,
                status=EventStatus.STARTED,
                source="minimax",
                seq=-1,
            )
        with pytest.raises(ValueError, match="on_conflict"):
            store.insert(
                event=EventType.LLM_CALL_STARTED,
                status=EventStatus.STARTED,
                source="minimax",
                on_conflict="ignroe",
            )
        assert store.count() == 0


class TestDedupe:
    def test_dedupe_same_identity_returns_original(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """生产 SQLCipher 直抛 DBAPI IntegrityError 时仍保持两种去重契约。"""
        from sqlalchemy.orm import sessionmaker

        from my_ai_employee.core import keychain
        from my_ai_employee.core.db import Database
        from my_ai_employee.core.models import Base
        from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine
        from my_ai_employee.events.models import Event

        def fake_get() -> keychain.KeychainResult:
            return keychain.KeychainResult(ok=True, value="test-password")

        monkeypatch.setattr(keychain, "get_db_password", fake_get)
        db = Database.open(db_path=tmp_path / "events.db")
        try:
            engine = make_sqlalchemy_engine(db)
            Base.metadata.create_all(engine)
            sqlcipher_store = EventStore(sessionmaker(bind=engine))

            def insert_duplicate(on_conflict: str = "ignore") -> Event:
                return sqlcipher_store.insert(
                    event=EventType.LLM_CALL_STARTED,
                    status=EventStatus.STARTED,
                    source="minimax",
                    subject_id="req-sqlcipher",
                    seq=1,
                    session_id="sess-sqlcipher",
                    timestamp_ms=1_780_000_000_000,
                    on_conflict=on_conflict,
                )

            first = insert_duplicate()
            duplicate = insert_duplicate()

            assert duplicate.id == first.id
            assert sqlcipher_store.count() == 1
            with pytest.raises(EventFingerprintConflictError, match="UNIQUE 冲突"):
                insert_duplicate(on_conflict="raise")
        finally:
            db.close()

    def test_dedupe_across_different_time_stays_same(self, store: EventStore) -> None:
        """同身份 + 不同 timestamp_ms/seq 仍 dedupe(运行时字段不参与 fingerprint)."""
        e1 = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id="req-1",
            seq=1,
            session_id="sess-A",
            timestamp_ms=1_780_000_000_000,
        )
        e2 = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id="req-1",
            seq=99,  # 不同 seq
            session_id="sess-A",
            timestamp_ms=1_790_000_000_000,  # 不同 timestamp
        )
        assert e2.id == e1.id

    def test_dedupe_raise_mode_raises_conflict(self, store: EventStore) -> None:
        """on_conflict='raise' 模式: UNIQUE 冲突抛 EventFingerprintConflictError."""
        store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id="req-1",
            seq=1,
            session_id="sess-A",
        )
        with pytest.raises(EventFingerprintConflictError, match="UNIQUE 冲突"):
            store.insert(
                event=EventType.LLM_CALL_STARTED,
                status=EventStatus.STARTED,
                source="minimax",
                subject_id="req-1",
                seq=1,
                session_id="sess-A",
                on_conflict="raise",
            )

    def test_dedupe_with_null_subject_id(self, store: EventStore) -> None:
        """P1 复检回归 (D4.3.1): subject_id=None + 同 fingerprint 必须 dedupe.

        旧 4 字段 UNIQUE 在 subject_id=NULL 时被 SQLite 视为不同行, 允许重复插入.
        修复: 改 UNIQUE(fingerprint) 全局唯一. 此测试确保修复生效.
        """
        e1 = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id=None,  # 关键: 软引用, 无关联实体
            seq=1,
            session_id="sess-A",
        )
        e2 = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id=None,  # 同 None
            seq=2,  # 不同 seq
            session_id="sess-A",
            timestamp_ms=1_790_000_000_000,  # 不同 timestamp
        )
        # 关键断言: dedupe 命中, id 相同
        assert e2.id == e1.id
        assert e2.fingerprint == e1.fingerprint
        assert store.count() == 1  # 实际只插 1 行

    def test_dedupe_null_subject_id_raise_mode(self, store: EventStore) -> None:
        """P1 复检回归 (D4.3.1): subject_id=None + raise 模式必须抛冲突."""
        store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id=None,
            seq=1,
        )
        with pytest.raises(EventFingerprintConflictError):
            store.insert(
                event=EventType.LLM_CALL_STARTED,
                status=EventStatus.STARTED,
                source="minimax",
                subject_id=None,
                seq=2,
                on_conflict="raise",
            )

    def test_dedupe_fallback_cross_source_allowed(self, store: EventStore) -> None:
        """P1 修复辅助验证: fallback 跨源 (deepseek 失败 → openai 重试) 各自 1 条.

        compute_fingerprint 入参含 source, 不同 source → 不同 fingerprint,
        UNIQUE(fingerprint) 不会误判, 各允许 1 条.
        """
        e1 = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.FAILED,  # 第一次失败
            source="deepseek",
            subject_id="req-1",
            seq=1,
        )
        e2 = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.SUCCEEDED,  # fallback 重试成功
            source="openai",
            subject_id="req-1",
            seq=1,
        )
        # 关键: 不同 source + 不同 status → 不同 fingerprint → 2 条
        assert e1.id != e2.id
        assert e1.fingerprint != e2.fingerprint
        assert store.count() == 2

    def test_different_status_creates_new_fingerprint(self, store: EventStore) -> None:
        """不同 status → 新 fingerprint → 新行."""
        e1 = store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id="req-1",
            seq=1,
        )
        e2 = store.insert(
            event=EventType.LLM_CALL_SUCCEEDED,  # 不同 event
            status=EventStatus.SUCCEEDED,  # 不同 status
            source="minimax",
            subject_id="req-1",
            seq=2,
        )
        assert e2.id != e1.id
        assert e2.fingerprint != e1.fingerprint
        assert store.count() == 2


class TestQueries:
    @pytest.fixture(autouse=True)
    def _isolate_store(self, store: EventStore) -> None:  # noqa: D401
        """D5.6.2 修复:每次查询测试前清空 store,避免 TestDedupe 留下的 session_id 污染。

        pytest collection 顺序变化(加 dispatcher_approval test 后)导致 TestDedupe
        先于 TestQueries 跑,留下 sess-A seq=1 事件,by_session DESC 排序 LIMIT 1
        取到 TestDedupe 的旧事件(因为 Event.created_at 默认 0,所有 DESC 顺序不定)。
        """
        from sqlalchemy import delete  # noqa: PLC0415

        from my_ai_employee.events.models import Event  # noqa: PLC0415

        with store._session_factory() as session:  # noqa: SLF001
            session.execute(delete(Event))
            session.commit()

    def _seed(self, store: EventStore) -> None:
        """测试数据: 3 events 跨 2 sessions + 2 subjects + 4 statuses."""
        store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id="req-1",
            seq=1,
            session_id="sess-A",
        )
        store.insert(
            event=EventType.LLM_CALL_SUCCEEDED,
            status=EventStatus.SUCCEEDED,
            source="minimax",
            subject_id="req-1",
            seq=2,
            session_id="sess-A",
        )
        store.insert(
            event=EventType.LLM_CALL_FAILED,
            status=EventStatus.FAILED,
            source="minimax",
            subject_id="req-2",
            seq=1,
            session_id="sess-B",
        )

    def test_get_by_id(self, store: EventStore) -> None:
        """get_by_id 命中 + 未命中 None."""
        self._seed(store)
        e = store.by_subject("req-1")[0]  # 先拿 id
        got = store.get_by_id(e.id)
        assert got is not None
        assert got.id == e.id
        assert store.get_by_id(99999) is None

    def test_get_by_fingerprint(self, store: EventStore) -> None:
        """get_by_fingerprint 命中 + 未命中 None."""
        self._seed(store)
        e = store.by_subject("req-1")[0]
        got = store.get_by_fingerprint(e.fingerprint)
        assert got is not None
        assert got.id == e.id
        assert store.get_by_fingerprint("nonexistent") is None

    def test_by_session(self, store: EventStore) -> None:
        """by_session 只返回该 session 的 events(按 created_at DESC)."""
        self._seed(store)
        a = store.by_session("sess-A")
        b = store.by_session("sess-B")
        assert len(a) == 2
        assert len(b) == 1
        # 倒序: 后插的先返回(seq 在 event_metadata 内)
        assert a[0].event_metadata["seq"] == 2
        assert a[1].event_metadata["seq"] == 1
        # session B 只有 1 条
        assert b[0].subject_id == "req-2"

    def test_by_session_limit(self, store: EventStore) -> None:
        """by_session limit 参数截断."""
        self._seed(store)
        a = store.by_session("sess-A", limit=1)
        assert len(a) == 1
        assert a[0].event_metadata["seq"] == 2  # 最新那条

    def test_by_subject(self, store: EventStore) -> None:
        """by_subject 只返回该 subject 的 events."""
        self._seed(store)
        r1 = store.by_subject("req-1")
        r2 = store.by_subject("req-2")
        assert len(r1) == 2
        assert len(r2) == 1
        assert r2[0].status == EventStatus.FAILED.value

    def test_by_event_type(self, store: EventStore) -> None:
        """by_event_type 只返回该 type 的 events."""
        self._seed(store)
        started = store.by_event_type(EventType.LLM_CALL_STARTED)
        succeeded = store.by_event_type(EventType.LLM_CALL_SUCCEEDED)
        failed = store.by_event_type(EventType.LLM_CALL_FAILED)
        assert len(started) == 1
        assert len(succeeded) == 1
        assert len(failed) == 1

    def test_by_status_negative_evidence(self, store: EventStore) -> None:
        """by_status 负向证据查询(FAILED/SKIPPED/BLOCKED 独立)."""
        self._seed(store)
        # 加 2 条 SKIPPED + 1 条 BLOCKED
        store.insert(
            event=EventType.EMAIL_CLASSIFY_FAILED,
            status=EventStatus.SKIPPED,
            source="classifier",
            subject_id="req-3",
            seq=1,
        )
        store.insert(
            event=EventType.DRAFT_GENERATE_FAILED,
            status=EventStatus.BLOCKED,
            source="drafter",
            subject_id="req-4",
            seq=1,
        )
        failed = store.by_status(EventStatus.FAILED)
        skipped = store.by_status(EventStatus.SKIPPED)
        blocked = store.by_status(EventStatus.BLOCKED)
        assert len(failed) == 1
        assert len(skipped) == 1
        assert len(blocked) == 1
        # 验证 status 字段正确
        assert failed[0].status == "failed"
        assert skipped[0].status == "skipped"
        assert blocked[0].status == "blocked"

    def test_count(self, store: EventStore) -> None:
        """count() 返回总行数."""
        assert store.count() == 0
        self._seed(store)
        assert store.count() == 3
        # dedupe 不增计数
        store.insert(
            event=EventType.LLM_CALL_STARTED,
            status=EventStatus.STARTED,
            source="minimax",
            subject_id="req-1",
            seq=1,
            session_id="sess-A",
        )
        assert store.count() == 3
