"""AI 新闻 hourly one-shot CLI 契约。"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import ClassVar

import pytest

from my_ai_employee.news.models import RefreshResult, SourceRefreshStatus
from my_ai_employee.news.store import FileNewsStore
from scripts import refresh_daily_news as refresh_script


class _FakeNewsService:
    """隔离 CLI 返回码与输出，不触发真实公开 Feed 请求。"""

    result: ClassVar[RefreshResult] = RefreshResult(
        success=False,
        wrote_snapshot=False,
        kept_previous_snapshot=False,
        item_count=0,
        source_statuses=(),
    )
    received_stores: ClassVar[list[FileNewsStore | None]] = []
    error: ClassVar[Exception | None] = None

    def __init__(self, store: FileNewsStore | None = None) -> None:
        _FakeNewsService.received_stores.append(store)

    def refresh(self) -> RefreshResult:
        if _FakeNewsService.error is not None:
            raise _FakeNewsService.error
        return _FakeNewsService.result


def _stub_refresh(
    monkeypatch: pytest.MonkeyPatch,
    result: RefreshResult,
) -> None:
    _FakeNewsService.result = result
    _FakeNewsService.received_stores = []
    _FakeNewsService.error = None
    monkeypatch.setattr(refresh_script, "NewsService", _FakeNewsService)


def _source_status(
    *,
    source_id: str = "official-feed",
    status: str = "ok",
    item_count: int = 0,
    error: str | None = None,
) -> SourceRefreshStatus:
    return SourceRefreshStatus(
        source_id=source_id,
        name="Private source name must not enter journal",
        region="global",
        origin="official",
        status=status,
        item_count=item_count,
        error=error,
    )


def _run_records(output: Path) -> list[dict[str, object]]:
    runs_path = output.parent / "runs.jsonl"
    return [json.loads(line) for line in runs_path.read_text(encoding="utf-8").splitlines()]


def test_cli_json_success_writes_only_local_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    fsync_calls: list[int] = []
    original_fsync = os.fsync

    def track_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", track_fsync)
    _stub_refresh(
        monkeypatch,
        RefreshResult(
            success=True,
            wrote_snapshot=True,
            kept_previous_snapshot=False,
            item_count=12,
            source_statuses=(_source_status(item_count=12),),
        ),
    )

    output = tmp_path / "news" / "latest.json"
    assert refresh_script.main(["--format", "json", "--output", str(output)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["wrote_snapshot"] is True
    assert payload["item_count"] == 12
    assert _FakeNewsService.received_stores[0] is not None
    assert _FakeNewsService.received_stores[0].path == output
    assert set(payload) == {
        "success",
        "wrote_snapshot",
        "kept_previous_snapshot",
        "degraded",
        "item_count",
        "sources",
    }

    runs_path = output.parent / "runs.jsonl"
    records = _run_records(output)
    assert len(records) == 1
    record = records[0]
    assert {key: value for key, value in record.items() if key != "at"} == {
        "schema_version": 1,
        "outcome": "success",
        "success": True,
        "degraded": False,
        "item_count": 12,
        "sources": [{"source_id": "official-feed", "status": "ok", "item_count": 12}],
    }
    assert isinstance(record["at"], str)
    assert record["at"].endswith("Z")
    assert stat.S_IMODE(runs_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(runs_path.parent.stat().st_mode) == 0o700
    assert fsync_calls


def test_cli_nonzero_for_overlapping_run_records_overlap(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stub_refresh(
        monkeypatch,
        RefreshResult(
            success=False,
            wrote_snapshot=False,
            kept_previous_snapshot=True,
            item_count=48,
            source_statuses=(),
            degraded=False,
        ),
    )

    output = tmp_path / "news" / "latest.json"
    assert refresh_script.main(["--format", "json", "--output", str(output)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["kept_previous_snapshot"] is True
    assert payload["degraded"] is False
    assert payload["item_count"] == 48
    assert _run_records(output)[0]["outcome"] == "overlap"


def test_cli_records_all_source_failure_without_source_error_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    secret_error = "https://private.example/path?token=not-for-journal"
    _stub_refresh(
        monkeypatch,
        RefreshResult(
            success=False,
            wrote_snapshot=True,
            kept_previous_snapshot=True,
            item_count=48,
            source_statuses=(_source_status(status="error", error=secret_error),),
            degraded=True,
        ),
    )

    output = tmp_path / "news" / "latest.json"
    assert refresh_script.main(["--format", "json", "--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().out)["degraded"] is True

    journal = _run_records(output)[0]
    assert journal["outcome"] == "all_sources_failed"
    assert journal["sources"] == [
        {"source_id": "official-feed", "status": "error", "item_count": 0}
    ]
    stored = (output.parent / "runs.jsonl").read_text(encoding="utf-8")
    assert secret_error not in stored
    assert "Private source name" not in stored


def test_outcome_treats_retained_previous_snapshot_as_all_source_failure() -> None:
    result = RefreshResult(
        success=False,
        wrote_snapshot=True,
        kept_previous_snapshot=True,
        item_count=48,
        source_statuses=(),
        degraded=True,
    )

    assert refresh_script._outcome(result) == "all_sources_failed"


def test_cli_records_successful_degraded_refresh(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stub_refresh(
        monkeypatch,
        RefreshResult(
            success=True,
            wrote_snapshot=True,
            kept_previous_snapshot=True,
            item_count=48,
            source_statuses=(_source_status(status="ok"),),
            degraded=True,
        ),
    )

    output = tmp_path / "news" / "latest.json"
    assert refresh_script.main(["--format", "json", "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["success"] is True
    assert _run_records(output)[0]["outcome"] == "degraded"


def test_cli_records_runtime_error_without_exposing_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stub_refresh(
        monkeypatch,
        RefreshResult(
            success=True,
            wrote_snapshot=False,
            kept_previous_snapshot=False,
            item_count=0,
            source_statuses=(),
        ),
    )
    secret_error = "https://private.example/path?token=not-for-output"
    _FakeNewsService.error = RuntimeError(secret_error)

    output = tmp_path / "news" / "latest.json"
    assert refresh_script.main(["--format", "json", "--output", str(output)]) == 2
    rendered = capsys.readouterr().out
    assert secret_error not in rendered
    assert json.loads(rendered)["success"] is False
    records = _run_records(output)
    assert len(records) == 1
    assert {key: value for key, value in records[0].items() if key != "at"} == {
        "schema_version": 1,
        "outcome": "runtime_error",
        "success": False,
        "degraded": False,
        "item_count": 0,
        "sources": [],
    }
    assert isinstance(records[0]["at"], str)


def test_cli_source_keeps_one_shot_non_service_control_boundary() -> None:
    source = Path(refresh_script.__file__).read_text(encoding="utf-8")

    for forbidden in ("launchctl", "kickstart", "bootout", "SMTP", "IMAP"):
        assert forbidden not in source
