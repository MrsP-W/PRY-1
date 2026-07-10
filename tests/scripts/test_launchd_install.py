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
PLIST_MENUBAR_PATH = PROJECT_ROOT / "launchd_plist" / "com.myaiemployee.menu-bar.plist"
PLIST_DASHBOARD_PATH = PROJECT_ROOT / "launchd_plist" / "com.myaiemployee.dashboard.plist"
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


def test_f4_install_sh_deploys_menu_bar_and_dashboard_runners_to_home_bin():
    """F4. 撞坑 #95 修复(2026-07-10):menu-bar + dashboard runner 必部署到 ~/bin,避免 launchd 执行 Documents 下的 sh."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    # 取代原 TARGET_START_RUNNER(digital-runner) — 现拆 2 独立 wrapper
    assert 'TARGET_MENUBAR_WRAPPER="${HOME_BIN}/my-ai-employee-menu-bar-runner"' in text
    assert 'TARGET_DASHBOARD_WRAPPER="${HOME_BIN}/my-ai-employee-dashboard-runner"' in text
    # 必 heredoc 写入(不 cp SOURCE_START_SH)
    assert 'cat << EOF > "${TARGET_MENUBAR_WRAPPER}"' in text
    assert 'cat << EOF > "${TARGET_DASHBOARD_WRAPPER}"' in text
    assert 'chmod +x "${TARGET_MENUBAR_WRAPPER}"' in text
    assert 'chmod +x "${TARGET_DASHBOARD_WRAPPER}"' in text
    # 禁原 launcher 父子链(已废弃)
    assert "TARGET_START_RUNNER" not in text, (
        "撞坑 #95 修复:install.sh 禁 TARGET_START_RUNNER launcher 变量(已拆 menu-bar + dashboard 独立)"
    )
    assert "my-ai-employee-digital-runner" not in text, (
        "撞坑 #95 修复:install.sh 禁部署 digital-runner launcher(已拆 2 独立 wrapper)"
    )


def test_f5_install_menu_bar_dashboard_wrappers_avoid_documents_ops_exec():
    """F5. 撞坑 #95 修复:menu-bar + dashboard wrapper 不得 exec 项目 Documents 目录下的 ops 脚本."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    # 禁原 launcher 形式
    forbidden = 'exec bash \\"${PROJECT_ROOT}/ops/start-digital-employee.sh\\" start'
    assert forbidden not in text
    # heredoc 必 export 3 个环境变量(撞坑 #92 修复 B 范本)
    assert 'export MY_AI_EMPLOYEE_PROJECT_ROOT="${PROJECT_ROOT}"' in text
    assert 'export MY_AI_EMPLOYEE_APP_SUPPORT_DIR="${APP_SUPPORT_DIR}"' in text
    assert 'export MY_AI_EMPLOYEE_ENV_FILE="${APP_SUPPORT_ENV}"' in text
    # 2 wrapper heredoc 必都含 env 导出
    menubar_block_start = text.index('cat << EOF > "${TARGET_MENUBAR_WRAPPER}"')
    menubar_block_end = text.index('chmod +x "${TARGET_MENUBAR_WRAPPER}"')
    menubar_block = text[menubar_block_start:menubar_block_end]
    assert "export MY_AI_EMPLOYEE_PROJECT_ROOT=" in menubar_block
    assert "scripts/run_menu_bar.py" in menubar_block, (
        "撞坑 #95 修复:menu-bar wrapper 必调 scripts/run_menu_bar.py(独立 wrapper)"
    )
    dashboard_block_start = text.index('cat << EOF > "${TARGET_DASHBOARD_WRAPPER}"')
    dashboard_block_end = text.index('chmod +x "${TARGET_DASHBOARD_WRAPPER}"')
    dashboard_block = text[dashboard_block_start:dashboard_block_end]
    assert "export MY_AI_EMPLOYEE_PROJECT_ROOT=" in dashboard_block
    assert "my_ai_employee.dashboard.server" in dashboard_block, (
        "撞坑 #95 修复:dashboard wrapper 必调 my_ai_employee.dashboard.server(独立 wrapper)"
    )


