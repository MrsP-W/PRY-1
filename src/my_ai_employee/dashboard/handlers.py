"""Dashboard HTTP 路由 — stdlib BaseHTTPRequestHandler.

默认只读 GET;v0.2.53.11 仅开放 ApprovalGate POST 契约端点,该端点当前
不会执行真实写入。
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from my_ai_employee.dashboard.approval_gate import evaluate_writer_dry_run
from my_ai_employee.dashboard.business_writer import (
    SUPPORTED_ACTIONS,
    AuditContext,
)
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
_MAX_POST_BODY_BYTES = 16 * 1024
_READ_ONLY_METHODS = "GET, OPTIONS"
_APPROVAL_GATE_METHODS = "POST, OPTIONS"


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
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/api/approval-gate/actions":
            error_status, payload = self._read_json_object()
            if error_status is not None:
                self._send_json(error_status, payload, allow_methods=_APPROVAL_GATE_METHODS)
                return
            # v0.2.53.29 POST 传 3 字段(env / impl / ready)给 evaluate_writer_dry_run,
            # 让响应 payload 暴露 3 字段,前端 inspector 可逐字段展示 + 501 文案边界化
            writer_env = self.dashboard_context.is_business_writer_env_enabled()
            writer_impl = self.dashboard_context.is_business_writer_impl_injected()
            status, decision = evaluate_writer_dry_run(
                payload,
                writer_enabled=writer_env,
                writer_impl_injected=writer_impl,
            )
            # v0.2.53.22 第三道门:仅路径 3.5(200 OK)合并 writer.dry_run
            if status == HTTPStatus.OK:
                decision = self._merge_writer_dry_run(decision)
            self._send_json(status, decision, allow_methods=_APPROVAL_GATE_METHODS)
            return
        self._method_not_allowed()

    def _merge_writer_dry_run(self, decision: dict[str, Any]) -> dict[str, Any]:
        """v0.2.53.21 handler dry-run 接入 BusinessWriter — 合并 writer.dry_run 结果到 ApprovalGate 决策.

        触发条件(沿 v0.2.53.19 路径 3.5 设计):
            - approval_gate_passed=True(双门已过)
            - dry_run=True(默认)
            - action 在 SUPPORTED_ACTIONS 白名单

        合并字段(沿 v0.2.53.15 WriteDecision):
            - would_allow ← writer.dry_run(action, target_id, audit).would_allow
            - required ← writer.dry_run(action, target_id, audit).required
            - business_writer_error ← writer.dry_run().error(若有)
            - business_writer_reason ← writer.dry_run().reason(若有)
            - write_executed 恒为 False(沿 v0.2.53.11 不变式)

        失败模式(沿撞坑 #65 + v0.2.53.8):
            - writer.dry_run 抛异常 → decision 不变(approval_gate 决策优先)
        """
        if not decision.get("approval_gate_passed"):
            return decision
        if not decision.get("dry_run"):
            return decision
        action = decision.get("action")
        target_id = decision.get("target_id")
        if not isinstance(action, str) or not action or action not in SUPPORTED_ACTIONS:
            return decision
        if not isinstance(target_id, str) or not target_id:
            return decision
        # 构造 AuditContext(沿 v0.2.53.15 §三 + v0.2.53.11 audit 字段)
        audit = AuditContext(
            actor=str(decision.get("audit", {}).get("actor", "local_dashboard")),
            reason=str(decision.get("audit", {}).get("reason", "")),
            source=str(decision.get("audit", {}).get("source", "dashboard")),
        )
        try:
            writer = self.dashboard_context.resolve_business_writer()
            writer_decision = writer.dry_run(action, target_id, audit=audit)
        except Exception:
            # 异常隔离(沿撞坑 #65 + v0.2.53.8):writer 异常不传播,decision 不变
            return decision
        # 合并字段(沿 v0.2.53.15 WriteDecision 字段)
        merged = dict(decision)
        merged["would_allow"] = writer_decision.would_allow
        merged["business_writer_error"] = writer_decision.error
        merged["business_writer_reason"] = writer_decision.reason
        # required 合并:ApprovalGate 已有 required + writer 新增 required(去重保序)
        existing_required = list(decision.get("required", []))
        for item in writer_decision.required:
            if item not in existing_required:
                existing_required.append(item)
        merged["required"] = existing_required
        # write_executed 保持 False(沿 v0.2.53.11 不变式)
        return merged

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:  # noqa: N802
        """允许静态 file:// 原型读取本地只读 GET API."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        allow_methods = (
            _APPROVAL_GATE_METHODS if path == "/api/approval-gate/actions" else _READ_ONLY_METHODS
        )
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self._send_common_headers(content_length=0, allow_methods=allow_methods)
        self.end_headers()

    def _method_not_allowed(self) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"error": "method_not_allowed", "read_only": True},
        )

    def _read_json_object(self) -> tuple[HTTPStatus | None, dict[str, Any]]:
        length_raw = self.headers.get("Content-Length", "0").strip()
        try:
            content_length = int(length_raw)
        except ValueError:
            return (
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "invalid_content_length",
                    "read_only": True,
                    "write_executed": False,
                },
            )
        if content_length <= 0:
            return (
                HTTPStatus.BAD_REQUEST,
                {"error": "empty_body", "read_only": True, "write_executed": False},
            )
        if content_length > _MAX_POST_BODY_BYTES:
            return (
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {
                    "error": "body_too_large",
                    "max_bytes": _MAX_POST_BODY_BYTES,
                    "read_only": True,
                    "write_executed": False,
                },
            )
        raw = self.rfile.read(content_length)
        try:
            loaded: Any = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            return (
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_utf8", "read_only": True, "write_executed": False},
            )
        except json.JSONDecodeError:
            return (
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_json", "read_only": True, "write_executed": False},
            )
        if not isinstance(loaded, dict):
            return (
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "json_object_required",
                    "read_only": True,
                    "write_executed": False,
                },
            )
        return None, loaded

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        *,
        allow_methods: str = _READ_ONLY_METHODS,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self._send_common_headers(content_length=len(body), allow_methods=allow_methods)
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self, *, content_length: int, allow_methods: str) -> None:
        self.send_header("Content-Type", _JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(content_length))
        self.send_header("X-Read-Only-Api", "true")
        self.send_header("Access-Control-Allow-Origin", _CORS_FILE_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", allow_methods)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Allow", allow_methods)
        self.send_header("Vary", "Origin")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """静默默认 access log(测试/本地不刷屏)."""


def handler_factory(ctx: DashboardContext) -> type[DashboardHandler]:
    """绑定 DashboardContext 到 handler 类(沿 stdlib 范本)."""

    class _BoundHandler(DashboardHandler):
        dashboard_context = ctx

    return _BoundHandler
