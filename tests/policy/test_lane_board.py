"""D4.4 — LaneBoard 3 lanes + 状态转换 + freshness + status JSON 测试.

覆盖:
  - LaneBoard 初始化: idle_threshold_ms 类型校验
  - add: 重复 entry_id / 空 entry_id / 非 LaneEntry / FINISHED 状态拒绝
  - update: 状态转换合法性矩阵(ACTIVE ↔ BLOCKED → FINISHED)
  - update: 相同状态幂等通过
  - update: 非法转换 → PolicyLaneError
  - update: owner/extra 类型校验 → ValueError(透传)
  - remove / get: 不存在 entry_id → PolicyLaneError
  - list_by_status / group_all / group_by_status
  - freshness 单条 + freshness_overview 全板
  - to_status_json 导出 g006 §"status JSON"
  - now_ms 注入: 测试可控时间
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.policy import (  # noqa: E402
    LaneBoard,
    LaneEntry,
    LaneFreshness,
    LaneStatus,
    PolicyError,
    PolicyLaneError,
)

# ===== Fixtures =====


@pytest.fixture
def board() -> LaneBoard:
    """默认 board, idle_threshold=60s."""
    return LaneBoard(idle_threshold_ms=60_000)


@pytest.fixture
def entry() -> LaneEntry:
    """默认 entry(ACTIVE 状态)."""
    return LaneEntry(entry_id="t1", objective="D4.4 任务策略板")


# ===== 初始化 =====


class TestInit:
    def test_default_init(self) -> None:
        """默认 idle_threshold=60000ms."""
        b = LaneBoard()
        assert b.idle_threshold_ms == 60_000

    def test_custom_threshold(self) -> None:
        """自定义 idle_threshold."""
        b = LaneBoard(idle_threshold_ms=10_000)
        assert b.idle_threshold_ms == 10_000

    def test_threshold_not_int_raises(self) -> None:
        """非 int threshold → ValueError."""
        with pytest.raises(ValueError, match="idle_threshold_ms 必须是 int"):
            LaneBoard(idle_threshold_ms="10000")

    def test_threshold_zero_raises(self) -> None:
        """threshold=0 → ValueError."""
        with pytest.raises(ValueError, match="idle_threshold_ms 必须 > 0"):
            LaneBoard(idle_threshold_ms=0)

    def test_threshold_negative_raises(self) -> None:
        """threshold<0 → ValueError."""
        with pytest.raises(ValueError, match="idle_threshold_ms 必须 > 0"):
            LaneBoard(idle_threshold_ms=-1)


# ===== add =====


class TestAdd:
    def test_add_entry(self, board: LaneBoard, entry: LaneEntry) -> None:
        """add 成功."""
        board.add(entry)
        assert board.get("t1") is entry

    def test_add_sets_timestamps(self, board: LaneBoard) -> None:
        """add 时 created/updated_at_ms 自动设(若为 0)."""
        e = LaneEntry(entry_id="t1", objective="x", created_at_ms=0, updated_at_ms=0)
        board.add(e)
        assert e.created_at_ms > 0
        assert e.updated_at_ms > 0

    def test_add_preserves_explicit_timestamps(self, board: LaneBoard) -> None:
        """add 时若时间已填, 保留(不覆盖)."""
        e = LaneEntry(entry_id="t1", objective="x", created_at_ms=1000, updated_at_ms=2000)
        board.add(e)
        assert e.created_at_ms == 1000
        assert e.updated_at_ms == 2000

    def test_add_duplicate_id_raises(self, board: LaneBoard, entry: LaneEntry) -> None:
        """重复 entry_id → PolicyLaneError."""
        board.add(entry)
        with pytest.raises(PolicyLaneError, match="entry_id 重复"):
            board.add(LaneEntry(entry_id="t1", objective="dup"))

    def test_add_empty_id_raises(self, board: LaneBoard) -> None:
        """空 entry_id → PolicyLaneError."""
        with pytest.raises(PolicyLaneError, match="entry_id 必填非空"):
            board.add(LaneEntry(entry_id="", objective="x"))

    def test_add_non_lane_entry_raises(self, board: LaneBoard) -> None:
        """非 LaneEntry → PolicyLaneError."""
        with pytest.raises(PolicyLaneError, match="entry 必须是 LaneEntry"):
            board.add({"entry_id": "t1"})

    def test_add_finished_status_raises(self, board: LaneBoard) -> None:
        """add FINISHED 状态 → PolicyLaneError(终态)."""
        with pytest.raises(PolicyLaneError, match="新 entry 不能是 FINISHED 状态"):
            board.add(LaneEntry(entry_id="t1", objective="x", status=LaneStatus.FINISHED))

    def test_add_blocked_status_allowed(self, board: LaneBoard) -> None:
        """add BLOCKED 状态 OK(等审批场景)."""
        e = LaneEntry(entry_id="t1", objective="x", status=LaneStatus.BLOCKED)
        board.add(e)
        assert board.get("t1").status == LaneStatus.BLOCKED


# ===== update + 状态转换合法性矩阵 =====


class TestStateTransitions:
    """g006 状态转换: ACTIVE ↔ BLOCKED → FINISHED."""

    def test_active_to_blocked(self, board: LaneBoard, entry: LaneEntry) -> None:
        """ACTIVE → BLOCKED 合法."""
        board.add(entry)
        board.update("t1", status=LaneStatus.BLOCKED)
        assert board.get("t1").status == LaneStatus.BLOCKED

    def test_active_to_finished(self, board: LaneBoard, entry: LaneEntry) -> None:
        """ACTIVE → FINISHED 合法."""
        board.add(entry)
        board.update("t1", status=LaneStatus.FINISHED)
        assert board.get("t1").status == LaneStatus.FINISHED

    def test_blocked_to_active(self, board: LaneBoard) -> None:
        """BLOCKED → ACTIVE 合法(恢复)."""
        board.add(LaneEntry(entry_id="t1", objective="x", status=LaneStatus.BLOCKED))
        board.update("t1", status=LaneStatus.ACTIVE)
        assert board.get("t1").status == LaneStatus.ACTIVE

    def test_blocked_to_finished(self, board: LaneBoard) -> None:
        """BLOCKED → FINISHED 合法(取消/超时收尾)."""
        board.add(LaneEntry(entry_id="t1", objective="x", status=LaneStatus.BLOCKED))
        board.update("t1", status=LaneStatus.FINISHED)
        assert board.get("t1").status == LaneStatus.FINISHED

    def test_finished_is_terminal(self, board: LaneBoard, entry: LaneEntry) -> None:
        """FINISHED 终态, 不能再 update 到任何状态."""
        board.add(entry)
        board.update("t1", status=LaneStatus.FINISHED)
        for target in (LaneStatus.ACTIVE, LaneStatus.BLOCKED):
            with pytest.raises(PolicyLaneError, match="非法状态转换"):
                board.update("t1", status=target)

    def test_same_state_idempotent(self, board: LaneBoard, entry: LaneEntry) -> None:
        """相同状态幂等通过(便于 caller 重复 update)."""
        board.add(entry)
        board.update("t1", status=LaneStatus.ACTIVE)  # 仍 ACTIVE
        assert board.get("t1").status == LaneStatus.ACTIVE

    def test_update_with_str_status(self, board: LaneBoard, entry: LaneEntry) -> None:
        """update 接受 str 状态(便于 JSON 输入)."""
        board.add(entry)
        board.update("t1", status="blocked")
        assert board.get("t1").status == LaneStatus.BLOCKED

    def test_update_with_invalid_str_raises(self, board: LaneBoard, entry: LaneEntry) -> None:
        """非法 str 状态 → PolicyLaneError."""
        board.add(entry)
        with pytest.raises(PolicyLaneError, match="status 非法"):
            board.update("t1", status="bogus_status")

    def test_update_with_invalid_type_raises(self, board: LaneBoard, entry: LaneEntry) -> None:
        """非 LaneStatus/str 状态 → PolicyLaneError."""
        board.add(entry)
        with pytest.raises(PolicyLaneError, match="status 必须是 LaneStatus 或 str"):
            board.update("t1", status=123)

    def test_update_owner(self, board: LaneBoard, entry: LaneEntry) -> None:
        """update owner 字段."""
        board.add(entry)
        board.update("t1", owner="alice")
        assert board.get("t1").owner == "alice"

    def test_update_owner_wrong_type_raises(self, board: LaneBoard, entry: LaneEntry) -> None:
        """update owner 非 str → ValueError(编程错误透传)."""
        board.add(entry)
        with pytest.raises(ValueError, match="owner 必须是 str"):
            board.update("t1", owner=123)

    def test_update_extra_merges(self, board: LaneBoard, entry: LaneEntry) -> None:
        """update extra merge 到现有 extra(不覆盖)."""
        board.add(entry)
        board.update("t1", extra={"k1": "v1"})
        board.update("t1", extra={"k2": "v2"})
        e = board.get("t1")
        assert e.extra == {"k1": "v1", "k2": "v2"}

    def test_update_extra_wrong_type_raises(self, board: LaneBoard, entry: LaneEntry) -> None:
        """update extra 非 dict → ValueError(透传)."""
        board.add(entry)
        with pytest.raises(ValueError, match="extra 必须是 dict"):
            board.update("t1", extra="not a dict")

    def test_update_sets_updated_at_ms(self, board: LaneBoard, entry: LaneEntry) -> None:
        """update 自动刷 updated_at_ms(可注入 now_ms)."""
        board.add(entry)
        board.update("t1", owner="alice", now_ms=1234567)
        assert board.get("t1").updated_at_ms == 1234567

    def test_update_nonexistent_id_raises(self, board: LaneBoard) -> None:
        """更新不存在的 entry_id → PolicyLaneError."""
        with pytest.raises(PolicyLaneError, match="entry_id 不存在"):
            board.update("nonexistent", status=LaneStatus.BLOCKED)


# ===== remove / get =====


class TestRemoveAndGet:
    def test_remove(self, board: LaneBoard, entry: LaneEntry) -> None:
        """remove 成功."""
        board.add(entry)
        board.remove("t1")
        with pytest.raises(PolicyLaneError, match="entry_id 不存在"):
            board.get("t1")

    def test_remove_nonexistent_raises(self, board: LaneBoard) -> None:
        """remove 不存在 entry_id → PolicyLaneError."""
        with pytest.raises(PolicyLaneError, match="entry_id 不存在"):
            board.remove("nope")

    def test_remove_wrong_type_raises(self, board: LaneBoard) -> None:
        """remove 非 str entry_id → ValueError(透传)."""
        with pytest.raises(ValueError, match="entry_id 必须是 str"):
            board.remove(123)

    def test_get_wrong_type_raises(self, board: LaneBoard) -> None:
        """get 非 str entry_id → ValueError(透传)."""
        with pytest.raises(ValueError, match="entry_id 必须是 str"):
            board.get(123)

    def test_get_returns_lane_entry(self, board: LaneBoard, entry: LaneEntry) -> None:
        """get 返回 LaneEntry 实例."""
        board.add(entry)
        result = board.get("t1")
        assert isinstance(result, LaneEntry)
        assert result.entry_id == "t1"
        assert result.objective == "D4.4 任务策略板"


# ===== 查询 =====


class TestQueries:
    def test_list_all(self, board: LaneBoard) -> None:
        """list_all 返回所有 entry."""
        board.add(LaneEntry(entry_id="a", objective="a"))
        board.add(LaneEntry(entry_id="b", objective="b", status=LaneStatus.BLOCKED))
        assert len(board.list_all()) == 2

    def test_list_by_status_enum(self, board: LaneBoard) -> None:
        """list_by_status(LaneStatus.ACTIVE) 过滤."""
        board.add(LaneEntry(entry_id="a", objective="a"))
        board.add(LaneEntry(entry_id="b", objective="b", status=LaneStatus.BLOCKED))
        active = board.list_by_status(LaneStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].entry_id == "a"

    def test_list_by_status_str(self, board: LaneBoard) -> None:
        """list_by_status 接受 str(同 enum)."""
        board.add(LaneEntry(entry_id="a", objective="a"))
        assert len(board.list_by_status("active")) == 1

    def test_list_by_status_invalid_raises(self, board: LaneBoard) -> None:
        """list_by_status 非法 str → PolicyLaneError."""
        with pytest.raises(PolicyLaneError, match="status 非法"):
            board.list_by_status("bogus")

    def test_list_by_status_wrong_type_raises(self, board: LaneBoard) -> None:
        """list_by_status 非 LaneStatus/str → PolicyLaneError."""
        with pytest.raises(PolicyLaneError, match="status 必须是 LaneStatus 或 str"):
            board.list_by_status(123)

    def test_group_by_status_alias(self, board: LaneBoard) -> None:
        """group_by_status 是 list_by_status 的 alias(g006 用词)."""
        board.add(LaneEntry(entry_id="a", objective="a"))
        assert board.group_by_status(LaneStatus.ACTIVE) == board.list_by_status(LaneStatus.ACTIVE)

    def test_group_all_returns_3_lanes(self, board: LaneBoard) -> None:
        """group_all 返回 3 lanes 字典."""
        board.add(LaneEntry(entry_id="a", objective="a"))
        board.add(LaneEntry(entry_id="b", objective="b", status=LaneStatus.BLOCKED))
        # FINISHED 走 ACTIVE → FINISHED 路径(add 不允许直接 FINISHED)
        board.add(LaneEntry(entry_id="c", objective="c"))
        board.update("c", status=LaneStatus.FINISHED)
        result = board.group_all()
        assert set(result.keys()) == {"active", "blocked", "finished"}
        assert len(result["active"]) == 1
        assert len(result["blocked"]) == 1
        assert len(result["finished"]) == 1


# ===== Freshness =====


class TestFreshness:
    def test_freshness_recent_is_fresh(self, board: LaneBoard) -> None:
        """最近 update → FRESH."""
        e = LaneEntry(
            entry_id="t1",
            objective="x",
            created_at_ms=1000,
            updated_at_ms=1000,
        )
        board.add(e)
        assert board.freshness("t1", now_ms=2000) == LaneFreshness.FRESH

    def test_freshness_idle_exceeds_threshold_is_stale(self, board: LaneBoard) -> None:
        """idle > threshold → STALE."""
        e = LaneEntry(
            entry_id="t1",
            objective="x",
            created_at_ms=1000,
            updated_at_ms=1000,
        )
        board.add(e)
        # threshold 60s, idle 100s → STALE
        assert board.freshness("t1", now_ms=101_000) == LaneFreshness.STALE

    def test_freshness_at_threshold_is_fresh(self, board: LaneBoard) -> None:
        """idle == threshold → FRESH(inclusive 边界)."""
        e = LaneEntry(
            entry_id="t1",
            objective="x",
            created_at_ms=1000,
            updated_at_ms=1000,
        )
        board.add(e)
        # threshold 60s, idle 60s → FRESH
        assert board.freshness("t1", now_ms=61_000) == LaneFreshness.FRESH

    def test_freshness_overview(self, board: LaneBoard) -> None:
        """freshness_overview 返回 fresh/stale 计数."""
        # a: updated_at=1000, threshold=60s; b: updated_at=2000
        # now=61_000 → a idle=60s ≤ 60s (FRESH), b idle=59s ≤ 60s (FRESH)
        # then update b updated_at to 1000; now=61_000 → both idle=60s FRESH
        # 想 1 fresh + 1 stale: now=130_000 → a idle=129s STALE, b idle=128s STALE
        # 真正 1f+1s: a updated=1000, b updated=10_000, now=70_000 → a idle=69s STALE, b idle=60s FRESH
        board.add(
            LaneEntry(
                entry_id="a",
                objective="a",
                created_at_ms=1000,
                updated_at_ms=1000,
            )
        )
        board.add(
            LaneEntry(
                entry_id="b",
                objective="b",
                created_at_ms=2000,
                updated_at_ms=10_000,
            )
        )
        result = board.freshness_overview(now_ms=70_000)
        assert result == {"fresh": 1, "stale": 1}

    def test_freshness_wrong_now_type_raises(self, board: LaneBoard) -> None:
        """freshness now_ms 非 int → ValueError."""
        e = LaneEntry(entry_id="t1", objective="x")
        board.add(e)
        with pytest.raises(ValueError, match="now_ms 必须是 int"):
            board.freshness("t1", now_ms="123")


# ===== to_status_json =====


class TestStatusJson:
    def test_status_json_structure(self, board: LaneBoard) -> None:
        """to_status_json 返回 g006 规范结构."""
        board.add(LaneEntry(entry_id="a", objective="a"))
        result = board.to_status_json(now_ms=1000)
        assert "lanes" in result
        assert "freshness" in result
        assert "total" in result
        assert "idle_threshold_ms" in result
        assert result["total"] == 1
        assert result["idle_threshold_ms"] == 60_000
        assert set(result["lanes"].keys()) == {"active", "blocked", "finished"}

    def test_status_json_includes_freshness_counts(self, board: LaneBoard) -> None:
        """to_status_json 含 fresh/stale 计数."""
        board.add(
            LaneEntry(
                entry_id="a",
                objective="a",
                created_at_ms=1000,
                updated_at_ms=1000,
            )
        )
        result = board.to_status_json(now_ms=2000)
        assert result["freshness"]["fresh"] == 1
        assert result["freshness"]["stale"] == 0


# ===== LaneEntry dataclass =====


class TestLaneEntry:
    def test_default_values(self) -> None:
        """LaneEntry 默认 status=ACTIVE, owner='', created/updated=0, extra={}."""
        e = LaneEntry(entry_id="t1", objective="x")
        assert e.status == LaneStatus.ACTIVE
        assert e.owner == ""
        assert e.created_at_ms == 0
        assert e.updated_at_ms == 0
        assert e.extra == {}

    def test_to_dict(self) -> None:
        """to_dict 返回所有字段."""
        e = LaneEntry(
            entry_id="t1",
            objective="x",
            status=LaneStatus.BLOCKED,
            owner="alice",
            created_at_ms=1000,
            updated_at_ms=2000,
            extra={"k": "v"},
        )
        d = e.to_dict()
        assert d["entry_id"] == "t1"
        assert d["objective"] == "x"
        assert d["status"] == "blocked"
        assert d["owner"] == "alice"
        assert d["created_at_ms"] == 1000
        assert d["updated_at_ms"] == 2000
        assert d["extra"] == {"k": "v"}


# ===== LaneError 层级 =====


class TestPolicyLaneError:
    def test_lane_error_is_policy_error(self) -> None:
        """PolicyLaneError 继承 PolicyError."""
        assert issubclass(PolicyLaneError, PolicyError)
