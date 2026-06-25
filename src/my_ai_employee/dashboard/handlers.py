"""Dashboard HTTP 路由 — stdlib BaseHTTPRequestHandler(只读 GET)."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse

from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.responses import build_status_payload, build_tasks_today_payload

_JSON_CONTENT_TYPE = "application/json; charset=utf-8"


class DashboardHandler(BaseHTTPRequestHandler):
    """只读 Dashboard API handler."""

    dashboard_context: DashboardContext

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "read_only": True})
            return
        if path == "/api/status":
            self._send_json(HTTPStatus.OK, build_status_payload(self.dashboard_context))
            return
        if path == "/api/tasks/today":
            self._send_json(HTTPStatus.OK, build_tasks_today_payload(self.dashboard_context))
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"error": "not_found", "path": path, "read_only": True},
        )

    def do_POST(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"error": "method_not_allowed", "read_only": True},
        )

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", _JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Read-Only-Api", "true")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """静默默认 access log(测试/本地不刷屏)."""


def handler_factory(ctx: DashboardContext) -> type[DashboardHandler]:
    """绑定 DashboardContext 到 handler 类(沿 stdlib 范本)."""

    class _BoundHandler(DashboardHandler):
        dashboard_context = ctx

    return _BoundHandler
