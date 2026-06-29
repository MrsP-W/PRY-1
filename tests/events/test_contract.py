"""D4.3 — events contract 测试 (g004 4 大不变量 + 6 必含字段 + fingerprint + 异常窄化).

覆盖:
  - build_event_metadata: 6 必含字段全生成
  - assert_event_invariants: 缺字段/类型错 → EventMetadataError
  - assert_event_invariants: 非法 event/status 枚举 → EventContractError
  - assert_event_invariants: 编程错误 ValueError 透传
  - compute_fingerprint: 排除运行时字段(timestamp_ms/seq), 跨时间稳定
  - compute_fingerprint: 同身份 → 同 fingerprint
  - compute_fingerprint: 不同身份 → 不同 fingerprint
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.events import (  # noqa: E402
    REQUIRED_METADATA_KEYS,
    EventContractError,
    EventMetadataError,
    EventOwnership,
    EventProvenance,
    EventStatus,
    EventType,
    assert_event_invariants,
    build_event_metadata,
    compute_fingerprint,
)

# ===== build_event_metadata =====


class TestBuildEventMetadata:
    def test_build_event_metadata_has_6_required_keys(self) -> None:
        """build_event_metadata 必返回 6 必含字段."""
        meta = build_event_metadata(seq=1, session_id="s1")
        for key in REQUIRED_METADATA_KEYS:
            assert key in meta

    def test_build_event_metadata_6_required_keys_count(self) -> None:
        """REQUIRED_METADATA_KEYS 正好 6 字段(seq/timestamp_ms/session_id/ownership/provenance/fingerprint)."""
        assert len(REQUIRED_METADATA_KEYS) == 6
        assert set(REQUIRED_METADATA_KEYS) == {
            "seq",
            "timestamp_ms",
            "session_id",
            "ownership",
            "provenance",
            "fingerprint",
        }

    def test_build_event_metadata_default_values(self) -> None:
        """build_event_metadata 默认值: timestamp_ms 自动取当前时间, fingerprint 占位空串."""
        meta = build_event_metadata(seq=5, session_id="sess-x")
        assert meta["seq"] == 5
        assert meta["session_id"] == "sess-x"
        assert meta["ownership"] == EventOwnership.OBSERVE.value
        assert meta["provenance"] == EventProvenance.LIVE.value
        assert meta["fingerprint"] == ""
        assert isinstance(meta["timestamp_ms"], int)
        assert meta["timestamp_ms"] > 0

    def test_build_event_metadata_explicit_timestamp(self) -> None:
        """timestamp_ms 显式注入(测试用)."""
        meta = build_event_metadata(seq=1, session_id="s", timestamp_ms=1_780_000_000_000)
        assert meta["timestamp_ms"] == 1_780_000_000_000

    def test_build_event_metadata_extra_payload(self) -> None:
        """extra 业务字段会合并到 metadata(非保留字段)."""
        meta = build_event_metadata(
            seq=1,
            session_id="s",
            extra={"tokens": 100, "model": "M3", "latency_ms": 1234},
        )
        assert meta["tokens"] == 100
        assert meta["model"] == "M3"
        assert meta["latency_ms"] == 1234

    def test_build_event_metadata_seq_negative_raises(self) -> None:
        """seq < 0 抛 ValueError(编程错误透传, 不包装)."""
        with pytest.raises(ValueError, match="seq 必须 >= 0"):
            build_event_metadata(seq=-1, session_id="s")

    # ===== D4.3.2 复检 P1 修复: extra 覆盖保护 =====
    @pytest.mark.parametrize(
        "forbidden_key",
        ["seq", "timestamp_ms", "session_id", "ownership", "provenance", "fingerprint"],
    )
    def test_build_event_metadata_extra_with_required_key_raises(self, forbidden_key: str) -> None:
        """D4.3.2 复检 P1 回归: extra 含 6 必含字段之一 → 抛 ValueError(防覆盖)."""
        with pytest.raises(ValueError, match="extra 包含契约保留字段"):
            build_event_metadata(
                seq=1,
                session_id="s",
                extra={forbidden_key: "anything"},
            )

    def test_build_event_metadata_extra_rejects_seq_negative_override(self) -> None:
        """D4.3.2 复检 P1 回归: 即便 extra={seq: -1} 也必须拒绝(防绕过 seq>=0 校验)."""
        with pytest.raises(ValueError, match="extra 包含契约保留字段"):
            build_event_metadata(
                seq=1,
                session_id="s",
                extra={"seq": -1, "timestamp_ms": -5},
            )

    def test_build_event_metadata_extra_mixed_safe_and_forbidden_raises(self) -> None:
        """D4.3.2 复检 P1 回归: extra 含业务字段 + 保留字段 → 仍拒绝(任一保留字段都拒)."""
        with pytest.raises(ValueError, match="extra 包含契约保留字段"):
            build_event_metadata(
                seq=1,
                session_id="s",
                extra={"tokens": 100, "fingerprint": "evil-override"},
            )


# ===== assert_event_invariants =====


class TestAssertEventInvariants:
    def test_valid_metadata_passes(self) -> None:
        """合法 metadata 不抛."""
        meta = build_event_metadata(seq=1, session_id="s")
        # 不抛
        assert_event_invariants(EventType.LLM_CALL_STARTED, EventStatus.STARTED, meta)

    def test_missing_required_key_raises_metadata_error(self) -> None:
        """metadata 缺 seq 字段 → EventMetadataError."""
        meta = build_event_metadata(seq=1, session_id="s")
        del meta["seq"]
        with pytest.raises(EventMetadataError, match="缺必含字段"):
            assert_event_invariants(EventType.LLM_CALL_STARTED, EventStatus.STARTED, meta)

    def test_missing_multiple_required_keys_lists_them(self) -> None:
        """metadata 缺多个字段 → 错误信息含全部缺失项."""
        meta = build_event_metadata(seq=1, session_id="s")
        del meta["seq"]
        del meta["timestamp_ms"]
        with pytest.raises(EventMetadataError) as exc_info:
            assert_event_invariants(EventType.LLM_CALL_STARTED, EventStatus.STARTED, meta)
        msg = str(exc_info.value)
        assert "seq" in msg
        assert "timestamp_ms" in msg

    def test_seq_wrong_type_raises_metadata_error(self) -> None:
        """seq 必须是 int, 实际 str → EventMetadataError."""
        meta = build_event_metadata(seq=1, session_id="s")
        meta["seq"] = "1"
        with pytest.raises(EventMetadataError, match="seq 必须是 int"):
            assert_event_invariants(EventType.LLM_CALL_STARTED, EventStatus.STARTED, meta)

    def test_invalid_event_enum_raises_contract_error(self) -> None:
        """event 非法枚举值 → EventContractError."""
        meta = build_event_metadata(seq=1, session_id="s")
        with pytest.raises(EventContractError, match="event 非法"):
            assert_event_invariants("invalid.event", EventStatus.STARTED, meta)

    def test_invalid_status_enum_raises_contract_error(self) -> None:
        """status 非法枚举值 → EventContractError."""
        meta = build_event_metadata(seq=1, session_id="s")
        with pytest.raises(EventContractError, match="status 非法"):
            assert_event_invariants(EventType.LLM_CALL_STARTED, "unknown", meta)

    def test_invalid_ownership_in_metadata_raises_metadata_error(self) -> None:
        """metadata.ownership 不在 EventOwnership 枚举 → EventMetadataError."""
        meta = build_event_metadata(seq=1, session_id="s")
        meta["ownership"] = "bogus"
        with pytest.raises(EventMetadataError, match="ownership 非法"):
            assert_event_invariants(EventType.LLM_CALL_STARTED, EventStatus.STARTED, meta)

    def test_metadata_not_dict_raises_metadata_error(self) -> None:
        """metadata 不是 dict → EventMetadataError."""
        with pytest.raises(EventMetadataError, match="metadata 必须是 dict"):
            assert_event_invariants(EventType.LLM_CALL_STARTED, EventStatus.STARTED, "not a dict")

    def test_negative_evidence_first_class(self) -> None:
        """负向证据 first-class: status=failed/skipped/blocked 独立合法."""
        meta = build_event_metadata(seq=1, session_id="s")
        for neg_status in (
            EventStatus.FAILED,
            EventStatus.SKIPPED,
            EventStatus.BLOCKED,
            EventStatus.CANCELLED,
            EventStatus.DEGRADED,
        ):
            # 不抛
            assert_event_invariants(EventType.LLM_CALL_FAILED, neg_status, meta)


# ===== compute_fingerprint =====


class TestComputeFingerprint:
    def test_fingerprint_stable_across_time(self) -> None:
        """同身份 + 不同 timestamp_ms → 同一 fingerprint(排除运行时字段)."""
        meta1 = build_event_metadata(seq=1, session_id="s1", timestamp_ms=1_780_000_000_000)
        meta2 = build_event_metadata(seq=99, session_id="s1", timestamp_ms=1_790_000_000_000)
        fp1 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta1
        )
        fp2 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta2
        )
        assert fp1 == fp2
        # seq 不同也不算(排除运行时)
        assert len(fp1) == 64  # SHA-256 十六进制长度

    def test_different_status_different_fingerprint(self) -> None:
        """不同 status → 不同 fingerprint."""
        meta = build_event_metadata(seq=1, session_id="s")
        fp1 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta
        )
        fp2 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.SUCCEEDED, "minimax", "req-1", meta
        )
        assert fp1 != fp2

    def test_different_event_different_fingerprint(self) -> None:
        """不同 event → 不同 fingerprint."""
        meta = build_event_metadata(seq=1, session_id="s")
        fp1 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta
        )
        fp2 = compute_fingerprint(
            EventType.LLM_CALL_SUCCEEDED, EventStatus.SUCCEEDED, "minimax", "req-1", meta
        )
        assert fp1 != fp2

    def test_different_source_different_fingerprint(self) -> None:
        """不同 source → 不同 fingerprint."""
        meta = build_event_metadata(seq=1, session_id="s")
        fp1 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta
        )
        fp2 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "mcp.fs", "req-1", meta
        )
        assert fp1 != fp2

    def test_different_subject_id_different_fingerprint(self) -> None:
        """不同 subject_id → 不同 fingerprint."""
        meta = build_event_metadata(seq=1, session_id="s")
        fp1 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta
        )
        fp2 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-2", meta
        )
        assert fp1 != fp2

    def test_different_session_id_different_fingerprint(self) -> None:
        """不同 session_id → 不同 fingerprint."""
        meta1 = build_event_metadata(seq=1, session_id="sess-A")
        meta2 = build_event_metadata(seq=1, session_id="sess-B")
        fp1 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta1
        )
        fp2 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta2
        )
        assert fp1 != fp2

    def test_fingerprint_does_not_include_fingerprint_field(self) -> None:
        """fingerprint 自身不参与哈希(避免循环)."""
        meta = build_event_metadata(seq=1, session_id="s")
        meta["fingerprint"] = "different_value_1"
        fp1 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta
        )
        meta["fingerprint"] = "different_value_2"
        fp2 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta
        )
        assert fp1 == fp2

    def test_fingerprint_canonical_json_uses_sorted_keys(self) -> None:
        """fingerprint 用 sorted keys, 保证 canonical 稳定."""
        meta = build_event_metadata(seq=1, session_id="s", extra={"z": 1, "a": 2})
        fp1 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta
        )
        # 改 extra key 顺序不影响 fingerprint(因为 canonical JSON sort_keys=True)
        meta_reordered = build_event_metadata(seq=1, session_id="s", extra={"a": 2, "z": 1})
        fp2 = compute_fingerprint(
            EventType.LLM_CALL_STARTED, EventStatus.STARTED, "minimax", "req-1", meta_reordered
        )
        assert fp1 == fp2
