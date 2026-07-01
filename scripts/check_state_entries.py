"""校验状态入口文档与 quality_snapshot 对齐(撞坑 #50 第四层防御).

只检查当前入口块(README / SESSION-STATE / MODIFICATION-LOG / launch-plan 基线行),
不扫描历史流水账。

用法:
    uv run python scripts/check_state_entries.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from my_ai_employee.quality_snapshot import (  # noqa: E402
    DEFAULT_QUALITY_GATES,
    QualityGateSnapshot,
)
from scripts.check_quality_snapshot import parse_lint_file_count, parse_pytest_counts  # noqa: E402

_MYPY_FILES_RE = re.compile(r"(\d+)\s+source files")


@dataclass(frozen=True, slots=True)
class EntryLineCheck:
    """单行入口校验:必须包含 required,不得包含 forbidden."""

    rel_path: str
    line_no: int
    required: tuple[str, ...]
    forbidden: tuple[str, ...] = ()


def count_mypy_source_files(root: Path = ROOT) -> int:
    """mypy src tests 源文件计数(与 make mypy 一致)."""
    result = subprocess.run(
        ["uv", "run", "mypy", "--strict", "src", "tests"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"mypy failed:\n{result.stdout}\n{result.stderr}"
        raise RuntimeError(msg)
    match = _MYPY_FILES_RE.search(result.stdout + result.stderr)
    if not match:
        msg = "无法解析 mypy 源文件计数"
        raise RuntimeError(msg)
    return int(match.group(1))


def parse_mypy_files_count(mypy_files: str) -> int:
    """从 '238 files' 解析计数."""
    match = re.match(r"^(\d+)\s+files\b", mypy_files.strip())
    if not match:
        msg = f"无法解析 quality_snapshot.mypy_files 格式: {mypy_files!r}"
        raise ValueError(msg)
    return int(match.group(1))


def build_entry_checks(*, gates: QualityGateSnapshot = DEFAULT_QUALITY_GATES) -> list[EntryLineCheck]:
    """根据 quality_snapshot 生成入口行校验规则."""
    md_count = parse_lint_file_count(gates.lint)
    passed, _skipped = parse_pytest_counts(gates.pytest)
    mypy_count = parse_mypy_files_count(gates.mypy_files)
    stale_md = str(md_count - 1) if md_count > 0 else "0"
    stale_mypy = str(mypy_count - 1) if mypy_count > 0 else "0"

    return [
        EntryLineCheck(
            "README.md",
            7,
            required=(
                f"{passed} passed",
                gates.coverage,
                f"MD lint {md_count}",
            ),
            forbidden=(f"MD lint {stale_md}",),
        ),
        EntryLineCheck(
            "SESSION-STATE.md",
            4,
            required=(f"lint **{md_count}**",),
            forbidden=(f"lint **{stale_md}**",),
        ),
        EntryLineCheck(
            "SESSION-STATE.md",
            18,
            required=(f"MD lint **{md_count}**",),
            forbidden=(f"MD lint **{stale_md}**",),
        ),
        EntryLineCheck(
            "SESSION-STATE.md",
            33,
            required=(
                gates.pytest,
                gates.coverage,
                f"{mypy_count} files",
                f"{md_count} files",
            ),
            forbidden=(f"{stale_mypy} files", f"{stale_md} files"),
        ),
        EntryLineCheck(
            "MODIFICATION-LOG.md",
            116,
            required=(
                gates.pytest,
                gates.coverage,
                f"{mypy_count} files",
                f"{md_count} files",
            ),
            forbidden=(f"{stale_mypy} files", f"{stale_md} files"),
        ),
        EntryLineCheck(
            "docs/v0.2-launch-plan.md",
            264,
            required=(
                gates.pytest,
                gates.coverage,
                f"{md_count} MD files",
                f"{mypy_count} files",
            ),
            forbidden=(f"{stale_md} MD files", f"{stale_mypy} files"),
        ),
    ]


def check_state_entries(*, root: Path = ROOT) -> list[str]:
    """返回漂移错误列表;空列表表示通过."""
    errors: list[str] = []
    gates = DEFAULT_QUALITY_GATES

    live_mypy = count_mypy_source_files(root)
    claimed_mypy = parse_mypy_files_count(gates.mypy_files)
    if live_mypy != claimed_mypy:
        errors.append(
            "mypy files drift: "
            f"quality_snapshot claims {claimed_mypy} files, "
            f"mypy src tests reports {live_mypy}"
        )

    for spec in build_entry_checks(gates=gates):
        path = root / spec.rel_path
        if not path.is_file():
            errors.append(f"missing entry file: {spec.rel_path}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        if spec.line_no < 1 or spec.line_no > len(lines):
            errors.append(f"{spec.rel_path}:{spec.line_no} line out of range")
            continue
        line = lines[spec.line_no - 1]
        for needle in spec.required:
            if needle not in line:
                errors.append(
                    f"{spec.rel_path}:{spec.line_no} missing {needle!r} "
                    f"(entry drift vs quality_snapshot)"
                )
        for needle in spec.forbidden:
            if needle in line:
                errors.append(
                    f"{spec.rel_path}:{spec.line_no} stale {needle!r} "
                    f"(entry drift vs quality_snapshot)"
                )
    return errors


def main() -> int:
    errors = check_state_entries()
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            "Fix: sync current-entry docs with quality_snapshot.py "
            "(README / SESSION-STATE / MODIFICATION-LOG / launch-plan baseline).",
            file=sys.stderr,
        )
        return 1
    gates = DEFAULT_QUALITY_GATES
    md_count = parse_lint_file_count(gates.lint)
    mypy_count = parse_mypy_files_count(gates.mypy_files)
    print(
        "OK: state entry docs match quality_snapshot "
        f"({gates.pytest} · {gates.coverage} · {md_count} md · {mypy_count} mypy files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