def test_f6_start_script_accepts_explicit_project_root_override():
    """F6. 被复制到 ~/bin 的 runner 必能用显式项目根路径定位资源(沿 P0-1 范本,适用于 ops/start-digital-employee.sh 仍存在 · 撞坑 #95 后退役)."""
    text = START_DIGITAL_EMPLOYEE_SH.read_text(encoding="utf-8")
    assert "MY_AI_EMPLOYEE_PROJECT_ROOT" in text
    assert 'PROJECT_ROOT="${MY_AI_EMPLOYEE_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"' in text


def test_f7_install_sh_supports_deploy_only_without_launchctl_load():
    """F7. deploy-only/no-load 必只部署文件,不进入 launchctl load 段(撞坑 #95 修复后 4 job)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "deploy-only | no-load)" in text
    assert "DEPLOY_ONLY=true" in text
    deploy_exit = text.index('if [[ "${DEPLOY_ONLY}" == "true" ]]')
    # 撞坑 #95 修复:launchctl load 段从 3 job → 4 job(menu-bar + dashboard 独立)
    load_section = text.index("# ===== 6. launchctl load(4 job")
    assert deploy_exit < load_section
    deploy_block = text[deploy_exit:load_section]
    assert "launchctl load -w" in deploy_block
    assert "exit 0" in deploy_block


def test_f8_install_sh_sets_up_app_support_dir_and_env_migration():
    """F8. 撞坑 #92 修复(2026-07-09):APP_SUPPORT_DIR 创建 + .env 自动迁移."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert 'APP_SUPPORT_DIR="${HOME}/Library/Application Support/MyAIEmployee"' in text
    assert 'APP_SUPPORT_ENV="${APP_SUPPORT_DIR}/.env"' in text
    # 创建 APP_SUPPORT_DIR 段
    assert 'mkdir -p "${APP_SUPPORT_DIR}"' in text
    # .env 迁移逻辑
    assert 'cp "${PROJECT_ROOT}/.env" "${APP_SUPPORT_ENV}"' in text
    assert 'if [[ -f "${PROJECT_ROOT}/.env" && ! -f "${APP_SUPPORT_ENV}" ]]' in text


def test_f9_install_start_wrapper_exports_app_support_env_explicit():
    """F9. 撞坑 #92 修复:digital-runner wrapper 显式 export APP_SUPPORT_DIR + ENV_FILE."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert 'export MY_AI_EMPLOYEE_APP_SUPPORT_DIR="${APP_SUPPORT_DIR}"' in text
    assert 'export MY_AI_EMPLOYEE_ENV_FILE="${APP_SUPPORT_ENV}"' in text


def test_f10_install_imap_wrapper_uses_app_support_env():
    """F10. 撞坑 #92 修复:IMAP wrapper ENV_FILE 必读 APP_SUPPORT_ENV 而非 PROJECT_ROOT/.env."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert 'ENV_FILE="${APP_SUPPORT_ENV}"' in text
    # 旧路径不应再出现(只允许作为迁移源)
    imap_block_start = text.index("📋 部署 ${TARGET_IMAP_SCRIPT}")
    imap_block_end = text.index("✅ ${TARGET_IMAP_SCRIPT} 部署完成")
    imap_block = text[imap_block_start:imap_block_end]
    assert 'ENV_FILE="${PROJECT_ROOT}/.env"' not in imap_block


def test_g1_start_digital_employee_uses_env_file_not_project_root():
    """G1. 撞坑 #92 修复:ops/start-digital-employee.sh 读 ENV_FILE 而非 PROJECT_ROOT/.env."""
    text = START_DIGITAL_EMPLOYEE_SH.read_text(encoding="utf-8")
    assert 'ENV_FILE="${MY_AI_EMPLOYEE_ENV_FILE:-$APP_SUPPORT_DIR/.env}"' in text
    # 禁止 PROJECT_ROOT/.env 直接 grep(只允许 ENV_FILE 引用)
    assert 'grep -E "^IMAP_USER=" "$PROJECT_ROOT/.env"' not in text
    assert 'grep -qE "^DB_ENCRYPTION_KEY=' in text  # 用 ENV_FILE 而非 PROJECT_ROOT/.env
    assert 'grep -qE "^DB_ENCRYPTION_KEY=[a-fA-F0-9]{64}$" "$ENV_FILE"' in text


