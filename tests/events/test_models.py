"""D4.3 — Events ORM Model + 4 StrEnum + JSONDict TypeDecorator 测试.

覆盖:
  - Base.metadata 注册 events 表(7 张表 = 6 D3 + 1 D4.3)
  - 4 StrEnum 值个数 + 值字符串
  - Event ORM 字段 7 个 + 索引 + UNIQUE 约束
  - JSONDict TypeDecorator: dict ↔ JSON 文本
  - server_default 生效
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.events import (  # noqa: E402
    Event,
    EventOwnership,
    EventProvenance,
    EventStatus,
    EventType,
    JSONDict,
)


class TestMetadataRegistration:
    def test_events_table_registered(self) -> None:
        """Base.metadata 注册了 events 表(D4.3 新增, 第 7 张表; D4.8 启动后第 8 张是 outbox)."""
        tables = sorted(Base.metadata.tables.keys())
        assert "events" in tables
        # 8 张表 = 6 D3 + 1 D4.3 events + 1 D4.8 outbox
        assert len(tables) == 8

    def test_events_table_has_7_columns(self) -> None:
        """events 表 7 字段 (id + event + status + source + subject_id + fingerprint + event_metadata + created_at)."""
        cols = sorted(Base.metadata.tables["events"].columns.keys())
        expected = sorted(
            [
                "id",
                "event",
                "status",
                "source",
                "subject_id",
                "fingerprint",
                "event_metadata",
                "created_at",
            ]
        )
        assert cols == expected

    def test_events_table_has_unique_constraint(self) -> None:
        """UNIQUE(fingerprint) 全局唯一 (D4.3.1 复检 P1 修复).

        旧 4 字段 UNIQUE 在 subject_id=NULL 时被 SQLite 视为不同行, 破坏 dedupe.
        改 fingerprint 全局唯一键. fallback 跨源场景由 compute_fingerprint 入参
        含 source 保证 fingerprint 不同, 不被误判.
        """
        table = Base.metadata.tables["events"]
        uq_names = [
            str(c.name) for c in table.constraints if hasattr(c, "name") and c.name is not None
        ]
        uq_names = [n for n in uq_names if "uq_" in n]
        assert "uq_events_fingerprint" in uq_names
        # 旧 4 字段 UNIQUE 名称不应再出现
        assert "uq_events_event_source_subject_fingerprint" not in uq_names

    def test_events_table_has_6_indexes(self) -> None:
        """6 索引 (created_at DESC + event + status + source + subject_id + fingerprint)."""
        table = Base.metadata.tables["events"]
        idx_names = sorted(i.name for i in table.indexes if i.name is not None)
        expected = sorted(
            [
                "idx_events_created_at",
                "idx_events_event",
                "idx_events_status",
                "idx_events_source",
                "idx_events_subject_id",
                "idx_events_fingerprint",
            ]
        )
        assert idx_names == expected


class TestEnums:
    def test_event_type_has_13_values(self) -> None:
        """EventType 13 枚举 (4 LLM + 3 MCP + 2 email + 2 draft + 2 policy).

        D4.4 新增 2 policy 决策事件: policy.decision.made / policy.decision.degraded.
        """
        values = [e.value for e in EventType]
        assert len(values) == 13
        # g004 风格命名(2+ 段, 主要 3 段; 4 段如 email.classify.failed 允许子动作细分)
        assert all("." in v for v in values)
        assert all(v.count(".") >= 2 for v in values)
        # D4.4 新增 2 policy 事件
        assert "policy.decision.made" in values
        assert "policy.decision.degraded" in values

    def test_event_status_has_7_values(self) -> None:
        """EventStatus 7 枚举 (started / succeeded / failed / degraded / skipped / blocked / cancelled)."""
        values = sorted(e.value for e in EventStatus)
        assert values == sorted(
            ["started", "succeeded", "failed", "degraded", "skipped", "blocked", "cancelled"]
        )

    def test_event_provenance_has_4_values(self) -> None:
        """EventProvenance 4 枚举 (live / test / replay / healthcheck)."""
        values = sorted(e.value for e in EventProvenance)
        assert values == sorted(["live", "test", "replay", "healthcheck"])

    def test_event_ownership_has_3_values(self) -> None:
        """EventOwnership 3 枚举 (act / observe / ignore)."""
        values = sorted(e.value for e in EventOwnership)
        assert values == sorted(["act", "observe", "ignore"])


class TestEventORM:
    def test_event_orm_create_and_query(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        """Event ORM: 创建 + session.get 重查 + 字段一致."""
        with session_factory() as session:
            e = Event(
                event=EventType.LLM_CALL_STARTED.value,
                status=EventStatus.STARTED.value,
                source="minimax",
                subject_id="req-1",
                fingerprint="abc123",
                event_metadata={"seq": 1, "tokens": 100},
                created_at=1_780_000_000_000,
            )
            session.add(e)
            session.commit()
            eid = e.id

        with session_factory() as session:
            e2 = session.get(Event, eid)
            assert e2 is not None
            assert e2.event == "llm.call.started"
            assert e2.status == "started"
            assert e2.source == "minimax"
            assert e2.subject_id == "req-1"
            assert e2.fingerprint == "abc123"
            assert e2.event_metadata == {"seq": 1, "tokens": 100}
            assert e2.created_at == 1_780_000_000_000

    def test_event_metadata_default_dict(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        """event_metadata 缺省值 {} (server_default 生效)."""
        with session_factory() as session:
            e = Event(
                event="llm.call.started",
                status="started",
                source="minimax",
                fingerprint="x",
                created_at=1_780_000_000_000,
            )
            session.add(e)
            session.commit()
            eid = e.id
        with session_factory() as session:
            e2 = session.get(Event, eid)
            assert e2 is not None
            assert e2.event_metadata == {}

    def test_event_source_default_empty(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        """source 缺省值 '' (server_default 生效)."""
        with session_factory() as session:
            e = Event(
                event="llm.call.started",
                status="started",
                fingerprint="x",
                created_at=1_780_000_000_000,
            )
            session.add(e)
            session.commit()
            eid = e.id
        with session_factory() as session:
            e2 = session.get(Event, eid)
            assert e2 is not None
            assert e2.source == ""

    def test_event_subject_id_nullable(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        """subject_id 可空."""
        with session_factory() as session:
            e = Event(
                event="llm.call.started",
                status="started",
                source="x",
                fingerprint="x",
                subject_id=None,
                created_at=1_780_000_000_000,
            )
            session.add(e)
            session.commit()
            eid = e.id
        with session_factory() as session:
            e2 = session.get(Event, eid)
            assert e2 is not None
            assert e2.subject_id is None

    def test_event_repr_includes_key_fields(self) -> None:
        """__repr__ 含 id + event + status + source + subject_id."""
        e = Event(
            id=1,
            event="llm.call.started",
            status="started",
            source="minimax",
            subject_id="req-1",
            fingerprint="x",
            created_at=1_780_000_000_000,
        )
        r = repr(e)
        assert "id=1" in r
        assert "llm.call.started" in r
        assert "started" in r
        assert "minimax" in r
        assert "req-1" in r


class TestJSONDictTypeDecorator:
    def test_json_dict_empty_becomes_empty_dict(self) -> None:
        """process_result_value: 空字符串 / None → {}."""
        td = JSONDict()
        assert td.process_result_value("", None) == {}
        assert td.process_result_value(None, None) == {}

    def test_json_dict_parses_json_text(self) -> None:
        """process_result_value: JSON 文本 → dict."""
        td = JSONDict()
        result = td.process_result_value('{"a": 1, "b": "x"}', None)
        assert result == {"a": 1, "b": "x"}

    def test_json_dict_serializes_dict(self) -> None:
        """process_bind_param: dict → JSON 文本(ensure_ascii=False 保中文)."""
        td = JSONDict()
        result = td.process_bind_param({"a": 1, "b": "中文"}, None)
        assert result is not None
        assert "中文" in result  # ensure_ascii=False
        assert '"a": 1' in result

    def test_json_dict_none_stays_none(self) -> None:
        """process_bind_param: None → None(让 DB 走 NULL 而不是 '{}')."""
        td = JSONDict()
        assert td.process_bind_param(None, None) is None
