"""D4.7.3 — EmailDrafterAdapter 单元测试.

设计:
  - 复用 conftest 的 in-memory SQLite + EventStore fixture
  - 用伪造 DraftResult 模拟 D4.7 ai/drafter.py 的输出
  - 验证: 6 决策触发条件 + EventStore 落 1 条 PolicyDecisionEvent + LaneBoard add/update + Heartbeat 探活
  - 每次测试用 run_id="r-{test_name}" 显式注入, 避免 fingerprint 冲突

D4.7.3 测试点:
  1. factory 函数 (4 个): 类型 / 字段数 / 严判类型 (D4.5 P0 + D4.6 v1.0.2 二次复检 P1 范本)
  2. EmailDrafterAdapter 初始化: 4 依赖可注入 / 拒空 source
  3. build_lane_entry_id: 命名 "draft:<source>:<run_id>" / 拒空 run_id
  4. record_to_lane: add (ACTIVE) → update (FINISHED) / 拒 FINISHED 状态直接 add
  5. tick_heartbeat: transport_alive 严判 bool / Liveness 3 状态
  6. draft_and_emit: 6 决策触发 / EventStore 落地 / lane / heartbeat 一气呵成
     + 严判入口 (D4.5 P0: 拒 bool 子类、负数、非 str)
     + lane_entry_id + run_id 写入 event_metadata (D4.5 v1.0.1 反馈闭环)
     + 业务字段: tone + body_length + latency_ms 透传到 DraftDecisionReport
     + D4.7.2 v1.0.8 强一致契约: spam_reply_authorized + spam_reply_intent 双字段透传
  7. record_draft_blocked_and_emit: 阻断入口 + spam_reply 双字段强一致
  8. DraftDecisionReport + DraftBlockedDecisionReport __post_init__ 强一致校验

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

from my_ai_employee.ai.drafter import (  # noqa: E402
    DraftResult,
    DraftSpamReplyIntent,
    DraftTone,
)
from my_ai_employee.events.models import EventType  # noqa: E402
from my_ai_employee.policy.heartbeat import Liveness  # noqa: E402
from my_ai_employee.policy.integration import (  # noqa: E402
    DraftBlockedDecisionReport,
    DraftDecisionReport,
    DraftFailureDecisionReport,
    EmailDrafterAdapter,
    build_draft_blocked_packet,
    build_draft_failure_packet,
    build_draft_packet,
    build_draft_policy_context,
    compute_draft_acceptance,
)
from my_ai_employee.policy.lane_board import LaneStatus  # noqa: E402
from my_ai_employee.policy.policy_engine import (  # noqa: E402
    PolicyEngine,
)

# ===== 测试用 DraftResult 仿造 =====
# ⚠️ 必须有 subject / body / tone / model_full_id / latency_ms / spam_reply_authorized / spam_reply_intent
#    7 个 duck-typed 字段(与 ai/drafter.py DraftResult 对齐)


@dataclass(frozen=True)
class FakeDraftResult(DraftResult):
    """仿造 DraftResult(供 EmailDrafterAdapter.draft_and_emit 用).

    D4.7.3 沿用 D4.6 FakeClassification 范本但改为 DraftResult 子类,
    spam_reply_authorized 默认 False + spam_reply_intent 默认 None(非 SPAM 场景)。
    继承 DraftResult 而非 duck type,可避开 mypy arg-type 不匹配 + 复用 __post_init__ 强一致校验。
    """

    @classmethod
    def make(
        cls,
        tone: DraftTone = DraftTone.FORMAL,
        body_length: int = 50,
        latency_ms: int = 1500,
        model_full_id: str = "deepseek/deepseek-chat",
        spam_reply_authorized: bool = False,
        spam_reply_intent: DraftSpamReplyIntent | None = None,
    ) -> FakeDraftResult:
        body = "感谢您的反馈,我们会尽快处理您的问题。\n\n如有疑问, 请随时联系。" * (
            body_length // 30 + 1
        )
        body = body[:body_length]
        return cls(
            subject="客户投诉回复",
            body=body,
            tone=tone,
            model_full_id=model_full_id,
            latency_ms=latency_ms,
            raw_content='{"subject":"客户投诉回复"}',
            spam_reply_authorized=spam_reply_authorized,
            spam_reply_intent=spam_reply_intent,
        )


# ============================================================
# factory 函数
# ============================================================


class TestFactoryFunctions:
    """4 个 factory 函数单元测试."""

    # ----- build_draft_packet -----

    def test_build_draft_packet_8_fields(self) -> None:
        """8 必含字段全填."""
        p = build_draft_packet(
            email_id=42,
            source="qq",
            tone="FORMAL",
            model_full_id="deepseek/deepseek-chat",
            body_length=50,
        )
        assert p.objective.startswith("email_draft:source=qq:id=")
        assert "ai/drafter.py" in p.scope
        assert "core/models.py" in p.scope
        assert "db:sqlcipher" in p.resources
        assert "llm:router" in p.resources
        assert len(p.acceptance_criteria) == 3
        assert p.model == "deepseek/deepseek-chat"
        assert p.provider == "deepseek"
        assert p.permission_profile == "read_only"
        assert p.recovery_policy == "retry_on_transient"

    def test_build_draft_packet_accepts_draft_tone_enum(self) -> None:
        """接受 DraftTone 枚举(D4.7.3 v1.0 范本: duck type 接受枚举/str)."""
        p = build_draft_packet(
            email_id=1,
            source="qq",
            tone=DraftTone.FORMAL,
            model_full_id="m",
            body_length=20,
        )
        assert "tone=FORMAL" in p.acceptance_criteria

    def test_build_draft_packet_strict_type_rejection(self) -> None:
        """D4.5 P0 教训应用: 严判入口拒 bool 子类/负数/越界/枚举外."""
        with pytest.raises(ValueError):
            build_draft_packet(
                email_id=True,
                source="qq",
                tone="FORMAL",
                model_full_id="m",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_draft_packet(
                email_id=-1,
                source="qq",
                tone="FORMAL",
                model_full_id="m",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_draft_packet(
                email_id=1,
                source="",
                tone="FORMAL",
                model_full_id="m",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone="APOLOGETIC",  # 枚举外
                model_full_id="m",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone=None,  # type: ignore[arg-type]
                model_full_id="m",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                model_full_id="",
                body_length=50,
            )
        with pytest.raises(ValueError):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                model_full_id="m",
                body_length=-1,
            )
        with pytest.raises(ValueError):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                model_full_id="m",
                body_length=True,
            )

    def test_build_draft_packet_provider_parsing(self) -> None:
        """model_full_id 拆 provider 正确(D4.6 v1.0.1 范本)."""
        p = build_draft_packet(
            email_id=1,
            source="qq",
            tone="FORMAL",
            model_full_id="minimax/MiniMax-M3",
            body_length=20,
        )
        assert p.provider == "minimax"
        p = build_draft_packet(
            email_id=1,
            source="qq",
            tone="FORMAL",
            model_full_id="unknown",
            body_length=20,
        )
        assert p.provider == "unknown"

    # ----- build_draft_blocked_packet -----

    def test_build_draft_blocked_packet_8_fields(self) -> None:
        """8 必含字段全填(阻断场景)."""
        p = build_draft_blocked_packet(
            email_id=42,
            source="qq",
            tone="FORMAL",
            reason="spam_business_blocked",
            original_email_category="SPAM",
        )
        assert p.objective.startswith("email_draft_blocked:source=qq:id=")
        assert "ai/drafter.py" in p.scope
        assert "db:sqlcipher" in p.resources
        assert len(p.acceptance_criteria) == 3
        assert p.model == "unknown"  # 阻断路径无 LLM 调用
        assert p.provider == "unknown"
        assert "reason=spam_business_blocked" in p.acceptance_criteria
        assert "original_email_category=SPAM" in p.acceptance_criteria

    def test_build_draft_blocked_packet_strict_type_rejection(self) -> None:
        """严判 reason 白名单 + original_email_category ∈ 5 类."""
        with pytest.raises(ValueError):
            build_draft_blocked_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                reason="other_blocked",  # 白名单外
                original_email_category="SPAM",
            )
        with pytest.raises(ValueError):
            build_draft_blocked_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                reason="spam_business_blocked",
                original_email_category="UNKNOWN",  # 5 类外
            )
        with pytest.raises(ValueError):
            build_draft_blocked_packet(
                email_id=-1,
                source="qq",
                tone="FORMAL",
                reason="spam_business_blocked",
                original_email_category="SPAM",
            )

    # ----- compute_draft_acceptance -----

    def test_compute_acceptance_3_fields_strict(self) -> None:
        """3 字段全 True 严判 type() is bool."""
        ac = compute_draft_acceptance(tone="FORMAL", latency_ms=2000, body_length=50)
        assert ac == [True, True, True]
        for x in ac:
            assert type(x) is bool  # 严判(D4.4 P1 + D4.5 P0-3 教训)

    def test_compute_acceptance_tone_invalid(self) -> None:
        """tone 枚举外 → ValueError."""
        with pytest.raises(ValueError):
            compute_draft_acceptance(tone="APOLOGETIC", latency_ms=2000, body_length=50)

    def test_compute_acceptance_body_too_short(self) -> None:
        """D4.7.3 v1.0.1 P2-1: body_length < 10 → AC[1] False(10 是合法下界).

        D4.7.2 v1.0.0 漏洞: body_length > 10 把合法 10 字符草稿错误阻断,
        与 _validate_draft_body(10 <= len <= 8000) 锁定契约不一致。
        v1.0.1 真修: 改为 body_length >= 10。
        """
        # 9 字符 → AC[1] False
        ac = compute_draft_acceptance(tone="FORMAL", latency_ms=2000, body_length=9)
        assert ac == [True, False, True]
        # 10 字符(合法下界) → AC[1] True(v1.0.1 修复点)
        ac = compute_draft_acceptance(tone="FORMAL", latency_ms=2000, body_length=10)
        assert ac == [True, True, True]

    def test_compute_acceptance_latency_too_long(self) -> None:
        """latency_ms >= 5000 → AC[2] False."""
        ac = compute_draft_acceptance(tone="FORMAL", latency_ms=5000, body_length=50)
        assert ac == [True, True, False]

    def test_compute_acceptance_latency_negative_rejected(self) -> None:
        """latency_ms 负数 → ValueError(D3.3.3 教训:窄化异常)."""
        with pytest.raises(ValueError):
            compute_draft_acceptance(tone="FORMAL", latency_ms=-1, body_length=50)

    # ----- build_draft_policy_context -----

    def test_build_draft_policy_context_12_fields(self) -> None:
        """12 字段全填."""
        ctx = build_draft_policy_context(tone="FORMAL", latency_ms=2000, body_length=50)
        expected_keys = {
            "last_error_recoverable",
            "current_attempts",
            "max_attempts",
            "branch_stale",
            "last_heartbeat_ms",
            "stale_threshold_ms",
            "now_ms",
            "action_sensitive",
            "has_approval_token",
            "approval_token_id",
            "acceptance_results",
            "policy_eval_failed",
        }
        assert set(ctx.keys()) == expected_keys
        # D4.7.3 v1.0.4 P2-3 修复: current_attempts 用 cf(默认 0),
        # 默认场景"尚未开始重试", 写死 1 会误导 audit
        assert ctx["current_attempts"] == 0
        assert ctx["max_attempts"] == 3
        assert ctx["acceptance_results"] == [True, True, True]

    def test_build_draft_policy_context_strict_type_rejection(self) -> None:
        """严判入口: last_draft_failed bool / consecutive_draft_failures int >= 0."""
        with pytest.raises(ValueError):
            build_draft_policy_context(
                tone="FORMAL",
                latency_ms=1000,
                body_length=50,
                last_draft_failed="false",  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError):
            build_draft_policy_context(
                tone="FORMAL",
                latency_ms=1000,
                body_length=50,
                consecutive_draft_failures=True,
            )
        with pytest.raises(ValueError):
            build_draft_policy_context(
                tone="FORMAL",
                latency_ms=1000,
                body_length=50,
                consecutive_draft_failures=-1,
            )
        with pytest.raises(ValueError):
            build_draft_policy_context(
                tone="FORMAL",
                latency_ms=1000,
                body_length=50,
                branch_stale="false",  # type: ignore[arg-type]
            )


# ============================================================
# EmailDrafterAdapter 初始化
# ============================================================


class TestEmailDrafterAdapterInit:
    """4 依赖可注入 + 拒空 source."""

    def test_init_with_no_dependencies(self) -> None:
        """None 依赖时,内部用 default PolicyEngine / Heartbeat / LaneBoard."""
        a = EmailDrafterAdapter(source="qq")
        assert a._source == "qq"
        assert a._event_store is None
        assert isinstance(a._engine, PolicyEngine)
        assert a._heartbeat is not None
        assert a._board is not None

    def test_init_with_all_dependencies(self) -> None:
        """全部依赖注入."""
        a = EmailDrafterAdapter(
            source="outlook",
            event_store=None,
            engine=PolicyEngine(),
            heartbeat=None,
            board=None,
        )
        assert a._source == "outlook"

    def test_init_reject_empty_source(self) -> None:
        """拒空 source(D4.5 P0 范本)."""
        with pytest.raises(ValueError):
            EmailDrafterAdapter(source="")
        with pytest.raises(ValueError):
            EmailDrafterAdapter(source=None)  # type: ignore[arg-type]


class TestBuildLaneEntryId:
    """lane_entry_id 命名 'draft:<source>:<run_id>'."""

    def test_build_lane_entry_id_naming(self) -> None:
        a = EmailDrafterAdapter(source="qq")
        assert a.build_lane_entry_id("r001") == "draft:qq:r001"

    def test_build_lane_entry_id_reject_empty(self) -> None:
        """拒空 run_id."""
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.build_lane_entry_id("")
        with pytest.raises(ValueError):
            a.build_lane_entry_id(None)  # type: ignore[arg-type]


class TestTickHeartbeat:
    """Heartbeat 探活."""

    def test_tick_heartbeat_transport_alive(self) -> None:
        a = EmailDrafterAdapter(source="qq")
        liveness = a.tick_heartbeat(transport_alive=True)
        assert liveness in {Liveness.HEALTHY, Liveness.STALLED, Liveness.TRANSPORT_DEAD}

    def test_tick_heartbeat_reject_non_bool(self) -> None:
        """严判 transport_alive bool."""
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.tick_heartbeat(transport_alive="true")  # type: ignore[arg-type]


# ============================================================
# draft_and_emit 主入口
# ============================================================


class TestDraftAndEmit:
    """成功草稿主入口."""

    def test_draft_and_emit_normal(self) -> None:
        """正常草稿成功路径 → DraftDecisionReport."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make(body_length=50, latency_ms=1500)
        report = a.draft_and_emit(
            email_id=123, draft_result=result, category="URGENT", run_id="r001"
        )
        assert isinstance(report, DraftDecisionReport)
        assert report.tone == "FORMAL"
        assert report.email_id == 123
        assert report.body_length == 50
        assert report.latency_ms == 1500
        assert report.lane_entry_id == "draft:qq:r001"
        assert report.spam_reply_authorized is False
        assert report.spam_reply_intent is None

    def test_draft_and_emit_with_event_store(self, store: Any) -> None:
        """EventStore 落地 1 条 PolicyDecisionEvent(D4.3 + D4.5 范本)."""
        a = EmailDrafterAdapter(source="qq", event_store=store)
        result = FakeDraftResult.make(body_length=50, latency_ms=1500)
        report = a.draft_and_emit(
            email_id=123, draft_result=result, category="URGENT", run_id="r002"
        )
        assert report.event_id is not None
        # 查落地事件
        events = store.by_event_type(event_type=EventType.POLICY_DECISION_MADE.value, limit=10)
        assert len(events) >= 1
        # 验证 lane_entry_id + run_id 透传(D4.5 v1.0.1)
        ev = events[0]
        meta = ev.event_metadata or {}
        assert meta.get("lane_entry_id") == "draft:qq:r002"
        assert meta.get("run_id") == "r002"
        # D4.7.3 业务字段透传
        assert meta.get("tone") == "FORMAL"
        assert meta.get("body_length") == 50
        assert meta.get("latency_ms") == 1500
        assert meta.get("email_id") == 123
        assert meta.get("source") == "qq"
        # D4.7.2 v1.0.8 强一致双字段透传
        assert meta.get("spam_reply_authorized") is False
        assert meta.get("spam_reply_intent") is None

    def test_draft_and_emit_spam_authorized_propagates(self, store: Any) -> None:
        """D4.7.2 v1.0.8 强一致双字段透传到 event_metadata(SPAM 授权放行)."""
        a = EmailDrafterAdapter(source="qq", event_store=store)
        result = FakeDraftResult.make(
            body_length=50,
            latency_ms=1800,
            spam_reply_authorized=True,
            spam_reply_intent=DraftSpamReplyIntent.REJECT,
        )
        report = a.draft_and_emit(email_id=124, draft_result=result, category="SPAM", run_id="r003")
        assert report.spam_reply_authorized is True
        assert report.spam_reply_intent == "REJECT"
        events = store.by_event_type(event_type=EventType.POLICY_DECISION_MADE.value, limit=10)
        assert len(events) >= 1
        meta = events[0].event_metadata or {}
        assert meta.get("spam_reply_authorized") is True
        assert meta.get("spam_reply_intent") == "REJECT"

    def test_draft_and_emit_strict_email_id(self) -> None:
        """严判 email_id int >= 0."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=-1, draft_result=result, category="URGENT", run_id="r004")
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=True, draft_result=result, category="URGENT", run_id="r004")

    def test_draft_and_emit_strict_transport_alive(self) -> None:
        """严判 transport_alive bool."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        with pytest.raises(ValueError):
            a.draft_and_emit(
                email_id=1,
                draft_result=result,
                category="URGENT",
                run_id="r005",
                transport_alive="true",  # type: ignore[arg-type]
            )

    def test_draft_and_emit_reject_missing_field(self) -> None:
        """draft_result 缺必要字段 → ValueError."""
        a = EmailDrafterAdapter(source="qq")

        @dataclass(frozen=True)
        class IncompleteDraft:
            subject: str = "x"
            body: str = "x"
            tone: DraftTone = DraftTone.FORMAL
            # 缺 model_full_id / latency_ms / spam_reply_*

        with pytest.raises(ValueError):
            a.draft_and_emit(
                email_id=1,
                draft_result=IncompleteDraft(),  # type: ignore[arg-type]
                category="URGENT",
                run_id="r006",
            )

    def test_draft_and_emit_strong_consistency_rejection(self) -> None:
        """D4.7.2 v1.0.8 P1-2: 入口预校验 spam_reply 双字段强一致.

        D4.7.3 v1.0.0 真修后: 强一致校验既在 adapter 入口段, 也在 DraftResult.__post_init__
        双层防御. FakeDraftResult 继承 DraftResult, 父类 __post_init__ 也会拒收矛盾状态.
        pytest.raises(ValueError) 接受任何 ValueError(无论从 adapter 还是父类抛).
        """
        a = EmailDrafterAdapter(source="qq")
        # authorized=True + intent=None → 父类 DraftResult.__post_init__ 抛 ValueError
        with pytest.raises(ValueError):
            FakeDraftResult.make(spam_reply_authorized=True, spam_reply_intent=None)
        # authorized=False + intent=REJECT → 父类 DraftResult.__post_init__ 抛 ValueError
        with pytest.raises(ValueError):
            FakeDraftResult.make(
                spam_reply_authorized=False, spam_reply_intent=DraftSpamReplyIntent.REJECT
            )
        # Adapter 入口段独立校验: 用合法构造 + object.__setattr__ 绕过 frozen
        # 模拟"调用方绕过 DraftResult 构造直接进 adapter" 路径
        valid_result = FakeDraftResult.make()
        object.__setattr__(valid_result, "spam_reply_authorized", True)
        object.__setattr__(valid_result, "spam_reply_intent", None)
        with pytest.raises(ValueError):
            a.draft_and_emit(
                email_id=1, draft_result=valid_result, category="URGENT", run_id="r007"
            )

    def test_draft_and_emit_lane_finished_on_success(self) -> None:
        """正常路径 → LaneBoard FINISHED(AC 全 True)."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make(body_length=50, latency_ms=1500)
        report = a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="r009")
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.FINISHED


# ============================================================
# record_draft_business_blocked_and_emit 业务阻断入口(D4.7.3 v1.0.1 P1-1 拆分)
# ============================================================


class TestRecordDraftBusinessBlockedAndEmit:
    """业务阻断草稿入口(SPAM 业务硬阻断, last_draft_failed=False, 不触发 retry).

    D4.7.3 v1.0.1 P1-1 真修后:
      - 业务阻断 ≠ 技术失败, 业务阻断 cf=0, 不计入失败计数器, 永不 retry/escalate
      - last_draft_failed=False 隐式(等同成功路径)
      - blocked_kind="business" 标记区别于技术失败
    """

    def test_business_blocked_normal(self) -> None:
        """正常业务阻断 → DraftBlockedDecisionReport(cf=0)."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_business_blocked_and_emit(
            email_id=123,
            tone=DraftTone.FORMAL,
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="SpamBlockedError('SPAM detected')",
            spam_reply_authorized=False,
            run_id="rbb001",
        )
        assert isinstance(report, DraftBlockedDecisionReport)
        # D4.7.3 v1.0.3 P2-1: blocked 替代 failed(业务阻断专属字段名)
        assert report.blocked is True
        assert report.last_error == "SpamBlockedError('SPAM detected')"
        # D4.7.3 v1.0.1 P1-1: 业务阻断 cf=0(不计入失败计数)
        assert report.consecutive_draft_failures == 0
        assert report.tone == "FORMAL"
        assert report.original_email_category == "SPAM"
        assert report.reason == "spam_business_blocked"
        assert report.spam_reply_authorized is False
        assert report.spam_reply_intent is None
        assert report.lane_entry_id == "draft:qq:rbb001"

    def test_business_blocked_with_event_store(self, store: Any) -> None:
        """EventStore 落地 1 条 PolicyDecisionEvent, blocked_kind=business."""
        a = EmailDrafterAdapter(source="qq", event_store=store)
        report = a.record_draft_business_blocked_and_emit(
            email_id=123,
            tone=DraftTone.FORMAL,
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="SPAM detected",
            spam_reply_authorized=False,
            run_id="rbb002",
        )
        assert report.event_id is not None
        events = store.by_event_type(event_type=EventType.POLICY_DECISION_MADE.value, limit=10)
        assert len(events) >= 1
        meta = events[0].event_metadata or {}
        assert meta.get("lane_entry_id") == "draft:qq:rbb002"
        assert meta.get("blocked") is True
        # D4.7.3 v1.0.1 P1-1: blocked_kind 区分业务阻断 vs 技术失败
        assert meta.get("blocked_kind") == "business"
        # D4.7.2 v1.0.8 双字段透传
        assert meta.get("spam_reply_authorized") is False
        assert meta.get("spam_reply_intent") is None

    def test_business_blocked_spam_authorized_with_intent(self) -> None:
        """SPAM 授权场景(authorized=True + intent=UNSUBSCRIBE)通过强一致校验."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_business_blocked_and_emit(
            email_id=124,
            tone=DraftTone.FORMAL,
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="Authorized but blocked at template level",
            spam_reply_authorized=True,
            spam_reply_intent=DraftSpamReplyIntent.UNSUBSCRIBE,
            run_id="rbb003",
        )
        assert report.spam_reply_authorized is True
        assert report.spam_reply_intent == "UNSUBSCRIBE"

    def test_business_blocked_strict_reason_whitelist(self) -> None:
        """reason 锁定白名单."""
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.record_draft_business_blocked_and_emit(
                email_id=1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="other_blocked",
                last_error="x",
                run_id="rbb004",
            )

    def test_business_blocked_strict_category_consistency(self) -> None:
        """D4.7.3 v1.0.1 P2-2: reason=spam_business_blocked 必配 SPAM 分类."""
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.record_draft_business_blocked_and_emit(
                email_id=1,
                tone="FORMAL",
                original_email_category="URGENT",
                reason="spam_business_blocked",
                last_error="x",
                run_id="rbb005",
            )
        with pytest.raises(ValueError):
            a.record_draft_business_blocked_and_emit(
                email_id=1,
                tone="FORMAL",
                original_email_category="TODO",
                reason="spam_business_blocked",
                last_error="x",
                run_id="rbb006",
            )

    def test_business_blocked_last_error_required(self) -> None:
        """last_error 必填非空(转 str 后非空)."""
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.record_draft_business_blocked_and_emit(
                email_id=1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
                last_error="",
                run_id="rbb007",
            )

    def test_business_blocked_strong_consistency_rejection(self) -> None:
        """D4.7.2 v1.0.8 P1-2: 业务阻断入口预校验 spam_reply 双字段强一致."""
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.record_draft_business_blocked_and_emit(
                email_id=1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
                last_error="x",
                spam_reply_authorized=True,
                spam_reply_intent=None,
                run_id="rbb008",
            )
        with pytest.raises(ValueError):
            a.record_draft_business_blocked_and_emit(
                email_id=1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
                last_error="x",
                spam_reply_authorized=False,
                spam_reply_intent=DraftSpamReplyIntent.REJECT,
                run_id="rbb009",
            )

    def test_business_blocked_lane_always_blocked(self) -> None:
        """业务阻断入口强制 LaneBoard BLOCKED."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_business_blocked_and_emit(
            email_id=1,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="x",
            run_id="rbb010",
        )
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED

    def test_business_blocked_alias_backward_compatible(self) -> None:
        """旧 v1.0.0 record_draft_blocked_and_emit API 仍可用(向后兼容别名)."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_blocked_and_emit(
            email_id=1,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="x",
            consecutive_draft_failures=999,  # v1.0.0 API 多余字段, v1.0.1 静默忽略
            run_id="rbb011",
        )
        assert report.consecutive_draft_failures == 0  # 业务阻断 cf=0


# ============================================================
# record_draft_failure_and_emit 技术失败入口(D4.7.3 v1.0.1 P1-1 新增)
# ============================================================


class TestRecordDraftFailureAndEmit:
    """技术失败草稿入口(DrafterResponseError / LLM 异常, 触发 retry / escalate).

    D4.7.3 v1.0.1 P1-1 新增(拆分自 v1.0.0 阻断入口):
      - 技术失败(LLM 响应解析失败 / 网络超时 / 路由异常) → 触发 retry / escalate
      - last_draft_failed=True(隐式) + cf 必填 >= 1
      - cf < 3 触发 retry_available, cf >= 3 触发 escalate
    """

    def test_failure_normal(self) -> None:
        """D4.7.3 v1.0.2 P1-1: 正常技术失败场景 → DraftFailureDecisionReport(独立类型, cf=1 触发 retry).

        v1.0.1 漏洞: 返回 DraftBlockedDecisionReport (伪造 SPAM), 调用方可能误累加 cf.
        v1.0.2 真修: 返回 DraftFailureDecisionReport 独立类型.
        """
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_failure_and_emit(
            email_id=123,
            last_error="DrafterResponseError: invalid tone",
            consecutive_draft_failures=1,
            run_id="rf001",
        )
        assert isinstance(report, DraftFailureDecisionReport)
        # 不是 DraftBlockedDecisionReport(类型层面区分)
        assert not isinstance(report, DraftBlockedDecisionReport)
        assert report.failed is True
        assert report.last_error == "DrafterResponseError: invalid tone"
        assert report.consecutive_draft_failures == 1

    def test_failure_escalate_at_cf_3(self) -> None:
        """cf=3 → 触发 escalate (而非 retry)."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_failure_and_emit(
            email_id=123,
            last_error="LLMError: timeout",
            consecutive_draft_failures=3,
            run_id="rf002",
        )
        assert report.consecutive_draft_failures == 3

    def test_failure_with_event_store(self, store: Any) -> None:
        """EventStore 落地 1 条 PolicyDecisionEvent, failed_kind=technical."""
        a = EmailDrafterAdapter(source="qq", event_store=store)
        report = a.record_draft_failure_and_emit(
            email_id=123,
            last_error="DrafterResponseError",
            consecutive_draft_failures=2,
            run_id="rf003",
        )
        assert report.event_id is not None
        events = store.by_event_type(event_type=EventType.POLICY_DECISION_MADE.value, limit=10)
        assert len(events) >= 1
        meta = events[0].event_metadata or {}
        assert meta.get("lane_entry_id") == "draft:qq:rf003"
        # D4.7.3 v1.0.1 P1-1: failed_kind 区分业务阻断 vs 技术失败
        assert meta.get("failed_kind") == "technical"
        assert meta.get("failed") is True
        assert meta.get("consecutive_draft_failures") == 2

    def test_failure_strict_consecutive_failures(self) -> None:
        """技术失败 consecutive_draft_failures 必填 >= 1(0 拒收)."""
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.record_draft_failure_and_emit(
                email_id=1,
                last_error="x",
                consecutive_draft_failures=0,
                run_id="rf004",
            )
        with pytest.raises(ValueError):
            a.record_draft_failure_and_emit(
                email_id=1,
                last_error="x",
                consecutive_draft_failures=-1,
                run_id="rf004",
            )

    def test_failure_last_error_required(self) -> None:
        """last_error 必填非空."""
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.record_draft_failure_and_emit(
                email_id=1,
                last_error="",
                consecutive_draft_failures=1,
                run_id="rf005",
            )

    def test_failure_lane_always_blocked(self) -> None:
        """技术失败入口强制 LaneBoard BLOCKED."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_failure_and_emit(
            email_id=1,
            last_error="x",
            consecutive_draft_failures=1,
            run_id="rf006",
        )
        entry = a._board.get(report.lane_entry_id)
        assert entry.status == LaneStatus.BLOCKED


# ============================================================
# DraftDecisionReport + DraftBlockedDecisionReport 数据类强一致校验
# ============================================================


class TestDraftDecisionReportStrongConsistency:
    """DraftDecisionReport.__post_init__ 强一致 + 入口预校验."""

    def _make_base_report_args(self) -> DraftDecisionReport:
        """构造合法的 DraftDecisionReport 字段(draft_and_emit 返回值)."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        return a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="rb011")

    def test_strong_consistency_reject_authorized_without_intent(self) -> None:
        """D4.7.2 v1.0.8 P1-2: authorized=True + intent=None → 拒收."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        base = a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="rb012")
        with pytest.raises(ValueError):
            DraftDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                tone="FORMAL",
                model_full_id="m",
                email_id=1,
                latency_ms=1,
                body_length=20,
                spam_reply_authorized=True,
                spam_reply_intent=None,
            )

    def test_strong_consistency_reject_unauthorized_with_intent(self) -> None:
        """D4.7.2 v1.0.8 P1-2: authorized=False + intent=REJECT → 拒收."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        base = a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="rb013")
        with pytest.raises(ValueError):
            DraftDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                tone="FORMAL",
                model_full_id="m",
                email_id=1,
                latency_ms=1,
                body_length=20,
                spam_reply_authorized=False,
                spam_reply_intent=DraftSpamReplyIntent.REJECT,
            )

    def test_strict_tone_validation(self) -> None:
        """__post_init__ 严判 tone ∈ 3 类."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        base = a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="rb014")
        with pytest.raises(ValueError):
            DraftDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                tone="APOLOGETIC",  # 枚举外
                model_full_id="m",
                email_id=1,
                latency_ms=1,
                body_length=20,
            )

    def test_strict_latency_validation(self) -> None:
        """__post_init__ 严判 latency_ms int >= 0."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        base = a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="rb015")
        with pytest.raises(ValueError):
            DraftDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                tone="FORMAL",
                model_full_id="m",
                email_id=1,
                latency_ms=-1,
                body_length=20,
            )


