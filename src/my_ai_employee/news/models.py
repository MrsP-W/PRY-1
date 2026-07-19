"""AI 每日情报的数据契约。

该模块只承载公开来源的元数据与短摘要，不保存账号、Cookie、全文或任何私有内容。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeedSource:
    """允许抓取的公开 HTTPS Feed。

    ``role`` 只影响展示和分类，不会让采集器擅自把媒体转述当作领导人原话。
    """

    source_id: str
    name: str
    url: str
    region: str
    origin: str
    role: str = "event"
    require_ai_match: bool = False
    statement_eligible: bool = False


@dataclass(frozen=True, slots=True)
class NewsItem:
    """供本地缓存与 Dashboard 展示的一条已脱敏新闻元数据。"""

    item_id: str
    title: str
    summary: str
    url: str
    source: str
    source_id: str
    region: str
    origin: str
    kind: str
    published_at: str
    topics: tuple[str, ...]
    relevance: str
    speaker: str | None = None
    quote: str | None = None
    verbatim: bool = False

    def to_dict(self) -> dict[str, object]:
        """转换成 JSON 兼容字典。"""
        return {
            "id": self.item_id,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "source": self.source,
            "source_id": self.source_id,
            "region": self.region,
            "origin": self.origin,
            "kind": self.kind,
            "published_at": self.published_at,
            "topics": list(self.topics),
            "relevance": self.relevance,
            "speaker": self.speaker,
            "quote": self.quote,
            "verbatim": self.verbatim,
        }


@dataclass(frozen=True, slots=True)
class SourceRefreshStatus:
    """单一来源的刷新结果；失败不影响其他来源。"""

    source_id: str
    name: str
    region: str
    origin: str
    status: str
    item_count: int
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """转换成 JSON 兼容字典。"""
        return {
            "source_id": self.source_id,
            "name": self.name,
            "region": self.region,
            "origin": self.origin,
            "status": self.status,
            "item_count": self.item_count,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """一次刷新运行的结果，供 CLI 和测试使用。"""

    success: bool
    wrote_snapshot: bool
    kept_previous_snapshot: bool
    item_count: int
    source_statuses: tuple[SourceRefreshStatus, ...]
    # 来源可访问但本轮没有任何合格条目时，保留旧情报并显式降级；
    # 这与“所有来源请求失败”不同，CLI 可据此给出准确提示。
    degraded: bool = False
