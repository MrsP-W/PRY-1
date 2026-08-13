"""P3 epoch rollover 的安全门控回归。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import p3_rollover_epoch as rollover


def _verify(result: str, epoch: datetime) -> dict[str, object]:
    return {"result": result, "epoch_started_at": epoch.isoformat(), "attention": []}


def test_rollover_stops_when_archive_target_exists(tmp_path: Path) -> None:
    epoch = datetime(2026, 7, 21, 18, 23, 47, tzinfo=UTC)
    source = tmp_path / "burn-in"
    source.mkdir()
    archive = tmp_path / "burn-in-archive" / "epoch-2026-07-21T18-23-47Z"
    archive.mkdir(parents=True)

    with patch.object(
        rollover, "verify_first_daily", return_value=_verify("fail_attention", epoch)
    ):
        payload = rollover.rollover_once(app_support_dir=tmp_path)

    assert payload["result"] == "archive_target_exists"
    assert source.is_dir()


def test_rollover_moves_epoch_and_starts_new_day0(tmp_path: Path) -> None:
    epoch = datetime(2026, 7, 21, 18, 23, 47, tzinfo=UTC)
    source = tmp_path / "burn-in"
    source.mkdir()
    (source / "state.json").write_text("{}", encoding="utf-8")
    new_day0 = epoch + timedelta(days=2)

    with (
        patch.object(rollover, "verify_first_daily", return_value=_verify("fail_attention", epoch)),
        patch.object(rollover.burn_in, "start_burn_in", return_value=new_day0),
        patch.object(rollover.burn_in, "run_report") as report,
        patch.object(rollover, "watch_once", return_value={"burn_in": {"attention": []}}),
    ):
        report.return_value.to_dict.return_value = {"status": "collecting"}
        payload = rollover.rollover_once(app_support_dir=tmp_path)

    assert payload["result"] == "rolled_over"
    assert not source.exists()
    assert (tmp_path / "burn-in-archive" / "epoch-2026-07-21T18-23-47Z").is_dir()
    assert payload["new_day0"] == new_day0.isoformat()


def test_rollover_does_not_start_before_gate(tmp_path: Path) -> None:
    with patch.object(
        rollover,
        "verify_first_daily",
        return_value={"result": "too_early", "epoch_started_at": None},
    ):
        payload = rollover.rollover_once(app_support_dir=tmp_path)

    assert payload["result"] == "too_early"
    assert not (tmp_path / "burn-in-archive").exists()


def test_rollover_fail_attention_does_not_short_circuit(tmp_path: Path) -> None:
    """fail_attention 是生产场景：attention 不阻断，应继续归档并开新 Day0。"""

    epoch = datetime(2026, 7, 30, 7, 4, 45, tzinfo=UTC)
    source = tmp_path / "burn-in"
    source.mkdir()
    (source / "state.json").write_text("{}", encoding="utf-8")
    new_day0 = epoch + timedelta(days=1)
    verify = {
        "result": "fail_attention",
        "epoch_started_at": epoch.isoformat(),
        "attention": ["health_sample_gap", "news_run_gap"],
    }

    with (
        patch.object(rollover, "verify_first_daily", return_value=verify),
        patch.object(rollover.burn_in, "start_burn_in", return_value=new_day0),
        patch.object(rollover.burn_in, "run_report") as report,
        patch.object(rollover, "watch_once", return_value={"burn_in": {"attention": []}}),
    ):
        report.return_value.to_dict.return_value = {"status": "collecting"}
        payload = rollover.rollover_once(app_support_dir=tmp_path)

    assert payload["result"] == "rolled_over"
    assert payload["verify"]["attention"] == ["health_sample_gap", "news_run_gap"]
    assert not source.exists()
    assert (tmp_path / "burn-in-archive" / "epoch-2026-07-30T07-04-45Z").is_dir()


def test_rollover_source_missing(tmp_path: Path) -> None:
    epoch = datetime(2026, 7, 30, 7, 4, 45, tzinfo=UTC)

    with patch.object(
        rollover, "verify_first_daily", return_value=_verify("fail_attention", epoch)
    ):
        payload = rollover.rollover_once(app_support_dir=tmp_path)

    assert payload["result"] == "source_missing"
    assert payload["source_path"] == str(tmp_path / "burn-in")
    assert not (tmp_path / "burn-in-archive").exists()


def test_rollover_archived_start_failed_keeps_archive(tmp_path: Path) -> None:
    epoch = datetime(2026, 7, 30, 7, 4, 45, tzinfo=UTC)
    source = tmp_path / "burn-in"
    source.mkdir()
    (source / "state.json").write_text('{"keep": true}', encoding="utf-8")
    archive = tmp_path / "burn-in-archive" / "epoch-2026-07-30T07-04-45Z"

    with (
        patch.object(rollover, "verify_first_daily", return_value=_verify("fail_attention", epoch)),
        patch.object(
            rollover.burn_in,
            "start_burn_in",
            side_effect=RuntimeError("simulated start failure"),
        ),
    ):
        payload = rollover.rollover_once(app_support_dir=tmp_path)

    assert payload["result"] == "archived_start_failed"
    assert payload["error"] == "RuntimeError"
    assert not source.exists()
    assert archive.is_dir()
    assert (archive / "state.json").read_text(encoding="utf-8") == '{"keep": true}'


def test_rollover_watch_once_rejects_app_support_dir_but_still_rolls(tmp_path: Path) -> None:
    """归档与新 Day0 成功后，watch_once 未知参数不得把 result 从 rolled_over 打成崩溃。"""

    epoch = datetime(2026, 7, 30, 7, 4, 45, tzinfo=UTC)
    source = tmp_path / "burn-in"
    source.mkdir()
    (source / "state.json").write_text("{}", encoding="utf-8")
    new_day0 = epoch + timedelta(hours=1)

    def _strict_watch_once(**kwargs: object) -> dict[str, object]:
        if "app_support_dir" in kwargs:
            raise TypeError("watch_once() got an unexpected keyword argument 'app_support_dir'")
        return {"status": "ok"}

    with (
        patch.object(rollover, "verify_first_daily", return_value=_verify("fail_attention", epoch)),
        patch.object(rollover.burn_in, "start_burn_in", return_value=new_day0),
        patch.object(rollover.burn_in, "run_report") as report,
        patch.object(rollover, "watch_once", side_effect=_strict_watch_once),
    ):
        report.return_value.to_dict.return_value = {"status": "collecting"}
        payload = rollover.rollover_once(app_support_dir=tmp_path)

    assert payload["result"] == "rolled_over"
    assert payload["watch"] == {"status": "ok"}
    assert payload["new_day0"] == new_day0.isoformat()