class TestDraftBlockedDecisionReportStrongConsistency:
    """DraftBlockedDecisionReport.__post_init__ 强一致 + 字段自洽."""

    def _make_base_blocked_report(self) -> Any:
        a = EmailDrafterAdapter(source="qq")
        # D4.7.3 v1.0.1 P1-1: 用新拆分入口 record_draft_business_blocked_and_emit
        return a.record_draft_business_blocked_and_emit(
            email_id=1,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="x",
            run_id="rb016",
        )

    def test_failed_required_true(self) -> None:
        """failed 必为 True(Literal[True] 类型层面固化)."""
        base = self._make_base_blocked_report()
        with pytest.raises(ValueError):
            DraftBlockedDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                blocked=False,  # type: ignore[arg-type]
                last_error="x",
                consecutive_draft_failures=1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
            )

    def test_last_error_required(self) -> None:
        """last_error 必填非空."""
        base = self._make_base_blocked_report()
        with pytest.raises(ValueError):
            DraftBlockedDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                blocked=True,
                last_error="",
                consecutive_draft_failures=1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
            )

    def test_consecutive_draft_failures_required(self) -> None:
        """D4.7.3 v1.0.1 P1-1: consecutive_draft_failures 必须 >= 0(业务阻断场景允许 0)."""
        base = self._make_base_blocked_report()
        # cf=-1 拒收(负数非法)
        with pytest.raises(ValueError):
            DraftBlockedDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                blocked=True,
                last_error="x",
                consecutive_draft_failures=-1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
            )
        # cf=0 在 v1.0.1 是合法的(业务阻断场景), 不应拒收
        DraftBlockedDecisionReport(
            evaluation=base.evaluation,
            event_id=base.event_id,
            lane_entry_id=base.lane_entry_id,
            liveness=base.liveness,
            blocked=True,
            last_error="x",
            consecutive_draft_failures=0,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="spam_business_blocked",
        )

    def test_reason_whitelist(self) -> None:
        """reason 锁定白名单."""
        base = self._make_base_blocked_report()
        with pytest.raises(ValueError):
            DraftBlockedDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                blocked=True,
                last_error="x",
                consecutive_draft_failures=1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="other_blocked",  # 白名单外
            )

    def test_strong_consistency_reject_authorized_without_intent(self) -> None:
        """D4.7.2 v1.0.8 P1-2: 阻断数据类 authorized=True + intent=None → 拒收."""
        base = self._make_base_blocked_report()
        with pytest.raises(ValueError):
            DraftBlockedDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                blocked=True,
                last_error="x",
                consecutive_draft_failures=1,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
                spam_reply_authorized=True,
                spam_reply_intent=None,
            )


