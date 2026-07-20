"""MCP Transport 抽象 — 参考 g007 stdio/SSE 模式(本项目暂不绑死协议).

设计: Transport 是 MCPClient 与 server 进程之间的字节流抽象.
- 真实场景: stdio(JSON-RPC over stdin/stdout) / SSE
- D4.2: MockTransport 用于测试, 注入可控的成功/超时/协议错/响应错
- 不绑死具体协议: 子类化 Transport, 实现 start()/send()/close() 即可
"""

from __future__ import annotations

import abc
import contextlib
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
        self.call_protocol_error: bool = False  # 响应非 dict (transport 层抛)
        self.call_response_error: bool = False  # 缺 result 字段 (transport 层抛)
        self.call_malformed_response: str | None = None  # 响应坏值, 由 _validate_response 抛
        # 可选值: None(正常) / "non_dict"(返回 list) / "missing_result"(返回 dict 无 result)
        # 默认全局生效, 若 malformed_methods 非空则只对这些 method 生效
        self.malformed_methods: set[str] = set()  # D4.2.2: 按方法注入
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
        method = request.get("method", "")
        # 按 method 注入失败(只对特定 method 生效, 其他 method 正常)
        if method in self.malformed_methods and self.call_malformed_response == "non_dict":
            return ["malformed", "response"]  # type: ignore[return-value]
        if method in self.malformed_methods and self.call_malformed_response == "missing_result":
            return {"jsonrpc": "2.0", "id": request.get("id"), "no_result": True}
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
        if self.call_malformed_response == "non_dict" and not self.malformed_methods:
            # 旧版全局模式(向后兼容)
            return ["malformed", "response"]  # type: ignore[return-value]
        if self.call_malformed_response == "missing_result" and not self.malformed_methods:
            # 旧版全局模式(向后兼容)
            return {"jsonrpc": "2.0", "id": request.get("id"), "no_result": True}
        # 正常: 按 method 路由
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


# === 本机 stdio 白名单实现 ===


class StdioTransport(Transport):
    """本机 JSON-RPC over stdio（newline-delimited）。

    红线：
      - command[0] 必须是绝对路径且在 allowlist
      - 禁止 /bin/sh、/bin/bash、env 等 shell 包装
    """

    _SHELL_BASENAMES = frozenset({"sh", "bash", "zsh", "fish", "dash", "env", "sudo"})

    def __init__(
        self,
        server_name: str,
        command: list[str],
        *,
        allowlist: list[str] | frozenset[str] | set[str],
        timeout_seconds: float = 5.0,
    ) -> None:
        super().__init__(server_name=server_name)
        if not command:
            raise ValueError("command 不能为空")
        self._command = list(command)
        self._allowlist = frozenset(allowlist)
        self._timeout_seconds = timeout_seconds
        self._proc: Any = None
        self._validate_command()

    def _validate_command(self) -> None:
        import os
        from pathlib import Path

        exe = self._command[0]
        if not os.path.isabs(exe):
            raise MCPConnectionError(f"stdio 命令必须是绝对路径: {exe!r}")
        if exe not in self._allowlist:
            raise MCPConnectionError(f"stdio 命令不在白名单: {exe!r}")
        if Path(exe).name in self._SHELL_BASENAMES:
            raise MCPConnectionError(f"禁止 shell 包装命令: {exe!r}")

    def start(self) -> None:
        import subprocess

        if self.connected:
            return
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise MCPConnectionError(f"stdio 启动失败: {exc!r}") from exc
        self.connected = True

    def send(self, request: dict[str, Any]) -> dict[str, Any]:
        import json
        import select

        if not self.connected or self._proc is None:
            raise MCPConnectionError(f"StdioTransport {self.server_name} 未连接")
        if self._proc.stdin is None or self._proc.stdout is None:
            raise MCPConnectionError("stdio 管道不可用")
        self._send_log.append(request)
        line = json.dumps(request, ensure_ascii=False) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except BrokenPipeError as exc:
            raise MCPConnectionError("stdio stdin 已断开") from exc

        ready, _, _ = select.select([self._proc.stdout], [], [], self._timeout_seconds)
        if not ready:
            raise MCPTimeoutError(f"StdioTransport {self.server_name} 调用超时")
        raw = self._proc.stdout.readline()
        if not raw:
            raise MCPConnectionError("stdio stdout EOF")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MCPProtocolError(f"stdio 响应非 JSON: {raw[:120]!r}") from exc
        if not isinstance(payload, dict):
            raise MCPProtocolError("stdio 响应非 object")
        if "result" not in payload and "error" not in payload:
            raise MCPResponseError("stdio 响应缺 result/error")
        if "error" in payload:
            raise MCPResponseError(f"stdio 工具错误: {payload['error']!r}")
        return payload

    def close(self) -> None:
        if self._proc is not None:
            with contextlib.suppress(Exception):
                if self._proc.stdin:
                    self._proc.stdin.close()
            with contextlib.suppress(Exception):
                self._proc.terminate()
                self._proc.wait(timeout=2)
            self._proc = None
        self.connected = False
