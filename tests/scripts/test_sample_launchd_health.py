"""P0-4 launchd 健康采样器的纯注入测试。"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import sample_launchd_health as health

NOW = datetime(2026, 7, 11, 7, 30, tzinfo=UTC)
LAUNCHCTL_HEALTHY = """\
PID\tStatus\tLabel
-\t0\tcom.myaiemployee.agent
-\t0\tcom.myaiemployee.imap-sync
20196\t0\tcom.myaiemployee.menu-bar
11406\t0\tcom.myaiemployee.dashboard
"""
LSOF_HEALTHY = """\
COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
Python  11411  wei    3u  IPv4 0x1      0t0  TCP 127.0.0.1:8765 (LISTEN)
"""
PS_HEALTHY = """\
20196 1 00:07:00
11406 1 00:07:00
11411 11406 00:07:00
"""
DEFAULT_LAUNCHCTL = health.CommandResult(0, LAUNCHCTL_HEALTHY)
DEFAULT_LSOF = health.CommandResult(0, LSOF_HEALTHY)
DEFAULT_PS = health.CommandResult(0, PS_HEALTHY)


def _runner(
    results: dict[tuple[str, ...], health.CommandResult | OSError],
    calls: list[tuple[str, ...]],
    *,
    ps: health.CommandResult = DEFAULT_PS,
) -> Callable[[Sequence[str]], health.CommandResult]:
    def run(args: Sequence[str]) -> health.CommandResult:
        key = tuple(args)
        calls.append(key)
        if key[:2] == ("ps", "-p"):
            return ps
        result = results[key]
        if isinstance(result, OSError):
            raise result
        return result

    return run


def _stat_path(path: Path) -> SimpleNamespace:
    if path.name == "menu-bar.err.log":
        return SimpleNamespace(st_size=12, st_mtime=1_783_727_000.0)
    if path.name == "dashboard.err.log":
        return SimpleNamespace(st_size=24, st_mtime=1_783_727_001.0)
    raise FileNotFoundError(path)


def _snapshot(
    *,
    launchctl: health.CommandResult = DEFAULT_LAUNCHCTL,
    lsof: health.CommandResult = DEFAULT_LSOF,
    ps: health.CommandResult = DEFAULT_PS,
) -> tuple[dict[str, object], list[tuple[str, ...]]]:
    calls: list[tuple[str, ...]] = []
    results: dict[tuple[str, ...], health.CommandResult | OSError] = {
        ("launchctl", "list"): launchctl,
        ("lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN"): lsof,
        ("ps", "-p", "11406,11411,20196", "-o", "pid=,ppid=,etime="): health.CommandResult(
            0, PS_HEALTHY
        ),
    }
    snapshot = health.collect_snapshot(
        run_command=_runner(results, calls, ps=ps),
        now=NOW,
        monotonic_ns=42,
        stat_path=_stat_path,  # type: ignore[arg-type]
        log_dir=Path("/safe/logs"),
    )
    return snapshot, calls


def test_collect_healthy_snapshot_uses_only_readonly_command_allowlist() -> None:
    snapshot, calls = _snapshot()

    assert snapshot["healthy"] is True
    assert snapshot["read_only"] is True
    assert snapshot["dashboard_listener"] == {
        "port": 8765,
        "loopback_listening": True,
        "pids": (11411,),
    }
    assert snapshot["processes"] == {
        20196: {"ppid": 1, "elapsed": "00:07:00"},
        11406: {"ppid": 1, "elapsed": "00:07:00"},
        11411: {"ppid": 11406, "elapsed": "00:07:00"},
    }
    assert calls == [
        ("launchctl", "list"),
        ("lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN"),
        ("ps", "-p", "11406,11411,20196", "-o", "pid=,ppid=,etime="),
    ]
    assert "healthy=true" in health.render_text(snapshot)
    assert json.loads(json.dumps(snapshot, ensure_ascii=False))["read_only"] is True


def test_scheduled_jobs_with_idle_pid_remain_healthy_and_labels_are_exact() -> None:
    snapshot, _ = _snapshot()
    jobs = snapshot["jobs"]

    assert jobs["com.myaiemployee.agent"]["registered"] is True  # type: ignore[index]
    assert jobs["com.myaiemployee.agent"]["pid"] is None  # type: ignore[index]
    assert jobs["com.myaiemployee.imap-sync"]["pid"] is None  # type: ignore[index]
    parsed = health.parse_launchctl_list(
        "20196 0 comXmyaiemployeeXmenu-bar\n20196 0 com.myaiemployee.menu-bar\n"
    )
    assert parsed["com.myaiemployee.menu-bar"].registered is True
    assert parsed["com.myaiemployee.dashboard"].registered is False


def test_registered_job_with_nonzero_last_exit_is_unhealthy() -> None:
    """计划型 job 即使空闲，也不能掩盖最近一次失败退出。"""
    failed_imap_sync = LAUNCHCTL_HEALTHY.replace(
        "-\t0\tcom.myaiemployee.imap-sync", "-\t2\tcom.myaiemployee.imap-sync"
    )

    snapshot, _ = _snapshot(launchctl=health.CommandResult(0, failed_imap_sync))

    assert snapshot["healthy"] is False
    assert snapshot["reasons"] == ["last_exit_nonzero:com.myaiemployee.imap-sync:2"]
    assert snapshot["probe_errors"] == []


def test_parse_lsof_listener_pids_requires_exact_loopback_endpoint_port() -> None:
    listeners = """\
COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
Python  11411  wei    3u  IPv4 0x1      0t0  TCP 127.0.0.1:8765 (LISTEN)
Python  11412  wei    3u  IPv4 0x1      0t0  TCP 127.0.0.1:87650 (LISTEN)
Python  11413  wei    3u  IPv6 0x1      0t0  TCP [::1]:87650 (LISTEN)
Python  11414  wei    3u  IPv4 0x1      0t0  TCP 0.0.0.0:8765 (LISTEN)
Python  11415  wei    3u  IPv6 0x1      0t0  TCP [::1]:8765 (LISTEN)
"""

    assert health.parse_lsof_listener_pids(listeners) == (11411, 11415)


def test_missing_dashboard_job_or_listener_has_stable_unhealthy_reason() -> None:
    missing_dashboard = LAUNCHCTL_HEALTHY.replace(
        "11406\t0\tcom.myaiemployee.dashboard", "-\t0\tcom.myaiemployee.dashboard"
    )
    snapshot, _ = _snapshot(launchctl=health.CommandResult(0, missing_dashboard))
    assert snapshot["healthy"] is False
    assert snapshot["reasons"] == ["not_running:com.myaiemployee.dashboard"]

    no_listener, _ = _snapshot(lsof=health.CommandResult(1, ""))
    assert no_listener["healthy"] is False
    assert no_listener["reasons"] == ["dashboard_listener_missing"]
    assert no_listener["probe_errors"] == []


def test_listener_not_owned_by_dashboard_is_unhealthy() -> None:
    """其他本机进程占用端口时，不能把 Dashboard 误报为健康。"""
    ps_with_unrelated_listener = PS_HEALTHY.replace("11411 11406", "11411 1")

    snapshot, _ = _snapshot(ps=health.CommandResult(0, ps_with_unrelated_listener))

    assert snapshot["healthy"] is False
    assert snapshot["reasons"] == ["dashboard_listener_not_owned"]
    assert snapshot["probe_errors"] == []


def test_required_running_job_missing_from_ps_is_unhealthy() -> None:
    """launchctl PID 在采样间隙退出时，不能因 listener 仍在而误报健康。"""
    ps_without_dashboard = """\
20196 1 00:07:00
11411 11406 00:07:00
"""
    snapshot, _ = _snapshot(ps=health.CommandResult(0, ps_without_dashboard))

    assert snapshot["healthy"] is False
    assert snapshot["reasons"] == ["missing_process:com.myaiemployee.dashboard"]
    assert snapshot["probe_errors"] == []


def test_probe_failures_are_serializable_without_stderr_leakage() -> None:
    calls: list[tuple[str, ...]] = []
    results: dict[tuple[str, ...], health.CommandResult | OSError] = {
        ("launchctl", "list"): OSError("secret launchctl stderr"),
        ("lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN"): health.CommandResult(
            2, "private lsof stdout"
        ),
    }
    snapshot = health.collect_snapshot(
        run_command=_runner(results, calls),
        now=NOW,
        monotonic_ns=42,
        stat_path=_stat_path,  # type: ignore[arg-type]
        log_dir=Path("/safe/logs"),
    )
    rendered = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["healthy"] is False
    assert snapshot["probe_errors"] == ["launchctl_failed", "lsof_failed"]
    assert "secret launchctl stderr" not in rendered
    assert "private lsof stdout" not in rendered
    assert calls == [
        ("launchctl", "list"),
        ("lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN"),
    ]


def test_subprocess_runner_timeout_is_stable_and_redacted() -> None:
    """单个只读 probe 卡住时，不能阻塞 10 分钟采样循环或泄漏 stderr。"""
    timeout = subprocess.TimeoutExpired(
        cmd=["launchctl", "list"],
        timeout=health.COMMAND_TIMEOUT_SECONDS,
        output="private stdout",
        stderr="secret stderr",
    )

    with patch("scripts.sample_launchd_health.subprocess.run", side_effect=timeout) as run:
        result = health._subprocess_runner(("launchctl", "list"))

    assert result == health.CommandResult(returncode=124, stdout="")
    assert run.call_args.kwargs["timeout"] == health.COMMAND_TIMEOUT_SECONDS
    assert "secret stderr" not in result.stdout
