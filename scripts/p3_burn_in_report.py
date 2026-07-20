"""P3 长稳观察的本地只读报告器。

``start`` 只创建一次 epoch marker；``report`` 仅汇总 marker 之后的脱敏运行
记录。报告不会请求网络、控制服务或读取任何错误文件正文。完整 UTC 日和完整
ISO 周才会写入本机 Application Support，避免把进行中的窗口误报为验收证据。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
JOURNAL_SCHEMA_VERSION = 1
HEALTH_GAP_SECONDS = 30 * 60
NEWS_GAP_SECONDS = 2 * 60 * 60
PASS_AFTER_DAYS = 30
SEVEN_DAY_TARGET = 7
MAX_REPORTED_GAPS = 20

_SAFE_CODE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_DASHBOARD_PORT = 8765
_PID_LABELS = (
    "com.myaiemployee.menu-bar",
    "com.myaiemployee.dashboard",
)
_METADATA_KEYS = ("menu_bar", "dashboard")
_NEWS_OUTCOMES = frozenset(
    {"success", "degraded", "all_sources_failed", "overlap", "runtime_error"}
)
_NEWS_SOURCE_STATUSES = frozenset({"ok", "error"})


class BurnInAlreadyStartedError(RuntimeError):
    """已有 marker 时拒绝覆盖，避免混合两段观察窗口。"""


class BurnInStateError(RuntimeError):
    """marker 缺失或不符合最小契约。"""


@dataclass(frozen=True)
class JournalRead:
    """一个 JSONL 输入的可用对象与被隔离的坏行数量。"""

    records: tuple[dict[str, Any], ...]
    invalid_lines: int
    unavailable: bool


@dataclass(frozen=True)
class HealthSample:
    """健康输入中足以生成 P3 证据的脱敏字段。"""

    at: datetime
    healthy: bool
    attempts: int
    recovered_by_retry: bool
    reasons: tuple[str, ...]
    pids: dict[str, int | None]
    stderr_metadata: dict[str, tuple[bool, int | None, int | None]]


@dataclass(frozen=True)
class HealthAlert:
    """结构化告警的最小安全字段。"""

    at: datetime
    event: str
    failure_streak: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class NewsRun:
    """新闻 one-shot 运行历史的最小安全字段。"""

    at: datetime
    outcome: str
    item_count: int
    sources: tuple[tuple[str, str, int], ...]


@dataclass(frozen=True)
class BurnInReportResult:
    """一次 report 执行的简短结果，适合 launchd stdout。"""

    started: bool
    result: str
    status: str | None
    epoch_started_at: datetime | None
    daily_written: int = 0
    weekly_written: int = 0
    attention: tuple[str, ...] = ()
    progress: dict[str, dict[str, bool | int]] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "action": "report",
            "started": self.started,
            "result": self.result,
        }
        if self.started:
            payload.update(
                {
                    "status": self.status,
                    "epoch_started_at": _format_time(self.epoch_started_at),
                    "reports_written": {
                        "daily": self.daily_written,
                        "weekly": self.weekly_written,
                    },
                    "attention": list(self.attention),
                    "progress": self.progress or {},
                }
            )
        return payload


def default_app_support_dir() -> Path:
    """返回本机状态根；测试可通过环境变量或 CLI 覆盖。"""

    configured = os.environ.get("MY_AI_EMPLOYEE_APP_SUPPORT_DIR", "").strip()
    return (
        Path(configured) if configured else Path.home() / "Library/Application Support/MyAIEmployee"
    )


def _normalise_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _format_time(value: datetime | None) -> str | None:
    return _normalise_utc(value).isoformat() if value is not None else None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _normalise_utc(parsed)


def _parse_utc_time(value: object) -> datetime | None:
    """仅接受带显式 UTC 偏移的 journal 时间，拒绝本地时区歧义。"""

    if not isinstance(value, str) or not value:
        return None
    normalised = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def _safe_int(value: object, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _safe_code(value: object) -> str | None:
    if not isinstance(value, str) or not _SAFE_CODE.fullmatch(value):
        return None
    return value


def _strict_codes(value: object) -> tuple[str, ...] | None:
    """验证 journal 中的原因码数组，禁止静默丢弃坏字段。"""

    if not isinstance(value, list):
        return None
    codes: list[str] = []
    for item in value:
        code = _safe_code(item)
        if code is None:
            return None
        codes.append(code)
    return tuple(codes)


def _valid_optional_int(value: object, *, minimum: int = 0) -> bool:
    return value is None or _safe_int(value, minimum=minimum) is not None


def _dedupe(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def ensure_private_directory(path: Path) -> None:
    """创建仅当前用户可访问的状态目录。"""

    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def write_text_atomic(path: Path, content: str) -> None:
    """以 fsync 后的原子替换写出私有文件。"""

    ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """写入稳定排序的 JSON，便于只读核验。"""

    write_text_atomic(
        path, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )


def write_marker_once(path: Path, payload: dict[str, Any]) -> None:
    """以 ``O_EXCL`` 创建 Day0 marker，任何并发调用都不能覆盖首个 epoch。"""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise BurnInAlreadyStartedError("burn-in marker already exists") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())
        os.fchmod(output.fileno(), 0o600)


def _resolve_paths(
    *,
    app_support_dir: Path | None,
    state_dir: Path | None,
    health_dir: Path | None,
    news_dir: Path | None,
) -> tuple[Path, Path, Path, Path]:
    root = app_support_dir or (
        state_dir.parent if state_dir is not None else default_app_support_dir()
    )
    return (
        root,
        state_dir or root / "burn-in",
        health_dir or root / "health",
        news_dir or root / "news",
    )


def _state_path(state_dir: Path) -> Path:
    return state_dir / "state.json"


def start_burn_in(
    *,
    app_support_dir: Path | None = None,
    state_dir: Path | None = None,
    now_fn: Callable[[], datetime] = _now_utc,
) -> datetime:
    """创建不可覆盖的 P3 epoch marker，且不读取任何运行 journal。"""

    _, resolved_state_dir, _, _ = _resolve_paths(
        app_support_dir=app_support_dir,
        state_dir=state_dir,
        health_dir=None,
        news_dir=None,
    )
    ensure_private_directory(resolved_state_dir)
    marker_path = _state_path(resolved_state_dir)
    started_at = _normalise_utc(now_fn())
    write_marker_once(
        marker_path,
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "p3_burn_in_epoch",
            "started_at": started_at.isoformat(),
            "time_basis": "UTC",
        },
    )
    return started_at


def load_epoch_marker(state_dir: Path) -> datetime:
    """读取 epoch；损坏 marker 不能被误当作新观察窗口。"""

    marker_path = _state_path(state_dir)
    try:
        with marker_path.open("rb") as handle:
            raw = json.loads(handle.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BurnInStateError("burn-in marker unavailable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise BurnInStateError("burn-in marker invalid")
    if raw.get("kind") != "p3_burn_in_epoch":
        raise BurnInStateError("burn-in marker invalid")
    started_at = _parse_time(raw.get("started_at"))
    if started_at is None:
        raise BurnInStateError("burn-in marker invalid")
    return started_at


def read_jsonl(path: Path) -> JournalRead:
    """逐行读取 JSONL；坏行（含未完成尾行）隔离而不阻断报告。"""

    records: list[dict[str, Any]] = []
    invalid_lines = 0
    try:
        with path.open("rb") as input_file:
            for raw_line in input_file:
                if not raw_line.strip():
                    continue
                try:
                    decoded = raw_line.decode("utf-8")
                    parsed = json.loads(decoded)
                except (UnicodeError, json.JSONDecodeError):
                    invalid_lines += 1
                    continue
                if isinstance(parsed, dict):
                    records.append(parsed)
                else:
                    invalid_lines += 1
    except FileNotFoundError:
        # 告警 journal 在从未触发告警时不存在是正常状态；缺少样本/新闻仍会由
        # 窗口缺口判定出来，不能把它误写成“读取故障”。
        return JournalRead(records=(), invalid_lines=0, unavailable=False)
    except OSError:
        return JournalRead(records=(), invalid_lines=0, unavailable=True)
    return JournalRead(records=tuple(records), invalid_lines=invalid_lines, unavailable=False)


def _parse_metadata(value: object) -> dict[str, tuple[bool, int | None, int | None]] | None:
    """严格读取两个 stderr 的无内容元数据。"""

    if not isinstance(value, dict):
        return None
    metadata: dict[str, tuple[bool, int | None, int | None]] = {}
    for key in _METADATA_KEYS:
        raw_entry = value.get(key)
        if (
            not isinstance(raw_entry, dict)
            or not isinstance(raw_entry.get("exists"), bool)
            or "size_bytes" not in raw_entry
            or "mtime_epoch" not in raw_entry
            or not _valid_optional_int(raw_entry["size_bytes"])
            or not _valid_optional_int(raw_entry["mtime_epoch"])
        ):
            return None
        size = _safe_int(raw_entry.get("size_bytes"))
        mtime = _safe_int(raw_entry.get("mtime_epoch"))
        metadata[key] = raw_entry["exists"], size, mtime
    return metadata


def _parse_health_jobs(value: object) -> dict[str, tuple[bool, bool, int | None]] | None:
    """验证 P1 写入的两个关键 launchd job 快照。"""

    if not isinstance(value, dict):
        return None
    jobs: dict[str, tuple[bool, bool, int | None]] = {}
    for label in _PID_LABELS:
        raw_job = value.get(label)
        if (
            not isinstance(raw_job, dict)
            or not isinstance(raw_job.get("registered"), bool)
            or not isinstance(raw_job.get("required_running"), bool)
            or "pid" not in raw_job
            or (raw_job["pid"] is not None and _safe_int(raw_job["pid"], minimum=1) is None)
        ):
            return None
        jobs[label] = (
            raw_job["registered"],
            raw_job["required_running"],
            _safe_int(raw_job["pid"], minimum=1),
        )
    return jobs


def _parse_dashboard_listener(value: object) -> tuple[bool, tuple[int, ...]] | None:
    """验证 loopback :8765 元数据，且不保留其余网络信息。"""

    if (
        not isinstance(value, dict)
        or value.get("port") != _DASHBOARD_PORT
        or not isinstance(value.get("loopback_listening"), bool)
        or not isinstance(value.get("pids"), list)
    ):
        return None
    pids: list[int] = []
    for raw_pid in value["pids"]:
        pid = _safe_int(raw_pid, minimum=1)
        if pid is None:
            return None
        pids.append(pid)
    return value["loopback_listening"], tuple(pids)


def _parse_dashboard_health(value: object) -> tuple[bool, bool] | None:
    if not isinstance(value, dict):
        return None
    ok = value.get("ok")
    read_only = value.get("read_only")
    if not isinstance(ok, bool) or not isinstance(read_only, bool):
        return None
    return ok, read_only


def _parse_health_samples(
    records: Iterable[dict[str, Any]], *, epoch: datetime
) -> tuple[list[HealthSample], int]:
    samples: list[HealthSample] = []
    invalid_records = 0
    for raw in records:
        at = _parse_utc_time(raw.get("at"))
        if at is None:
            invalid_records += 1
            continue
        if at < epoch:
            continue
        sample = raw.get("sample")
        attempts = _safe_int(raw.get("attempts"), minimum=1)
        recovered_by_retry = raw.get("recovered_by_retry")
        if (
            raw.get("schema_version") != JOURNAL_SCHEMA_VERSION
            or not isinstance(sample, dict)
            or sample.get("schema_version") != JOURNAL_SCHEMA_VERSION
            or not isinstance(sample.get("healthy"), bool)
            or attempts is None
            or not isinstance(recovered_by_retry, bool)
        ):
            invalid_records += 1
            continue
        reasons = _strict_codes(sample.get("reasons"))
        jobs = _parse_health_jobs(sample.get("jobs"))
        listener = _parse_dashboard_listener(sample.get("dashboard_listener"))
        dashboard_health = _parse_dashboard_health(sample.get("dashboard_health"))
        stderr_metadata = _parse_metadata(sample.get("error_log_metadata"))
        if (
            reasons is None
            or jobs is None
            or listener is None
            or dashboard_health is None
            or stderr_metadata is None
        ):
            invalid_records += 1
            continue
        listener_healthy, listener_pids = listener
        dashboard_ok, dashboard_read_only = dashboard_health
        if sample["healthy"] is True and (
            reasons
            or not all(
                registered and required_running and pid is not None
                for registered, required_running, pid in jobs.values()
            )
            or not listener_healthy
            or not listener_pids
            or not dashboard_ok
            or not dashboard_read_only
        ):
            invalid_records += 1
            continue
        samples.append(
            HealthSample(
                at=at,
                healthy=sample["healthy"],
                attempts=attempts,
                recovered_by_retry=recovered_by_retry,
                reasons=reasons,
                pids={label: job[2] for label, job in jobs.items()},
                stderr_metadata=stderr_metadata,
            )
        )
    return sorted(samples, key=lambda item: item.at), invalid_records


def _parse_alerts(
    records: Iterable[dict[str, Any]], *, epoch: datetime
) -> tuple[list[HealthAlert], int]:
    alerts: list[HealthAlert] = []
    invalid_records = 0
    for raw in records:
        at = _parse_utc_time(raw.get("at"))
        if at is None:
            invalid_records += 1
            continue
        if at < epoch:
            continue
        event = raw.get("event")
        streak = _safe_int(raw.get("failure_streak"), minimum=0)
        reasons = _strict_codes(raw.get("reasons"))
        if (
            raw.get("schema_version") != JOURNAL_SCHEMA_VERSION
            or event not in {"opened", "resolved"}
            or streak is None
            or reasons is None
        ):
            invalid_records += 1
            continue
        alerts.append(
            HealthAlert(
                at=at,
                event=event,
                failure_streak=streak,
                reasons=reasons,
            )
        )
    return sorted(alerts, key=lambda item: item.at), invalid_records


def _parse_news_sources(value: object) -> tuple[tuple[str, str, int], ...] | None:
    """只接受白名单化新闻回执里的每来源计数。"""

    if not isinstance(value, list):
        return None
    sources: list[tuple[str, str, int]] = []
    for raw_source in value:
        if not isinstance(raw_source, dict):
            return None
        source_id = _safe_code(raw_source.get("source_id"))
        status = raw_source.get("status")
        item_count = _safe_int(raw_source.get("item_count"))
        if source_id is None or status not in _NEWS_SOURCE_STATUSES or item_count is None:
            return None
        sources.append((source_id, status, item_count))
    return tuple(sources)


def _parse_news_runs(
    records: Iterable[dict[str, Any]], *, epoch: datetime
) -> tuple[list[NewsRun], int]:
    runs: list[NewsRun] = []
    invalid_records = 0
    for raw in records:
        at = _parse_utc_time(raw.get("at"))
        if at is None:
            invalid_records += 1
            continue
        if at < epoch:
            continue
        outcome = raw.get("outcome")
        success = raw.get("success")
        degraded = raw.get("degraded")
        item_count = _safe_int(raw.get("item_count"))
        sources = _parse_news_sources(raw.get("sources"))
        if (
            raw.get("schema_version") != JOURNAL_SCHEMA_VERSION
            or outcome not in _NEWS_OUTCOMES
            or not isinstance(success, bool)
            or not isinstance(degraded, bool)
            or item_count is None
            or sources is None
        ):
            invalid_records += 1
            continue
        has_ok_source = any(status == "ok" for _, status, _ in sources)
        if (
            (outcome == "success" and (not success or degraded or not has_ok_source))
            or (outcome == "degraded" and (not success or not degraded or not has_ok_source))
            or (outcome == "all_sources_failed" and (success or has_ok_source))
            or (outcome == "overlap" and (success or degraded or sources))
            or (outcome == "runtime_error" and (success or degraded or item_count != 0 or sources))
        ):
            invalid_records += 1
            continue
        runs.append(
            NewsRun(
                at=at,
                outcome=outcome if outcome in {"success", "degraded", "overlap"} else "failure",
                item_count=item_count,
                sources=sources,
            )
        )
    return sorted(runs, key=lambda item: item.at), invalid_records


def _interval_gaps(
    times: Iterable[datetime],
    *,
    start: datetime,
    end: datetime,
    threshold_seconds: int,
) -> dict[str, Any]:
    ordered = [start, *sorted(times), end]
    gaps: list[dict[str, Any]] = []
    total = 0
    maximum = 0
    for previous, current in zip(ordered, ordered[1:], strict=False):
        seconds = max(0, int((current - previous).total_seconds()))
        if seconds <= threshold_seconds:
            continue
        total += 1
        maximum = max(maximum, seconds)
        if len(gaps) < MAX_REPORTED_GAPS:
            gaps.append(
                {
                    "from": previous.isoformat(),
                    "to": current.isoformat(),
                    "seconds": seconds,
                }
            )
    return {
        "threshold_seconds": threshold_seconds,
        "count": total,
        "max_seconds": maximum,
        "intervals": gaps,
        "truncated": total > len(gaps),
    }


def _changes[T](values: Iterable[tuple[datetime, T]]) -> int:
    previous: T | None = None
    seen = False
    count = 0
    for _, value in sorted(values, key=lambda item: item[0]):
        if seen and value != previous:
            count += 1
        previous = value
        seen = True
    return count


def _in_period[T](
    records: Iterable[T],
    *,
    start: datetime,
    end: datetime,
    at: Callable[[T], datetime],
) -> list[T]:
    return [record for record in records if start <= at(record) < end]


def _health_summary(
    samples: Iterable[HealthSample],
    alerts: Iterable[HealthAlert],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    selected = _in_period(samples, start=start, end=end, at=lambda sample: sample.at)
    selected_alerts = _in_period(alerts, start=start, end=end, at=lambda alert: alert.at)
    reason_counts: Counter[str] = Counter()
    for sample in selected:
        reason_counts.update(sample.reasons)

    pid_changes = {
        label: _changes((sample.at, sample.pids.get(label)) for sample in selected)
        for label in _PID_LABELS
    }
    stderr_changes: dict[str, int] = {}
    stderr_seen: dict[str, int] = {}
    for key in _METADATA_KEYS:
        observations = [
            (sample.at, sample.stderr_metadata[key])
            for sample in selected
            if key in sample.stderr_metadata
        ]
        stderr_seen[key] = len(observations)
        stderr_changes[key] = _changes(observations)

    alert_reasons: Counter[str] = Counter()
    for alert in selected_alerts:
        alert_reasons.update(alert.reasons)

    return {
        "samples": {
            "count": len(selected),
            "healthy": sum(sample.healthy for sample in selected),
            "unhealthy": sum(not sample.healthy for sample in selected),
            "recovered_by_retry": sum(sample.recovered_by_retry for sample in selected),
            "attempts_total": sum(sample.attempts for sample in selected),
            "gaps": _interval_gaps(
                (sample.at for sample in selected),
                start=start,
                end=end,
                threshold_seconds=HEALTH_GAP_SECONDS,
            ),
            "reason_counts": dict(sorted(reason_counts.items())),
        },
        "pid_changes": pid_changes,
        "stderr_metadata": {
            "observations": stderr_seen,
            "changes": stderr_changes,
        },
        "alerts": {
            "opened": sum(alert.event == "opened" for alert in selected_alerts),
            "resolved": sum(alert.event == "resolved" for alert in selected_alerts),
            "reason_counts": dict(sorted(alert_reasons.items())),
        },
    }


def _news_summary(runs: Iterable[NewsRun], *, start: datetime, end: datetime) -> dict[str, Any]:
    selected = _in_period(runs, start=start, end=end, at=lambda run: run.at)
    outcomes: Counter[str] = Counter(run.outcome for run in selected)
    source_statuses: dict[str, Counter[str]] = defaultdict(Counter)
    source_items: Counter[str] = Counter()
    for run in selected:
        for source_id, status, item_count in run.sources:
            source_statuses[source_id][status] += 1
            source_items[source_id] += item_count
    return {
        "runs": {
            "count": len(selected),
            "success": outcomes["success"],
            "degraded": outcomes["degraded"],
            "failure": outcomes["failure"],
            "overlap": outcomes["overlap"],
            "item_count_total": sum(run.item_count for run in selected),
            "gaps": _interval_gaps(
                (run.at for run in selected),
                start=start,
                end=end,
                threshold_seconds=NEWS_GAP_SECONDS,
            ),
        },
        "sources": {
            source_id: {
                "status_counts": dict(sorted(statuses.items())),
                "item_count_total": source_items[source_id],
            }
            for source_id, statuses in sorted(source_statuses.items())
        },
    }


def _attention_from_summary(
    health: dict[str, Any],
    news: dict[str, Any],
    *,
    input_integrity: dict[str, int | bool] | None = None,
) -> list[str]:
    attention: list[str] = []
    health_samples = health["samples"]
    health_alerts = health["alerts"]
    news_runs = news["runs"]
    if health_samples["unhealthy"]:
        attention.append("health_unhealthy_sample")
    if health_samples["gaps"]["count"]:
        attention.append("health_sample_gap")
    if health_alerts["opened"]:
        attention.append("health_alert_opened")
    if news_runs["gaps"]["count"]:
        attention.append("news_run_gap")
    if news_runs["degraded"]:
        attention.append("news_degraded")
    if news_runs["failure"]:
        attention.append("news_failure")
    if news_runs["overlap"]:
        attention.append("news_overlap")
    if input_integrity is not None and any(
        value is True or (isinstance(value, int) and value > 0)
        for value in input_integrity.values()
    ):
        attention.append("input_integrity_issue")
    return attention


def _period_payload(
    *,
    report_type: str,
    period_id: str,
    start: datetime,
    end: datetime,
    epoch: datetime,
    generated_at: datetime,
    overall_status: str,
    samples: Iterable[HealthSample],
    alerts: Iterable[HealthAlert],
    news_runs: Iterable[NewsRun],
    input_integrity: dict[str, int | bool],
) -> dict[str, Any]:
    health = _health_summary(samples, alerts, start=start, end=end)
    news = _news_summary(news_runs, start=start, end=end)
    attention = _attention_from_summary(health, news, input_integrity=input_integrity)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": report_type,
        "time_basis": "UTC",
        "generated_at": generated_at.isoformat(),
        "epoch_started_at": epoch.isoformat(),
        "period": {
            "id": period_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "complete": True,
        },
        "status": "attention" if attention else "pass",
        "burn_in_status": overall_status,
        "health": health,
        "news": news,
        "input_integrity": input_integrity,
        "attention": attention,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    """渲染短报告；不转储输入记录、错误文本或新闻内容。"""

    period = payload["period"]
    health = payload["health"]
    news = payload["news"]
    health_samples = health["samples"]
    health_alerts = health["alerts"]
    news_runs = news["runs"]
    attention = payload["attention"]
    lines = [
        f"# P3 burn-in {payload['report_type']} report — {period['id']}",
        "",
        f"- Period (UTC): `{period['start']}` → `{period['end']}`",
        f"- Period status: `{payload['status']}`",
        f"- Current burn-in status: `{payload['burn_in_status']}`",
        "",
        "## Health evidence",
        "",
        (
            "- Samples: "
            f"`{health_samples['count']}` total / `{health_samples['healthy']}` healthy / "
            f"`{health_samples['unhealthy']}` unhealthy / "
            f"`{health_samples['recovered_by_retry']}` retry recoveries"
        ),
        (
            "- Sample gaps: "
            f"`{health_samples['gaps']['count']}` "
            f"(max `{health_samples['gaps']['max_seconds']}s`)"
        ),
        f"- Alerts: `{health_alerts['opened']}` opened / `{health_alerts['resolved']}` resolved",
        f"- PID changes: `{sum(health['pid_changes'].values())}`",
        f"- stderr metadata changes: `{sum(health['stderr_metadata']['changes'].values())}`",
        "",
        "## News evidence",
        "",
        (
            "- Runs: "
            f"`{news_runs['count']}` total / `{news_runs['success']}` success / "
            f"`{news_runs['degraded']}` degraded / `{news_runs['failure']}` failure / "
            f"`{news_runs['overlap']}` overlap"
        ),
        f"- Run gaps: `{news_runs['gaps']['count']}` (max `{news_runs['gaps']['max_seconds']}s`)",
        "",
        "## Attention",
        "",
    ]
    lines.extend(f"- `{item}`" for item in attention) if attention else lines.append("- none")
    return "\n".join(lines) + "\n"


def _complete_days(epoch: datetime, now: datetime) -> list[date]:
    """返回 marker 起第二天开始、且已经结束的 UTC 日。"""

    first = epoch.date() + timedelta(days=1)
    last = now.date() - timedelta(days=1)
    if first > last:
        return []
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _complete_weeks(epoch: datetime, now: datetime) -> list[date]:
    """返回完全位于 epoch 后且已经结束的 ISO 周一。"""

    first_day = epoch.date() + timedelta(days=1)
    first_monday = first_day + timedelta(days=(7 - first_day.weekday()) % 7)
    starts: list[date] = []
    current = first_monday
    while current + timedelta(days=7) <= now.date():
        starts.append(current)
        current += timedelta(days=7)
    return starts


def _progress(
    *, epoch: datetime, now: datetime, has_attention: bool
) -> dict[str, dict[str, bool | int]]:
    elapsed_seconds = max(0, int((now - epoch).total_seconds()))
    elapsed_days = elapsed_seconds // (24 * 60 * 60)
    return {
        "seven_day_unattended": {
            "required_days": SEVEN_DAY_TARGET,
            "elapsed_days": elapsed_days,
            "eligible": elapsed_days >= SEVEN_DAY_TARGET and not has_attention,
        },
        "thirty_day_no_p0_p1": {
            "required_days": PASS_AFTER_DAYS,
            "elapsed_days": elapsed_days,
            "eligible": elapsed_days >= PASS_AFTER_DAYS and not has_attention,
        },
    }


def _write_report(directory: Path, stem: str, payload: dict[str, Any]) -> None:
    ensure_private_directory(directory)
    write_json_atomic(directory / f"{stem}.json", payload)
    write_text_atomic(directory / f"{stem}.md", render_markdown(payload))


def run_report(
    *,
    app_support_dir: Path | None = None,
    state_dir: Path | None = None,
    health_dir: Path | None = None,
    news_dir: Path | None = None,
    now_fn: Callable[[], datetime] = _now_utc,
) -> BurnInReportResult:
    """汇总 epoch 后运行证据；未开始时只返回安全状态，不写伪证据。"""

    _, resolved_state_dir, resolved_health_dir, resolved_news_dir = _resolve_paths(
        app_support_dir=app_support_dir,
        state_dir=state_dir,
        health_dir=health_dir,
        news_dir=news_dir,
    )
    marker_path = _state_path(resolved_state_dir)
    if not marker_path.exists() and not marker_path.is_symlink():
        return BurnInReportResult(
            started=False,
            result="not_started",
            status=None,
            epoch_started_at=None,
        )
    try:
        epoch = load_epoch_marker(resolved_state_dir)
    except BurnInStateError:
        return BurnInReportResult(
            started=False,
            result="state_invalid",
            status=None,
            epoch_started_at=None,
        )

    now = _normalise_utc(now_fn())
    samples_input = read_jsonl(resolved_health_dir / "samples.jsonl")
    alerts_input = read_jsonl(resolved_health_dir / "alerts.jsonl")
    news_input = read_jsonl(resolved_news_dir / "runs.jsonl")
    samples, invalid_samples = _parse_health_samples(samples_input.records, epoch=epoch)
    alerts, invalid_alerts = _parse_alerts(alerts_input.records, epoch=epoch)
    news_runs, invalid_news = _parse_news_runs(news_input.records, epoch=epoch)
    input_integrity: dict[str, int | bool] = {
        "health_sample_invalid_lines": samples_input.invalid_lines + invalid_samples,
        "health_alert_invalid_lines": alerts_input.invalid_lines + invalid_alerts,
        "news_run_invalid_lines": news_input.invalid_lines + invalid_news,
        "health_sample_unavailable": samples_input.unavailable,
        "health_alert_unavailable": alerts_input.unavailable,
        "news_run_unavailable": news_input.unavailable,
    }

    health = _health_summary(samples, alerts, start=epoch, end=now)
    news = _news_summary(news_runs, start=epoch, end=now)
    attention = _dedupe(_attention_from_summary(health, news, input_integrity=input_integrity))
    progress = _progress(epoch=epoch, now=now, has_attention=bool(attention))
    if attention:
        status = "attention"
    elif progress["thirty_day_no_p0_p1"]["eligible"] is True:
        status = "pass"
    else:
        status = "collecting"

    daily_dir = resolved_state_dir / "daily"
    weekly_dir = resolved_state_dir / "weekly"
    daily_written = 0
    weekly_written = 0
    for day in _complete_days(epoch, now):
        start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=1)
        payload = _period_payload(
            report_type="daily",
            period_id=day.isoformat(),
            start=start,
            end=end,
            epoch=epoch,
            generated_at=now,
            overall_status=status,
            samples=samples,
            alerts=alerts,
            news_runs=news_runs,
            input_integrity=input_integrity,
        )
        _write_report(daily_dir, day.isoformat(), payload)
        daily_written += 1
    for week_start_day in _complete_weeks(epoch, now):
        iso_year, iso_week, _ = week_start_day.isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"
        start = datetime.combine(week_start_day, datetime.min.time(), tzinfo=UTC)
        end = start + timedelta(days=7)
        payload = _period_payload(
            report_type="weekly",
            period_id=week_id,
            start=start,
            end=end,
            epoch=epoch,
            generated_at=now,
            overall_status=status,
            samples=samples,
            alerts=alerts,
            news_runs=news_runs,
            input_integrity=input_integrity,
        )
        _write_report(weekly_dir, week_id, payload)
        weekly_written += 1
    return BurnInReportResult(
        started=True,
        result="reported",
        status=status,
        epoch_started_at=epoch,
        daily_written=daily_written,
        weekly_written=weekly_written,
        attention=tuple(attention),
        progress=progress,
    )


def build_parser() -> argparse.ArgumentParser:
    """构造明确的 start/report CLI，避免隐式重置 epoch。"""

    parser = argparse.ArgumentParser(description="生成本地 P3 burn-in 证据报告")
    parser.add_argument(
        "--app-support-dir",
        type=Path,
        default=None,
        help="覆盖 Application Support 根目录（测试或迁移使用）",
    )
    parser.add_argument("--state-dir", type=Path, default=None, help="覆盖 burn-in 状态目录")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (subparsers.add_parser("start"), subparsers.add_parser("report")):
        command.add_argument(
            "--app-support-dir",
            type=Path,
            default=argparse.SUPPRESS,
            help="覆盖 Application Support 根目录（测试或迁移使用）",
        )
        command.add_argument(
            "--state-dir",
            type=Path,
            default=argparse.SUPPRESS,
            help="覆盖 burn-in 状态目录",
        )
    report = subparsers.choices["report"]
    report.add_argument("--health-dir", type=Path, default=None, help="覆盖健康 journal 目录")
    report.add_argument("--news-dir", type=Path, default=None, help="覆盖新闻 journal 目录")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口；状态不可用时仅输出稳定码，不尝试修复运行服务。"""

    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            started_at = start_burn_in(
                app_support_dir=args.app_support_dir,
                state_dir=args.state_dir,
            )
            print(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "action": "start",
                        "result": "started",
                        "epoch_started_at": started_at.isoformat(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        result = run_report(
            app_support_dir=args.app_support_dir,
            state_dir=args.state_dir,
            health_dir=args.health_dir,
            news_dir=args.news_dir,
        )
    except BurnInAlreadyStartedError:
        print(
            json.dumps(
                {"schema_version": SCHEMA_VERSION, "action": "start", "result": "already_started"}
            )
        )
        return 1
    except (OSError, ValueError):
        print(
            json.dumps(
                {"schema_version": SCHEMA_VERSION, "action": args.command, "result": "state_failed"}
            )
        )
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
