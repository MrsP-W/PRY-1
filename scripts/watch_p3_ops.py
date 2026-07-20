#!/usr/bin/env python3
"""P3 等待窗只读巡检：首份日报门控 + burn-in 摘要 + Dashboard/menu-bar stderr。

不重置 Day0，不 SMTP，不控制 launchd。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import p3_burn_in_report as burn_in  # noqa: E402
from scripts.verify_p3_first_daily import FIRST_DAILY_GATE, verify_first_daily  # noqa: E402

_PATTERN = re.compile(r"(?i)(traceback|exception|error|sqlalchemy|runtimeerror|operationalerror)")
_LOG_NAMES = ("dashboard.err.log", "menu-bar.err.log")


def _default_logs_dir() -> Path:
    return Path.home() / "Library" / "Logs" / "MyAIEmployee"


def _default_baseline_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "MyAIEmployee"
        / "burn-in"
        / "stderr-watch-baseline.json"
    )


def _probe_health(url: str = "http://127.0.0.1:8765/health", timeout: float = 2.0) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=timeout) as resp:  # noqa: S310 — loopback only
            body = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(body) if body.strip().startswith("{") else {"raw": body}
            return {"ok": True, "http_status": getattr(resp, "status", 200), "body": payload}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def _scan_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    st = path.stat()
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    hits = [ln for ln in lines[-400:] if _PATTERN.search(ln)]
    return {
        "exists": True,
        "size_bytes": st.st_size,
        "mtime_epoch": int(st.st_mtime),
        "line_count": len(lines),
        "recent_pattern_hits": len(hits),
        "recent_hit_samples": [h[:160] for h in hits[-5:]],
    }


def _compare_baseline(current: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    if not baseline:
        return {"has_baseline": False, "grown": [], "new_recent_hits": []}
    grown: list[str] = []
    new_hits: list[str] = []
    base_logs = baseline.get("logs") if isinstance(baseline, dict) else None
    if not isinstance(base_logs, dict):
        return {"has_baseline": False, "grown": [], "new_recent_hits": []}
    for name, cur in current.items():
        prev = base_logs.get(name) if isinstance(base_logs.get(name), dict) else None
        if not isinstance(cur, dict) or not cur.get("exists"):
            continue
        if not prev or not prev.get("exists"):
            grown.append(name)
            continue
        if int(cur.get("size_bytes") or 0) > int(prev.get("size_bytes") or 0):
            grown.append(name)
        if int(cur.get("recent_pattern_hits") or 0) > int(prev.get("recent_pattern_hits") or 0):
            new_hits.append(name)
    return {"has_baseline": True, "grown": grown, "new_recent_hits": new_hits}


def watch_once(
    *,
    logs_dir: Path | None = None,
    baseline_path: Path | None = None,
    write_baseline: bool = False,
    force_verify: bool = False,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    logs_root = logs_dir or _default_logs_dir()
    base_path = baseline_path or _default_baseline_path()

    log_scan = {name: _scan_log(logs_root / name) for name in _LOG_NAMES}
    baseline: dict[str, Any] | None = None
    if base_path.exists():
        try:
            loaded = json.loads(base_path.read_text(encoding="utf-8"))
            baseline = loaded if isinstance(loaded, dict) else None
        except (OSError, json.JSONDecodeError):
            baseline = None

    if write_baseline:
        payload = {"captured_at": now.isoformat(), "schema_version": 1, "logs": log_scan}
        base_path.parent.mkdir(parents=True, exist_ok=True)
        base_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        baseline = payload

    report = burn_in.run_report()
    verify = verify_first_daily(force=force_verify)
    health = _probe_health()
    delta = _compare_baseline(log_scan, baseline)

    hours_to_gate = (FIRST_DAILY_GATE - now).total_seconds() / 3600.0
    return {
        "schema_version": 1,
        "action": "watch_p3_ops",
        "captured_at": now.isoformat(),
        "hours_until_first_daily_gate": round(hours_to_gate, 2),
        "first_daily_gate": FIRST_DAILY_GATE.isoformat(),
        "verify_first_daily": {
            "result": verify.get("result"),
            "ok": verify.get("ok"),
        },
        "burn_in": {
            "status": report.status,
            "attention": list(report.attention),
            "epoch_started_at": (
                report.epoch_started_at.isoformat() if report.epoch_started_at else None
            ),
            "daily_written": report.daily_written,
            "weekly_written": report.weekly_written,
            "progress": report.progress,
        },
        "dashboard_health": health,
        "stderr": {
            "logs": {
                name: {k: v for k, v in meta.items() if k != "recent_hit_samples"}
                for name, meta in log_scan.items()
            },
            "delta_vs_baseline": delta,
            "baseline_path": str(base_path),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P3 等待窗只读巡检")
    parser.add_argument("--write-baseline", action="store_true", help="刷新 stderr 体积基线")
    parser.add_argument("--force-verify", action="store_true", help="忽略首份日报时间门（调试）")
    parser.add_argument("--logs-dir", type=Path, default=None)
    parser.add_argument("--baseline-path", type=Path, default=None)
    args = parser.parse_args(argv)

    payload = watch_once(
        logs_dir=args.logs_dir,
        baseline_path=args.baseline_path,
        write_baseline=args.write_baseline,
        force_verify=args.force_verify,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))

    # 观察脚本默认 exit 0；仅当健康探针失败或出现新增 recent hit 时 exit 1
    health_ok = bool(payload.get("dashboard_health", {}).get("ok"))
    new_hits = payload.get("stderr", {}).get("delta_vs_baseline", {}).get("new_recent_hits") or []
    if not health_ok or new_hits:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
