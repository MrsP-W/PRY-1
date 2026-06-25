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
from my_ai_employee.dashboard.responses import build_status_payload, build_tasks_today_payload
from my_ai_employee.dashboard.server import create_server


class _CountingDraft:
    def get_pending_draft_count(self) -> int:
        return 2


class _CountingConfirm:
    def get_pending_confirm_count(self) -> int:
        return 3

    def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
        return []

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
        return []


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


def test_build_tasks_today_payload_counts(dashboard_ctx: DashboardContext) -> None:
    payload = build_tasks_today_payload(dashboard_ctx)
    assert payload["read_only"] is True
    assert payload["total"] == 6
    assert payload["tasks"][0]["count"] == 2
    assert payload["tasks"][1]["count"] == 3
    assert payload["tasks"][2]["count"] == 1


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
    status, body = _fetch_json(f"{running_server}/api/status")
    assert status == 200
    assert body["read_only"] is True
    assert "quality_gates" in body


def test_http_api_tasks_today(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/tasks/today")
    assert status == 200
    assert body["total"] == 6
    assert len(body["tasks"]) == 3


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


def test_handler_factory_binds_context(dashboard_ctx: DashboardContext) -> None:
    handler_cls = handler_factory(dashboard_ctx)
    assert handler_cls.dashboard_context is dashboard_ctx
