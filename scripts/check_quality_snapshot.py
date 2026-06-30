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

from my_ai_employee.quality_snapshot import DEFAULT_QUALITY_GATES  # noqa: E402

_LINT_RE = re.compile(r"^(\d+) files\b")


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


def parse_lint_file_count(lint: str) -> int:
    """从 '218 files 0 errors' 解析文件数."""
    match = _LINT_RE.match(lint.strip())
    if not match:
        msg = f"无法解析 quality_snapshot.lint 格式: {lint!r}"
        raise ValueError(msg)
    return int(match.group(1))


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
    return errors


def main() -> int:
    errors = check_snapshot()
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            "Fix: update src/my_ai_employee/quality_snapshot.py lint field "
            "and current-entry docs (README / SESSION-STATE / MODIFICATION-LOG).",
            file=sys.stderr,
        )
        return 1
    tracked = count_tracked_md_files()
    print(f"OK: quality_snapshot MD lint matches git ls-files ({tracked} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
