"""verify_launchd_intervals 回归。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.verify_launchd_intervals import observe


def test_observe_health_gaps(tmp_path: Path) -> None:
    app = tmp_path / "app"
    health = app / "health"
    news = app / "news"
    health.mkdir(parents=True)
    news.mkdir(parents=True)
    t0 = datetime(2026, 7, 21, 18, 0, tzinfo=UTC)
    samples = [t0, t0 + timedelta(minutes=10), t0 + timedelta(minutes=20)]
    (health / "samples.jsonl").write_text(
        "".join(
            json.dumps({"at": t.isoformat(), "sample": {"healthy": True}}) + "\n" for t in samples
        ),
        encoding="utf-8",
    )
    (news / "runs.jsonl").write_text(
        json.dumps({"at": samples[-1].isoformat()}) + "\n",
        encoding="utf-8",
    )
    out = observe(
        app_support=app,
        since=t0,
        wait_seconds=0,
        health_max_gap_min=20.0,
        news_max_gap_min=90.0,
        now_fn=lambda: t0 + timedelta(minutes=21),
    )
    assert out["ok"] is True
    assert out["health"]["max_gap_min"] == 10.0
    assert out["health"]["tail_age_min"] == 1.0
    assert out["news"]["tail_age_min"] == 1.0


def test_observe_rejects_stale_tail_without_interior_gap(tmp_path: Path) -> None:
    app = tmp_path / "app"
    health = app / "health"
    news = app / "news"
    health.mkdir(parents=True)
    news.mkdir(parents=True)
    t0 = datetime(2026, 7, 21, 18, 0, tzinfo=UTC)
    (health / "samples.jsonl").write_text(
        json.dumps({"at": t0.isoformat(), "sample": {"healthy": True}}) + "\n",
        encoding="utf-8",
    )
    (news / "runs.jsonl").write_text(
        json.dumps({"at": t0.isoformat()}) + "\n",
        encoding="utf-8",
    )

    out = observe(
        app_support=app,
        since=t0,
        wait_seconds=0,
        health_max_gap_min=20.0,
        news_max_gap_min=90.0,
        now_fn=lambda: t0 + timedelta(minutes=91),
    )

    assert out["ok"] is False
    assert out["health"] == {
        "samples": [t0.isoformat()],
        "gaps_min": [],
        "max_gap_min": None,
        "tail_age_min": 91.0,
        "ok": False,
        "limit_min": 20.0,
    }
    assert out["news"]["tail_age_min"] == 91.0
    assert out["news"]["ok"] is False
