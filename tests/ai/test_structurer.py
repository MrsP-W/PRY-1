"""D9.4 — NoteStructurerService 单元测试(14 cases).

承接 D9.4 plan §4 C3:
  - NoteStore(InMemory SQLite) 注入 + LLM Provider mock 注入
  - 3 入口互斥: structure_and_emit / record_private_skip_and_emit / record_failure_and_emit
  - 数据类严判: StructuredNote / PrivateSkipDecisionReport / FailureDecisionReport
  - LLM 响应解析契约 2(裸 JSON `{"category", "tags"}`)+ 严判
  - D3.3.3 异常范围窄化(OperationalError 透传 record_failure_and_emit)

设计(沿 tests/ai/test_drafter_adapter.py 范本):
  - 复用 conftest in-memory SQLite + NoteStore fixture
  - 用 FakeLLMRouter 模拟 LLMRouter.route 返回固定 LLMResponse
  - 验证: 3 入口返回值类型 + tags 写入 NoteStore.tags 字段 + 业务阻断不计入失败累加
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.ai.note_structurer import (  # noqa: E402
    FailureDecisionReport,
    NoteStructurerService,
    PrivateSkipDecisionReport,
    StructuredNote,
    _parse_structurer_response,
)
from my_ai_employee.ai.providers import LLMError, LLMResponse, LLMResponseError  # noqa: E402
from my_ai_employee.db.notes import Note, NoteStore  # noqa: E402

# ===== Fixtures(InMemory SQLite + NoteStore,沿 D9.1 test_notes.py 范本)=====


@pytest.fixture
def engine():
    """InMemory SQLite + Note ORM 10 列 create_all."""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.notes import Note  # noqa: F401, F811

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory) -> NoteStore:
    return NoteStore(session_factory)


# ===== Fake LLM Router(沿 D4.7.3 v1.0.6 范本 duck type)=====


@dataclass
class FakeLLMResponse:
    """沿 D4.7.3 v1.0.6 范本 duck type 模拟 LLMResponse."""

    content: str
    model_full_id: str = "deepseek/deepseek-chat"
    input_tokens: int = 100
    output_tokens: int = 50
    latency_ms: int = 1500


class FakeLLMRouter:
    """Fake LLMRouter,返回预设 content(供测试用).

    D9.4 范本: route() 接受 (task_type, messages, temperature, max_tokens) 4 个位置参,
    返回 LLMResponse. Test 期间可预设 content(成功 / 失败 JSON / markdown 包裹).
    """

    def __init__(self, content: str = "", *, raise_error: BaseException | None = None) -> None:
        self._content = content
        self._raise = raise_error
        self.calls: list[dict[str, Any]] = []

    def route(
        self,
        task_type: Any,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self.calls.append(
            {
                "task_type": task_type,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self._raise is not None:
            raise self._raise
        return LLMResponse(
            content=self._content,
            model_full_id="deepseek/deepseek-chat",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1500,
        )


def _insert_note(
    store: NoteStore,
    *,
    apple_note_id: str,
    is_private: bool = False,
    body: str = "测试正文",
    title: str = "测试标题",
) -> Note:
    """便捷 helper: 插入一条 note 供 structurer 测试."""
    return store.insert(
        apple_note_id=apple_note_id,
        folder="Notes",
        title=title,
        body=body,
        updated_at_ms=1700000000000,
        is_private=is_private,
    )


# ===== 1. 初始化严判(2 tests)=====


class TestInit:
    """NoteStructurerService 初始化严判(必传 store + llm_provider)."""

    def test_init_with_required_deps(self, store: NoteStore) -> None:
        """1.1 必传 store + llm_provider 可正常初始化."""
        svc = NoteStructurerService(store=store, llm_provider=FakeLLMRouter())
        assert svc._store is store
        assert svc._llm is not None
        assert svc._event_store is None  # 默认 None

    def test_init_rejects_none_deps(self, store: NoteStore) -> None:
        """1.2 store/llm_provider=None 抛 ValueError(沿 D4.7.3 v1.0.5 范本)."""
        with pytest.raises(ValueError, match="store 必传非 None"):
            NoteStructurerService(store=None, llm_provider=FakeLLMRouter())  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="llm_provider 必传非 None"):
            NoteStructurerService(store=store, llm_provider=None)  # type: ignore[arg-type]


# ===== 2. structure_and_emit 成功路径(1 test)=====


class TestStructureAndEmitSuccess:
    """成功路径: LLM 返回合法 JSON → 写 tags → 返回 StructuredNote."""

    def test_success_writes_tags_to_store(self, store: NoteStore) -> None:
        """2.1 成功主路径: LLM 合法响应 → StructuredNote + NoteStore.tags 写入."""
        _insert_note(store, apple_note_id="x-coredata://note-001", body="项目周会讨论 Q3 路线图")
        llm = FakeLLMRouter(
            content='{"category": "URGENT", "tags": ["周会", "Q3", "路线图", "项目"]}'
        )
        svc = NoteStructurerService(store=store, llm_provider=llm)

        result = svc.structure_and_emit("x-coredata://note-001")

        assert isinstance(result, StructuredNote)
        assert result.apple_note_id == "x-coredata://note-001"
        assert result.category == "URGENT"
        assert result.tags == ["周会", "Q3", "路线图", "项目"]
        assert result.model_full_id == "deepseek/deepseek-chat"
        assert result.latency_ms == 1500
        assert result.body_length == len("项目周会讨论 Q3 路线图")

        # NoteStore 写 tags 验证
        note = store.find_by_apple_id("x-coredata://note-001")
        assert note is not None
        assert note.tags == "周会,Q3,路线图,项目"
        # synced_at_ms 已被 mark_structured 覆盖到当前时间
        assert note.synced_at_ms > 1700000000000  # 大于 inserted 时的时间戳


# ===== 3. structure_and_emit 业务阻断(1 test)=====


class TestStructureAndEmitPrivateSkip:
    """业务阻断: is_private=True 笔记跳过 LLM → PrivateSkipDecisionReport."""

    def test_private_note_skips_llm(self, store: NoteStore) -> None:
        """3.1 is_private=True 笔记不调 LLM, 直接返回 PrivateSkipDecisionReport."""
        _insert_note(store, apple_note_id="x-coredata://priv-001", is_private=True)
        llm = FakeLLMRouter(content='{"category": "TODO", "tags": ["a", "b", "c", "d"]}')
        svc = NoteStructurerService(store=store, llm_provider=llm)

        result = svc.structure_and_emit("x-coredata://priv-001")

        assert isinstance(result, PrivateSkipDecisionReport)
        assert result.apple_note_id == "x-coredata://priv-001"
        assert result.reason == "is_private"
        assert result.kind == "business_blocked"
        # 业务阻断不调 LLM
        assert len(llm.calls) == 0
        # NoteStore.tags 仍为 None(未调用 mark_structured)
        note = store.find_by_apple_id("x-coredata://priv-001")
        assert note is not None
        assert note.tags is None


# ===== 4. structure_and_emit 业务失败路径(2 tests)=====


class TestStructureAndEmitFailure:
    """技术失败: note 不存在 / LLM 异常 → FailureDecisionReport."""

    def test_note_not_found_returns_failure(self, store: NoteStore) -> None:
        """4.1 apple_note_id 不存在 → FailureDecisionReport(reason='db_failure')."""
        llm = FakeLLMRouter(content='{"category": "TODO", "tags": ["a", "b", "c", "d"]}')
        svc = NoteStructurerService(store=store, llm_provider=llm)

        result = svc.structure_and_emit("x-coredata://nonexistent")

        assert isinstance(result, FailureDecisionReport)
        assert result.apple_note_id == "x-coredata://nonexistent"
        assert result.reason == "db_failure"
        assert result.consecutive_failures == 1
        assert result.kind == "technical_failure"
        assert result.failed is True
        assert "不存在" in result.last_error  # NoteNotFoundError 信息
        # 业务失败不调 LLM(在查 note 阶段就阻断)
        assert len(llm.calls) == 0

    def test_llm_error_returns_failure(self, store: NoteStore) -> None:
        """4.2 LLM 异常 → FailureDecisionReport(reason='llm_failure')."""
        _insert_note(store, apple_note_id="x-coredata://note-002")
        llm_error = LLMError("全链 fallback 失败,primary=down")
        llm = FakeLLMRouter(content="", raise_error=llm_error)
        svc = NoteStructurerService(store=store, llm_provider=llm)

        result = svc.structure_and_emit("x-coredata://note-002")

        assert isinstance(result, FailureDecisionReport)
        assert result.reason == "llm_failure"
        assert result.consecutive_failures == 1
        assert "全链 fallback" in result.last_error


# ===== 5. structure_and_emit LLM 响应解析失败(1 test)=====


class TestStructureAndEmitLLMResponseParse:
    """LLM 响应非严格 JSON → FailureDecisionReport(reason='llm_failure')."""

    def test_invalid_json_returns_failure(self, store: NoteStore) -> None:
        """5.1 LLM 响应非 JSON(契约 2 拒 markdown 包裹)→ FailureDecisionReport."""
        _insert_note(store, apple_note_id="x-coredata://note-003")
        llm = FakeLLMRouter(content='```json\n{"category": "TODO"}\n```')  # markdown 包裹
        svc = NoteStructurerService(store=store, llm_provider=llm)

        result = svc.structure_and_emit("x-coredata://note-003")

        assert isinstance(result, FailureDecisionReport)
        assert result.reason == "llm_failure"
        assert "严格 JSON" in result.last_error or "非严格 JSON" in result.last_error


# ===== 6. record_private_skip_and_emit 独立入口(2 tests)=====


class TestRecordPrivateSkip:
    """record_private_skip_and_emit 独立入口(直接调,不走 LLM)."""

    def test_returns_private_skip_report(self, store: NoteStore) -> None:
        """6.1 正常入口返回 PrivateSkipDecisionReport."""
        llm = FakeLLMRouter()
        svc = NoteStructurerService(store=store, llm_provider=llm)

        report = svc.record_private_skip_and_emit("x-coredata://priv-002")

        assert isinstance(report, PrivateSkipDecisionReport)
        assert report.apple_note_id == "x-coredata://priv-002"
        assert report.reason == "is_private"
        assert report.kind == "business_blocked"
        # 不调 LLM
        assert len(llm.calls) == 0

    def test_rejects_invalid_apple_note_id(self, store: NoteStore) -> None:
        """6.2 严判 apple_note_id: type 错 / 空字符串 抛 ValueError."""
        llm = FakeLLMRouter()
        svc = NoteStructurerService(store=store, llm_provider=llm)

        with pytest.raises(ValueError, match="apple_note_id 必须是 str"):
            svc.record_private_skip_and_emit(123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="apple_note_id 必非空"):
            svc.record_private_skip_and_emit("")  # 空白
        with pytest.raises(ValueError, match="apple_note_id 必非空"):
            svc.record_private_skip_and_emit("   ")  # 纯空白


# ===== 7. record_failure_and_emit 独立入口(3 tests)=====


class TestRecordFailure:
    """record_failure_and_emit 独立入口(LLM/DB 失败转 FailureDecisionReport)."""

    def test_llm_failure_reason(self, store: NoteStore) -> None:
        """7.1 reason='llm_failure' 正常入口."""
        llm = FakeLLMRouter()
        svc = NoteStructurerService(store=store, llm_provider=llm)

        report = svc.record_failure_and_emit(
            "x-coredata://note-004",
            LLMError("test"),
            reason="llm_failure",
            consecutive_failures=1,
        )

        assert isinstance(report, FailureDecisionReport)
        assert report.apple_note_id == "x-coredata://note-004"
        assert report.reason == "llm_failure"
        assert report.consecutive_failures == 1
        assert report.kind == "technical_failure"
        assert report.failed is True

    def test_db_failure_reason(self, store: NoteStore) -> None:
        """7.2 reason='db_failure' 正常入口(沿 D3.3.3 范本,OperationalError 透传)."""
        llm = FakeLLMRouter()
        svc = NoteStructurerService(store=store, llm_provider=llm)

        report = svc.record_failure_and_emit(
            "x-coredata://note-005",
            OperationalError("DB 锁 5s 后超时", None, None),  # type: ignore[arg-type]
            reason="db_failure",
            consecutive_failures=2,
        )

        assert isinstance(report, FailureDecisionReport)
        assert report.reason == "db_failure"
        assert report.consecutive_failures == 2
        assert "DB 锁" in report.last_error

    def test_rejects_invalid_reason_and_cf(self, store: NoteStore) -> None:
        """7.3 严判 reason 白名单 + consecutive_failures 必 >= 1."""
        llm = FakeLLMRouter()
        svc = NoteStructurerService(store=store, llm_provider=llm)

        # 非法 reason
        with pytest.raises(ValueError, match="reason 必须在"):
            svc.record_failure_and_emit(
                "x-coredata://note-006",
                LLMError("test"),
                reason="other_failure",  # type: ignore[arg-type]
            )
        # cf=0 非法
        with pytest.raises(ValueError, match="consecutive_failures 必须是原生 int"):
            svc.record_failure_and_emit(
                "x-coredata://note-007",
                LLMError("test"),
                reason="llm_failure",
                consecutive_failures=0,
            )


# ===== 8. 数据类严判(2 tests)=====


class TestDataClasses:
    """3 类可观测报告数据类 __post_init__ 严判."""

    def test_structured_note_validates_6_fields(self) -> None:
        """8.1 StructuredNote 6 字段严判(type / 范围 / 长度 / 白名单).

        沿 D4.7.3 v1.0.5 P1 范本: 工厂层 + 数据类双层防御.
        """
        # 合法构造
        note = StructuredNote(
            apple_note_id="x-coredata://note-ok",
            category="URGENT",
            tags=["a", "b", "c"],
            model_full_id="deepseek/deepseek-chat",
            latency_ms=1500,
            body_length=100,
        )
        assert note.category == "URGENT"
        assert note.tags == ["a", "b", "c"]

        # 非法 category
        with pytest.raises(ValueError, match="category 必须在"):
            StructuredNote(
                apple_note_id="x-coredata://note-bad",
                category="OOPS",
                tags=["a", "b", "c"],
                model_full_id="m",
                latency_ms=1500,
                body_length=100,
            )
        # tags 太短(< 3)
        with pytest.raises(ValueError, match="tags 长度必须在"):
            StructuredNote(
                apple_note_id="x-coredata://note-bad",
                category="URGENT",
                tags=["a", "b"],  # 只 2 个
                model_full_id="m",
                latency_ms=1500,
                body_length=100,
            )
        # latency_ms 负数
        with pytest.raises(ValueError, match="latency_ms 必须是原生 int"):
            StructuredNote(
                apple_note_id="x-coredata://note-bad",
                category="URGENT",
                tags=["a", "b", "c"],
                model_full_id="m",
                latency_ms=-1,
                body_length=100,
            )

    def test_failure_decision_report_validates(self) -> None:
        """8.2 FailureDecisionReport 严判 failed=True + reason 白名单 + cf >= 1."""
        # 合法构造
        rep = FailureDecisionReport(
            apple_note_id="x-coredata://note-008",
            last_error="LLM 失败",
            consecutive_failures=1,
            reason="llm_failure",
        )
        assert rep.failed is True
        assert rep.kind == "technical_failure"
        assert rep.reason == "llm_failure"

        # 非法 reason
        with pytest.raises(ValueError, match="reason 必须在"):
            FailureDecisionReport(
                apple_note_id="x-coredata://note-009",
                last_error="test",
                consecutive_failures=1,
                reason="other",  # type: ignore[arg-type]
            )
        # cf=0 非法(技术失败必填 >= 1)
        with pytest.raises(ValueError, match="consecutive_failures 必须是 int"):
            FailureDecisionReport(
                apple_note_id="x-coredata://note-010",
                last_error="test",
                consecutive_failures=0,
                reason="llm_failure",
            )
        # 空白 last_error
        with pytest.raises(ValueError, match="last_error 必填非空白"):
            FailureDecisionReport(
                apple_note_id="x-coredata://note-011",
                last_error="   ",
                consecutive_failures=1,
                reason="llm_failure",
            )


# ===== 9. _parse_structurer_response 严判(1 test)=====


class TestParseResponse:
    """裸 JSON 契约解析 helper 测试."""

    def test_rejects_markdown_wrapped(self) -> None:
        """9.1 拒 markdown 包裹(契约 2 严格,沿 drafter 范本)."""
        with pytest.raises(LLMResponseError, match="非严格 JSON"):
            _parse_structurer_response('```json\n{"category": "TODO"}\n```')

    def test_rejects_invalid_category(self) -> None:
        """9.2 非法 category 抛 LLMResponseError(透传到 Adapter 走技术失败)."""
        with pytest.raises(LLMResponseError, match="category 非法"):
            _parse_structurer_response('{"category": "OOPS", "tags": ["a", "b", "c"]}')

    def test_rejects_too_few_tags(self) -> None:
        """9.3 tags < 3 抛 LLMResponseError."""
        with pytest.raises(LLMResponseError, match="tags 非法"):
            _parse_structurer_response('{"category": "URGENT", "tags": ["a", "b"]}')

    def test_parses_valid_response(self) -> None:
        """9.4 合法响应解析成功."""
        category, tags = _parse_structurer_response(
            '{"category": "PERSONAL", "tags": ["日记", "感想", "晨间"]}'
        )
        assert category == "PERSONAL"
        assert tags == ["日记", "感想", "晨间"]