def test_g2_start_digital_employee_uses_app_support_data_dir():
    """G2. 撞坑 #92 修复:ops/start-digital-employee.sh DATA_DIR/LOG_DIR 必用 APP_SUPPORT_DIR(非 PROJECT_ROOT/data)."""
    text = START_DIGITAL_EMPLOYEE_SH.read_text(encoding="utf-8")
    assert (
        'APP_SUPPORT_DIR="${MY_AI_EMPLOYEE_APP_SUPPORT_DIR:-$HOME/Library/Application Support/MyAIEmployee}"'
        in text
    )
    assert 'DATA_DIR="$APP_SUPPORT_DIR/data"' in text
    # 禁止 PROJECT_ROOT/data 直接引用
    assert 'DATA_DIR="$PROJECT_ROOT/data"' not in text
    assert 'LOG_DIR="$DATA_DIR/logs"' not in text  # 不再用链式 PROJECT_ROOT/data/logs
    # LOG_DIR 必用 ~/Library/Logs/MyAIEmployee
    assert 'LOG_DIR="${MY_AI_EMPLOYEE_LOG_DIR:-$HOME/Library/Logs/MyAIEmployee}"' in text


# ===== H. 撞坑 #93 修复 — uv 绝对路径(2026-07-09) =====


def test_h1_start_digital_employee_detects_uv_bin_with_fallback():
    """H1. 撞坑 #93 修复:ops/start-digital-employee.sh 必 UV_BIN 检测(command -v 优先 + 绝对路径 fallback)."""
    text = START_DIGITAL_EMPLOYEE_SH.read_text(encoding="utf-8")
    assert 'UV_BIN="$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)"' in text


def test_h2_start_digital_employee_uses_uv_bin_for_all_invocations():
    """H2. 撞坑 #93 修复:所有 uv run 调用必用 ${UV_BIN}(6 处:precheck alembic/dashboard + 2 real + 2 dry-run echo)."""
    text = START_DIGITAL_EMPLOYEE_SH.read_text(encoding="utf-8")
    # 移除注释后,不应出现裸的 `uv run`(必须 ${UV_BIN} run)
    # 排除注释里的描述性 `uv run`
    import re

    # 抽取非注释行
    code_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    code_text = "\n".join(code_lines)
    # 禁止裸 uv run(只能 ${UV_BIN} run)
    bare_uv_run = re.findall(r"(?<!\$\{UV_BIN\})\buv\s+run\b", code_text)
    assert not bare_uv_run, "撞坑 #93 修复:所有 uv run 必须 ${{UV_BIN}} run,发现裸调用 " + str(
        bare_uv_run
    )
    # 必有 6 处 ${UV_BIN} run(2 precheck + 2 real nohup + 2 dry-run echo)
    # 匹配两种形式:"${UV_BIN}" run(quoted)与 ${UV_BIN} run(unquoted in echo)
    uv_bin_count = len(re.findall(r"\$\{UV_BIN\}[\"']?\s+run\b", code_text))
    assert uv_bin_count >= 6, (
        "撞坑 #93 修复:${{UV_BIN}} run 应至少 6 处(precheck alembic/dashboard + menubar/dashboard nohup + 2 dry-run echo),实际 "
        + str(uv_bin_count)
    )


def test_h3_install_sh_monthly_report_wrapper_uses_absolute_uv_path():
    """H3. 撞坑 #93 修复:monthly-report wrapper 必用绝对路径 /opt/homebrew/bin/uv(launchd 子进程 PATH 不含 uv)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    monthly_block_start = text.index("📋 部署 ${TARGET_SCRIPT}(动态月份)")
    monthly_block_end = text.index("✅ ${TARGET_SCRIPT} 部署完成")
    monthly_block = text[monthly_block_start:monthly_block_end]
    assert "/opt/homebrew/bin/uv run --project" in monthly_block, (
        f"撞坑 #93 修复:monthly-report wrapper 必用绝对路径,实际 block:\n{monthly_block}"
    )


def test_h4_install_sh_imap_wrapper_uses_absolute_uv_path():
    """H4. 撞坑 #93 修复:imap-sync wrapper 必用绝对路径 /opt/homebrew/bin/uv."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    imap_block_start = text.index("📋 部署 ${TARGET_IMAP_SCRIPT}")
    imap_block_end = text.index("✅ ${TARGET_IMAP_SCRIPT} 部署完成")
    imap_block = text[imap_block_start:imap_block_end]
    assert "exec /opt/homebrew/bin/uv run --project" in imap_block, (
        f"撞坑 #93 修复:imap-sync wrapper 必用绝对路径,实际 block:\n{imap_block}"
    )


