"""D7 虚拟 spike — 5 段全链路 + 4 重防'误' 范本测试.

承接 D7 5 段虚拟 spike + D5.6.5 4 重防误发范本:
    - env 门控 D7_VIRTUAL_SPIKE=1(缺省 → exit 1)
    - confirm 文本(不匹配 → exit 1)
    - --pairs 范围 1-20(超出 → exit 1)
    - --seed 非负(负数 → exit 1)
    - 5 段全过(EXIT 0)

跑法:
    pytest tests/scripts/test_spike_d7_virtual.py -v
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPIKE_SCRIPT = PROJECT_ROOT / "scripts" / "spike_d7_virtual_cross_source.py"

CONFIRM_PHRASE = "yes-i-understand-this-is-virtual"
SPIKE_ENV_VAR = "D7_VIRTUAL_SPIKE"
SPIKE_ENV_VALUE = "1"


def _run_spike(
    *args: str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """跑 spike 子进程,捕获 stdout/stderr/returncode."""
    env = os.environ.copy()
    env.pop(SPIKE_ENV_VAR, None)  # 默认不设
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["uv", "run", "python", str(SPIKE_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
        timeout=120,
    )


# ===== 4 重防'误' 范本 =====


def test_guard_1_env_locked_by_default() -> None:
    """门 1:env 门控 — 不设 D7_VIRTUAL_SPIKE=1 → exit 1."""
    result = _run_spike("--confirm", CONFIRM_PHRASE)
    assert result.returncode == 1, (
        f"未设 env 应 exit 1,实际 {result.returncode}\nstderr={result.stderr}"
    )
    assert SPIKE_ENV_VAR in result.stderr


def test_guard_2_confirm_mismatch_exits_1() -> None:
    """门 2:confirm 文本 — 不匹配 → exit 1."""
    result = _run_spike(
        "--confirm",
        "wrong-text",
        env_extra={SPIKE_ENV_VAR: SPIKE_ENV_VALUE},
    )
    assert result.returncode == 1
    assert "confirm" in result.stderr.lower() or "yes-i-understand" in result.stderr


def test_guard_3_pairs_out_of_range_exits_1() -> None:
    """门 3:--pairs 范围 1-20 — 超出 → exit 1."""
    result = _run_spike(
        "--confirm",
        CONFIRM_PHRASE,
        "--pairs",
        "0",
        env_extra={SPIKE_ENV_VAR: SPIKE_ENV_VALUE},
    )
    assert result.returncode == 1
    assert "pairs" in result.stderr.lower()

    result = _run_spike(
        "--confirm",
        CONFIRM_PHRASE,
        "--pairs",
        "21",
        env_extra={SPIKE_ENV_VAR: SPIKE_ENV_VALUE},
    )
    assert result.returncode == 1


def test_guard_4_seed_negative_exits_1() -> None:
    """门 4:--seed 非负 — 负数 → exit 1."""
    result = _run_spike(
        "--confirm",
        CONFIRM_PHRASE,
        "--seed",
        "-1",
        env_extra={SPIKE_ENV_VAR: SPIKE_ENV_VALUE},
    )
    assert result.returncode == 1
    assert "seed" in result.stderr.lower()


# ===== 5 段全过 范本 =====


def test_spike_5_segments_all_pass(tmp_path: Path) -> None:
    """5 段全过 — 4 重防误发全过 + 5 段 PASS + 报告生成.

    完整链路验证:
    - env 门控 ✓
    - confirm 文本 ✓
    - --pairs 5(范围) ✓
    - --seed 42(非负) ✓
    - 5 段全过(PASS)
    - 报告写入 docs/reports/2026-06-15-d7-virtual-spike.md
    """
    result = _run_spike(
        "--confirm",
        CONFIRM_PHRASE,
        "--pairs",
        "5",
        "--seed",
        "42",
        "--report-dir",
        str(tmp_path / "reports"),
        env_extra={SPIKE_ENV_VAR: SPIKE_ENV_VALUE},
    )
    assert result.returncode == 0, (
        f"5 段 spike 应 exit 0,实际 {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    # 5 段全过
    assert "5 段全过: True" in result.stdout
    # 报告生成
    report_path = tmp_path / "reports" / "2026-06-15-d7-virtual-spike.md"
    assert report_path.exists(), f"报告应生成: {report_path}"
    content = report_path.read_text(encoding="utf-8")
    # 5 段都在报告里(用段号 + 关键词匹配,因段描述本身有"."会与 split 冲突)
    assert "| A | 单源 L1 重复阻断" in content
    assert "| B | 单源 L1 跨源不误判" in content
    assert "| C | 跨源 L2 needs_confirm 触发" in content and "alipay→wechat" in content
    assert "| D | 跨源 L2 needs_confirm 触发" in content and "wechat→alipay" in content
    assert "| E | D7 5 扩展点全验证" in content
    # inserted + duplicates + needs_confirm 计数
    assert "inserted=" in content or "**inserted**" in content


def test_spike_different_pairs_runs_segments() -> None:
    """--pairs=2 也应能跑(段 C/D 的"对数"参数化)."""
    result = _run_spike(
        "--confirm",
        CONFIRM_PHRASE,
        "--pairs",
        "2",
        "--seed",
        "100",
        env_extra={SPIKE_ENV_VAR: SPIKE_ENV_VALUE},
    )
    assert result.returncode == 0
    assert "5 段全过: True" in result.stdout


def test_spike_creates_temporary_db_not_real() -> None:
    """DB 隔离:spike 跑的 DB 是临时 sqlite,绝不入真实 ~/Library."""
    result = _run_spike(
        "--confirm",
        CONFIRM_PHRASE,
        "--pairs",
        "3",
        "--seed",
        "7",
        env_extra={SPIKE_ENV_VAR: SPIKE_ENV_VALUE},
    )
    assert result.returncode == 0
    # 报告里 db_path 应是 /tmp/... 或 tempdir
    assert "db_path" in result.stdout or "/tmp/" in result.stdout
    # 不应含真实 DB 路径
    assert "Library/Application Support" not in result.stdout
    assert "Library/Application Support" not in result.stderr
