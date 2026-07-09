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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLIST_PATH = PROJECT_ROOT / "launchd_plist" / "com.myaiemployee.agent.plist"
PLIST_IMAP_PATH = PROJECT_ROOT / "launchd_plist" / "com.myaiemployee.imap-sync.plist"
PLIST_START_PATH = PROJECT_ROOT / "launchd_plist" / "com.myaiemployee.digital-employee.plist"
INSTALL_SH = PROJECT_ROOT / "scripts" / "launchd_install.sh"
UNINSTALL_SH = PROJECT_ROOT / "scripts" / "launchd_uninstall.sh"
KICKSTART_SEAL_SH = PROJECT_ROOT / "scripts" / "launchd_kickstart_and_seal.sh"
START_DIGITAL_EMPLOYEE_SH = PROJECT_ROOT / "ops" / "start-digital-employee.sh"


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
    assert "my-ai-employee-monthly-report" in args[0], f"第 1 元素必含脚本名,实际 {args[0]!r}"
    assert "generate" in args, f"必传 'generate' 子命令,实际 {args}"


def test_a5_plist_calendar_interval_monthly_1st_9am():
    """A5. StartCalendarInterval 必为每月 1 号 9:0(不含 Month → 每月重复)."""
    with PLIST_PATH.open("rb") as f:
        data = plistlib.load(f)
    cal = data.get("StartCalendarInterval", {})
    assert "Month" not in cal, f"Month 不应存在(否则仅 1 月触发),实际 {cal.get('Month')}"
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
    assert "Library/Logs/MyAIEmployee" in out, (
        f"StandardOutPath 必 ~/Library/Logs/MyAIEmployee/,实际 {out}"
    )
    assert "Library/Logs/MyAIEmployee" in err, (
        f"StandardErrorPath 必 ~/Library/Logs/MyAIEmployee/,实际 {err}"
    )


# ===== B. install.sh 契约 =====


def test_b1_install_sh_exists_and_executable():
    """B1. install.sh 必存且可执行."""
    assert INSTALL_SH.exists(), f"install.sh 必存: {INSTALL_SH}"
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
    assert "${HOME}/bin" in text or "$HOME/bin" in text, "install.sh 必部署到 ~/bin/(沿 D5.6 范本)"


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


# ===== D. launchd_kickstart_and_seal.sh 契约(2026-06-23 检查员 P0 修复)=====


def test_d1_kickstart_seal_sh_exists():
    """D1. launchd_kickstart_and_seal.sh 必存."""
    assert KICKSTART_SEAL_SH.exists(), f"kickstart_seal.sh 必存: {KICKSTART_SEAL_SH}"


def test_d2_kickstart_seal_sh_has_bash_shebang():
    """D2. kickstart_seal.sh 必以 #!/usr/bin/env bash 开头."""
    first_line = KICKSTART_SEAL_SH.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!") and "bash" in first_line, (
        f"kickstart_seal.sh 必以 bash shebang 开头,实际 {first_line!r}"
    )


def test_d3_kickstart_seal_sh_has_set_euo_pipefail():
    """D3. kickstart_seal.sh 必启用 set -euo pipefail(严格模式)."""
    text = KICKSTART_SEAL_SH.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text, "kickstart_seal.sh 必启用 set -euo pipefail"


def test_d4_kickstart_seal_sh_uses_plutil_for_label_check():
    """D4. kickstart_seal.sh 必用 plutil 验 Label(沿 4 重防误发 重 1)."""
    text = KICKSTART_SEAL_SH.read_text(encoding="utf-8")
    assert "plutil" in text, "kickstart_seal.sh 必用 plutil 验 Label"
    assert "Label" in text, "kickstart_seal.sh 必含 Label 字段校验"


def test_d5_kickstart_seal_sh_uses_launchctl_kickstart():
    """D5. kickstart_seal.sh 必调 launchctl kickstart(沿选 C 方案 Step 2)."""
    text = KICKSTART_SEAL_SH.read_text(encoding="utf-8")
    assert "launchctl kickstart" in text, "kickstart_seal.sh 必调 launchctl kickstart"


