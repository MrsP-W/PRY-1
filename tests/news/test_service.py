"""AI 每日情报刷新、失败隔离和 Dashboard Payload 回归。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import respx
from httpx import Response

from my_ai_employee.news.models import FeedSource, NewsItem
from my_ai_employee.news.service import NewsService, _fetch_feed
from my_ai_employee.news.store import FileNewsStore
from my_ai_employee.news.translation import NewsTranslation

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


class _RecordingTranslator:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[NewsItem]] = []

    def translate(self, items: Sequence[NewsItem]) -> dict[str, NewsTranslation]:
        self.calls.append(list(items))
        if self.fail:
            raise RuntimeError("translation unavailable")
        return {
            item.item_id: NewsTranslation(
                item_id=item.item_id,
                title_zh="企业人工智能智能体更新",
                summary_zh="智能体与模型上下文协议工作流更新。",
            )
            for item in items
        }


class _FailAfterFirstBatchTranslator(_RecordingTranslator):
    def translate(self, items: Sequence[NewsItem]) -> dict[str, NewsTranslation]:
        if self.calls:
            self.calls.append(list(items))
            raise RuntimeError("second translation batch unavailable")
        return super().translate(items)


def _many_item_rss(count: int) -> bytes:
    entries = "".join(
        (
            "<item>"
            f"<title>Enterprise AI agent update {index}</title>"
            f"<link>https://example.com/ai-agent-{index}</link>"
            f"<description>Agent workflow update number {index}.</description>"
            "<pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate>"
            "</item>"
        )
        for index in range(count)
    )
    return f"<rss><channel>{entries}</channel></rss>".encode()


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


def test_refresh_reuses_translation_when_id_title_and_summary_are_unchanged(
    tmp_path: Path,
) -> None:
    store = FileNewsStore(tmp_path / "latest.json")
    first_translator = _RecordingTranslator()
    first = NewsService(
        store,
        sources=(_source("official"),),
        translator=first_translator,
    )

    assert first.refresh(fetcher=lambda _source: RSS, now=NOW).success is True
    assert len(first_translator.calls) == 1

    second_translator = _RecordingTranslator(fail=True)
    second = NewsService(
        store,
        sources=(_source("official"),),
        translator=second_translator,
    )
    assert second.refresh(fetcher=lambda _source: RSS, now=NOW).success is True

    assert second_translator.calls == []
    persisted = store.read()
    assert persisted is not None
    assert persisted["items"][0]["title_zh"] == "企业人工智能智能体更新"
    assert persisted["items"][0]["summary_zh"] == "智能体与模型上下文协议工作流更新。"


def test_refresh_retranslates_when_original_summary_changes(tmp_path: Path) -> None:
    store = FileNewsStore(tmp_path / "latest.json")
    first_translator = _RecordingTranslator()
    service = NewsService(
        store,
        sources=(_source("official"),),
        translator=first_translator,
    )
    assert service.refresh(fetcher=lambda _source: RSS, now=NOW).success is True

    changed_rss = RSS.replace(
        b"Agent and MCP workflow update.",
        b"Agent and MCP workflow changed.",
    )
    second_translator = _RecordingTranslator()
    changed = NewsService(
        store,
        sources=(_source("official"),),
        translator=second_translator,
    )
    assert changed.refresh(fetcher=lambda _source: changed_rss, now=NOW).success is True

    assert len(second_translator.calls) == 1


def test_translation_failure_does_not_block_rss_snapshot_and_falls_back_to_english(
    tmp_path: Path,
) -> None:
    store = FileNewsStore(tmp_path / "latest.json")
    service = NewsService(
        store,
        sources=(_source("official"),),
        translator=_RecordingTranslator(fail=True),
    )

    result = service.refresh(fetcher=lambda _source: RSS, now=NOW)

    assert result.success is True
    assert result.wrote_snapshot is True
    payload = service.build_payload(now=NOW)
    assert payload["items"][0]["title"] == "Enterprise AI agent update"
    assert "title_zh" not in payload["items"][0]
    assert "summary_zh" not in payload["items"][0]


def test_domestic_news_is_not_sent_to_translator(tmp_path: Path) -> None:
    translator = _RecordingTranslator(fail=True)
    service = NewsService(
        FileNewsStore(tmp_path / "latest.json"),
        sources=(_source("cn"),),
        translator=translator,
    )

    assert service.refresh(fetcher=lambda _source: RSS, now=NOW).success is True

    assert translator.calls == []


def test_refresh_keeps_successful_first_translation_batch_when_second_batch_fails(
    tmp_path: Path,
) -> None:
    store = FileNewsStore(tmp_path / "latest.json")
    translator = _FailAfterFirstBatchTranslator()
    service = NewsService(
        store,
        sources=(_source("official"),),
        translator=translator,
    )

    result = service.refresh(fetcher=lambda _source: _many_item_rss(9), now=NOW)

    assert result.success is True
    assert [len(batch) for batch in translator.calls] == [8, 1]
    persisted = store.read()
    assert persisted is not None
    assert len(persisted["items"]) == 9
    assert sum(isinstance(item["title_zh"], str) for item in persisted["items"]) == 8
    assert sum(item["title_zh"] is None for item in persisted["items"]) == 1
    payload = service.build_payload(now=NOW)
    assert sum("title_zh" in item for item in payload["items"]) == 8


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
