#!/usr/bin/env bash
# D10.3 — launchd 卸载脚本
#
# 退出码(沿 D5.6.5 范本):
#   0 = 成功卸载
#   1 = plist 不存在(已卸载)
#   3 = launchctl unload 失败

set -euo pipefail

LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/com.myaiemployee.agent.plist"
HOME_BIN="${HOME}/bin"
TARGET_SCRIPT="${HOME_BIN}/my-ai-employee-monthly-report"

# ===== 1. plist 存在性 =====
if [[ ! -f "${TARGET_PLIST}" ]]; then
    echo "ℹ️  plist 不存在(${TARGET_PLIST}),已卸载"
    exit 1
fi

# ===== 2. launchctl unload =====
echo "🛑 launchctl unload ${TARGET_PLIST}"
if ! launchctl unload "${TARGET_PLIST}" 2>/dev/null; then
    echo "❌ launchctl unload 失败" >&2
    exit 3
fi
echo "✅ launchctl unload 完成"

# ===== 3. 删除 plist =====
rm -f "${TARGET_PLIST}"
echo "🗑️  已删除 ${TARGET_PLIST}"

# ===== 4. 删除 ~/bin/ 脚本(可选,默认保留) =====
if [[ "${1:-}" == "--purge-bin" ]]; then
    if [[ -f "${TARGET_SCRIPT}" ]]; then
        rm -f "${TARGET_SCRIPT}"
        echo "🗑️  已删除 ${TARGET_SCRIPT}(--purge-bin)"
    fi
else
    echo "ℹ️  保留 ${TARGET_SCRIPT}(用 --purge-bin 删)"
fi

echo ""
echo "🎉 launchd 卸载完成!"
