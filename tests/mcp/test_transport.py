"""D4.2 — Transport 抽象 + MockTransport 注入行为测试.

覆盖:
  - MockTransport start() 成功
  - MockTransport 注入失败: start_failure / call_timeout / call_failure /
    call_protocol_error / call_response_error
  - MockTransport send_log 记录请求
  - MockTransport use() context manager
  - 未连接时 send() 抛 MCPConnectionError
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.mcp.exceptions import (  # noqa: E402
    MCPConnectionError,
    MCPProtocolError,
    MCPResponseError,
    MCPTimeoutError,
)
from my_ai_employee.mcp.transport import MockTransport  # noqa: E402


class TestMockTransportStart:
    def test_start_success(self) -> None:
        t = MockTransport(server_name="fs", tools=["read_file"])
        assert t.connected is False
        t.start()
        assert t.connected is True

    def test_start_with_injected_failure(self) -> None:
        t = MockTransport(server_name="fs")
        t.start_failure = MCPConnectionError("simulated start fail")
        with pytest.raises(MCPConnectionError, match="simulated"):
            t.start()
        assert t.connected is False

    def test_start_with_timeout(self) -> None:
        t = MockTransport(server_name="fs", start_timeout=0.05)
        t.start_failure = MCPTimeoutError("simulated start timeout")
        with pytest.raises(MCPTimeoutError):
            t.start()


class TestMockTransportSend:
    def test_send_tools_list(self) -> None:
        t = MockTransport(server_name="fs", tools=["read_file", "write_file"])
        t.start()
        resp = t.send({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"]["tools"] == [{"name": "read_file"}, {"name": "write_file"}]

    def test_send_tools_call(self) -> None:
        t = MockTransport(server_name="fs", tools=["read_file"])
        t.start()
        resp = t.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "read_file", "arguments": {}},
            }
        )
        assert resp["result"]["content"][0]["text"] == "called tools/call"

    def test_send_unconnected_raises_connection_error(self) -> None:
        t = MockTransport(server_name="fs")
        # 不 start
        with pytest.raises(MCPConnectionError, match="未连接"):
            t.send({"method": "tools/list"})

    def test_send_injected_timeout(self) -> None:
        t = MockTransport(server_name="fs")
        t.start()
        t.call_timeout = True
        with pytest.raises(MCPTimeoutError, match="调用超时"):
            t.send({"method": "tools/list"})

    def test_send_injected_connection_failure(self) -> None:
        t = MockTransport(server_name="fs")
        t.start()
        t.call_failure = MCPConnectionError("simulated call fail")
        with pytest.raises(MCPConnectionError, match="simulated call"):
            t.send({"method": "tools/list"})

    def test_send_injected_protocol_error(self) -> None:
        t = MockTransport(server_name="fs")
        t.start()
        t.call_protocol_error = True
        with pytest.raises(MCPProtocolError):
            t.send({"method": "tools/list"})

    def test_send_injected_response_error(self) -> None:
        t = MockTransport(server_name="fs")
        t.start()
        t.call_response_error = True
        with pytest.raises(MCPResponseError, match="缺 result"):
            t.send({"method": "tools/list"})


class TestMockTransportContextManager:
    def test_use_context_manager(self) -> None:
        t = MockTransport(server_name="fs", tools=["read_file"])
        with t.use() as m:
            assert m.connected is True
            resp = m.send({"method": "tools/list", "id": 1})
            assert "result" in resp
        # 退出 context 后自动 close
        assert t.connected is False


class TestSendLog:
    def test_send_log_records_all_requests(self) -> None:
        t = MockTransport(server_name="fs", tools=["x"])
        t.start()
        t.send({"method": "tools/list", "id": 1})
        t.send({"method": "tools/call", "id": 2, "params": {"name": "x"}})
        assert len(t.send_log) == 2
        assert t.send_log[0]["method"] == "tools/list"
        assert t.send_log[1]["method"] == "tools/call"
