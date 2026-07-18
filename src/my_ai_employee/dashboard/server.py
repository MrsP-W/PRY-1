"""Dashboard 本地 HTTP 服务入口 — 127.0.0.1 只读."""

from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer

from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.handlers import handler_factory

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765


def _validate_local_host(host: str) -> None:
    """拒绝绕过 CLI 的非本地绑定，保持 Dashboard 仅限本机访问。"""
    if host != _DEFAULT_HOST:
        raise ValueError("Dashboard 仅允许本地绑定 127.0.0.1")


def create_server(
    ctx: DashboardContext | None = None,
    *,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
) -> ThreadingHTTPServer:
    """创建 ThreadingHTTPServer(测试可 bind port=0)."""
    _validate_local_host(host)
    context = ctx or DashboardContext.default()
    handler_cls = handler_factory(context)
    return ThreadingHTTPServer((host, port), handler_cls)


def run_server(
    ctx: DashboardContext | None = None,
    *,
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
) -> None:
    """阻塞运行 Dashboard API 服务."""
    server = create_server(ctx, host=host, port=port)
    bound_host, bound_port = server.server_address[:2]
    print(f"Dashboard 只读 API: http://{str(bound_host)}:{bound_port}/api/status")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard API 已停止")
    finally:
        server.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="my-ai-employee-dashboard",
        description="我的AI员工 — 本地 Web Dashboard 只读 API(P2 骨架)",
    )
    parser.add_argument("--host", default=_DEFAULT_HOST, help="绑定地址(默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help="端口(默认 8765)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _validate_local_host(args.host)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    run_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
