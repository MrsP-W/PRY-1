"""v0.2.53.2 P2 — Dashboard 只读 API 测试."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Generator
from typing import Any

import pytest

from my_ai_employee.dashboard.context import DashboardContext, QualityGateSnapshot
from my_ai_employee.dashboard.handlers import handler_factory
from my_ai_employee.dashboard.responses import (
    build_finance_anomalies_payload,
    build_notes_pending_payload,
    build_outbox_payload,
    build_status_payload,
    build_tasks_today_payload,
)
from my_ai_employee.dashboard.server import create_server


class _CountingDraft:
    def get_pending_draft_count(self) -> int:
        return 2

    def list_pending_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {
                "outbox_id": 101,
                "subject": "供应商付款确认",
                "status": "pending_send",
                "priority": "urgent",
            }
        ][:limit]


class _CountingConfirm:
    def get_pending_confirm_count(self) -> int:
        return 3

    def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {
                "apple_note_id": "note-1",
                "title": "L2 候选",
                "folder": "工作",
                "needs_confirm": 1,
            }
        ][:limit]

    def confirm_note(self, apple_note_id: str) -> None:
        return None


class _CountingExpense:
    def get_total_notes_count(self) -> int:
        return 0

    def get_unsynced_count(self) -> int:
        return 0

    def get_recent_note_titles(self, limit: int = 5) -> list[str]:
        return []

    def is_clipboard_listener_running(self) -> bool:
        return False

    def get_tcc_authorization_status(self) -> bool:
        return False

    def get_anomaly_count(self) -> int:
        return 1

    def get_recent_anomalies(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {
                "date": "2026-06-25",
                "counterparty": "支付宝",
                "amount": 1299,
                "kinds": "amount_spike",
            }
        ][:limit]


@pytest.fixture
def dashboard_ctx() -> DashboardContext:
    return DashboardContext(
        expense_service=_CountingExpense(),
        note_confirm_service=_CountingConfirm(),
        outbox_draft_service=_CountingDraft(),
        git_head_resolver=lambda: "abc123",
        keychain_probe=lambda _s: False,
        quality_gates=QualityGateSnapshot(pytest="2278 passed / 1 skipped"),
    )


def test_build_status_payload_read_only(dashboard_ctx: DashboardContext) -> None:
    payload = build_status_payload(dashboard_ctx)
    assert payload["read_only"] is True
    assert payload["git_head"] == "abc123"
    assert payload["quality_gates"]["pytest"] == "2278 passed / 1 skipped"
    assert payload["providers"]["keychain"]["smtp_qq"] == "missing"
    assert payload["approval_gates"]["keychain_write"] is False


class TestDryRunThreeGateStatus:
    """v0.2.53.28 三门联调 status payload — 第三道门以 Impl 实际注入为准.

    覆盖 3 态:
        - 默认(双门都未开):outcome=disabled
        - env 开但 Impl 未注入:outcome=writer_required
        - Impl 已注入 + env 开:outcome=dry_run_ready
    """

    def _base_payload(self) -> dict[str, Any]:
        from my_ai_employee.dashboard.responses import build_status_payload

        return build_status_payload(self._make_ctx())

    @staticmethod
    def _make_ctx() -> DashboardContext:
        return DashboardContext(
            git_head_resolver=lambda: "abc123",
            keychain_probe=lambda _s: False,
            quality_gates=QualityGateSnapshot(pytest="2516 passed / 1 skipped"),
        )

    def test_default_state_outcome_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.responses import build_status_payload

        monkeypatch.delenv(DASHBOARD_WRITE_API_ENV, raising=False)
        monkeypatch.delenv(BUSINESS_WRITER_ENABLED_ENV, raising=False)
        payload = build_status_payload(self._make_ctx())
        ag = payload["approval_gates"]
        assert ag["dashboard_write_api"] is False
        assert ag["business_writer_enabled"] is False
        assert ag["business_writer_env_enabled"] is False
        assert ag["business_writer_impl_injected"] is False
        assert ag["business_writer_ready"] is False
        status = ag["v0_2_53_26_dry_run_status"]
        assert status["first_gate"] == "closed"
        assert status["second_gate"] == "confirm_required_per_action"
        assert status["third_gate"] == "closed"
        assert status["outcome"] == "disabled"

    def test_writer_env_only_outcome_writer_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.responses import build_status_payload

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        payload = build_status_payload(self._make_ctx())
        ag = payload["approval_gates"]
        assert ag["business_writer_env_enabled"] is True
        assert ag["business_writer_impl_injected"] is False
        assert ag["business_writer_ready"] is False
        status = ag["v0_2_53_26_dry_run_status"]
        assert status["first_gate"] == "open"
        assert status["second_gate"] == "confirm_required_per_action"
        assert status["third_gate"] == "closed"
        assert status["outcome"] == "writer_required"

    def test_dashbaord_write_api_only_outcome_writer_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.responses import build_status_payload

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.delenv(BUSINESS_WRITER_ENABLED_ENV, raising=False)
        payload = build_status_payload(self._make_ctx())
        ag = payload["approval_gates"]
        assert ag["dashboard_write_api"] is True
        assert ag["business_writer_enabled"] is False
        status = ag["v0_2_53_26_dry_run_status"]
        assert status["first_gate"] == "open"
        assert status["second_gate"] == "confirm_required_per_action"
        assert status["third_gate"] == "closed"
        assert status["outcome"] == "writer_required"

    def test_both_gates_open_outcome_dry_run_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl
        from my_ai_employee.dashboard.responses import build_status_payload

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        ctx = self._make_ctx().with_business_writer(BusinessWriterImpl())
        payload = build_status_payload(ctx)
        ag = payload["approval_gates"]
        assert ag["dashboard_write_api"] is True
        assert ag["business_writer_enabled"] is True
        assert ag["business_writer_env_enabled"] is True
        assert ag["business_writer_impl_injected"] is True
        assert ag["business_writer_ready"] is True
        status = ag["v0_2_53_26_dry_run_status"]
        assert status["first_gate"] == "open"
        assert status["second_gate"] == "confirm_required_per_action"
        assert status["third_gate"] == "open"
        assert status["outcome"] == "dry_run_ready"


def test_build_tasks_today_payload_counts(dashboard_ctx: DashboardContext) -> None:
    payload = build_tasks_today_payload(dashboard_ctx)
    assert payload["read_only"] is True
    assert payload["total"] == 6
    assert payload["tasks"][0]["count"] == 2
    assert payload["tasks"][1]["count"] == 3
    assert payload["tasks"][2]["count"] == 1


def test_build_outbox_payload_items(dashboard_ctx: DashboardContext) -> None:
    payload = build_outbox_payload(dashboard_ctx)
    assert payload["read_only"] is True
    assert payload["count"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["outbox_id"] == 101


def test_build_notes_pending_payload_items(dashboard_ctx: DashboardContext) -> None:
    payload = build_notes_pending_payload(dashboard_ctx)
    assert payload["count"] == 3
    assert payload["items"][0]["apple_note_id"] == "note-1"


def test_build_finance_anomalies_payload_items(dashboard_ctx: DashboardContext) -> None:
    payload = build_finance_anomalies_payload(dashboard_ctx)
    assert payload["count"] == 1
    assert payload["items"][0]["counterparty"] == "支付宝"


def test_parse_limit_clamps() -> None:
    from my_ai_employee.dashboard.context import parse_limit

    assert parse_limit(None) == 10
    assert parse_limit("5") == 5
    assert parse_limit("0") == 1
    assert parse_limit("999") == 100
    assert parse_limit("bad") == 10


def _fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 — 测试 localhost
        return resp.status, json.loads(resp.read().decode("utf-8"))


@pytest.fixture
def running_server(dashboard_ctx: DashboardContext) -> Generator[str, None, None]:
    server = create_server(dashboard_ctx, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _host, port = server.server_address[:2]
    base = f"http://127.0.0.1:{port}"
    yield base
    server.shutdown()
    thread.join(timeout=2.0)


def test_http_api_status(running_server: str) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{running_server}/api/status",
        headers={"Origin": "null"},
    )
    with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310 — 测试 localhost
        status = resp.status
        cors_origin = resp.headers["Access-Control-Allow-Origin"]
        body = json.loads(resp.read().decode("utf-8"))
    assert status == 200
    assert cors_origin == "null"
    assert body["read_only"] is True
    assert "quality_gates" in body


def test_http_api_tasks_today(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/tasks/today")
    assert status == 200
    assert body["total"] == 6
    assert len(body["tasks"]) == 3


def test_http_api_outbox(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/outbox?limit=5")
    assert status == 200
    assert body["count"] == 2
    assert body["items"][0]["subject"] == "供应商付款确认"


def test_http_api_notes_pending(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/notes/pending")
    assert status == 200
    assert body["count"] == 3
    assert body["items"][0]["title"] == "L2 候选"


def test_http_api_finance_anomalies(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/finance/anomalies")
    assert status == 200
    assert body["count"] == 1
    assert body["items"][0]["amount"] == 1299


def test_http_api_not_found(running_server: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _fetch_json(f"{running_server}/api/unknown")
    assert exc.value.code == 404


def test_http_post_not_allowed(running_server: str) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{running_server}/api/status",
        data=b"{}",
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=2)
    assert exc.value.code == 405


def test_http_options_for_static_file_dashboard(running_server: str) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{running_server}/api/status",
        headers={"Origin": "null"},
        method="OPTIONS",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310 — 测试 localhost
        assert resp.status == 204
        assert resp.headers["Access-Control-Allow-Origin"] == "null"
        assert resp.headers["Allow"] == "GET, OPTIONS"


def test_handler_factory_binds_context(dashboard_ctx: DashboardContext) -> None:
    handler_cls = handler_factory(dashboard_ctx)
    assert handler_cls.dashboard_context is dashboard_ctx
