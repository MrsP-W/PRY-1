"""D4.4 — Heartbeat 3 状态 + update/evaluate + assert_alive 测试.

覆盖:
  - 默认值: last_seen_ms=0, transport_alive=True, idle_threshold_ms=30000
  - __post_init__ 类型校验: ValueError 透传
  - update(transport_alive, now_ms): 刷心跳 + 显式 transport 状态
  - evaluate() 优先级: TRANSPORT_DEAD > STALLED > HEALTHY
  - evaluate() 首次未 update → STALLED(不能假定 HEALTHY)
  - evaluate() idle_ms < 0 → ValueError(时间倒流)
  - is_alive() / is_healthy() / assert_alive() 便捷方法
  - now_ms 注入: 测试可控时间
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.policy import (  # noqa: E402
    Heartbeat,
    Liveness,
    PolicyError,
    PolicyHeartbeatError,
)


class TestDefaults:
    """默认值."""

    def test_default_values(self) -> None:
        """默认: last_seen_ms=0, transport_alive=True, idle_threshold_ms=30000."""
        h = Heartbeat()
        assert h.last_seen_ms == 0
        assert h.transport_alive is True
        assert h.idle_threshold_ms == 30_000

    def test_custom_threshold(self) -> None:
        """可传自定义 idle_threshold_ms."""
        h = Heartbeat(idle_threshold_ms=5_000)
        assert h.idle_threshold_ms == 5_000


class TestPostInitValidation:
    """__post_init__ 类型校验."""

    def test_threshold_not_int_raises(self) -> None:
        """threshold 非 int → ValueError."""
        with pytest.raises(ValueError, match="idle_threshold_ms 必须是 int"):
            Heartbeat(idle_threshold_ms="30000")

    def test_threshold_zero_raises(self) -> None:
        """threshold <= 0 → ValueError."""
        with pytest.raises(ValueError, match="idle_threshold_ms 必须 > 0"):
            Heartbeat(idle_threshold_ms=0)

    def test_threshold_negative_raises(self) -> None:
        """threshold < 0 → ValueError."""
        with pytest.raises(ValueError, match="idle_threshold_ms 必须 > 0"):
            Heartbeat(idle_threshold_ms=-1)

    def test_transport_alive_not_bool_raises(self) -> None:
        """transport_alive 非 bool → ValueError."""
        with pytest.raises(ValueError, match="transport_alive 必须是 bool"):
            Heartbeat(transport_alive="yes")

    def test_last_seen_not_int_raises(self) -> None:
        """last_seen_ms 非 int → ValueError."""
        with pytest.raises(ValueError, match="last_seen_ms 必须是 int"):
            Heartbeat(last_seen_ms="123")


class TestUpdate:
    """update(transport_alive, now_ms)."""

    def test_update_without_args_refreshes_time(self) -> None:
        """update() 无参 → 刷 last_seen_ms 到当前时间(transport_alive 不变)."""
        h = Heartbeat(last_seen_ms=0)
        h.update(now_ms=1000)
        assert h.last_seen_ms == 1000
        assert h.transport_alive is True  # 默认不变

    def test_update_explicit_transport_alive(self) -> None:
        """update(transport_alive=False) → 标记死亡."""
        h = Heartbeat()
        h.update(transport_alive=False, now_ms=2000)
        assert h.transport_alive is False
        assert h.last_seen_ms == 2000

    def test_update_keeps_transport_alive_when_none(self) -> None:
        """update(transport_alive=None) → 保持当前值."""
        h = Heartbeat(transport_alive=False)
        h.update(transport_alive=None, now_ms=3000)
        assert h.transport_alive is False  # 保持 False

    def test_update_transport_alive_wrong_type_raises(self) -> None:
        """update(transport_alive="not_bool") → ValueError."""
        h = Heartbeat()
        with pytest.raises(ValueError, match="transport_alive 必须是 bool"):
            h.update(transport_alive="not_bool")

    def test_update_refresh_last_seen_int_0_raises(self) -> None:
        """update(refresh_last_seen=0) → ValueError(拒 int 真值陷阱,D5.5.4 P3)."""
        h = Heartbeat()
        with pytest.raises(ValueError, match="refresh_last_seen 必须是原生 bool"):
            h.update(refresh_last_seen=0)

    def test_update_refresh_last_seen_int_1_raises(self) -> None:
        """update(refresh_last_seen=1) → ValueError(拒 int 1 显式真值陷阱)."""
        h = Heartbeat()
        with pytest.raises(ValueError, match="refresh_last_seen 必须是原生 bool"):
            h.update(refresh_last_seen=1)

    def test_update_refresh_last_seen_str_false_raises(self) -> None:
        """update(refresh_last_seen="False") → ValueError(拒字符串真值)."""
        h = Heartbeat()
        with pytest.raises(ValueError, match="refresh_last_seen 必须是原生 bool"):
            h.update(refresh_last_seen="False")

    def test_update_refresh_last_seen_none_raises(self) -> None:
        """update(refresh_last_seen=None) → ValueError(拒 None,必须显式传 bool)."""
        h = Heartbeat()
        with pytest.raises(ValueError, match="refresh_last_seen 必须是原生 bool"):
            h.update(refresh_last_seen=None)

    def test_update_refresh_last_seen_false_keeps_last_seen(self) -> None:
        """update(refresh_last_seen=False) → 不动 last_seen_ms(D5.5.2 设计契约)."""
        h = Heartbeat(last_seen_ms=1000)
        h.update(refresh_last_seen=False, now_ms=9999)
        assert h.last_seen_ms == 1000  # 未刷
        # 注:transport_alive 也未动(只显式传才动)

    def test_update_refresh_last_seen_true_refreshes(self) -> None:
        """update(refresh_last_seen=True) → 刷 last_seen_ms 到 now_ms(D5.5.2 契约)."""
        h = Heartbeat(last_seen_ms=0)
        h.update(refresh_last_seen=True, now_ms=5000)
        assert h.last_seen_ms == 5000


class TestEvaluatePriority:
    """evaluate() 优先级: TRANSPORT_DEAD > STALLED > HEALTHY."""

    def test_transport_dead_overrides_healthy(self) -> None:
        """transport 断连 → 必为 TRANSPORT_DEAD(即使 last_seen 很近)."""
        h = Heartbeat(last_seen_ms=9999, transport_alive=False, idle_threshold_ms=100)
        assert h.evaluate(now_ms=10000) == Liveness.TRANSPORT_DEAD

    def test_transport_dead_overrides_stalled(self) -> None:
        """transport 断连 → 必为 TRANSPORT_DEAD(即使 last_seen 很久之前)."""
        h = Heartbeat(last_seen_ms=0, transport_alive=False)
        assert h.evaluate() == Liveness.TRANSPORT_DEAD

    def test_first_eval_no_update_is_stalled(self) -> None:
        """首次 evaluate() 未 update → STALLED(不能假定 HEALTHY)."""
        h = Heartbeat()
        assert h.evaluate(now_ms=999_999) == Liveness.STALLED

    def test_idle_within_threshold_is_healthy(self) -> None:
        """idle_ms <= threshold → HEALTHY."""
        h = Heartbeat(last_seen_ms=1000, idle_threshold_ms=500)
        assert h.evaluate(now_ms=1500) == Liveness.HEALTHY

    def test_idle_exceeds_threshold_is_stalled(self) -> None:
        """idle_ms > threshold → STALLED."""
        h = Heartbeat(last_seen_ms=1000, idle_threshold_ms=500)
        assert h.evaluate(now_ms=2000) == Liveness.STALLED

    def test_idle_at_threshold_is_healthy(self) -> None:
        """idle_ms == threshold → HEALTHY(边界 inclusive)."""
        h = Heartbeat(last_seen_ms=1000, idle_threshold_ms=500)
        assert h.evaluate(now_ms=1500) == Liveness.HEALTHY


class TestTimeTravel:
    """evaluate() 时间倒流校验."""

    def test_time_travel_raises_value_error(self) -> None:
        """now_ms < last_seen_ms → ValueError(编程错误透传)."""
        h = Heartbeat(last_seen_ms=5000, idle_threshold_ms=1000)
        with pytest.raises(ValueError, match="now_ms < last_seen_ms"):
            h.evaluate(now_ms=1000)


class TestConvenienceMethods:
    """is_alive / is_healthy / assert_alive."""

    def test_is_alive_when_healthy(self) -> None:
        """HEALTHY → alive=True."""
        h = Heartbeat(last_seen_ms=1000, idle_threshold_ms=500)
        assert h.is_alive(now_ms=1100) is True

    def test_is_alive_when_stalled(self) -> None:
        """STALLED → alive=True(stalled 不算死, transport 还活着)."""
        h = Heartbeat(last_seen_ms=1000, idle_threshold_ms=100)
        assert h.is_alive(now_ms=5000) is True

    def test_is_alive_false_when_transport_dead(self) -> None:
        """TRANSPORT_DEAD → alive=False."""
        h = Heartbeat(transport_alive=False)
        assert h.is_alive() is False

    def test_is_healthy_true_only_when_healthy(self) -> None:
        """is_healthy 仅在 HEALTHY 时 True."""
        h_healthy = Heartbeat(last_seen_ms=1000, idle_threshold_ms=500)
        assert h_healthy.is_healthy(now_ms=1100) is True

        h_stalled = Heartbeat(last_seen_ms=1000, idle_threshold_ms=100)
        assert h_stalled.is_healthy(now_ms=5000) is False

    def test_assert_alive_passes_when_healthy(self) -> None:
        """HEALTHY → assert_alive 不抛."""
        h = Heartbeat(last_seen_ms=1000, idle_threshold_ms=500)
        h.assert_alive(now_ms=1100)  # 不抛

    def test_assert_alive_raises_when_transport_dead(self) -> None:
        """TRANSPORT_DEAD → assert_alive 抛 PolicyHeartbeatError."""
        h = Heartbeat(transport_alive=False)
        with pytest.raises(PolicyHeartbeatError, match="heartbeat 死亡"):
            h.assert_alive()

    def test_heartbeat_error_is_policy_error(self) -> None:
        """PolicyHeartbeatError 继承 PolicyError."""
        h = Heartbeat(transport_alive=False)
        with pytest.raises(PolicyError):
            h.assert_alive()


class TestLivenessEnum:
    """Liveness StrEnum 校验."""

    def test_3_values_present(self) -> None:
        """Liveness 正好 3 个值."""
        assert {Liveness.HEALTHY, Liveness.STALLED, Liveness.TRANSPORT_DEAD} == set(Liveness)

    def test_str_values(self) -> None:
        """Liveness 字符串值与 g006 对齐."""
        assert Liveness.HEALTHY.value == "healthy"
        assert Liveness.STALLED.value == "stalled"
        assert Liveness.TRANSPORT_DEAD.value == "transport_dead"
