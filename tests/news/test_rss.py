"""AI 每日情报 RSS/Atom 解析与去重回归。"""

from __future__ import annotations

from datetime import UTC, datetime

from my_ai_employee.news.models import FeedSource
from my_ai_employee.news.rss import deduplicate_and_sort, parse_feed

NOW = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)


def _source(
    *,
    source_id: str = "official",
    name: str = "Official Feed",
    url: str = "https://example.com/feed.xml",
    region: str = "global",
    origin: str = "official",
    role: str = "event",
    require_ai_match: bool = False,
    statement_eligible: bool = False,
) -> FeedSource:
    return FeedSource(
        source_id=source_id,
        name=name,
        url=url,
        region=region,
        origin=origin,
        role=role,
        require_ai_match=require_ai_match,
        statement_eligible=statement_eligible,
    )


def test_parse_rss_sanitizes_html_and_preserves_official_verbatim_statement() -> None:
    payload = b"""<?xml version=\"1.0\"?>
    <rss><channel><item>
      <title>Sam Altman on responsible AI</title>
      <link>https://example.com/news/sam</link>
      <description>&lt;p&gt;Sam Altman said: &ldquo;Safety work must scale with capability.&rdquo;&lt;/p&gt;</description>
      <pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate>
      <source>OpenAI</source>
    </item></channel></rss>"""

    items = parse_feed(_source(statement_eligible=True), payload, now=NOW)

    assert len(items) == 1
    item = items[0]
    assert item.kind == "leader_statement"
    assert item.speaker == "Sam Altman"
    assert item.quote == "Safety work must scale with capability."
    assert item.verbatim is True
    assert "<p>" not in item.summary
    assert item.published_at == "2026-07-19T09:00:00Z"


def test_parse_official_statement_requires_speaker_adjacent_to_quote() -> None:
    payload = b"""<?xml version="1.0"?>
    <rss><channel><item>
      <title>NVIDIA national AI infrastructure update</title>
      <link>https://example.com/news/nvidia</link>
      <description>&lt;p&gt;&ldquo;AI infrastructure must serve every developer,&rdquo; said Jensen Huang, founder and CEO of NVIDIA.&lt;/p&gt;</description>
      <pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate>
    </item></channel></rss>"""

    item = parse_feed(_source(statement_eligible=True), payload, now=NOW)[0]

    assert item.kind == "leader_statement"
    assert item.speaker == "Jensen Huang"
    assert item.quote == "AI infrastructure must serve every developer,"
    assert item.verbatim is True


def test_parse_handles_nested_html_entities_in_official_feed_content() -> None:
    payload = b"""<rss><channel><item>
      <title>NVIDIA AI infrastructure announcement</title>
      <link>https://example.com/news/nvidia-encoded</link>
      <content>&lt;![CDATA[&lt;p&gt;&amp;ldquo;Every enterprise should control its AI infrastructure,&amp;rdquo; said Jensen Huang, founder and CEO of NVIDIA.&lt;/p&gt;]]&gt;</content>
      <pubDate>Wed, 15 Jul 2026 08:00:00 GMT</pubDate>
    </item></channel></rss>"""

    item = parse_feed(_source(statement_eligible=True), payload, now=NOW)[0]

    assert item.kind == "leader_statement"
    assert item.quote == "Every enterprise should control its AI infrastructure,"
    assert "&ldquo;" not in item.summary


def test_parse_does_not_promote_unattributed_quote_to_leader_statement() -> None:
    payload = b"""<rss><channel><item>
      <title>Sam Altman discusses an AI policy quote</title>
      <link>https://example.com/news/policy</link>
      <description>A panel displayed &ldquo;Safety is essential for deployment&rdquo; while Sam Altman attended.</description>
      <pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate>
    </item></channel></rss>"""

    item = parse_feed(_source(statement_eligible=True), payload, now=NOW)[0]

    assert item.kind == "leader_clue"
    assert item.quote is None
    assert item.verbatim is False


def test_parse_atom_uses_alternate_href_and_marks_official_video_as_voice_clue() -> None:
    payload = b"""<?xml version=\"1.0\"?>
    <feed xmlns=\"http://www.w3.org/2005/Atom\">
      <entry>
        <title>OpenAI keynote video</title>
        <link rel=\"alternate\" href=\"https://www.youtube.com/watch?v=1\"/>
        <updated>2026-07-19T08:30:00Z</updated>
        <summary>Official public video.</summary>
      </entry>
    </feed>"""

    items = parse_feed(_source(role="official_voice"), payload, now=NOW)

    assert len(items) == 1
    assert items[0].url == "https://www.youtube.com/watch?v=1"
    assert items[0].kind == "official_voice"
    assert items[0].verbatim is False


def test_media_source_with_required_ai_match_filters_unrelated_entries() -> None:
    payload = b"""<rss><channel>
      <item><title>Sports update</title><link>https://example.com/sports</link><pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate></item>
      <item><title>Chinese AI model release</title><link>https://example.com/ai</link><pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate></item>
    </channel></rss>"""

    items = parse_feed(_source(origin="media", require_ai_match=True), payload, now=NOW)

    assert [item.title for item in items] == ["Chinese AI model release"]


def test_parse_rejects_non_https_item_link() -> None:
    payload = b"""<rss><channel><item>
      <title>Unsafe link</title><link>javascript:alert(1)</link><pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate>
    </item></channel></rss>"""

    assert parse_feed(_source(), payload, now=NOW) == []


def test_parse_excludes_old_or_undated_feed_entries() -> None:
    payload = b"""<rss><channel>
      <item><title>Old AI update</title><link>https://example.com/old</link><pubDate>Mon, 13 Jul 2026 09:00:00 GMT</pubDate></item>
      <item><title>Undated AI update</title><link>https://example.com/undated</link></item>
    </channel></rss>"""

    assert parse_feed(_source(), payload, now=NOW) == []


def test_deduplicate_prefers_official_high_relevance_entry() -> None:
    payload = b"""<rss><channel><item>
      <title>Agent platform update</title><link>https://example.com/official</link>
      <description>Enterprise agent workflow update.</description>
      <pubDate>Sat, 19 Jul 2026 09:00:00 GMT</pubDate>
    </item></channel></rss>"""
    media_payload = b"""<rss><channel><item>
      <title>Agent platform update</title><link>https://example.net/report</link>
      <description>Media report.</description>
      <pubDate>Sat, 19 Jul 2026 08:00:00 GMT</pubDate>
    </item></channel></rss>"""
    official = parse_feed(_source(), payload, now=NOW)[0]
    media = parse_feed(
        _source(source_id="media", origin="media", url="https://example.net/feed.xml"),
        media_payload,
        now=NOW,
    )[0]

    items = deduplicate_and_sort([media, official])

    assert items == [official]
