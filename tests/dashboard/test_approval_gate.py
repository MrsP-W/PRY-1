"""v0.2.53.11 — ApprovalGate 写操作契约测试.

边界:
    - 默认禁写(`DASHBOARD_WRITE_API` 未设)
    - POST 端点只做契约校验,不执行真实写入
    - 即使 env + confirm_text 齐全,v0.2.53.11 仍返回 write_not_implemented
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Generator
from http.server import HTTPServer
from types import SimpleNamespace
from typing import Any, cast

import pytest

from my_ai_employee.dashboard.approval_gate import (
    BUSINESS_WRITER_ENABLED_ENV,
    CONFIRM_TEXT,
    DASHBOARD_WRITE_API_ENV,
    build_approval_gate_status,
    evaluate_approval_action_request,
    evaluate_writer_dry_run,
    is_dashboard_write_api_enabled,
    list_action_contracts,
)
from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.handlers import handler_factory
from my_ai_employee.dashboard.responses import build_status_payload


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.delenv(DASHBOARD_WRITE_API_ENV, raising=False)
    monkeypatch.delenv(BUSINESS_WRITER_ENABLED_ENV, raising=False)
    yield


@pytest.fixture
def http_server() -> Generator[str, None, None]:
    ctx = DashboardContext.default()
    yield from _serve_dashboard(ctx)


def _serve_dashboard(ctx: DashboardContext) -> Generator[str, None, None]:
    server = HTTPServer(("127.0.0.1", 0), handler_factory(ctx))
    host, port = server.server_address[:2]
    host_str = str(host)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host_str}:{port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2.0)


def _post_json(url: str, payload: dict[str, Any] | str) -> tuple[int, dict[str, Any]]:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    req = urllib.request.Request(  # noqa: S310 — 测试 localhost
        url,
        data=data.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            body: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return exc.code, body


class TestApprovalGateEnv:
    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
    def test_truthy_values_enable(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, value)
        assert is_dashboard_write_api_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "random"])
    def test_other_values_disable(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, value)
        assert is_dashboard_write_api_enabled() is False

    def test_status_contract_is_safe(self) -> None:
        status = build_approval_gate_status()
        assert status["write_enabled"] is False
        assert status["write_executed"] is False
        assert status["confirm_text"] == CONFIRM_TEXT
        assert len(status["actions"]) >= 3


class TestApprovalGateContract:
    def test_action_contracts_have_no_secret(self) -> None:
        contracts = list_action_contracts()
        assert {c["action"] for c in contracts} >= {"outbox.approve", "notes.confirm"}
        for contract in contracts:
            assert "password" not in json.dumps(contract).lower()
            assert "token" not in json.dumps(contract).lower()

    def test_default_valid_request_is_forbidden_no_write(self) -> None:
        status, payload = evaluate_approval_action_request(
            {"action": "outbox.approve", "target_id": 123, "reason": "用户点击审批"}
        )
        assert status.value == 403
        assert payload["error"] == "write_disabled"
        assert payload["write_enabled"] is False
        assert payload["write_executed"] is False
        assert payload["action_contract"]["target_type"] == "outbox"

    def test_missing_action_bad_request(self) -> None:
        status, payload = evaluate_approval_action_request({"target_id": 123})
        assert status.value == 400
        assert payload["error"] == "missing_action"
        assert payload["write_executed"] is False

    def test_unsupported_action_bad_request(self) -> None:
        status, payload = evaluate_approval_action_request(
            {"action": "keychain.write", "target_id": "x"}
        )
        assert status.value == 400
        assert payload["error"] == "unsupported_action"
        assert payload["write_executed"] is False

    def test_missing_target_bad_request(self) -> None:
        status, payload = evaluate_approval_action_request({"action": "notes.confirm"})
        assert status.value == 400
        assert payload["error"] == "missing_target_id"

    def test_enabled_without_confirmation_still_forbidden(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        status, payload = evaluate_approval_action_request(
            {"action": "notes.confirm", "target_id": "note-1"}
        )
        assert status.value == 403
        assert payload["error"] == "confirmation_required"
        assert payload["write_enabled"] is True
        assert payload["write_executed"] is False

    def test_enabled_and_confirmed_still_not_implemented(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        status, payload = evaluate_approval_action_request(
            {
                "action": "notes.confirm",
                "target_id": "note-1",
                "confirm_text": CONFIRM_TEXT,
                "actor": "tester",
                "reason": "dry-run",
            }
        )
        assert status.value == 501
        assert payload["error"] == "write_not_implemented"
        assert payload["would_allow"] is False
        assert payload["approval_gate_passed"] is True
        assert payload["write_executed"] is False
        assert payload["audit"]["actor"] == "tester"


class TestApprovalGateStatusPayload:
    def test_status_payload_exposes_write_gate(self) -> None:
        payload = build_status_payload(
            DashboardContext(git_head_resolver=lambda: "abc123", keychain_probe=lambda _s: False)
        )
        assert payload["approval_gates"]["dashboard_write_api"] is False
        assert payload["approval_gates"]["write_contract_version"] == "v0.2.57"
        assert len(payload["approval_gates"]["write_actions"]) >= 3


class TestApprovalGateHttp:
    def test_post_default_forbidden(self, http_server: str) -> None:
        status, payload = _post_json(
            f"{http_server}/api/approval-gate/actions",
            {"action": "outbox.approve", "target_id": 1},
        )
        assert status == 403
        assert payload["error"] == "write_disabled"
        assert payload["write_executed"] is False

    def test_post_dry_run_explicit_forbidden(self, http_server: str) -> None:
        status, payload = _post_json(
            f"{http_server}/api/approval-gate/actions",
            {
                "action": "outbox.approve",
                "target_id": 1,
                "dry_run": True,
                "reason": "dashboard ui dry-run click",
                "actor": "local_dashboard",
            },
        )
        assert status == 403
        assert payload["error"] == "write_disabled"
        assert payload["dry_run"] is True
        assert payload["write_executed"] is False

    def test_post_finance_dismiss_dry_run_forbidden(self, http_server: str) -> None:
        status, payload = _post_json(
            f"{http_server}/api/approval-gate/actions",
            {
                "action": "finance.dismiss_anomaly",
                "target_id": "2026-06-25|支付宝|1299",
                "dry_run": True,
            },
        )
        assert status == 403
        assert payload["error"] == "write_disabled"
        assert payload["action_contract"]["target_type"] == "finance_anomaly"
        assert payload["write_executed"] is False

    def test_post_invalid_json_bad_request(self, http_server: str) -> None:
        status, payload = _post_json(f"{http_server}/api/approval-gate/actions", "{bad")
        assert status == 400
        assert payload["error"] == "invalid_json"
        assert payload["write_executed"] is False

    def test_options_approval_gate_allows_post(self, http_server: str) -> None:
        req = urllib.request.Request(  # noqa: S310
            f"{http_server}/api/approval-gate/actions",
            method="OPTIONS",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            assert resp.status == 204
            assert resp.headers["Allow"] == "POST, OPTIONS"

    def test_other_post_still_method_not_allowed(self, http_server: str) -> None:
        status, payload = _post_json(f"{http_server}/api/status", {})
        assert status == 405
        assert payload["error"] == "method_not_allowed"


class TestApprovalGateWriterDryRunHttp:
    """v0.2.53.22 handler 走 evaluate_writer_dry_run 第三道门 HTTP 测试."""

    def test_post_env_confirm_writer_off_501(
        self, http_server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        status, payload = _post_json(
            f"{http_server}/api/approval-gate/actions",
            {
                "action": "notes.confirm",
                "target_id": "note-1",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
        )
        assert status == 501
        assert payload["error"] == "write_not_implemented"
        assert payload["approval_gate_passed"] is True
        assert payload["write_executed"] is False
        assert "business_writer_error" not in payload

    def test_post_env_confirm_writer_env_only_stub_501(
        self, http_server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BUSINESS_WRITER_ENABLED=1 但 Impl 未注入 → 501(不再误报 200)."""
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        status, payload = _post_json(
            f"{http_server}/api/approval-gate/actions",
            {
                "action": "notes.confirm",
                "target_id": "note-1",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
        )
        assert status == 501
        assert payload["error"] == "write_not_implemented"
        assert payload["approval_gate_passed"] is True
        assert payload["write_executed"] is False
        assert "business_writer_error" not in payload

    def test_post_all_gates_dry_run_ok_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        ctx = DashboardContext().with_business_writer(BusinessWriterImpl())
        for base_url in _serve_dashboard(ctx):
            status, payload = _post_json(
                f"{base_url}/api/approval-gate/actions",
                {
                    "action": "outbox.approve",
                    "target_id": "123",
                    "confirm_text": CONFIRM_TEXT,
                    "dry_run": True,
                },
            )
        assert status == 200
        assert payload["error"] is None
        assert payload["writer_enabled"] is True
        assert payload["approval_gate_passed"] is True
        assert payload["write_executed"] is False
        assert payload["business_writer_error"] == "write_not_implemented"
        assert payload["would_allow"] is False

    def test_post_all_gates_real_write_missing_internal_gates_501(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        ctx = DashboardContext().with_business_writer(BusinessWriterImpl())
        for base_url in _serve_dashboard(ctx):
            status, payload = _post_json(
                f"{base_url}/api/approval-gate/actions",
                {
                    "action": "outbox.approve",
                    "target_id": "123",
                    "confirm_text": CONFIRM_TEXT,
                    "dry_run": False,
                },
            )
        assert status == 501
        assert payload["error"] == "write_not_implemented"
        assert "写保护锁未开" in payload["reason"]
        assert payload["write_executed"] is False
        assert "business_writer_error" not in payload

    def test_post_all_five_gates_real_write_ok_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """五门全开 + fake outbox store → handler 执行 writer 实写分发."""
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl
        from my_ai_employee.menu_bar.approval_gate_audit import InMemoryApprovalGateAuditStore

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        monkeypatch.setenv("ENABLE_PATH_4_WRITE", "1")
        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            outbox_store=cast(
                Any,
                SimpleNamespace(update_status=lambda **kw: SimpleNamespace(id=321)),
            ),
            audit_store=audit_store,
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        ctx = DashboardContext(audit_store=audit_store).with_business_writer(writer)
        for base_url in _serve_dashboard(ctx):
            status, payload = _post_json(
                f"{base_url}/api/approval-gate/actions",
                {
                    "action": "outbox.approve",
                    "target_id": "321",
                    "confirm_text": CONFIRM_TEXT,
                    "dry_run": False,
                    "actor": "tester",
                    "reason": "advance 8/1 task",
                },
            )
        assert status == 200
        assert payload["read_only"] is False
        assert payload["error"] is None
        assert payload["write_executed"] is True
        assert payload["affected_id"] == "321"
        assert payload["audit_id"] == "audit:1"
        assert audit_store.count() == 1


class TestEvaluateWriterDryRunContract:
    """evaluate_writer_dry_run 单元测试(沿 v0.2.53.22 决策矩阵)."""

    def test_writer_dry_run_path_3_5_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        status, payload = evaluate_writer_dry_run(
            {
                "action": "outbox.approve",
                "target_id": "1",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status.value == 200
        assert payload["writer_enabled"] is True
        assert payload["approval_gate_passed"] is True
        assert payload["write_executed"] is False

    def test_real_write_request_passes_to_handler_when_dry_run_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        status, payload = evaluate_writer_dry_run(
            {
                "action": "outbox.approve",
                "target_id": "1",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": False,
            },
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status.value == 200
        assert payload["error"] is None
        assert payload["would_allow"] is True
        assert payload["write_executed"] is False


class TestEvaluateWriterDryRunThreeField:
    """v0.2.53.29 evaluate_writer_dry_run 暴露 3 字段测试(env / impl / ready).

    边界:
        - default:env=False / impl=False / ready=False + 文案默认(无 DASHBOARD_REAL_DB 提示)
        - env_only:env=True / impl=False / ready=False + 文案边界化(需 DASHBOARD_REAL_DB=1)
        - all_open:env=True / impl=True / ready=True + 200 OK
        - writer_impl_injected=None:保守 501(不返回 200)
    """

    def test_default_payload_exposes_3_fields_all_false(self) -> None:
        """默认 403 响应也含 3 字段(全 False,沿 _decision 暴露)."""
        status, payload = evaluate_approval_action_request(
            {"action": "outbox.approve", "target_id": "1"}
        )
        assert status.value == 403
        assert payload["business_writer_env_enabled"] is False
        assert payload["business_writer_impl_injected"] is False
        assert payload["business_writer_ready"] is False

    def test_env_only_marker_in_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 已开 + Impl 未注入 → 501 + reason 包含「BusinessWriter env 已开且 Impl 未注入」边界文案."""
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        status, payload = evaluate_writer_dry_run(
            {
                "action": "notes.confirm",
                "target_id": "note-1",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
            writer_enabled=True,
            writer_impl_injected=False,
        )
        assert status.value == 501
        assert payload["error"] == "write_not_implemented"
        assert "BusinessWriter env 已开且 Impl 未注入" in payload["reason"]
        assert "DASHBOARD_REAL_DB=1" in payload["reason"]
        assert payload["business_writer_env_enabled"] is True
        assert payload["business_writer_impl_injected"] is False
        assert payload["business_writer_ready"] is False

    def test_impl_injected_payload_3_fields_all_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env + Impl 都注入 → ready=True + 3 字段全 True + 200 OK."""
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        status, payload = evaluate_writer_dry_run(
            {
                "action": "outbox.approve",
                "target_id": "1",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status.value == 200
        assert payload["business_writer_env_enabled"] is True
        assert payload["business_writer_impl_injected"] is True
        assert payload["business_writer_ready"] is True
        assert payload["approval_gate_passed"] is True

    def test_writer_impl_injected_none_conservative_501(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """writer_impl_injected=None(默认) → 保守 501(不返回 200 dry-run-ready).

        边界(v0.2.53.30):
            - writer_impl_injected is not True → env_only marker(501)
            - 仅 writer_impl_injected is True 才进入路径 3.5 dry_run 200
        """
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        status, payload = evaluate_writer_dry_run(
            {
                "action": "notes.confirm",
                "target_id": "note-1",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
            writer_enabled=True,
            # writer_impl_injected 默认 None
        )
        assert status.value == 501
        assert payload["error"] == "write_not_implemented"
        assert "BusinessWriter env 已开且 Impl 未注入" in payload["reason"]
        assert payload["business_writer_env_enabled"] is True
        assert payload["business_writer_impl_injected"] is False
        assert payload["business_writer_ready"] is False


class TestApprovalGateWriterDryRunHttpThreeField:
    """v0.2.53.29 HTTP POST 暴露 3 字段测试(handler 透传 ctx)."""

    def test_post_default_forbidden_payload_exposes_3_fields(self, http_server: str) -> None:
        """403 默认禁写响应也含 3 字段(全 False)."""
        status, payload = _post_json(
            f"{http_server}/api/approval-gate/actions",
            {"action": "outbox.approve", "target_id": "1"},
        )
        assert status == 403
        assert payload["error"] == "write_disabled"
        assert payload["business_writer_env_enabled"] is False
        assert payload["business_writer_impl_injected"] is False
        assert payload["business_writer_ready"] is False

    def test_post_env_only_marker_in_http_reason(
        self, http_server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HTTP POST:env 开 + ctx 默认 stub(impl=False)→ 501 + 边界文案."""
        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        status, payload = _post_json(
            f"{http_server}/api/approval-gate/actions",
            {
                "action": "notes.confirm",
                "target_id": "note-1",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
        )
        assert status == 501
        assert payload["error"] == "write_not_implemented"
        # handler ctx.is_business_writer_impl_injected() == False (默认 stub)
        assert "BusinessWriter env 已开且 Impl 未注入" in payload["reason"]
        assert "DASHBOARD_REAL_DB=1" in payload["reason"]
        assert payload["business_writer_env_enabled"] is True
        assert payload["business_writer_impl_injected"] is False
        assert payload["business_writer_ready"] is False

    def test_post_all_gates_payload_exposes_3_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP POST:env + Impl 都注入(handler ctx)→ ready=True + 3 字段全 True + 200 OK."""
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        ctx = DashboardContext().with_business_writer(BusinessWriterImpl())
        for base_url in _serve_dashboard(ctx):
            status, payload = _post_json(
                f"{base_url}/api/approval-gate/actions",
                {
                    "action": "outbox.approve",
                    "target_id": "1",
                    "confirm_text": CONFIRM_TEXT,
                    "dry_run": True,
                },
            )
        assert status == 200
        assert payload["business_writer_env_enabled"] is True
        assert payload["business_writer_impl_injected"] is True
        assert payload["business_writer_ready"] is True
        assert payload["approval_gate_passed"] is True
        assert payload["write_executed"] is False
