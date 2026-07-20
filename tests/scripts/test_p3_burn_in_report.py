"""P3 burn-in 报告器的本地、脱敏和窗口边界回归。"""

from __future__ import annotations

import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import p3_burn_in_report as burn_in

EPOCH = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def _jsonl(path: Path, records: list[dict[str, Any]], *, tail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    path.write_text(rendered + tail, encoding="utf-8")


def _times(start: datetime, end: datetime, *, minutes: int) -> list[datetime]:
    result: list[datetime] = []
    current = start
    while current < end:
        result.append(current)
        current += timedelta(minutes=minutes)
    return result


def _health_record(
    at: datetime,
    *,
    healthy: bool = True,
    menu_pid: int = 101,
    dashboard_pid: int = 202,
    recovered_by_retry: bool = False,
    reasons: list[str] | None = None,
    stderr_size: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": burn_in.JOURNAL_SCHEMA_VERSION,
        "at": at.isoformat(),
        "attempts": 2 if recovered_by_retry else 1,
        "recovered_by_retry": recovered_by_retry,
        "sample": {
            "schema_version": burn_in.JOURNAL_SCHEMA_VERSION,
            "healthy": healthy,
            "reasons": reasons or [],
            "jobs": {
                "com.myaiemployee.menu-bar": {
                    "registered": True,
                    "required_running": True,
                    "pid": menu_pid,
                },
                "com.myaiemployee.dashboard": {
                    "registered": True,
                    "required_running": True,
                    "pid": dashboard_pid,
                },
            },
            "dashboard_listener": {
                "port": 8765,
                "loopback_listening": True,
                "pids": [dashboard_pid + 1],
            },
            "dashboard_health": {"ok": True, "read_only": True},
            "error_log_metadata": {
                "menu_bar": {
                    "exists": True,
                    "size_bytes": stderr_size,
                    "mtime_epoch": 1_784_000_000 + stderr_size,
                },
                "dashboard": {
                    "exists": True,
                    "size_bytes": stderr_size,
                    "mtime_epoch": 1_784_000_000 + stderr_size,
                },
            },
        },
    }


def _alert_record(
    at: datetime, event: str, *, reason: str = "dashboard_listener_missing"
) -> dict[str, Any]:
    return {
        "schema_version": burn_in.JOURNAL_SCHEMA_VERSION,
        "at": at.isoformat(),
        "event": event,
        "failure_streak": 3,
        "reasons": [reason],
    }


def _news_record(
    at: datetime,
    *,
    outcome: str = "success",
    success: bool = True,
    degraded: bool = False,
) -> dict[str, Any]:
    item_count = 3
    sources: list[dict[str, Any]] = [
        {"source_id": "public_ai", "status": "ok", "item_count": item_count}
    ]
    if outcome == "all_sources_failed":
        sources = [{"source_id": "public_ai", "status": "error", "item_count": 0}]
    elif outcome in {"overlap", "runtime_error"}:
        item_count = 0
        sources = []
    return {
        "schema_version": burn_in.JOURNAL_SCHEMA_VERSION,
        "at": at.isoformat(),
        "outcome": outcome,
        "success": success,
        "degraded": degraded,
        "item_count": item_count,
        "sources": sources,
    }


def _seed_continuous_journals(app_support: Path, start: datetime, end: datetime) -> None:
    _jsonl(
        app_support / "health" / "samples.jsonl",
        [_health_record(at) for at in _times(start, end, minutes=15)],
    )
    _jsonl(
        app_support / "news" / "runs.jsonl",
        [_news_record(at) for at in _times(start, end, minutes=60)],
    )


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_start_creates_private_marker_and_refuses_overwrite(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"

    started_at = burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: EPOCH)

    marker = app_support / "burn-in" / "state.json"
    assert started_at == EPOCH
    assert _load(marker)["started_at"] == EPOCH.isoformat()
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    assert stat.S_IMODE(marker.parent.stat().st_mode) == 0o700
    with pytest.raises(burn_in.BurnInAlreadyStartedError):
        burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: EPOCH + timedelta(days=1))
    assert _load(marker)["started_at"] == EPOCH.isoformat()


