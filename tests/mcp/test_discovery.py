"""D4.2 — discover_servers 关键 regression 测试.

参考 g007: `manager_discovery_report_keeps_healthy_servers_when_one_server_fails`
本测试是 D4.2 关键 regression: 单个 server 失败不阻塞其他 server.

覆盖:
  - 全成功: 所有 server 加入 working, report.is_healthy=True
  - 1 个可选 server 失败: 失败降级, 其他 server 仍 connected
  - 必填 server 失败: 抛 MCPError, 已连 server 全部关闭
  - 失败 server 的 expected_tools 进入 missing_tools
  - 失败 server 的 MCPError → McpErrorSurface
  - 重置 DEFAULT_SERVERS(避免污染其他测试)
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Generator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.mcp import discovery  # noqa: E402
from my_ai_employee.mcp.discovery import (  # noqa: E402
    ServerConfig,
    discover_servers,
)
from my_ai_employee.mcp.exceptions import MCPConnectionError, MCPTimeoutError  # noqa: E402
from my_ai_employee.mcp.report import LifecyclePhase  # noqa: E402
from my_ai_employee.mcp.transport import MockTransport  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_default_servers() -> Generator[None, None, None]:
    """每个测试后重置 DEFAULT_SERVERS(避免污染)."""
    yield
    # 重置为原始 DEFAULT_SERVERS
    discovery.DEFAULT_SERVERS = {
        "filesystem": ServerConfig(
            name="filesystem",
            required=False,
            transport_factory=lambda: MockTransport(server_name="filesystem", tools=["read_file"]),
            expected_tools=["read_file"],
        ),
        "calendar": ServerConfig(
            name="calendar",
            required=True,
            transport_factory=lambda: MockTransport(server_name="calendar", tools=["create_event"]),
            expected_tools=["create_event"],
        ),
    }


def _make_failing_factory(failure: Exception) -> Callable[[], MockTransport]:
    """构造一个 start 时抛指定异常的 factory."""

    def factory() -> MockTransport:
        t = MockTransport(server_name="broken")
        t.start_failure = failure
        return t

    return factory


def _make_raising_factory(failure: MCPConnectionError) -> Callable[[], MockTransport]:
    """构造一个在创建 transport 时直接抛业务异常的 factory."""

    def factory() -> MockTransport:
        raise failure

    return factory


def _make_working_factory(server_name: str, tools: list[str]) -> Callable[[], MockTransport]:
    def factory() -> MockTransport:
        return MockTransport(server_name=server_name, tools=tools)

    return factory


class _CloseFailingTransport(MockTransport):
    """模拟已连接 client 在 cleanup 时抛编程异常。"""

    def __init__(self, server_name: str, tools: list[str]) -> None:
        super().__init__(server_name=server_name, tools=tools)
        self.close_attempted = False

    def close(self) -> None:
        self.close_attempted = True
        raise RuntimeError("cleanup programming failure")


class TestDiscoverAllSuccess:
    def test_all_servers_connected(self) -> None:
        """全成功: 所有 server connected, report.is_healthy=True."""
        discovery.DEFAULT_SERVERS = {
            "fs": ServerConfig(
                name="fs",
                required=False,
                transport_factory=_make_working_factory("fs", ["read_file"]),
                expected_tools=["read_file"],
            ),
            "cal": ServerConfig(
                name="cal",
                required=True,
                transport_factory=_make_working_factory("cal", ["create_event"]),
                expected_tools=["create_event"],
            ),
        }
        clients, report = discover_servers()
        assert set(clients.keys()) == {"fs", "cal"}
        assert report.working == ["fs", "cal"]
        assert report.failed == []
        assert report.is_healthy is True
        assert report.is_degraded is False
        assert report.available_tools == {"read_file", "create_event"}
        # 清理
        for c in clients.values():
            c.disconnect()


class TestDiscoverOptionalFailure:
    """关键 regression: 1 个可选 server 失败, 其他 server 仍 connected."""

    def test_keeps_healthy_servers_when_optional_fails(self) -> None:
        """factory 创建失败也不阻断健康 server（g007 关键 regression Python 版）."""
        discovery.DEFAULT_SERVERS = {
            "fs_optional_failing": ServerConfig(
                name="fs_optional_failing",
                required=False,  # 可选
                transport_factory=_make_raising_factory(MCPConnectionError("fs broken")),
                expected_tools=["read_file"],
            ),
            "cal_working": ServerConfig(
                name="cal_working",
                required=True,  # 必填(但成功)
                transport_factory=_make_working_factory("cal_working", ["create_event"]),
                expected_tools=["create_event"],
            ),
        }
        clients, report = discover_servers()
        # 关键: 健康的 cal_working 仍然 connected
        assert "cal_working" in clients
        assert clients["cal_working"].transport.connected is True
        # 失败的 fs_optional_failing 在 failed list
        assert "fs_optional_failing" in report.failed
        assert "cal_working" in report.working
        # missing_tools 含 fs 的 expected_tools
        assert "read_file" in report.missing_tools
        assert "create_event" in report.available_tools
        # 至少 1 个 error surface
        assert len(report.errors) == 1
        assert report.errors[0].server == "fs_optional_failing"
        assert report.errors[0].phase == LifecyclePhase.DISCOVERY
        # 清理
        for c in clients.values():
            c.disconnect()

    def test_multiple_optional_failures_aggregate(self) -> None:
        """多个可选失败 → 都进 failed, 健康 server 不受影响."""
        discovery.DEFAULT_SERVERS = {
            "fs1_fail": ServerConfig(
                name="fs1_fail",
                required=False,
                transport_factory=_make_failing_factory(MCPConnectionError("fs1")),
                expected_tools=["read_file"],
            ),
            "fs2_fail": ServerConfig(
                name="fs2_fail",
                required=False,
                transport_factory=_make_failing_factory(MCPTimeoutError("fs2")),
                expected_tools=["write_file"],
            ),
            "cal_ok": ServerConfig(
                name="cal_ok",
                required=True,
                transport_factory=_make_working_factory("cal_ok", ["create_event"]),
                expected_tools=["create_event"],
            ),
        }
        clients, report = discover_servers()
        assert set(report.failed) == {"fs1_fail", "fs2_fail"}
        assert report.working == ["cal_ok"]
        assert report.missing_tools == {"read_file", "write_file"}
        assert len(report.errors) == 2
        # 清理
        for c in clients.values():
            c.disconnect()


class TestDiscoverRequiredFailure:
    """必填 server 失败 → 抛 MCPError(让启动 abort)."""

    def test_required_failure_raises(self) -> None:
        discovery.DEFAULT_SERVERS = {
            "fs_optional_ok": ServerConfig(
                name="fs_optional_ok",
                required=False,
                transport_factory=_make_working_factory("fs_optional_ok", ["read_file"]),
                expected_tools=["read_file"],
            ),
            "cal_required_failing": ServerConfig(
                name="cal_required_failing",
                required=True,  # 必填
                transport_factory=_make_failing_factory(MCPConnectionError("cal down")),
                expected_tools=["create_event"],
            ),
        }
        with pytest.raises(MCPConnectionError, match="cal down"):
            discover_servers()
        # 关键: 已连的 fs_optional_ok 应被关闭
        # (此处无法直接验证, 因为 clients 字典在内部被清理)
        # 但 report 没机会返回, 抛错就是抛错

    def test_required_factory_failure_cleanup_is_best_effort(self) -> None:
        """cleanup 异常不掩盖必填失败，且仍继续关闭其余 client。"""
        close_failing_transport = _CloseFailingTransport(
            server_name="first_optional",
            tools=["read_file"],
        )
        healthy_transport = MockTransport(
            server_name="second_optional",
            tools=["write_file"],
        )
        discovery.DEFAULT_SERVERS = {
            "first_optional": ServerConfig(
                name="first_optional",
                required=False,
                transport_factory=lambda: close_failing_transport,
                expected_tools=["read_file"],
            ),
            "second_optional": ServerConfig(
                name="second_optional",
                required=False,
                transport_factory=lambda: healthy_transport,
                expected_tools=["write_file"],
            ),
            "required_failing": ServerConfig(
                name="required_failing",
                required=True,
                transport_factory=_make_raising_factory(MCPConnectionError("required down")),
                expected_tools=["create_event"],
            ),
        }

        with pytest.raises(MCPConnectionError, match="required down"):
            discover_servers()

        assert close_failing_transport.close_attempted is True
        assert healthy_transport.connected is False


class TestDiscoverErrorSurface:
    """失败 server 的 MCPError → McpErrorSurface(5 字段)."""

    def test_error_surface_captures_failure(self) -> None:
        discovery.DEFAULT_SERVERS = {
            "fs_fail": ServerConfig(
                name="fs_fail",
                required=False,
                transport_factory=_make_failing_factory(MCPConnectionError("sim fail")),
                expected_tools=["read_file"],
            ),
            "cal_ok": ServerConfig(
                name="cal_ok",
                required=True,
                transport_factory=_make_working_factory("cal_ok", ["create_event"]),
                expected_tools=["create_event"],
            ),
        }
        clients, report = discover_servers()
        assert len(report.errors) == 1
        e = report.errors[0]
        assert e.server == "fs_fail"
        assert e.phase == LifecyclePhase.CONNECT
        assert "sim fail" in e.message
        assert e.recoverable is True  # ConnectionError 是 recoverable
        assert e.context["exc_type"] == "MCPConnectionError"
        # 清理
        for c in clients.values():
            c.disconnect()


class TestDiscoverGetServerConfig:
    def test_get_existing(self) -> None:
        cfg = discovery.get_server_config("filesystem")
        assert cfg.name == "filesystem"
        assert cfg.required is False

    def test_get_missing_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="not_exist"):
            discovery.get_server_config("not_exist")
