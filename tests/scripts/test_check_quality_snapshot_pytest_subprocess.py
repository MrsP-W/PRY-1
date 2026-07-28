"""防 #106 修复回退 + 防 #106 二修遗漏.

沿撞坑 #106 范本:`scripts/check_quality_snapshot.py` 的 3 处子进程必须用
`sys.executable -m pytest`,不能用 `uv run pytest`(干净 worktree uv 环境
缺 pytest)。同时禁止 `import sys` 重复(防 B1 修复回退)。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_quality_snapshot.py"


def test_no_uv_run_in_subprocess_pytest_calls() -> None:
    """scripts/check_quality_snapshot.py 中不应有 subprocess.run(['uv', ...]) 调 pytest.

    沿撞坑 #106:干净 worktree 的 uv 环境缺 pytest,子进程需用 sys.executable.
    """
    content = SCRIPT.read_text(encoding="utf-8")
    uv_in_subprocess = re.findall(
        r'subprocess\.run\(\s*\[\s*"uv"',
        content,
    )
    assert uv_in_subprocess == [], (
        f"发现 {len(uv_in_subprocess)} 处 subprocess.run(['uv', ...]) 调用 "
        f"(防 #106 一修回退 + 二修遗漏):"
        f"\n{uv_in_subprocess}"
        f"\n需改为 [sys.executable, '-m', 'pytest', ...]"
    )


def test_import_sys_appears_once() -> None:
    """scripts/check_quality_snapshot.py 中 `import sys` 必须唯一(防 B1 重复)."""
    content = SCRIPT.read_text(encoding="utf-8")
    count = len(re.findall(r"^import sys$", content, re.MULTILINE))
    assert count == 1, f"import sys 出现 {count} 次,期望 1(防 #106 二修 B1 回退)"


def test_subprocess_uses_sys_executable_three_times() -> None:
    """sys.executable 必须在 3 处子进程调用中出现.

    三处:
    - count_collected_tests (#106 一修)
    - count_baseline_guardian_failures (#106 二修 A1)
    - count_live_pytest_outcomes (#106 二修 A2)
    """
    content = SCRIPT.read_text(encoding="utf-8")
    count = content.count("sys.executable")
    assert count >= 3, f"sys.executable 出现 {count} 次,期望 ≥ 3(防 #106 二修遗漏)"
