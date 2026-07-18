"""quality_snapshot 单一事实源 + Dashboard/菜单栏 消费一致性."""

from __future__ import annotations

import errno
import fcntl
import os
import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.responses import build_status_payload
from my_ai_employee.quality_snapshot import (
    DEFAULT_QUALITY_GATES,
    QualityGateSnapshot,
    format_system_health_body,
)
from scripts.check_quality_snapshot import (
    SnapshotLockBusyError,
    acquire_snapshot_lock,
    check_snapshot,
    count_baseline_guardian_failures,
    count_collected_tests,
    count_live_pytest_outcomes,
    count_tracked_md_files,
    parse_lint_file_count,
    parse_pytest_counts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_tracked_md_count_matches_snapshot_lint() -> None:
    """quality_snapshot.lint 必须等于 git ls-files '*.md' 计数."""
    claimed = parse_lint_file_count(DEFAULT_QUALITY_GATES.lint)
    tracked = count_tracked_md_files(PROJECT_ROOT)
    assert tracked == claimed


# 撞坑 #50 Day 10:稳态 collected == passed+skipped;仅 guardian 自身 fail 时放宽,
# 且差值必须等于 count_baseline_guardian_failures() 实测值(不用固定上限).


def test_collected_test_count_matches_snapshot_pytest() -> None:
    """pytest 收集数与 snapshot 严格对齐(仅 guardian fail 时按实测放宽)."""
    passed, skipped = parse_pytest_counts(DEFAULT_QUALITY_GATES.pytest)
    collected = count_collected_tests(PROJECT_ROOT)
    guardian_failures = count_baseline_guardian_failures(root=PROJECT_ROOT)
    expected = passed + skipped + guardian_failures
    assert collected >= passed + skipped, (
        f"collected ({collected}) < passed+skipped ({passed + skipped})"
    )
    assert collected == expected, (
        f"collected ({collected}) != passed+skipped+guardian_failures "
        f"({passed}+{skipped}+{guardian_failures}={expected})"
    )


def test_guardian_failure_probe_does_not_spawn_inside_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两种 pytest/guardian 标记均不得递归启动子 pytest。"""
    for env_name, value in (
        ("PYTEST_CURRENT_TEST", "test_quality_snapshot.py::guardian (call)"),
        ("MY_AI_EMPLOYEE_SNAPSHOT_GUARDIAN_PROBE", "1"),
    ):
        with monkeypatch.context() as scoped_monkeypatch:
            scoped_monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
            scoped_monkeypatch.delenv("MY_AI_EMPLOYEE_SNAPSHOT_GUARDIAN_PROBE", raising=False)
            scoped_monkeypatch.setenv(env_name, value)
            with patch("scripts.check_quality_snapshot.subprocess.run") as run:
                assert count_baseline_guardian_failures(root=PROJECT_ROOT) == 0
            run.assert_not_called()


def test_dashboard_api_status_quality_gates_match_default() -> None:
    """GET /api/status quality_gates 与 DEFAULT_QUALITY_GATES 同源."""
    payload = build_status_payload(DashboardContext.default())
    qg = payload["quality_gates"]
    assert qg["pytest"] == DEFAULT_QUALITY_GATES.pytest
    assert qg["coverage"] == DEFAULT_QUALITY_GATES.coverage
    assert qg["mypy"] == DEFAULT_QUALITY_GATES.mypy
    assert qg["lint"] == DEFAULT_QUALITY_GATES.lint


def test_menu_bar_system_health_body_matches_default() -> None:
    """菜单栏系统健康正文与 DEFAULT_QUALITY_GATES 同源."""
    body = format_system_health_body(git_head="abc1234")
    assert DEFAULT_QUALITY_GATES.pytest in body
    assert DEFAULT_QUALITY_GATES.coverage in body
    assert DEFAULT_QUALITY_GATES.mypy in body
    assert DEFAULT_QUALITY_GATES.lint in body


def test_check_snapshot_rejects_underreported_passed_count() -> None:
    """snapshot 少记测试时必须拒绝，且不依赖当前工作树基线。"""
    with (
        patch(
            "scripts.check_quality_snapshot.DEFAULT_QUALITY_GATES",
            QualityGateSnapshot(
                pytest="9 passed / 1 skipped",
                coverage=DEFAULT_QUALITY_GATES.coverage,
                mypy=DEFAULT_QUALITY_GATES.mypy,
                mypy_files=DEFAULT_QUALITY_GATES.mypy_files,
                lint="1 files 0 errors",
            ),
        ),
        patch("scripts.check_quality_snapshot.count_tracked_md_files", return_value=1),
        patch("scripts.check_quality_snapshot.count_collected_tests", return_value=11),
        patch(
            "scripts.check_quality_snapshot.count_baseline_guardian_failures",
            return_value=0,
        ),
        patch(
            "scripts.check_quality_snapshot.count_baseline_guardian_tests",
            return_value=1,
        ),
        patch("scripts.check_quality_snapshot.count_live_pytest_outcomes", return_value=None),
    ):
        errors = check_snapshot(root=PROJECT_ROOT)
    assert errors == [
        "pytest drift: quality_snapshot claims 9 passed / 1 skipped, "
        "pytest --collect-only has 11, expected 10 "
        "(passed+skipped=10 + baseline guardian failures=0)"
    ]


def test_check_quality_snapshot_script_exits_zero(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CLI 成功、失败与单实例锁均在进程内校验，避免 pytest 子进程嵌套。"""
    from scripts import check_quality_snapshot as snapshot_script

    with patch.object(snapshot_script, "acquire_snapshot_lock", return_value=nullcontext()):
        with (
            patch.object(snapshot_script, "check_snapshot", return_value=[]),
            patch.object(snapshot_script, "count_tracked_md_files", return_value=291),
            patch.object(snapshot_script, "parse_pytest_counts", return_value=(2953, 1)),
            patch("scripts.check_state_entries.check_state_entries", return_value=[]),
        ):
            assert snapshot_script.main() == 0
        assert "state entry docs match quality_snapshot" in capsys.readouterr().out

        with patch.object(snapshot_script, "check_snapshot", return_value=["pytest drift"]):
            assert snapshot_script.main() == 1
        assert "ERROR: pytest drift" in capsys.readouterr().err

        with patch.object(
            snapshot_script,
            "check_snapshot",
            side_effect=RuntimeError("pytest output unavailable"),
        ):
            assert snapshot_script.main() == 1
        assert "ERROR: quality snapshot check failed: pytest output unavailable" in (
            capsys.readouterr().err
        )

        with patch.object(
            snapshot_script,
            "check_snapshot",
            side_effect=subprocess.CalledProcessError(1, ["uv", "run", "pytest"]),
        ):
            assert snapshot_script.main() == 1
        assert "ERROR: quality snapshot check failed:" in capsys.readouterr().err

        with patch.object(
            snapshot_script,
            "check_snapshot",
            side_effect=ValueError("quality_snapshot pytest format invalid"),
        ):
            assert snapshot_script.main() == 1
        assert "ERROR: quality snapshot check failed: quality_snapshot pytest format invalid" in (
            capsys.readouterr().err
        )

    operations: list[int] = []

    def record_flock(_fd: int, operation: int) -> None:
        operations.append(operation)

    monkeypatch.setattr(fcntl, "flock", record_flock)

    with acquire_snapshot_lock(root=tmp_path):
        pass

    assert operations == [
        fcntl.LOCK_EX | fcntl.LOCK_NB,
        fcntl.LOCK_UN,
    ]

    def raise_busy_lock(_fd: int, _operation: int) -> None:
        raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")

    monkeypatch.setattr(fcntl, "flock", raise_busy_lock)

    with (
        pytest.raises(SnapshotLockBusyError, match="already running"),
        acquire_snapshot_lock(root=tmp_path),
    ):
        pass

    with (
        patch.object(
            snapshot_script,
            "acquire_snapshot_lock",
            side_effect=SnapshotLockBusyError("check-snapshot already running"),
        ),
        patch.object(snapshot_script, "check_snapshot") as check,
    ):
        assert snapshot_script.main() == os.EX_TEMPFAIL

    check.assert_not_called()
    assert "ERROR: check-snapshot already running" in capsys.readouterr().err


def test_live_pytest_outcomes_match_snapshot_when_mocked() -> None:
    """补强:实跑 passed/skipped 分布须与 snapshot 一致."""
    from unittest.mock import patch

    from scripts.check_quality_snapshot import check_snapshot

    passed, skipped = parse_pytest_counts(DEFAULT_QUALITY_GATES.pytest)
    with (
        patch(
            "scripts.check_quality_snapshot.DEFAULT_QUALITY_GATES",
            QualityGateSnapshot(
                pytest=f"{passed - 3} passed / {skipped + 1} skipped",
                coverage=DEFAULT_QUALITY_GATES.coverage,
                mypy=DEFAULT_QUALITY_GATES.mypy,
                mypy_files=DEFAULT_QUALITY_GATES.mypy_files,
                lint=DEFAULT_QUALITY_GATES.lint,
            ),
        ),
        patch(
            "scripts.check_quality_snapshot.count_live_pytest_outcomes",
            return_value=(passed, 0, skipped),
        ),
    ):
        errors = check_snapshot(root=PROJECT_ROOT)
    assert any("outcome drift" in err for err in errors)

    captured_env: dict[str, str] = {}

    def run_with_captured_env(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raw_env = kwargs.get("env")
        assert isinstance(raw_env, dict)
        captured_env.update({str(key): str(value) for key, value in raw_env.items()})
        return subprocess.CompletedProcess(
            args=["uv", "run", "pytest"],
            returncode=0,
            stdout=f"{passed} passed / {skipped} skipped",
            stderr="",
        )

    with (
        patch.dict(
            os.environ,
            {
                "MYAI_EMPLOYEE_SNAPSHOT_SKIP_LIVE_PYTEST": "",
                "PYTEST_CURRENT_TEST": "",
            },
        ),
        patch(
            "scripts.check_quality_snapshot.subprocess.run",
            side_effect=run_with_captured_env,
        ),
    ):
        outcomes = count_live_pytest_outcomes(root=PROJECT_ROOT)

    assert outcomes == (passed, 0, skipped)
    assert captured_env["MYAI_EMPLOYEE_SNAPSHOT_SKIP_LIVE_PYTEST"] == "1"
    assert captured_env["MY_AI_EMPLOYEE_SNAPSHOT_GUARDIAN_PROBE"] == "1"


def test_check_state_entries_script_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """状态入口 CLI 成功与错误退出码不再通过外部子进程复验。"""
    from scripts import check_state_entries as state_script

    captured_args: list[list[str]] = []

    def run_mypy(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_args.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Success: no issues found in 258 source files\n",
            stderr="",
        )

    with patch("scripts.check_state_entries.subprocess.run", side_effect=run_mypy):
        assert state_script.count_mypy_source_files(root=PROJECT_ROOT) == 258
    assert captured_args == [
        ["uv", "run", "mypy", "--strict", "src", "tests", state_script.P0_4_HEALTH_SAMPLE]
    ]

    with patch.object(state_script, "check_state_entries", return_value=[]):
        assert state_script.main() == 0
    assert "state entry docs match quality_snapshot" in capsys.readouterr().out

    with patch.object(state_script, "check_state_entries", return_value=["entry drift"]):
        assert state_script.main() == 1
    assert "ERROR: entry drift" in capsys.readouterr().err
