"""MCP Server Discovery — 参考 g007 discover_tools_best_effort 模式.

参考 g007-mcp-lifecycle-mapping.md:
  - discover_servers() 单 server 失败不阻塞
  - 必填 server 失败 → 抛 MCPError(让启动 abort)
  - 可选 server 失败 → 进入 degraded report
  - 关键 regression: `manager_discovery_report_keeps_healthy_servers_when_one_fails`

设计:
  - Server config 用硬编码 dict(暂不读 JSON, D4.2 不接真实 server)
  - 每个 server 配置含 name + required + transport_factory
  - discover_servers() 遍历 config → 建 client → connect()
    - 成功 → 加入 working list
    - 失败 + required=True → 抛 MCPError(启动 abort)
    - 失败 + required=False → 加入 degraded report
  - 返回 McpDegradedReport
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .client import MCPClient
from .exceptions import MCPConnectionError, MCPError, MCPTimeoutError
from .report import LifecyclePhase, McpDegradedReport, McpErrorSurface
from .transport import Transport


@dataclass(frozen=True)
class ServerConfig:
    """MCP server 配置(硬编码, 后续可改 JSON 加载).

    Attributes:
        name: server 名
        required: True → 失败 abort, False → 失败降级
        transport_factory: 工厂函数, 调用返回 Transport 实例
        expected_tools: 期望工具列表(用于 missing_tools 报告)
    """

    name: str
    required: bool
    transport_factory: Callable[[], Transport]
    expected_tools: list[str] = None  # type: ignore[assignment]


# === 默认配置(测试 / 开发用) ===

DEFAULT_SERVERS: dict[str, ServerConfig] = {
    "filesystem": ServerConfig(
        name="filesystem",
        required=False,  # 可选: 邮件分类不需要文件
        transport_factory=lambda: _default_transport("filesystem", ["read_file"]),
        expected_tools=["read_file"],
    ),
    "calendar": ServerConfig(
        name="calendar",
        required=True,  # 必填: 提醒功能依赖
        transport_factory=lambda: _default_transport("calendar", ["create_event"]),
        expected_tools=["create_event"],
    ),
}


def _default_transport(server_name: str, tools: list[str]) -> Transport:
    """构造 MockTransport(默认测试用)."""
    from .transport import MockTransport

    return MockTransport(server_name=server_name, tools=tools)


def get_server_config(name: str) -> ServerConfig:
    """按名取 server 配置.

    Raises:
        KeyError: 配置不存在
    """
    if name not in DEFAULT_SERVERS:
        raise KeyError(f"server {name!r} 不在 DEFAULT_SERVERS({list(DEFAULT_SERVERS)!r})")
    return DEFAULT_SERVERS[name]


def discover_servers(
    configs: dict[str, ServerConfig] | None = None,
) -> tuple[dict[str, MCPClient], McpDegradedReport]:
    """发现 + 连接所有 server — Degraded Graceful.

    Args:
        configs: server 配置 dict(默认用 DEFAULT_SERVERS)

    Returns:
        (connected_clients, report):
          - connected_clients: 成功连接的 client dict{name: MCPClient}
          - report: McpDegradedReport(working + failed + errors + tools)

    Raises:
        MCPError: 必填 server 失败时抛(让启动 abort)
    """
    if configs is None:
        configs = DEFAULT_SERVERS

    clients: dict[str, MCPClient] = {}
    working: list[str] = []
    failed: list[str] = []
    available_tools: set[str] = set()
    expected_tools = {tool for cfg in configs.values() for tool in (cfg.expected_tools or [])}
    errors: list[Any] = []

    for name, cfg in configs.items():
        client: MCPClient | None = None
        try:
            transport = cfg.transport_factory()
            client = MCPClient(server_name=name, transport=transport)
            client.connect()
        except MCPError as e:
            # factory 失败时尚未创建 client，按 discovery 阶段记录；其余为 connect 失败。
            error_surface = (
                client.error_surface(LifecyclePhase.CONNECT, e)
                if client is not None
                else McpErrorSurface(
                    phase=LifecyclePhase.DISCOVERY,
                    server=name,
                    message=str(e),
                    context={"exc_type": type(e).__name__},
                    recoverable=isinstance(e, (MCPTimeoutError, MCPConnectionError)),
                )
            )
            errors.append(error_surface)
            failed.append(name)
            # 关键决策: 必填失败 → abort
            if cfg.required:
                # 尽力关闭已连的所有 client。清理本身不能掩盖启动失败，
                # 也不能让一个 close 异常阻断其余 client 的回收。
                for c in clients.values():
                    try:
                        c.disconnect()
                    except Exception:
                        continue
                raise
            # 可选失败 → 继续
            continue
        except Exception:
            # 编程异常保持原样透传，但仍须回收此前已连的 client，
            # 避免配置/工厂错误在启动中止时遗留连接。
            for c in clients.values():
                try:
                    c.disconnect()
                except Exception:
                    continue
            raise
        # 成功
        clients[name] = client
        working.append(name)
        available_tools.update(client.tools)

    report = McpDegradedReport(
        working=working,
        failed=failed,
        available_tools=available_tools,
        missing_tools=expected_tools - available_tools,
        errors=errors,
    )
    return clients, report
