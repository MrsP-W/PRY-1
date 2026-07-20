"""MCP schema / tool gate / StdioTransport 红线回归。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from my_ai_employee.mcp.exceptions import MCPConnectionError
from my_ai_employee.mcp.schema import JsonSchemaValidationError, validate_json_schema
from my_ai_employee.mcp.tool_gate import (
    GatedToolCaller,
    ToolApprovalRequiredError,
    ToolReadOnlyViolationError,
)
from my_ai_employee.mcp.transport import StdioTransport


def test_validate_json_schema_required_and_types() -> None:
    schema = {
        "type": "object",
        "required": ["path"],
        "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
    }
    validate_json_schema({"path": "/tmp/x", "limit": 1}, schema)
    with pytest.raises(JsonSchemaValidationError):
        validate_json_schema({"limit": 1}, schema)
    with pytest.raises(JsonSchemaValidationError):
        validate_json_schema({"path": "/tmp/x", "limit": "nope"}, schema)


def test_tool_gate_readonly_and_approval() -> None:
    gate = GatedToolCaller(
        tool_schemas={
            "read_file": {
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string"}},
            },
            "write_file": {
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        },
        read_only=True,
    )
    gate.ensure_callable("read_file", {"path": "/tmp/a"})
    with pytest.raises(ToolReadOnlyViolationError):
        gate.ensure_callable("write_file", {"path": "/tmp/a", "content": "x"})

    gate.read_only = False
    with pytest.raises(ToolApprovalRequiredError):
        gate.ensure_callable("write_file", {"path": "/tmp/a", "content": "x"})
    gate.approve("write_file")
    gate.ensure_callable("write_file", {"path": "/tmp/a", "content": "x"})


def test_stdio_rejects_relative_and_non_allowlisted(tmp_path: Path) -> None:
    with pytest.raises(MCPConnectionError, match="绝对路径"):
        StdioTransport("x", ["python3"], allowlist={"/usr/bin/python3"})
    with pytest.raises(MCPConnectionError, match="白名单"):
        StdioTransport("x", ["/usr/bin/python3"], allowlist={"/opt/other"})


def test_stdio_rejects_shell_wrapper() -> None:
    with pytest.raises(MCPConnectionError, match="shell"):
        StdioTransport("x", ["/bin/sh", "-c", "echo"], allowlist={"/bin/sh"})


def test_stdio_roundtrip_with_allowlisted_python(tmp_path: Path) -> None:
    server = tmp_path / "echo_server.py"
    server.write_text(
        "\n".join(
            [
                "import json, sys",
                "for line in sys.stdin:",
                "    req = json.loads(line)",
                "    print(json.dumps({'jsonrpc': '2.0', 'id': req.get('id'), 'result': {'ok': True}}))",
                "    sys.stdout.flush()",
            ]
        ),
        encoding="utf-8",
    )
    python = Path(sys.executable).resolve()
    transport = StdioTransport(
        "echo",
        [str(python), str(server)],
        allowlist={str(python)},
        timeout_seconds=3.0,
    )
    transport.start()
    try:
        resp = transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp["result"]["ok"] is True
    finally:
        transport.close()
