"""Dashboard HTTP 路由 — stdlib BaseHTTPRequestHandler(只读 GET)."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from my_ai_employee.dashboard.context import DashboardContext, parse_limit
from my_ai_employee.dashboard.responses import (
    build_finance_anomalies_payload,
    build_notes_pending_payload,
    build_outbox_payload,
    build_report_preview_payload,
    build_reports_payload,
    build_status_payload,
    build_tasks_today_payload,
)

_JSON_CONTENT_TYPE = "application/json; charset=utf-8"
_CORS_FILE_ORIGIN = "null"


class DashboardHandler(BaseHTTPRequestHandler):
    """只读 Dashboard API handler."""

    dashboard_context: DashboardContext

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        limit_raw = query.get("limit", [None])[0]
        limit = parse_limit(limit_raw)
        type_raw = query.get("type", [None])[0]
        type_filter = type_raw.strip() if type_raw else None
        path_raw = query.get("path", [None])[0]
        if path == "/api/reports/preview":
            if not path_raw or not path_raw.strip():
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "missing_path", "read_only": True},
                )
                return
            payload = build_report_preview_payload(path_raw.strip())
            if payload is None:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "report_not_found", "path": path_raw, "read_only": True},
                )
                return
            self._send_json(HTTPStatus.OK, payload)
            return
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "read_only": True})
            return
        if path == "/api/status":
            self._send_json(HTTPStatus.OK, build_status_payload(self.dashboard_context))
            return
        if path == "/api/tasks/today":
            self._send_json(HTTPStatus.OK, build_tasks_today_payload(self.dashboard_context))
            return
        if path == "/api/outbox":
            self._send_json(
                HTTPStatus.OK,
                build_outbox_payload(self.dashboard_context, limit=limit),
            )
            return
        if path == "/api/notes/pending":
            self._send_json(
                HTTPStatus.OK,
                build_notes_pending_payload(self.dashboard_context, limit=limit),
            )
            return
        if path == "/api/finance/anomalies":
            self._send_json(
                HTTPStatus.OK,
                build_finance_anomalies_payload(self.dashboard_context, limit=limit),
            )
            return
        if path == "/api/reports":
            self._send_json(
                HTTPStatus.OK,
                build_reports_payload(self.dashboard_context, limit=limit, type_filter=type_filter),
            )
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

    def do_OPTIONS(self) -> None:  # noqa: N802
        """允许静态 file:// 原型读取本地只读 GET API."""
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self._send_common_headers(content_length=0)
        self.send_header("Allow", "GET, OPTIONS")
        self.end_headers()

    def _method_not_allowed(self) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"error": "method_not_allowed", "read_only": True},
        )

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self._send_common_headers(content_length=len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self, *, content_length: int) -> None:
        self.send_header("Content-Type", _JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(content_length))
        self.send_header("X-Read-Only-Api", "true")
        self.send_header("Access-Control-Allow-Origin", _CORS_FILE_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """静默默认 access log(测试/本地不刷屏)."""


def handler_factory(ctx: DashboardContext) -> type[DashboardHandler]:
    """绑定 DashboardContext 到 handler 类(沿 stdlib 范本)."""

    class _BoundHandler(DashboardHandler):
        dashboard_context = ctx

    return _BoundHandler
