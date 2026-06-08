"""MCP Client — connect/disconnect/call_tool 生命周期 + 重试 + 4 类业务异常透传.

参考 g007-mcp-lifecycle-mapping.md:
  - connect() 启动 transport + initialize 协议
  - disconnect() 关闭 transport
  - call_tool() 发 JSON-RPC 请求 + 重试(recoverable 错误)

D3.3.3 + D4.1 教训应用:
  - 4 类业务异常窄化(MCPTimeoutError / MCPConnectionError /
    MCPProtocolError / MCPResponseError)
  - 编程错误(ValueError/TypeError) 透传
  - 重试只针对 recoverable=True 的错误(超时/连接断), 协议错/响应错不重试
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .exceptions import (
    MCPConnectionError,
    MCPError,
    MCPProtocolError,
    MCPResponseError,
    MCPTimeoutError,
)
from .report import LifecyclePhase, McpErrorSurface
from .transport import Transport


@dataclass
class MCPClient:
    """MCP 客户端基类.

    Attributes:
        server_name: server 名
        transport: Transport 实例(注入)
        max_retries: call_tool 可重试次数(recoverable 错误)
        retry_backoff: 重试退避基数(秒, 线性 backoff = n * retry_backoff)
        call_timeout: 单次 call_tool 超时(秒, 0 = 不超时)
        tools: 连接的 server 暴露的工具列表
        _state: 内部状态机 IDLE → CONNECTED → CLOSED
    """

    server_name: str
    transport: Transport
    max_retries: int = 2
    retry_backoff: float = 0.05
    call_timeout: float = 0.0
    tools: list[str] = field(default_factory=list, init=False)

    def connect(self) -> None:
        """连接 + 初始化.

        流程:
          1. transport.start() — 启动进程
          2. send initialize — MCP 协议握手
          3. send tools/list — 拉工具清单

        异常: 4 类业务异常透传(由调用方决定 degraded vs abort)
        失败时: 任何阶段抛 MCPError → 关闭 transport(D4.2.1 修复)
        """
        if self.transport.connected:
            return  # 幂等
        try:
            self.transport.start()
        except MCPError:
            raise  # 透传业务异常
        # initialize 协议(JSON-RPC initialize) + 校验
        # send + validate 包在同一个 try 里, 任何异常都关闭 transport
        try:
            init_resp = self.transport.send(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"},
                }
            )
            self._validate_response(init_resp, method="initialize")
        except MCPError:
            self.transport.close()
            raise
        # tools/list + 校验(同上)
        try:
            tools_resp = self.transport.send(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
            )
            self._validate_response(tools_resp, method="tools/list")
        except MCPError:
            self.transport.close()
            raise
        # 解析工具列表
        self.tools = [
            t.get("name", "")  # type: ignore[union-attr]
            for t in tools_resp.get("result", {}).get("tools", [])  # type: ignore[union-attr]
        ]

    def disconnect(self) -> None:
        """断开连接(幂等)."""
        if not self.transport.connected:
            return
        self.transport.close()

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用工具 + 重试(recoverable 错误).

        Args:
            name: 工具名
            arguments: 工具参数

        Returns:
            工具响应 dict(result.content)

        Raises:
            MCPTimeoutError: 超时(已用尽重试)
            MCPConnectionError: 连接断(已用尽重试)
            MCPProtocolError: 协议错(不重试, 直接抛)
            MCPResponseError: 响应结构错(不重试, 直接抛)
            ValueError: 编程错误(name 不在 tools 列表, 透传)
        """
        if name not in self.tools:
            raise ValueError(
                f"工具 {name!r} 不在 server {self.server_name!r} 的 {self.tools!r} 列表中"
            )
        request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        last_error: MCPError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.transport.send(request)
                self._validate_response(resp, method="tools/call")
                result: dict[str, Any] = resp.get("result", {})  # type: ignore[assignment]
                return result
            except (MCPTimeoutError, MCPConnectionError) as e:
                # 可恢复: 重试
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff * (attempt + 1))
                    continue
                raise
            except (MCPProtocolError, MCPResponseError):
                # 不可恢复: 不重试, 直接抛
                raise
        # 防御性: 循环结束但没抛错(逻辑不该到这里)
        if last_error:
            raise last_error
        raise RuntimeError("call_tool unreachable")

    def _validate_response(self, resp: Any, method: str) -> None:
        """校验 JSON-RPC 响应结构.

        Raises:
            MCPProtocolError: 响应不是 dict
            MCPResponseError: 响应缺 result 或 result 缺 tools
        """
        if not isinstance(resp, dict):
            raise MCPProtocolError(f"响应不是 dict(method={method}, type={type(resp).__name__})")
        if "result" not in resp:
            raise MCPResponseError(f"响应缺 result 字段(method={method}, resp={resp!r})")
        # initialize/tools/list 还要校验 result 结构
        if method in ("tools/list", "initialize"):
            result = resp.get("result", {})
            if not isinstance(result, dict):
                raise MCPResponseError(
                    f"result 不是 dict(method={method}, type={type(result).__name__})"
                )

    def error_surface(self, phase: LifecyclePhase, exc: MCPError) -> McpErrorSurface:
        """把业务异常转 McpErrorSurface(给 discovery 聚合)."""
        return McpErrorSurface(
            phase=phase,
            server=self.server_name,
            message=str(exc),
            context={"exc_type": type(exc).__name__},
            recoverable=isinstance(exc, (MCPTimeoutError, MCPConnectionError)),
        )
