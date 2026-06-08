"""D4.6 — EmailClassifierAdapter 单元测试.

设计:
  - 复用 conftest 的 in-memory SQLite + EventStore fixture
  - 用伪造 ClassificationResult 模拟 D4.6 ai/classifier.py 的输出
  - 验证: 6 决策触发条件 + EventStore 落 1 条 PolicyDecisionEvent + LaneBoard add/update + Heartbeat 探活
  - 每次测试用 run_id="r-{test_name}" 显式注入, 避免 fingerprint 冲突

D4.6 测试点:
  1. factory 函数 (3 个): 类型 / 字段数 / 严判类型 (D4.5 P0 教训应用)
  2. EmailClassifierAdapter 初始化: 4 依赖可注入 / 拒空 source
  3. build_lane_entry_id: 命名 "classify:<source>:<run_id>" / 拒空 run_id
  4. record_to_lane: add (ACTIVE) → update (FINISHED) / 拒 FINISHED 状态直接 add
  5. tick_heartbeat: transport_alive 严判 bool / Liveness 3 状态
  6. classify_and_emit: 6 决策触发 / EventStore 落地 / lane / heartbeat 一气呵成
     + 严判入口 (D4.5 P0: 拒 bool 子类、负数、非 str)
     + lane_entry_id + run_id 写入 event_metadata (D4.5 v1.0.1 反馈闭环)
     + 业务字段: category + confidence 透传到 ClassifyDecisionReport

参考 EventStore API:
  - insert(event, status, source, subject_id, seq, session_id, ownership, provenance, extra, ...)
  - by_event_type(event_type, limit) 查同类型事件
  - by_subject(subject_id, limit) 查同实体事件
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.events.models import EventType  # noqa: E402
from my_ai_employee.policy.heartbeat import Liveness  # noqa: E402
from my_ai_employee.policy.integration import (  # noqa: E402
    ClassifyDecisionReport,
    EmailClassifierAdapter,
    build_classify_packet,
    build_classify_policy_context,
    compute_classification_acceptance,
)
from my_ai_employee.policy.lane_board import LaneStatus  # noqa: E402
from my_ai_employee.policy.policy_engine import (  # noqa: E402
    PolicyDecisionKind,
    PolicyEngine,
)

# ===== 测试用 ClassificationResult 仿造 =====
# ⚠️ 必须有 category (.value) / confidence / model_full_id / latency_ms
#    4 个 duck-typed 字段(与 ai/classifier.py ClassificationResult 对齐)


@dataclass(frozen=True)
class _FakeCategory:
    """仿造 EmailCategory 枚举(只暴露 .value)."""

    value: str


@dataclass(frozen=True)
class FakeClassification:
    """仿造 ClassificationResult(供 EmailClassifierAdapter.classify_and_emit 用)."""

    category: _FakeCategory
    confidence: float
    model_full_id: str
    latency_ms: int

    @classmethod
    def make(
        cls,
        category_value: str = "URGENT",
        confidence: float = 0.9,
        model_full_id: str = "deepseek/deepseek-chat",
        latency_ms: int = 1500,
    ) -> FakeClassification:
        return cls(
            category=_FakeCategory(value=category_value),
            confidence=confidence,
            model_full_id=model_full_id,
            latency_ms=latency_ms,
        )


# ============================================================
# factory 函数
# ============================================================


class TestFactoryFunctions:
    """3 个 factory 函数单元测试."""

    # ----- build_classify_packet -----

    def test_build_classify_packet_8_fields(self) -> None:
        """8 必含字段全填."""
        p = build_classify_packet(
            email_id=42,
            source="qq",
            category_value="URGENT",
            model_full_id="deepseek/deepseek-chat",
            confidence=0.9,
        )
        assert p.objective.startswith("email_classify:source=qq:id=")
        assert "ai/classifier.py" in p.scope
        assert "core/models.py" in p.scope
        assert "db:sqlcipher" in p.resources
        assert "llm:router" in p.resources
        assert len(p.acceptance_criteria) == 3
        assert p.model == "deepseek/deepseek-chat"
        assert p.provider == "deepseek"
        assert p.permission_profile == "read_only"
        assert p.recovery_policy == "retry_on_transient"

    def test_build_classify_packet_strict_type_rejection(self) -> None:
        """D4.5 P0 教训应用: 严判入口拒 bool 子类/负数/越界."""
        with pytest.raises(ValueError):
            build_classify_packet(
                email_id=True,  # type: ignore[arg-type]  # bool 是 int 子类
                source="qq",
                category_value="URGENT",
                model_full_id="m",
                confidence=0.9,
            )
        with pytest.raises(ValueError):
            build_classify_packet(
                email_id=-1,
                source="qq",
                category_value="URGENT",
                model_full_id="m",
                confidence=0.9,
            )
        with pytest.raises(ValueError):
            build_classify_packet(
                email_id=1,
                source="",
                category_value="URGENT",
                model_full_id="m",
                confidence=0.9,
            )
        with pytest.raises(ValueError):
            build_classify_packet(
                email_id=1,
                source="qq",
                category_value="",
                model_full_id="m",
                confidence=0.9,
            )
        with pytest.raises(ValueError):
            build_classify_packet(
                email_id=1,
                source="qq",
                category_value="URGENT",
                model_full_id="",
                confidence=0.9,
            )
        with pytest.raises(ValueError):
            build_classify_packet(
                email_id=1,
                source="qq",
                category_value="URGENT",
                model_full_id="m",
                confidence=1.5,  # 越界
            )
        with pytest.raises(ValueError):
            build_classify_packet(
                email_id=1,
                source="qq",
                category_value="URGENT",
                model_full_id="m",
                confidence=True,  # type: ignore[arg-type]  # bool 拒收(D4.4 P1)
            )

    def test_build_classify_packet_provider_parsing(self) -> None:
        """model_full_id 拆 provider 正确."""
        p = build_classify_packet(
            email_id=1,
            source="qq",
            category_value="TODO",
            model_full_id="minimax/MiniMax-M3",
            confidence=0.5,
        )
        assert p.provider == "minimax"
        p = build_classify_packet(
            email_id=1,
            source="qq",
            category_value="TODO",
            model_full_id="unknown",
            confidence=0.5,
        )
        assert p.provider == "unknown"  # 没有 "/" 时兜底

    # ----- compute_classification_acceptance -----

    def test_compute_acceptance_3_fields_strict(self) -> None:
        """3 字段全 True 严判 type() is bool."""
        ac = compute_classification_acceptance(
            category_value="URGENT", confidence=0.8, latency_ms=2000
        )
        assert ac == [True, True, True]
        for x in ac:
            assert type(x) is bool  # 严判(D4.4 P1 + D4.5 P0-3 教训)

    def test_compute_acceptance_confidence_low(self) -> None:
        ac = compute_classification_acceptance(
            category_value="URGENT", confidence=0.5, latency_ms=2000
        )
        assert ac == [False, True, True]

    def test_compute_acceptance_spam_filtered(self) -> None:
        """SPAM 应被过滤(走低优先级分支,不阻塞主决策)."""
        ac = compute_classification_acceptance(
            category_value="SPAM", confidence=0.9, latency_ms=2000
        )
        assert ac == [True, False, True]

    def test_compute_acceptance_latency_high(self) -> None:
        ac = compute_classification_acceptance(
            category_value="URGENT", confidence=0.8, latency_ms=6000
        )
        assert ac == [True, True, False]

    # ----- build_classify_policy_context -----

    def test_build_classify_policy_context_12_fields_strict(self) -> None:
        """12 字段全填, 严判类型."""
        ctx = build_classify_policy_context(
            category_value="URGENT",
            confidence=0.9,
            latency_ms=1500,
        )
        assert len(ctx) == 12
        assert "acceptance_results" in ctx
        assert "policy_eval_failed" in ctx
        assert type(ctx["branch_stale"]) is bool
        assert type(ctx["action_sensitive"]) is bool
        assert type(ctx["now_ms"]) is int

    def test_build_classify_policy_context_strict_type_rejection(self) -> None:
        """严判入口 (D4.5 P0 教训应用)."""
        with pytest.raises(ValueError):
            build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                consecutive_classify_failures=True,  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError):
            build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                consecutive_classify_failures=-1,
            )
        with pytest.raises(ValueError):
            build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                branch_stale="false",  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError):
            build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                now_ms="123",  # type: ignore[arg-type]
            )

    def test_build_classify_policy_context_escalate_logic(self) -> None:
        """escalate 语义: consecutive_classify_failures >= 3 → policy_eval_failed=True."""
        for cf, expected in [(0, False), (2, False), (3, True), (5, True)]:
            ctx = build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                consecutive_classify_failures=cf,
            )
            assert ctx["policy_eval_failed"] is expected, f"cf={cf}"

    def test_build_classify_policy_context_recoverable_logic(self) -> None:
        """recoverable 语义: cf > 0 AND cf < 3."""
        for cf, expected in [(0, False), (1, True), (2, True), (3, False), (5, False)]:
            ctx = build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                consecutive_classify_failures=cf,
            )
            assert ctx["last_error_recoverable"] is expected, f"cf={cf}"


# ============================================================
# EmailClassifierAdapter 初始化
# ============================================================


class TestEmailClassifierAdapterInit:
    """Adapter 初始化单元测试."""

    def test_init_with_defaults(self) -> None:
        a = EmailClassifierAdapter(source="qq")
        assert a._source == "qq"

    def test_init_rejects_empty_source(self) -> None:
        with pytest.raises(ValueError):
            EmailClassifierAdapter(source="")
        with pytest.raises(ValueError):
            EmailClassifierAdapter(source=None)  # type: ignore[arg-type]

    def test_init_with_dependencies(self) -> None:
        eng = PolicyEngine()
        a = EmailClassifierAdapter(source="outlook", engine=eng)
        assert a._engine is eng


# ============================================================
# build_lane_entry_id
# ============================================================


class TestBuildLaneEntryId:
    """build_lane_entry_id 单元测试."""

    def test_format(self) -> None:
        a = EmailClassifierAdapter(source="qq")
        assert a.build_lane_entry_id("r1") == "classify:qq:r1"

    def test_distinct_from_sync(self) -> None:
        """与 SyncPolicyAdapter 命名区分."""
        a = EmailClassifierAdapter(source="qq")
        lid = a.build_lane_entry_id("r1")
        assert lid.startswith("classify:")
        assert not lid.startswith("sync:")

    def test_rejects_empty_run_id(self) -> None:
        a = EmailClassifierAdapter(source="qq")
        with pytest.raises(ValueError):
            a.build_lane_entry_id("")
        with pytest.raises(ValueError):
            a.build_lane_entry_id(None)  # type: ignore[arg-type]


# ============================================================
# tick_heartbeat
# ============================================================


class TestTickHeartbeat:
    """tick_heartbeat 单元测试."""

    def test_healthy_when_alive_true(self) -> None:
        a = EmailClassifierAdapter(source="qq")
        liveness = a.tick_heartbeat(transport_alive=True)
        assert liveness == Liveness.HEALTHY

    def test_transport_dead_when_alive_false(self) -> None:
        a = EmailClassifierAdapter(source="qq")
        liveness = a.tick_heartbeat(transport_alive=False)
        assert liveness == Liveness.TRANSPORT_DEAD

    def test_strict_type_rejection(self) -> None:
        """D4.5 P0 修复: 拒 'true' 字符串."""
        a = EmailClassifierAdapter(source="qq")
        with pytest.raises(ValueError):
            a.tick_heartbeat(transport_alive="true")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            a.tick_heartbeat(transport_alive=1)  # type: ignore[arg-type]


# ============================================================
# classify_and_emit (主入口)
# ============================================================


class TestClassifyAndEmit:
    """classify_and_emit 主入口单元测试."""

    def test_basic_flow_emit_to_store(self, store) -> None:
        """基本流程: 评估 + 落 1 条事件 + 推 lane + 刷 heartbeat."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(
            category_value="URGENT",
            confidence=0.9,
            latency_ms=1500,
        )
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-basic-flow",
        )

        # 1) 报告字段完整
        assert isinstance(report, ClassifyDecisionReport)
        assert report.event_id is not None
        assert report.lane_entry_id.startswith("classify:qq:")
        assert report.liveness == Liveness.HEALTHY
        assert report.category == "URGENT"
        assert report.confidence == 0.9

        # 2) EventStore 落 1 条 PolicyDecisionEvent
        events = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)
        assert len(events) == 1
        ev = events[0]
        # v1.0.1 反馈闭环: lane_entry_id + run_id 写入 event_metadata
        assert "lane_entry_id" in ev.event_metadata
        assert "run_id" in ev.event_metadata
        assert ev.event_metadata["run_id"] == "r-basic-flow"

    def test_no_store_dry_run(self) -> None:
        """不传 store = 纯评估模式, event_id=None."""
        a = EmailClassifierAdapter(source="qq")  # event_store=None
        classification = FakeClassification.make()
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-dry-run",
        )
        assert report.event_id is None

    def test_spam_triggers_blocked_lane(self, store) -> None:
        """SPAM → AC[1]=False → BLOCKED + transport_dead(D4.5 P0-3 范本)."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(category_value="SPAM", confidence=0.95)
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-spam",
        )
        assert report.liveness == Liveness.TRANSPORT_DEAD
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED

    def test_low_confidence_triggers_blocked_lane(self, store) -> None:
        """置信度 < 0.7 → AC[0]=False → BLOCKED."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(confidence=0.5)
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-low-conf",
        )
        assert report.liveness == Liveness.TRANSPORT_DEAD
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED

    def test_high_latency_triggers_blocked_lane(self, store) -> None:
        """延迟 ≥ 5000ms → AC[2]=False → BLOCKED."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(latency_ms=6000)
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-high-latency",
        )
        assert report.liveness == Liveness.TRANSPORT_DEAD
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED

    def test_escalate_at_threshold_3(self, store) -> None:
        """consecutive_classify_failures >= 3 → EscalateRequired 决策触发."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make()
        a.classify_and_emit(
            email_id=1,
            classification=classification,
            consecutive_classify_failures=3,
            run_id="r-escalate",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        assert PolicyDecisionKind.ESCALATE_REQUIRED in kinds

    def test_no_escalate_below_threshold(self, store) -> None:
        """consecutive_classify_failures < 3 → 不应触发 EscalateRequired."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make()
        a.classify_and_emit(
            email_id=1,
            classification=classification,
            consecutive_classify_failures=2,
            run_id="r-no-escalate",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        assert PolicyDecisionKind.ESCALATE_REQUIRED not in kinds

    def test_run_id_custom_passes_through(self, store) -> None:
        """自定义 run_id 透传到 event_metadata + lane_entry_id."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make()
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="custom-rid-001",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        assert ev.event_metadata["run_id"] == "custom-rid-001"
        assert ev.event_metadata["lane_entry_id"] == "classify:qq:custom-rid-001"
        assert report.lane_entry_id == "classify:qq:custom-rid-001"

    def test_strict_type_rejection_email_id(self) -> None:
        """D4.5 P0 严判入口: email_id 必填原生 int >= 0(拒 bool 子类)."""
        a = EmailClassifierAdapter(source="qq")
        classification = FakeClassification.make()
        with pytest.raises(ValueError):
            a.classify_and_emit(
                email_id=True,  # type: ignore[arg-type]
                classification=classification,
                run_id="r-bad-email-id",
            )
        with pytest.raises(ValueError):
            a.classify_and_emit(
                email_id=-1,
                classification=classification,
                run_id="r-neg-email-id",
            )

    def test_strict_type_rejection_consecutive_failures(self) -> None:
        """consecutive_classify_failures 必填原生 int >= 0(拒 bool 子类)."""
        a = EmailClassifierAdapter(source="qq")
        classification = FakeClassification.make()
        with pytest.raises(ValueError):
            a.classify_and_emit(
                email_id=1,
                classification=classification,
                consecutive_classify_failures=True,  # type: ignore[arg-type]
                run_id="r-bool-cf",
            )
        with pytest.raises(ValueError):
            a.classify_and_emit(
                email_id=1,
                classification=classification,
                consecutive_classify_failures=-1,
                run_id="r-neg-cf",
            )

    def test_event_metadata_contains_business_fields(self, store) -> None:
        """业务字段 (category + confidence) 写入 event_metadata 顶层."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(
            category_value="TODO",
            confidence=0.85,
            model_full_id="qwen/qwen3-max",
        )
        a.classify_and_emit(
            email_id=42,
            classification=classification,
            run_id="r-business-fields",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        # 业务字段合并到 event_metadata 顶层(D4.3.2 决策:`meta.update(extra)`)
        meta = ev.event_metadata
        assert meta.get("category") == "TODO"
        assert meta.get("confidence") == 0.85
        assert meta.get("model_full_id") == "qwen/qwen3-max"
        assert meta.get("email_id") == 42
        assert meta.get("source") == "qq"

    def test_retry_available_at_cf_2(self, store) -> None:
        """consecutive_classify_failures=2 → RetryAvailable 触发."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make()
        a.classify_and_emit(
            email_id=1,
            classification=classification,
            consecutive_classify_failures=2,
            run_id="r-retry",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        assert PolicyDecisionKind.RETRY_AVAILABLE in kinds
