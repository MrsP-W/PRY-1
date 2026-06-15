"""D10.3 — launchd 部署脚本契约测试(8 cases).

承接 scripts/launchd_install.sh + scripts/launchd_uninstall.sh +
launchd_plist/com.myaiemployee.agent.plist(D10 启动).

测试目标(沿 D5.6 代理故障排查 memory ~/bin/ 部署范本 + 5 源判定):
    - plist XML 良构 + 必含 Label/ProgramArguments/StartCalendarInterval
    - install.sh 有 shebang + 5 源验证段 + 4 退出码契约
    - uninstall.sh 有 shebang + 1/3 退出码契约
    - plist 含 `$USER` 占位符(install.sh 必 sed 替换)
    - plist StartCalendarInterval 必为 1 号 9:0(沿 week2-mvp.md L224 + 审计员触发)
"""

from __future__ import annotations

import plistlib
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLIST_PATH = PROJECT_ROOT / "launchd_plist" / "com.myaiemployee.agent.plist"
INSTALL_SH = PROJECT_ROOT / "scripts" / "launchd_install.sh"
UNINSTALL_SH = PROJECT_ROOT / "scripts" / "launchd_uninstall.sh"


# ===== A. plist XML 良构 =====

def test_a1_plist_exists():
    """A1. plist 文件必存."""
    assert PLIST_PATH.exists(), f"plist 必存: {PLIST_PATH}"


def test_a2_plist_is_valid_xml():
    """A2. plist 必为良构 XML(plistlib 可解析)."""
    with PLIST_PATH.open("rb") as f:
        data = plistlib.load(f)
    assert isinstance(data, dict), "plist 必为 dict"


def test_a3_plist_label():
    """A3. Label 必为 'com.myaiemployee.agent'."""
    with PLIST_PATH.open("rb") as f:
        data = plistlib.load(f)
    assert data.get("Label") == "com.myaiemployee.agent", (
        f"Label 必为 com.myaiemployee.agent,实际 {data.get('Label')!r}"
    )


def test_a4_plist_program_arguments():
    """A4. ProgramArguments 必含 my-ai-employee-monthly-report + generate."""
    with PLIST_PATH.open("rb") as f:
        data = plistlib.load(f)
    args = data.get("ProgramArguments", [])
    assert len(args) >= 2, f"ProgramArguments 必 >= 2 元素,实际 {args}"
    assert "my-ai-employee-monthly-report" in args[0], (
        f"第 1 元素必含脚本名,实际 {args[0]!r}"
    )
    assert "generate" in args, f"必传 'generate' 子命令,实际 {args}"


def test_a5_plist_calendar_interval_monthly_1st_9am():
    """A5. StartCalendarInterval 必为 1 号 9:0(每月 1 号 09:00)."""
    with PLIST_PATH.open("rb") as f:
        data = plistlib.load(f)
    cal = data.get("StartCalendarInterval", {})
    assert cal.get("Month") == 1, f"Month 必为 1,实际 {cal.get('Month')}"
    assert cal.get("Day") == 1, f"Day 必为 1,实际 {cal.get('Day')}"
    assert cal.get("Hour") == 9, f"Hour 必为 9,实际 {cal.get('Hour')}"
    assert cal.get("Minute") == 0, f"Minute 必为 0,实际 {cal.get('Minute')}"


def test_a6_plist_run_at_load_false():
    """A6. RunAtLoad 必为 false(避免开机就触发)."""
    with PLIST_PATH.open("rb") as f:
        data = plistlib.load(f)
    assert data.get("RunAtLoad") is False, (
        f"RunAtLoad 必为 false(避免开机就触发),实际 {data.get('RunAtLoad')}"
    )


def test_a7_plist_uses_user_placeholder():
    """A7. plist 必用 $USER 占位符(install.sh sed 替换)."""
    text = PLIST_PATH.read_text(encoding="utf-8")
    assert "$USER" in text, "plist 必含 $USER 占位符(install.sh 必 sed 替换)"


def test_a8_plist_standard_log_paths():
    """A8. StandardOutPath/StandardErrorPath 必 ~/Library/Logs/MyAIEmployee/."""
    with PLIST_PATH.open("rb") as f:
        data = plistlib.load(f)
    out = data.get("StandardOutPath", "")
    err = data.get("StandardErrorPath", "")
    assert "Library/Logs/MyAIEmployee" in out, f"StandardOutPath 必 ~/Library/Logs/MyAIEmployee/,实际 {out}"
    assert "Library/Logs/MyAIEmployee" in err, f"StandardErrorPath 必 ~/Library/Logs/MyAIEmployee/,实际 {err}"


