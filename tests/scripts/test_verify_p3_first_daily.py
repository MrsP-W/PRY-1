"""verify_p3_first_daily 窗口门控回归。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts import p3_burn_in_report as burn_in
from scripts.verify_p3_first_daily import FIRST_DAILY_GATE, main, verify_first_daily


def _seed_epoch(state_dir: Path, started_at: datetime) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "kind": "p3_burn_in_epoch",
                "schema_version": 1,
                "started_at": started_at.isoformat(),
                "time_basis": "UTC",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _health(at: datetime) -> dict[str, Any]:
    return {
        "schema_version": burn_in.JOURNAL_SCHEMA_VERSION,
        "at": at.isoformat(),
        "attempts": 1,
        "recovered_by_retry": False,
        "sample": {
            "schema_version": burn_in.JOURNAL_SCHEMA_VERSION,
            "healthy": True,
            "reasons": [],
            "jobs": {
                "com.myaiemployee.menu-bar": {
                    "registered": True,
                    "required_running": True,
                    "pid": 1,
                },
                "com.myaiemployee.dashboard": {
                    "registered": True,
                    "required_running": True,
                    "pid": 2,
                },
            },
            "dashboard_listener": {"loopback_listening": True, "port": 8765, "pids": [2]},
            "dashboard_health": {"ok": True, "read_only": True},
            "error_log_metadata": {
                "menu_bar": {"exists": True, "size_bytes": 0, "mtime_epoch": 1},
                "dashboard": {"exists": True, "size_bytes": 0, "mtime_epoch": 1},
            },
        },
    }


def _news(at: datetime) -> dict[str, Any]:
    return {
        "schema_version": burn_in.JOURNAL_SCHEMA_VERSION,
        "at": at.isoformat(),
        "outcome": "success",
        "success": True,
        "degraded": False,
        "item_count": 1,
        "sources": [{"source_id": "cn-ai-news", "status": "ok", "item_count": 1}],
    }


def test_too_early_before_gate(tmp_path: Path) -> None:
    early = FIRST_DAILY_GATE - timedelta(hours=1)
    out = verify_first_daily(now=early, force=False, state_dir=tmp_path / "burn-in")
    assert out["result"] == "too_early"
    assert out["ok"] is False


def test_pass_after_gate_with_complete_utc_day(tmp_path: Path) -> None:
    app = tmp_path / "app"
    state = app / "burn-in"
    health = app / "health"
    news = app / "news"
    day0 = datetime(2026, 7, 20, 19, 4, 33, 499091, tzinfo=UTC)
    _seed_epoch(state, day0)
    health.mkdir(parents=True)
    news.mkdir(parents=True)
    samples = [
        _health(day0 + timedelta(minutes=15)),
        _health(datetime(2026, 7, 21, 1, 0, tzinfo=UTC)),
        _health(datetime(2026, 7, 21, 12, 0, tzinfo=UTC)),
        _health(datetime(2026, 7, 21, 23, 0, tzinfo=UTC)),
    ]
    (health / "samples.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in samples),
        encoding="utf-8",
    )
    (health / "alerts.jsonl").write_text("", encoding="utf-8")
    runs = [
        _news(day0 + timedelta(minutes=30)),
        _news(datetime(2026, 7, 21, 2, 0, tzinfo=UTC)),
        _news(datetime(2026, 7, 21, 14, 0, tzinfo=UTC)),
    ]
    (news / "runs.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in runs),
        encoding="utf-8",
    )

    after = datetime(2026, 7, 22, 0, 5, tzinfo=UTC)
    out = verify_first_daily(
        now=after,
        force=False,
        app_support_dir=app,
        state_dir=state,
        health_dir=health,
        news_dir=news,
    )
    assert out["result"] == "pass"
    assert out["ok"] is True
    assert out["daily_written"] >= 1
    assert out["day0_ok"] is True


def test_cli_too_early_exit_code() -> None:
    assert main([]) == 3