def test_d6_kickstart_seal_sh_references_v010_tag_as_plain_text():
    """D6. kickstart_seal.sh 必用纯文本引用 v0.1.0 tag(2af775f),不写 ${2af775f} 等会被 bash 当变量展开。

    修复历史(检查员 6/22 检查报告 P0):
        原 L194 写 `tag ${2af775f}` → bash 会把 ${2af775f} 当变量求值,运行期报 `bad substitution`。
        修法:用纯文本 `2af775f` 或定义常量再引用。
        本测试断言:扫描所有 `${...}` 引用,只允许 `${VARNAME}` 形式(VARNAME 以字母/下划线开头),
        拒收 `${数字...}` 这种 bash 解释为 bad substitution 的形式。
    """
    text = KICKSTART_SEAL_SH.read_text(encoding="utf-8")
    # 匹配所有 ${...} 引用(不贪婪,匹配到第一个 } 即可)
    matches = re.findall(r"\$\{([^}]+)\}", text)
    assert matches, "kickstart_seal.sh 必有 ${...} 引用(本测试才有意义)"
    for varname in matches:
        # varname 必以字母/下划线开头(合法变量名)
        # 数字开头会被 bash 当成 positional param 求值,触发 bad substitution
        assert re.match(r"^[A-Za-z_]", varname), (
            f"kickstart_seal.sh 含 bad substitution 陷阱: ${{{varname}}} "
            f"(varname 不能以数字开头,会被 bash 当 positional param 求值,运行期报 bad substitution。"
            f"修法:用纯文本 commit hash / 定义常量再引用)"
        )


def test_d7_kickstart_seal_sh_has_release_notes_flip():
    """D7. kickstart_seal.sh 必含 release notes flip 段(沿选 C 方案 Step 5)."""
    text = KICKSTART_SEAL_SH.read_text(encoding="utf-8")
    assert "release notes" in text.lower() or "v0.1-release-notes" in text, (
        "kickstart_seal.sh 必含 release notes flip 段"
    )
    assert "sed -i" in text, "kickstart_seal.sh 必用 sed -i 改 release notes"


# ===== E. IMAP sync plist =====


def test_e1_imap_plist_exists():
    assert PLIST_IMAP_PATH.exists()


def test_e2_imap_plist_label():
    with PLIST_IMAP_PATH.open("rb") as f:
        data = plistlib.load(f)
    assert data.get("Label") == "com.myaiemployee.imap-sync"


def test_e3_imap_plist_daily_7am():
    with PLIST_IMAP_PATH.open("rb") as f:
        data = plistlib.load(f)
    cal = data.get("StartCalendarInterval", {})
    assert cal.get("Hour") == 7
    assert cal.get("Minute") == 0
    assert data.get("RunAtLoad") is False


# ===== F. digital-employee plist =====


def test_f1_start_plist_exists():
    assert PLIST_START_PATH.exists()


def test_f2_start_plist_label():
    with PLIST_START_PATH.open("rb") as f:
        data = plistlib.load(f)
    assert data.get("Label") == "com.myaiemployee.digital-employee"


def test_f3_start_plist_run_at_load():
    with PLIST_START_PATH.open("rb") as f:
        data = plistlib.load(f)
    assert data.get("RunAtLoad") is True
    args = data.get("ProgramArguments", [])
    assert "my-ai-employee-start" in args[0]


def test_f4_install_sh_deploys_digital_runner_to_home_bin():
    """F4. 数字员工 runner 必部署到 ~/bin,避免 launchd 执行 Documents 下的 sh."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert 'TARGET_START_RUNNER="${HOME_BIN}/my-ai-employee-digital-runner"' in text
    assert 'cp "${SOURCE_START_SH}" "${TARGET_START_RUNNER}"' in text
    assert 'chmod +x "${TARGET_START_RUNNER}"' in text
    assert '"${HOME_BIN}/my-ai-employee-digital-runner"' in text


def test_f5_install_start_wrapper_avoids_documents_ops_exec():
    """F5. start wrapper 不得再 exec 项目 Documents 目录下的 ops 脚本."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    forbidden = 'exec bash \\"${PROJECT_ROOT}/ops/start-digital-employee.sh\\" start'
    assert forbidden not in text
    assert 'export MY_AI_EMPLOYEE_PROJECT_ROOT=\\"${PROJECT_ROOT}\\"' in text
    assert 'exec \\"${TARGET_START_RUNNER}\\" start' in text


def test_f6_start_script_accepts_explicit_project_root_override():
    """F6. 被复制到 ~/bin 的 runner 必能用显式项目根路径定位资源."""
    text = START_DIGITAL_EMPLOYEE_SH.read_text(encoding="utf-8")
    assert "MY_AI_EMPLOYEE_PROJECT_ROOT" in text
    assert 'PROJECT_ROOT="${MY_AI_EMPLOYEE_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"' in text


def test_f7_install_sh_supports_deploy_only_without_launchctl_load():
    """F7. deploy-only/no-load 必只部署文件,不进入 launchctl load 段."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "deploy-only | no-load)" in text
    assert "DEPLOY_ONLY=true" in text
    deploy_exit = text.index('if [[ "${DEPLOY_ONLY}" == "true" ]]')
    load_section = text.index("# ===== 6. launchctl load(3 job) =====")
    assert deploy_exit < load_section
    deploy_block = text[deploy_exit:load_section]
    assert "launchctl load -w" in deploy_block
    assert "exit 0" in deploy_block