# ===== I. 撞坑 #96 修复 — IMAP wrapper 用绝对路径(2026-07-10) =====
# 历史沿革:
#   - 原实现 `python scripts/sync_imap.py` 相对路径 → launchd CWD=$HOME 解析为
#     /Users/wei/scripts/sync_imap.py(报错 No such file or directory)
#   - 第一次尝试 `python -m scripts.sync_imap` 模块形式 → Python sys.path 不含
#     ${PROJECT_ROOT},ModuleNotFoundError: No module named 'scripts'
#   - 最终方案:`python "${PROJECT_ROOT}/scripts/sync_imap.py"` 绝对路径,
#     与 uv --project 协同工作(uv 设 venv + 设 PYTHONPATH 含 ${PROJECT_ROOT}/src)
#     与 CWD 无关。已实测 launchd 上下文(env -i HOME=$HOME PATH=minimal)通过
#     干净测试:IMAP 拉取 14 封,0 failed,err.log 空


def test_i1_install_sh_imap_wrapper_uses_absolute_script_path():
    """I1. 撞坑 #96 修复:IMAP wrapper exec 行必用 ${PROJECT_ROOT}/scripts/sync_imap.py 绝对路径.

    取代原 `python scripts/sync_imap.py` 相对路径(launchd CWD=$HOME 解析错误)。
    也取代 `python -m scripts.sync_imap` 模块形式(Python sys.path 不含 PROJECT_ROOT)。
    """
    text = INSTALL_SH.read_text(encoding="utf-8")
    imap_block_start = text.index("📋 部署 ${TARGET_IMAP_SCRIPT}")
    imap_block_end = text.index("✅ ${TARGET_IMAP_SCRIPT} 部署完成")
    imap_block = text[imap_block_start:imap_block_end]
    # 必含绝对路径形式
    assert 'python "${PROJECT_ROOT}/scripts/sync_imap.py"' in imap_block, (
        f"撞坑 #96 修复:IMAP wrapper exec 行必用绝对路径 ${{PROJECT_ROOT}}/scripts/sync_imap.py,"
        f"实际 block:\n{imap_block}"
    )
    # 禁绝 exec 行的相对路径形式(注释行不在此列)
    exec_lines = [line for line in imap_block.splitlines() if line.strip().startswith("exec ")]
    assert exec_lines, "IMAP wrapper 必含至少 1 行 exec 起始的命令"
    for line in exec_lines:
        # 禁相对路径(无 PROJECT_ROOT 前缀 + scripts/sync_imap.py)
        assert "python scripts/sync_imap.py" not in line, (
            f"撞坑 #96 修复:exec 行禁止用相对路径 {line!r}"
        )
        # 禁 python -m 形式(sys.path 不含 PROJECT_ROOT)
        assert "python -m scripts.sync_imap" not in line, (
            f"撞坑 #96 修复:exec 行禁止用 python -m 形式(sys.path 不含 PROJECT_ROOT) {line!r}"
        )
        # 必含绝对路径
        assert "${PROJECT_ROOT}/scripts/sync_imap.py" in line, (
            f"撞坑 #96 修复:exec 行必用绝对路径 ${{PROJECT_ROOT}}/scripts/sync_imap.py {line!r}"
        )


