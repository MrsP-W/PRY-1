"""watch_p3_ops 只读巡检回归。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.watch_p3_ops import main, watch_once


class _FakeReport:
    status = "collecting"
    attention: tuple[str, ...] = ()
    epoch_started_at = None
    daily_written = 0
    weekly_written = 0
    progress: dict[str, Any] = {}


class _AttentionReport(_FakeReport):
    status = "attention"
    attention = ("news_run_gap",)


class _StartedReport(_FakeReport):
    epoch_started_at = datetime(2026, 7, 27, tzinfo=UTC)


def test_watch_once_writes_baseline_and_compares(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    dash = logs / "dashboard.err.log"
    menu = logs / "menu-bar.err.log"
    dash.write_text("info ok\n", encoding="utf-8")
    menu.write_text("info ok\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"

    with (
        patch("scripts.watch_p3_ops.burn_in.run_report", return_value=_FakeReport()),
        patch(
            "scripts.watch_p3_ops.verify_first_daily",
            return_value={"result": "too_early", "ok": False},
        ),
        patch("scripts.watch_p3_ops._probe_health", return_value={"ok": True}),
    ):
        first = watch_once(logs_dir=logs, baseline_path=baseline, write_baseline=True)
        assert first["verify_first_daily"]["result"] == "too_early"
        assert baseline.exists()
        assert first["stderr"]["delta_vs_baseline"]["has_baseline"] is True

        dash.write_text("info ok\nERROR boom\n", encoding="utf-8")
        second = watch_once(logs_dir=logs, baseline_path=baseline, write_baseline=False)
        assert "dashboard.err.log" in second["stderr"]["delta_vs_baseline"]["grown"]
        assert "dashboard.err.log" in second["stderr"]["delta_vs_baseline"]["new_recent_hits"]


def test_main_returns_nonzero_for_burn_in_attention(tmp_path: Path) -> None:
    with (
        patch("scripts.watch_p3_ops.burn_in.run_report", return_value=_AttentionReport()),
        patch(
            "scripts.watch_p3_ops.verify_first_daily",
            return_value={"result": "too_early", "ok": False},
        ),
        patch("scripts.watch_p3_ops._probe_health", return_value={"ok": True}),
    ):
        assert (
            main(
                [
                    "--logs-dir",
                    str(tmp_path / "logs"),
                    "--baseline-path",
                    str(tmp_path / "baseline.json"),
                ]
            )
            == 1
        )


def test_main_returns_nonzero_when_epoch_is_not_started(tmp_path: Path) -> None:
    with (
        patch("scripts.watch_p3_ops.burn_in.run_report", return_value=_FakeReport()),
        patch(
            "scripts.watch_p3_ops.verify_first_daily",
            return_value={"result": "not_started", "ok": False},
        ),
        patch("scripts.watch_p3_ops._probe_health", return_value={"ok": True}),
    ):
        assert (
            main(
                [
                    "--logs-dir",
                    str(tmp_path / "logs"),
                    "--baseline-path",
                    str(tmp_path / "baseline.json"),
                ]
            )
            == 1
        )


def test_main_allows_too_early_first_daily_gate(tmp_path: Path) -> None:
    with (
        patch("scripts.watch_p3_ops.burn_in.run_report", return_value=_StartedReport()),
        patch(
            "scripts.watch_p3_ops.verify_first_daily",
            return_value={"result": "too_early", "ok": False},
        ),
        patch("scripts.watch_p3_ops._probe_health", return_value={"ok": True}),
    ):
        assert (
            main(
                [
                    "--logs-dir",
                    str(tmp_path / "logs"),
                    "--baseline-path",
                    str(tmp_path / "baseline.json"),
                ]
            )
            == 0
        )
