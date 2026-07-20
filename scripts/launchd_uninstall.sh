#!/usr/bin/env bash
# D10.3 / Day 14 — standalone launchd 卸载脚本
#
# 退出码(沿 D5.6.5 范本):
#   0 = 成功卸载
#   1 = 所有受管 job 均未注册且 plist 均不存在(已卸载)
#   3 = launchctl 无法卸载 / bootout，或最终仍有受管 job 注册

set -euo pipefail

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
HOME_BIN="${HOME}/bin"

# Day 14 撞坑 #95 后，菜单栏与 Dashboard 已拆为独立 LaunchAgent；
# legacy digital-employee 仍须在独立卸载入口中退役，避免 standalone 脚本
# 因 agent plist 缺失而提前返回、遗留常驻进程。
LAUNCHD_LABELS=(
    "com.myaiemployee.agent"
    "com.myaiemployee.imap-sync"
    "com.myaiemployee.menu-bar"
    "com.myaiemployee.dashboard"
    "com.myaiemployee.health-monitor"
    "com.myaiemployee.news-refresh"
    "com.myaiemployee.digital-employee"
)
TARGET_WRAPPERS=(
    "${HOME_BIN}/my-ai-employee-monthly-report"
    "${HOME_BIN}/my-ai-employee-imap-sync"
    "${HOME_BIN}/my-ai-employee-menu-bar-runner"
    "${HOME_BIN}/my-ai-employee-dashboard-runner"
    "${HOME_BIN}/my-ai-employee-health-monitor-runner"
    "${HOME_BIN}/my-ai-employee-news-refresh-runner"
    "${HOME_BIN}/my-ai-employee-start"
)

launchctl_list_has_label() {
    local expected_label="$1"
    local list_output="$2"
    awk -v label="${expected_label}" '$NF == label { found = 1; exit } END { exit !found }' "${list_output}"
}

LAUNCHCTL_LIST="$(mktemp -t myaiemployee_launchd_uninstall.XXXXXX)"
trap 'rm -f "${LAUNCHCTL_LIST}"' EXIT

refresh_launchctl_list() {
    if ! launchctl list > "${LAUNCHCTL_LIST}" 2>/dev/null; then
        echo "❌ launchctl list 失败" >&2
        exit 3
    fi
}

had_managed_state=false
refresh_launchctl_list

# ===== 1. 卸载所有当前与 legacy label =====
for label in "${LAUNCHD_LABELS[@]}"; do
    target_plist="${LAUNCH_AGENTS_DIR}/${label}.plist"
    if [[ -f "${target_plist}" || -L "${target_plist}" ]]; then
        had_managed_state=true
        echo "🛑 launchctl unload ${target_plist}"
        if ! launchctl unload "${target_plist}" 2>/dev/null; then
            echo "⚠️  launchctl unload 失败，尝试 bootout ${label}" >&2
        fi
    else
        echo "ℹ️  plist 不存在，跳过: ${target_plist}"
    fi

    refresh_launchctl_list
    if launchctl_list_has_label "${label}" "${LAUNCHCTL_LIST}"; then
        had_managed_state=true
        echo "🛑 launchctl bootout gui/$(id -u)/${label}"
        if ! launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null; then
            echo "❌ launchctl 无法退役 ${label}" >&2
            exit 3
        fi
        refresh_launchctl_list
        if launchctl_list_has_label "${label}" "${LAUNCHCTL_LIST}"; then
            echo "❌ launchctl bootout 后仍见 ${label}，保留 plist 以便恢复" >&2
            exit 3
        fi
    fi

    # 仅在 launchctl list 已确认 label 不再注册后删除 plist；若 unload 与
    # bootout 都失败，前面的 exit 3 会保留该文件，供人工恢复或重试。
    if [[ -f "${target_plist}" || -L "${target_plist}" ]]; then
        rm -f "${target_plist}"
        echo "🗑️  已删除 ${target_plist}"
    fi
done

# ===== 2. 精确验证所有受管 label 已退役 =====
refresh_launchctl_list
for label in "${LAUNCHD_LABELS[@]}"; do
    if launchctl_list_has_label "${label}" "${LAUNCHCTL_LIST}"; then
        echo "❌ 验证失败：launchctl list 仍见 ${label}" >&2
        exit 3
    fi
done

already_uninstalled=false
if [[ "${had_managed_state}" != true ]]; then
    already_uninstalled=true
fi

# ===== 3. 删除 ~/bin/ wrapper(可选，默认保留) =====
if [[ "${1:-}" == "--purge-bin" ]]; then
    for target_wrapper in "${TARGET_WRAPPERS[@]}"; do
        if [[ -f "${target_wrapper}" || -L "${target_wrapper}" ]]; then
            rm -f "${target_wrapper}"
            echo "🗑️  已删除 ${target_wrapper}(--purge-bin)"
        fi
    done
elif [[ "${already_uninstalled}" != true ]]; then
    echo "ℹ️  保留 ${#TARGET_WRAPPERS[@]} 个 ~/bin/ wrapper(用 --purge-bin 删除)"
fi

if [[ "${already_uninstalled}" == true ]]; then
    echo "ℹ️  所有受管 plist 均不存在且 job 未注册，已卸载"
    exit 1
fi

echo ""
echo "🎉 launchd 卸载完成!"
