#!/usr/bin/env python3
"""核验 P3 首份完整 UTC 日报。

门槛 = Day0 日期 + 2 天的 00:00Z（首个完整 UTC 日结束后）。
有 attention 时 fail-closed；不重置 Day0，不触碰 SMTP。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# launchd / 直接 python scripts/... 时保证可 import scripts.*
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import p3_burn_in_report as burn_in  # noqa: E402


def first_daily_gate_for_epoch(epoch: datetime) -> datetime:
    """首个完整 UTC 日结束后才可核验（epoch.date()+1 为完整日，+2 日 00:00Z 开窗）。"""

    epoch = burn_in._normalise_utc(epoch)
    return datetime.combine(epoch.date() + timedelta(days=2), datetime.min.time(), tzinfo=UTC)


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
    report = burn_in.run_report(
        app_support_dir=app_support_dir,
        state_dir=state_dir,
        health_dir=health_dir,
        news_dir=news_dir,
        now_fn=lambda: current,
    )
    if not report.started or report.epoch_started_at is None:
        return {
            "schema_version": 1,
            "action": "verify_first_daily",
            "result": "not_started",
            "ok": False,
            "now": current.isoformat(),
            "gate": None,
            "epoch_started_at": None,
        }

    epoch = burn_in._normalise_utc(report.epoch_started_at)
    gate = first_daily_gate_for_epoch(epoch)
    if not force and current < gate:
        return {
            "schema_version": 1,
            "action": "verify_first_daily",
            "result": "too_early",
            "gate": gate.isoformat(),
            "now": current.isoformat(),
            "ok": False,
            "epoch_started_at": epoch.isoformat(),
        }

    # Re-run with the evaluation clock so daily artifacts use the same `now`.
    report = burn_in.run_report(
        app_support_dir=app_support_dir,
        state_dir=state_dir,
        health_dir=health_dir,
        news_dir=news_dir,
        now_fn=lambda: current,
    )
    epoch_iso = report.epoch_started_at.isoformat() if report.epoch_started_at else None
    day0_ok = bool(epoch_iso)
    daily_ok = report.daily_written >= 1
    attention = list(report.attention)
    attention_ok = len(attention) == 0 and report.status != "attention"
    ok = bool(report.started and day0_ok and daily_ok and attention_ok)
    result = "pass" if ok else "fail"
    if not attention_ok and report.started:
        result = "fail_attention"
    return {
        "schema_version": 1,
        "action": "verify_first_daily",
        "result": result,
        "ok": ok,
        "gate": gate.isoformat(),
        "now": current.isoformat(),
        "day0_ok": day0_ok,
        "attention_ok": attention_ok,
        "epoch_started_at": epoch_iso,
        "daily_written": report.daily_written,
        "weekly_written": report.weekly_written,
        "status": report.status,
        "attention": attention,
        "report": report.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核验 P3 首份完整 UTC 日报")
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略首份日报时间门（仅调试；生产核验不要用）",
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
    if payload["result"] == "not_started":
        return 2
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
