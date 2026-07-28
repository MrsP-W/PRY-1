"""防 #106 二修 Makefile ruff scope 回退.

沿撞坑 #106 二修 C1:`make ruff` 必须覆盖 `check_quality_snapshot.py`,
不能漏 scripts/ 目录。本测试断言 LAUNCHD_ONE_SHOT_SCRIPTS 包含
`check_quality_snapshot.py`(实际 ruff 命令沿用 `$(LAUNCHD_ONE_SHOT_SCRIPTS)`)。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"


def test_makefile_ruff_includes_check_quality_snapshot() -> None:
    """Makefile LAUNCHD_ONE_SHOT_SCRIPTS 必须包含 check_quality_snapshot.py.

    沿撞坑 #106 二修 C1:make ruff 必须覆盖 scripts/ 中所有目标。
    `scripts/check_quality_snapshot.py` 是 quality snapshot 守护脚本,
    修复 #106 后任何回退(包括重复 import / 子进程 uv 残留)必须被 ruff 检测。
    """
    content = MAKEFILE.read_text(encoding="utf-8")

    # 找 LAUNCHD_ONE_SHOT_SCRIPTS 定义行
    assert "LAUNCHD_ONE_SHOT_SCRIPTS :=" in content, "Makefile 应定义 LAUNCHD_ONE_SHOT_SCRIPTS 变量"

    # 提取 LAUNCHD_ONE_SHOT_SCRIPTS 行
    match = re.search(
        r"^LAUNCHD_ONE_SHOT_SCRIPTS := (.+)$",
        content,
        re.MULTILINE,
    )
    assert match is not None, "找不到 LAUNCHD_ONE_SHOT_SCRIPTS 定义"

    scripts_list = match.group(1).split()
    assert "scripts/check_quality_snapshot.py" in scripts_list, (
        f"LAUNCHD_ONE_SHOT_SCRIPTS 必须包含 scripts/check_quality_snapshot.py(防 #106 二修 C1 回退)\n"
        f"当前:{scripts_list}"
    )

    # ruff 命令必须用 $(LAUNCHD_ONE_SHOT_SCRIPTS)
    assert "ruff check src tests $(LAUNCHD_ONE_SHOT_SCRIPTS)" in content, (
        "make ruff 必须包含 $(LAUNCHD_ONE_SHOT_SCRIPTS) 变量(沿用 make ruff 模式)"
    )