def test_i2_install_sh_imap_wrapper_comment_documents_pitfall_96():
    """I2. 撞坑 #96 修复:IMAP wrapper heredoc 必含 #96 标记注释(防回归)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    imap_block_start = text.index("📋 部署 ${TARGET_IMAP_SCRIPT}")
    imap_block_end = text.index("✅ ${TARGET_IMAP_SCRIPT} 部署完成")
    imap_block = text[imap_block_start:imap_block_end]
    assert "撞坑 #96 修复" in imap_block, (
        f"撞坑 #96 修复:IMAP wrapper heredoc 必含 #96 注释(防回归),实际 block:\n{imap_block}"
    )
    # 必含 launchd CWD 根因解释
    assert "WorkingDirectory" in imap_block or "CWD" in imap_block, (
        f"撞坑 #96 修复:IMAP wrapper 注释必含 CWD/WorkingDirectory 根因解释,实际 block:\n{imap_block}"
    )


def test_i3_sync_imap_script_exists_at_absolute_path():
    """I3. 撞坑 #96 修复:scripts/sync_imap.py 必存在(绝对路径调用的前提)."""
    sync_imap = PROJECT_ROOT / "scripts" / "sync_imap.py"
    assert sync_imap.exists(), f"scripts/sync_imap.py 必存在: {sync_imap}"
    text = sync_imap.read_text(encoding="utf-8")
    # 必含 entry point(uv run 也会用)
    assert '__name__ == "__main__"' in text, (
        "scripts/sync_imap.py 必含 if __name__ == '__main__' 入口"
    )


def test_i4_deploy_only_imap_wrapper_also_uses_absolute_path():
    """I4. 撞坑 #96 修复:deploy-only / install 模式生成的 IMAP wrapper 都必用绝对路径.

    install.sh deploy-only 与 install 共用同一段 IMAP wrapper heredoc(行 240-258),
    本测试交叉确认 deploy-only 模式下生成的 wrapper 也用绝对路径。
    """
    text = INSTALL_SH.read_text(encoding="utf-8")
    # 全文只有一处 IMAP wrapper heredoc
    imap_block_start = text.index("📋 部署 ${TARGET_IMAP_SCRIPT}")
    imap_block_end = text.index("✅ ${TARGET_IMAP_SCRIPT} 部署完成")
    # 该段在 install flow 内(在 # ===== 6. launchctl load 之前 · 撞坑 #95 修复后 4 job)
    load_section_start = text.index("# ===== 6. launchctl load(4 job")
    deploy_only_check = text.index('if [[ "${DEPLOY_ONLY}" == "true" ]]')
    # imap_block 必在 load_section 之前(沿 deploy-only 退出前)
    assert imap_block_start < load_section_start
    # imap_block 必在 deploy_only 检查之前(但 deploy_only 检查之后 wrapper 已部署好)
    assert imap_block_end < deploy_only_check, (
        f"撞坑 #96 修复:deploy-only 必须在 IMAP wrapper 部署之后才能退出,"
        f"imap_block_end={imap_block_end} 但 deploy_only_check={deploy_only_check}"
    )


# ===== J. 撞坑 #95 修复 — menu-bar + Dashboard 拆 2 个独立 LaunchAgent(2026-07-10) =====
# 根因:原 com.myaiemployee.digital-employee.plist 父子进程 + ProcessType=Background
#   - launcher (start-digital-employee.sh) 启动 menubar + dashboard 子进程
#   - 子进程成孤儿,launchd 50s 内强制 kill
# 修复:拆 2 个独立 LaunchAgent
#   - com.myaiemployee.menu-bar.plist (ProcessType=Standard, KeepAlive=true)
#   - com.myaiemployee.dashboard.plist (ProcessType=Standard, KeepAlive=true, DASHBOARD_PORT=8765)
#   - 各自独立 wrapper 调对应服务(menubar→run_menu_bar.py / dashboard→dashboard.server)
# 验证维度:
#   J1:2 plist 必存 + ProcessType=Standard(禁 Background)+ KeepAlive=true
#   J2:2 plist 都用 $USER 占位符 + 独立 wrapper 路径
#   J3:install.sh deploy-only 部署 2 独立 wrapper + 2 独立 plist,删 digital-employee launcher
#   J4:install.sh install 模式 4 job launchctl load(agent + imap-sync + menu-bar + dashboard)


