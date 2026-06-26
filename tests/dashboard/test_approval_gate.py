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
from typing import Any

import pytest

from my_ai_employee.dashboard.approval_gate import (
    CONFIRM_TEXT,
    DASHBOARD_WRITE_API_ENV,
    build_approval_gate_status,
    evaluate_approval_action_request,
    is_dashboard_write_api_enabled,
    list_action_contracts,
)
from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.handlers import handler_factory
from my_ai_employee.dashboard.responses import build_status_payload


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.delenv(DASHBOARD_WRITE_API_ENV, raising=False)
    yield


@pytest.fixture
def http_server() -> Generator[str, None, None]:
    ctx = DashboardContext.default()
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
        assert payload["would_allow"] is True
        assert payload["write_executed"] is False
        assert payload["audit"]["actor"] == "tester"


class TestApprovalGateStatusPayload:
    def test_status_payload_exposes_write_gate(self) -> None:
        payload = build_status_payload(
            DashboardContext(git_head_resolver=lambda: "abc123", keychain_probe=lambda _s: False)
        )
        assert payload["approval_gates"]["dashboard_write_api"] is False
        assert payload["approval_gates"]["write_contract_version"] == "v0.2.53.11"
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
