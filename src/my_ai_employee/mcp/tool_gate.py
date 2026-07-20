"""危险 MCP 工具审批门（对接 ApprovalGate / AgentRun awaiting_approval）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from my_ai_employee.mcp.schema import JsonSchemaValidationError, validate_json_schema


class ToolApprovalRequiredError(PermissionError):
    """危险工具未获审批。"""


class ToolReadOnlyViolationError(PermissionError):
    """只读配置下调用写工具。"""


DEFAULT_DANGEROUS_TOOLS: frozenset[str] = frozenset(
    {
        "write_file",
        "delete_file",
        "send_email",
        "create_event",
        "shell_exec",
    }
)


@dataclass
class GatedToolCaller:
    """校验 schema + 只读默认 + 危险工具审批。"""

    tool_schemas: dict[str, dict[str, Any]] = field(default_factory=dict)
    dangerous_tools: frozenset[str] = DEFAULT_DANGEROUS_TOOLS
    read_only: bool = True
    approved_tools: set[str] = field(default_factory=set)

    def approve(self, tool_name: str) -> None:
        self.approved_tools.add(tool_name)

    def ensure_callable(self, tool_name: str, arguments: dict[str, Any] | None = None) -> None:
        args = arguments or {}
        schema = self.tool_schemas.get(tool_name)
        if schema is not None:
            try:
                validate_json_schema(args, schema)
            except JsonSchemaValidationError as exc:
                raise JsonSchemaValidationError(str(exc)) from exc

        is_dangerous = tool_name in self.dangerous_tools
        if self.read_only and is_dangerous:
            raise ToolReadOnlyViolationError(
                f"只读模式禁止危险工具 {tool_name!r}；需 ApprovalGate 后关闭 read_only 或改用审批路径"
            )
        if is_dangerous and tool_name not in self.approved_tools:
            raise ToolApprovalRequiredError(
                f"危险工具 {tool_name!r} 需要 ApprovalGate / approved_tools"
            )


__all__ = [
    "DEFAULT_DANGEROUS_TOOLS",
    "GatedToolCaller",
    "ToolApprovalRequiredError",
    "ToolReadOnlyViolationError",
]
