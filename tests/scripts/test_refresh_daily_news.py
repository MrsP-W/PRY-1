"""AI 新闻 hourly one-shot CLI 契约。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest

from my_ai_employee.news.models import RefreshResult
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

    def __init__(self, store: FileNewsStore | None = None) -> None:
        _FakeNewsService.received_stores.append(store)

    def refresh(self) -> RefreshResult:
        return _FakeNewsService.result


def _stub_refresh(
    monkeypatch: pytest.MonkeyPatch,
    result: RefreshResult,
) -> None:
    _FakeNewsService.result = result
    _FakeNewsService.received_stores = []
    monkeypatch.setattr(refresh_script, "NewsService", _FakeNewsService)


def test_cli_json_success_writes_only_local_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _stub_refresh(
        monkeypatch,
        RefreshResult(
            success=True,
            wrote_snapshot=True,
            kept_previous_snapshot=False,
            item_count=12,
            source_statuses=(),
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


def test_cli_nonzero_for_all_source_failure_or_overlapping_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_refresh(
        monkeypatch,
        RefreshResult(
            success=False,
            wrote_snapshot=True,
            kept_previous_snapshot=True,
            item_count=48,
            source_statuses=(),
            degraded=True,
        ),
    )

    assert refresh_script.main(["--format", "json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["kept_previous_snapshot"] is True
    assert payload["degraded"] is True
    assert payload["item_count"] == 48


def test_cli_source_keeps_one_shot_non_service_control_boundary() -> None:
    source = Path(refresh_script.__file__).read_text(encoding="utf-8")

    for forbidden in ("launchctl", "kickstart", "bootout", "SMTP", "IMAP"):
        assert forbidden not in source
