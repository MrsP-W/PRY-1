#!/usr/bin/env python3
"""核验 P3 首份完整 UTC 日报（最早 2026-07-22T00:00Z）。

默认 fail-closed：未到窗口直接退出，不重置 Day0，不触碰 SMTP。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# launchd / 直接 python scripts/... 时保证可 import scripts.*
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import p3_burn_in_report as burn_in  # noqa: E402

FIRST_DAILY_GATE = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)
EXPECTED_DAY0_PREFIX = "2026-07-20T19:04:33"


def verify_first_daily(
    *,
    now: datetime | None = None,
    force: bool = False,
    app_support_dir: Path | None = None,
    state_dir: Path | None = None,
    health_dir: Path | None = None,
    news_dir: Path | None = None,
) -> dict[str, Any]:
    """返回结构化核验结果；未到窗口且未 force 时 result=too_early。"""

    current = burn_in._normalise_utc(now or burn_in._now_utc())
    if not force and current < FIRST_DAILY_GATE:
        return {
            "schema_version": 1,
            "action": "verify_first_daily",
            "result": "too_early",
            "gate": FIRST_DAILY_GATE.isoformat(),
            "now": current.isoformat(),
            "ok": False,
        }

    report = burn_in.run_report(
        app_support_dir=app_support_dir,
        state_dir=state_dir,
        health_dir=health_dir,
        news_dir=news_dir,
        now_fn=lambda: current,
    )
    epoch = report.epoch_started_at.isoformat() if report.epoch_started_at else None
    day0_ok = bool(epoch and epoch.startswith(EXPECTED_DAY0_PREFIX))
    daily_ok = report.daily_written >= 1
    ok = bool(report.started and day0_ok and daily_ok)
    return {
        "schema_version": 1,
        "action": "verify_first_daily",
        "result": "pass" if ok else "fail",
        "ok": ok,
        "gate": FIRST_DAILY_GATE.isoformat(),
        "now": current.isoformat(),
        "day0_ok": day0_ok,
        "epoch_started_at": epoch,
        "daily_written": report.daily_written,
        "weekly_written": report.weekly_written,
        "status": report.status,
        "attention": list(report.attention),
        "report": report.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核验 P3 首份完整 UTC 日报")
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略 2026-07-22T00:00Z 窗口（仅调试；生产核验不要用）",
    )
    parser.add_argument("--app-support-dir", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--health-dir", type=Path, default=None)
    parser.add_argument("--news-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = verify_first_daily(
        force=args.force,
        app_support_dir=args.app_support_dir,
        state_dir=args.state_dir,
        health_dir=args.health_dir,
        news_dir=args.news_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if payload["result"] == "too_early":
        return 3
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
