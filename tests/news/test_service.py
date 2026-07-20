"""AI 每日情报刷新、失败隔离和 Dashboard Payload 回归。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import respx
from httpx import Response

from my_ai_employee.news.models import FeedSource
from my_ai_employee.news.service import NewsService, _fetch_feed
from my_ai_employee.news.store import FileNewsStore

NOW = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)
RSS = b"""<rss><channel><item>
  <title>Enterprise AI agent update</title>
  <link>https://example.com/ai-agent</link>
  <description>Agent and MCP workflow update.</description>
  <pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate>
</item></channel></rss>"""
EMPTY_RSS = b"<rss><channel></channel></rss>"


def _source(source_id: str) -> FeedSource:
    return FeedSource(
        source_id=source_id,
        name=source_id,
        url=f"https://{source_id}.example.com/feed.xml",
        region="cn" if source_id == "cn" else "global",
        origin="official" if source_id == "official" else "media",
    )


def test_refresh_isolates_single_source_failure_and_writes_snapshot(tmp_path: Path) -> None:
    sources = (_source("official"), _source("broken"))
    store = FileNewsStore(tmp_path / "latest.json")
    service = NewsService(store, sources=sources)

    def fetcher(source: FeedSource) -> bytes:
        if source.source_id == "broken":
            raise RuntimeError("network unavailable")
        return RSS

    result = service.refresh(fetcher=fetcher, now=NOW)

    assert result.success is True
    assert result.wrote_snapshot is True
    assert result.item_count == 1
    assert [status.status for status in result.source_statuses] == ["ok", "error"]
    payload = service.build_payload(now=NOW + timedelta(minutes=10))
    assert payload["state"] == "fresh"
    assert payload["coverage"]["successful_sources"] == 1
    assert payload["items"][0]["relevance"] == "high"


def test_all_source_failures_keep_previous_snapshot(tmp_path: Path) -> None:
    store = FileNewsStore(tmp_path / "latest.json")
    previous = {
        "schema_version": 1,
        "generated_at": "2026-07-19T09:00:00Z",
        "items": [
            {
                "id": "previous-news",
                "title": "Previous AI update",
                "url": "https://example.com/previous",
                "region": "global",
                "kind": "event",
            }
        ],
        "sources": [],
        "coverage": {},
    }
    store.write(previous)
    service = NewsService(store, sources=(_source("broken"),))

    def failing_fetcher(_source: FeedSource) -> bytes:
        raise RuntimeError("offline")

    result = service.refresh(fetcher=failing_fetcher, now=NOW)

    assert result.success is False
    assert result.wrote_snapshot is True
    assert result.kept_previous_snapshot is True
    assert result.degraded is True
    persisted = store.read()
    assert persisted is not None
    assert persisted["items"] == previous["items"]
    assert persisted["generated_at"] == previous["generated_at"]
    assert persisted["refresh_state"] == "degraded_source_failures"
    assert NewsService(store, sources=()).build_payload(now=NOW)["state"] == "degraded"


def test_refresh_isolates_invalid_xml_from_one_source(tmp_path: Path) -> None:
    """P2：单源坏 XML 不阻塞其它源写 snapshot。"""
    sources = (_source("official"), _source("broken_xml"))
    store = FileNewsStore(tmp_path / "latest.json")
    service = NewsService(store, sources=sources)

    def fetcher(source: FeedSource) -> bytes:
        if source.source_id == "broken_xml":
            return b"<not-valid-xml"
        return RSS

    result = service.refresh(fetcher=fetcher, now=NOW)

    assert result.success is True
    assert result.wrote_snapshot is True
    assert result.item_count == 1
    statuses = {status.source_id: status.status for status in result.source_statuses}
    assert statuses["official"] == "ok"
    assert statuses["broken_xml"] == "error"
    payload = service.build_payload(now=NOW + timedelta(minutes=5))
    assert payload["state"] == "fresh"
    assert payload["coverage"]["successful_sources"] == 1


def test_build_payload_skips_malformed_cached_items(tmp_path: Path) -> None:
    """P2：缓存里坏 item 字段被跳过，不炸 Dashboard payload。"""
    store = FileNewsStore(tmp_path / "latest.json")
    store.write(
        {
            "schema_version": 1,
            "generated_at": "2026-07-19T09:50:00Z",
            "items": [
                {"id": 123, "title": "bad-id-type"},
                {
                    "id": "good-news",
                    "title": "Valid AI update",
                    "url": "https://example.com/good",
                    "region": "global",
                    "kind": "event",
                },
            ],
            "sources": [],
            "coverage": {},
        }
    )

    payload = NewsService(store, sources=()).build_payload(now=NOW)

    assert payload["available"] is True
    assert [item["id"] for item in payload["items"]] == ["good-news"]


def test_empty_successful_refresh_keeps_previous_nonempty_snapshot(tmp_path: Path) -> None:
    store = FileNewsStore(tmp_path / "latest.json")
    previous = {
        "schema_version": 1,
        "generated_at": "2026-07-19T09:00:00Z",
        "items": [
            {
                "id": "previous-news",
                "title": "Previous AI update",
                "url": "https://example.com/previous",
                "region": "cn",
                "kind": "event",
            }
        ],
        "sources": [],
        "coverage": {},
    }
    store.write(previous)
    service = NewsService(store, sources=(_source("official"),))

    result = service.refresh(fetcher=lambda _source: EMPTY_RSS, now=NOW)

    assert result.success is True
    assert result.wrote_snapshot is True
    assert result.kept_previous_snapshot is True
    assert result.degraded is True
    assert result.item_count == 1
    persisted = store.read()
    assert persisted is not None
    assert persisted["items"] == previous["items"]
    assert persisted["generated_at"] == previous["generated_at"]
    assert persisted["refresh_state"] == "degraded_empty_results"
    payload = service.build_payload(now=NOW)
    assert payload["state"] == "degraded"
    assert payload["coverage"]["domestic"] == 1


@respx.mock
def test_fetch_feed_allows_only_same_origin_https_redirect() -> None:
    source = FeedSource(
        source_id="feed",
        name="Feed",
        url="https://feed.example/rss.xml",
        region="global",
        origin="official",
    )
    initial = respx.get(source.url).mock(
        return_value=Response(302, headers={"location": "/canonical.xml"})
    )
    final = respx.get("https://feed.example/canonical.xml").mock(
        return_value=Response(200, content=RSS)
    )

    assert _fetch_feed(source) == RSS
    assert initial.called is True
    assert final.called is True


@pytest.mark.parametrize(
    "target",
    (
        "http://feed.example/unsafe.xml",
        "https://evil.example/unsafe.xml",
        "https://127.0.0.1/unsafe.xml",
        "https://feed.example:8443/unsafe.xml",
    ),
)
def test_fetch_feed_rejects_unsafe_redirect_before_request(target: str) -> None:
    source = FeedSource(
        source_id="feed",
        name="Feed",
        url="https://feed.example/rss.xml",
        region="global",
        origin="official",
    )
    with respx.mock(assert_all_called=False) as router:
        router.get(source.url).mock(return_value=Response(302, headers={"location": target}))
        forbidden_target = router.get(target).mock(return_value=Response(200, content=RSS))

        with pytest.raises(ValueError, match="Feed 重定向被拒绝"):
            _fetch_feed(source)

    assert forbidden_target.called is False


def test_payload_reports_stale_snapshot_without_network_access(tmp_path: Path) -> None:
    store = FileNewsStore(tmp_path / "latest.json")
    store.write(
        {
            "schema_version": 1,
            "generated_at": "2026-07-19T07:00:00Z",
            "items": [],
            "sources": [],
            "coverage": {},
        }
    )

    payload = NewsService(store, sources=()).build_payload(now=NOW)

    assert payload["available"] is True
    assert payload["state"] == "stale"
    assert payload["age_minutes"] == 180


def test_payload_handles_missing_first_refresh(tmp_path: Path) -> None:
    payload = NewsService(FileNewsStore(tmp_path / "missing.json"), sources=()).build_payload(
        now=NOW
    )

    assert payload["available"] is False
    assert payload["state"] == "not_refreshed"
    assert payload["items"] == []
