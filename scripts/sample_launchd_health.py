"""P0-4 launchd 健康只读采样器。

仅采集四个 launchd job、Dashboard loopback listener、相关进程元数据和两个
stderr 文件的 stat 元数据。脚本不保存基线、不读取日志正文，也绝不执行服务启停。

用法：
    uv run python scripts/sample_launchd_health.py --format json
    uv run python scripts/sample_launchd_health.py --format text
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TARGET_LABELS: tuple[str, ...] = (
    "com.myaiemployee.agent",
    "com.myaiemployee.imap-sync",
    "com.myaiemployee.menu-bar",
    "com.myaiemployee.dashboard",
)
REQUIRED_RUNNING_LABELS = frozenset({"com.myaiemployee.menu-bar", "com.myaiemployee.dashboard"})
DEFAULT_PORT = 8765
DEFAULT_LOG_DIR = Path.home() / "Library" / "Logs" / "MyAIEmployee"
COMMAND_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class CommandResult:
    """只保留 probe 所需的安全命令结果，不保存 stderr。"""

    returncode: int
    stdout: str


@dataclass(frozen=True)
class JobState:
    """launchctl list 中一个精确 label 的状态。"""

    registered: bool
    pid: int | None
    last_exit_status: int | None
    required_running: bool


@dataclass(frozen=True)
class ProcessState:
    """采样时指定 PID 的最小、非敏感进程元数据。"""

    ppid: int
    elapsed: str


CommandRunner = Callable[[Sequence[str]], CommandResult]
StatPath = Callable[[Path], os.stat_result]


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def parse_launchctl_list(
    text: str,
    labels: Sequence[str] = TARGET_LABELS,
) -> dict[str, JobState]:
    """按末列精确解析 ``launchctl list``，避免 label 点号的模糊匹配。"""

    states = {
        label: JobState(
            registered=False,
            pid=None,
            last_exit_status=None,
            required_running=label in REQUIRED_RUNNING_LABELS,
        )
        for label in labels
    }
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        label = fields[-1]
        if label not in states:
            continue
        states[label] = JobState(
            registered=True,
            pid=_parse_int(fields[0]),
            last_exit_status=_parse_int(fields[1]),
            required_running=label in REQUIRED_RUNNING_LABELS,
        )
    return states


def parse_lsof_listener_pids(text: str, *, port: int = DEFAULT_PORT) -> tuple[int, ...]:
    """只返回 loopback TCP listener 的 PID；不把非本机监听算作健康。"""

    pids: set[int] = set()
    loopback_endpoints = frozenset((f"127.0.0.1:{port}", f"[::1]:{port}", f"::1:{port}"))
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[-1] != "(LISTEN)":
            continue
        if fields[-2] not in loopback_endpoints:
            continue
        pid = _parse_int(fields[1])
        if pid is not None:
            pids.add(pid)
    return tuple(sorted(pids))


def parse_ps_rows(text: str) -> dict[int, ProcessState]:
    """解析 ``ps -o pid=,ppid=,etime=`` 的最小字段。"""

    states: dict[int, ProcessState] = {}
    for line in text.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) != 3:
            continue
        pid = _parse_int(fields[0])
        ppid = _parse_int(fields[1])
        if pid is None or ppid is None:
            continue
        states[pid] = ProcessState(ppid=ppid, elapsed=fields[2])
    return states


def _subprocess_runner(args: Sequence[str]) -> CommandResult:
    """真实 runner：禁止 shell、限制耗时，且绝不把 stderr 交给输出层。"""

    try:
        result = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=124, stdout="")
    except OSError:
        return CommandResult(returncode=127, stdout="")
    return CommandResult(returncode=result.returncode, stdout=result.stdout)


def _probe(
    *,
    name: str,
    args: Sequence[str],
    run_command: CommandRunner,
    allow_no_match: bool = False,
) -> tuple[str, list[str]]:
    """执行允许的只读命令；失败仅返回稳定错误码，不回显命令输出。"""

    try:
        result = run_command(args)
    except OSError:
        return "", [f"{name}_failed"]
    if result.returncode != 0 and not (allow_no_match and result.returncode == 1):
        return result.stdout, [f"{name}_failed"]
    return result.stdout, []


def _log_metadata(path: Path, *, stat_path: StatPath) -> dict[str, int | None | bool]:
    """只读取 log 的 exists/size/mtime，不读取其路径或正文。"""

    try:
        result = stat_path(path)
    except OSError:
        return {"exists": False, "size_bytes": None, "mtime_epoch": None}
    return {
        "exists": True,
        "size_bytes": int(result.st_size),
        "mtime_epoch": int(result.st_mtime),
    }


def collect_snapshot(
    *,
    run_command: CommandRunner = _subprocess_runner,
    now: datetime | None = None,
    monotonic_ns: int | None = None,
    stat_path: StatPath = Path.stat,
    port: int = DEFAULT_PORT,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> dict[str, Any]:
    """采集一份可 JSON 序列化的无状态快照。

    ``agent`` 与 ``imap-sync`` 是计划型 job，PID 为 ``-`` 仍可健康；menu-bar 和
    dashboard 则必须有 PID。listener PID 可能是 dashboard job 的子进程，不能要求
    两者相等；但在 ``ps`` 成功时，listener 必须归属于该 Dashboard 进程，避免其他
    本机进程占用端口时误报健康。
    """

    captured_at = now or datetime.now(tz=UTC)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    errors: list[str] = []

    launchctl_text, probe_errors = _probe(
        name="launchctl",
        args=("launchctl", "list"),
        run_command=run_command,
    )
    errors.extend(probe_errors)
    job_states = parse_launchctl_list(launchctl_text)

    lsof_text, probe_errors = _probe(
        name="lsof",
        args=("lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"),
        run_command=run_command,
        allow_no_match=True,
    )
    errors.extend(probe_errors)
    listener_pids = parse_lsof_listener_pids(lsof_text, port=port)

    observed_pids = sorted(
        {pid for state in job_states.values() for pid in (state.pid,) if pid is not None}
        | set(listener_pids)
    )
    process_states: dict[int, ProcessState] = {}
    ps_succeeded = False
    if observed_pids:
        ps_text, ps_probe_errors = _probe(
            name="ps",
            args=(
                "ps",
                "-p",
                ",".join(str(pid) for pid in observed_pids),
                "-o",
                "pid=,ppid=,etime=",
            ),
            run_command=run_command,
        )
        errors.extend(ps_probe_errors)
        if not ps_probe_errors:
            process_states = parse_ps_rows(ps_text)
            ps_succeeded = True

    reasons: list[str] = []
    for label, state in job_states.items():
        if not state.registered:
            reasons.append(f"missing_job:{label}")
            continue
        if state.last_exit_status not in (None, 0):
            reasons.append(f"last_exit_nonzero:{label}:{state.last_exit_status}")
        if state.required_running and state.pid is None:
            reasons.append(f"not_running:{label}")
        elif ps_succeeded and state.required_running and state.pid not in process_states:
            reasons.append(f"missing_process:{label}")
    if not listener_pids:
        reasons.append("dashboard_listener_missing")
    elif (
        ps_succeeded and (dashboard_pid := job_states["com.myaiemployee.dashboard"].pid) is not None
    ):
        listener_is_owned = any(
            listener_pid == dashboard_pid
            or (
                (listener_state := process_states.get(listener_pid)) is not None
                and listener_state.ppid == dashboard_pid
            )
            for listener_pid in listener_pids
        )
        if not listener_is_owned:
            reasons.append("dashboard_listener_not_owned")

    jobs = {
        label: {
            "registered": state.registered,
            "pid": state.pid,
            "last_exit_status": state.last_exit_status,
            "required_running": state.required_running,
        }
        for label, state in job_states.items()
    }
    processes = {
        pid: {"ppid": state.ppid, "elapsed": state.elapsed} for pid, state in process_states.items()
    }
    return {
        "schema_version": 1,
        "captured_at": captured_at.isoformat(),
        "monotonic_ns": monotonic_ns if monotonic_ns is not None else time.monotonic_ns(),
        "read_only": True,
        "healthy": not reasons and not errors,
        "reasons": reasons,
        "probe_errors": errors,
        "jobs": jobs,
        "dashboard_listener": {
            "port": port,
            "loopback_listening": bool(listener_pids),
            "pids": listener_pids,
        },
        "processes": processes,
        "error_log_metadata": {
            "menu_bar": _log_metadata(log_dir / "menu-bar.err.log", stat_path=stat_path),
            "dashboard": _log_metadata(log_dir / "dashboard.err.log", stat_path=stat_path),
        },
    }


def render_text(snapshot: dict[str, Any]) -> str:
    """生成一行 grep 友好的无敏感文本摘要。"""

    jobs = snapshot["jobs"]
    menu_pid = jobs["com.myaiemployee.menu-bar"]["pid"]
    dashboard_pid = jobs["com.myaiemployee.dashboard"]["pid"]
    listener = snapshot["dashboard_listener"]
    listener_pids = ",".join(str(pid) for pid in listener["pids"]) or "-"
    reasons = ",".join(snapshot["reasons"] + snapshot["probe_errors"]) or "-"
    return (
        f"{snapshot['captured_at']} healthy={str(snapshot['healthy']).lower()} "
        f"menu_bar=pid:{menu_pid or '-'} dashboard=pid:{dashboard_pid or '-'} "
        f"listener={listener['port']}:{listener_pids} reasons={reasons}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口。健康与否由 JSON 字段表达，采样成功即返回 0。"""

    parser = argparse.ArgumentParser(description="只读采样 MyAIEmployee launchd 健康状态")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)
    snapshot = collect_snapshot()
    if args.format == "json":
        print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
