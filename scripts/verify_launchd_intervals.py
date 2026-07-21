#!/usr/bin/env python3
"""受控验证 health/news LaunchAgent 间隔（只读 journal，不重置 P3）。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _parse_ats(path: Path, *, key: str = "at") -> list[datetime]:
    if not path.exists():
        return []
    out: list[datetime] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        at = raw.get(key)
        if not isinstance(at, str):
            continue
        out.append(datetime.fromisoformat(at.replace("Z", "+00:00")))
    return out


def _gaps_minutes(ats: list[datetime]) -> list[float]:
    return [(b - a).total_seconds() / 60.0 for a, b in zip(ats, ats[1:], strict=False)]


def observe(
    *,
    app_support: Path,
    since: datetime,
    wait_seconds: int,
    health_max_gap_min: float,
    news_max_gap_min: float,
) -> dict[str, Any]:
    health_path = app_support / "health" / "samples.jsonl"
    news_path = app_support / "news" / "runs.jsonl"
    started = datetime.now(UTC)
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    ended = datetime.now(UTC)

    health_ats = [t for t in _parse_ats(health_path) if t >= since]
    news_ats = [t for t in _parse_ats(news_path) if t >= since]
    # Prefer samples that landed during this observation window when waiting.
    if wait_seconds > 0:
        health_window = [t for t in health_ats if t >= started]
        news_window = [t for t in news_ats if t >= started]
    else:
        health_window = health_ats[-6:]
        news_window = news_ats[-4:]

    health_gaps = _gaps_minutes(health_window)
    news_gaps = _gaps_minutes(news_window)
    health_ok = bool(health_window) and (
        not health_gaps or max(health_gaps) <= health_max_gap_min
    )
    # News may not fire in a short wait; only judge if >=2 samples in window/since.
    news_ok = True
    if len(news_window) >= 2:
        news_ok = max(news_gaps) <= news_max_gap_min
    elif wait_seconds >= 3700:
        news_ok = False

    return {
        "schema_version": 1,
        "action": "verify_launchd_intervals",
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "wait_seconds": wait_seconds,
        "since": since.isoformat(),
        "health": {
            "samples": [t.isoformat() for t in health_window],
            "gaps_min": [round(g, 2) for g in health_gaps],
            "max_gap_min": round(max(health_gaps), 2) if health_gaps else None,
            "ok": health_ok,
            "limit_min": health_max_gap_min,
        },
        "news": {
            "runs": [t.isoformat() for t in news_window],
            "gaps_min": [round(g, 2) for g in news_gaps],
            "max_gap_min": round(max(news_gaps), 2) if news_gaps else None,
            "ok": news_ok,
            "limit_min": news_max_gap_min,
        },
        "ok": health_ok and news_ok,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="受控验证 LaunchAgent 间隔")
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="ISO 时间；默认=现在（仅看等待窗内新样本）",
    )
    parser.add_argument("--health-max-gap-min", type=float, default=20.0)
    parser.add_argument("--news-max-gap-min", type=float, default=90.0)
    parser.add_argument(
        "--app-support-dir",
        type=Path,
        default=Path.home() / "Library" / "Application Support" / "MyAIEmployee",
    )
    args = parser.parse_args(argv)
    since = (
        datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        if args.since
        else datetime.now(UTC)
    )
    payload = observe(
        app_support=args.app_support_dir,
        since=since,
        wait_seconds=args.wait_seconds,
        health_max_gap_min=args.health_max_gap_min,
        news_max_gap_min=args.news_max_gap_min,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
