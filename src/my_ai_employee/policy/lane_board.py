"""D4.4 — LaneBoard (g006 §"Active lane board/dashboard/status JSON").

参考 g006-task-policy-board-verification-map.md:
  - 3 lanes: active / blocked / finished
  - LaneEntry: 任务实例在 board 中的表示
  - LaneFreshness: fresh / stale(基于 last_update_at_ms + idle_threshold)
  - status JSON over canonical state(导出 to_status_json 供 CLI 消费)

设计:
  - LaneBoard 是 in-memory 数据结构(不落 events 表, 与 EventStore 解耦)
  - add / update / remove / get / group 5 个核心方法
  - 状态转换合法: ACTIVE ↔ BLOCKED → FINISHED(不能 FINISHED → 其他, 终态)
  - FINISHED 是终态, 不能 add 新 entry(若需 reopen, 重新 add 一个新 entry)

D3.3.3 教训应用:
  - 编程错误透传: ValueError 来自参数类型错
  - 业务错误窄化: PolicyLaneError 包裹状态错/转换非法
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any

from my_ai_employee.policy.exceptions import PolicyLaneError

# ===== 枚举 =====


class LaneStatus(enum.StrEnum):
    """Lane 状态 (g006 §"active/blocked/finished lanes").

    ACTIVE:   — 正在执行
    BLOCKED:  — 等待(等审批 / 等资源 / 等 retry)
    FINISHED: — 终态(成功 / 失败 / 取消)
    """

    ACTIVE = "active"
    BLOCKED = "blocked"
    FINISHED = "finished"


class LaneFreshness(enum.StrEnum):
    """Lane entry 新鲜度 (g006 §"heartbeat freshness").

    FRESH: — 最近 update 在 idle_threshold_ms 内
    STALE: — 超过 idle_threshold_ms 未 update
    """

    FRESH = "fresh"
    STALE = "stale"


# ===== LaneEntry dataclass =====


@dataclass
class LaneEntry:
    """Lane board 单条记录.

    Attributes:
        entry_id: 唯一 ID(str, caller 生成, 通常是 task_packet.objective + seq)
        objective: 任务目标(copied from TaskPacket.objective)
        status: 当前 lane 状态(LaneStatus enum)
        owner: 责任人(str, 便于人工排查)
        created_at_ms: 创建 Unix epoch ms
        updated_at_ms: 最近 update Unix epoch ms
        extra: 业务扩展字段(透传 packet 的 acceptance_criteria / scope 等)
    """

    entry_id: str
    objective: str
    status: LaneStatus = LaneStatus.ACTIVE
    owner: str = ""
    created_at_ms: int = 0
    updated_at_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "objective": self.objective,
            "status": self.status.value,
            "owner": self.owner,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "extra": dict(self.extra),
        }


# ===== LaneBoard =====


class LaneBoard:
    """任务 lane 看板 (g006 §"Active lane board/dashboard/status JSON").

    Usage:
        board = LaneBoard(idle_threshold_ms=60_000)
        board.add(LaneEntry(entry_id="t1", objective="D4.5 classifier"))
        board.update("t1", status=LaneStatus.BLOCKED, owner="alice")
        # 看板查询
        active = board.list_by_status(LaneStatus.ACTIVE)
        overview = board.freshness_overview(now_ms=...)
    """

    def __init__(self, idle_threshold_ms: int = 60_000) -> None:
        if not isinstance(idle_threshold_ms, int):
            raise ValueError(
                f"idle_threshold_ms 必须是 int, 实际 {type(idle_threshold_ms).__name__}"
            )
        if idle_threshold_ms <= 0:
            raise ValueError(f"idle_threshold_ms 必须 > 0, 实际 {idle_threshold_ms}")
        self._entries: dict[str, LaneEntry] = {}
        self.idle_threshold_ms = idle_threshold_ms

    # ===== CRUD =====

    def add(self, entry: LaneEntry) -> None:
        """添加 entry.

        Raises:
            PolicyLaneError: entry_id 重复 / entry 不是 LaneEntry / FINISHED 状态不允许
        """
        if not isinstance(entry, LaneEntry):
            raise PolicyLaneError(f"entry 必须是 LaneEntry, 实际 {type(entry).__name__}")
        if not entry.entry_id:
            raise PolicyLaneError("entry_id 必填非空")
        if not isinstance(entry.entry_id, str):
            raise PolicyLaneError(f"entry_id 必须是 str, 实际 {type(entry.entry_id).__name__}")
        if entry.entry_id in self._entries:
            raise PolicyLaneError(f"entry_id 重复: {entry.entry_id!r}(已存在 board 中)")
        if not isinstance(entry.status, LaneStatus):
            raise PolicyLaneError(
                f"status 必须是 LaneStatus enum, 实际 {type(entry.status).__name__}"
            )
        if entry.status == LaneStatus.FINISHED:
            raise PolicyLaneError("新 entry 不能是 FINISHED 状态(终态, 需先走 ACTIVE/BLOCKED 路径)")
        now = int(time.time() * 1000)
        if entry.created_at_ms == 0:
            entry.created_at_ms = now
        if entry.updated_at_ms == 0:
            entry.updated_at_ms = now
        self._entries[entry.entry_id] = entry

    def update(
        self,
        entry_id: str,
        *,
        status: LaneStatus | str | None = None,
        owner: str | None = None,
        extra: dict[str, Any] | None = None,
        now_ms: int | None = None,
    ) -> LaneEntry:
        """更新 entry.

        Args:
            entry_id: 要更新的 entry ID
            status: 新状态(可选, 合法转换 ACTIVE ↔ BLOCKED → FINISHED)
            owner: 新责任人
            extra: 新业务字段(merge 到现有 extra)
            now_ms: 注入"当前时间"(测试用)

        Returns:
            更新后的 LaneEntry

        Raises:
            PolicyLaneError: entry_id 不存在 / 状态转换非法
            ValueError: 参数类型错
        """
        entry = self.get(entry_id)
        if status is not None:
            if isinstance(status, str):
                try:
                    new_status = LaneStatus(status)
                except ValueError as err:
                    raise PolicyLaneError(f"status 非法: {status!r} 不在 LaneStatus 枚举") from err
            elif isinstance(status, LaneStatus):
                new_status = status
            else:
                raise PolicyLaneError(
                    f"status 必须是 LaneStatus 或 str, 实际 {type(status).__name__}"
                )
            self._assert_valid_transition(entry.status, new_status)
            entry.status = new_status
        if owner is not None:
            if not isinstance(owner, str):
                raise ValueError(f"owner 必须是 str, 实际 {type(owner).__name__}")
            entry.owner = owner
        if extra is not None:
            if not isinstance(extra, dict):
                raise ValueError(f"extra 必须是 dict, 实际 {type(extra).__name__}")
            entry.extra.update(extra)
        entry.updated_at_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        return entry

    def remove(self, entry_id: str) -> None:
        """删除 entry(从 board 移除, 不落 events 表)."""
        if not isinstance(entry_id, str):
            raise ValueError(f"entry_id 必须是 str, 实际 {type(entry_id).__name__}")
        if entry_id not in self._entries:
            raise PolicyLaneError(f"entry_id 不存在: {entry_id!r}")
        del self._entries[entry_id]

    def get(self, entry_id: str) -> LaneEntry:
        """查 entry.

        Raises:
            PolicyLaneError: entry_id 不存在
            ValueError: entry_id 不是 str
        """
        if not isinstance(entry_id, str):
            raise ValueError(f"entry_id 必须是 str, 实际 {type(entry_id).__name__}")
        if entry_id not in self._entries:
            raise PolicyLaneError(f"entry_id 不存在: {entry_id!r}")
        return self._entries[entry_id]

    # ===== 查询 =====

    def list_all(self) -> list[LaneEntry]:
        """所有 entry 列表."""
        return list(self._entries.values())

    def list_by_status(self, status: LaneStatus | str) -> list[LaneEntry]:
        """按状态过滤."""
        target = self._normalize_status(status)
        return [e for e in self._entries.values() if e.status == target]

    def group_by_status(self, status: LaneStatus | str) -> list[LaneEntry]:
        """按状态分组单 lane(同 list_by_status, g006 用词)."""
        return self.list_by_status(status)

    def group_all(self) -> dict[str, list[LaneEntry]]:
        """按状态分组返回 dict(active/blocked/finished 3 键, 值为 entry 列表)."""
        return {
            LaneStatus.ACTIVE.value: self.list_by_status(LaneStatus.ACTIVE),
            LaneStatus.BLOCKED.value: self.list_by_status(LaneStatus.BLOCKED),
            LaneStatus.FINISHED.value: self.list_by_status(LaneStatus.FINISHED),
        }

    def freshness(self, entry_id: str, *, now_ms: int | None = None) -> LaneFreshness:
        """单条 entry 的新鲜度."""
        entry = self.get(entry_id)
        return self._compute_freshness(entry, now_ms=now_ms)

    def freshness_overview(self, *, now_ms: int | None = None) -> dict[str, int]:
        """全 board 新鲜度统计 {fresh: N, stale: M}."""
        fresh = 0
        stale = 0
        for entry in self._entries.values():
            if self._compute_freshness(entry, now_ms=now_ms) == LaneFreshness.FRESH:
                fresh += 1
            else:
                stale += 1
        return {"fresh": fresh, "stale": stale}

    def to_status_json(self, *, now_ms: int | None = None) -> dict[str, Any]:
        """导出 status JSON (g006 §"status JSON over canonical state")."""
        grouped = self.group_all()
        return {
            "lanes": {status: [e.to_dict() for e in grouped[status]] for status in grouped},
            "freshness": self.freshness_overview(now_ms=now_ms),
            "total": len(self._entries),
            "idle_threshold_ms": self.idle_threshold_ms,
        }

    # ===== 内部 =====

    def _compute_freshness(self, entry: LaneEntry, *, now_ms: int | None = None) -> LaneFreshness:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        if not isinstance(now, int):
            raise ValueError(f"now_ms 必须是 int, 实际 {type(now).__name__}")
        idle = now - entry.updated_at_ms
        if idle <= self.idle_threshold_ms:
            return LaneFreshness.FRESH
        return LaneFreshness.STALE

    def _normalize_status(self, status: LaneStatus | str) -> LaneStatus:
        if isinstance(status, LaneStatus):
            return status
        if isinstance(status, str):
            try:
                return LaneStatus(status)
            except ValueError as err:
                raise PolicyLaneError(f"status 非法: {status!r} 不在 LaneStatus 枚举") from err
        raise PolicyLaneError(f"status 必须是 LaneStatus 或 str, 实际 {type(status).__name__}")

    def _assert_valid_transition(self, from_status: LaneStatus, to_status: LaneStatus) -> None:
        """状态转换合法性校验.

        合法转换:
          - ACTIVE → BLOCKED (等审批/资源)
          - ACTIVE → FINISHED (正常完成)
          - BLOCKED → ACTIVE (恢复)
          - BLOCKED → FINISHED (取消)
          - FINISHED → (无, 终态)
        相同状态幂等通过(便于 caller 重复 update)。
        """
        if from_status == to_status:
            return  # 幂等, 允许
        valid: dict[LaneStatus, set[LaneStatus]] = {
            LaneStatus.ACTIVE: {LaneStatus.BLOCKED, LaneStatus.FINISHED},
            LaneStatus.BLOCKED: {LaneStatus.ACTIVE, LaneStatus.FINISHED},
            LaneStatus.FINISHED: set(),  # 终态
        }
        allowed = valid[from_status]
        if to_status not in allowed:
            raise PolicyLaneError(
                f"非法状态转换: {from_status.value} → {to_status.value} "
                f"(合法转换: {sorted(s.value for s in allowed) or '无'})"
            )


# ===== 模块导出 =====


__all__ = [
    "LaneStatus",
    "LaneFreshness",
    "LaneEntry",
    "LaneBoard",
]
