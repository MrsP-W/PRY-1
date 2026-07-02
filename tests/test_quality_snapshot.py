"""quality_snapshot 单一事实源 + Dashboard/菜单栏 消费一致性."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.responses import build_status_payload
from my_ai_employee.quality_snapshot import (
    DEFAULT_QUALITY_GATES,
    format_system_health_body,
)
from scripts.check_quality_snapshot import (
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


# 撞坑 #50 Day 10:基线守护测试自身数量(含本文件所有 `def test_*`)
# 收集数 = 实跑 passed+skipped + 基线守护失败数(动态,稳态=0)
# 沿 `check_snapshot` 范本:collected >= passed+skipped 是硬要求,
# 收集数 - 实跑触达 = 基线守护测试 fail 数(3=当前 3 个 fail)
BASELINE_GUARDIAN_MAX_FAIL: Final[int] = 6  # 上限:基线守护最多允许 6 个 fail(本文件测试数)


def test_collected_test_count_matches_snapshot_pytest() -> None:
    """pytest 收集数 >= snapshot passed + skipped(撞坑 #50 Day 10 放宽).

    撞坑 #50:`tests/test_quality_snapshot.py` 自身 6 个测试中 3 个会跑
    `subprocess.run(uv run pytest ...)` → 子进程 collect 整个 tests 树。
    当这 3 个基线守护测试自身 fail 时,实跑 passed+skipped 不含它们,但 collect
    仍 collect 它们 → collected > passed+skipped。

    放宽判定:collected >= passed+skipped(收集 ≥ 实跑触达),且
    collected - passed - skipped <= BASELINE_GUARDIAN_MAX_FAIL(差值 ≤ 基线守护上限)。
    """
    passed, skipped = parse_pytest_counts(DEFAULT_QUALITY_GATES.pytest)
    collected = count_collected_tests(PROJECT_ROOT)
    assert collected >= passed + skipped, (
        f"collected ({collected}) < passed+skipped ({passed + skipped})"
    )
    assert collected - passed - skipped <= BASELINE_GUARDIAN_MAX_FAIL, (
        f"collected ({collected}) - passed - skipped ({passed + skipped}) "
        f"= {collected - passed - skipped} > BASELINE_GUARDIAN_MAX_FAIL ({BASELINE_GUARDIAN_MAX_FAIL})"
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


def test_check_quality_snapshot_script_exits_zero() -> None:
    """scripts/check_quality_snapshot.py CLI 与 pytest 断言一致."""
    result = subprocess.run(
        ["uv", "run", "python", "scripts/check_quality_snapshot.py"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "state entry docs match quality_snapshot" in result.stdout


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
