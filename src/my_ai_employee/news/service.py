"""AI 每日情报刷新与只读 Payload 服务。"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any, Final
from urllib.parse import urljoin, urlparse

import httpx

from my_ai_employee.news.models import FeedSource, NewsItem, RefreshResult, SourceRefreshStatus
from my_ai_employee.news.rss import deduplicate_and_sort, parse_feed
from my_ai_employee.news.sources import DEFAULT_FEED_SOURCES
from my_ai_employee.news.store import FileNewsStore

FeedFetcher = Callable[[FeedSource], bytes]
_REQUEST_TIMEOUT_SECONDS: Final = 5.0
# OpenAI 官方 Feed 的有效 XML 在高峰期可超过 512 KiB；上限仍限制在 2 MiB，
# 防止单源异常响应无限占用内存，同时不牺牲关键一手来源。
_MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
_REFRESH_INTERVAL_MINUTES: Final = 60
_FRESH_AFTER_MINUTES: Final = 90
_MAX_REDIRECTS: Final = 2


class NewsService:
    """刷新白名单来源并向 Dashboard 提供只读快照。"""

    def __init__(
        self,
        store: FileNewsStore | None = None,
        *,
        sources: tuple[FeedSource, ...] = DEFAULT_FEED_SOURCES,
    ) -> None:
        self.store = store or FileNewsStore()
        self.sources = sources

    def refresh(
        self,
        *,
        fetcher: FeedFetcher | None = None,
        now: datetime | None = None,
    ) -> RefreshResult:
        """抓取所有来源，单源失败隔离；全部失败时不覆盖上次有效快照。"""
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        retrieve = fetcher or _fetch_feed
        with self.store.refresh_lock() as acquired:
            if not acquired:
                return RefreshResult(
                    success=False,
                    wrote_snapshot=False,
                    kept_previous_snapshot=self.store.read() is not None,
                    item_count=0,
                    source_statuses=(),
                )
            return self._refresh_locked(retrieve, moment)

    def build_payload(self, *, now: datetime | None = None) -> dict[str, Any]:
        """将本地快照转换为 API Payload；绝不在请求路径访问外网。"""
        snapshot = self.store.read()
        if snapshot is None:
            return _empty_payload("not_refreshed")
        generated_at = _parse_snapshot_time(snapshot.get("generated_at"))
        if generated_at is None:
            return _empty_payload("invalid_snapshot")
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        age_minutes = max(0, int((moment - generated_at).total_seconds() // 60))
        items = _safe_items(snapshot.get("items"))
        statuses = _safe_statuses(snapshot.get("sources"))
        coverage = _safe_coverage(snapshot.get("coverage"), items=items, statuses=statuses)
        refresh_state = snapshot.get("refresh_state")
        state = _payload_state(refresh_state, age_minutes=age_minutes)
        last_attempt_at = _parse_snapshot_time(snapshot.get("last_attempt_at"))
        return {
            "read_only": True,
            "available": True,
            "state": state,
            "refresh_state": refresh_state if isinstance(refresh_state, str) else None,
            "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
            "last_attempt_at": (
                last_attempt_at.isoformat().replace("+00:00", "Z")
                if last_attempt_at is not None
                else None
            ),
            "age_minutes": age_minutes,
            "refresh_interval_minutes": _REFRESH_INTERVAL_MINUTES,
            "items": items,
            "count": len(items),
            "sources": statuses,
            "coverage": coverage,
        }

    def _refresh_locked(self, fetcher: FeedFetcher, moment: datetime) -> RefreshResult:
        previous_snapshot = self.store.read()
        statuses: dict[str, SourceRefreshStatus] = {}
        parsed_items: list[NewsItem] = []
        worker_count = max(1, min(3, len(self.sources)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures: dict[Future[bytes], FeedSource] = {
                executor.submit(fetcher, source): source for source in self.sources
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    items = parse_feed(source, future.result(), now=moment)
                except Exception as exc:  # noqa: BLE001 — 外部来源必须彼此隔离
                    statuses[source.source_id] = SourceRefreshStatus(
                        source_id=source.source_id,
                        name=source.name,
                        region=source.region,
                        origin=source.origin,
                        status="error",
                        item_count=0,
                        error=_safe_error(exc),
                    )
                else:
                    parsed_items.extend(items)
                    statuses[source.source_id] = SourceRefreshStatus(
                        source_id=source.source_id,
                        name=source.name,
                        region=source.region,
                        origin=source.origin,
                        status="ok",
                        item_count=len(items),
                    )

        ordered_statuses = tuple(statuses[source.source_id] for source in self.sources)
        if not any(status.status == "ok" for status in ordered_statuses):
            previous_items = _safe_items(
                previous_snapshot.get("items") if previous_snapshot is not None else None
            )
            if previous_snapshot is not None:
                self.store.write(
                    _degraded_snapshot(
                        previous_snapshot,
                        previous_items,
                        ordered_statuses,
                        moment=moment,
                        reason="source_failures",
                    )
                )
            return RefreshResult(
                success=False,
                wrote_snapshot=previous_snapshot is not None,
                kept_previous_snapshot=previous_snapshot is not None,
                item_count=len(previous_items),
                source_statuses=ordered_statuses,
                degraded=previous_snapshot is not None,
            )

        items = deduplicate_and_sort(parsed_items)
        previous_items = _safe_items(
            previous_snapshot.get("items") if previous_snapshot is not None else None
        )
        if not items and previous_snapshot is not None and previous_items:
            self.store.write(
                _degraded_snapshot(
                    previous_snapshot,
                    previous_items,
                    ordered_statuses,
                    moment=moment,
                    reason="empty_results",
                )
            )
            return RefreshResult(
                success=True,
                wrote_snapshot=True,
                kept_previous_snapshot=True,
                item_count=len(previous_items),
                source_statuses=ordered_statuses,
                degraded=True,
            )
        snapshot = {
            "schema_version": 1,
            "generated_at": moment.isoformat().replace("+00:00", "Z"),
            "last_attempt_at": moment.isoformat().replace("+00:00", "Z"),
            "refresh_state": "fresh" if items else "empty",
            "refresh_interval_minutes": _REFRESH_INTERVAL_MINUTES,
            "items": [item.to_dict() for item in items],
            "sources": [status.to_dict() for status in ordered_statuses],
            "coverage": _coverage(items, ordered_statuses),
        }
        self.store.write(snapshot)
        return RefreshResult(
            success=True,
            wrote_snapshot=True,
            kept_previous_snapshot=False,
            item_count=len(items),
            source_statuses=ordered_statuses,
        )


def _fetch_feed(source: FeedSource) -> bytes:
    """抓取一份固定 HTTPS Feed，并限制响应大小和重定向边界。"""
    headers = {"User-Agent": "MyAIEmployee-AINews/0.1 (+local read-only dashboard)"}
    source_origin = _feed_origin(source.url, error_message="Feed 来源 URL 不安全")
    current_url = source.url
    redirects = 0
    with httpx.Client(
        timeout=_REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        headers=headers,
    ) as client:
        while True:
            with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location or redirects >= _MAX_REDIRECTS:
                        raise ValueError("Feed 重定向被拒绝")
                    candidate_url = urljoin(str(response.url), location)
                    if (
                        _feed_origin(candidate_url, error_message="Feed 重定向被拒绝")
                        != source_origin
                    ):
                        raise ValueError("Feed 重定向被拒绝")
                    current_url = candidate_url
                    redirects += 1
                    continue
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        raise ValueError("Feed 响应超过大小上限")
                    chunks.append(chunk)
                return b"".join(chunks)


def _empty_payload(state: str) -> dict[str, Any]:
    return {
        "read_only": True,
        "available": False,
        "state": state,
        "refresh_state": None,
        "generated_at": None,
        "last_attempt_at": None,
        "age_minutes": None,
        "refresh_interval_minutes": _REFRESH_INTERVAL_MINUTES,
        "items": [],
        "count": 0,
        "sources": [],
        "coverage": {
            "domestic": 0,
            "international": 0,
            "leader_statements": 0,
            "leader_clues": 0,
            "successful_sources": 0,
            "total_sources": 0,
        },
    }


def _coverage(items: list[NewsItem], statuses: tuple[SourceRefreshStatus, ...]) -> dict[str, int]:
    return {
        "domestic": sum(item.region == "cn" for item in items),
        "international": sum(item.region == "global" for item in items),
        "leader_statements": sum(item.kind == "leader_statement" for item in items),
        "leader_clues": sum(item.kind in {"leader_clue", "official_voice"} for item in items),
        "successful_sources": sum(status.status == "ok" for status in statuses),
        "total_sources": len(statuses),
    }


def _coverage_from_stored_items(
    items: list[dict[str, object]], statuses: tuple[SourceRefreshStatus, ...]
) -> dict[str, int]:
    """为保留的旧缓存重算覆盖数，避免沿用过期来源健康状态。"""
    return {
        "domestic": sum(item.get("region") == "cn" for item in items),
        "international": sum(item.get("region") == "global" for item in items),
        "leader_statements": sum(item.get("kind") == "leader_statement" for item in items),
        "leader_clues": sum(
            item.get("kind") in {"leader_clue", "official_voice"} for item in items
        ),
        "successful_sources": sum(status.status == "ok" for status in statuses),
        "total_sources": len(statuses),
    }


def _degraded_snapshot(
    previous: dict[str, Any],
    previous_items: list[dict[str, object]],
    statuses: tuple[SourceRefreshStatus, ...],
    *,
    moment: datetime,
    reason: str,
) -> dict[str, Any]:
    """记录一次失败尝试，同时保留最后一份可展示的新闻内容和生成时间。"""
    snapshot = dict(previous)
    snapshot.update(
        {
            "schema_version": 1,
            "last_attempt_at": moment.isoformat().replace("+00:00", "Z"),
            "refresh_state": f"degraded_{reason}",
            "sources": [status.to_dict() for status in statuses],
            "coverage": _coverage_from_stored_items(previous_items, statuses),
        }
    )
    return snapshot


def _payload_state(refresh_state: object, *, age_minutes: int) -> str:
    """将缓存内部刷新结果映射为稳定的 Dashboard 状态。"""
    if isinstance(refresh_state, str) and refresh_state.startswith("degraded_"):
        return "degraded"
    if refresh_state == "empty":
        return "empty"
    return "fresh" if age_minutes <= _FRESH_AFTER_MINUTES else "stale"


def _feed_origin(value: str, *, error_message: str) -> tuple[str, str, int]:
    """解析受限 HTTPS origin；拒绝 localhost、私网字面量和非标准端口。"""
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(error_message) from exc
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise ValueError(error_message)
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError(error_message)
    try:
        address = ip_address(hostname)
    except ValueError:
        # 非 IP host 是正常的白名单域名；只需继续由同源检查约束。
        pass
    else:
        if not address.is_global:
            raise ValueError(error_message)
    return ("https", hostname, 443)


def _parse_snapshot_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _safe_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    allowed = {
        "id",
        "title",
        "summary",
        "url",
        "source",
        "source_id",
        "region",
        "origin",
        "kind",
        "published_at",
        "topics",
        "relevance",
        "speaker",
        "quote",
        "verbatim",
    }
    items: list[dict[str, object]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        title = raw.get("title")
        url = raw.get("url")
        if (
            not isinstance(title, str)
            or not title
            or not isinstance(url, str)
            or not url.startswith("https://")
        ):
            continue
        items.append({key: raw[key] for key in allowed if key in raw})
    return items


def _safe_statuses(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    statuses: list[dict[str, object]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        source_id = raw.get("source_id")
        status = raw.get("status")
        if not isinstance(source_id, str) or status not in {"ok", "error"}:
            continue
        statuses.append(
            {
                "source_id": source_id,
                "name": raw.get("name") if isinstance(raw.get("name"), str) else source_id,
                "region": raw.get("region") if isinstance(raw.get("region"), str) else "unknown",
                "origin": raw.get("origin") if isinstance(raw.get("origin"), str) else "unknown",
                "status": status,
                "item_count": (
                    raw.get("item_count") if isinstance(raw.get("item_count"), int) else 0
                ),
                "error": raw.get("error") if isinstance(raw.get("error"), str) else None,
            }
        )
    return statuses


def _safe_coverage(
    value: object,
    *,
    items: list[dict[str, object]],
    statuses: list[dict[str, object]],
) -> dict[str, int]:
    keys = (
        "domestic",
        "international",
        "leader_statements",
        "leader_clues",
        "successful_sources",
        "total_sources",
    )
    if isinstance(value, dict) and all(isinstance(value.get(key), int) for key in keys):
        return {key: int(value[key]) for key in keys}
    return {
        "domestic": sum(item.get("region") == "cn" for item in items),
        "international": sum(item.get("region") == "global" for item in items),
        "leader_statements": sum(item.get("kind") == "leader_statement" for item in items),
        "leader_clues": sum(
            item.get("kind") in {"leader_clue", "official_voice"} for item in items
        ),
        "successful_sources": sum(status.get("status") == "ok" for status in statuses),
        "total_sources": len(statuses),
    }


def _safe_error(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    return (message or exc.__class__.__name__)[:180]
