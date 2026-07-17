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


def _write_fake_launchctl(fake_bin: Path, state_file: Path, calls_file: Path) -> None:
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'state="${FAKE_LAUNCHCTL_STATE:?}"\n'
        'calls="${FAKE_LAUNCHCTL_CALLS:?}"\n'
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
        '    remove_label "$(basename "${2:?}" .plist)"\n'
        "    ;;\n"
        "  bootout)\n"
        '    printf \'%s\\n\' "$*" >> "${calls}"\n'
        '    remove_label "${2##*/}"\n'
        "    ;;\n"
        "  *)\n"
        "    printf 'unexpected launchctl: %s\\n' \"$*\" >&2\n"
        "    exit 1\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_launchctl.chmod(0o755)
    state_file.write_text("\n".join(f"123 0 {label}" for label in LABELS) + "\n", encoding="utf-8")
    calls_file.touch()


def _run_uninstall(
    tmp_path: Path, *, purge_bin: bool
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
    _write_fake_launchctl(fake_bin, state_file, calls_file)

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


def test_standalone_uninstall_preserves_all_wrappers_without_purge_bin(tmp_path: Path) -> None:
    """兼容旧契约：不带 --purge-bin 时仅退役 job，不删除用户的 wrapper。"""
    result, home, _ = _run_uninstall(tmp_path, purge_bin=False)

    assert result.returncode == 0, result.stderr
    assert all((home / "bin" / name).exists() for name in WRAPPER_NAMES)