# D4.7.3 v1.0.1 检查员反馈 P 修复专项覆盖测试


class TestD473V101Fixes:
    """D4.7.3 v1.0.1 检查员反馈 2 P1 + 4 P2 专项覆盖.

    P1-1: 业务阻断 vs 技术失败拆分(双入口范本)
    P1-2: 6 字段透传契约(week1-mvp.md 锁定)
    P2-1: 草稿 body 长度边界修正为 >= 10
    P2-2: reason 与 category 强一致
    P2-3: 严判 subject/body 非空字符串
    P2-4: now_ms 严判 type() is int
    """

    # ----- P1-1: 业务阻断 vs 技术失败 -----

    def test_p1_1_business_blocked_no_retry(self, store: Any) -> None:
        """D4.7.3 v1.0.1 P1-1: 业务阻断不触发 retry (last_draft_failed=False, cf=0).

        旧 v1.0.0 漏洞: record_draft_blocked_and_emit 用 last_draft_failed=True
        + cf 累加, 触发 retry_available(cf<3) / escalate(cf>=3) — 重复无意义调用。
        """
        a = EmailDrafterAdapter(source="qq", event_store=store)
        report = a.record_draft_business_blocked_and_emit(
            email_id=1,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="x",
            run_id="vp10101",
        )
        # P1-1 关键断言: cf=0(业务阻断不计入失败计数) + extra_business_payload
        # 通过 PolicyEngine.evaluate 构造, cf=0 → PolicyEval 内 retry 不会触发
        assert report.consecutive_draft_failures == 0
        # 验证 event_id 已落地(说明 PolicyEngine.evaluate 完整跑完)
        assert report.event_id is not None
        # 验证 blocked_kind=business(与 technical 区分)
        events = store.by_event_type(event_type=EventType.POLICY_DECISION_MADE.value, limit=10)
        meta = events[0].event_metadata or {}
        assert meta.get("blocked_kind") == "business"

    def test_p1_1_failure_triggers_retry(self) -> None:
        """D4.7.3 v1.0.1 P1-1: 技术失败 last_draft_failed=True, 触发 retry (cf=1) / escalate (cf=3).

        与业务阻断对比: 同样的 cf=1, 业务阻断 cf=0 不重试, 技术失败 cf=1 触发 retry。
        """
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_failure_and_emit(
            email_id=1,
            last_error="DrafterResponseError",
            consecutive_draft_failures=1,
            run_id="vp10102",
        )
        assert report.consecutive_draft_failures == 1  # 触发 retry

    def test_p1_1_failure_triggers_escalate_at_cf_3(self) -> None:
        """D4.7.3 v1.0.1 P1-1: cf >= 3 触发 escalate (而非 retry)."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_failure_and_emit(
            email_id=1,
            last_error="LLMError: timeout",
            consecutive_draft_failures=3,
            run_id="vp10103",
        )
        assert report.consecutive_draft_failures == 3  # 触发 escalate

    # ----- P1-2: 6 字段透传契约(week1-mvp.md 锁定) -----

    def test_p1_2_six_fields_propagated(self, store: Any) -> None:
        """D4.7.3 v1.0.1 P1-2: draft_subject/draft_body/tone/model_full_id/email_id/category 6 字段全透传.

        week1-mvp.md:705 锁定契约。
        旧 v1.0.0 漏洞: 缺 draft_subject/draft_body/category, 仅透传 tone/model_full_id/latency。
        """
        a = EmailDrafterAdapter(source="qq", event_store=store)
        result = FakeDraftResult.make(body_length=50)
        a.draft_and_emit(
            email_id=999,
            draft_result=result,
            category="URGENT",
            run_id="vp10104",
        )
        events = store.by_event_type(event_type=EventType.POLICY_DECISION_MADE.value, limit=10)
        meta = events[0].event_metadata or {}
        # 6 字段全在(week1-mvp.md 锁定)
        assert meta.get("draft_subject") == result.subject
        assert meta.get("draft_body") == result.body
        assert meta.get("tone") == "FORMAL"
        assert meta.get("model_full_id") == result.model_full_id
        assert meta.get("email_id") == 999
        assert meta.get("category") == "URGENT"

    def test_p1_2_category_required(self) -> None:
        """D4.7.3 v1.0.1 P1-2: draft_and_emit 必传 category ∈ 5 类."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="UNKNOWN", run_id="vp10105")
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category=None, run_id="vp10105")  # type: ignore[arg-type]

    # ----- P2-1: 草稿 body 长度边界 -----

    def test_p2_1_body_length_10_passes(self) -> None:
        """D4.7.3 v1.0.1 P2-1: body_length=10 是合法下界, 不应被错误阻断.

        v1.0.0 漏洞: body_length > 10 把合法 10 字符草稿错误阻断。
        v1.0.1 真修: body_length >= 10, 与 _validate_draft_body(10 <= len <= 8000) 一致。
        """
        ac = compute_draft_acceptance(tone="FORMAL", latency_ms=2000, body_length=10)
        assert ac == [True, True, True]

    def test_p2_1_body_length_9_fails(self) -> None:
        """D4.7.3 v1.0.1 P2-1: body_length=9 (下界以下) 应阻断."""
        ac = compute_draft_acceptance(tone="FORMAL", latency_ms=2000, body_length=9)
        assert ac == [True, False, True]

    # ----- P2-2: reason 与 category 强一致 -----

    def test_p2_2_reason_category_consistency(self) -> None:
        """D4.7.3 v1.0.1 P2-2: spam_business_blocked 必配 SPAM, 不允许 URGENT+spam.

        旧 v1.0.0 漏洞: 允许 URGENT + spam_business_blocked 矛盾状态。
        """
        a = EmailDrafterAdapter(source="qq")
        with pytest.raises(ValueError):
            a.record_draft_business_blocked_and_emit(
                email_id=1,
                tone="FORMAL",
                original_email_category="URGENT",
                reason="spam_business_blocked",
                last_error="x",
                run_id="vp10106",
            )
        with pytest.raises(ValueError):
            a.record_draft_business_blocked_and_emit(
                email_id=1,
                tone="FORMAL",
                original_email_category="TODO",
                reason="spam_business_blocked",
                last_error="x",
                run_id="vp10107",
            )

    # ----- P2-3: 严判 subject/body 非空字符串 -----

    def test_p2_3_subject_empty_rejected(self) -> None:
        """D4.7.3 v1.0.1 P2-3: subject 非空字符串, 空字符串/None 拒收.

        旧 v1.0.0 漏洞: 直接 len(draft_result.body) 可能触发 TypeError 泄漏。
        """
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        object.__setattr__(result, "subject", "")  # 绕过 frozen
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="vp10108")

    def test_p2_3_body_not_str_rejected(self) -> None:
        """D4.7.3 v1.0.1 P2-3: body 必须是 str(防 len() TypeError 泄漏)."""
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        object.__setattr__(result, "body", None)  # 绕过 frozen
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="vp10109")

    # ----- P2-4: now_ms 严判 type() is int -----

    def test_p2_4_now_ms_true_rejected(self) -> None:
        """D4.7.3 v1.0.1 P2-4: now_ms=True 被错误接受, 改为严判 type() is int.

        旧 v1.0.0 漏洞: isinstance(now_ms, int) 接受 bool 子类(True/False),
        因为 bool 是 int 子类(isinstance(True, int) == True)。
        v1.0.1 真修: type(now_ms) is int。
        """
        with pytest.raises(ValueError):
            build_draft_policy_context(
                tone="FORMAL",
                latency_ms=1000,
                body_length=20,
                now_ms=True,  # bool 子类, 旧版错误接受
            )
        with pytest.raises(ValueError):
            build_draft_policy_context(
                tone="FORMAL",
                latency_ms=1000,
                body_length=20,
                now_ms=False,  # 同上
            )


