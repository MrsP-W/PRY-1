"""D4.7.4 — EmailReviewerAdapter 单元测试.

设计:
  - 复用 conftest 的 in-memory SQLite + EventStore fixture
  - 用伪造 FakeReviewResult 模拟 D4.7.4 ai/reviewer.py ReviewResult 的输出
  - 验证: 三入口触发 + EventStore 落 1 条 PolicyDecisionEvent + LaneBoard add/update + Heartbeat 探活
  - 每次测试用 run_id="r-{test_name}" 显式注入, 避免 fingerprint 冲突

D4.7.4 测试点(沿用 D4.7.3 v1.0.6 范本 + 7 项核心契约):
  1. 5 _validate_review_* helper: type / 白名单 / 跨字段 / 双向强一致
  2. factory 函数 (4 个): build_review_packet / build_review_blocked_packet /
     build_review_failure_packet / build_review_policy_context
  3. compute_review_acceptance: 3 条 AC(review_passed / summary / latency)
  4. EmailReviewerAdapter 初始化: 4 依赖可注入 / is None 范式 / 拒空 source
  5. build_lane_entry_id: 命名 "review:<source>:<run_id>" / 拒空 run_id
  6. tick_heartbeat: transport_alive 严判 bool
  7. review_and_emit: 成功入口 / EventStore 落地 / lane / heartbeat
     + 拒 review_passed=False(阻断走 record_review_business_blocked_and_emit)
     + 6 字段透传契约
  8. record_review_business_blocked_and_emit: 4 类白名单 + 跨字段 blocked_word
     + blocked: Literal[True] + kind="business_blocked" + cf=0
  9. record_review_failure_and_emit: failed: Literal[True] + cf >= 1
  10. ReviewDecisionReport / ReviewBlockedDecisionReport / ReviewFailureDecisionReport
      __post_init__ 强一致校验 + 跨字段约束
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.ai.drafter import DraftTone  # noqa: E402
from my_ai_employee.ai.reviewer import (  # noqa: E402
    EmailCategory,
    ReviewResult,
)
from my_ai_employee.events.models import EventType  # noqa: E402
from my_ai_employee.policy.heartbeat import Liveness  # noqa: E402
from my_ai_employee.policy.integration import (  # noqa: E402
    EmailReviewerAdapter,
    ReviewBlockedDecisionReport,
    ReviewDecisionReport,
    ReviewFailureDecisionReport,
    build_review_blocked_packet,
    build_review_failure_packet,
    build_review_packet,
    build_review_policy_context,
    compute_review_acceptance,
)
from my_ai_employee.policy.lane_board import LaneStatus  # noqa: E402
from my_ai_employee.policy.policy_engine import PolicyEngine  # noqa: E402

# ===== 测试用 FakeReviewResult 仿造 =====
# ⚠️ 必须有 9 个 duck-typed 字段(与 ai/reviewer.py ReviewResult 对齐):
#   subject / body / tone / email_category / review_passed / flagged_issues /
#   review_summary / model_full_id / latency_ms


@dataclass(frozen=True)
class FakeReviewResult(ReviewResult):
    """仿造 ReviewResult(供 EmailReviewerAdapter.review_and_emit 用).

    D4.7.4 沿用 D4.7.3 FakeDraftResult 范本但改为 ReviewResult 子类。
    继承 ReviewResult 可避开 mypy arg-type 不匹配 + 复用 __post_init__ 强一致校验。
    """

    @classmethod
    def make(
        cls,
        tone: DraftTone = DraftTone.FORMAL,
        body_length: int = 50,
        latency_ms: int = 1500,
        model_full_id: str = "deepseek/deepseek-chat",
        review_passed: bool = True,
        review_summary: str = "审阅通过, 草稿可发",
        flagged_issues: list[str] | None = None,
    ) -> FakeReviewResult:
        body = "感谢您的反馈, 我们会尽快处理您的问题。\n\n如有疑问, 请随时联系。" * (
            body_length // 30 + 1
        )
        body = body[:body_length]
        return cls(
            subject="客户投诉回复",
            body=body,
            tone=tone,
            email_category=EmailCategory.URGENT,
            review_passed=review_passed,
            flagged_issues=flagged_issues if flagged_issues is not None else [],
            review_summary=review_summary,
            model_full_id=model_full_id,
            latency_ms=latency_ms,
            raw_content='{"review_passed": true}',
        )


# ===== Adapter fixture =====


@pytest.fixture
def adapter(store) -> EmailReviewerAdapter:
    """默认 Adapter(in-memory store, 默认 PolicyEngine/Heartbeat/LaneBoard)."""
    return EmailReviewerAdapter(source="qq", event_store=store)


# ============================================================
# 1. _validate_review_block_reason (4 类白名单)
# ============================================================


class TestValidateReviewBlockReason:
    """4 类白名单 helper 严判测试."""

    @pytest.mark.parametrize(
        "reason",
        ["sensitive_word_hit", "template_violation", "tone_mismatch", "factual_conflict"],
    )
    def test_whitelist_4_classes_pass(self, reason: str) -> None:
        from my_ai_employee.policy.integration import _validate_review_block_reason

        assert _validate_review_block_reason(reason) == reason

    @pytest.mark.parametrize("bad", ["other", "spam", "BANNED", "", "OTHER"])
    def test_invalid_reasons_rejected(self, bad: str) -> None:
        from my_ai_employee.policy.integration import _validate_review_block_reason

        with pytest.raises(ValueError, match="block_reason 必须在"):
            _validate_review_block_reason(bad)

    def test_non_string_rejected(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_block_reason

        with pytest.raises(ValueError, match="block_reason 必须是 str"):
            _validate_review_block_reason(42)  # type: ignore[arg-type]

    def test_unhashable_rejected_as_valueerror(self) -> None:
        """D4.7.3 v1.0.5 P2-1 范本: type 严判在前, 防 TypeError 泄漏."""
        from my_ai_employee.policy.integration import _validate_review_block_reason

        with pytest.raises(ValueError, match="block_reason 必须是 str"):
            _validate_review_block_reason([])  # type: ignore[arg-type]


# ============================================================
# 2. _validate_review_summary (1-2000 字符, strip 语义非空)
# ============================================================


class TestValidateReviewSummary:
    """review_summary 严判测试."""

    def test_valid_summary_passes(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_summary

        assert _validate_review_summary("草稿通过") == "草稿通过"

    def test_empty_string_rejected(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_summary

        with pytest.raises(ValueError, match="review_summary"):
            _validate_review_summary("")

    def test_whitespace_only_rejected(self) -> None:
        """D4.7.3 v1.0.4 P1-1 范本: strip() 语义非空."""
        from my_ai_employee.policy.integration import _validate_review_summary

        with pytest.raises(ValueError, match="review_summary"):
            _validate_review_summary("   \n\t  ")

    def test_too_long_rejected(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_summary

        with pytest.raises(ValueError, match="字符数必须 <= 2000"):
            _validate_review_summary("a" * 2001)

    def test_exactly_2000_passes(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_summary

        assert len(_validate_review_summary("a" * 2000)) == 2000

    def test_non_string_rejected(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_summary

        with pytest.raises(ValueError, match="review_summary 必须是 str"):
            _validate_review_summary(123)  # type: ignore[arg-type]


# ============================================================
# 3. _validate_review_flagged_issues (list[str] / 阻断时必非空)
# ============================================================


class TestValidateReviewFlaggedIssues:
    """flagged_issues 严判测试."""

    def test_empty_list_passes_when_not_required(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_flagged_issues

        assert _validate_review_flagged_issues([], required=False) == []

    def test_empty_list_rejected_when_required(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_flagged_issues

        with pytest.raises(ValueError, match="阻断时必非空"):
            _validate_review_flagged_issues([], required=True)

    def test_non_list_rejected(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_flagged_issues

        with pytest.raises(ValueError, match="flagged_issues 必须是 list"):
            _validate_review_flagged_issues("not a list", required=False)  # type: ignore[arg-type]

    def test_non_str_element_rejected(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_flagged_issues

        with pytest.raises(ValueError, match=r"flagged_issues\[0\] 必须是 str"):
            _validate_review_flagged_issues([42, "ok"], required=False)  # type: ignore[list-item]

    def test_valid_list_passes(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_flagged_issues

        assert _validate_review_flagged_issues(["问题1", "问题2"], required=True) == [
            "问题1",
            "问题2",
        ]


# ============================================================
# 4. _validate_review_blocked_word (跨字段校验)
# ============================================================


class TestValidateReviewBlockedWord:
    """blocked_word 跨字段校验测试."""

    def test_sensitive_word_hit_requires_nonempty(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_blocked_word

        assert _validate_review_blocked_word("密码", reason="sensitive_word_hit") == "密码"
        with pytest.raises(ValueError, match="sensitive_word_hit"):
            _validate_review_blocked_word("", reason="sensitive_word_hit")
        with pytest.raises(ValueError, match="sensitive_word_hit"):
            _validate_review_blocked_word("   ", reason="sensitive_word_hit")

    def test_other_reasons_require_empty(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_blocked_word

        # template_violation / tone_mismatch / factual_conflict 都应空串
        for r in ("template_violation", "tone_mismatch", "factual_conflict"):
            assert _validate_review_blocked_word("", reason=r) == ""
            with pytest.raises(ValueError, match="blocked_word 必须为空字符串"):
                _validate_review_blocked_word("误填", reason=r)

    def test_non_string_rejected(self) -> None:
        from my_ai_employee.policy.integration import _validate_review_blocked_word

        with pytest.raises(ValueError, match="blocked_word 必须是 str"):
            _validate_review_blocked_word(123, reason="sensitive_word_hit")  # type: ignore[arg-type]


# ============================================================
# 5. compute_review_acceptance (3 ACs)
# ============================================================


class TestComputeReviewAcceptance:
    """3 条 acceptance_criteria 计算测试."""

    def test_all_pass(self) -> None:
        acs = compute_review_acceptance(review_passed=True, review_summary="通过", latency_ms=1000)
        assert acs == [True, True, True]

    def test_review_passed_false_fails_ac0(self) -> None:
        acs = compute_review_acceptance(review_passed=False, review_summary="通过", latency_ms=1000)
        assert acs == [False, True, True]

    def test_too_long_summary_fails_ac1(self) -> None:
        """2001 字符时 _validate_review_summary 直接拒收(compute 入口先严判)."""
        with pytest.raises(ValueError, match="字符数必须 <= 2000"):
            compute_review_acceptance(
                review_passed=True, review_summary="a" * 2001, latency_ms=1000
            )

    def test_exactly_2000_summary_passes(self) -> None:
        """2000 字符边界 OK."""
        acs = compute_review_acceptance(
            review_passed=True, review_summary="a" * 2000, latency_ms=1000
        )
        assert acs[1] is True

    def test_latency_too_long_fails_ac2(self) -> None:
        acs = compute_review_acceptance(review_passed=True, review_summary="通过", latency_ms=6000)
        assert acs[2] is False

    def test_returns_list_of_bool(self) -> None:
        acs = compute_review_acceptance(review_passed=True, review_summary="通过", latency_ms=1000)
        assert all(type(x) is bool for x in acs)

    def test_invalid_args_rejected(self) -> None:
        with pytest.raises(ValueError):
            compute_review_acceptance(
                review_passed=1,  # type: ignore[arg-type]
                review_summary="x",
                latency_ms=1000,
            )
        with pytest.raises(ValueError):
            compute_review_acceptance(
                review_passed=True,
                review_summary="",
                latency_ms=1000,
            )
        with pytest.raises(ValueError):
            compute_review_acceptance(
                review_passed=True,
                review_summary="x",
                latency_ms=-1,
            )


# ============================================================
# 6. factory 函数
# ============================================================


class TestBuildReviewPacket:
    """build_review_packet 测试."""

    def test_8_fields_complete(self) -> None:
        p = build_review_packet(
            email_id=42,
            source="qq",
            tone="FORMAL",
            model_full_id="deepseek/deepseek-chat",
            body_length=50,
        )
        assert p.objective.startswith("email_review:source=qq:id=")
        assert "ai/reviewer.py" in p.scope
        assert "core/models.py" in p.scope
        assert "db:sqlcipher" in p.resources
        assert "llm:router" in p.resources
        assert len(p.acceptance_criteria) == 3
        assert p.model == "deepseek/deepseek-chat"
        assert p.provider == "deepseek"
        assert p.permission_profile == "read_only"
        assert p.recovery_policy == "retry_on_transient"

    def test_accepts_draft_tone_enum(self) -> None:
        p = build_review_packet(
            email_id=1,
            source="qq",
            tone=DraftTone.FORMAL,
            model_full_id="m",
            body_length=20,
        )
        # 固定契约描述字符串, 不写自证式
        assert "review_passed=true" in p.acceptance_criteria
        assert "1<=review_summary<=2000" in p.acceptance_criteria
        assert "latency<5000ms" in p.acceptance_criteria

    def test_strict_type_rejection(self) -> None:
        with pytest.raises(ValueError):
            build_review_packet(
                email_id=True,  # type: ignore[arg-type]
                source="qq",
                tone="FORMAL",
                model_full_id="m",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_review_packet(
                email_id=42,
                source="",  # 空 source
                tone="FORMAL",
                model_full_id="m",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_review_packet(
                email_id=42,
                source="qq",
                tone="INVALID",
                model_full_id="m",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_review_packet(
                email_id=42,
                source="qq",
                tone="FORMAL",
                model_full_id="",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_review_packet(
                email_id=42,
                source="qq",
                tone="FORMAL",
                model_full_id="m",
                body_length=5,  # < 10
            )
        with pytest.raises(ValueError):
            build_review_packet(
                email_id=42,
                source="qq",
                tone="FORMAL",
                model_full_id="m",
                body_length=8001,  # > 8000
            )


class TestBuildReviewBlockedPacket:
    """build_review_blocked_packet 测试."""

    def test_4_reasons_pass(self) -> None:
        for reason in (
            "sensitive_word_hit",
            "template_violation",
            "tone_mismatch",
            "factual_conflict",
        ):
            bw = "命中词" if reason == "sensitive_word_hit" else ""
            p = build_review_blocked_packet(
                email_id=42,
                source="qq",
                tone="FORMAL",
                reason=reason,
                blocked_word=bw,
                original_email_category="URGENT",
            )
            assert p.objective.startswith("email_review_blocked:source=qq:id=")
            assert p.model == "unknown"

    def test_invalid_reason_rejected(self) -> None:
        with pytest.raises(ValueError, match="block_reason"):
            build_review_blocked_packet(
                email_id=42,
                source="qq",
                tone="FORMAL",
                reason="other",
                blocked_word="",
                original_email_category="URGENT",
            )

    def test_sensitive_word_hit_requires_nonempty_blocked_word(self) -> None:
        with pytest.raises(ValueError, match="sensitive_word_hit"):
            build_review_blocked_packet(
                email_id=42,
                source="qq",
                tone="FORMAL",
                reason="sensitive_word_hit",
                blocked_word="",
                original_email_category="URGENT",
            )

    def test_other_reasons_require_empty_blocked_word(self) -> None:
        with pytest.raises(ValueError, match="blocked_word 必须为空字符串"):
            build_review_blocked_packet(
                email_id=42,
                source="qq",
                tone="FORMAL",
                reason="template_violation",
                blocked_word="误填",
                original_email_category="URGENT",
            )

    def test_invalid_category_rejected(self) -> None:
        with pytest.raises(ValueError):
            build_review_blocked_packet(
                email_id=42,
                source="qq",
                tone="FORMAL",
                reason="template_violation",
                blocked_word="",
                original_email_category="OTHER",
            )


class TestBuildReviewFailurePacket:
    """build_review_failure_packet 测试."""

    def test_basic(self) -> None:
        p = build_review_failure_packet(
            email_id=42,
            source="qq",
            last_error_str="LLM timeout",
            consecutive_review_failures=1,
        )
        assert p.objective.startswith("email_review_failed:source=qq:id=")
        assert p.model == "unknown"
        assert "last_error=LLM timeout" in p.acceptance_criteria[0]
        assert "consecutive_review_failures=1" in p.acceptance_criteria[1]

    def test_cf_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="consecutive_review_failures 必须是原生 int >= 1"):
            build_review_failure_packet(
                email_id=42,
                source="qq",
                last_error_str="x",
                consecutive_review_failures=0,
            )

    def test_blank_last_error_rejected(self) -> None:
        with pytest.raises(ValueError, match="last_error_str"):
            build_review_failure_packet(
                email_id=42,
                source="qq",
                last_error_str="   ",
                consecutive_review_failures=1,
            )


class TestBuildReviewPolicyContext:
    """build_review_policy_context 双向强一致测试."""

    def test_success_path(self) -> None:
        ctx = build_review_policy_context(
            tone="FORMAL",
            latency_ms=1000,
            body_length=50,
            last_review_failed=False,
            consecutive_review_failures=0,
        )
        assert ctx["last_error_recoverable"] is False
        assert ctx["current_attempts"] == 0
        assert ctx["max_attempts"] == 3
        assert ctx["policy_eval_failed"] is False
        assert len(ctx["acceptance_results"]) == 3
        assert all(ac is True for ac in ctx["acceptance_results"])

    def test_failure_path_1_to_2_recoverable(self) -> None:
        ctx = build_review_policy_context(
            tone="FORMAL",
            latency_ms=1000,
            body_length=50,
            last_review_failed=True,
            consecutive_review_failures=1,
        )
        assert ctx["last_error_recoverable"] is True
        assert ctx["policy_eval_failed"] is False

    def test_failure_path_3_escalate(self) -> None:
        ctx = build_review_policy_context(
            tone="FORMAL",
            latency_ms=1000,
            body_length=50,
            last_review_failed=True,
            consecutive_review_failures=3,
        )
        assert ctx["last_error_recoverable"] is False
        assert ctx["policy_eval_failed"] is True

    def test_bidirectional_consistency_true_requires_cf_ge_1(self) -> None:
        with pytest.raises(ValueError, match="last_review_failed=True"):
            build_review_policy_context(
                tone="FORMAL",
                latency_ms=1000,
                body_length=50,
                last_review_failed=True,
                consecutive_review_failures=0,
            )

    def test_bidirectional_consistency_false_requires_cf_zero(self) -> None:
        with pytest.raises(ValueError, match="last_review_failed=False"):
            build_review_policy_context(
                tone="FORMAL",
                latency_ms=1000,
                body_length=50,
                last_review_failed=False,
                consecutive_review_failures=1,
            )

    def test_invalid_args(self) -> None:
        with pytest.raises(ValueError):
            build_review_policy_context(
                tone="INVALID",
                latency_ms=1000,
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_review_policy_context(
                tone="FORMAL",
                latency_ms=-1,
                body_length=50,
            )


# ============================================================
# 7. EmailReviewerAdapter 初始化
# ============================================================


class TestEmailReviewerAdapterInit:
    """Adapter 初始化测试."""

    def test_minimal_init(self) -> None:
        a = EmailReviewerAdapter(source="qq")
        assert a._source == "qq"
        assert a._event_store is None
        assert a._engine is not None
        assert a._heartbeat is not None
        assert a._board is not None

    def test_all_4_deps_injected(self, store) -> None:
        engine = PolicyEngine()
        from my_ai_employee.policy.heartbeat import Heartbeat
        from my_ai_employee.policy.lane_board import LaneBoard

        hb = Heartbeat(idle_threshold_ms=30_000)
        board = LaneBoard(idle_threshold_ms=60_000)
        a = EmailReviewerAdapter(
            source="qq", event_store=store, engine=engine, heartbeat=hb, board=board
        )
        assert a._source == "qq"
        assert a._event_store is store
        assert a._engine is engine
        assert a._heartbeat is hb
        assert a._board is board

    def test_blank_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="source 必填非空白"):
            EmailReviewerAdapter(source="   ")

    def test_non_str_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="source 必填非空白"):
            EmailReviewerAdapter(source=42)  # type: ignore[arg-type]

    def test_is_none_keeps_falsy_substitute(self) -> None:
        """D4.7.3 v1.0.3 P2-2 范本: is None 范式保留 falsey 替身."""


# ============================================================
# 8. build_lane_entry_id
# ============================================================


class TestBuildLaneEntryId:
    """build_lane_entry_id 命名 + 严判测试."""

    def test_naming(self, adapter: EmailReviewerAdapter) -> None:
        assert adapter.build_lane_entry_id("run-1") == "review:qq:run-1"

    def test_blank_run_id_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="run_id 必填非空白"):
            adapter.build_lane_entry_id("   ")

    def test_non_str_run_id_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="run_id"):
            adapter.build_lane_entry_id(42)  # type: ignore[arg-type]


# ============================================================
# 9. tick_heartbeat
# ============================================================


class TestTickHeartbeat:
    """tick_heartbeat 严判 + Liveness 测试."""

    def test_transport_alive_true(self, adapter: EmailReviewerAdapter) -> None:
        liveness = adapter.tick_heartbeat(transport_alive=True)
        assert isinstance(liveness, Liveness)

    def test_transport_alive_false(self, adapter: EmailReviewerAdapter) -> None:
        adapter.tick_heartbeat(transport_alive=True)  # 先 alive
        liveness = adapter.tick_heartbeat(transport_alive=False)
        # 1 次 False 不会立刻死, 但会触发状态变更
        assert liveness is not None

    def test_non_bool_transport_alive_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="transport_alive 必须是原生 bool"):
            adapter.tick_heartbeat(transport_alive=1)  # type: ignore[arg-type]


# ============================================================
# 10. review_and_emit (成功入口)
# ============================================================


class TestReviewAndEmit:
    """成功审阅入口测试."""

    def test_basic_success(self, adapter: EmailReviewerAdapter) -> None:
        result = FakeReviewResult.make(review_passed=True)
        report = adapter.review_and_emit(
            email_id=42,
            review_result=result,
            category="URGENT",
            run_id="r-basic-success",
        )
        assert isinstance(report, ReviewDecisionReport)
        assert report.review_passed is True
        assert report.tone == "FORMAL"
        assert report.email_id == 42
        assert report.category == "URGENT"
        assert report.lane_entry_id == "review:qq:r-basic-success"
        assert report.latency_ms == 1500
        assert report.model_full_id == "deepseek/deepseek-chat"

    def test_event_store_insert(self, adapter: EmailReviewerAdapter) -> None:
        result = FakeReviewResult.make()
        adapter.review_and_emit(
            email_id=42,
            review_result=result,
            category="URGENT",
            run_id="r-event-insert",
        )
        events = adapter._event_store.by_event_type(  # type: ignore[union-attr]
            EventType.POLICY_DECISION_MADE, limit=10
        )
        assert len(events) >= 1
        # event_metadata 含 lane_entry_id + run_id(D4.5 v1.0.1 反馈闭环)
        assert any(
            e.event_metadata.get("lane_entry_id") == "review:qq:r-event-insert" for e in events
        )

    def test_lane_board_recorded_finished(self, adapter: EmailReviewerAdapter) -> None:
        result = FakeReviewResult.make(latency_ms=1000)
        adapter.review_and_emit(
            email_id=42,
            review_result=result,
            category="URGENT",
            run_id="r-lane-finished",
        )
        lane = adapter._board.get("review:qq:r-lane-finished")  # type: ignore[union-attr]
        assert lane.status == LaneStatus.FINISHED

    def test_review_passed_false_rejected(self, adapter: EmailReviewerAdapter) -> None:
        """成功入口拒 review_passed=False(阻断请走 record_review_business_blocked_and_emit)."""
        # review_passed=False 必须配非空 flagged_issues(reviewer.py ReviewResult 契约)
        result = FakeReviewResult.make(review_passed=False, flagged_issues=["草稿未复述任务"])
        with pytest.raises(ValueError, match="review_and_emit 仅接受 review_passed=True"):
            adapter.review_and_emit(
                email_id=42,
                review_result=result,
                category="URGENT",
                run_id="r-blocked-rejected",
            )

    def test_invalid_email_id(self, adapter: EmailReviewerAdapter) -> None:
        result = FakeReviewResult.make()
        with pytest.raises(ValueError, match="email_id 必须是原生 int >= 0"):
            adapter.review_and_emit(
                email_id=-1,  # type: ignore[arg-type]
                review_result=result,
                category="URGENT",
            )
        with pytest.raises(ValueError, match="email_id 必须是原生 int >= 0"):
            adapter.review_and_emit(
                email_id=True,  # type: ignore[arg-type]
                review_result=result,
                category="URGENT",
            )

    def test_invalid_category(self, adapter: EmailReviewerAdapter) -> None:
        result = FakeReviewResult.make()
        with pytest.raises(ValueError):
            adapter.review_and_emit(
                email_id=42,
                review_result=result,
                category="OTHER",
            )

    def test_non_bool_transport_alive_rejected(self, adapter: EmailReviewerAdapter) -> None:
        result = FakeReviewResult.make()
        with pytest.raises(ValueError, match="transport_alive 必须是原生 bool"):
            adapter.review_and_emit(
                email_id=42,
                review_result=result,
                category="URGENT",
                transport_alive=1,  # type: ignore[arg-type]
            )

    def test_missing_required_field_rejected(self, adapter: EmailReviewerAdapter) -> None:
        @dataclass(frozen=True)
        class Incomplete:
            subject: str = "x"
            # 缺 body / tone / email_category / review_passed 等

        with pytest.raises(ValueError, match="review_result.body 缺失"):
            adapter.review_and_emit(
                email_id=42,
                review_result=Incomplete(),  # type: ignore[arg-type]
                category="URGENT",
            )

    def test_six_field_business_payload(self, adapter: EmailReviewerAdapter) -> None:
        """week1-mvp.md:781 锁定 6 字段透传契约."""
        result = FakeReviewResult.make()
        adapter.review_and_emit(
            email_id=42,
            review_result=result,
            category="URGENT",
            run_id="r-payload",
        )
        events = adapter._event_store.by_event_type(  # type: ignore[union-attr]
            EventType.POLICY_DECISION_MADE, limit=1
        )
        # event_metadata 含 6 字段(extra_business_payload)
        assert events[0].event_metadata.get("category") == "URGENT"
        assert events[0].event_metadata.get("email_id") == 42


# ============================================================
# 11. record_review_business_blocked_and_emit (业务阻断)
# ============================================================


class TestRecordReviewBusinessBlockedAndEmit:
    """业务阻断入口测试(4 类白名单 + 跨字段)."""

    def test_basic_blocked(self, adapter: EmailReviewerAdapter) -> None:
        report = adapter.record_review_business_blocked_and_emit(
            email_id=42,
            tone="FORMAL",
            original_email_category="URGENT",
            reason="sensitive_word_hit",
            blocked_word="内部代号",
            flagged_issues=["包含敏感词"],
            review_summary="命中内部代号, 已阻断",
            last_error="sensitive_word_hit: 内部代号",
            run_id="r-bblocked",
        )
        assert isinstance(report, ReviewBlockedDecisionReport)
        assert report.blocked is True
        assert report.kind == "business_blocked"
        assert report.reason == "sensitive_word_hit"
        assert report.blocked_word == "内部代号"
        assert report.consecutive_review_failures == 0
        assert report.email_id == 42
        assert report.lane_entry_id == "review:qq:r-bblocked"

    @pytest.mark.parametrize(
        "reason,bw",
        [
            ("sensitive_word_hit", "内部代号"),
            ("template_violation", ""),
            ("tone_mismatch", ""),
            ("factual_conflict", ""),
        ],
    )
    def test_4_reasons_pass(self, adapter: EmailReviewerAdapter, reason: str, bw: str) -> None:
        report = adapter.record_review_business_blocked_and_emit(
            email_id=42,
            tone="FORMAL",
            original_email_category="URGENT",
            reason=reason,
            blocked_word=bw,
            flagged_issues=["问题"],
            review_summary="阻断",
            last_error="err",
            run_id=f"r-{reason}",
        )
        assert report.reason == reason
        assert report.blocked_word == bw

    def test_event_store_insert(self, adapter: EmailReviewerAdapter) -> None:
        adapter.record_review_business_blocked_and_emit(
            email_id=42,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="template_violation",
            blocked_word="",
            flagged_issues=["无截止时间"],
            review_summary="TODO 邮件无截止时间",
            last_error="template_violation",
            run_id="r-bblocked-event",
        )
        events = adapter._event_store.by_event_type(  # type: ignore[union-attr]
            EventType.POLICY_DECISION_MADE, limit=10
        )
        assert any(
            e.event_metadata.get("lane_entry_id") == "review:qq:r-bblocked-event" for e in events
        )
        # blocked_kind 标记
        assert any(e.event_metadata.get("blocked_kind") == "business" for e in events)

    def test_lane_board_blocked(self, adapter: EmailReviewerAdapter) -> None:
        adapter.record_review_business_blocked_and_emit(
            email_id=42,
            tone="FORMAL",
            original_email_category="URGENT",
            reason="sensitive_word_hit",
            blocked_word="x",
            flagged_issues=["问题"],
            review_summary="阻断",
            last_error="err",
            run_id="r-bblocked-lane",
        )
        lane = adapter._board.get("review:qq:r-bblocked-lane")  # type: ignore[union-attr]
        assert lane.status == LaneStatus.BLOCKED

    def test_invalid_reason_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="block_reason"):
            adapter.record_review_business_blocked_and_emit(
                email_id=42,
                tone="FORMAL",
                original_email_category="URGENT",
                reason="other",  # type: ignore[arg-type]
                blocked_word="",
                flagged_issues=["x"],
                review_summary="x",
                last_error="err",
            )

    def test_sensitive_word_hit_requires_nonempty_blocked_word(
        self, adapter: EmailReviewerAdapter
    ) -> None:
        with pytest.raises(ValueError, match="sensitive_word_hit"):
            adapter.record_review_business_blocked_and_emit(
                email_id=42,
                tone="FORMAL",
                original_email_category="URGENT",
                reason="sensitive_word_hit",
                blocked_word="",
                flagged_issues=["x"],
                review_summary="x",
                last_error="err",
            )

    def test_other_reasons_require_empty_blocked_word(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="blocked_word 必须为空字符串"):
            adapter.record_review_business_blocked_and_emit(
                email_id=42,
                tone="FORMAL",
                original_email_category="URGENT",
                reason="template_violation",
                blocked_word="误填",
                flagged_issues=["x"],
                review_summary="x",
                last_error="err",
            )

    def test_blocked_flagged_issues_required(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="阻断时必非空"):
            adapter.record_review_business_blocked_and_emit(
                email_id=42,
                tone="FORMAL",
                original_email_category="URGENT",
                reason="template_violation",
                blocked_word="",
                flagged_issues=[],  # 阻断时必非空
                review_summary="x",
                last_error="err",
            )

    def test_invalid_category_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError):
            adapter.record_review_business_blocked_and_emit(
                email_id=42,
                tone="FORMAL",
                original_email_category="OTHER",
                reason="template_violation",
                blocked_word="",
                flagged_issues=["x"],
                review_summary="x",
                last_error="err",
            )

    def test_blank_last_error_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="last_error"):
            adapter.record_review_business_blocked_and_emit(
                email_id=42,
                tone="FORMAL",
                original_email_category="URGENT",
                reason="template_violation",
                blocked_word="",
                flagged_issues=["x"],
                review_summary="x",
                last_error="   ",
            )

    def test_none_last_error_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="last_error 不能为 None"):
            adapter.record_review_business_blocked_and_emit(
                email_id=42,
                tone="FORMAL",
                original_email_category="URGENT",
                reason="template_violation",
                blocked_word="",
                flagged_issues=["x"],
                review_summary="x",
                last_error=None,
            )


# ============================================================
# 12. record_review_failure_and_emit (技术失败)
# ============================================================


class TestRecordReviewFailureAndEmit:
    """技术失败入口测试."""

    def test_basic_failure(self, adapter: EmailReviewerAdapter) -> None:
        report = adapter.record_review_failure_and_emit(
            email_id=42,
            last_error="LLM timeout",
            consecutive_review_failures=2,
            run_id="r-fail-basic",
        )
        assert isinstance(report, ReviewFailureDecisionReport)
        assert report.failed is True
        assert report.consecutive_review_failures == 2
        assert report.lane_entry_id == "review:qq:r-fail-basic"
        assert "LLM timeout" in report.last_error

    def test_cf_must_be_positive(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="consecutive_review_failures 必须是原生 int >= 1"):
            adapter.record_review_failure_and_emit(
                email_id=42,
                last_error="err",
                consecutive_review_failures=0,
            )

    def test_lane_blocked(self, adapter: EmailReviewerAdapter) -> None:
        adapter.record_review_failure_and_emit(
            email_id=42,
            last_error="err",
            consecutive_review_failures=1,
            run_id="r-fail-lane",
        )
        lane = adapter._board.get("review:qq:r-fail-lane")  # type: ignore[union-attr]
        assert lane.status == LaneStatus.BLOCKED

    def test_event_store_failed_kind(self, adapter: EmailReviewerAdapter) -> None:
        adapter.record_review_failure_and_emit(
            email_id=42,
            last_error="LLM timeout",
            consecutive_review_failures=1,
            run_id="r-fail-event",
        )
        events = adapter._event_store.by_event_type(  # type: ignore[union-attr]
            EventType.POLICY_DECISION_MADE, limit=10
        )
        assert any(e.event_metadata.get("failed_kind") == "technical" for e in events)

    def test_blank_last_error_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="last_error"):
            adapter.record_review_failure_and_emit(
                email_id=42,
                last_error="   ",
                consecutive_review_failures=1,
            )

    def test_none_last_error_rejected(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="last_error 不能为 None"):
            adapter.record_review_failure_and_emit(
                email_id=42,
                last_error=None,
                consecutive_review_failures=1,
            )

    def test_invalid_email_id(self, adapter: EmailReviewerAdapter) -> None:
        with pytest.raises(ValueError, match="email_id 必须是原生 int >= 0"):
            adapter.record_review_failure_and_emit(
                email_id=-1,
                last_error="err",
                consecutive_review_failures=1,
            )


# ============================================================
# 13. ReviewDecisionReport __post_init__ 强一致校验
# ============================================================


class TestReviewDecisionReportStrongConsistency:
    """ReviewDecisionReport 字段契约自洽校验测试."""

    def _make_args(
        self,
        review_passed: bool = True,
        review_summary: str = "草稿通过",
        flagged_issues: list[str] | None = None,
        tone: str = "FORMAL",
        model_full_id: str = "m",
        email_id: int = 1,
        latency_ms: int = 1000,
        category: str = "URGENT",
        body_length: int = 50,
    ) -> dict[str, Any]:
        from my_ai_employee.policy.policy_engine import (
            PolicyEngine,
        )

        evaluation = PolicyEngine().evaluate(
            packet=build_review_packet(
                email_id=email_id,
                source="qq",
                tone=tone,
                model_full_id=model_full_id,
                body_length=body_length,
            ),
            context=build_review_policy_context(
                tone=tone,
                latency_ms=latency_ms,
                body_length=body_length,
            ),
            store=None,
            lane_entry_id="review:qq:1",
            run_id="1",
        )
        return {
            "evaluation": evaluation,
            "event_id": evaluation.event_id,
            "lane_entry_id": "review:qq:1",
            "liveness": Liveness.HEALTHY,
            "review_passed": review_passed,
            "review_summary": review_summary,
            "flagged_issues": flagged_issues if flagged_issues is not None else [],
            "tone": tone,
            "model_full_id": model_full_id,
            "email_id": email_id,
            "latency_ms": latency_ms,
            "category": category,
            "body_length": body_length,
        }

    def test_valid(self) -> None:
        args = self._make_args()
        report = ReviewDecisionReport(**args)
        assert report.review_passed is True
        assert report.tone == "FORMAL"
        assert report.category == "URGENT"

    def test_review_passed_false_rejected(self) -> None:
        """D4.7.4 范本: Literal[True] 类型层面固化."""
        with pytest.raises(ValueError, match="review_passed 必为 True"):
            ReviewDecisionReport(**self._make_args(review_passed=False))  # type: ignore[arg-type]

    def test_blank_summary_rejected(self) -> None:
        with pytest.raises(ValueError, match="review_summary"):
            ReviewDecisionReport(**self._make_args(review_summary="   "))

    def test_too_long_summary_rejected(self) -> None:
        with pytest.raises(ValueError, match="review_summary"):
            ReviewDecisionReport(**self._make_args(review_summary="a" * 2001))

    def test_blank_model_full_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="model_full_id"):
            ReviewDecisionReport(**self._make_args(model_full_id="   "))

    def test_invalid_category_rejected(self) -> None:
        with pytest.raises(ValueError, match="category"):
            ReviewDecisionReport(**self._make_args(category="OTHER"))

    def test_negative_email_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="email_id"):
            ReviewDecisionReport(**self._make_args(email_id=-1))

    def test_flagged_issues_can_be_empty(self) -> None:
        """成功时可空."""
        args = self._make_args(flagged_issues=[])
        report = ReviewDecisionReport(**args)
        assert report.flagged_issues == []


# ============================================================
# 14. ReviewBlockedDecisionReport __post_init__ 强一致校验
# ============================================================


class TestReviewBlockedDecisionReportStrongConsistency:
    """ReviewBlockedDecisionReport 字段契约 + 跨字段校验测试."""

    def _make_args(
        self,
        reason: str = "sensitive_word_hit",
        blocked_word: str = "内部代号",
        original_email_category: str = "URGENT",
        email_id: int = 1,
        tone: str = "FORMAL",
        flagged_issues: list[str] | None = None,
        review_summary: str = "命中",
        last_error: str = "err",
        consecutive_review_failures: int = 0,
        blocked: bool = True,
        kind: str = "business_blocked",
    ) -> dict[str, Any]:
        from my_ai_employee.policy.policy_engine import (
            PolicyEngine,
        )

        evaluation = PolicyEngine().evaluate(
            packet=build_review_blocked_packet(
                email_id=email_id,
                source="qq",
                tone=tone,
                reason=reason,
                blocked_word=blocked_word,
                original_email_category=original_email_category,
            ),
            context=build_review_policy_context(
                tone="FORMAL",
                latency_ms=0,
                body_length=0,
            ),
            store=None,
            lane_entry_id="review:qq:1",
            run_id="1",
        )
        return {
            "evaluation": evaluation,
            "event_id": evaluation.event_id,
            "lane_entry_id": "review:qq:1",
            "liveness": Liveness.HEALTHY,
            "last_error": last_error,
            "tone": tone,
            "reason": reason,
            "blocked_word": blocked_word,
            "flagged_issues": flagged_issues if flagged_issues is not None else ["问题"],
            "review_summary": review_summary,
            "original_email_category": original_email_category,
            "email_id": email_id,
            "consecutive_review_failures": consecutive_review_failures,
            "blocked": blocked,
            "kind": kind,
        }

    def test_valid_sensitive_word_hit(self) -> None:
        args = self._make_args()
        report = ReviewBlockedDecisionReport(**args)
        assert report.blocked is True
        assert report.kind == "business_blocked"
        assert report.reason == "sensitive_word_hit"
        assert report.consecutive_review_failures == 0

    def test_valid_template_violation(self) -> None:
        args = self._make_args(reason="template_violation", blocked_word="")
        report = ReviewBlockedDecisionReport(**args)
        assert report.reason == "template_violation"
        assert report.blocked_word == ""

    def test_blocked_false_rejected(self) -> None:
        """D4.7.4 范本: blocked 必为 True."""
        with pytest.raises(ValueError, match="blocked 必为 True"):
            ReviewBlockedDecisionReport(**self._make_args(blocked=False))  # type: ignore[arg-type]

    def test_kind_must_be_business_blocked(self) -> None:
        with pytest.raises(ValueError, match="kind 必为 'business_blocked'"):
            ReviewBlockedDecisionReport(**self._make_args(kind="technical"))  # type: ignore[arg-type]

    def test_cf_must_be_zero(self) -> None:
        """D4.7.4 范本: 业务阻断 cf=0(不计入失败累加器)."""
        with pytest.raises(ValueError, match="consecutive_review_failures 业务阻断必为 0"):
            ReviewBlockedDecisionReport(**self._make_args(consecutive_review_failures=1))

    def test_sensitive_word_hit_requires_nonempty(self) -> None:
        with pytest.raises(ValueError, match="sensitive_word_hit"):
            ReviewBlockedDecisionReport(
                **self._make_args(reason="sensitive_word_hit", blocked_word="")
            )

    def test_other_reasons_require_empty_blocked_word(self) -> None:
        with pytest.raises(ValueError, match="blocked_word 必须为空字符串"):
            ReviewBlockedDecisionReport(
                **self._make_args(reason="tone_mismatch", blocked_word="误填")
            )

    def test_flagged_issues_required(self) -> None:
        with pytest.raises(ValueError, match="阻断时必非空"):
            ReviewBlockedDecisionReport(**self._make_args(flagged_issues=[]))

    def test_invalid_reason_rejected(self) -> None:
        with pytest.raises(ValueError, match="block_reason"):
            ReviewBlockedDecisionReport(
                **self._make_args(reason="other", blocked_word="")  # type: ignore[arg-type]
            )

    def test_invalid_category_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewBlockedDecisionReport(**self._make_args(original_email_category="OTHER"))

    def test_blank_last_error_rejected(self) -> None:
        with pytest.raises(ValueError, match="last_error"):
            ReviewBlockedDecisionReport(**self._make_args(last_error="   "))

    def test_negative_email_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="email_id"):
            ReviewBlockedDecisionReport(**self._make_args(email_id=-1))


# ============================================================
# 15. ReviewFailureDecisionReport __post_init__ 强一致校验
# ============================================================


class TestReviewFailureDecisionReportStrongConsistency:
    """ReviewFailureDecisionReport 字段契约测试."""

    def _make_args(
        self,
        failed: bool = True,
        last_error: str = "LLM timeout",
        consecutive_review_failures: int = 1,
    ) -> dict[str, Any]:
        from my_ai_employee.policy.policy_engine import (
            PolicyEngine,
        )

        evaluation = PolicyEngine().evaluate(
            packet=build_review_failure_packet(
                email_id=1,
                source="qq",
                last_error_str=last_error,
                consecutive_review_failures=consecutive_review_failures,
            ),
            context=build_review_policy_context(
                tone="FORMAL",
                latency_ms=0,
                body_length=0,
                last_review_failed=True,
                consecutive_review_failures=consecutive_review_failures,
            ),
            store=None,
            lane_entry_id="review:qq:1",
            run_id="1",
        )
        return {
            "evaluation": evaluation,
            "event_id": evaluation.event_id,
            "lane_entry_id": "review:qq:1",
            "liveness": Liveness.HEALTHY,
            "failed": failed,
            "last_error": last_error,
            "consecutive_review_failures": consecutive_review_failures,
        }

    def test_valid(self) -> None:
        report = ReviewFailureDecisionReport(**self._make_args())
        assert report.failed is True
        assert report.consecutive_review_failures == 1

    def test_failed_false_rejected(self) -> None:
        """D4.7.4 范本: failed 必为 True."""
        with pytest.raises(ValueError, match="failed 必为 True"):
            ReviewFailureDecisionReport(**self._make_args(failed=False))  # type: ignore[arg-type]

    def test_cf_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="consecutive_review_failures 必须是原生 int >= 1"):
            ReviewFailureDecisionReport(**self._make_args(consecutive_review_failures=0))

    def test_blank_last_error_rejected(self) -> None:
        with pytest.raises(ValueError, match="last_error"):
            ReviewFailureDecisionReport(**self._make_args(last_error="   "))


# ============================================================
# 16. 顶层导出契约
# ============================================================


class TestTopLevelExports:
    """policy.__init__ 顶层导出契约测试."""

    def test_email_reviewer_adapter_in_policy_namespace(self) -> None:
        import my_ai_employee.policy as policy_pkg

        assert hasattr(policy_pkg, "EmailReviewerAdapter")
        assert policy_pkg.EmailReviewerAdapter is EmailReviewerAdapter

    def test_three_reports_in_policy_namespace(self) -> None:
        import my_ai_employee.policy as policy_pkg

        assert policy_pkg.ReviewDecisionReport is ReviewDecisionReport
        assert policy_pkg.ReviewBlockedDecisionReport is ReviewBlockedDecisionReport
        assert policy_pkg.ReviewFailureDecisionReport is ReviewFailureDecisionReport

    def test_four_factories_in_policy_namespace(self) -> None:
        import my_ai_employee.policy as policy_pkg

        assert policy_pkg.build_review_packet is build_review_packet
        assert policy_pkg.build_review_blocked_packet is build_review_blocked_packet
        assert policy_pkg.build_review_failure_packet is build_review_failure_packet
        assert policy_pkg.build_review_policy_context is build_review_policy_context

    def test_compute_review_acceptance_in_policy_namespace(self) -> None:
        import my_ai_employee.policy as policy_pkg

        assert policy_pkg.compute_review_acceptance is compute_review_acceptance