def test_j1_menu_bar_plist_process_type_standard_keepalive():
    """J1a. 撞坑 #95 修复:menu-bar plist 必用 ProcessType=Standard(非 Background)+ KeepAlive=true."""
    assert PLIST_MENUBAR_PATH.exists(), f"menu-bar plist 必存: {PLIST_MENUBAR_PATH}"
    text = PLIST_MENUBAR_PATH.read_text(encoding="utf-8")
    # 必含 ProcessType=Standard(禁 Background)
    assert "<string>Standard</string>" in text, (
        f"撞坑 #95 修复:menu-bar plist 必用 ProcessType=Standard,实际:\n{text}"
    )
    assert "<string>Background</string>" not in text, (
        f"撞坑 #95 修复:menu-bar plist 禁 ProcessType=Background(50s 强制回收),实际:\n{text}"
    )
    # 必含 KeepAlive=true(崩了自动重启,user 可分别 launchctl unload)
    assert "<key>KeepAlive</key>" in text and "<true/>" in text, (
        f"撞坑 #95 修复:menu-bar plist 必含 KeepAlive=true,实际:\n{text}"
    )


def test_j1b_dashboard_plist_process_type_standard_keepalive():
    """J1b. 撞坑 #95 修复:dashboard plist 必用 ProcessType=Standard + KeepAlive=true + DASHBOARD_PORT=8765."""
    assert PLIST_DASHBOARD_PATH.exists(), f"dashboard plist 必存: {PLIST_DASHBOARD_PATH}"
    text = PLIST_DASHBOARD_PATH.read_text(encoding="utf-8")
    # 必含 ProcessType=Standard
    assert "<string>Standard</string>" in text, (
        f"撞坑 #95 修复:dashboard plist 必用 ProcessType=Standard,实际:\n{text}"
    )
    assert "<string>Background</string>" not in text, (
        f"撞坑 #95 修复:dashboard plist 禁 ProcessType=Background,实际:\n{text}"
    )
    # 必含 KeepAlive=true
    assert "<key>KeepAlive</key>" in text and "<true/>" in text, (
        f"撞坑 #95 修复:dashboard plist 必含 KeepAlive=true,实际:\n{text}"
    )
    # Dashboard 特有:DASHBOARD_PORT=8765(127.0.0.1 默认)
    assert "<key>DASHBOARD_PORT</key>" in text and "8765" in text, (
        f"撞坑 #95 修复:dashboard plist 必含 DASHBOARD_PORT=8765,实际:\n{text}"
    )
    assert "<key>DASHBOARD_REAL_DB</key>" in text and "<string>1</string>" in text, (
        f"撞坑 #95 修复:dashboard plist 必含 DASHBOARD_REAL_DB=1,实际:\n{text}"
    )


def test_j2_menu_bar_plist_uses_user_placeholder_and_independent_wrapper():
    """J2a. 撞坑 #95 修复:menu-bar plist 必用 $USER 占位符 + 独立 ~/bin wrapper 路径."""
    text = PLIST_MENUBAR_PATH.read_text(encoding="utf-8")
    # 必用 $USER 占位符(沿 imap-sync 范本,install.sh sed 替换)
    assert "$USER" in text, (
        f"撞坑 #95 修复:menu-bar plist 必用 $USER 占位符(沿 imap-sync 范本),实际:\n{text}"
    )
    # 必指独立 wrapper(非 launcher 父子链)
    assert "/Users/$USER/bin/my-ai-employee-menu-bar-runner" in text, (
        f"撞坑 #95 修复:menu-bar plist 必指 ~/bin/my-ai-employee-menu-bar-runner,实际:\n{text}"
    )
    # 禁指 launcher(撞坑 #95 根因)
    assert "my-ai-employee-start" not in text, (
        f"撞坑 #95 修复:menu-bar plist 禁指 launcher(my-ai-employee-start),实际:\n{text}"
    )
    assert "my-ai-employee-digital-runner" not in text, (
        f"撞坑 #95 修复:menu-bar plist 禁指 digital-runner(launcher),实际:\n{text}"
    )


