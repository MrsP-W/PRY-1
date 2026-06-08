"""D4.2 — McpDegradedReport / McpErrorSurface / LifecyclePhase 数据结构测试.

覆盖:
  - LifecyclePhase 5 阶段(枚举值)
  - McpServerStatus dataclass(frozen)
  - McpErrorSurface 5 字段 + to_dict 序列化
  - McpDegradedReport 健康/降级判断 + to_dict
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.mcp.report import (  # noqa: E402
    LifecyclePhase,
    McpDegradedReport,
    McpErrorSurface,
    McpServerStatus,
)


class TestLifecyclePhase:
    def test_all_phases(self) -> None:
        """5 个生命周期阶段."""
        assert LifecyclePhase.DISCOVERY.value == "discovery"
        assert LifecyclePhase.CONNECT.value == "connect"
        assert LifecyclePhase.INITIALIZE.value == "initialize"
        assert LifecyclePhase.CALL.value == "call"
        assert LifecyclePhase.DISCONNECT.value == "disconnect"


class TestMcpServerStatus:
    def test_default_values(self) -> None:
        s = McpServerStatus(name="fs", required=False, connected=True)
        assert s.tools == []
        assert s.error is None

    def test_required_flag_distinguishes(self) -> None:
        """required 字段是必填字段, 决策依据."""
        s_required = McpServerStatus(name="cal", required=True, connected=False, error="x")
        s_optional = McpServerStatus(name="fs", required=False, connected=False, error="x")
        assert s_required.required is True
        assert s_optional.required is False

    def test_frozen(self) -> None:
        """frozen=True → 不能修改."""
        import dataclasses

        s = McpServerStatus(name="fs", required=False, connected=True)
        # replace 创建新对象, 原对象不变(frozen)
        new_s = dataclasses.replace(s, connected=False)
        assert new_s.connected is False
        assert s.connected is True  # 原对象不变


class TestMcpErrorSurface:
    def test_5_fields(self) -> None:
        e = McpErrorSurface(
            phase=LifecyclePhase.CONNECT,
            server="calendar",
            message="stdio broken",
            context={"exc_type": "MCPConnectionError"},
            recoverable=True,
        )
        assert e.phase == LifecyclePhase.CONNECT
        assert e.server == "calendar"
        assert e.message == "stdio broken"
        assert e.context == {"exc_type": "MCPConnectionError"}
        assert e.recoverable is True

    def test_to_dict_serializes_phase_as_string(self) -> None:
        e = McpErrorSurface(
            phase=LifecyclePhase.CONNECT, server="cal", message="x", recoverable=False
        )
        d = e.to_dict()
        assert d["phase"] == "connect"  # 枚举转字符串
        assert d["server"] == "cal"
        assert d["recoverable"] is False


class TestMcpDegradedReport:
    def test_empty_is_healthy(self) -> None:
        """空 report = 完全健康(无失败)."""
        r = McpDegradedReport()
        assert r.is_healthy is True
        assert r.is_degraded is False

    def test_with_failures_is_degraded(self) -> None:
        r = McpDegradedReport(failed=["fs"], available_tools={"read_file"})
        assert r.is_healthy is False
        assert r.is_degraded is True

    def test_with_missing_tools_not_healthy(self) -> None:
        r = McpDegradedReport(missing_tools={"create_event"})
        assert r.is_healthy is False
        assert r.is_degraded is False  # 没失败, 但有 missing

    def test_to_dict_converts_set_to_sorted_list(self) -> None:
        """set 字段转 sorted list, 保持序列化稳定性."""
        r = McpDegradedReport(
            working=["cal"],
            failed=["fs"],
            available_tools={"create_event", "read_file"},
            missing_tools={"write_file"},
        )
        d = r.to_dict()
        assert d["available_tools"] == ["create_event", "read_file"]  # sorted
        assert d["missing_tools"] == ["write_file"]
        assert d["is_healthy"] is False
        assert d["is_degraded"] is True
        assert d["errors"] == []

    def test_to_dict_serializes_errors(self) -> None:
        e = McpErrorSurface(
            phase=LifecyclePhase.CONNECT, server="fs", message="timeout", recoverable=True
        )
        r = McpDegradedReport(failed=["fs"], errors=[e])
        d = r.to_dict()
        assert len(d["errors"]) == 1
        assert d["errors"][0]["phase"] == "connect"
        assert d["errors"][0]["recoverable"] is True
