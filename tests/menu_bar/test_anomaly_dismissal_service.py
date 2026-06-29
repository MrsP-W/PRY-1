"""v0.2.53.16 AnomalyDismissalService Protocol + Stub 测试.

边界(沿 v0.2.53.14 §5 + 撞坑 #65):
    - 默认全 Stub(is_enabled=False,dismiss 返回 not_enabled)
    - 不调 DB / 不调 OutboxStore / 不读 Keychain 明文
"""

from __future__ import annotations

import pytest

from my_ai_employee.menu_bar.anomaly_dismissal_service import (
    AnomalyDismissalServiceStub,
    DismissalResult,
)


class TestStubIsEnabled:
    """is_enabled() 默认 False(沿撞坑 #65 opt-in 边界)."""

    def test_is_enabled_default_false(self) -> None:
        """Stub 默认 is_enabled=False(需 opt-in)."""
        service = AnomalyDismissalServiceStub()
        assert service.is_enabled() is False


class TestStubDismiss:
    """dismiss() 默认返回失败结果(Stub 不真 dismiss)."""

    def test_dismiss_returns_not_enabled(self) -> None:
        """Stub dismiss 返回 success=False, error='not_enabled'."""
        service = AnomalyDismissalServiceStub()
        result = service.dismiss("2026-06-26|星巴克|38.50")
        assert isinstance(result, DismissalResult)
        assert result.success is False
        assert result.error == "not_enabled"
        assert result.anomaly_id is None
        assert result.dismissed_at_ms is None

    def test_dismiss_with_reason_still_returns_not_enabled(self) -> None:
        """带 reason 调用仍返回 not_enabled(Stub 忽略 reason)."""
        service = AnomalyDismissalServiceStub()
        result = service.dismiss("2026-06-26|星巴克|38.50", reason="已知商家")
        assert result.success is False
        assert result.error == "not_enabled"

    def test_dismiss_invalid_anomaly_id_empty_string(self) -> None:
        """空字符串 anomaly_id → invalid_anomaly_id."""
        service = AnomalyDismissalServiceStub()
        result = service.dismiss("")
        assert result.success is False
        assert result.error == "invalid_anomaly_id"

    def test_dismiss_invalid_anomaly_id_not_string(self) -> None:
        """非 str 类型 anomaly_id → invalid_anomaly_id."""
        service = AnomalyDismissalServiceStub()
        # 故意传 int(类型错误) — 严判必须拒绝
        result = service.dismiss(123)
        assert result.success is False
        assert result.error == "invalid_anomaly_id"

    def test_dismiss_invalid_reason_not_string(self) -> None:
        """非 str 类型 reason → invalid_reason."""
        service = AnomalyDismissalServiceStub()
        result = service.dismiss("2026-06-26|星巴克|38.50", reason=123)
        assert result.success is False
        assert result.error == "invalid_reason"

    def test_dismiss_reason_too_long(self) -> None:
        """reason 超 240 字符 → reason_too_long."""
        service = AnomalyDismissalServiceStub()
        result = service.dismiss("2026-06-26|星巴克|38.50", reason="r" * 241)
        assert result.success is False
        assert result.error == "reason_too_long"

    def test_dismiss_reason_at_limit_ok(self) -> None:
        """reason 正好 240 字符 → 边界内(不超长)."""
        service = AnomalyDismissalServiceStub()
        result = service.dismiss("2026-06-26|星巴克|38.50", reason="r" * 240)
        # 长度 OK,但 Stub 仍返回 not_enabled
        assert result.error == "not_enabled"


class TestStubListRecentDismissals:
    """list_recent_dismissals() 默认返回 []."""

    def test_list_default_empty(self) -> None:
        """默认返回 []."""
        service = AnomalyDismissalServiceStub()
        assert service.list_recent_dismissals() == []

    def test_list_with_limit_returns_empty(self) -> None:
        """带 limit 参数仍返回 [] (Stub 不校验)."""
        service = AnomalyDismissalServiceStub()
        assert service.list_recent_dismissals(limit=100) == []


class TestDismissalResultDataclass:
    """DismissalResult dataclass 字段."""

    def test_success_result(self) -> None:
        """成功结果."""
        result = DismissalResult(
            success=True,
            anomaly_id="2026-06-26|星巴克|38.50",
            dismissed_at_ms=1234567890,
            error=None,
            reason="",
        )
        assert result.success is True
        assert result.anomaly_id == "2026-06-26|星巴克|38.50"
        assert result.dismissed_at_ms == 1234567890
        assert result.error is None

    def test_failure_result(self) -> None:
        """失败结果."""
        result = DismissalResult(
            success=False,
            anomaly_id=None,
            dismissed_at_ms=None,
            error="not_enabled",
            reason="Stub 阶段不真 dismiss",
        )
        assert result.success is False
        assert result.error == "not_enabled"
        assert result.anomaly_id is None


class TestStubFactory:
    """AnomalyDismissalServiceStub.get_default_stub 工厂."""

    def test_get_default_stub(self) -> None:
        """工厂返回 AnomalyDismissalServiceStub 实例."""
        stub = AnomalyDismissalServiceStub.get_default_stub()
        assert isinstance(stub, AnomalyDismissalServiceStub)


class TestStubBoundaries:
    """撞坑 #65 边界 — 默认无写入 + 无 SMTP + 无 Keychain."""

    def test_default_does_not_read_keychain(self) -> None:
        """Stub 不调用 KeychainProbe / 不读凭据."""
        service = AnomalyDismissalServiceStub()
        # 验证 is_enabled / dismiss / list 都不依赖外部资源
        assert service.is_enabled() is False
        assert service.dismiss("any") is not None
        assert service.list_recent_dismissals() == []

    def test_default_does_not_write_db(self) -> None:
        """Stub dismiss 永远返回失败结果(不静默成功 = 证明不写 DB)."""
        service = AnomalyDismissalServiceStub()
        result = service.dismiss("2026-06-26|星巴克|38.50")
        assert result.success is False
        # 没有 anomaly_id 填入 = 没真写
        assert result.anomaly_id is None
        assert result.dismissed_at_ms is None


@pytest.mark.parametrize(
    "anomaly_id",
    [
        "2026-06-26|星巴克|38.50",
        "2026-06-25|美团外卖|58.00",
        "2026-06-24|工资发放|15000.00",
    ],
)
class TestStubVariousAnomalyIds:
    """各种 anomaly_id 格式 — Stub 都返回 not_enabled(格式不校验,只严判类型)."""

    def test_various_anomaly_ids_return_not_enabled(self, anomaly_id: str) -> None:
        service = AnomalyDismissalServiceStub()
        result = service.dismiss(anomaly_id)
        assert result.error == "not_enabled"
        assert result.success is False