def test_start_uses_exclusive_create_under_concurrent_calls(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    barrier = threading.Barrier(2)
    first = EPOCH
    second = EPOCH + timedelta(seconds=1)

    def start_at(moment: datetime) -> datetime | Exception:
        try:
            return burn_in.start_burn_in(
                app_support_dir=app_support,
                now_fn=lambda: (barrier.wait(), moment)[1],
            )
        except Exception as exc:  # noqa: BLE001 — 检查并发调用只能有一个 winner。
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(start_at, (first, second)))

    winners = [outcome for outcome in outcomes if isinstance(outcome, datetime)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
    assert len(winners) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], burn_in.BurnInAlreadyStartedError)
    assert _load(app_support / "burn-in" / "state.json")["started_at"] == winners[0].isoformat()


def test_report_without_marker_is_safe_and_does_not_create_evidence(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: EPOCH)

    assert result.to_dict() == {
        "schema_version": burn_in.SCHEMA_VERSION,
        "action": "report",
        "started": False,
        "result": "not_started",
    }
    assert not app_support.exists()


def test_epoch_excludes_old_records_and_current_day_is_not_written(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: EPOCH)
    report_at = EPOCH + timedelta(hours=1)
    _jsonl(
        app_support / "health" / "samples.jsonl",
        [
            _health_record(
                EPOCH - timedelta(days=1),
                healthy=False,
                reasons=["old_private_payload"],
            ),
            *[_health_record(at) for at in _times(EPOCH, report_at, minutes=15)],
        ],
    )
    _jsonl(
        app_support / "news" / "runs.jsonl",
        [_news_record(at) for at in _times(EPOCH, report_at, minutes=60)],
    )

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: report_at)

    assert result.started is True
    assert result.status == "collecting"
    assert result.daily_written == 0
    assert not (app_support / "burn-in" / "daily").exists()


def test_complete_days_and_weeks_use_only_marker_after_evidence(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: EPOCH)
    report_at = datetime(2026, 7, 21, 0, 10, tzinfo=UTC)
    _seed_continuous_journals(app_support, EPOCH, report_at)
    _jsonl(
        app_support / "health" / "alerts.jsonl",
        [_alert_record(EPOCH - timedelta(days=2), "opened", reason="old_private_payload")],
    )

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: report_at)

    daily = app_support / "burn-in" / "daily" / "2026-07-13.json"
    weekly = app_support / "burn-in" / "weekly" / "2026-W29.json"
    assert result.status == "collecting"
    assert result.daily_written == 8
    assert result.weekly_written == 1
    assert _load(daily)["status"] == "pass"
    assert _load(weekly)["period"]["complete"] is True
    assert "old_private_payload" not in weekly.read_text(encoding="utf-8")
    assert stat.S_IMODE(daily.stat().st_mode) == 0o600
    assert stat.S_IMODE(daily.parent.stat().st_mode) == 0o700


def test_bad_jsonl_and_partial_tail_are_isolated_without_payload_leak(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: EPOCH)
    report_at = EPOCH + timedelta(days=2)
    _seed_continuous_journals(app_support, EPOCH, report_at)
    _jsonl(
        app_support / "health" / "samples.jsonl",
        [_health_record(at) for at in _times(EPOCH, report_at, minutes=15)],
        tail='{"private_error":"do-not-copy"',
    )

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: report_at)

    report = app_support / "burn-in" / "daily" / "2026-07-13.json"
    payload = _load(report)
    assert result.status == "attention"
    assert payload["input_integrity"]["health_sample_invalid_lines"] == 1
    assert "input_integrity_issue" in result.attention
    assert "do-not-copy" not in report.read_text(encoding="utf-8")


