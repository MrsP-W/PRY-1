"""D4.5 — 业务层接入测试 (SyncPolicyAdapter + 3 factory 函数).

设计:
  - 不依赖 IMAPConnector / SQLCipher (policy 层测业务层接入点)
  - 复用 conftest.py 的 in-memory SQLite + EventStore fixture
  - 用伪造 SyncResult (frozen dataclass) 模拟 D3.3 同步结果
  - 验证: 6 决策触发条件 + EventStore 落 1 条 PolicyDecisionEvent + LaneBoard add/update + Heartbeat 探活

D4.5 P0 测试点:
  1. factory 函数 (3 个): 类型 / 字段数 / 严判类型 (D4.4 P1 教训)
  2. SyncPolicyAdapter 初始化: 4 依赖可注入 / 拒空 source
  3. record_to_lane: add (ACTIVE) → update (FINISHED) / 拒 FINISHED 状态直接 add
  4. tick_heartbeat: transport_alive 严判 bool / Liveness 3 状态
  5. evaluate_and_emit: 6 决策触发 / EventStore 落地 / lane / heartbeat 一气呵成
"""

from __future__ import annotations

from typing import Any

import pytest

# ===== 测试用 SyncResult 仿造（D3.3 frozen dataclass）=====
# ⚠️ 必须用真实 SyncResult, 避免伪造类型破坏集成测试
from my_ai_employee.core.sync import SyncResult
from my_ai_employee.events.models import EventType
from my_ai_employee.policy.exceptions import PolicyLaneError
from my_ai_employee.policy.heartbeat import Liveness
from my_ai_employee.policy.integration import (
    SyncPolicyAdapter,
    build_imap_sync_packet,
    build_sync_policy_context,
    compute_acceptance_results,
)
from my_ai_employee.policy.lane_board import LaneStatus
from my_ai_employee.policy.policy_engine import (
    PolicyDecisionKind,
    PolicyEngine,
)
from my_ai_employee.policy.task_packet import (
    PermissionProfile,
    RecoveryPolicy,
)


def _make_sync_result(
    *,
    total_fetched: int = 100,
    inserted: int = 95,
    skipped: int = 0,
    failed: int = 0,
    new_last_uid: int = 100,
    duration_seconds: float = 1.5,
) -> SyncResult:
    """造一个 SyncResult 供 adapter 用。"""
    return SyncResult(
        total_fetched=total_fetched,
        inserted=inserted,
        skipped=skipped,
        failed=failed,
        new_last_uid=new_last_uid,
        duration_seconds=duration_seconds,
    )


# ===== 1. factory 函数测试 =====