def test_j2b_dashboard_plist_uses_user_placeholder_and_independent_wrapper():
    """J2b. 撞坑 #95 修复:dashboard plist 必用 $USER 占位符 + 独立 ~/bin wrapper 路径."""
    text = PLIST_DASHBOARD_PATH.read_text(encoding="utf-8")
    assert "$USER" in text, f"撞坑 #95 修复:dashboard plist 必用 $USER 占位符,实际:\n{text}"
    assert "/Users/$USER/bin/my-ai-employee-dashboard-runner" in text, (
        f"撞坑 #95 修复:dashboard plist 必指 ~/bin/my-ai-employee-dashboard-runner,实际:\n{text}"
    )
    assert "my-ai-employee-start" not in text, (
        f"撞坑 #95 修复:dashboard plist 禁指 launcher,实际:\n{text}"
    )
    assert "my-ai-employee-digital-runner" not in text, (
        f"撞坑 #95 修复:dashboard plist 禁指 digital-runner,实际:\n{text}"
    )


def test_j3_install_sh_uses_independent_menu_bar_and_dashboard_wrappers():
    """J3. 撞坑 #95 修复:install.sh 必部署 2 独立 wrapper(menu-bar + dashboard),删 launcher 父子链."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    # 必部署 menu-bar 独立 wrapper heredoc
    assert "my-ai-employee-menu-bar-runner" in text, (
        "撞坑 #95 修复:install.sh 必部署 ~/bin/my-ai-employee-menu-bar-runner 独立 wrapper"
    )
    assert "my-ai-employee-dashboard-runner" in text, (
        "撞坑 #95 修复:install.sh 必部署 ~/bin/my-ai-employee-dashboard-runner 独立 wrapper"
    )
    # 必含 #95 修复注释(防回退)
    assert "撞坑 #95 修复" in text, "撞坑 #95 修复:install.sh 必含 #95 注释(防回归)"
    # 删原 launcher 父子链
    assert "TARGET_START_SCRIPT" not in text, (
        "撞坑 #95 修复:install.sh 禁 TARGET_START_SCRIPT 父子链变量(已拆 menu-bar + dashboard 独立)"
    )
    assert "TARGET_START_RUNNER" not in text, (
        "撞坑 #95 修复:install.sh 禁 TARGET_START_RUNNER launcher 变量"
    )
    assert "SOURCE_PLIST_START" not in text, (
        "撞坑 #95 修复:install.sh 禁 SOURCE_PLIST_START digital-employee 源 plist 变量"
    )
    # 必含 4 job LAUNCHD_LABELS(取代 3 job)
    assert '"com.myaiemployee.menu-bar"' in text, (
        "撞坑 #95 修复:install.sh LAUNCHD_LABELS 必含 com.myaiemployee.menu-bar"
    )
    assert '"com.myaiemployee.dashboard"' in text, (
        "撞坑 #95 修复:install.sh LAUNCHD_LABELS 必含 com.myaiemployee.dashboard"
    )


def test_j4_install_sh_deploy_only_loads_4_jobs():
    """J4. 撞坑 #95 修复:install.sh deploy-only 部署 4 plist + install 模式 launchctl load 4 job."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    # 4 plist 必都被 install.sh 部署(deploy-only 模式输出含 menu-bar + dashboard plist 路径)
    assert "TARGET_PLIST_MENUBAR" in text, (
        "撞坑 #95 修复:install.sh 必含 TARGET_PLIST_MENUBAR 部署目标"
    )
    assert "TARGET_PLIST_DASHBOARD" in text, (
        "撞坑 #95 修复:install.sh 必含 TARGET_PLIST_DASHBOARD 部署目标"
    )
    # 4 wrapper 必都被 install.sh 部署
    assert "TARGET_MENUBAR_WRAPPER" in text, (
        "撞坑 #95 修复:install.sh 必含 TARGET_MENUBAR_WRAPPER 部署目标"
    )
    assert "TARGET_DASHBOARD_WRAPPER" in text, (
        "撞坑 #95 修复:install.sh 必含 TARGET_DASHBOARD_WRAPPER 部署目标"
    )
    # launchctl load 段必含 menu-bar + dashboard plist
    load_section_start = text.index("# ===== 6. launchctl load")
    load_section_end = text.index("# ===== 7. 5 源验证")
    load_section = text[load_section_start:load_section_end]
    assert "TARGET_PLIST_MENUBAR" in load_section, (
        "撞坑 #95 修复:launchctl load 段必加载 menu-bar plist"
    )
    assert "TARGET_PLIST_DASHBOARD" in load_section, (
        "撞坑 #95 修复:launchctl load 段必加载 dashboard plist"
    )