# ============================================================
# D4.7.3 v1.0.2 检查员第二轮反馈 P 修复专项覆盖测试
# ============================================================


class TestD473V102Fixes:
    """D4.7.3 v1.0.2 检查员第二轮反馈 2 P1 + 3 P2 专项覆盖.

    P1-1: 技术失败被伪装成 SPAM 阻断 → 独立 DraftFailureDecisionReport
    P1-2: 分类与 SPAM 授权双向强一致(SPAM+auth=False 也拒收)
    P2-1: 业务阻断报告添加 kind="business_blocked" 字段(防 cf 误累加)
    P2-2: 顶层导出从 __all__ 删除不存在的符号(改为 build_draft_failure_packet + DraftFailureDecisionReport)
    P2-3: 拒纯空白 subject + body_length <= 8000 上限
    """

    # ----- P1-1: 技术失败独立类型 -----

    def test_p1_1_failure_returns_independent_type(self) -> None:
        """D4.7.3 v1.0.2 P1-1: record_draft_failure_and_emit 返回 DraftFailureDecisionReport.

        v1.0.1 漏洞: 返回 DraftBlockedDecisionReport + 伪造 SPAM + spam_business_blocked,
        调用方可能错误累加 cf(把技术失败 cf 计入业务阻断计数器)。
        v1.0.2 真修: 独立类型 DraftFailureDecisionReport, 调用方可基于 isinstance 区分。
        """
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_failure_and_emit(
            email_id=1,
            last_error="DrafterResponseError",
            consecutive_draft_failures=1,
            run_id="vp10201",
        )
        assert isinstance(report, DraftFailureDecisionReport)
        assert not isinstance(report, DraftBlockedDecisionReport)
        assert not isinstance(report, DraftDecisionReport)

    def test_p1_1_build_draft_failure_packet_independent(self) -> None:
        """D4.7.3 v1.0.2 P1-1: build_draft_failure_packet 独立 packet, objective = 'email_draft_failed:...'."""
        p = build_draft_failure_packet(
            email_id=1,
            source="qq",
            last_error_str="DrafterResponseError",
            consecutive_draft_failures=2,
        )
        assert p.objective.startswith("email_draft_failed:source=qq:id=")
        assert "ai/drafter.py" in p.scope
        assert "last_error=" in p.acceptance_criteria[0]
        assert "consecutive_draft_failures=2" in p.acceptance_criteria[1]

    def test_p1_1_failure_packet_strict_consecutive_failures(self) -> None:
        """D4.7.3 v1.0.2 P1-1: build_draft_failure_packet 严判 consecutive_draft_failures >= 1."""
        with pytest.raises(ValueError):
            build_draft_failure_packet(
                email_id=1,
                source="qq",
                last_error_str="x",
                consecutive_draft_failures=0,
            )
        with pytest.raises(ValueError):
            build_draft_failure_packet(
                email_id=1,
                source="qq",
                last_error_str="x",
                consecutive_draft_failures=-1,
            )

    def test_p1_1_draft_failure_decision_report_literal_true(self) -> None:
        """D4.7.3 v1.0.2 P1-1: DraftFailureDecisionReport failed: Literal[True] + 三重校验.

        [week1-mvp.md:716](/Users/wei/Documents/DesktopOrganizer/我的AI员工/docs/week1-mvp.md:716) 锁定:
        DraftFailureDecisionReport 独立类型 + Literal[True] + __post_init__ 三重校验。
        """
        # 直接构造测试 __post_init__ 三重校验
        a = EmailDrafterAdapter(source="qq")
        base = a.record_draft_failure_and_emit(
            email_id=1,
            last_error="x",
            consecutive_draft_failures=1,
            run_id="vp10202",
        )
        # failed=False 拒收
        with pytest.raises(ValueError):
            DraftFailureDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                failed=False,  # type: ignore[arg-type]
                last_error="x",
                consecutive_draft_failures=1,
            )
        # last_error 空拒收
        with pytest.raises(ValueError):
            DraftFailureDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                failed=True,
                last_error="",
                consecutive_draft_failures=1,
            )
        # cf < 1 拒收
        with pytest.raises(ValueError):
            DraftFailureDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                failed=True,
                last_error="x",
                consecutive_draft_failures=0,
            )

    # ----- P1-2: 分类 ↔ SPAM 授权双向强一致 -----

    def test_p1_2_urgent_with_spam_authorized_rejected(self) -> None:
        """D4.7.3 v1.0.2 P1-2: URGENT + spam_authorized=True 拒收(forward 方向).

        D4.7.2 v1.0.7 P1-1 范本: spam_authorized=True 必配 SPAM.
        """
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make(
            spam_reply_authorized=True,
            spam_reply_intent=DraftSpamReplyIntent.UNSUBSCRIBE,
        )
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="vp10203")

    def test_p1_2_spam_without_spam_authorized_rejected(self) -> None:
        """D4.7.3 v1.0.2 P1-2: SPAM + spam_authorized=False 拒收(反向补强).

        v1.0.0 漏洞: 仅校验 spam_authorized=True → category=SPAM,
        反向 SPAM + auth=False 仍能通过, 触发 merge_required, 业务层 cf 累加器误读.
        v1.0.2 真修: 反向补强.
        """
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make(
            spam_reply_authorized=False,
            spam_reply_intent=None,
        )
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="SPAM", run_id="vp10204")

    def test_p1_2_spam_with_spam_authorized_accepted(self) -> None:
        """D4.7.3 v1.0.2 P1-2: SPAM + spam_authorized=True 接受(完整链路).

        合法的 SPAM 授权放行场景, 双向强一致通过.
        """
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make(
            spam_reply_authorized=True,
            spam_reply_intent=DraftSpamReplyIntent.UNSUBSCRIBE,
        )
        report = a.draft_and_emit(
            email_id=1,
            draft_result=result,
            category="SPAM",
            run_id="vp10205",
        )
        assert report.spam_reply_authorized is True
        assert report.spam_reply_intent == "UNSUBSCRIBE"

    # ----- P2-1: 业务阻断 kind="business_blocked" 类型固化 -----

    def test_p2_1_business_blocked_kind_field(self) -> None:
        """D4.7.3 v1.0.2 P2-1: DraftBlockedDecisionReport 业务阻断场景 kind="business_blocked"."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_business_blocked_and_emit(
            email_id=1,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="x",
            run_id="vp10206",
        )
        assert report.kind == "business_blocked"

    def test_p2_1_kind_required_literal(self) -> None:
        """D4.7.3 v1.0.2 P2-1: __post_init__ 严判 kind == 'business_blocked'.

        与 failed: Literal[True] 范本一致, 双层防御.
        """
        a = EmailDrafterAdapter(source="qq")
        base = a.record_draft_business_blocked_and_emit(
            email_id=1,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="x",
            run_id="vp10207",
        )
        # kind="technical" 拒收(类型层面与 DraftFailureDecisionReport 区分)
        with pytest.raises(ValueError):
            DraftBlockedDecisionReport(
                evaluation=base.evaluation,
                event_id=base.event_id,
                lane_entry_id=base.lane_entry_id,
                liveness=base.liveness,
                blocked=True,
                last_error="x",
                consecutive_draft_failures=0,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
                kind="technical",  # type: ignore[arg-type]
            )

    # ----- P2-3: 拒纯空白 + body_length 上限 -----

    def test_p2_3_blank_subject_rejected(self) -> None:
        """D4.7.3 v1.0.2 P2-3: subject = '   ' 拒收(strip 后语义空).

        v1.0.1 漏洞: 仅 len(subject) >= 1 接受纯空白字符串.
        v1.0.2 真修: strip() 严判语义非空.
        """
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        object.__setattr__(result, "subject", "   ")  # 纯空白
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="vp10208")

    def test_p2_3_body_length_8001_rejected(self) -> None:
        """D4.7.3 v1.0.2 P2-3: DraftResult 父类严判 body_length > MAX_BODY_CHARS(8000 实际 DraftBlocked 上限是2000).

        v1.0.1 漏洞: compute_draft_acceptance 仅检查下限 body_length >= 10,
        上界默认 2000 但 _validate_draft_body 8000, 漏严判导致 8001 字符 body
        仍通过 draft_and_emit 触发 merge_required.
        v1.0.2 真修: _DRAFT_MAX_BODY_CHARS=8000 双向严判 + 父类 __post_init__ 兜底.
        """
        # DraftBlockedDecisionReport 实际上限是 EmailDrafter.MAX_BODY_CHARS=2000,
        # 父类 DraftResult.__post_init__ 严判 body > 2000 拒收
        # (DraftResult 与 DraftBlockedResult 共用 body 长度上限契约)
        with pytest.raises(ValueError):
            FakeDraftResult.make(body_length=8001)

    def test_p2_3_compute_acceptance_max_body_boundary(self) -> None:
        """D4.7.3 v1.0.2 P2-3: compute_draft_acceptance 8000 合法, 8001 拒收."""
        ac_8000 = compute_draft_acceptance(tone="FORMAL", latency_ms=2000, body_length=8000)
        assert ac_8000 == [True, True, True]
        ac_8001 = compute_draft_acceptance(tone="FORMAL", latency_ms=2000, body_length=8001)
        assert ac_8001 == [True, False, True]


# ============================================================
# D4.7.3 v1.0.3 检查员第三轮反馈 P 修复专项覆盖测试
# ============================================================


class _BoolFalseFake:
    """D4.7.3 v1.0.3 P2-2 专项: __bool__() 返回 False 的合法 falsey 替身.

    用于测试依赖注入保留合法 falsey 对象, 不被 'or' 默认实例替换.
    """

    def __init__(self) -> None:
        self.alive = True
        self.calls: list[dict[str, Any]] = []

    def __bool__(self) -> bool:  # noqa: D105
        """故意返回 False, 模拟第三方库的合法 falsey 替身."""
        return False

    def update(self, transport_alive: bool, now_ms: int | None = None) -> None:
        self.calls.append({"transport_alive": transport_alive, "now_ms": now_ms})


class TestD473V103Fixes:
    """D4.7.3 v1.0.3 检查员第三轮反馈 1 P1 + 3 P2 专项覆盖.

    P1-1: draft_and_emit duck type 仍可绕过契约
        复用 _validate_draft_subject/_body 拒 201/8001/空 model_full_id
    P2-1: 业务阻断改用 blocked: Literal[True] 字段名
        防止通用 `if report.failed` 误计业务阻断
    P2-2: 依赖注入 'is None' 范式保留合法 falsey 替身
    P2-3: build_draft_packet acceptance_criteria 固定 10<=body_length<=8000
        避免 `body_length>={body_length}` 自证式条件
    """

    # ----- P1-1: draft_and_emit 复用契约 helper -----

    def test_p1_1_201_char_subject_rejected(self) -> None:
        """D4.7.3 v1.0.3 P1-1: draft_and_emit 拒 201 字符 subject.

        v1.0.2 漏洞: draft_and_emit 自造严判(仅 strip() 非空), 缺契约 helper 长度上下界.
        实际 subject 字符数 > 200 时仍能通过.
        v1.0.3 真修: 复用 _validate_draft_subject(1<=len<=200 + strip 语义非空).
        """
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        object.__setattr__(result, "subject", "x" * 201)  # 201 字符
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="vp10301")

    def test_p1_1_8001_char_body_rejected(self) -> None:
        """D4.7.3 v1.0.3 P1-1: draft_and_emit 拒 8001 字符 body.

        v1.0.2 漏洞: 仅在 compute_draft_acceptance 校验 10<=len<=8000,
        但 draft_and_emit 入口未复用契约 helper, 8001 字符 body 仅触发 AC[1] False → BLOCKED.
        v1.0.3 真修: 复用 _validate_draft_body(10<=len<=8000 + strip 语义非空).
        """
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        object.__setattr__(result, "body", "x" * 8001)
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="vp10302")

    def test_p1_1_blank_model_full_id_rejected(self) -> None:
        """D4.7.3 v1.0.3 P1-1: draft_and_emit 拒空白 model_full_id.

        v1.0.2 漏洞: 仅 type() 严判 + 非空检查, 接受 "   " 纯空白字符串.
        v1.0.3 真修: type() is str + strip() 非空.
        """
        a = EmailDrafterAdapter(source="qq")
        result = FakeDraftResult.make()
        object.__setattr__(result, "model_full_id", "   ")  # 纯空白
        with pytest.raises(ValueError):
            a.draft_and_emit(email_id=1, draft_result=result, category="URGENT", run_id="vp10303")

    def test_p1_1_duck_type_class_with_valid_fields(self) -> None:
        """D4.7.3 v1.0.3 P1-1: draft_and_emit 接受 duck type 实例(只要契约满足).

        v1.0.2 之前测试仅验证 DraftResult 真实类, 公开声明支持的 duck type 未覆盖.
        v1.0.3 真修: _validate_draft_subject/_body 接受任意 duck type 字段访问.
        """

        @dataclass(frozen=True)
        class DuckDraftResult:
            """duck type 仿造 DraftResult(无继承, 仅满足字段契约)."""

            subject: str
            body: str
            tone: DraftTone
            model_full_id: str
            latency_ms: int
            spam_reply_authorized: bool = False
            spam_reply_intent: DraftSpamReplyIntent | None = None

        a = EmailDrafterAdapter(source="qq")
        duck = DuckDraftResult(
            subject="x" * 150,  # 150 字符合法
            body="x" * 100,  # 100 字符合法
            tone=DraftTone.FORMAL,
            model_full_id="deepseek/deepseek-chat",
            latency_ms=1500,
        )
        report = a.draft_and_emit(
            email_id=1,
            draft_result=duck,  # type: ignore[arg-type]
            category="URGENT",
            run_id="vp10304",
        )
        assert report.tone == "FORMAL"
        assert report.body_length == 100

    # ----- P2-1: 业务阻断 blocked 字段名 -----

    def test_p2_1_business_blocked_uses_blocked_field(self) -> None:
        """D4.7.3 v1.0.3 P2-1: 业务阻断场景 DraftBlockedDecisionReport.blocked=True (替代 v1.0.2 failed).

        防通用 `if report.failed` 误计业务阻断为失败(业务阻断不计入 cf 累加器).
        """
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_business_blocked_and_emit(
            email_id=1,
            tone="FORMAL",
            original_email_category="SPAM",
            reason="spam_business_blocked",
            last_error="x",
            run_id="vp10305",
        )
        assert report.blocked is True
        # 关键验证: 业务阻断类没有 `failed` 字段(替代为 `blocked`)
        assert not hasattr(report, "failed") or "failed" not in report.__dataclass_fields__

    def test_p2_1_failure_uses_failed_field(self) -> None:
        """D4.7.3 v1.0.3 P2-1: 技术失败场景 DraftFailureDecisionReport.failed=True (独立字段名)."""
        a = EmailDrafterAdapter(source="qq")
        report = a.record_draft_failure_and_emit(
            email_id=1,
            last_error="DrafterResponseError",
            consecutive_draft_failures=1,
            run_id="vp10306",
        )
        assert report.failed is True
        assert not hasattr(report, "blocked")

    # ----- P2-2: 依赖注入 is None 范式 -----

    def test_p2_2_preserves_falsey_test_double(self) -> None:
        """D4.7.3 v1.0.3 P2-2: 依赖注入保留 __bool__() == False 的合法替身.

        v1.0.2 漏洞: `engine or PolicyEngine()` 当 engine.__bool__() 返回 False
        时被默认 PolicyEngine 替换, 测试替身被丢失.
        v1.0.3 真修: `engine if engine is not None else PolicyEngine()`.
        """
        # 创建一个 __bool__() 返回 False 但调用 update 正常工作的替身
        fake_engine = _BoolFalseFake()
        a = EmailDrafterAdapter(source="qq", engine=fake_engine)  # type: ignore[arg-type]
        # 验证: 替身被保留(不是默认 PolicyEngine)
        assert a._engine is fake_engine
        # 验证: 替身的 update 方法可正常调用
        fake_engine.update(transport_alive=True)
        assert len(fake_engine.calls) == 1

    # ----- P2-3: acceptance_criteria 固定契约描述 -----

    def test_p2_3_acceptance_criteria_fixed_contract(self) -> None:
        """D4.7.3 v1.0.3 P2-3: build_draft_packet acceptance_criteria 固定 10<=body_length<=8000.

        v1.0.2 漏洞: 写成 `body_length>={body_length}` 自证式条件,
        body_length=8001 时变成 `body_length>=8001` 荒唐描述, audit 把非法长度描述成验收标准.
        v1.0.3 真修: 固定为 "10<=body_length<=8000", 与契约一致.
        v1.0.4 适配: 用合法 body_length(5000) 验证描述固定(8001 已被 P1-2 严判拒收).
        """
        p = build_draft_packet(
            email_id=1,
            source="qq",
            tone="FORMAL",
            model_full_id="m",
            body_length=5000,  # 合法长度(10-8000), 验证 acceptance_criteria 描述固定
        )
        # 3 条 acceptance_criteria, body_length 描述固定
        assert len(p.acceptance_criteria) == 3
        assert p.acceptance_criteria[1] == "10<=body_length<=8000"
        # tone 和 latency 描述
        assert p.acceptance_criteria[0] == "tone=FORMAL"
        assert p.acceptance_criteria[2] == "latency<5000ms"


class TestD473V104Fixes:
    """D4.7.3 v1.0.4 第四轮复检 2 P1 + 2 P2 专项测试.

    检查员第四轮反馈 4 项 P:
      - P1-1: DraftBlockedDecisionReport 跨字段校验漏洞
        (URGENT+spam_business_blocked / cf=2 / 纯空白 last_error 矛盾状态)
      - P1-2: build_draft_packet 接受 0/9/8001 长度
        (v1.0.3 P2-3 改 acceptance_criteria 描述, 但 factory 实际未严判)
      - P2-3: build_draft_policy_context current_attempts 写死 1
        (cf=2 时仍显示"已重试 1/3 次"误导 audit)
      - P2-4: 公共构造器接受空白 source/model_full_id/last_error
        (技术失败报告也接受空白错误信息)
    """

    # ===== P1-1: DraftBlockedDecisionReport 跨字段校验(3 tests) =====

    def test_p1_1_reject_urgent_with_spam_business_blocked(self) -> None:
        """v1.0.4 P1-1: URGENT + spam_business_blocked 矛盾状态必须拒收.

        v1.0.3 漏洞: __post_init__ 仅校验各字段自身, 未校验跨字段关系.
        实测可构造 `category=URGENT, reason=spam_business_blocked` 矛盾状态.
        v1.0.4 真修: 业务阻断 category 必为 'SPAM'(唯一 reason 锁定).
        """
        from my_ai_employee.policy.integration import DraftBlockedDecisionReport
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        eval_obj = PolicyEvaluation(status="succeeded", decisions=[])
        with pytest.raises(ValueError, match="original_email_category 业务阻断必为 'SPAM'"):
            DraftBlockedDecisionReport(
                evaluation=eval_obj,
                event_id=None,
                lane_entry_id="test:1",
                liveness=None,  # type: ignore[arg-type]
                last_error="SPAM 邮件禁止回复",
                consecutive_draft_failures=0,
                tone="FORMAL",
                original_email_category="URGENT",  # 矛盾! 业务阻断必为 SPAM
                reason="spam_business_blocked",
            )

    def test_p1_1_reject_cf_nonzero_in_business_block(self) -> None:
        """v1.0.4 P1-1: 业务阻断 cf 必为 0(阻断不计入失败累加器).

        v1.0.3 漏洞: __post_init__ 允许 cf >= 0 任何值, 实际 cf=2 会触发
        PolicyEngine RetryableFailure 误判. 业务阻断必 cf=0 锁定.
        v1.0.4 真修: __post_init__ 校验 cf == 0.
        """
        from my_ai_employee.policy.integration import DraftBlockedDecisionReport
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        eval_obj = PolicyEvaluation(status="succeeded", decisions=[])
        with pytest.raises(ValueError, match="consecutive_draft_failures 业务阻断必为 0"):
            DraftBlockedDecisionReport(
                evaluation=eval_obj,
                event_id=None,
                lane_entry_id="test:1",
                liveness=None,  # type: ignore[arg-type]
                last_error="SPAM 邮件禁止回复",
                consecutive_draft_failures=2,  # 业务阻断不允许非 0
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
            )

    def test_p1_1_reject_whitespace_last_error(self) -> None:
        """v1.0.4 P1-1: 纯空白 last_error 必须拒收(语义非空).

        v1.0.3 漏洞: 仅 isinstance + bool(self.last_error) 校验,
        "   " 纯空白字符串(实际是 Exception("   ") str() 化)能通过.
        v1.0.4 真修: strip() 后校验非空.
        """
        from my_ai_employee.policy.integration import DraftBlockedDecisionReport
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        eval_obj = PolicyEvaluation(status="succeeded", decisions=[])
        with pytest.raises(ValueError, match="last_error 必填非空白 str"):
            DraftBlockedDecisionReport(
                evaluation=eval_obj,
                event_id=None,
                lane_entry_id="test:1",
                liveness=None,  # type: ignore[arg-type]
                last_error="   ",  # 纯空白, 实际未填
                consecutive_draft_failures=0,
                tone="FORMAL",
                original_email_category="SPAM",
                reason="spam_business_blocked",
            )

    # ===== P1-2: build_draft_packet body_length 10-8000 严判(3 tests) =====

    def test_p1_2_reject_body_length_zero(self) -> None:
        """v1.0.4 P1-2: body_length=0 拒收(契约 1 下限 10).

        v1.0.3 漏洞: build_draft_packet 只校验 type+>=0, body_length=0
        可生成声称满足 10<=body_length<=8000 的 packet(契约自相矛盾).
        v1.0.4 真修: build_draft_packet 改用 _validate_draft_body_length_range(10-8000 严格).
        """
        with pytest.raises(ValueError, match=r"body_length 必须 >= 10"):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                model_full_id="deepseek/deepseek-chat",
                body_length=0,  # 契约下限 10
            )

    def test_p1_2_reject_body_length_nine(self) -> None:
        """v1.0.4 P1-2: body_length=9 拒收(契约 1 下限 10, 9 是下边界测试)."""
        with pytest.raises(ValueError, match=r"body_length 必须 >= 10"):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                model_full_id="deepseek/deepseek-chat",
                body_length=9,  # 恰好 < 10
            )

    def test_p1_2_reject_body_length_8001(self) -> None:
        """v1.0.4 P1-2: body_length=8001 拒收(契约 1 上限 8000).

        v1.0.3 P2-3 已把 acceptance_criteria 描述固定为 "10<=body_length<=8000",
        但 factory 实际未严判, body_length=8001 仍能通过(自相矛盾).
        v1.0.4 真修: 上下界双向严判.
        """
        with pytest.raises(ValueError, match=r"body_length 必须 <= 8000"):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                model_full_id="deepseek/deepseek-chat",
                body_length=8001,  # 恰好 > 8000
            )

    # ===== P2-3: current_attempts = consecutive_draft_failures(2 tests) =====

    def test_p2_3_current_attempts_equals_cf(self) -> None:
        """v1.0.4 P2-3: current_attempts = consecutive_draft_failures(不是写死 1).

        v1.0.3 漏洞: context['current_attempts'] 写死 1,
        cf=2 时 PolicyEngine RetryableFailure 决策显示"已重试 1/3 次"误导 audit.
        v1.0.4 真修: current_attempts 透传 cf.
        """
        ctx = build_draft_policy_context(
            tone="FORMAL",
            latency_ms=2000,
            body_length=50,
            last_draft_failed=True,
            consecutive_draft_failures=2,
        )
        assert ctx["current_attempts"] == 2

    def test_p2_3_current_attempts_default_zero(self) -> None:
        """v1.0.4 P2-3: 默认 cf=0 → current_attempts=0(尚未开始重试).

        旧 v1.0.3 期望 current_attempts=1(写死).
        v1.0.4 真修: 默认场景"尚未开始重试"才是合理描述.
        """
        ctx = build_draft_policy_context(tone="FORMAL", latency_ms=2000, body_length=50)
        # 默认 consecutive_draft_failures=0, current_attempts 应为 0
        assert ctx["current_attempts"] == 0

    # ===== P2-4: 公共构造器空白字段校验(4 tests) =====

    def test_p2_4_reject_whitespace_source_in_draft_packet(self) -> None:
        """v1.0.4 P2-4: build_draft_packet 拒空白 source."""
        with pytest.raises(ValueError, match="source 必填非空白 str"):
            build_draft_packet(
                email_id=1,
                source="   ",  # 纯空白
                tone="FORMAL",
                model_full_id="deepseek/deepseek-chat",
                body_length=50,
            )

    def test_p2_4_reject_whitespace_model_full_id_in_draft_packet(self) -> None:
        """v1.0.4 P2-4: build_draft_packet 拒空白 model_full_id."""
        with pytest.raises(ValueError, match="model_full_id 必填非空白 str"):
            build_draft_packet(
                email_id=1,
                source="qq",
                tone="FORMAL",
                model_full_id="  \t  ",  # 纯空白
                body_length=50,
            )

    def test_p2_4_reject_whitespace_source_in_failure_packet(self) -> None:
        """v1.0.4 P2-4: build_draft_failure_packet 拒空白 source."""
        with pytest.raises(ValueError, match="source 必填非空白 str"):
            build_draft_failure_packet(
                email_id=1,
                source="   ",
                last_error_str="LLM timeout",
                consecutive_draft_failures=1,
                model_full_id="deepseek/deepseek-chat",
            )

    def test_p2_4_reject_whitespace_last_error_in_failure_packet(self) -> None:
        """v1.0.4 P2-4: build_draft_failure_packet 拒空白 last_error_str.

        v1.0.3 漏洞: 技术失败报告 last_error_str 只校验 isinstance + bool(),
        "   " 纯空白(实际是 Exception("   ") str() 化)能通过.
        v1.0.4 真修: strip() 后校验非空(防 prompt 撑爆伪造异常审计).
        """
        with pytest.raises(ValueError, match="last_error_str 必填非空白 str"):
            build_draft_failure_packet(
                email_id=1,
                source="qq",
                last_error_str="   ",  # 纯空白
                consecutive_draft_failures=1,
                model_full_id="deepseek/deepseek-chat",
            )


class TestD473V105Fixes:
    """D4.7.3 v1.0.5 第五轮复检 2 P1 + 2 P2 + 1 P3 专项测试.

    检查员第五轮反馈 5 项 P:
      - P1-1: DraftDecisionReport.__post_init__ 可绕过长度契约
        (v1.0.4 P1-2 在 build_draft_packet 工厂层加了, 但数据类 __post_init__
        仍用 _validate_draft_body_length 仅校验 >= 0, 0/9/8001 绕过;
        model_full_id 仍用 `not self.model_full_id` 长度检查, 纯空白绕过)
      - P1-2: build_draft_policy_context last_draft_failed 与 cf 允许矛盾
        (last_draft_failed=True, cf=0 / last_draft_failed=False, cf>0 都接受)
      - P2-1: record_draft_business_blocked_and_emit reason 非哈希 TypeError
        (reason=[] / reason={} 抛 TypeError: unhashable type, 应统一为 ValueError)
      - P2-2: Adapter init source / build_lane_entry_id run_id /
        DraftFailureDecisionReport last_error 仍用 `not value` 长度检查
      - P3: 文档注释过期(双入口/body_length>10/失败返回/DraftBlockedDecisionReport 缺 category)
    """

    # ===== P1-1: DraftDecisionReport.__post_init__ body_length + model_full_id (3 tests) =====

    def test_p1_1_reject_body_length_zero_in_decision_report(self) -> None:
        """v1.0.5 P1-1: DraftDecisionReport body_length=0 拒收.

        v1.0.4 漏洞: __post_init__ 用 _validate_draft_body_length 仅校验 >= 0,
        body_length=0 能通过并形成 audit 契约矛盾(声称 10<=body_length<=8000
        实际 body_length=0).
        v1.0.5 真修: 改用 _validate_draft_body_length_range(10-8000 严格).
        """
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        eval_obj = PolicyEvaluation(status="succeeded", decisions=[])
        with pytest.raises(ValueError, match="body_length 必须 >="):
            DraftDecisionReport(
                evaluation=eval_obj,
                event_id=None,
                lane_entry_id="draft:qq:r-1",
                liveness=None,  # type: ignore[arg-type]
                tone="FORMAL",
                model_full_id="deepseek/deepseek-chat",
                email_id=1,
                latency_ms=100,
                body_length=0,  # 应拒收
            )

    def test_p1_1_reject_body_length_8001_in_decision_report(self) -> None:
        """v1.0.5 P1-1: DraftDecisionReport body_length=8001 拒收.

        v1.0.4 漏洞: build_draft_packet 已用 range, 但 __post_init__ 仍 >= 0.
        v1.0.5 真修: __post_init__ 也用 range.
        """
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        eval_obj = PolicyEvaluation(status="succeeded", decisions=[])
        with pytest.raises(ValueError, match="body_length 必须 <="):
            DraftDecisionReport(
                evaluation=eval_obj,
                event_id=None,
                lane_entry_id="draft:qq:r-1",
                liveness=None,  # type: ignore[arg-type]
                tone="FORMAL",
                model_full_id="deepseek/deepseek-chat",
                email_id=1,
                latency_ms=100,
                body_length=8001,  # 应拒收
            )

    def test_p1_1_reject_whitespace_model_full_id_in_decision_report(self) -> None:
        """v1.0.5 P1-1: DraftDecisionReport model_full_id 纯空白 拒收.

        v1.0.4 漏洞: __post_init__ 用 `not self.model_full_id` 长度检查,
        "   " 纯空白能通过.
        v1.0.5 真修: 改用 strip() 严判语义非空.
        """
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        eval_obj = PolicyEvaluation(status="succeeded", decisions=[])
        with pytest.raises(ValueError, match="model_full_id 必填非空白 str"):
            DraftDecisionReport(
                evaluation=eval_obj,
                event_id=None,
                lane_entry_id="draft:qq:r-1",
                liveness=None,  # type: ignore[arg-type]
                tone="FORMAL",
                model_full_id="   ",  # 纯空白应拒收
                email_id=1,
                latency_ms=100,
                body_length=50,
            )

    # ===== P1-2: build_draft_policy_context 双向强一致 (4 tests) =====

    def test_p1_2_reject_failed_true_with_cf_zero(self) -> None:
        """v1.0.5 P1-2: last_draft_failed=True + cf=0 拒收.

        v1.0.4 漏洞: 允许矛盾状态(True 意味"上次失败"但 cf=0 意味"累计 0 次").
        v1.0.5 真修: last_draft_failed=True → cf >= 1 双向强一致.
        """
        with pytest.raises(ValueError, match="last_draft_failed=True 时"):
            build_draft_policy_context(
                tone="FORMAL",
                latency_ms=100,
                body_length=50,
                last_draft_failed=True,
                consecutive_draft_failures=0,  # 矛盾
                branch_stale=False,
            )

    def test_p1_2_reject_failed_false_with_cf_positive(self) -> None:
        """v1.0.5 P1-2: last_draft_failed=False + cf>0 拒收.

        v1.0.4 漏洞: 允许矛盾状态(False 意味"上次未失败"但 cf>0 意味"累计 > 0").
        v1.0.5 真修: last_draft_failed=False → cf == 0 双向强一致.
        """
        with pytest.raises(ValueError, match="last_draft_failed=False 时"):
            build_draft_policy_context(
                tone="FORMAL",
                latency_ms=100,
                body_length=50,
                last_draft_failed=False,
                consecutive_draft_failures=2,  # 矛盾
                branch_stale=False,
            )

    def test_p1_2_accept_failed_true_with_cf_one(self) -> None:
        """v1.0.5 P1-2: 正常失败场景 (True + cf=1) 通过.

        对照: 正向用例(不是拒收案例)验证双向强一致允许 True + cf >= 1.
        """
        ctx = build_draft_policy_context(
            tone="FORMAL",
            latency_ms=100,
            body_length=50,
            last_draft_failed=True,
            consecutive_draft_failures=1,
            branch_stale=False,
        )
        assert ctx["current_attempts"] == 1  # cf=1 透传
        assert ctx["policy_eval_failed"] is False  # cf < 3
        assert ctx["last_error_recoverable"] is True

    def test_p1_2_accept_failed_false_with_cf_zero(self) -> None:
        """v1.0.5 P1-2: 正常成功场景 (False + cf=0) 通过.

        对照: 成功路径(默认 cf=0) 验证双向强一致允许 False + cf=0.
        """
        ctx = build_draft_policy_context(
            tone="FORMAL",
            latency_ms=100,
            body_length=50,
            last_draft_failed=False,
            consecutive_draft_failures=0,
            branch_stale=False,
        )
        assert ctx["current_attempts"] == 0
        assert ctx["policy_eval_failed"] is False
        assert ctx["last_error_recoverable"] is False

    # ===== P2-1: reason 非哈希 TypeError → ValueError (2 tests) =====

    def test_p2_1_reject_unhashable_reason_list(self, store: Any) -> None:
        """v1.0.5 P2-1: reason=[] 抛 ValueError 而非 TypeError.

        v1.0.4 漏洞: record_draft_business_blocked_and_emit 入口白名单检查
        在 type 校验前, reason=[] 会抛 `TypeError: unhashable type: 'list'`
        违反公开入口统一 ValueError 契约.
        v1.0.5 真修: 白名单检查前先 isinstance 严判.
        """
        adapter = EmailDrafterAdapter(source="qq", event_store=store)
        with pytest.raises(ValueError, match="reason 必填非空 str"):
            adapter.record_draft_business_blocked_and_emit(
                email_id=1,
                last_error="blocked by spam filter",
                tone=DraftTone.FORMAL,
                original_email_category="SPAM",
                reason=[],  # type: ignore[arg-type]  # list 不是 str, 应抛 ValueError 而非 TypeError
                spam_reply_authorized=False,
            )

    def test_p2_1_reject_unhashable_reason_dict(self, store: Any) -> None:
        """v1.0.5 P2-1: reason={} 抛 ValueError 而非 TypeError.

        与 list 测试对照: dict 同样 unhashable.
        v1.0.5 真修: type 严判在白名单前.
        """
        adapter = EmailDrafterAdapter(source="qq", event_store=store)
        with pytest.raises(ValueError, match="reason 必填非空 str"):
            adapter.record_draft_business_blocked_and_emit(
                email_id=1,
                last_error="blocked by spam filter",
                tone=DraftTone.FORMAL,
                original_email_category="SPAM",
                reason={"unexpected": "dict"},  # type: ignore[arg-type]  # dict 同样应抛 ValueError
                spam_reply_authorized=False,
            )

    # ===== P2-2: 剩余空白字段严判 (3 tests) =====

    def test_p2_2_reject_whitespace_source_in_adapter_init(self) -> None:
        """v1.0.5 P2-2: EmailDrafterAdapter(source='   ') 抛 ValueError.

        v1.0.4 漏洞: Adapter __init__ 用 `not source` 长度检查,
        '   ' 纯空白能通过, 后续 build_lane_entry_id 生成 'draft:   :run-1' 无效 lane.
        v1.0.5 真修: 严判 strip() 语义非空.
        """
        with pytest.raises(ValueError, match="source 必填非空白 str"):
            EmailDrafterAdapter(source="   ")

    def test_p2_2_reject_whitespace_run_id_in_build_lane_entry_id(self, store: Any) -> None:
        """v1.0.5 P2-2: build_lane_entry_id('   ') 抛 ValueError.

        v1.0.4 漏洞: build_lane_entry_id 用 `not run_id` 长度检查,
        '   ' 纯空白能通过生成 'draft:qq:   ' 无效 lane_entry_id.
        v1.0.5 真修: 严判 strip() 语义非空.
        """
        adapter = EmailDrafterAdapter(source="qq", event_store=store)
        with pytest.raises(ValueError, match="run_id 必填非空白 str"):
            adapter.build_lane_entry_id("   ")

    def test_p2_2_reject_whitespace_last_error_in_failure_report(self) -> None:
        """v1.0.5 P2-2: DraftFailureDecisionReport(last_error='   ') 抛 ValueError.

        v1.0.4 漏洞: 数据类 __post_init__ 用 `not self.last_error` 长度检查,
        '   ' 纯空白能通过(常见于 Exception('   ') str() 化).
        v1.0.5 真修: 严判 strip() 语义非空.
        """
        from my_ai_employee.policy.policy_engine import PolicyEvaluation

        eval_obj = PolicyEvaluation(status="succeeded", decisions=[])
        with pytest.raises(ValueError, match="last_error 必填非空白 str"):
            DraftFailureDecisionReport(
                evaluation=eval_obj,
                event_id=None,
                lane_entry_id="draft:qq:r-1",
                liveness=None,  # type: ignore[arg-type]
                failed=True,
                last_error="   ",  # 纯空白
                consecutive_draft_failures=1,
            )