class TestFactoryFunctions:
    """factory 函数: build_imap_sync_packet / build_sync_policy_context / compute_acceptance_results"""

    def test_build_imap_sync_packet_8_fields(self) -> None:
        """TaskPacket 8 必含字段全填 + 合法枚举值。"""
        p = build_imap_sync_packet(
            source="qq",
            inserted=10,
            failed=0,
            duration_seconds=1.0,
        )
        assert isinstance(p.objective, str) and p.objective
        assert isinstance(p.scope, list) and len(p.scope) >= 1
        assert isinstance(p.resources, list) and len(p.resources) >= 1
        assert isinstance(p.acceptance_criteria, list) and len(p.acceptance_criteria) >= 1
        assert isinstance(p.model, str) and p.model
        assert isinstance(p.provider, str) and p.provider
        assert p.permission_profile == PermissionProfile.READ_ONLY.value
        assert p.recovery_policy == RecoveryPolicy.RETRY_ON_TRANSIENT.value

    def test_build_imap_sync_packet_objective_format(self) -> None:
        """objective 必须含 source 名（便于 subject_id 截断 + 事件溯源）。"""
        p = build_imap_sync_packet(source="qq", inserted=1, failed=0, duration_seconds=0.1)
        assert "qq" in p.objective
        assert p.objective == "imap_sync:qq"

    def test_compute_acceptance_results_all_pass(self) -> None:
        """全 pass: inserted>0 + failed=0 + duration<30s → 3 True。"""
        results = compute_acceptance_results(inserted=10, failed=0, duration_seconds=1.0)
        assert results == [True, True, True]
        # D4.4 P1 严判: 元素必须是 bool
        for r in results:
            assert type(r) is bool

    def test_compute_acceptance_results_partial_fail(self) -> None:
        """部分 fail: failed>0 → [True, False, True]。"""
        results = compute_acceptance_results(inserted=10, failed=5, duration_seconds=1.0)
        assert results == [True, False, True]

    def test_compute_acceptance_results_no_progress(self) -> None:
        """无进度: inserted=0 → [False, True, True]（拉空也算成功 sync）。"""
        results = compute_acceptance_results(inserted=0, failed=0, duration_seconds=1.0)
        assert results == [False, True, True]

    def test_compute_acceptance_results_too_slow(self) -> None:
        """超时: duration>=30s → [True, True, False]。"""
        results = compute_acceptance_results(inserted=10, failed=0, duration_seconds=35.0)
        assert results == [True, True, False]

    def test_build_sync_policy_context_12_fields_strict(self) -> None:
        """context 12 字段严判 native bool/int/str/list[bool]（D4.4 P1 教训）。"""
        result = _make_sync_result()
        ctx = build_sync_policy_context(result=result, consecutive_failures=0)
        assert len(ctx) == 12
        # bool 字段: type() is bool
        for k in (
            "last_error_recoverable",
            "branch_stale",
            "action_sensitive",
            "has_approval_token",
            "policy_eval_failed",
        ):
            assert type(ctx[k]) is bool, f"{k} 必须是原生 bool, 实际 {type(ctx[k]).__name__}"
        # int 字段: type() is int
        for k in (
            "current_attempts",
            "max_attempts",
            "last_heartbeat_ms",
            "stale_threshold_ms",
            "now_ms",
        ):
            assert type(ctx[k]) is int, f"{k} 必须是原生 int, 实际 {type(ctx[k]).__name__}"
        # str 字段
        assert type(ctx["approval_token_id"]) is str
        # list 字段
        assert type(ctx["acceptance_results"]) is list
        for x in ctx["acceptance_results"]:
            assert type(x) is bool

    def test_build_sync_policy_context_recoverable_logic(self) -> None:
        """recoverable 逻辑: failed>0 AND consecutive_failures<3 → True。"""
        # failed>0 + consecutive_failures<3 → 可恢复
        ctx = build_sync_policy_context(result=_make_sync_result(failed=5), consecutive_failures=2)
        assert ctx["last_error_recoverable"] is True

        # failed>0 + consecutive_failures>=3 → 不可恢复
        ctx = build_sync_policy_context(result=_make_sync_result(failed=5), consecutive_failures=3)
        assert ctx["last_error_recoverable"] is False

        # failed=0 → 不可恢复（无所谓"恢复"，无错可恢复）
        ctx = build_sync_policy_context(result=_make_sync_result(failed=0), consecutive_failures=2)
        assert ctx["last_error_recoverable"] is False

    def test_build_sync_policy_context_escalate_logic(self) -> None:
        """escalate 逻辑: failed > consecutive_failures > 0 → True（已超阈值,升级）。"""
        # failed=10, consecutive_failures=5 → escalate
        ctx = build_sync_policy_context(result=_make_sync_result(failed=10), consecutive_failures=5)
        assert ctx["policy_eval_failed"] is True

        # failed=5, consecutive_failures=10 → 不 escalate（失败次数 < 累计次数,矛盾但不发升级）
        ctx = build_sync_policy_context(result=_make_sync_result(failed=5), consecutive_failures=10)
        assert ctx["policy_eval_failed"] is False

        # failed=0 → 不 escalate
        ctx = build_sync_policy_context(result=_make_sync_result(failed=0), consecutive_failures=5)
        assert ctx["policy_eval_failed"] is False


# ===== 2. SyncPolicyAdapter 初始化 =====


class TestSyncPolicyAdapterInit:
    """初始化: 4 依赖可注入 + 拒空 source。"""

    def test_init_default_dependencies(self) -> None:
        """不传依赖 → 用默认 (PolicyEngine / Heartbeat / LaneBoard)。"""
        a = SyncPolicyAdapter(source="qq")
        assert a._engine is not None
        assert a._heartbeat is not None
        assert a._board is not None
        assert a._event_store is None

    def test_init_custom_dependencies(self, store: Any) -> None:
        """传 event_store / engine → 全部生效。"""
        eng = PolicyEngine()
        a = SyncPolicyAdapter(source="qq", event_store=store, engine=eng)
        assert a._event_store is store
        assert a._engine is eng

    def test_init_rejects_empty_source(self) -> None:
        """空 source 抛 ValueError（编程错误, 透传）。"""
        with pytest.raises(ValueError, match="source 必填非空"):
            SyncPolicyAdapter(source="")

    def test_init_rejects_non_str_source(self) -> None:
        """非 str source 抛 ValueError。"""
        with pytest.raises(ValueError, match="source 必填非空"):
            SyncPolicyAdapter(source=123)  # type: ignore[arg-type]


# ===== 3. record_to_lane 测试 =====