def test_semantically_invalid_journals_cannot_fill_burn_in_evidence(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    start = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    report_at = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: start)
    health_records = [_health_record(at) for at in _times(start, report_at, minutes=15)]
    health_records[99]["sample"]["reasons"] = ["unexpected_healthy_reason"]
    health_records[100] = {
        "schema_version": burn_in.JOURNAL_SCHEMA_VERSION,
        "at": health_records[100]["at"],
        "attempts": 1,
        "recovered_by_retry": False,
        "sample": {"schema_version": burn_in.JOURNAL_SCHEMA_VERSION, "healthy": True},
    }
    _jsonl(app_support / "health" / "samples.jsonl", health_records)
    news_records = [_news_record(at) for at in _times(start, report_at, minutes=60)]
    news_records[25].pop("outcome")
    news_records[26]["outcome"] = "all_sources_failed"
    _jsonl(app_support / "news" / "runs.jsonl", news_records)

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: report_at)

    report = _load(app_support / "burn-in" / "daily" / "2026-07-21.json")
    assert result.status == "attention"
    assert "input_integrity_issue" in result.attention
    assert report["input_integrity"]["health_sample_invalid_lines"] == 2
    assert report["input_integrity"]["news_run_invalid_lines"] == 2


def test_unavailable_journal_blocks_pass_instead_of_being_silently_ignored(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: EPOCH)
    (app_support / "health" / "samples.jsonl").mkdir(parents=True)
    _jsonl(app_support / "news" / "runs.jsonl", [_news_record(EPOCH)])

    result = burn_in.run_report(
        app_support_dir=app_support, now_fn=lambda: EPOCH + timedelta(hours=1)
    )

    assert result.status == "attention"
    assert "input_integrity_issue" in result.attention


def test_overlap_with_retained_cache_count_is_valid_attention(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: EPOCH)
    overlap = _news_record(EPOCH, outcome="overlap", success=False)
    overlap["item_count"] = 48
    _jsonl(app_support / "health" / "samples.jsonl", [_health_record(EPOCH)])
    _jsonl(app_support / "news" / "runs.jsonl", [overlap])

    result = burn_in.run_report(
        app_support_dir=app_support, now_fn=lambda: EPOCH + timedelta(hours=1)
    )

    assert result.status == "attention"
    assert "news_overlap" in result.attention
    assert "input_integrity_issue" not in result.attention


def test_report_surfaces_pid_stderr_alert_and_news_outcomes(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    start = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    report_at = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: start)
    health_records: list[dict[str, Any]] = []
    for at in _times(start, report_at, minutes=15):
        changed = at >= start + timedelta(hours=12)
        health_records.append(
            _health_record(
                at,
                menu_pid=303 if changed else 101,
                stderr_size=7 if changed else 0,
                recovered_by_retry=at == start + timedelta(hours=1),
            )
        )
    _jsonl(app_support / "health" / "samples.jsonl", health_records)
    _jsonl(
        app_support / "health" / "alerts.jsonl",
        [
            _alert_record(start + timedelta(hours=3), "opened"),
            _alert_record(start + timedelta(hours=4), "resolved"),
        ],
    )
    news_records = [_news_record(at) for at in _times(start, report_at, minutes=60)]
    news_records[2] = _news_record(
        start + timedelta(hours=2), outcome="degraded", success=True, degraded=True
    )
    news_records[3] = _news_record(
        start + timedelta(hours=3), outcome="all_sources_failed", success=False
    )
    news_records[4] = _news_record(start + timedelta(hours=4), outcome="overlap", success=False)
    _jsonl(app_support / "news" / "runs.jsonl", news_records)

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: report_at)

    report = _load(app_support / "burn-in" / "daily" / "2026-07-21.json")
    assert result.status == "attention"
    assert report["health"]["samples"]["recovered_by_retry"] == 0
    assert report["health"]["pid_changes"]["com.myaiemployee.menu-bar"] == 0
    assert report["health"]["stderr_metadata"]["changes"]["menu_bar"] == 0
    # 7/20 carries the transition and all exceptional events; it is retained as a partial
    # epoch day only in the global result, not as a complete daily artifact.
    assert "health_alert_opened" in result.attention
    assert "news_degraded" in result.attention
    assert "news_failure" in result.attention
    assert "news_overlap" in result.attention


