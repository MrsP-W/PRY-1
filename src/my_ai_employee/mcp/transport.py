"""MCP Transport 抽象 — 参考 g007 stdio/SSE 模式(本项目暂不绑死协议).

设计: Transport 是 MCPClient 与 server 进程之间的字节流抽象.
- 真实场景: stdio(JSON-RPC over stdin/stdout) / SSE
- D4.2: MockTransport 用于测试, 注入可控的成功/超时/协议错/响应错
- 不绑死具体协议: 子类化 Transport, 实现 start()/send()/close() 即可
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from .exceptions import (
    MCPConnectionError,
    MCPProtocolError,
    MCPResponseError,
    MCPTimeoutError,
)


@dataclass
class Transport(abc.ABC):
    """MCP Transport 抽象基类.

    Attributes:
        server_name: server 名(用于错误日志)
        connected: 是否已连接
    """

    server_name: str
    connected: bool = False
    _send_log: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    @abc.abstractmethod
    def start(self) -> None:
        """启动 transport(子进程启动 / SSE 握手).

        Raises:
            MCPTimeoutError: 启动超时
            MCPConnectionError: 启动失败
        """

    @abc.abstractmethod
    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        """发请求 → 收响应(JSON-RPC 风格).

        Args:
            request: JSON-RPC 请求 dict(method + params + id)

        Returns:
            JSON-RPC 响应 dict(result + id)

        Raises:
            MCPTimeoutError: 调用超时
            MCPConnectionError: 连接断开
            MCPProtocolError: 协议错(响应非 JSON-RPC 风格)
            MCPResponseError: 响应结构错(缺 result 字段)
        """

    @abc.abstractmethod
    def close(self) -> None:
        """关闭 transport(子进程结束 / SSE 断开)."""


# === Mock 实现(测试用, 无外部依赖) ===


class MockTransport(Transport):
    """可注入行为的 Mock Transport — 类比 respx 模式.

    用法:
        t = MockTransport(server_name="fs", tools=["read_file"])
        t.start()  # connected=True
        resp = t.send({"method": "tools/list", "id": 1})
        assert resp["result"]["tools"] == ["read_file"]

    注入失败:
        t.start_failure = MCPTimeoutError("simulated")
        t.call_failure = MCPConnectionError("simulated")
        t.call_protocol_error = True
        t.call_response_error = True
    """

    def __init__(
        self,
        server_name: str,
        tools: list[str] | None = None,
        start_timeout: float = 0.0,
    ) -> None:
        super().__init__(server_name=server_name)
        self._tools = tools or []
        self._start_timeout = start_timeout
        # 注入失败点(默认无失败)
        self.start_failure: Exception | None = None
        self.call_failure: Exception | None = None
        self.call_protocol_error: bool = False  # 响应非 dict
        self.call_response_error: bool = False  # 缺 result 字段
        self.call_timeout: bool = False

    def start(self) -> None:
        if self.start_failure is not None:
            raise self.start_failure
        if self._start_timeout > 0:
            import time as _t

            _t.sleep(self._start_timeout)
        self.connected = True

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.connected:
            raise MCPConnectionError(f"MockTransport {self.server_name} 未连接")
        self._send_log.append(request)
        # 注入失败
        if self.call_timeout:
            raise MCPTimeoutError(f"MockTransport {self.server_name} 调用超时")
        if self.call_failure is not None:
            raise self.call_failure
        if self.call_protocol_error:
            # 协议错: 响应不是 dict(模拟 transport 层抛协议错)
            raise MCPProtocolError(f"MockTransport {self.server_name} 协议错: 响应非 dict")
        if self.call_response_error:
            # 响应结构错: 缺 result(模拟 transport 层抛响应错)
            raise MCPResponseError(f"MockTransport {self.server_name} 响应错: 缺 result 字段")
        # 正常: 按 method 路由
        method = request.get("method", "")
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {"tools": [{"name": t} for t in self._tools]},
            }
        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "result": {"content": [{"type": "text", "text": f"called {method}"}]},
            }
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {},
        }

    def close(self) -> None:
        self.connected = False

    # 辅助方法
    @property
    def send_log(self) -> list[dict[str, Any]]:
        return list(self._send_log)

    @contextmanager
    def use(self) -> Iterator[MockTransport]:
        """测试用: 启动 + 退出自动关闭."""
        self.start()
        try:
            yield self
        finally:
            self.close()