# ===== B. install.sh 契约 =====

def test_b1_install_sh_exists_and_executable():
    """B1. install.sh 必存且可执行."""
    assert INSTALL_SH.exists(), f"install.sh 必存: {INSTALL_SH}"
    import os
    import stat
    mode = INSTALL_SH.stat().st_mode
    assert mode & stat.S_IXUSR, "install.sh 必可执行"


def test_b2_install_sh_has_bash_shebang():
    """B2. install.sh 必以 #!/usr/bin/env bash 开头."""
    first_line = INSTALL_SH.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!") and "bash" in first_line, (
        f"install.sh 必以 bash shebang 开头,实际 {first_line!r}"
    )


def test_b3_install_sh_has_set_euo_pipefail():
    """B3. install.sh 必启用 set -euo pipefail(严格模式)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text, "install.sh 必启用 set -euo pipefail"


def test_b4_install_sh_has_5_source_check():
    """B4. install.sh 必含 5 源验证段(目录/脚本/plist/launchctl/日志)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    # 5 源关键词(沿 Agent Assistant proxy_health.sh 5 源判定范本)
    keywords = ("目录", "脚本", "plist", "launchctl", "日志")
    for kw in keywords:
        assert kw in text, f"install.sh 必含 5 源验证段关键词 {kw!r}"


def test_b5_install_sh_has_4_exit_codes():
    """B5. install.sh 必含 4 退出码契约(0/1/2/3)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    # 4 退出码
    assert re.search(r"exit\s+0\b", text), "exit 0 必出现"
    assert re.search(r"exit\s+1\b", text), "exit 1 必出现"
    assert re.search(r"exit\s+2\b", text), "exit 2 必出现"
    assert re.search(r"exit\s+3\b", text), "exit 3 必出现"


def test_b6_install_sh_deploys_to_home_bin():
    """B6. install.sh 必部署到 ~/bin/(沿 D5.6 memory ~/bin/ 部署范本)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    # ~/bin 路径必出现
    assert "${HOME}/bin" in text or "$HOME/bin" in text, (
        "install.sh 必部署到 ~/bin/(沿 D5.6 范本)"
    )


def test_b7_install_sh_uses_sed_for_user_replacement():
    """B7. install.sh 必用 sed 替换 $USER 占位符."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "sed" in text, "install.sh 必用 sed"
    assert r"\$USER" in text, "install.sh 必替换 $USER 占位符"


def test_b8_install_sh_uses_launchctl_load():
    """B8. install.sh 必调用 launchctl load -w(沿 D5.6 范本)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "launchctl load" in text, "install.sh 必调 launchctl load"
    assert "-w" in text, "install.sh 必传 -w(overrides disable flag)"


# ===== C. uninstall.sh 契约 =====

def test_c1_uninstall_sh_exists_and_executable():
    """C1. uninstall.sh 必存且可执行."""
    assert UNINSTALL_SH.exists(), f"uninstall.sh 必存: {UNINSTALL_SH}"
    import stat
    mode = UNINSTALL_SH.stat().st_mode
    assert mode & stat.S_IXUSR, "uninstall.sh 必可执行"


def test_c2_uninstall_sh_has_bash_shebang():
    """C2. uninstall.sh 必以 #!/usr/bin/env bash 开头."""
    first_line = UNINSTALL_SH.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!") and "bash" in first_line, (
        f"uninstall.sh 必以 bash shebang 开头,实际 {first_line!r}"
    )


def test_c3_uninstall_sh_has_exit_codes_1_and_3():
    """C3. uninstall.sh 必含 exit 1(已卸载) + exit 3(launchctl unload 失败)."""
    text = UNINSTALL_SH.read_text(encoding="utf-8")
    assert re.search(r"exit\s+1\b", text), "uninstall.sh exit 1 必出现(已卸载)"
    assert re.search(r"exit\s+3\b", text), "uninstall.sh exit 3 必出现(launchctl unload 失败)"


def test_c4_uninstall_sh_calls_launchctl_unload():
    """C4. uninstall.sh 必调 launchctl unload."""
    text = UNINSTALL_SH.read_text(encoding="utf-8")
    assert "launchctl unload" in text, "uninstall.sh 必调 launchctl unload"


def test_c5_uninstall_sh_supports_purge_bin():
    """C5. uninstall.sh --purge-bin 必删 ~/bin/ 脚本(可选,默认保留)."""
    text = UNINSTALL_SH.read_text(encoding="utf-8")
    assert "--purge-bin" in text, "uninstall.sh 必支持 --purge-bin 选项"
    assert "rm -f" in text, "uninstall.sh 必用 rm -f 删除"
