"""D4.4 — Heartbeat (g006 §"liveness heartbeat" 段).

参考 g006-task-policy-board-verification-map.md:
  - healthy: 正常(最近一次 update 在 idle_threshold_ms 内)
  - stalled: 停滞(超过 idle_threshold_ms 未更新, 但 transport 还活着)
  - transport-dead: 传输死亡(transport 主动断连, 优先级最高)

设计:
  - Heartbeat 单实例(per session / per task)
  - update() 刷新 last_seen_ms + transport_alive(可选注入 now_ms 便于测试)
  - evaluate() 返回当前 Liveness(可注入 now_ms)
  - assert_alive() strict 模式: TRANSPORT_DEAD 抛 PolicyHeartbeatError
  - 编程错误透传(D3.3.3 教训): ValueError 来自参数类型错/时间倒流
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass

from my_ai_employee.policy.exceptions import PolicyHeartbeatError

# ===== 3 状态枚举 =====


class Liveness(enum.StrEnum):
    """Heartbeat liveness 状态 (g006 §"healthy/stalled/transport-dead").

    HEALTHY:        — 最近 update 在 idle_threshold_ms 内
    STALLED:        — 超过 idle_threshold_ms 未 update, 但 transport 还活着
    TRANSPORT_DEAD: — transport 主动断连(self.transport_alive=False)
    """

    HEALTHY = "healthy"
    STALLED = "stalled"
    TRANSPORT_DEAD = "transport_dead"


# ===== Heartbeat dataclass =====


@dataclass
class Heartbeat:
    """会话/任务心跳 (g006 §"running-state liveness heartbeat").

    Attributes:
        last_seen_ms: 最近一次 update 的 Unix epoch ms(0 = 未 update 过)
        transport_alive: transport 是否还活着(MCP server 断连 → False)
        idle_threshold_ms: HEALTHY 阈值(默认 30000 = 30s, 测试时可调小)
    """

    last_seen_ms: int = 0
    transport_alive: bool = True
    idle_threshold_ms: int = 30_000

    def __post_init__(self) -> None:
        if not isinstance(self.idle_threshold_ms, int):
            raise ValueError(
                f"idle_threshold_ms 必须是 int, 实际 {type(self.idle_threshold_ms).__name__}"
            )
        if self.idle_threshold_ms <= 0:
            raise ValueError(f"idle_threshold_ms 必须 > 0, 实际 {self.idle_threshold_ms}")
        if not isinstance(self.transport_alive, bool):
            raise ValueError(
                f"transport_alive 必须是 bool, 实际 {type(self.transport_alive).__name__}"
            )
        if not isinstance(self.last_seen_ms, int):
            raise ValueError(f"last_seen_ms 必须是 int, 实际 {type(self.last_seen_ms).__name__}")

    # ===== update =====

    def update(
        self,
        transport_alive: bool | None = None,
        *,
        now_ms: int | None = None,
        refresh_last_seen: bool = True,
    ) -> None:
        """刷新心跳.

        Args:
            transport_alive: 显式指定 transport 状态(None = 保持当前)
            now_ms: 注入"当前时间"(测试用, None = int(time.time() * 1000))
            refresh_last_seen: 是否同步刷新 last_seen_ms(D5.5.2 新增,默认 True)。
                False = 仅刷新 transport_alive,不动 last_seen_ms,
                用于 OutboxDispatcher.run_once 这种"先 evaluate 再 update"场景,
                避免 STALLED 状态被自己覆盖。

        Raises:
            ValueError: transport_alive 不是 bool(now_ms 不是 int 暂不校验)
        """
        if transport_alive is not None:
            if not isinstance(transport_alive, bool):
                raise ValueError(
                    f"transport_alive 必须是 bool, 实际 {type(transport_alive).__name__}"
                )
            self.transport_alive = transport_alive
        if refresh_last_seen:
            self.last_seen_ms = now_ms if now_ms is not None else int(time.time() * 1000)

    # ===== evaluate =====

    def evaluate(self, *, now_ms: int | None = None) -> Liveness:
        """评估当前 liveness.

        Returns:
            Liveness.HEALTHY | STALLED | TRANSPORT_DEAD

        优先级: TRANSPORT_DEAD > STALLED > HEALTHY
            (transport 断连 → 必为 TRANSPORT_DEAD, 不论 last_seen 多近)

        Raises:
            ValueError: now_ms < last_seen_ms(时间倒流, 视为编程错误)
        """
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        # 1) transport 断连 → TRANSPORT_DEAD(优先级最高)
        if not self.transport_alive:
            return Liveness.TRANSPORT_DEAD
        # 2) 首次未 update → 视作 STALLED(不能假定 HEALTHY)
        if self.last_seen_ms == 0:
            return Liveness.STALLED
        # 3) 计算 idle 时长
        idle_ms = now - self.last_seen_ms
        if idle_ms < 0:
            raise ValueError(
                f"now_ms < last_seen_ms(now={now}, last_seen={self.last_seen_ms}, "
                f"idle_ms={idle_ms}, 视为时间倒流)"
            )
        if idle_ms <= self.idle_threshold_ms:
            return Liveness.HEALTHY
        return Liveness.STALLED

    # ===== 便捷方法 =====

    def is_alive(self, *, now_ms: int | None = None) -> bool:
        """活着?(HEALTHY 或 STALLED 都算活着, TRANSPORT_DEAD 才算死)."""
        return self.evaluate(now_ms=now_ms) != Liveness.TRANSPORT_DEAD

    def is_healthy(self, *, now_ms: int | None = None) -> bool:
        """健康?(仅 HEALTHY 算健康, STALLED 已不正常)."""
        return self.evaluate(now_ms=now_ms) == Liveness.HEALTHY

    def assert_alive(self, *, now_ms: int | None = None) -> None:
        """断言 alive — 死了抛 PolicyHeartbeatError(给 strict caller 用)."""
        liveness = self.evaluate(now_ms=now_ms)
        if liveness == Liveness.TRANSPORT_DEAD:
            raise PolicyHeartbeatError(
                f"heartbeat 死亡: liveness={liveness.value}, "
                f"last_seen_ms={self.last_seen_ms}, transport_alive={self.transport_alive}"
            )


# ===== 模块导出 =====


__all__ = ["Heartbeat", "Liveness"]
