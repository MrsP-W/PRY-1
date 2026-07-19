"""RSS/Atom 解析、分类和去重。

解析器只接受采集器内置的 Feed 字节，不跟随其中的内容链接，也不执行任何
HTML/脚本。展示层仍会对所有文本进行 HTML 转义。
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import entities, unescape
from typing import Final
from urllib.parse import urlparse
from xml.etree import ElementTree

from my_ai_employee.news.models import FeedSource, NewsItem

_MAX_ITEMS_PER_FEED: Final = 12
_MAX_EVENT_AGE: Final = timedelta(hours=72)
# 逐字原话的价值通常在一周内仍高于普通快讯；单独保留更长窗口，避免周末边界
# 恰好把最近的可核验发言排除在情报台外。
_MAX_STATEMENT_AGE: Final = timedelta(days=7)
_MAX_TITLE_CHARS: Final = 300
_MAX_SUMMARY_CHARS: Final = 700
_MAX_STATEMENT_SCAN_CHARS: Final = 6_000
_MAX_VERIFIED_STATEMENTS: Final = 4
_LEADER_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "Sam Altman": ("sam altman",),
    "Dario Amodei": ("dario amodei",),
    "Demis Hassabis": ("demis hassabis",),
    "Jensen Huang": ("jensen huang", "黄仁勋"),
    "Sundar Pichai": ("sundar pichai",),
    "Satya Nadella": ("satya nadella",),
    "Mark Zuckerberg": ("mark zuckerberg",),
    "Yann LeCun": ("yann lecun",),
    "李彦宏": ("李彦宏", "robin li"),
    "李开复": ("李开复", "kai-fu lee"),
    "周鸿祎": ("周鸿祎",),
    "王小川": ("王小川",),
}
_TOPIC_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("模型", ("model", "llm", "大模型", "模型", "inference", "推理")),
    ("Agent", ("agent", "智能体", "multi-agent", "multi agent")),
    ("RAG/知识库", ("rag", "retrieval", "知识库", "检索增强")),
    ("MCP/开发工具", ("mcp", "coding", "code", "开发者", "编程")),
    ("企业AI/SAP", ("sap", "erp", "enterprise", "企业", "工作流")),
    ("安全/治理", ("safety", "security", "governance", "监管", "安全", "治理")),
)
_AI_SIGNAL_KEYWORDS: Final[tuple[str, ...]] = (
    "ai",
    "artificial intelligence",
    "人工智能",
    "大模型",
    "模型",
    "llm",
    "gpt",
    "智能体",
    "agent",
    "生成式",
    "芯片",
)
_TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_DEDUP_RE: Final[re.Pattern[str]] = re.compile(r"[^\w\u4e00-\u9fff]+")
_HTML_ENTITY_RE: Final[re.Pattern[str]] = re.compile(r"&([A-Za-z][A-Za-z0-9]+);")
_XML_ENTITIES: Final[frozenset[str]] = frozenset({"amp", "lt", "gt", "quot", "apos"})


def parse_feed(source: FeedSource, payload: bytes, *, now: datetime) -> list[NewsItem]:
    """解析单份 RSS 或 Atom Feed，返回有限、清洗后的新闻条目。

    ``now`` 用于过滤没有可验证发布日期的条目；普通动态只保留 72 小时，已核验
    的一手公开发言保留 7 天，避免周末边界丢失仍有价值的原文。
    """
    try:
        root = ElementTree.fromstring(_normalize_html_entities(payload))
    except ElementTree.ParseError as exc:
        raise ValueError("Feed XML 格式无效") from exc

    entries = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
    items: list[NewsItem] = []
    for entry in entries[:_MAX_ITEMS_PER_FEED]:
        item = _parse_entry(source, entry, now=now)
        if item is not None:
            items.append(item)
    return items


def deduplicate_and_sort(items: list[NewsItem], *, limit: int = 48) -> list[NewsItem]:
    """按标准化标题去重，并在固定容量内保留少量可核验公开发言。"""
    selected: dict[str, NewsItem] = {}
    for item in items:
        key = _dedupe_key(item.title)
        current = selected.get(key)
        if current is None or _sort_key(item) > _sort_key(current):
            selected[key] = item
    ordered = sorted(selected.values(), key=_sort_key, reverse=True)
    statements = [item for item in ordered if item.kind == "leader_statement"]
    others = [item for item in ordered if item.kind != "leader_statement"]
    return (statements[:_MAX_VERIFIED_STATEMENTS] + others)[:limit]


def _parse_entry(
    source: FeedSource,
    entry: ElementTree.Element[str],
    *,
    now: datetime,
) -> NewsItem | None:
    title = _clean_text(_child_text(entry, {"title"}), _MAX_TITLE_CHARS)
    url = _entry_url(entry)
    if not title or not _is_safe_url(url):
        return None

    statement_source = source.statement_eligible and source.origin == "official"
    summary_for_matching = _clean_text(
        _child_text(entry, {"description", "summary", "content", "encoded"}),
        _MAX_STATEMENT_SCAN_CHARS if statement_source else _MAX_SUMMARY_CHARS,
    )
    summary = summary_for_matching[:_MAX_SUMMARY_CHARS].rstrip()
    if source.require_ai_match and not _contains_ai_signal(f"{title} {summary_for_matching}"):
        return None
    publisher = _clean_text(_child_text(entry, {"source", "publisher"}), 120) or source.name
    published = _parse_datetime(_child_text(entry, {"pubdate", "published", "updated", "date"}))
    maximum_age = _MAX_STATEMENT_AGE if statement_source else _MAX_EVENT_AGE
    if published is None or published < now - maximum_age:
        return None
    speaker = _detect_speaker(f"{title} {summary_for_matching}")
    quote = (
        _extract_verified_quote(summary_for_matching, speaker)
        if statement_source and speaker
        else None
    )
    kind = _kind_for(source, speaker=speaker, quote=quote)
    topics = _classify_topics(f"{title} {summary_for_matching}")
    relevance = _relevance_for(topics)
    item_id = hashlib.sha256(f"{source.source_id}|{url}|{title}".encode()).hexdigest()[:20]
    return NewsItem(
        item_id=item_id,
        title=title,
        summary=summary,
        url=url,
        source=publisher,
        source_id=source.source_id,
        region=source.region,
        origin=source.origin,
        kind=kind,
        published_at=published.isoformat().replace("+00:00", "Z"),
        topics=topics,
        relevance=relevance,
        speaker=speaker,
        quote=quote,
        verbatim=quote is not None,
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1].lower()


def _child_text(entry: ElementTree.Element[str], names: set[str]) -> str:
    for child in list(entry):
        if _local_name(child.tag) in names and child.text:
            return child.text
    return ""


def _entry_url(entry: ElementTree.Element[str]) -> str:
    for child in list(entry):
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "")
        relation = child.attrib.get("rel", "alternate")
        if href and relation in {"", "alternate"}:
            return href
        if child.text:
            return child.text
    return ""


def _clean_text(value: str, max_chars: int) -> str:
    decoded = value
    # 一些 RSS 会把 CDATA 内的 HTML 实体再编码一层（例如 ``&amp;ldquo;``）。
    # 有限次解码即可还原原话，同时不会解析或执行 HTML。
    for _ in range(3):
        unescaped = unescape(decoded)
        if unescaped == decoded:
            break
        decoded = unescaped
    decoded = decoded.replace("<![CDATA[", "").replace("]]>", "")
    collapsed = _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", decoded)).strip()
    return collapsed[:max_chars].rstrip()


def _normalize_html_entities(payload: bytes) -> bytes:
    """把 RSS 中常见但非 XML 标准的 HTML 实体转为数值实体。

    合法 XML 实体保持原样；未知实体保持不变，由 XML 解析器将该 Feed 标为失败，
    这样不会在错误恢复时悄悄篡改原文。
    """
    text = payload.decode("utf-8", errors="replace")

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in _XML_ENTITIES:
            return match.group(0)
        decoded = entities.html5.get(f"{name};")
        if decoded is None:
            return match.group(0)
        return "".join(f"&#{ord(char)};" for char in decoded)

    return _HTML_ENTITY_RE.sub(replace, text).encode("utf-8")


def _is_safe_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and len(value) <= 2048


def _parse_datetime(value: str) -> datetime | None:
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
        except (TypeError, ValueError):
            pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
        except ValueError:
            pass
    return None


def _detect_speaker(value: str) -> str | None:
    lowered = value.lower()
    for speaker, aliases in _LEADER_ALIASES.items():
        if any(alias.lower() in lowered for alias in aliases):
            return speaker
    return None


def _extract_verified_quote(summary: str, speaker: str) -> str | None:
    """仅提取和已识别说话人紧邻、带明确归因的逐字摘录。

    一手 Feed 也可能包含采访转述或别人的引语，因此不能只因同一条目里出现姓名
    和引号就标记为原话。支持“某人表示：‘…’”与“‘…’，某人表示”两种常见格式。
    """
    aliases = _LEADER_ALIASES[speaker]
    speaker_pattern = "|".join(re.escape(alias) for alias in aliases)
    attribution = r"(?:said|says|stated|wrote|表示|称|指出|说)"
    after_speaker = re.compile(
        rf"(?:{speaker_pattern})\s*{attribution}[^\"“]{{0,96}}[\"“]([^\"”]{{12,280}})[\"”]",
        flags=re.IGNORECASE,
    )
    before_speaker = re.compile(
        rf"[\"“]([^\"”]{{12,280}})[\"”]\s*[,，]?\s*{attribution}\s+(?:{speaker_pattern})",
        flags=re.IGNORECASE,
    )
    for pattern in (after_speaker, before_speaker):
        match = pattern.search(summary)
        if match:
            return match.group(1).strip()
    return None


def _kind_for(source: FeedSource, *, speaker: str | None, quote: str | None) -> str:
    if source.statement_eligible and source.origin == "official" and speaker and quote:
        return "leader_statement"
    if source.role == "official_voice":
        return "official_voice"
    if source.role == "leader_clue" or speaker:
        return "leader_clue"
    return "event"


def _classify_topics(value: str) -> tuple[str, ...]:
    lowered = value.lower()
    topics = tuple(
        label
        for label, keywords in _TOPIC_RULES
        if any(keyword.lower() in lowered for keyword in keywords)
    )
    return topics or ("AI动态",)


def _contains_ai_signal(value: str) -> bool:
    lowered = value.lower()
    for keyword in _AI_SIGNAL_KEYWORDS:
        if keyword == "ai":
            if re.search(r"\bai\b", lowered):
                return True
        elif keyword.lower() in lowered:
            return True
    return False


def _relevance_for(topics: tuple[str, ...]) -> str:
    workflow_topics = {"Agent", "RAG/知识库", "MCP/开发工具", "企业AI/SAP", "安全/治理"}
    return "high" if workflow_topics.intersection(topics) else "normal"


def _dedupe_key(title: str) -> str:
    return _DEDUP_RE.sub("", title.lower())[:300]


def _sort_key(item: NewsItem) -> tuple[str, int, int, int]:
    return (
        item.published_at,
        1 if item.origin == "official" else 0,
        1 if item.relevance == "high" else 0,
        1 if item.kind == "leader_statement" else 0,
    )