class TestRecordToLane:
    """LaneBoard 接入: add (ACTIVE/BLOCKED) → update (FINISHED)。"""

    def test_add_then_finish(self) -> None:
        """新 entry ACTIVE → update FINISHED 路径。"""
        a = SyncPolicyAdapter(source="qq")
        e1 = a.record_to_lane(run_id="r1", status=LaneStatus.ACTIVE)
        assert e1.status == LaneStatus.ACTIVE
        e2 = a.record_to_lane(run_id="r1", status=LaneStatus.FINISHED)
        assert e2.status == LaneStatus.FINISHED

    def test_finished_via_factory(self) -> None:
        """直接传 FINISHED → 内部先 add ACTIVE 再 update FINISHED（D4.4 lane.add 拒 FINISHED 直 add）。"""
        a = SyncPolicyAdapter(source="qq")
        e = a.record_to_lane(run_id="r2", status=LaneStatus.FINISHED)
        assert e.status == LaneStatus.FINISHED
        # 验证 entry_id 命名: "sync:qq:r2"
        assert e.entry_id == "sync:qq:r2"

    def test_update_existing(self) -> None:
        """已存在 entry → update 而非 add（避免重复）。"""
        a = SyncPolicyAdapter(source="qq")
        a.record_to_lane(run_id="r3", status=LaneStatus.ACTIVE)
        # 再调用同 run_id → update (BLOCKED)
        e = a.record_to_lane(run_id="r3", status=LaneStatus.BLOCKED)
        assert e.status == LaneStatus.BLOCKED

    def test_blocked_lane_raises_on_finished_revert(self) -> None:
        """FINISHED 是终态 (D4.4 状态矩阵), 不能再 update 到 ACTIVE/BLOCKED。"""
        a = SyncPolicyAdapter(source="qq")
        a.record_to_lane(run_id="r4", status=LaneStatus.FINISHED)
        with pytest.raises(PolicyLaneError, match="非法状态转换"):
            a.record_to_lane(run_id="r4", status=LaneStatus.ACTIVE)

    def test_lane_entry_id_format(self) -> None:
        """entry_id 必须 'sync:<source>:<run_id>'。"""
        a = SyncPolicyAdapter(source="outlook")
        assert a.build_lane_entry_id("xyz") == "sync:outlook:xyz"

    def test_lane_entry_id_rejects_empty_run_id(self) -> None:
        """run_id 必填非空。"""
        a = SyncPolicyAdapter(source="qq")
        with pytest.raises(ValueError, match="run_id 必填非空"):
            a.build_lane_entry_id("")


# ===== 4. tick_heartbeat 测试 =====


class TestTickHeartbeat:
    """Heartbeat 接入: transport_alive 严判 + Liveness 3 状态。"""

    def test_tick_healthy(self) -> None:
        """transport_alive=True + 立即 evaluate → HEALTHY。"""
        a = SyncPolicyAdapter(source="qq")
        now = 10_000
        liveness = a.tick_heartbeat(transport_alive=True, now_ms=now)
        assert liveness == Liveness.HEALTHY

    def test_tick_transport_dead(self) -> None:
        """transport_alive=False → 立即 TRANSPORT_DEAD（优先级最高）。"""
        a = SyncPolicyAdapter(source="qq")
        liveness = a.tick_heartbeat(transport_alive=False, now_ms=10_000)
        assert liveness == Liveness.TRANSPORT_DEAD

    def test_tick_stalled(self) -> None:
        """update 后 idle > threshold → STALLED（直接用 Heartbeat.evaluate 测, 不用 adapter）."""
        from my_ai_employee.policy.heartbeat import Heartbeat

        hb = Heartbeat(last_seen_ms=10_000, transport_alive=True, idle_threshold_ms=30_000)
        assert hb.evaluate(now_ms=70_000) == Liveness.STALLED

    def test_tick_rejects_non_bool_transport(self) -> None:
        """transport_alive 严判 bool（D4.4 编程错误透传）。"""
        a = SyncPolicyAdapter(source="qq")
        with pytest.raises(ValueError, match="transport_alive 必须是 bool"):
            a.tick_heartbeat(transport_alive="true")  # type: ignore[arg-type]


# ===== 5. evaluate_and_emit 主入口测试 =====


