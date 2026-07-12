"""MCP Degraded Report 数据结构 — 参考 g007 McpDegradedReport.

参考 g007-mcp-lifecycle-mapping.md:
  - McpDegradedReport: working + failed + available_tools + missing_tools
  - McpErrorSurface: phase + server + message + context + recoverability
  - 必填失败 vs 可选失败 决策依据 = McpServerStatus.required

设计要点:
  - 所有字段都是 Truthful Status 原则(状态可观察、可序列化)
  - Evidence-Backed: 错误有结构化字段, prose 不可信
  - Machine-Readable: dataclass + asdict() 序列化, 适合 logging / API
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any


class LifecyclePhase(enum.StrEnum):
    """MCP server 生命周期阶段 — 参考 g007 PluginLifecycle."""

    DISCOVERY = "discovery"  # discover_servers() 阶段
    CONNECT = "connect"  # 启动进程 / 握手
    INITIALIZE = "initialize"  # MCP initialize 协议
    CALL = "call"  # call_tool() 阶段
    DISCONNECT = "disconnect"  # 主动关闭


@dataclass(frozen=True)
class McpServerStatus:
    """单个 MCP server 状态 — 决策依据.

    Attributes:
        name: server 配置名(唯一)
        required: True → 连接失败必须 abort; False → 失败降级
        connected: 是否已成功连接
        tools: 该 server 暴露的工具列表(连接成功后填充)
        error: 连接/调用错误信息(失败时填充)
    """

    name: str
    required: bool
    connected: bool
    tools: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class McpErrorSurface:
    """结构化错误面 — 参考 g007 McpErrorSurface 5 字段.

    Attributes:
        phase: 失败时的生命周期阶段(DISCOVERY/CONNECT/INITIALIZE/CALL)
        server: server 名
        message: 人类可读错误信息
        context: 附加上下文(可序列化 dict)
        recoverable: 是否可重试(超时/连接断=True, 协议错=False)
    """

    phase: LifecyclePhase
    server: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)
    recoverable: bool = True

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(phase 转字符串)."""
        d = asdict(self)
        d["phase"] = self.phase.value
        return d


@dataclass(frozen=True)
class McpDegradedReport:
    """MCP 启动降级报告 — 参考 g007 McpDegradedReport.

    Attributes:
        working: 已成功连接的 server 名列表
        failed: 失败的 server 名列表
        available_tools: 所有 working server 提供的工具名集合
        missing_tools: 用户期望但因 server 失败或未暴露能力而缺失的工具名
        errors: 失败 server 的结构化错误面
    """

    working: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    available_tools: set[str] = field(default_factory=set)
    missing_tools: set[str] = field(default_factory=set)
    errors: list[McpErrorSurface] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        """是否完全健康(无失败 + 无缺失工具)."""
        return not self.failed and not self.missing_tools

    @property
    def is_degraded(self) -> bool:
        """是否降级(有失败但没 abort, 即只有可选 server 失败)."""
        return bool(self.failed)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(set 转 sorted list 保证可序列化)."""
        return {
            "working": list(self.working),
            "failed": list(self.failed),
            "available_tools": sorted(self.available_tools),
            "missing_tools": sorted(self.missing_tools),
            "errors": [e.to_dict() for e in self.errors],
            "is_healthy": self.is_healthy,
            "is_degraded": self.is_degraded,
        }
