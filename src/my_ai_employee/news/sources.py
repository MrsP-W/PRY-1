"""AI 每日情报的公开来源白名单。

来源只使用 HTTPS、无需账号或 API Key 的 RSS/Atom。媒体聚合源仅作事件或发言
线索；领导人“原话”只允许来自一手逐字稿的可定位短摘，绝不由模型补写。
"""

from __future__ import annotations

from typing import Final

from my_ai_employee.news.models import FeedSource

DEFAULT_FEED_SOURCES: Final[tuple[FeedSource, ...]] = (
    FeedSource(
        source_id="cn-ai-news",
        name="Google 新闻 · 中国 AI",
        url=(
            "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA"
            "%E8%83%BD&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans"
        ),
        region="cn",
        origin="media",
    ),
    FeedSource(
        source_id="global-ai-news",
        name="Google 新闻 · 国际 AI",
        url=(
            "https://news.google.com/rss/search?q=%28artificial+intelligence+OR+"
            "generative+AI%29&hl=en-US&gl=US&ceid=US%3Aen"
        ),
        region="global",
        origin="media",
    ),
    FeedSource(
        source_id="openai-news",
        name="OpenAI News",
        url="https://openai.com/news/rss.xml",
        region="global",
        origin="official",
    ),
    FeedSource(
        source_id="google-ai-blog",
        name="Google AI Blog",
        url="https://blog.google/technology/ai/rss/",
        region="global",
        origin="official",
    ),
    FeedSource(
        source_id="hugging-face-blog",
        name="Hugging Face Blog",
        url="https://huggingface.co/blog/feed.xml",
        region="global",
        origin="official",
    ),
    # 逐条原文归因的官方 RSS：只有说话人、明确归因和引号同时命中时，
    # 解析器才会显示为“已核验原话”。其余条目仍只是官方事件。
    FeedSource(
        source_id="nvidia-newsroom",
        name="NVIDIA Newsroom",
        url="https://nvidianews.nvidia.com/rss.xml",
        region="global",
        origin="official",
        statement_eligible=True,
    ),
    FeedSource(
        source_id="36kr-ai",
        name="36氪 · 国内 AI 事件",
        url="https://www.36kr.com/feed",
        region="cn",
        origin="media",
        require_ai_match=True,
    ),
    FeedSource(
        source_id="techcrunch-ai",
        name="TechCrunch · AI",
        url="https://techcrunch.com/category/artificial-intelligence/feed/",
        region="global",
        origin="media",
    ),
    FeedSource(
        source_id="venturebeat-ai",
        name="VentureBeat · AI",
        url="https://venturebeat.com/category/ai/feed/",
        region="global",
        origin="media",
    ),
    FeedSource(
        source_id="the-verge-ai",
        name="The Verge · AI",
        url="https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        region="global",
        origin="media",
    ),
    FeedSource(
        source_id="leader-media-clues",
        name="Google 新闻 · AI 领袖发言线索",
        url=(
            "https://news.google.com/rss/search?q=%28Sam+Altman+OR+Dario+Amodei+OR+"
            "Demis+Hassabis+OR+Jensen+Huang%29+%28said+OR+speech+OR+interview%29"
            "&hl=en-US&gl=US&ceid=US%3Aen"
        ),
        region="global",
        origin="media",
        role="leader_clue",
    ),
    FeedSource(
        source_id="openai-videos",
        name="OpenAI 官方公开视频",
        url="https://www.youtube.com/feeds/videos.xml?channel_id=UCXZCJLdBC09xxGZ6gcdrc6A",
        region="global",
        origin="official",
        role="official_voice",
    ),
)
