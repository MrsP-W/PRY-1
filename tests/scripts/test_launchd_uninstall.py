"""standalone launchd 卸载脚本的隔离行为回归。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UNINSTALL_SH = PROJECT_ROOT / "scripts" / "launchd_uninstall.sh"
LABELS = (
    "com.myaiemployee.agent",
    "com.myaiemployee.imap-sync",
    "com.myaiemployee.menu-bar",
    "com.myaiemployee.dashboard",
    "com.myaiemployee.digital-employee",
)
WRAPPER_NAMES = (
    "my-ai-employee-monthly-report",
    "my-ai-employee-imap-sync",
    "my-ai-employee-menu-bar-runner",
    "my-ai-employee-dashboard-runner",
    "my-ai-employee-start",
)


def _write_fake_launchctl(
    fake_bin: Path,
    state_file: Path,
    calls_file: Path,
    *,
    registered_labels: tuple[str, ...] = LABELS,
) -> None:
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'state="${FAKE_LAUNCHCTL_STATE:?}"\n'
        'calls="${FAKE_LAUNCHCTL_CALLS:?}"\n'
        "should_fail() {\n"
        '  local labels="$1"\n'
        '  local label="$2"\n'
        '  [[ ",${labels}," == *",${label},"* ]]\n'
        "}\n"
        "remove_label() {\n"
        '  local label="$1"\n'
        '  awk -v label="${label}" \'$NF != label\' "${state}" > "${state}.next"\n'
        '  mv "${state}.next" "${state}"\n'
        "}\n"
        'case "${1:-}" in\n'
        "  list)\n"
        '    cat "${state}"\n'
        "    ;;\n"
        "  unload)\n"
        '    printf \'%s\\n\' "$*" >> "${calls}"\n'
        '    label="$(basename "${2:?}" .plist)"\n'
        '    if should_fail "${FAKE_LAUNCHCTL_FAIL_UNLOAD_LABELS:-}" "${label}"; then\n'
        "      exit 1\n"
        "    fi\n"
        '    remove_label "${label}"\n'
        "    ;;\n"
        "  bootout)\n"
        '    printf \'%s\\n\' "$*" >> "${calls}"\n'
        '    label="${2##*/}"\n'
        '    if should_fail "${FAKE_LAUNCHCTL_FAIL_BOOTOUT_LABELS:-}" "${label}"; then\n'
        "      exit 1\n"
        "    fi\n"
        '    remove_label "${label}"\n'
        "    ;;\n"
        "  *)\n"
        "    printf 'unexpected launchctl: %s\\n' \"$*\" >&2\n"
        "    exit 1\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_launchctl.chmod(0o755)
    state_file.write_text(
        "\n".join(f"123 0 {label}" for label in registered_labels) + "\n",
        encoding="utf-8",
    )
    calls_file.touch()


def _run_uninstall(
    tmp_path: Path,
    *,
    purge_bin: bool,
    managed_state: bool = True,
    fail_unload_labels: tuple[str, ...] = (),
    fail_bootout_labels: tuple[str, ...] = (),
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    home = tmp_path / "home"
    launch_agents = home / "Library" / "LaunchAgents"
    home_bin = home / "bin"
    fake_bin = tmp_path / "fake-bin"
    launch_agents.mkdir(parents=True)
    home_bin.mkdir()
    fake_bin.mkdir()
    state_file = tmp_path / "launchctl-state"
    calls_file = tmp_path / "launchctl-calls"
    _write_fake_launchctl(
        fake_bin,
        state_file,
        calls_file,
        registered_labels=LABELS if managed_state else (),
    )

    if managed_state:
        # agent plist 缺失：旧脚本会在此提前退出，留下其余 4 个 job。
        for label in LABELS[1:]:
            (launch_agents / f"{label}.plist").write_text("<plist/>", encoding="utf-8")
    for name in WRAPPER_NAMES:
        (home_bin / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_LAUNCHCTL_STATE": str(state_file),
            "FAKE_LAUNCHCTL_CALLS": str(calls_file),
            "FAKE_LAUNCHCTL_FAIL_UNLOAD_LABELS": ",".join(fail_unload_labels),
            "FAKE_LAUNCHCTL_FAIL_BOOTOUT_LABELS": ",".join(fail_bootout_labels),
        }
    )
    args = ["bash", str(UNINSTALL_SH)]
    if purge_bin:
        args.append("--purge-bin")
    result = subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    return result, home, calls_file


def test_standalone_uninstall_retires_all_jobs_when_agent_plist_is_missing(tmp_path: Path) -> None:
    """agent plist 缺失时也要精确退役四个当前 job 和 legacy job。"""
    result, home, calls_file = _run_uninstall(tmp_path, purge_bin=True)

    assert result.returncode == 0, result.stderr
    launch_agents = home / "Library" / "LaunchAgents"
    assert not any((launch_agents / f"{label}.plist").exists() for label in LABELS)
    assert not any((home / "bin" / name).exists() for name in WRAPPER_NAMES)
    calls = calls_file.read_text(encoding="utf-8")
    assert "bootout gui/" in calls
    for label in LABELS:
        assert label in calls


def test_standalone_uninstall_preserves_wrappers_without_purge_and_on_retirement_failure(
    tmp_path: Path,
) -> None:
    """无 purge 或双重退役失败均不得删除用户的可恢复文件。"""
    result, home, _ = _run_uninstall(tmp_path, purge_bin=False)

    assert result.returncode == 0, result.stderr
    assert all((home / "bin" / name).exists() for name in WRAPPER_NAMES)

    failed_label = "com.myaiemployee.imap-sync"
    failure_result, failure_home, calls_file = _run_uninstall(
        tmp_path / "double-failure",
        purge_bin=False,
        fail_unload_labels=(failed_label,),
        fail_bootout_labels=(failed_label,),
    )

    assert failure_result.returncode == 3
    assert f"无法退役 {failed_label}" in failure_result.stderr
    assert (failure_home / "Library" / "LaunchAgents" / f"{failed_label}.plist").exists()
    assert all((failure_home / "bin" / name).exists() for name in WRAPPER_NAMES)
    calls = calls_file.read_text(encoding="utf-8")
    assert f"unload {failure_home}/Library/LaunchAgents/{failed_label}.plist" in calls
    assert "bootout gui/" in calls
    assert failed_label in calls


def test_standalone_uninstall_purges_wrappers_when_already_uninstalled(tmp_path: Path) -> None:
    """显式 --purge-bin 不应被“已卸载”的早退路径跳过。"""
    result, home, calls_file = _run_uninstall(tmp_path, purge_bin=True, managed_state=False)

    assert result.returncode == 1, result.stderr
    assert "已卸载" in result.stdout
    assert not any((home / "bin" / name).exists() for name in WRAPPER_NAMES)
    assert calls_file.read_text(encoding="utf-8") == ""