class TestEvaluateAndEmit:
    """主入口: 6 决策触发 + EventStore 落地 + lane + heartbeat。"""

    def test_emit_event_with_store(self, store: Any) -> None:
        """传 store → 落 1 条 PolicyDecisionEvent 到 events 表。"""
        a = SyncPolicyAdapter(source="qq", event_store=store)
        result = _make_sync_result(inserted=10, failed=0, duration_seconds=1.0)
        report = a.evaluate_and_emit(result, consecutive_failures=0)
        # 1) 事件落地
        assert report.event_id is not None and report.event_id > 0
        assert store.count() == 1
        ev = store.get_by_id(report.event_id)
        assert ev is not None
        assert ev.event == EventType.POLICY_DECISION_MADE.value
        # 2) 决策正确: 全部 AC pass → MergeRequired 触发
        assert report.evaluation.has_decision(PolicyDecisionKind.MERGE_REQUIRED)
        # 3) lane FINISHED
        assert "sync:qq" in report.lane_entry_id
        # 4) heartbeat HEALTHY
        assert report.liveness == Liveness.HEALTHY

    def test_no_emit_without_store(self) -> None:
        """不传 store → 不落地事件, event_id=None。"""
        a = SyncPolicyAdapter(source="qq")
        result = _make_sync_result(inserted=10, failed=0, duration_seconds=1.0)
        report = a.evaluate_and_emit(result, consecutive_failures=0)
        assert report.event_id is None
        # 决策仍然评估 (纯评估模式)
        assert report.evaluation.has_decision(PolicyDecisionKind.MERGE_REQUIRED)

    def test_failed_sync_blocks_lane(self, store: Any) -> None:
        """failed>0 + 全部 AC fail → lane BLOCKED（不 FINISHED）。"""
        a = SyncPolicyAdapter(source="qq", event_store=store)
        result = _make_sync_result(inserted=0, failed=10, duration_seconds=1.0)
        report = a.evaluate_and_emit(result, consecutive_failures=1)
        # lane BLOCKED
        board_entry = a._board.get(report.lane_entry_id)
        assert board_entry.status == LaneStatus.BLOCKED
        # 不触发 MERGE_REQUIRED
        assert not report.evaluation.has_decision(PolicyDecisionKind.MERGE_REQUIRED)
        # 触发 RetryAvailable (recoverable=True)
        assert report.evaluation.has_decision(PolicyDecisionKind.RETRY_AVAILABLE)

    def test_escalate_when_consecutive_failures_high(self, store: Any) -> None:
        """failed > consecutive_failures 阈值 → EscalateRequired 触发。"""
        a = SyncPolicyAdapter(source="qq", event_store=store)
        result = _make_sync_result(inserted=0, failed=10, duration_seconds=1.0)
        # consecutive_failures=2 < failed=10 → policy_eval_failed=True
        report = a.evaluate_and_emit(result, consecutive_failures=2)
        assert report.evaluation.has_decision(PolicyDecisionKind.ESCALATE_REQUIRED)

    def test_run_id_unique_per_call(self, store: Any) -> None:
        """不传 run_id → 用 now_ms str 当默认, 多次调用 lane_entry_id 不同。"""
        import time as _time

        a = SyncPolicyAdapter(source="qq", event_store=store)
        result = _make_sync_result()
        r1 = a.evaluate_and_emit(result, consecutive_failures=0)
        _time.sleep(0.01)  # 10ms 间隔确保 ms timestamp 不同
        r2 = a.evaluate_and_emit(result, consecutive_failures=0)
        # run_id 不同 → entry_id 不同
        assert r1.lane_entry_id != r2.lane_entry_id

    def test_custom_run_id(self, store: Any) -> None:
        """传 run_id → lane_entry_id 用 caller 提供的 ID。"""
        a = SyncPolicyAdapter(source="qq", event_store=store)
        result = _make_sync_result()
        report = a.evaluate_and_emit(result, consecutive_failures=0, run_id="custom-rid-001")
        assert report.lane_entry_id == "sync:qq:custom-rid-001"

    def test_rejects_negative_consecutive_failures(self) -> None:
        """consecutive_failures 必填 int>=0（编程错误透传）。"""
        a = SyncPolicyAdapter(source="qq")
        result = _make_sync_result()
        with pytest.raises(ValueError, match="consecutive_failures 必须是 int >= 0"):
            a.evaluate_and_emit(result, consecutive_failures=-1)

    def test_full_event_payload(self, store: Any) -> None:
        """验证 event 落地的 7 业务字段（rule_name / kind / all_decisions / context_snapshot）。"""
        a = SyncPolicyAdapter(source="qq", event_store=store)
        result = _make_sync_result(inserted=10, failed=0, duration_seconds=1.0)
        report = a.evaluate_and_emit(result, consecutive_failures=0)
        assert report.event_id is not None
        ev = store.get_by_id(report.event_id)
        assert ev is not None
        # 业务 payload 7 字段直接合并到 event_metadata 顶层（D4.3.2 决策: build_event_metadata meta.update(extra)）
        # 6 必含 metadata 字段也在这里(seq/session_id/ownership/provenance/timestamp_ms/fingerprint)
        assert ev.event_metadata is not None
        for k in (
            "rule_name",
            "priority",
            "kind",
            "explanation",
            "approval_token_id",
            "all_decisions",
            "context_snapshot",
        ):
            assert k in ev.event_metadata, f"event_metadata 缺业务字段: {k}"
        # context_snapshot 必含 acceptance_results
        ctx = ev.event_metadata["context_snapshot"]
        assert "acceptance_results" in ctx
        # all_decisions 至少 1 个 (MERGE_REQUIRED)
        assert len(ev.event_metadata["all_decisions"]) >= 1
