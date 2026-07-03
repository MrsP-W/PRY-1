"""quality_snapshot 单一事实源 + Dashboard/菜单栏 消费一致性."""

from __future__ import annotations

import subprocess
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
    check_snapshot,
    count_baseline_guardian_failures,
    count_collected_tests,
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
    """snapshot 少记测试时不应被固定 guardian 上限误放行."""
    passed, skipped = parse_pytest_counts(DEFAULT_QUALITY_GATES.pytest)
    collected = count_collected_tests(PROJECT_ROOT)
    guardian_failures = count_baseline_guardian_failures(root=PROJECT_ROOT)
    if collected != passed + skipped + guardian_failures:
        pytest.skip("当前 snapshot 已漂移,跳过模拟 under-report 用例")
    with patch(
        "scripts.check_quality_snapshot.DEFAULT_QUALITY_GATES",
        QualityGateSnapshot(
            pytest=f"{passed - 6} passed / {skipped} skipped",
            coverage=DEFAULT_QUALITY_GATES.coverage,
            mypy=DEFAULT_QUALITY_GATES.mypy,
            mypy_files=DEFAULT_QUALITY_GATES.mypy_files,
            lint=DEFAULT_QUALITY_GATES.lint,
        ),
    ):
        errors = check_snapshot(root=PROJECT_ROOT)
    assert errors
    assert any("pytest drift" in err for err in errors)


def test_check_quality_snapshot_script_exits_zero() -> None:
    """scripts/check_quality_snapshot.py CLI 与 pytest 断言一致."""
    import os

    result = subprocess.run(
        ["uv", "run", "python", "scripts/check_quality_snapshot.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MYAI_EMPLOYEE_SNAPSHOT_SKIP_LIVE_PYTEST": "1"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "state entry docs match quality_snapshot" in result.stdout


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


def test_check_state_entries_script_exits_zero() -> None:
    """scripts/check_state_entries.py CLI 与入口文档一致."""
    result = subprocess.run(
        ["uv", "run", "python", "scripts/check_state_entries.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
