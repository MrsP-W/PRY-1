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

_GUARDIAN_PROBE_ENV = "MY_AI_EMPLOYEE_SNAPSHOT_GUARDIAN_PROBE"
_SKIP_LIVE_PYTEST_ENV = "MYAI_EMPLOYEE_SNAPSHOT_SKIP_LIVE_PYTEST"

_LINT_RE = re.compile(r"^(\d+) files\b")
_PYTEST_RE = re.compile(r"^(\d+) passed(?:\s*/\s*(\d+) skipped)?")
_BASELINE_GUARDIAN_REL = Path("tests/test_quality_snapshot.py")
_TEST_DEF_RE = re.compile(r"^\s*def test_", re.MULTILINE)


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


def count_baseline_guardian_tests(*, root: Path = ROOT) -> int:
    """`tests/test_quality_snapshot.py` 内 test 函数数(基线守护上限)."""
    path = root / _BASELINE_GUARDIAN_REL
    text = path.read_text(encoding="utf-8")
    return len(_TEST_DEF_RE.findall(text))


def count_baseline_guardian_failures(*, root: Path = ROOT) -> int:
    """仅跑基线守护模块,返回 fail 数(用于解释 collect vs passed+skipped 差值)."""
    import os

    if os.environ.get(_GUARDIAN_PROBE_ENV) == "1" or os.environ.get("PYTEST_CURRENT_TEST"):
        # pytest 进程内不得再启动 guardian：测试本身会调用 check_snapshot/CLI，
        # 否则会高扇出地递归 spawn pytest。仅顶层 CLI 做一次 guardian 探测。
        return 0
    env = os.environ.copy()
    env[_GUARDIAN_PROBE_ENV] = "1"
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            str(_BASELINE_GUARDIAN_REL),
            "-q",
            "--no-cov",
            "--tb=no",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    _, failed, _ = _parse_pytest_outcomes(result.stdout + result.stderr)
    return failed


def count_live_pytest_outcomes(*, root: Path = ROOT) -> tuple[int, int, int] | None:
    """实跑 pytest 解出 (passed, failed, skipped);SKIP 环境或已在 pytest 内时返回 None."""
    import os

    if os.environ.get(_SKIP_LIVE_PYTEST_ENV) == "1":
        return None
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    env = os.environ.copy()
    env[_SKIP_LIVE_PYTEST_ENV] = "1"
    # The live pytest includes the snapshot guardian tests. The outer check has
    # already run the guardian probe above, so prevent this child suite from
    # spawning another guardian probe.
    env[_GUARDIAN_PROBE_ENV] = "1"
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "--no-cov",
            "--tb=no",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    passed, failed, skipped = _parse_pytest_outcomes(result.stdout + result.stderr)
    if passed == 0 and failed == 0 and skipped == 0:
        msg = "无法解析 pytest 实跑 passed/skipped 分布"
        raise RuntimeError(msg)
    if failed > 0:
        msg = f"pytest 实跑有 {failed} failed,无法校验 snapshot 分布"
        raise RuntimeError(msg)
    return passed, failed, skipped


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
    # 撞坑 #50 Day 10:稳态要求 collected == passed+skipped(严格)。
    # 仅当基线守护模块自身有 fail 时,允许 collected = passed+skipped+failures,
    # 且 failures 必须等于实测 guardian fail 数(不能用固定上限掩盖 snapshot 漂移)。
    expected_collected = passed + skipped
    guardian_failures = count_baseline_guardian_failures(root=root)
    guardian_cap = count_baseline_guardian_tests(root=root)
    if guardian_failures > guardian_cap:
        errors.append(
            "pytest drift: "
            f"baseline guardian failures ({guardian_failures}) "
            f"> guardian test count ({guardian_cap})"
        )
        return errors
    allowed_collected = expected_collected + guardian_failures
    if collected < expected_collected:
        errors.append(
            "pytest drift: "
            f"quality_snapshot claims {passed} passed / {skipped} skipped, "
            f"but pytest --collect-only only has {collected} (< {expected_collected})"
        )
    elif collected != allowed_collected:
        errors.append(
            "pytest drift: "
            f"quality_snapshot claims {passed} passed / {skipped} skipped, "
            f"pytest --collect-only has {collected}, "
            f"expected {allowed_collected} "
            f"(passed+skipped={expected_collected} + "
            f"baseline guardian failures={guardian_failures})"
        )

    # 撞坑 #50 Day 13:collected 总数对齐不够,须校验实跑 passed/skipped 分布
    live = count_live_pytest_outcomes(root=root)
    if live is not None:
        live_passed, _live_failed, live_skipped = live
        if live_passed != passed or live_skipped != skipped:
            errors.append(
                "pytest outcome drift: "
                f"quality_snapshot claims {passed} passed / {skipped} skipped, "
                f"live pytest reports {live_passed} passed / {live_skipped} skipped"
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
