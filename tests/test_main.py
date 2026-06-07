"""D1 验证测试：Hello + info + version。

D2+ 实际业务测试会在 tests/connectors/、tests/core/、tests/ai/ 下扩展。

注意：用 `python -m src.main` 而非 `python src/main.py`，避免 main.py 冲突。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 定位项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_main(*args: str) -> subprocess.CompletedProcess[str]:
    """用 python -m src.main 跑子进程。"""
    return subprocess.run(
        [sys.executable, "-m", "src.main", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_main_hello() -> None:
    """验证 `python -m src.main` 跑通（Hello, 我的AI员工）。"""
    result = _run_main()
    assert result.returncode == 0, f"非零退出码：{result.returncode}\n{result.stderr}"
    assert "我的AI员工" in result.stdout
    assert "Hello" in result.stdout


def test_main_version() -> None:
    """验证 --version 输出。"""
    result = _run_main("--version")
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


def test_main_info() -> None:
    """验证 --info 输出。"""
    result = _run_main("--info")
    assert result.returncode == 0
    assert "项目根目录" in result.stdout
    assert "D1 脚手架" in result.stdout


def test_main_help() -> None:
    """验证 --help 输出。"""
    result = _run_main("--help")
    assert result.returncode == 0
    assert "全天候个人 AI 数字员工" in result.stdout
    assert "--info" in result.stdout


def test_src_init_version() -> None:
    """验证 src 包版本。"""
    from src import __version__

    assert __version__ == "0.1.0"


def test_src_init_author() -> None:
    """验证 src 包作者。"""
    from src import __author__

    assert __author__ == "Mr-PRY"
