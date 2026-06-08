"""MCP 4 类业务异常(D3.3.3 + D4.1 教训落地).

参考 D3.3.3: "异常范围要窄化到真要处理的类型"
参考 D4.1: 4 类业务异常基类 + 编程错误透传
参考 g007-mcp-lifecycle-mapping.md: McpErrorSurface 5 字段思想

异常分层:
  MCPTimeoutError    # 连接/调用超时 → 触发 reconnect / 跳过 server
  MCPConnectionError # 进程启动失败 / stdio 断开 → 触发 reconnect
  MCPProtocolError   # JSON-RPC 协议违反(method 错 / params 错) → server 配置问题
  MCPResponseError   # 响应解析失败 / 缺字段 / 字段类型错

编程错误(ValueError / TypeError / KeyError 在参数上) → 透传, 不包装.
"""

from __future__ import annotations


class MCPError(Exception):
    """MCP 业务异常基类."""


class MCPTimeoutError(MCPError):
    """连接/调用超时(进程启动超时 / call_tool 响应超时)."""


class MCPConnectionError(MCPError):
    """进程启动失败 / stdio 断开 / 握手失败."""


class MCPProtocolError(MCPError):
    """JSON-RPC 协议违反(method 不存在 / params 错 / 状态错).

    通常是 server 实现问题(不是网络问题), 走 degraded report 不重试.
    """


class MCPResponseError(MCPError):
    """响应解析失败(非 JSON / 缺 result 字段 / 字段类型错)."""
