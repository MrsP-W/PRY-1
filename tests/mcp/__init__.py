"""D4.2 — MCP 4 类业务异常窄化测试 (参考 D4.1 教训).

覆盖:
  - 4 类业务异常独立继承 MCPError
  - 编程错误(ValueError/TypeError/KeyError) 不归 MCPError
  - 异常可正常 raise + message 保留
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.mcp.exceptions import (  # noqa: E402
    MCPConnectionError,
    MCPError,
    MCPProtocolError,
    MCPResponseError,
    MCPTimeoutError,
)


class TestExceptionHierarchy:
    """异常继承关系."""

    def test_all_subclass_mcp_error(self) -> None:
        """4 类异常都继承 MCPError."""
        for cls in (MCPTimeoutError, MCPConnectionError, MCPProtocolError, MCPResponseError):
            assert issubclass(cls, MCPError)

    def test_mcp_error_subclass_exception(self) -> None:
        """MCPError 继承 Exception(基类)."""
        assert issubclass(MCPError, Exception)


class TestExceptionRaise:
    """4 类异常可正常 raise + message 保留."""

    @pytest.mark.parametrize(
        ("cls", "msg"),
        [
            (MCPTimeoutError, "30s timeout"),
            (MCPConnectionError, "stdio broken"),
            (MCPProtocolError, "method not found"),
            (MCPResponseError, "missing result field"),
        ],
    )
    def test_raise_preserves_message(self, cls: type[MCPError], msg: str) -> None:
        with pytest.raises(cls, match=msg):
            raise cls(msg)


class TestExceptionNarrowing:
    """D3.3.3 教训落地: 编程错误不被归为 MCPError.

    反向断言: ValueError/TypeError/KeyError 不是 MCPError 子类,
    在 MCPClient 决策点可安全区分业务异常 vs 编程错误.
    """

    def test_value_error_not_mcp_error(self) -> None:
        assert not issubclass(ValueError, MCPError)

    def test_type_error_not_mcp_error(self) -> None:
        assert not issubclass(TypeError, MCPError)

    def test_key_error_not_mcp_error(self) -> None:
        assert not issubclass(KeyError, MCPError)

    def test_catch_mcp_error_does_not_catch_value_error(self) -> None:
        """except MCPError 不会捕获 ValueError(关键安全保证)."""
        try:
            try:
                raise ValueError("program bug")
            except MCPError:
                pytest.fail("不应 catch ValueError")
        except ValueError:
            pass  # 预期: ValueError 透传
