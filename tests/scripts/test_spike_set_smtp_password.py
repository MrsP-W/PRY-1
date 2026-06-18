"""D5.1-fix / v0.2.2 SMTP provider Keychain CLI provider 严判测试。

D5.1 启动后被用户标记的 2 个代码风险之一:
- spike_set_smtp_password.py argparse choices 暴露 outlook/gmail
  误导用户以为已实现,实际运行时 NotImplementedError 抛错

v0.2.2 SMTPProviderFactory 解封后修订:
- qq/outlook/gmail 均允许写入对应 Keychain service
- 真实发送仍由 spike_send_100.py 的 SMTP_REAL_NETWORK + provider 白名单保护

测试覆盖:
    1. --provider qq/outlook/gmail 接受(argparse 不报 provider 错)
    2. 未知 provider 拒收(argparse SystemExit 2)
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


# ===== TestSpikeCLIProvider =====
# v0.2.2 修订:argparse choices=("qq","outlook","gmail")。


class TestSpikeCLIProvider:
    """spike_set_smtp_password.py --provider 严判白名单。"""

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

    def test_argparse_outlook_provider_accepted(self) -> None:
        result = _run_cli(["--provider", "outlook", "--check", "--email", "u@o.com"])
        assert "argument --provider" not in result.stderr
        assert "invalid choice" not in result.stderr.lower()

    def test_argparse_gmail_provider_accepted(self) -> None:
        result = _run_cli(["--provider", "gmail", "--check", "--email", "u@g.com"])
        assert "argument --provider" not in result.stderr
        assert "invalid choice" not in result.stderr.lower()

    def test_argparse_unknown_provider_rejected(self) -> None:
        result = _run_cli(["--provider", "invalid", "--check", "--email", "u@g.com"])
        assert result.returncode == 2
        assert "invalid choice" in result.stderr.lower()
        assert "invalid" in result.stderr
        assert "qq" in result.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
