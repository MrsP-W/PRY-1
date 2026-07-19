"""AI 每日情报本地缓存回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

from my_ai_employee.news.store import FileNewsStore, default_news_cache_path


def test_store_atomic_write_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "news" / "latest.json"
    store = FileNewsStore(path)
    snapshot = {"schema_version": 1, "generated_at": "2026-07-19T10:00:00Z", "items": []}

    store.write(snapshot)

    assert store.read() == snapshot
    assert not list(path.parent.glob(".latest-*.tmp"))


def test_store_returns_none_for_corrupted_json(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    path.write_text("{not-json", encoding="utf-8")

    assert FileNewsStore(path).read() is None


def test_default_cache_path_uses_existing_app_support_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MY_AI_EMPLOYEE_APP_SUPPORT_DIR", str(tmp_path))

    assert default_news_cache_path() == tmp_path / "news" / "latest.json"
