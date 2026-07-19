"""P1 15 分钟只读 health monitor 回归。"""

from __future__ import annotations

import json
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from scripts import monitor_launchd_health as monitor

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _snapshot(*, healthy: bool, reasons: list[str] | None = None) -> dict[str, Any]:
    return {
        "captured_at": NOW.isoformat(),
        "healthy": healthy,
        "reasons": reasons or [],
        "probe_errors": [],
        "jobs": {
            "com.myaiemployee.agent": {
                "registered": True,
                "pid": None,
                "required_running": False,
            },
            "com.myaiemployee.imap-sync": {
                "registered": True,
                "pid": None,
                "required_running": False,
            },
            "com.myaiemployee.menu-bar": {
                "registered": True,
                "pid": 34582,
                "required_running": True,
            },
            "com.myaiemployee.dashboard": {
                "registered": True,
                "pid": 34591,
                "required_running": True,
            },
        },
        "dashboard_listener": {"port": 8765, "loopback_listening": True, "pids": [34594]},
    }


def _collector(*snapshots: dict[str, Any]) -> Callable[[], dict[str, Any]]:
    pending = list(snapshots)

    def collect() -> dict[str, Any]:
        return pending.pop(0) if pending else snapshots[-1]

    return collect


def _health_probe() -> tuple[bool, str | None]:
    return True, None


def _read_json(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return cast(dict[str, object], raw)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        assert isinstance(raw, dict)
        records.append(cast(dict[str, object], raw))
    return records


def test_healthy_first_attempt_resets_prior_failure_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "health"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "schema_version": monitor.STATE_SCHEMA_VERSION,
                "failure_streak": 2,
                "alert_open": False,
            }
        ),
        encoding="utf-8",
    )

    result = monitor.run_monitor(
        state_dir=state_dir,
        collect_snapshot_fn=_collector(_snapshot(healthy=True)),
        health_probe=_health_probe,
        now_fn=lambda: NOW,
    )

    assert result.healthy is True
    assert result.attempts == 1
    assert result.failure_streak == 0
    assert result.alert_event is None
    state = _read_json(state_dir / "state.json")
    assert state["failure_streak"] == 0
    assert state["alert_open"] is False
    assert len(_read_jsonl(state_dir / "samples.jsonl")) == 1
    assert not (state_dir / "alerts.jsonl").exists()


def test_failed_first_attempt_retries_once_and_recovers(tmp_path: Path) -> None:
    delays: list[float] = []

    result = monitor.run_monitor(
        state_dir=tmp_path / "health",
        collect_snapshot_fn=_collector(
            _snapshot(healthy=False, reasons=["not_running:com.myaiemployee.dashboard"]),
            _snapshot(healthy=True),
        ),
        health_probe=_health_probe,
        sleep_fn=delays.append,
        now_fn=lambda: NOW,
    )

    assert result.healthy is True
    assert result.attempts == 2
    assert result.failure_streak == 0
    assert delays == [monitor.RETRY_DELAY_SECONDS]
    sample = _read_jsonl(tmp_path / "health" / "samples.jsonl")[0]
    assert sample["recovered_by_retry"] is True


def test_three_failed_cycles_open_one_structured_alert(tmp_path: Path) -> None:
    state_dir = tmp_path / "health"
    failed = _snapshot(healthy=False, reasons=["dashboard_listener_missing"])

    for expected_streak in (1, 2, 3):
        result = monitor.run_monitor(
            state_dir=state_dir,
            collect_snapshot_fn=_collector(failed, failed),
            health_probe=_health_probe,
            sleep_fn=lambda _seconds: None,
            now_fn=lambda: NOW,
        )
        assert result.healthy is False
        assert result.failure_streak == expected_streak

    assert _read_jsonl(state_dir / "alerts.jsonl") == [
        {
            "at": NOW.isoformat(),
            "event": "opened",
            "failure_streak": 3,
            "reasons": ["dashboard_listener_missing"],
            "schema_version": monitor.STATE_SCHEMA_VERSION,
        }
    ]
    state = _read_json(state_dir / "state.json")
    assert state["alert_open"] is True


