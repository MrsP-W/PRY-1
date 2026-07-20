"""MCP (Model Context Protocol) 客户端抽象层 — D4.2.

参考 claw-code docs/g007-mcp-lifecycle-mapping.md 架构原则:
  - Degraded startup: discover_servers() 单 server 失败不阻塞
  - Required vs Optional: 必填失败 → abort, 可选失败 → degraded report
  - McpErrorSurface 5 字段: phase + server + message + context + recoverability
  - McpDegradedReport 4 段: working + failed + available_tools + missing_tools
  - Lifecycle: connect() / disconnect() (Python 协议,无 command 数组)

参考 D3.3.3 + D4.1 教训("异常范围要窄化"):
  - 4 类业务异常(MCPTimeoutError / MCPConnectionError / MCPProtocolError /
    MCPResponseError), 编程错误(ValueError/TypeError) 透传
  - 决策点(client) 只接 MCPError, 不 catch-all

D4.2 范围: 抽象层 + DegradedReport + 4 类异常 + Required flag 决策
不接真实 MCP server(全 MockTransport), 见 docs/d4-claw-code-mapping.md §2.
"""

from .client import MCPClient
from .discovery import discover_servers, get_server_config
from .exceptions import (
    MCPConnectionError,
    MCPError,
    MCPProtocolError,
    MCPResponseError,
    MCPTimeoutError,
)
from .report import (
    LifecyclePhase,
    McpDegradedReport,
    McpErrorSurface,
    McpServerStatus,
)
from .transport import MockTransport, StdioTransport, Transport

__all__ = [
    # 客户端
    "MCPClient",
    # 异常(4 类业务异常 + 基类)
    "MCPConnectionError",
    "MCPError",
    "MCPProtocolError",
    "MCPResponseError",
    "MCPTimeoutError",
    # 报告
    "LifecyclePhase",
    "McpDegradedReport",
    "McpErrorSurface",
    "McpServerStatus",
    # Transport
    "MockTransport",
    "StdioTransport",
    "Transport",
    # Discovery
    "discover_servers",
    "get_server_config",
]
