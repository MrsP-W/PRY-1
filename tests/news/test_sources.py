"""默认 AI 情报来源的覆盖边界回归。"""

from __future__ import annotations

from my_ai_employee.news.sources import DEFAULT_FEED_SOURCES


def test_default_sources_cover_domestic_international_and_verified_statement_feed() -> None:
    """国内事件、国际事件和一手逐字原话至少各有一个受控入口。"""
    source_by_id = {source.source_id: source for source in DEFAULT_FEED_SOURCES}

    assert any(source.region == "cn" for source in DEFAULT_FEED_SOURCES)
    assert any(source.region == "global" for source in DEFAULT_FEED_SOURCES)
    nvidia = source_by_id["nvidia-newsroom"]
    assert nvidia.origin == "official"
    assert nvidia.statement_eligible is True
    assert nvidia.url == "https://nvidianews.nvidia.com/rss.xml"