def test_complete_period_reports_expose_pid_stderr_alert_and_news_outcomes(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    start = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    report_at = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: start)
    health_records: list[dict[str, Any]] = []
    for at in _times(start, report_at, minutes=15):
        changed = at >= datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
        health_records.append(
            _health_record(
                at,
                menu_pid=303 if changed else 101,
                stderr_size=7 if changed else 0,
                recovered_by_retry=at == datetime(2026, 7, 21, 1, 0, tzinfo=UTC),
            )
        )
    _jsonl(app_support / "health" / "samples.jsonl", health_records)
    _jsonl(
        app_support / "health" / "alerts.jsonl",
        [
            _alert_record(datetime(2026, 7, 21, 3, 0, tzinfo=UTC), "opened"),
            _alert_record(datetime(2026, 7, 21, 4, 0, tzinfo=UTC), "resolved"),
        ],
    )
    news_records = [_news_record(at) for at in _times(start, report_at, minutes=60)]
    base = datetime(2026, 7, 21, 0, 0, tzinfo=UTC)
    for offset, record in enumerate(
        (
            _news_record(
                base + timedelta(hours=2), outcome="degraded", success=True, degraded=True
            ),
            _news_record(base + timedelta(hours=3), outcome="all_sources_failed", success=False),
            _news_record(base + timedelta(hours=4), outcome="overlap", success=False),
        )
    ):
        news_records[36 + 2 + offset] = record
    _jsonl(app_support / "news" / "runs.jsonl", news_records)

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: report_at)

    report = _load(app_support / "burn-in" / "daily" / "2026-07-21.json")
    assert result.status == "attention"
    assert report["status"] == "attention"
    assert report["health"]["samples"]["recovered_by_retry"] == 1
    assert report["health"]["pid_changes"]["com.myaiemployee.menu-bar"] == 1
    assert report["health"]["stderr_metadata"]["changes"]["menu_bar"] == 1
    assert report["health"]["alerts"] == {
        "opened": 1,
        "resolved": 1,
        "reason_counts": {"dashboard_listener_missing": 2},
    }
    assert report["news"]["runs"]["degraded"] == 1
    assert report["news"]["runs"]["failure"] == 1
    assert report["news"]["runs"]["overlap"] == 1


def test_long_gap_is_attention_without_assuming_96_samples(tmp_path: Path) -> None:
    app_support = tmp_path / "app-support"
    start = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    report_at = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: start)
    _jsonl(
        app_support / "health" / "samples.jsonl",
        [_health_record(start), _health_record(report_at - timedelta(minutes=15))],
    )
    _jsonl(
        app_support / "news" / "runs.jsonl",
        [_news_record(start), _news_record(report_at - timedelta(minutes=60))],
    )

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: report_at)

    assert result.status == "attention"
    assert "health_sample_gap" in result.attention
    assert "news_run_gap" in result.attention


def test_pass_requires_thirty_days_without_attention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_support = tmp_path / "app-support"
    burn_in.start_burn_in(app_support_dir=app_support, now_fn=lambda: EPOCH)
    report_at = EPOCH + timedelta(days=30)
    _jsonl(app_support / "health" / "samples.jsonl", [_health_record(EPOCH)])
    _jsonl(app_support / "news" / "runs.jsonl", [_news_record(EPOCH)])
    monkeypatch.setattr(burn_in, "HEALTH_GAP_SECONDS", 31 * 24 * 60 * 60)
    monkeypatch.setattr(burn_in, "NEWS_GAP_SECONDS", 31 * 24 * 60 * 60)

    result = burn_in.run_report(app_support_dir=app_support, now_fn=lambda: report_at)

    assert result.status == "pass"
    assert result.progress is not None
    assert result.progress["seven_day_unattended"]["eligible"] is True
    assert result.progress["thirty_day_no_p0_p1"]["eligible"] is True


def test_cli_and_source_keep_read_only_non_service_boundary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app_support = tmp_path / "app-support"

    assert burn_in.main(["start", "--app-support-dir", str(app_support)]) == 0
    start_payload = json.loads(capsys.readouterr().out)
    assert start_payload["result"] == "started"
    assert burn_in.main(["--app-support-dir", str(app_support), "report"]) == 0
    report_payload = json.loads(capsys.readouterr().out)
    assert report_payload["result"] == "reported"
    source = Path(burn_in.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "launchctl",
        "SMTP",
        "IMAP",
        "subprocess",
        "requests",
        "urllib",
        "smtplib",
    ):
        assert forbidden not in source
