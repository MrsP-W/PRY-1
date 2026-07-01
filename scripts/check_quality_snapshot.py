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
    """pytest --collect-only 计数(与 snapshot pytest 字段对齐)."""
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
    expected_collected = passed + skipped
    if collected != expected_collected:
        errors.append(
            "pytest drift: "
            f"quality_snapshot claims {passed} passed / {skipped} skipped "
            f"(expected {expected_collected} collected), "
            f"pytest --collect-only has {collected}"
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
