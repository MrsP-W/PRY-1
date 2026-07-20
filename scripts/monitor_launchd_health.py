"""P1 每 15 分钟 launchd 健康巡检。

本脚本只复用 P0 的只读快照，并请求固定的 loopback ``/health`` 契约。
一次采样失败时只重试一次；连续三轮最终失败才写本地结构化告警。
它不读取日志正文、不接触业务数据，也不执行任何服务启停动作。

用法：
    uv run python scripts/monitor_launchd_health.py
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Any, Protocol

# launchd wrapper 以绝对路径执行本脚本时，Python 默认只把 scripts/ 放入 sys.path。
# 补入项目根后统一按包导入，避免相对 CWD 造成 #96 类路径漂移。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import sample_launchd_health as health_sample

DEFAULT_PORT = health_sample.DEFAULT_PORT
TARGET_LABELS = health_sample.TARGET_LABELS
collect_snapshot = health_sample.collect_snapshot

STATE_SCHEMA_VERSION = 1
HEALTH_PATH = "/health"
HEALTH_TIMEOUT_SECONDS = 2.0
MAX_HEALTH_BODY_BYTES = 4096
RETRY_DELAY_SECONDS = 5.0
ALERT_AFTER_CONSECUTIVE_FAILURES = 3
DEFAULT_STATE_DIR = Path.home() / "Library" / "Application Support" / "MyAIEmployee" / "health"


class MonitorLockBusyError(RuntimeError):
    """已有巡检实例在运行；本轮应安静跳过。"""


class HealthResponse(Protocol):
    """本机 HTTP 健康响应所需的最小协议。"""

    status: int

    def read(self, amt: int | None = None) -> bytes: ...


class HealthConnection(Protocol):
    """固定 loopback 连接所需的最小协议。"""

    def request(self, method: str, url: str) -> None: ...

    def getresponse(self) -> HealthResponse: ...

    def close(self) -> None: ...


HealthConnectionFactory = Callable[[str, int, float], HealthConnection]
SnapshotCollector = Callable[[], dict[str, Any]]
HealthProbe = Callable[[], tuple[bool, str | None]]
SleepFn = Callable[[float], None]
NowFn = Callable[[], datetime]


@dataclass(frozen=True)
class MonitorState:
    """跨轮最小状态；不保存日志正文、环境变量或业务数据。"""

    failure_streak: int = 0
    alert_open: bool = False


@dataclass(frozen=True)
class MonitorRunResult:
    """一轮巡检的脱敏执行结果。"""

    skipped: bool
    healthy: bool | None
    attempts: int
    failure_streak: int | None
    alert_event: str | None

    def to_dict(self) -> dict[str, bool | int | str | None]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "read_only": True,
            "skipped": self.skipped,
            "healthy": self.healthy,
            "attempts": self.attempts,
            "failure_streak": self.failure_streak,
            "alert_event": self.alert_event,
        }


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _default_connection_factory(host: str, port: int, timeout: float) -> HTTPConnection:
    """固定建连到由调用者提供的 loopback host/port。"""

    return HTTPConnection(host, port=port, timeout=timeout)


def probe_dashboard_health(
    *,
    connection_factory: HealthConnectionFactory = _default_connection_factory,
) -> tuple[bool, str | None]:
    """只对 ``127.0.0.1:8765/health`` 做无重定向、无代理的轻量 GET。"""

    connection: HealthConnection | None = None
    try:
        connection = connection_factory("127.0.0.1", DEFAULT_PORT, HEALTH_TIMEOUT_SECONDS)
        connection.request("GET", HEALTH_PATH)
        response = connection.getresponse()
        if response.status != 200:
            return False, "dashboard_health_http_status"
        body = response.read(MAX_HEALTH_BODY_BYTES + 1)
    except (HTTPException, OSError, TimeoutError):
        return False, "dashboard_health_unavailable"
    finally:
        if connection is not None:
            connection.close()

    if len(body) > MAX_HEALTH_BODY_BYTES:
        return False, "dashboard_health_invalid"
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "dashboard_health_invalid"
    if not isinstance(payload, dict):
        return False, "dashboard_health_invalid"
    if payload.get("ok") is not True or payload.get("read_only") is not True:
        return False, "dashboard_health_contract_invalid"
    return True, None


def _safe_reason_codes(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _safe_pid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _safe_log_metadata(value: object) -> dict[str, dict[str, bool | int | None]]:
    """保留 stderr 的 stat 元数据，不保留路径或任何日志正文。"""

    source = value if isinstance(value, dict) else {}
    metadata: dict[str, dict[str, bool | int | None]] = {}
    for name in ("menu_bar", "dashboard"):
        raw_entry = source.get(name)
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        size_bytes = entry.get("size_bytes")
        mtime_epoch = entry.get("mtime_epoch")
        metadata[name] = {
            "exists": entry.get("exists") is True,
            "size_bytes": (
                size_bytes
                if isinstance(size_bytes, int)
                and not isinstance(size_bytes, bool)
                and size_bytes >= 0
                else None
            ),
            "mtime_epoch": (
                mtime_epoch
                if isinstance(mtime_epoch, int)
                and not isinstance(mtime_epoch, bool)
                and mtime_epoch >= 0
                else None
            ),
        }
    return metadata


def _unique_reasons(reasons: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(reasons))


def sanitise_snapshot(
    snapshot: dict[str, Any],
    *,
    endpoint_healthy: bool,
    endpoint_reason: str | None,
    observed_at: datetime,
) -> dict[str, Any]:
    """只保留 P1/P3 决策需要的脱敏健康状态与 stderr stat 元数据。"""

    captured_at = snapshot.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at:
        captured_at = observed_at.isoformat()

    reasons = _safe_reason_codes(snapshot.get("reasons"))
    reasons.extend(_safe_reason_codes(snapshot.get("probe_errors")))
    if snapshot.get("healthy") is not True and not reasons:
        reasons.append("launchd_health_unhealthy")
    if endpoint_reason is not None:
        reasons.append(endpoint_reason)

    raw_jobs = snapshot.get("jobs")
    jobs_source = raw_jobs if isinstance(raw_jobs, dict) else {}
    jobs: dict[str, dict[str, bool | int | None]] = {}
    for label in TARGET_LABELS:
        raw_job = jobs_source.get(label)
        job = raw_job if isinstance(raw_job, dict) else {}
        jobs[label] = {
            "registered": job.get("registered") is True,
            "pid": _safe_pid(job.get("pid")),
            "required_running": job.get("required_running") is True,
        }

    raw_listener = snapshot.get("dashboard_listener")
    listener = raw_listener if isinstance(raw_listener, dict) else {}
    raw_listener_pids = listener.get("pids")
    listener_pids = (
        [_safe_pid(pid) for pid in raw_listener_pids]
        if isinstance(raw_listener_pids, (list, tuple))
        else []
    )
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "captured_at": captured_at,
        "healthy": snapshot.get("healthy") is True and endpoint_healthy,
        "reasons": _unique_reasons(reasons),
        "jobs": jobs,
        "dashboard_listener": {
            "port": DEFAULT_PORT,
            "loopback_listening": listener.get("loopback_listening") is True,
            "pids": [pid for pid in listener_pids if pid is not None],
        },
        "dashboard_health": {"ok": endpoint_healthy, "read_only": endpoint_healthy},
        "error_log_metadata": _safe_log_metadata(snapshot.get("error_log_metadata")),
    }


def collect_observation(
    *,
    collect_snapshot_fn: SnapshotCollector = collect_snapshot,
    health_probe: HealthProbe = probe_dashboard_health,
    now_fn: NowFn = _now_utc,
) -> dict[str, Any]:
    """采样 P0 快照并校验本机 Dashboard 的只读健康契约。"""

    snapshot = collect_snapshot_fn()
    endpoint_healthy, endpoint_reason = health_probe()
    return sanitise_snapshot(
        snapshot,
        endpoint_healthy=endpoint_healthy,
        endpoint_reason=endpoint_reason,
        observed_at=now_fn(),
    )


def ensure_state_directory(state_dir: Path) -> None:
    """创建私有本地状态目录。"""

    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_dir.chmod(0o700)


@contextmanager
def acquire_monitor_lock(*, state_dir: Path) -> Iterator[None]:
    """以非阻塞锁避免 launchd 与手工运行重叠。"""

    lock_path = state_dir / "monitor.lock"
    lock_file = lock_path.open("a+", encoding="utf-8")
    os.chmod(lock_path, 0o600)
    try:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            raise MonitorLockBusyError("health monitor already running") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def load_state(path: Path) -> MonitorState:
    """损坏或过期状态一律按空状态恢复，避免巡检本身中断。"""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return MonitorState()
    if not isinstance(raw, dict) or raw.get("schema_version") != STATE_SCHEMA_VERSION:
        return MonitorState()
    failure_streak = raw.get("failure_streak")
    if (
        isinstance(failure_streak, bool)
        or not isinstance(failure_streak, int)
        or failure_streak < 0
    ):
        return MonitorState()
    return MonitorState(failure_streak=failure_streak, alert_open=raw.get("alert_open") is True)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """原子替换状态文件，且限制为当前用户可读写。"""

    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """追加一条脱敏 JSONL 记录；锁已由调用方持有。"""

    with path.open("a", encoding="utf-8") as output:
        os.chmod(path, 0o600)
        output.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def _state_payload(
    *, state: MonitorState, observed_at: datetime, observation: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "updated_at": observed_at.isoformat(),
        "failure_streak": state.failure_streak,
        "alert_open": state.alert_open,
        "last_sample": observation,
    }


def _alert_payload(
    *, event: str, observed_at: datetime, failure_streak: int, observation: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "event": event,
        "at": observed_at.isoformat(),
        "failure_streak": failure_streak,
        "reasons": observation["reasons"],
    }


def run_monitor(
    *,
    state_dir: Path = DEFAULT_STATE_DIR,
    collect_snapshot_fn: SnapshotCollector = collect_snapshot,
    health_probe: HealthProbe = probe_dashboard_health,
    sleep_fn: SleepFn = time.sleep,
    now_fn: NowFn = _now_utc,
) -> MonitorRunResult:
    """执行一轮 P1 巡检；不健康只重试一次采样，绝不改变业务服务运行态。"""

    ensure_state_directory(state_dir)
    try:
        with acquire_monitor_lock(state_dir=state_dir):
            state_path = state_dir / "state.json"
            samples_path = state_dir / "samples.jsonl"
            alerts_path = state_dir / "alerts.jsonl"
            previous_state = load_state(state_path)
            observed_at = now_fn()
            first = collect_observation(
                collect_snapshot_fn=collect_snapshot_fn,
                health_probe=health_probe,
                now_fn=now_fn,
            )
            observation = first
            attempts = 1
            recovered_by_retry = False
            if first["healthy"] is not True:
                sleep_fn(RETRY_DELAY_SECONDS)
                observation = collect_observation(
                    collect_snapshot_fn=collect_snapshot_fn,
                    health_probe=health_probe,
                    now_fn=now_fn,
                )
                attempts = 2
                recovered_by_retry = observation["healthy"] is True

            healthy = observation["healthy"] is True
            alert_event: str | None = None
            if healthy:
                next_state = MonitorState()
                if previous_state.alert_open:
                    alert_event = "resolved"
                    append_jsonl(
                        alerts_path,
                        _alert_payload(
                            event=alert_event,
                            observed_at=observed_at,
                            failure_streak=previous_state.failure_streak,
                            observation=observation,
                        ),
                    )
            else:
                failure_streak = previous_state.failure_streak + 1
                alert_open = previous_state.alert_open
                if not alert_open and failure_streak >= ALERT_AFTER_CONSECUTIVE_FAILURES:
                    alert_event = "opened"
                    alert_open = True
                    append_jsonl(
                        alerts_path,
                        _alert_payload(
                            event=alert_event,
                            observed_at=observed_at,
                            failure_streak=failure_streak,
                            observation=observation,
                        ),
                    )
                next_state = MonitorState(failure_streak=failure_streak, alert_open=alert_open)

            append_jsonl(
                samples_path,
                {
                    "schema_version": STATE_SCHEMA_VERSION,
                    "at": observed_at.isoformat(),
                    "attempts": attempts,
                    "recovered_by_retry": recovered_by_retry,
                    "sample": observation,
                },
            )
            write_json_atomic(
                state_path,
                _state_payload(state=next_state, observed_at=observed_at, observation=observation),
            )
            return MonitorRunResult(
                skipped=False,
                healthy=healthy,
                attempts=attempts,
                failure_streak=next_state.failure_streak,
                alert_event=alert_event,
            )
    except MonitorLockBusyError:
        return MonitorRunResult(
            skipped=True,
            healthy=None,
            attempts=0,
            failure_streak=None,
            alert_event=None,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口；健康与否由 JSON 表达，巡检故障不触发 launchd 热循环。"""

    parser = argparse.ArgumentParser(description="每 15 分钟只读采样 MyAIEmployee launchd 健康")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    args = parser.parse_args(argv)
    try:
        result = run_monitor(state_dir=args.state_dir)
    except (OSError, ValueError):
        print(json.dumps({"schema_version": STATE_SCHEMA_VERSION, "error": "monitor_state_failed"}))
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
