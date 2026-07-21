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


def _write_dense_journals(
    *,
    health: Path,
    news: Path,
    start: datetime,
    end: datetime,
) -> None:
    health.mkdir(parents=True, exist_ok=True)
    news.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        samples.append(_health(cursor))
        if (cursor - start).total_seconds() % 3600 < 900:
            runs.append(_news(cursor))
        cursor += timedelta(minutes=15)
    if not runs:
        runs.append(_news(start))
    (health / "samples.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in samples),
        encoding="utf-8",
    )
    (health / "alerts.jsonl").write_text("", encoding="utf-8")
    (news / "runs.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in runs),
        encoding="utf-8",
    )


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
    after = datetime(2026, 7, 22, 0, 5, tzinfo=UTC)
    _seed_epoch(state, day0)
    _write_dense_journals(health=health, news=news, start=day0, end=after)

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
    assert out["attention_ok"] is True
    assert out["daily_written"] >= 1
    assert out["day0_ok"] is True


def test_fail_attention_even_with_daily_report(tmp_path: Path) -> None:
    app = tmp_path / "app"
    state = app / "burn-in"
    health = app / "health"
    news = app / "news"
    day0 = datetime(2026, 7, 20, 19, 4, 33, 499091, tzinfo=UTC)
    after = datetime(2026, 7, 22, 0, 5, tzinfo=UTC)
    _seed_epoch(state, day0)
    health.mkdir(parents=True)
    news.mkdir(parents=True)
    # 故意留下超大间隔 → health_sample_gap / news_run_gap
    samples = [
        _health(day0 + timedelta(minutes=15)),
        _health(datetime(2026, 7, 21, 12, 0, tzinfo=UTC)),
    ]
    (health / "samples.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in samples),
        encoding="utf-8",
    )
    (health / "alerts.jsonl").write_text("", encoding="utf-8")
    (news / "runs.jsonl").write_text(
        json.dumps(_news(day0 + timedelta(minutes=30)), sort_keys=True) + "\n",
        encoding="utf-8",
    )

    out = verify_first_daily(
        now=after,
        force=False,
        app_support_dir=app,
        state_dir=state,
        health_dir=health,
        news_dir=news,
    )
    assert out["ok"] is False
    assert out["result"] == "fail_attention"
    assert out["attention_ok"] is False
    assert out["daily_written"] >= 1
    assert "health_sample_gap" in out["attention"]


def test_cli_too_early_exit_code() -> None:
    assert main([]) == 3
