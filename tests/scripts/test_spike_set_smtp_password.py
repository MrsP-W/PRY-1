"""D5.1-fix spike_set_smtp_password.py CLI provider 严判测试(3 cases)。

D5.1 启动后被用户标记的 2 个代码风险之一:
- spike_set_smtp_password.py argparse choices 暴露 outlook/gmail
  误导用户以为已实现,实际运行时 NotImplementedError 抛错

修复策略:argparse choices 严判为 ("qq",),outlook/gmail 由 argparse
自动 system exit 2 给清晰错误信息(无需运行时再抛 NotImplementedError)。

测试覆盖(3 cases):
    1. --provider qq 接受(argparse 不报错)
    2. --provider outlook 拒收(argparse SystemExit 2)
    3. --provider gmail 拒收(argparse SystemExit 2)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 项目根目录(用于 subprocess cwd)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "spike_set_smtp_password.py"


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """跑 spike_set_smtp_password.py CLI,返回 CompletedProcess。"""
    return subprocess.run(  # noqa: S603 — 测试 subprocess 是安全的
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        cwd=str(PROJECT_ROOT),
    )


# ===== TestSpikeCLIProvider(3 cases)=====
# D5.1-fix 修复:argparse choices=("qq",) 硬约束,outlook/gmail argparse 自动报错


class TestSpikeCLIProvider:
    """D5.1-fix:spike_set_smtp_password.py --provider 严判 == 'qq'。"""

    def test_argparse_qq_provider_accepted(self) -> None:
        # --provider qq 接受(argparse choices 通过,后续走 --check / --delete 等子命令)
        # 跑 --check 但不传 email,期望 argparse 报 email 缺失(不是 provider 错)
        result = _run_cli(["--provider", "qq", "--check"])
        # 期望:exit code 2(argparse 错误)且 stderr 含 "email" 缺失
        # 但 --check 不依赖 email 时(实际依赖),argparse 会先报 email missing
        # 关键是 stderr 不应该含 "provider" 错误
        assert "argument --provider" not in result.stderr
        assert "invalid choice" not in result.stderr
        # exit code 非 0 是预期的(可能 email missing 或 keychain not found)
        # 但应该是 argparse / 业务错误,不是 provider 错

    def test_argparse_outlook_provider_rejected(self) -> None:
        # --provider outlook 拒收(argparse SystemExit 2 + invalid choice)
        result = _run_cli(["--provider", "outlook", "--check", "--email", "u@o.com"])
        assert result.returncode == 2  # argparse 标准错误码
        # stderr 含 "invalid choice" + "outlook" + "qq"
        assert "invalid choice" in result.stderr.lower()
        assert "outlook" in result.stderr
        assert "qq" in result.stderr

    def test_argparse_gmail_provider_rejected(self) -> None:
        # --provider gmail 拒收(argparse SystemExit 2 + invalid choice)
        result = _run_cli(["--provider", "gmail", "--check", "--email", "u@g.com"])
        assert result.returncode == 2
        assert "invalid choice" in result.stderr.lower()
        assert "gmail" in result.stderr
        assert "qq" in result.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
