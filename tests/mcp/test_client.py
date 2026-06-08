"""D4.2 — MCPClient connect/disconnect/call_tool + 重试 + 4 类业务异常测试.

覆盖:
  - connect() 成功 + 拉 tools
  - connect() 启动失败抛 MCPError(透传)
  - connect() 协议错抛 MCPProtocolError
  - connect() 响应错抛 MCPResponseError
  - disconnect() 幂等
  - call_tool() 成功
  - call_tool() 超时重试(recoverable=True)
  - call_tool() 协议错不重试(recoverable=False)
  - call_tool() 工具名不在列表 → ValueError(编程错误透传)
  - error_surface() 5 字段构造
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.mcp.client import MCPClient  # noqa: E402
from my_ai_employee.mcp.exceptions import (  # noqa: E402
    MCPConnectionError,
    MCPProtocolError,
    MCPResponseError,
    MCPTimeoutError,
)
from my_ai_employee.mcp.report import LifecyclePhase  # noqa: E402
from my_ai_employee.mcp.transport import MockTransport  # noqa: E402


class TestConnect:
    def test_connect_success(self) -> None:
        t = MockTransport(server_name="fs", tools=["read_file", "write_file"])
        client = MCPClient(server_name="fs", transport=t)
        client.connect()
        assert t.connected is True
        assert client.tools == ["read_file", "write_file"]

    def test_connect_idempotent(self) -> None:
        t = MockTransport(server_name="fs", tools=["x"])
        client = MCPClient(server_name="fs", transport=t)
        client.connect()
        client.connect()  # 第二次幂等
        assert t.connected is True
        # send_log 只记录 1 次 initialize + 1 次 tools/list(不重复)
        # initialize 和 tools/list 都被 send 了 1 次
        assert len(t.send_log) == 2

    def test_connect_start_failure_propagates(self) -> None:
        t = MockTransport(server_name="fs")
        t.start_failure = MCPConnectionError("process spawn failed")
        client = MCPClient(server_name="fs", transport=t)
        with pytest.raises(MCPConnectionError, match="process spawn failed"):
            client.connect()
        assert t.connected is False

    def test_connect_protocol_error_closes_transport(self) -> None:
        """protocol error 在 initialize 时 → 关闭 transport + 抛."""
        t = MockTransport(server_name="fs")
        t.start()
        t.call_protocol_error = True  # initialize 响应非 dict
        t.connected = False  # 重置让 connect() 走完完整流程
        client = MCPClient(server_name="fs", transport=t)
        with pytest.raises(MCPProtocolError):
            client.connect()
        # 失败时 transport 应关闭
        assert t.connected is False

    def test_connect_response_error_closes_transport(self) -> None:
        t = MockTransport(server_name="fs")
        t.start()
        t.call_response_error = True  # initialize 响应缺 result
        t.connected = False  # 重置让 connect() 走完完整流程
        client = MCPClient(server_name="fs", transport=t)
        with pytest.raises(MCPResponseError):
            client.connect()
        assert t.connected is False

    def test_connect_initialize_malformed_non_dict_closes_transport(self) -> None:
        """D4.2.1 修复 regression: initialize 返回非 dict (transport 不抛,
        由 _validate_response 抛) → transport 应关闭."""
        t = MockTransport(server_name="fs")
        t.start()
        t.call_malformed_response = "non_dict"  # 返回 list
        t.connected = False
        client = MCPClient(server_name="fs", transport=t)
        with pytest.raises(MCPProtocolError):
            client.connect()
        # 关键: 校验失败后 transport 仍被关闭
        assert t.connected is False

    def test_connect_initialize_malformed_missing_result_closes_transport(self) -> None:
        """D4.2.1 修复 regression: initialize 返回 dict 但缺 result
        (transport 不抛, 由 _validate_response 抛) → transport 应关闭."""
        t = MockTransport(server_name="fs")
        t.start()
        t.call_malformed_response = "missing_result"  # 返回 dict 无 result
        t.connected = False
        client = MCPClient(server_name="fs", transport=t)
        with pytest.raises(MCPResponseError):
            client.connect()
        assert t.connected is False

    def test_connect_tools_list_malformed_closes_transport(self) -> None:
        """D4.2.2 修复 regression: initialize 正常, tools/list 返回坏值
        → transport 应关闭 + 抛 MCPResponseError."""
        t = MockTransport(server_name="fs", tools=["read_file"])
        t.start()
        # initialize 正常返回, tools/list 返回 dict 但缺 result
        t.call_malformed_response = "missing_result"
        t.malformed_methods = {"tools/list"}  # 只对 tools/list 注入
        t.connected = False
        client = MCPClient(server_name="fs", transport=t)
        with pytest.raises(MCPResponseError):
            client.connect()
        # 关键: tools/list 阶段失败后 transport 仍被关闭
        assert t.connected is False
        # 验证 send_log 含 1 次 initialize (成功) + 1 次 tools/list (失败)
        methods = [r.get("method") for r in t._send_log]
        assert methods == ["initialize", "tools/list"]


class TestDisconnect:
    def test_disconnect_success(self) -> None:
        t = MockTransport(server_name="fs")
        client = MCPClient(server_name="fs", transport=t)
        client.connect()
        client.disconnect()
        assert t.connected is False

    def test_disconnect_idempotent(self) -> None:
        t = MockTransport(server_name="fs")
        client = MCPClient(server_name="fs", transport=t)
        client.disconnect()  # 未连接也 OK
        client.disconnect()


class TestCallTool:
    def test_call_tool_success(self) -> None:
        t = MockTransport(server_name="fs", tools=["read_file"])
        client = MCPClient(server_name="fs", transport=t)
        client.connect()
        result = client.call_tool("read_file", arguments={"path": "/tmp/x"})
        assert "content" in result

    def test_call_tool_unknown_raises_value_error(self) -> None:
        """工具名不在列表 → ValueError(编程错误透传, D3.3.3 教训)."""
        t = MockTransport(server_name="fs", tools=["read_file"])
        client = MCPClient(server_name="fs", transport=t)
        client.connect()
        with pytest.raises(ValueError, match="不在 server"):
            client.call_tool("unknown_tool")

    def test_call_tool_retries_on_timeout(self) -> None:
        """recoverable=True (timeout) → 重试 max_retries 次."""
        t = MockTransport(server_name="fs", tools=["read_file"])
        client = MCPClient(server_name="fs", transport=t, max_retries=2, retry_backoff=0.0)
        client.connect()
        # 清空 connect 期间的 send_log, 只关注 call_tool 重试
        t._send_log.clear()
        # 前 2 次超时, 第 3 次成功(MockTransport 无内置重试逻辑,
        # 我们需要让 call_timeout 在前 2 次为 True, 之后为 False)
        # 用 side_effect 模式: 这里用更简单方法 - 让所有 send 都失败
        t.call_timeout = True
        with pytest.raises(MCPTimeoutError):
            client.call_tool("read_file")
        # 重试 2 次 + 第 3 次最终失败 = 3 次 send
        # send_log 现在含 1 次 initialize + 1 次 tools/list + 3 次 call_tool
        call_count = sum(1 for r in t._send_log if r.get("method") == "tools/call")
        assert call_count == 3  # max_retries=2 + 第 3 次最终尝试

    def test_call_tool_does_not_retry_on_protocol_error(self) -> None:
        """recoverable=False (protocol error) → 不重试, 直接抛."""
        t = MockTransport(server_name="fs", tools=["read_file"])
        client = MCPClient(server_name="fs", transport=t, max_retries=2, retry_backoff=0.0)
        client.connect()
        t._send_log.clear()
        t.call_protocol_error = True
        with pytest.raises(MCPProtocolError):
            client.call_tool("read_file")
        call_count = sum(1 for r in t._send_log if r.get("method") == "tools/call")
        assert call_count == 1  # 不重试, 只 1 次

    def test_call_tool_does_not_retry_on_response_error(self) -> None:
        """recoverable=False (response error) → 不重试."""
        t = MockTransport(server_name="fs", tools=["read_file"])
        client = MCPClient(server_name="fs", transport=t, max_retries=2, retry_backoff=0.0)
        client.connect()
        t._send_log.clear()
        t.call_response_error = True
        with pytest.raises(MCPResponseError):
            client.call_tool("read_file")
        call_count = sum(1 for r in t._send_log if r.get("method") == "tools/call")
        assert call_count == 1


class TestErrorSurface:
    def test_error_surface_5_fields(self) -> None:
        t = MockTransport(server_name="fs")
        client = MCPClient(server_name="fs", transport=t)
        e = client.error_surface(LifecyclePhase.CONNECT, MCPConnectionError("stdio broken"))
        assert e.phase == LifecyclePhase.CONNECT
        assert e.server == "fs"
        assert e.message == "stdio broken"
        assert e.context == {"exc_type": "MCPConnectionError"}
        assert e.recoverable is True  # ConnectionError 是 recoverable

    def test_error_surface_protocol_not_recoverable(self) -> None:
        t = MockTransport(server_name="fs")
        client = MCPClient(server_name="fs", transport=t)
        e = client.error_surface(LifecyclePhase.CALL, MCPProtocolError("bad method"))
        assert e.recoverable is False