def test_success_resolves_open_alert_once(tmp_path: Path) -> None:
    state_dir = tmp_path / "health"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "schema_version": monitor.STATE_SCHEMA_VERSION,
                "failure_streak": 3,
                "alert_open": True,
            }
        ),
        encoding="utf-8",
    )

    result = monitor.run_monitor(
        state_dir=state_dir,
        collect_snapshot_fn=_collector(_snapshot(healthy=True)),
        health_probe=_health_probe,
        now_fn=lambda: NOW,
    )

    assert result.alert_event == "resolved"
    assert result.failure_streak == 0
    alert = _read_jsonl(state_dir / "alerts.jsonl")[0]
    assert alert["event"] == "resolved"
    assert alert["failure_streak"] == 3
    assert _read_json(state_dir / "state.json")["alert_open"] is False


def test_corrupt_prior_state_fails_safe_and_writes_private_replacement(tmp_path: Path) -> None:
    state_dir = tmp_path / "health"
    state_dir.mkdir()
    state_path = state_dir / "state.json"
    state_path.write_text("not-json", encoding="utf-8")

    result = monitor.run_monitor(
        state_dir=state_dir,
        collect_snapshot_fn=_collector(_snapshot(healthy=True)),
        health_probe=_health_probe,
        now_fn=lambda: NOW,
    )

    assert result.healthy is True
    state = _read_json(state_path)
    assert state["failure_streak"] == 0
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((state_dir / "samples.jsonl").stat().st_mode) == 0o600


class _FakeResponse:
    def __init__(self, *, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, _amt: int | None = None) -> bytes:
        return self._body


class _FakeConnection:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requested: tuple[str, str] | None = None
        self.closed = False

    def request(self, method: str, url: str) -> None:
        self.requested = method, url

    def getresponse(self) -> _FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def test_loopback_health_probe_uses_fixed_host_port_and_contract() -> None:
    connection = _FakeConnection(_FakeResponse(status=200, body=b'{"ok": true, "read_only": true}'))
    received: list[tuple[str, int, float]] = []

    def factory(host: str, port: int, timeout: float) -> _FakeConnection:
        received.append((host, port, timeout))
        return connection

    assert monitor.probe_dashboard_health(connection_factory=factory) == (True, None)
    assert received == [("127.0.0.1", 8765, monitor.HEALTH_TIMEOUT_SECONDS)]
    assert connection.requested == ("GET", "/health")
    assert connection.closed is True


def test_loopback_health_failure_is_redacted(tmp_path: Path) -> None:
    response = _FakeResponse(status=200, body=b'{"ok": true, "read_only": false}')
    connection = _FakeConnection(response)

    assert monitor.probe_dashboard_health(connection_factory=lambda *_args: connection) == (
        False,
        "dashboard_health_contract_invalid",
    )
    result = monitor.run_monitor(
        state_dir=tmp_path / "health",
        collect_snapshot_fn=_collector(_snapshot(healthy=True)),
        health_probe=lambda: (False, "dashboard_health_unavailable"),
        sleep_fn=lambda _seconds: None,
        now_fn=lambda: NOW,
    )
    assert result.healthy is False
    rendered = (tmp_path / "health" / "samples.jsonl").read_text(encoding="utf-8")
    assert "dashboard_health_unavailable" in rendered
    assert "127.0.0.1" not in rendered


def test_busy_lock_skips_without_new_sample(tmp_path: Path) -> None:
    state_dir = tmp_path / "health"
    monitor.ensure_state_directory(state_dir)

    with monitor.acquire_monitor_lock(state_dir=state_dir):
        result = monitor.run_monitor(
            state_dir=state_dir,
            collect_snapshot_fn=_collector(_snapshot(healthy=True)),
            health_probe=_health_probe,
            now_fn=lambda: NOW,
        )

    assert result.skipped is True
    assert result.attempts == 0
    assert not (state_dir / "samples.jsonl").exists()


def test_monitor_source_keeps_non_restart_boundary() -> None:
    source = Path(monitor.__file__).read_text(encoding="utf-8")
    for forbidden in ("kickstart", "bootout", "launchctl ", "SMTP", "IMAP"):
        assert forbidden not in source
