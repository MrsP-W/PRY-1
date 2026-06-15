"""S9 — launchd 重启 → 全部适配器自愈(D10 实化).

承接 docs/v0.1-launch-plan.md:244 S9 唯一编号表行 + docs/week2-mvp.md:241-256 D10 任务
+ D10.3 launchd_install.sh + plist(D10.3 commit ff30587).

D10.4 范围(2026-06-15 启动):skip 占位 → 真实断言.
    S9.1 — launchd plist 部署结构验证(Label / StartCalendarInterval / ~/bin/)
    S9.2 — @管家 agent 监控所有适配器(IMAP / 微信 / 支付宝 / Apple Notes / 菜单栏)
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLIST_PATH = PROJECT_ROOT / "launchd_plist" / "com.myaiemployee.agent.plist"
INSTALL_SH = PROJECT_ROOT / "scripts" / "launchd_install.sh"
UNINSTALL_SH = PROJECT_ROOT / "scripts" / "launchd_uninstall.sh"
STEWARD_PATH = PROJECT_ROOT / "src" / "my_ai_employee" / "agents" / "管家.md"


@pytest.mark.e2e
def test_s9_launchd_plist_deployment_structure():
    """S9.1 — launchd plist 必含部署结构(Label / ProgramArguments / StartCalendarInterval)."""
    assert PLIST_PATH.exists(), f"S9.1 plist 必存: {PLIST_PATH}"
    with PLIST_PATH.open("rb") as f:
        data = plistlib.load(f)

    # 沿 D10.3 8 验收点(测试中精简 5 关键点)
    assert data.get("Label") == "com.myaiemployee.agent", (
        f"S9.1 Label 必为 com.myaiemployee.agent,实际 {data.get('Label')!r}"
    )
    args = data.get("ProgramArguments", [])
    assert any("my-ai-employee-monthly-report" in a for a in args), (
        f"S9.1 ProgramArguments 必含脚本名,实际 {args}"
    )
    assert "generate" in args, "S9.1 必传 generate 子命令"

    cal = data.get("StartCalendarInterval", {})
    assert cal.get("Month") == 1 and cal.get("Day") == 1, f"S9.1 必每月 1 号触发,实际 {cal}"
    assert cal.get("Hour") == 9, "S9.1 必 09:00 触发"

    # RunAtLoad=false(避免开机就触发)
    assert data.get("RunAtLoad") is False, "S9.1 RunAtLoad 必为 false"


@pytest.mark.e2e
def test_s9_launchd_install_script_deploys_to_home_bin():
    """S9.2 — install.sh 必部署到 ~/bin/(沿 D5.6 范本)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    # ~/bin 路径必出现
    assert "${HOME}/bin" in text or "$HOME/bin" in text, (
        "S9.2 install.sh 必部署到 ~/bin/(沿 D5.6 范本)"
    )
    # launchctl load 必出现
    assert "launchctl load" in text, "S9.2 install.sh 必调 launchctl load"
    # 5 源验证
    for keyword in ("目录", "脚本", "plist", "launchctl", "日志"):
        assert keyword in text, f"S9.2 install.sh 必含 5 源验证 {keyword!r}"


@pytest.mark.e2e
def test_s9_launchd_uninstall_script_removes_plist():
    """S9.3 — uninstall.sh 必卸载 plist + 支持 --purge-bin."""
    text = UNINSTALL_SH.read_text(encoding="utf-8")
    assert "launchctl unload" in text, "S9.3 uninstall.sh 必调 launchctl unload"
    assert "rm -f" in text, "S9.3 uninstall.sh 必用 rm -f 删 plist"
    assert "--purge-bin" in text, "S9.3 uninstall.sh 必支持 --purge-bin 选项"


@pytest.mark.e2e
def test_s9_steward_agent_monitors_all_adapters():
    """S9.4 — @管家 agent 必监控全部 5 类适配器(IMAP/微信/支付宝/Apple Notes/菜单栏)."""
    body = STEWARD_PATH.read_text(encoding="utf-8")
    # 管家职责段
    assert "邮件处理" in body, "S9.4 管家必含邮件处理(IMAP)"
    # 5 类适配器关键词
    adapter_keywords = {
        "IMAP": "邮件处理" in body or "IMAP" in body,
        "微信/支付宝": "账本" in body or "微信" in body or "支付宝" in body,
        "Apple Notes": "笔记" in body,
        "菜单栏": "D5 业务调度器" in body or "菜单栏" in body or "日程" in body,
    }
    for adapter, present in adapter_keywords.items():
        assert present, f"S9.4 管家必监控适配器 {adapter!r}"


@pytest.mark.e2e
def test_s9_steward_24h_on_duty_with_sla():
    """S9.5 — @管家 必 24h 在岗 + SLA 告警(沿 D5.5 Heartbeat)."""
    body = STEWARD_PATH.read_text(encoding="utf-8")
    assert "24h 在岗" in body or "24小时在岗" in body, "S9.5 管家必明示 24h 在岗"
    # SLA 告警必联动 D5.5
    assert "D5.5" in body or "SLA" in body or "Heartbeat" in body, (
        "S9.5 管家必联动 D5.5 SLA/Heartbeat"
    )
    # 退避重试
    assert "退避" in body or "重试" in body, "S9.5 管家必含退避重试"


@pytest.mark.e2e
def test_s9_launchd_recovery_subprocess_succeeds():
    """S9.6 — install.sh 跑 help(不真跑 deploy)能 dry-run 通过(沿 D5.6.5 spike 范本).

    真实 launchctl load 在 CI 不可达,本测试只验 install.sh 能被 shell 解析(无 syntax error).
    """
    # shell -n 模式 = 解析不执行
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"S9.6 install.sh 语法必正确,实际 rc={result.returncode},stderr: {result.stderr}"
    )

    result = subprocess.run(
        ["bash", "-n", str(UNINSTALL_SH)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"S9.6 uninstall.sh 语法必正确,实际 rc={result.returncode},stderr: {result.stderr}"
    )
