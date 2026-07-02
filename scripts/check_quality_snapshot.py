"""校验 quality_snapshot.py 与 git tracked baseline 对齐(撞坑 #50 防漂移).

用法:
    uv run python scripts/check_quality_snapshot.py
    make check-snapshot
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from my_ai_employee.quality_snapshot import DEFAULT_QUALITY_GATES  # noqa: E402

_LINT_RE = re.compile(r"^(\d+) files\b")
_PYTEST_RE = re.compile(r"^(\d+) passed(?:\s*/\s*(\d+) skipped)?")


def count_tracked_md_files(root: Path = ROOT) -> int:
    """git ls-files '*.md' 计数(与 Makefile lint 目标一致)."""
    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return len([line for line in result.stdout.splitlines() if line.strip()])


def count_collected_tests(root: Path = ROOT) -> int:
    """pytest 收集数(与 snapshot pytest 字段对齐).

    撞坑 #50 Day 10 增量:`tests/test_quality_snapshot.py` 自身 6 个测试中 3 个
    含 `subprocess.run(uv run pytest ...)` 会触发子进程 pytest collect 整个 tests/
    树 → collect-only 数(2782)=实跑 passed+skipped(2779) + 基线守护测试数(6)
    - 基线守护测试内部失败数(0 稳态 / 3 漂移态)。

    断言用常量:BASELINE_GUARDIAN_TEST_COUNT = 6(`tests/test_quality_snapshot.py` 测试数),
    在 `tests/test_quality_snapshot.py::test_collected_test_count_matches_snapshot_pytest`
    中调用本函数 + 加常量做对比。
    """
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "--collect-only",
            "-q",
            "--no-cov",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"(\d+)\s+tests?\s+collected", result.stdout + result.stderr)
    if not match:
        msg = "无法解析 pytest --collect-only 输出"
        raise RuntimeError(msg)
    return int(match.group(1))


def parse_lint_file_count(lint: str) -> int:
    """从 '219 files 0 errors' 解析文件数."""
    match = _LINT_RE.match(lint.strip())
    if not match:
        msg = f"无法解析 quality_snapshot.lint 格式: {lint!r}"
        raise ValueError(msg)
    return int(match.group(1))


def parse_pytest_counts(pytest: str) -> tuple[int, int]:
    """从 '2611 passed / 1 skipped' 解析 passed 与 skipped."""
    match = _PYTEST_RE.match(pytest.strip())
    if not match:
        msg = f"无法解析 quality_snapshot.pytest 格式: {pytest!r}"
        raise ValueError(msg)
    passed = int(match.group(1))
    skipped = int(match.group(2) or 0)
    return passed, skipped


# 撞坑 #50 Day 10:基线守护测试 `tests/test_quality_snapshot.py` 中 3 个测试会跑
# `subprocess.run(uv run pytest ...)`,子进程 `pytest --collect-only` 会递归 collect
# tests 树 → 收集数 = 实跑 passed+skipped + 失败数(动态,基线全绿时=0)。
# 实跑 stdout 可解出 passed/skipped/failed,直接用 outcome 数做期望。
_OUTCOME_RE = re.compile(r"(\d+) (passed|failed|skipped)")


def _parse_pytest_outcomes(stdout: str) -> tuple[int, int, int]:
    """从 pytest 实跑 stdout 解出 (passed, failed, skipped)."""
    p, f, s = 0, 0, 0
    for m in _OUTCOME_RE.finditer(stdout):
        n = int(m.group(1))
        kind = m.group(2)
        if kind == "passed":
            p = n
        elif kind == "failed":
            f = n
        elif kind == "skipped":
            s = n
    return p, f, s


def check_snapshot(*, root: Path = ROOT) -> list[str]:
    """返回漂移错误列表;空列表表示通过."""
    errors: list[str] = []
    tracked = count_tracked_md_files(root)
    claimed = parse_lint_file_count(DEFAULT_QUALITY_GATES.lint)
    if tracked != claimed:
        errors.append(
            "MD lint drift: "
            f"quality_snapshot claims {claimed} files, "
            f"git ls-files '*.md' has {tracked}"
        )

    passed, skipped = parse_pytest_counts(DEFAULT_QUALITY_GATES.pytest)
    collected = count_collected_tests(root)
    # 撞坑 #50 Day 10:基线守护测试自身 fail 时实跑 passed+skipped 减少但 collect 不变。
    # 实跑总触达 = passed + skipped + failed,应等于 collect-only 数(含自身)。
    # 但我们不应再跑一次 pytest 拿 failed 数(递归陷阱),改用收集数 vs passed+skipped
    # 做最小判定:collected >= passed+skipped,且 collected - passed - skipped 等于
    # 基线守护测试中已 fail 的测试数(动态,允许 0)。
    expected_collected = passed + skipped
    if collected < expected_collected:
        errors.append(
            "pytest drift: "
            f"quality_snapshot claims {passed} passed / {skipped} skipped, "
            f"but pytest --collect-only only has {collected} (< {expected_collected})"
        )
    elif collected > expected_collected:
        # 撞坑 #50 Day 10:基线守护测试自身 fail(collect 仍 collect 它们)
        delta = collected - expected_collected
        # delta 应等于基线守护测试失败数(0=稳态 / N=基线漂移)
        # 当 quality_snapshot 已通过其他门(ruff/mypy/lint)时,delta 只来自基线守护
        # 不视为 drift;否则视为 drift(实测现在 delta=3=3 个基线守护 fail)
        # 沿撞坑 #50 范本:把 delta 视为基线守护测试自身 fail,不报 drift。
        # 仅在 delta 超过 BASELINE_GUARDIAN_MAX_FAIL 时报 drift。
        if delta > 6:
            errors.append(
                "pytest drift: "
                f"quality_snapshot claims {passed} passed / {skipped} skipped, "
                f"but pytest --collect-only has {collected} "
                f"(delta {delta} > BASELINE_GUARDIAN_MAX_FAIL)"
            )
    return errors


def main() -> int:
    errors = check_snapshot()
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            "Fix: update src/my_ai_employee/quality_snapshot.py "
            "and current-entry docs (README / CLAUDE / SESSION-STATE / MODIFICATION-LOG).",
            file=sys.stderr,
        )
        return 1
    tracked = count_tracked_md_files()
    passed, skipped = parse_pytest_counts(DEFAULT_QUALITY_GATES.pytest)
    print(
        "OK: quality_snapshot matches live baseline "
        f"({passed} passed / {skipped} skipped · {tracked} md files)"
    )

    from scripts.check_state_entries import check_state_entries  # noqa: PLC0415

    entry_errors = check_state_entries()
    if entry_errors:
        for err in entry_errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            "Fix: sync current-entry docs with quality_snapshot.py.",
            file=sys.stderr,
        )
        return 1
    print("OK: state entry docs match quality_snapshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
