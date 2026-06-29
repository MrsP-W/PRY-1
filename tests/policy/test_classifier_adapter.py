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

D4.6 v1.0.1 增量测试(2026-06-09 用户复检 P1-2 + P1-3 + P2-5):
  - TestD46V101AdapterFixes 类(末尾追加)
  - P1-2: transport_alive 显式参数,与 business_accepted 解耦
  - P2-5: classification duck type 严判,拒 bool/str coerce

参考 EventStore API:
  - insert(event, status, source, subject_id, seq, session_id, ownership, provenance, extra, ...)
  - by_event_type(event_type, limit) 查同类型事件
  - by_subject(subject_id, limit) 查同实体事件
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.events.models import EventType  # noqa: E402
from my_ai_employee.policy.heartbeat import Liveness  # noqa: E402
from my_ai_employee.policy.integration import (  # noqa: E402
    ClassifyDecisionReport,
    ClassifyFailureDecisionReport,
    EmailClassifierAdapter,
    build_classify_failure_packet,
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
                email_id=True,
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
                confidence=True,
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
                consecutive_classify_failures=True,
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
        """escalate 语义(D4.6 v1.0.1 P1-3): last_classify_failed AND cf >= 3.

        新版需 last_classify_failed=True 才触发 policy_eval_failed;
        默认 last_classify_failed=False 时 cf 任意值都不升级。
        """
        # last_classify_failed=False(默认): cf 多少都不升级
        for cf in [0, 2, 3, 5, 100]:
            ctx = build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                consecutive_classify_failures=cf,
            )
            assert ctx["policy_eval_failed"] is False, f"failed=False, cf={cf}"

        # last_classify_failed=True: cf >= 3 才升级
        for cf, expected in [(0, False), (2, False), (3, True), (5, True)]:
            ctx = build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                last_classify_failed=True,
                consecutive_classify_failures=cf,
            )
            assert ctx["policy_eval_failed"] is expected, f"failed=True, cf={cf}"

    def test_build_classify_policy_context_recoverable_logic(self) -> None:
        """recoverable 语义(D4.6 v1.0.1 P1-3): last_classify_failed AND 0 < cf < 3.

        新版需 last_classify_failed=True 才看 cf 范围;
        默认 last_classify_failed=False 时 cf 多少都不 recoverable。
        """
        # last_classify_failed=False(默认): cf 多少都不 recoverable
        for cf in [0, 1, 2, 3, 5]:
            ctx = build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                consecutive_classify_failures=cf,
            )
            assert ctx["last_error_recoverable"] is False, f"failed=False, cf={cf}"

        # last_classify_failed=True: 0 < cf < 3 才 recoverable
        for cf, expected in [(0, False), (1, True), (2, True), (3, False), (5, False)]:
            ctx = build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                last_classify_failed=True,
                consecutive_classify_failures=cf,
            )
            assert ctx["last_error_recoverable"] is expected, f"failed=True, cf={cf}"

    def test_build_classify_policy_context_last_failed_wrong_type(self) -> None:
        """D4.6 v1.0.1 P1-3 严判入口: last_classify_failed 必须是原生 bool."""
        with pytest.raises(ValueError, match="last_classify_failed"):
            build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                last_classify_failed="true",  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError, match="last_classify_failed"):
            build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=1000,
                last_classify_failed=1,  # type: ignore[arg-type]
            )


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

    def test_basic_flow_emit_to_store(self, store: Any) -> None:
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

    def test_spam_triggers_blocked_lane(self, store: Any) -> None:
        """SPAM → AC[1]=False → Lane=BLOCKED + Heartbeat=HEALTHY(D4.6 v1.0.1 P1-2).

        v1.0.1 修复: SPAM 业务拒绝 ≠ LLM 死了。Lane 用 business_accepted,
        Heartbeat 用 transport_alive(默认 True,LLM 调用成功)。
        """
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(category_value="SPAM", confidence=0.95)
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-spam",
        )
        # Lane: 业务拒绝 → BLOCKED
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED
        # Heartbeat: LLM 调用成功 → HEALTHY(P1-2 修复后 transport_alive 不再耦合业务)
        assert report.liveness == Liveness.HEALTHY

    def test_low_confidence_triggers_blocked_lane(self, store: Any) -> None:
        """置信度 < 0.7 → Lane=BLOCKED + Heartbeat=HEALTHY(D4.6 v1.0.1 P1-2)."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(confidence=0.5)
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-low-conf",
        )
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED
        assert report.liveness == Liveness.HEALTHY

    def test_high_latency_triggers_blocked_lane(self, store: Any) -> None:
        """延迟 ≥ 5000ms → Lane=BLOCKED + Heartbeat=HEALTHY(D4.6 v1.0.1 P1-2)."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(latency_ms=6000)
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-high-latency",
        )
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED
        assert report.liveness == Liveness.HEALTHY

    def test_escalate_at_threshold_3(self, store: Any) -> None:
        """D4.6 v1.0.2 P1-1 修复: 失败入口走 record_classify_failure_and_emit, cf >= 3 → EscalateRequired.

        v1.0 旧逻辑: 成功路径 + consecutive_classify_failures=3 → EscalateRequired 误触发
        v1.0.1 引入 last_classify_failed,但允许同时传 成功 classification,状态耦合
        v1.0.2 拆入口: 失败走 record_classify_failure_and_emit, 永不触发 merge
        """
        a = EmailClassifierAdapter(source="qq", event_store=store)
        a.record_classify_failure_and_emit(
            email_id=1,
            last_error="simulated LLM timeout",
            consecutive_classify_failures=3,
            run_id="r-escalate",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        assert PolicyDecisionKind.ESCALATE_REQUIRED in kinds

    def test_no_escalate_below_threshold(self, store: Any) -> None:
        """consecutive_classify_failures < 3 → 不应触发 EscalateRequired."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        a.record_classify_failure_and_emit(
            email_id=1,
            last_error="transient network",
            consecutive_classify_failures=2,
            run_id="r-no-escalate",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        assert PolicyDecisionKind.ESCALATE_REQUIRED not in kinds

    def test_run_id_custom_passes_through(self, store: Any) -> None:
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
                email_id=True,
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
        """D4.6 v1.0.2 P1-1 修复: 成功入口无 cf 参数(移到失败入口,必填 >= 1)."""
        a = EmailClassifierAdapter(source="qq")
        classification = FakeClassification.make()
        # 成功入口不能再传 consecutive_classify_failures(P1-1 强制拆入口)
        with pytest.raises(TypeError):
            a.classify_and_emit(  # type: ignore[call-arg]
                email_id=1,
                classification=classification,
                consecutive_classify_failures=2,
                run_id="r-no-cf-on-success",
            )
        # 失败入口 cf 必填 >= 1
        with pytest.raises(ValueError):
            a.record_classify_failure_and_emit(
                email_id=1,
                last_error="x",
                consecutive_classify_failures=0,  # < 1 拒收
                run_id="r-cf-zero",
            )
        with pytest.raises(ValueError):
            a.record_classify_failure_and_emit(
                email_id=1,
                last_error="x",
                consecutive_classify_failures=True,
                run_id="r-bool-cf",
            )

    def test_event_metadata_contains_business_fields(self, store: Any) -> None:
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

    def test_retry_available_at_cf_2(self, store: Any) -> None:
        """D4.6 v1.0.2 P1-1 修复: 失败入口 cf=2 → RetryAvailable.

        v1.0.1 引入 last_classify_failed 但允许同时传 成功 classification。
        v1.0.2 拆入口: 失败走 record_classify_failure_and_emit(cf=2) → retry。
        """
        a = EmailClassifierAdapter(source="qq", event_store=store)
        a.record_classify_failure_and_emit(
            email_id=1,
            last_error="transient network",
            consecutive_classify_failures=2,
            run_id="r-retry",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        assert PolicyDecisionKind.RETRY_AVAILABLE in kinds


# ============================================================
# D4.6 v1.0.1 业务语义修复测试(2026-06-09 用户复检)
# ============================================================


class TestD46V101AdapterFixes:
    """D4.6 v1.0.1 Adapter 层业务语义修复测试.

    覆盖用户 6/9 晨间复检的 P1-2 + P2-5。
    P1-1 由 tests/ai/test_classifier.py::TestD46V101Fixes 覆盖。
    P1-3 由上方的 test_build_classify_policy_context_* 系列覆盖。
    """

    # --- P1-2: transport_alive 显式参数 + 业务/传输解耦 ---

    def test_transport_alive_false_triggers_transport_dead(self, store: Any) -> None:
        """P1-2 修复: transport_alive=False → Heartbeat=TRANSPORT_DEAD(与业务无关)."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make()  # 业务验收通过
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            transport_alive=False,  # 关键: 显式标记 LLM 死了
            run_id="r-v101-transport-dead",
        )
        # 业务通过 → Lane FINISHED; 但 transport_alive=False → Heartbeat TRANSPORT_DEAD
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.FINISHED
        assert report.liveness == Liveness.TRANSPORT_DEAD

    def test_business_rejected_but_transport_alive(self, store: Any) -> None:
        """P1-2 修复: SPAM/低置信度 → Lane BLOCKED + Heartbeat HEALTHY(LLM 没死)."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make(category_value="SPAM", confidence=0.95)
        report = a.classify_and_emit(
            email_id=1,
            classification=classification,
            transport_alive=True,  # 显式声明 LLM 活着
            run_id="r-v101-biz-reject-transport-alive",
        )
        # 业务拒绝 → Lane BLOCKED; transport_alive=True → Heartbeat HEALTHY
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED
        assert report.liveness == Liveness.HEALTHY

    def test_transport_alive_wrong_type_rejected(self) -> None:
        """P1-2 严判入口: transport_alive 必须是原生 bool."""
        a = EmailClassifierAdapter(source="qq")
        classification = FakeClassification.make()
        with pytest.raises(ValueError, match="transport_alive"):
            a.classify_and_emit(
                email_id=1,
                classification=classification,
                transport_alive=1,  # type: ignore[arg-type]
                run_id="r-bool-transport",
            )
        with pytest.raises(ValueError, match="transport_alive"):
            a.classify_and_emit(
                email_id=1,
                classification=classification,
                transport_alive="true",  # type: ignore[arg-type]
                run_id="r-str-transport",
            )

    # --- P2-5: classification duck type 严判,拒 bool/str 静默 coerce ---

    def test_duck_type_rejects_bool_confidence(self) -> None:
        """P2-5 修复: confidence=True 旧版 float() → 1.0 通过; 新版严判拒收."""
        a = EmailClassifierAdapter(source="qq")

        @dataclass
        class BadConfBool:
            category_value: str = "URGENT"
            confidence: object = True
            model_full_id: str = "deepseek/deepseek-chat"
            latency_ms: int = 1000

            @property
            def category(self) -> Any:
                class _C:
                    value = self.category_value

                return _C()

        with pytest.raises(ValueError, match="confidence"):
            a.classify_and_emit(
                email_id=1,
                classification=BadConfBool(),
                run_id="r-v101-bool-conf",
            )

    def test_duck_type_rejects_str_confidence(self) -> None:
        """P2-5 修复: confidence='0.5' 旧版 float() → 0.5 通过; 新版严判拒收."""
        a = EmailClassifierAdapter(source="qq")

        @dataclass
        class BadConfStr:
            category_value: str = "URGENT"
            confidence: object = "0.5"
            model_full_id: str = "deepseek/deepseek-chat"
            latency_ms: int = 1000

            @property
            def category(self) -> Any:
                class _C:
                    value = self.category_value

                return _C()

        with pytest.raises(ValueError, match="confidence"):
            a.classify_and_emit(
                email_id=1,
                classification=BadConfStr(),
                run_id="r-v101-str-conf",
            )

    def test_duck_type_rejects_bool_latency(self) -> None:
        """P2-5 修复: latency_ms=True 旧版 int() → 1 通过; 新版严判拒收."""
        a = EmailClassifierAdapter(source="qq")

        @dataclass
        class BadLatencyBool:
            category_value: str = "URGENT"
            confidence: float = 0.9
            model_full_id: str = "deepseek/deepseek-chat"
            latency_ms: object = True

            @property
            def category(self) -> Any:
                class _C:
                    value = self.category_value

                return _C()

        with pytest.raises(ValueError, match="latency_ms"):
            a.classify_and_emit(
                email_id=1,
                classification=BadLatencyBool(),
                run_id="r-v101-bool-lat",
            )

    # --- P1-3 联动: 成功路径 last_classify_failed 默认 False,不触发 retry ---

    def test_successful_classify_does_not_trigger_retry(self, store: Any) -> None:
        """D4.6 v1.0.2 P1-1 修复: 成功入口永不触发 retry / escalate.

        v1.0 旧逻辑: 成功分类 + cf=2 → RETRY_AVAILABLE 误触发
        v1.0.1 引入 last_classify_failed=False → 强制 recoverable=False
        v1.0.2 拆入口: classify_and_emit 无 last_classify_failed / cf 参数,
          永不可能触发 retry / escalate
        """
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make()
        a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-v102-success-no-retry",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        assert PolicyDecisionKind.RETRY_AVAILABLE not in kinds
        assert PolicyDecisionKind.ESCALATE_REQUIRED not in kinds


# ============================================================
# D4.6 v1.0.2 业务语义修复测试(2026-06-09 第二次复检)
# ============================================================


class TestD46V102AdapterFixes:
    """D4.6 v1.0.2 Adapter 层业务语义修复测试.

    覆盖用户 6/9 第二次复检的 P1-1 + P1-2 + P2-5。
    P2-3 + P2-4 由 tests/ai/test_classifier.py::TestD46V102Fixes 覆盖(ai 层)。
    """

    # --- P1-1: 成功入口强制失败次数归零 ---

    def test_success_entry_no_failure_params(self, store: Any) -> None:
        """P1-1 修复: classify_and_emit 签名删除 last_classify_failed / consecutive_classify_failures.

        v1.0.1 允许传 last_classify_failed=True + 成功 classification → 状态耦合
        v1.0.2 拆入口: 成功入口无失败参数,从根上断绝
        """
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make()
        # 1) 成功入口不再接受 cf 参数
        with pytest.raises(TypeError):
            a.classify_and_emit(  # type: ignore[call-arg]
                email_id=1,
                classification=classification,
                consecutive_classify_failures=99,
                run_id="r-v102-no-cf",
            )
        # 2) 成功入口不再接受 last_classify_failed 参数
        with pytest.raises(TypeError):
            a.classify_and_emit(  # type: ignore[call-arg]
                email_id=1,
                classification=classification,
                last_classify_failed=True,
                run_id="r-v102-no-last-failed",
            )

    def test_success_and_failure_never_coexist(self, store: Any) -> None:
        """P1-1 修复: 成功入口不触发 retry / escalate,失败入口不触发 merge."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        classification = FakeClassification.make()  # 业务通过

        # 成功入口 → merge_only(无 retry / escalate)
        a.classify_and_emit(
            email_id=1,
            classification=classification,
            run_id="r-v102-success-only",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        success_kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        assert PolicyDecisionKind.RETRY_AVAILABLE not in success_kinds
        assert PolicyDecisionKind.ESCALATE_REQUIRED not in success_kinds

    def test_failure_entry_no_merge(self, store: Any) -> None:
        """P1-1 修复: 失败入口触发 retry / escalate,但不触发 merge.

        旧 v1.0.1: 成功 classification + last_classify_failed=True + cf=3
        → merge_required + escalate_required 同时触发
        新 v1.0.2: 失败入口走 synthetic AC[0]=False → 永不 merge
        """
        a = EmailClassifierAdapter(source="qq", event_store=store)
        a.record_classify_failure_and_emit(
            email_id=1,
            last_error="LLM timeout",
            consecutive_classify_failures=3,
            run_id="r-v102-fail-no-merge",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        failure_kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
        # 失败入口必须触发 escalate(因为 cf=3)
        assert PolicyDecisionKind.ESCALATE_REQUIRED in failure_kinds
        # 失败入口不能触发 merge(AC[0]=False,无业务合并意义)
        assert PolicyDecisionKind.MERGE_REQUIRED not in failure_kinds

    def test_failure_entry_under_threshold_triggers_retry(self, store: Any) -> None:
        """P1-1 修复: 失败入口 cf=1/2 → RETRY_AVAILABLE(不 escalate)."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        for cf in (1, 2):
            run_id = f"r-v102-fail-cf-{cf}"
            a.record_classify_failure_and_emit(
                email_id=1,
                last_error="transient",
                consecutive_classify_failures=cf,
                run_id=run_id,
            )
        events = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)
        for ev in events:
            kinds = [d["kind"] for d in ev.event_metadata["all_decisions"]]
            assert PolicyDecisionKind.RETRY_AVAILABLE in kinds
            assert PolicyDecisionKind.ESCALATE_REQUIRED not in kinds

    def test_failure_entry_payload_marks_failed(self, store: Any) -> None:
        """P1-1 修复: 失败入口 event_metadata 顶层有 failed=True + last_error."""
        a = EmailClassifierAdapter(source="qq", event_store=store)
        a.record_classify_failure_and_emit(
            email_id=42,
            last_error="HTTP 502 from upstream",
            consecutive_classify_failures=2,
            run_id="r-v102-fail-payload",
        )
        ev = store.by_event_type(EventType.POLICY_DECISION_MADE, limit=10)[0]
        meta = ev.event_metadata
        assert meta["failed"] is True
        assert "HTTP 502" in meta["last_error"]
        assert meta["consecutive_classify_failures"] == 2
        assert meta["email_id"] == 42
        assert meta["source"] == "qq"

    # --- P1-2: 严判 category 5 类 + latency_ms >= 0 ---

    def test_category_not_in_5_classes_rejected(self) -> None:
        """P1-2 修复: category 不在 5 类枚举 → ValueError(不触发 merge)."""
        a = EmailClassifierAdapter(source="qq")
        bad_classification = FakeClassification.make(category_value="OOPS")
        with pytest.raises(ValueError, match="5 类之一"):
            a.classify_and_emit(
                email_id=1,
                classification=bad_classification,
                run_id="r-v102-bad-category",
            )

    def test_latency_negative_rejected(self) -> None:
        """P1-2 修复: latency_ms < 0 → ValueError(防御时钟回退)."""
        a = EmailClassifierAdapter(source="qq")
        bad_classification = FakeClassification.make(latency_ms=-1)
        with pytest.raises(ValueError, match="latency_ms"):
            a.classify_and_emit(
                email_id=1,
                classification=bad_classification,
                run_id="r-v102-neg-latency",
            )

    # --- P2-5: build_classify_packet 拒 NaN/Inf ---

    def test_build_classify_packet_nan_rejected(self) -> None:
        """P2-5 修复: confidence=NaN 旧版 0<=NaN<=1 False 通过; 新版 isfinite 拒."""
        with pytest.raises(ValueError, match="NaN/Inf"):
            build_classify_packet(
                email_id=1,
                source="qq",
                category_value="URGENT",
                model_full_id="m",
                confidence=float("nan"),
            )

    def test_build_classify_packet_inf_rejected(self) -> None:
        """P2-5 修复: confidence=Inf / -Inf 拒收."""
        for bad in (float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="NaN/Inf"):
                build_classify_packet(
                    email_id=1,
                    source="qq",
                    category_value="URGENT",
                    model_full_id="m",
                    confidence=bad,
                )

    # --- P1-1 联动: build_classify_failure_packet factory 严判 ---

    def test_build_classify_failure_packet_strict(self) -> None:
        """P1-1 新增 factory: 严判 email_id / source / last_error_str / cf >= 1."""
        # 缺 last_error_str
        with pytest.raises(ValueError):
            build_classify_failure_packet(
                email_id=1,
                source="qq",
                last_error_str="",
                consecutive_classify_failures=1,
            )
        # cf=0 拒收
        with pytest.raises(ValueError):
            build_classify_failure_packet(
                email_id=1,
                source="qq",
                last_error_str="err",
                consecutive_classify_failures=0,
            )
        # 正常
        p = build_classify_failure_packet(
            email_id=42,
            source="qq",
            last_error_str="LLM timeout",
            consecutive_classify_failures=2,
        )
        assert p.objective.startswith("email_classify_failed:source=qq:id=42")
        assert len(p.acceptance_criteria) == 3
        assert "last_error=LLM timeout" in p.acceptance_criteria[0]


# ============================================================
# D4.6 v1.0.2 二次复检修复测试(2026-06-09 早晨第二次复检 4 项)
# ============================================================


class TestD46V102SecondPassFixes:
    """D4.6 v1.0.2 二次复检 4 项修复测试.

    覆盖用户 6/9 早晨第二次复检的 1 P1 + 2 P2 + 1 P3:
      - P1: 公开 helper 严判下沉(compute_classification_acceptance +
        build_classify_policy_context 加严判,防止 Adapter 重构后绕过)
      - P2-2: 失败报告独立数据类(ClassifyFailureDecisionReport,不再用空 category
        违反 ClassifyDecisionReport "category: 5 类" 契约)
      - P2-3: 顶层导出 build_classify_failure_packet + ClassifyFailureDecisionReport
      - P3: 文档同步(49+47 → 46+50、uv build blocked → 通过)

    主入口的 P1-1 + P1-2 修复已在 TestD46V102AdapterFixes 覆盖。
    ai 层的 P2-3 + P2-4 已在 tests/ai/test_classifier.py::TestD46V102Fixes 覆盖。
    """

    # --- P1: 公开 helper 严判下沉 ---

    def test_compute_classification_acceptance_rejects_bad_category(self) -> None:
        """P1 修复: compute_classification_acceptance 拒 OOPS(原版静默通过,产生 3 条 AC)."""
        with pytest.raises(ValueError, match="5 类之一"):
            compute_classification_acceptance(
                category_value="OOPS",  # 不在 5 类
                confidence=0.9,
                latency_ms=1500,
            )

    def test_compute_classification_acceptance_rejects_nan_confidence(self) -> None:
        """P1 修复: compute_classification_acceptance 拒 NaN(原版 AC[0]=NaN>=0.7 False 通过)."""
        with pytest.raises(ValueError, match="NaN/Inf"):
            compute_classification_acceptance(
                category_value="URGENT",
                confidence=float("nan"),
                latency_ms=1500,
            )

    def test_compute_classification_acceptance_rejects_inf_confidence(self) -> None:
        """P1 修复: compute_classification_acceptance 拒 Inf / -Inf."""
        for bad in (float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="NaN/Inf"):
                compute_classification_acceptance(
                    category_value="URGENT",
                    confidence=bad,
                    latency_ms=1500,
                )

    def test_compute_classification_acceptance_rejects_negative_latency(self) -> None:
        """P1 修复: compute_classification_acceptance 拒 latency_ms < 0(原版静默通过)."""
        with pytest.raises(ValueError, match="latency_ms"):
            compute_classification_acceptance(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=-1,
            )

    def test_build_classify_policy_context_rejects_bad_category(self) -> None:
        """P1 修复: build_classify_policy_context 同样严判 OOPS.

        旧 v1.0.2 写法只在校验前 field-access, 直接绕过 → caller 传 OOPS 也接受。
        新版走同一 _validate_classify_category helper, 任何 caller 都受保护。
        """
        with pytest.raises(ValueError, match="5 类之一"):
            build_classify_policy_context(
                category_value="OOPS",
                confidence=0.9,
                latency_ms=1500,
                last_classify_failed=False,
                consecutive_classify_failures=0,
            )

    def test_build_classify_policy_context_rejects_nan_confidence(self) -> None:
        """P1 修复: build_classify_policy_context 同样严判 NaN."""
        with pytest.raises(ValueError, match="NaN/Inf"):
            build_classify_policy_context(
                category_value="URGENT",
                confidence=float("nan"),
                latency_ms=1500,
                last_classify_failed=False,
                consecutive_classify_failures=0,
            )

    def test_build_classify_policy_context_rejects_negative_latency(self) -> None:
        """P1 修复: build_classify_policy_context 同样严判 latency < 0."""
        with pytest.raises(ValueError, match="latency_ms"):
            build_classify_policy_context(
                category_value="URGENT",
                confidence=0.9,
                latency_ms=-1,
                last_classify_failed=False,
                consecutive_classify_failures=0,
            )

    def test_build_classify_policy_context_synthetic_failure_values_pass(self) -> None:
        """P1 修复: 失败入口的 synthetic 值(category="URGENT"/conf=0/latency=0)
        全部能通过严判(便于失败入口继续用同一严判口径).

        关键: 这是 P1 修复的"兼容性证明", 失败入口的硬编码值必须合法。
        """
        ctx = build_classify_policy_context(
            category_value="URGENT",  # synthetic, 在 5 类
            confidence=0.0,  # synthetic, 有限 0-1
            latency_ms=0,  # synthetic, >= 0
            last_classify_failed=True,  # 失败入口隐式 True
            consecutive_classify_failures=3,  # 升级阈值
        )
        assert ctx["policy_eval_failed"] is True
        assert ctx["last_error_recoverable"] is False  # cf=3 不再 recoverable
        # AC[0] = (0.0 >= 0.7) = False → 永不 merge(失败入口设计)
        assert ctx["acceptance_results"][0] is False

    # --- P2-2: 失败报告独立数据类 ---

    def test_failure_entry_returns_classify_failure_decision_report(self, store: Any) -> None:
        """P2-2 修复: 失败入口返回 ClassifyFailureDecisionReport(非 ClassifyDecisionReport).

        旧 v1.0.2: 失败入口返回 ClassifyDecisionReport(category="" + confidence=0.0),
        违反自身 "category: 5 类枚举" 字段契约。
        新 v1.0.2-second: 独立 ClassifyFailureDecisionReport,字段自洽:
        - failed: 必为 True
        - last_error: 失败原因(截断到 200 字符)
        - consecutive_classify_failures: 失败计数
        - 无 category / confidence(失败场景无业务分类)
        """
        from dataclasses import fields as dc_fields

        a = EmailClassifierAdapter(source="qq", event_store=store)
        report = a.record_classify_failure_and_emit(
            email_id=1,
            last_error="LLM timeout after 30s",
            consecutive_classify_failures=3,
            run_id="r-v102sp-failure-report",
        )
        # 1) 类型必须为 ClassifyFailureDecisionReport
        assert isinstance(report, ClassifyFailureDecisionReport)
        assert not isinstance(report, ClassifyDecisionReport)  # 与成功报告区分
        # 2) 字段必填
        assert report.failed is True
        assert report.last_error == "LLM timeout after 30s"
        assert report.consecutive_classify_failures == 3
        assert report.event_id is not None
        assert report.lane_entry_id.startswith("classify:qq:")
        # 3) 数据类字段集: 不应有 category / confidence
        field_names = {f.name for f in dc_fields(ClassifyFailureDecisionReport)}
        assert "category" not in field_names
        assert "confidence" not in field_names
        assert "failed" in field_names
        assert "last_error" in field_names
        assert "consecutive_classify_failures" in field_names

    def test_failure_report_truncates_long_last_error(self) -> None:
        """P2-2 修复: 失败入口 last_error 截断到 200 字符."""
        a = EmailClassifierAdapter(source="qq")
        long_error = "X" * 500
        report = a.record_classify_failure_and_emit(
            email_id=1,
            last_error=long_error,
            consecutive_classify_failures=2,
            run_id="r-v102sp-truncate",
        )
        assert len(report.last_error) == 200
        assert report.last_error == "X" * 200

    # --- P2-3: 顶层导出 ---

    def test_top_level_imports_work(self) -> None:
        """P2-3 修复: from my_ai_employee.policy import build_classify_failure_packet /
        ClassifyFailureDecisionReport 顶层导入必须工作(旧 v1.0.2 漏导入会失败).
        """
        # 必须不抛 ImportError
        from my_ai_employee.policy import (  # noqa: F401
            ClassifyFailureDecisionReport as _Cfdr,
        )
        from my_ai_employee.policy import (  # noqa: F401
            build_classify_failure_packet as _bcfp,
        )

        # 类型/工厂可用
        assert callable(_bcfp)
        p = _bcfp(
            email_id=1,
            source="qq",
            last_error_str="err",
            consecutive_classify_failures=1,
        )
        assert p.objective.startswith("email_classify_failed:source=qq:id=1")


# ============================================================
# D4.6 v1.0.2 第三次复检修复测试(2026-06-09 早晨第三次复检 4 项)
# ============================================================


class TestD46V102ThirdPassFixes:
    """D4.6 v1.0.2 第三次复检 4 项修复测试.

    覆盖用户 6/9 早晨第三次复检的 1 P1 + 2 P2 + 1 P3:
      - P1: build_classify_packet 复用 _validate_classify_category 公共 helper
        (公共构造器不能再生成非法分类)
      - P2: ClassifyFailureDecisionReport.failed 字段升级为 Literal[True],
        __post_init__ 校验 last_error 非空 + consecutive_classify_failures >= 1
        (D3.3.3 教训:数据类字段约束必须自洽)
      - P2: classify_and_emit 走 _validate_classify_category 公共 helper,
        异常统一 ValueError(防止 list/dict 等不可哈希类型触发 TypeError)
      - P3: 文档同步(classify_and_emit 用例 docstring 移除已删除参数;
        record_classify_failure_and_emit 返回值 docstring 改为新报告类)
    """

    # --- P1: 公共构造器严判下沉 ---

    def test_build_classify_packet_rejects_bad_category(self) -> None:
        """P1 修复: build_classify_packet 拒 OOPS(原版仅 type() 严判, 缺 5 类校验).

        旧 v1.0.2 写法: `if type(category_value) is not str or not category_value`
        → "OOPS" 通过 type() 严判, 但不在 5 类枚举里, 静默生成 TaskPacket
        → 业务层调用方传 "OOPS" / "TODO_FIX" 等任意字符串都接受
        新 v1.0.2-third: 复用 _validate_classify_category 公共 helper, 与
        compute_classification_acceptance / build_classify_policy_context
        同一严判口径, 防止 Adapter 重构后绕过严判。
        """
        with pytest.raises(ValueError, match="5 类之一"):
            build_classify_packet(
                email_id=1,
                source="qq",
                category_value="OOPS",  # 不在 5 类
                model_full_id="m",
                confidence=0.9,
            )

    def test_build_classify_packet_rejects_empty_category(self) -> None:
        """P1 修复: build_classify_packet 拒空 category(原版只检查空,新版 5 类校验)."""
        with pytest.raises(ValueError, match="5 类之一"):
            build_classify_packet(
                email_id=1,
                source="qq",
                category_value="",  # 空串不在 5 类
                model_full_id="m",
                confidence=0.9,
            )

    # --- P2: 失败报告 Literal[True] + 字段自洽 ---

    def test_classify_failure_decision_report_rejects_failed_false(self) -> None:
        """P2 修复: failed 字段用 Literal[True] 类型固化, 手动构造 failed=False
        在运行时(mypy 静态 + __post_init__ 动态)双层防御.

        D3.3.3 教训: 数据类的字段约束必须自洽, 不能依赖 caller 显式传对。
        Literal[True] 让 mypy 在编译期拒绝 failed=False; __post_init__ 让
        运行时(mypy 绕过 / 动态构造)也拒绝。
        """
        # 1) 静态: Literal[True] 让 mypy 拒绝(此测试不跑 mypy, 仅校验运行时)
        # 2) 动态: __post_init__ 也校验 — 构造一个 fake PolicyEvaluation
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        fake_eval = PolicyEvaluation(
            status="succeeded",
            event_id=None,
        )
        # 运行时构造 failed=False 应被 __post_init__ 拒绝
        # 注: Literal[True] 在运行时是 str 注解, mypy 阻拦但 Python 不阻拦,
        # 所以需要 __post_init__ 显式校验(本测试的核心价值)
        try:
            r = ClassifyFailureDecisionReport(
                evaluation=fake_eval,
                event_id=None,
                lane_entry_id="classify:qq:r",
                liveness=Liveness.HEALTHY,
                failed=False,  # type: ignore[arg-type]
                last_error="err",
                consecutive_classify_failures=1,
            )
            # 如果没抛,说明运行时也漏了(回归)
            assert r.failed is True, (
                "Literal[True] 类型层面应固化 failed=True, 手动传 False 应在 __post_init__ 被拒"
            )
        except ValueError as e:
            # 期望: __post_init__ 显式拒绝 failed != True
            assert "failed" in str(e).lower() or "literal" in str(e).lower()

    def test_classify_failure_decision_report_rejects_empty_last_error(self) -> None:
        """P2 修复: __post_init__ 拒 last_error 空串(字段自洽)."""
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        fake_eval = PolicyEvaluation(
            status="succeeded",
            event_id=None,
        )
        with pytest.raises(ValueError, match="last_error"):
            ClassifyFailureDecisionReport(
                evaluation=fake_eval,
                event_id=None,
                lane_entry_id="classify:qq:r",
                liveness=Liveness.HEALTHY,
                failed=True,
                last_error="",  # 空串违反自洽
                consecutive_classify_failures=1,
            )

    def test_classify_failure_decision_report_rejects_cf_zero(self) -> None:
        """P2 修复: __post_init__ 拒 consecutive_classify_failures < 1(字段自洽)."""
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        fake_eval = PolicyEvaluation(
            status="succeeded",
            event_id=None,
        )
        with pytest.raises(ValueError, match="consecutive_classify_failures"):
            ClassifyFailureDecisionReport(
                evaluation=fake_eval,
                event_id=None,
                lane_entry_id="classify:qq:r",
                liveness=Liveness.HEALTHY,
                failed=True,
                last_error="err",
                consecutive_classify_failures=0,  # < 1 违反自洽
            )

    # --- P2: 异常统一 ValueError(classify_and_emit 走公共 helper) ---

    def test_classify_and_emit_list_category_raises_value_error(self) -> None:
        """P2 修复: classification.category.value 传列表 → ValueError(非 TypeError).

        旧 v1.0.2 内联 `if x not in frozenset` 与 build_classify_packet 不一致;
        新 v1.0.2-third 走 _validate_classify_category 公共 helper, 严判入口
        统一 ValueError(D3.3.3 教训:窄化异常范围, 防止 list/dict/set 等不可
        哈希类型在后续 set/frozenset 操作中触发 TypeError)。
        """
        a = EmailClassifierAdapter(source="qq")

        # 构造一个 category.value 是 list 的 classification
        @dataclass
        class _BadListCategory:
            value: list[str]  # 不可哈希

        @dataclass
        class _BadListClassification:
            category: _BadListCategory
            confidence: float = 0.9
            model_full_id: str = "m"
            latency_ms: int = 1500

        with pytest.raises(ValueError, match="原生 str"):
            a.classify_and_emit(
                email_id=1,
                classification=_BadListClassification(category=_BadListCategory(value=["URGENT"])),
                run_id="r-v102-third-list",
            )

    # --- P3: 文档同步(由 ruff/docstring 检查 + 测试侧 import 验证) ---

    def test_classify_and_emit_signature_has_no_failure_params(self) -> None:
        """P3 修复: classify_and_emit 签名不含 last_classify_failed / consecutive_classify_failures.

        旧 v1.0.1 文档示例中传 `consecutive_classify_failures=0` (P1-1 已删除),
        新 v1.0.2-third 文档已修正。本测试通过 inspect 验证签名对齐文档。
        """
        import inspect

        sig = inspect.signature(EmailClassifierAdapter.classify_and_emit)
        param_names = list(sig.parameters.keys())
        # 成功入口不应有 last_classify_failed / consecutive_classify_failures
        # (P1-1 修复:成功路径永不失败,这 2 个参数已删除)
        assert "last_classify_failed" not in param_names
        assert "consecutive_classify_failures" not in param_names
        # 应有的核心参数
        assert "email_id" in param_names
        assert "classification" in param_names
        assert "transport_alive" in param_names
        assert "run_id" in param_names

    def test_record_classify_failure_returns_failure_report(self, store: Any) -> None:
        """P3 修复: record_classify_failure_and_emit 返回 ClassifyFailureDecisionReport
        (旧文档写 ClassifyDecisionReport, 实际是独立失败报告类)。
        """
        a = EmailClassifierAdapter(source="qq", event_store=store)
        report = a.record_classify_failure_and_emit(
            email_id=42,
            last_error="timeout",
            consecutive_classify_failures=2,
            run_id="r-v102-third-failure-type",
        )
        # 必须是 ClassifyFailureDecisionReport, 不是 ClassifyDecisionReport
        assert isinstance(report, ClassifyFailureDecisionReport)
        assert not isinstance(report, ClassifyDecisionReport)
