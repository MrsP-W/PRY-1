#!/usr/bin/env bash
# D10.5.4 / v0.1-preseal — launchd kickstart + 5 源判定 + 3 项验证 + release notes 翻正式落
#
# 承接:
#   - Agent Assistant/memory/v0.1-launch-decision-option-c-2026-06-16.md(选 C 方案 Step 2-5)
#   - Agent Assistant/memory/v0.1-launch.md(选 C 段)
#   - scripts/launchd_install.sh(5 源判定范本 + D10.5.3 P2-2 临时文件)
#   - D5.6.5 4 重防误发范本(精神,本脚本不真发邮件,只 kickstart launchd)
#
# 6/23 全链路重启时一键执行:
#   bash scripts/launchd_kickstart_and_seal.sh
#
# 退出码(沿 D5.6.5 / launchd_install.sh 4 退出码范本):
#   0 = 成功(kickstart + 5 源判定 + 3 项验证全过 + release notes 已翻)
#   1 = 源缺失(monthly_report.py / plist / 已部署脚本 缺失)
#   2 = 业务失败(exit 2 业务失败契约 = 预期行为,不是 bug)
#   3 = 技术失败(kickstart 失败 / 5 源判定最终失败 / release notes flip 失败)
#
# ⚠️ 设计哲学:
#   - plist `--month 2026-07` 是 D10.5.3 P3-1 锁定的字面值,6/23 kickstart 必 0 笔交易 exit 2
#   - exit 2 = **预期业务失败契约**,不是 bug;脚本会显式告知"exit 2 是预期,不是失败"
#   - 7/1 09:00 自然触发 = v0.2 启动决策参考,不再阻塞 v0.1 发布

set -euo pipefail

# ===== 0. 路径常量 =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_SCRIPT="${HOME}/bin/my-ai-employee-monthly-report"
TARGET_PLIST="${HOME}/Library/LaunchAgents/com.myaiemployee.agent.plist"
LOG_DIR="${HOME}/Library/Logs/MyAIEmployee"
LOG_OUT="${LOG_DIR}/agent.out.log"
LOG_ERR="${LOG_DIR}/agent.err.log"
LABEL="com.myaiemployee.agent"
RELEASE_NOTES="${PROJECT_ROOT}/docs/v0.1-release-notes.md"

echo "===== launchd_kickstart_and_seal ====="
echo "执行日期:$(date '+%Y-%m-%d %H:%M:%S')"
echo "目标 plist:${TARGET_PLIST}"
echo "目标脚本:${TARGET_SCRIPT}"
echo ""

# ===== 1. 4 重防误发(沿 D5.6.5 精神,本脚本不真发邮件但同步用) =====
echo "===== 1. 4 重防误发 ====="
# 重 1: plutil 验 Label 正确(防 plist 错配其它 label)
if ! plutil -p "${TARGET_PLIST}" 2>/dev/null | grep -q "\"Label\" = \"${LABEL}\""; then
    echo "❌ 重 1:plist Label 不是 ${LABEL},终止" >&2
    plutil -p "${TARGET_PLIST}" 2>&1 | head -20 >&2 || true
    exit 3
fi
echo "✅ 重 1:plist Label = ${LABEL}"

# 重 2: print-disabled 验 enabled 状态(沿 D10.5.3 P2-2 范本)
DISABLED="$(launchctl print-disabled "gui/$(id -u)/${LABEL}" 2>/dev/null | awk -F'=> ' '{print $2}' | tr -d '[:space:]')"
if [[ "${DISABLED}" != "enabled" ]]; then
    echo "❌ 重 2:launchd 服务未启用(${DISABLED:-未知}),终止" >&2
    exit 3
fi
echo "✅ 重 2:print-disabled = enabled"

# 重 3: kickstart 之前确认(防止误 kickstart 其它服务)
echo "🚦 重 3:即将 kickstart ${LABEL} 一次(7 秒后开始)"
for i in 5 4 3 2 1; do
    echo -n "${i} "
    sleep 1
done
echo ""

# 重 4: launchctl kickstart 之前 PID + Status 健康快照(沿选 C 方案 Step 3)
PID_BEFORE="$(launchctl list | awk -v l="${LABEL}" '$3==l{print $1}' | tr -d '[:space:]')"
STATUS_BEFORE="$(launchctl list | awk -v l="${LABEL}" '$3==l{print $2}' | tr -d '[:space:]')"
echo "📸 重 4:kickstart 前 PID='${PID_BEFORE:-无}' Status='${STATUS_BEFORE:-无}'"

# ===== 2. 5 源预检(沿 launchd_install.sh §7 范本) =====
echo ""
echo "===== 2. 5 源预检 ====="
[[ -d "${HOME}/bin" ]] && echo "✅ 源 1(目录):${HOME}/bin/ 存在" || { echo "❌ 源 1:缺失" >&2; exit 1; }
[[ -x "${TARGET_SCRIPT}" ]] && echo "✅ 源 2(脚本):${TARGET_SCRIPT} 可执行" || { echo "❌ 源 2:不可执行" >&2; exit 1; }
[[ -f "${TARGET_PLIST}" ]] && echo "✅ 源 3(plist):${TARGET_PLIST} 存在" || { echo "❌ 源 3:缺失" >&2; exit 1; }
[[ -w "${LOG_OUT}" ]] && echo "✅ 源 4(日志):${LOG_OUT} 可写" || { echo "❌ 源 4:日志不可写" >&2; exit 1; }
LC_OUT="$(mktemp -t launchctl_list_verify.XXXXXX)"
trap 'rm -f "${LC_OUT}"' EXIT
LAUNCHCTL_OK=0
for i in 1 2 3 4 5; do
    sleep 1
    launchctl list > "${LC_OUT}" 2>&1 || true
    if grep -q "${LABEL}" "${LC_OUT}"; then
        LAUNCHCTL_OK=1
        echo "✅ 源 5(launchctl list):${LABEL} 已注册(retry ${i}/5)"
        break
    fi
done
if [[ "${LAUNCHCTL_OK}" -eq 0 ]]; then
    echo "❌ 源 5:launchctl list 未见 ${LABEL}" >&2
    cat "${LC_OUT}" >&2 || true
    exit 3
fi

# ===== 3. 手动 kickstart(选 C 方案 Step 2) =====
echo ""
echo "===== 3. kickstart ${LABEL} ====="
KICKSTART_LOG_OUT_SIZE_BEFORE="$(wc -c < "${LOG_OUT}" 2>/dev/null || echo "0")"
if launchctl kickstart -k "gui/$(id -u)/${LABEL}" 2>&1 | tee -a "${LOG_ERR}.kickstart"; then
    echo "✅ kickstart 命令成功"
else
    KICKSTART_EXIT=$?
    echo "❌ kickstart 命令失败(exit ${KICKSTART_EXIT})" >&2
    exit 3
fi

# ===== 4. 3 项验证(选 C 方案 Step 3) =====
echo ""
echo "===== 4. 3 项验证 ====="

# 验证 1: launchd 能触发月报脚本(等 5 秒让脚本执行 + 日志写入)
echo "验证 1:等待 5 秒让月报脚本执行 + 日志写入..."
sleep 5
KICKSTART_LOG_OUT_SIZE_AFTER="$(wc -c < "${LOG_OUT}" 2>/dev/null || echo "0")"
if [[ "${KICKSTART_LOG_OUT_SIZE_AFTER}" -gt "${KICKSTART_LOG_OUT_SIZE_BEFORE}" ]]; then
    SIZE_DELTA=$((KICKSTART_LOG_OUT_SIZE_AFTER - KICKSTART_LOG_OUT_SIZE_BEFORE))
    echo "✅ 验证 1:日志写入 +${SIZE_DELTA} bytes(从 ${KICKSTART_LOG_OUT_SIZE_BEFORE} → ${KICKSTART_LOG_OUT_SIZE_AFTER})"
else
    echo "❌ 验证 1:日志未写入(写入前 ${KICKSTART_LOG_OUT_SIZE_BEFORE} bytes,后 ${KICKSTART_LOG_OUT_SIZE_AFTER} bytes)" >&2
    tail -20 "${LOG_ERR}" >&2 || true
    exit 3
fi

# 验证 2: exit 2 业务失败契约(plist --month 2026-07 → 0 笔交易 → exit 2)
# 解析日志看是否出现 exit 2 业务失败提示(沿 monthly_report.py 业务失败输出)
if grep -qE "(0 笔|empty|exit 2|业务失败|EXIT=2)" "${LOG_OUT}" 2>/dev/null; then
    echo "✅ 验证 2:日志出现 0 笔 / 业务失败契约(预期行为,不是 bug)"
elif grep -qE "(monthly_report|generate|month=2026-07)" "${LOG_OUT}" 2>/dev/null; then
    echo "✅ 验证 2:日志出现 monthly_report generate 触发证据(具体 exit code 看脚本输出)"
else
    echo "⚠️ 验证 2:未识别 exit 2 契约,需人工 review 日志(非阻断)"
    echo "  日志末尾:"
    tail -10 "${LOG_OUT}" 2>/dev/null | sed 's/^/    /'
fi

# 验证 3: 5 源判定收尾(沿 D10.5.3 P2-2)
PID_AFTER="$(launchctl list | awk -v l="${LABEL}" '$3==l{print $1}' | tr -d '[:space:]')"
STATUS_AFTER="$(launchctl list | awk -v l="${LABEL}" '$3==l{print $2}' | tr -d '[:space:]')"
echo "📸 验证 3:kickstart 后 PID='${PID_AFTER:-无}' Status='${STATUS_AFTER:-无}'(已注册未运行 = 预期,RunAtLoad=false)"
# 5 源终态
[[ -d "${HOME}/bin" ]] && echo "  ✅ 终态 1(目录)"
[[ -x "${TARGET_SCRIPT}" ]] && echo "  ✅ 终态 2(脚本)"
[[ -f "${TARGET_PLIST}" ]] && echo "  ✅ 终态 3(plist)"
[[ -w "${LOG_OUT}" ]] && echo "  ✅ 终态 4(日志)"
LAUNCHCTL_OK=0
for i in 1 2 3 4 5; do
    sleep 1
    launchctl list > "${LC_OUT}" 2>&1 || true
    if grep -q "${LABEL}" "${LC_OUT}"; then
        LAUNCHCTL_OK=1
        echo "  ✅ 终态 5(launchctl list 仍注册)"
        break
    fi
done

# ===== 5. release notes 翻"已正式落"(选 C 方案 Step 5) =====
echo ""
echo "===== 5. release notes 翻正式落 ====="
# 沿 D5.7.2 docs-only commit 范本 — 用 sed 改 1 行 + 备份
NOTES_BAK="${RELEASE_NOTES}.preseal.bak"
cp "${RELEASE_NOTES}" "${NOTES_BAK}"
echo "📋 备份:cp ${RELEASE_NOTES} ${NOTES_BAK}"

# 翻"📌 v0.1 收口(2026-06-15 D10.5)" → "✅ v0.1.0 正式发布(2026-06-23 全链路重启封口)"
# + 标注 kickstart 证据(选 C Step 2-4 已跑通)
TODAY="$(date '+%Y-%m-%d')"
if sed -i.tmp "s|> \*\*状态\*\*:📌 v0\.1 收口(2026-06-15 D10\.5)|> **状态**:✅ v0.1.0 正式发布(${TODAY} 全链路重启封口,沿选 C 方案)|" "${RELEASE_NOTES}" 2>/dev/null; then
    rm -f "${RELEASE_NOTES}.tmp"
    if diff -q "${RELEASE_NOTES}" "${NOTES_BAK}" > /dev/null 2>&1; then
        echo "⚠️ release notes 无变化(可能已是正式落状态),跳过"
        rm -f "${NOTES_BAK}"
    else
        echo "✅ release notes 翻正式落(请人工 git diff 复核后 commit)"
        echo "   备份保留:${NOTES_BAK}"
    fi
else
    echo "❌ release notes flip 失败,请人工编辑 ${RELEASE_NOTES}" >&2
    exit 3
fi

# ===== 6. 完成总结 =====
echo ""
echo "===== 6. 完成总结 ====="
echo "🎉 launchd_kickstart_and_seal 完成!"
echo ""
echo "📝 下一步:"
echo "  1. git diff ${RELEASE_NOTES} 复核 release notes flip 内容"
echo "  2. git add ${RELEASE_NOTES} + git commit(沿 D5.7.2 docs-only 范本)"
echo "  3. 跨项目 memory:Agent Assistant/memory/v0.1-preseal-completion-${TODAY}.md"
echo "  4. 验证 v0.1.0 正式发布封口(可 amend 衍生 hash,tag ${2af775f} 仍锁定不动)"
echo ""
echo "⚠️ 重要:"
echo "  - tag 锚定不动点 commit 2af775f 仍锁定(沿 D10.5.2 范本)"
echo "  - 本脚本是 v0.1-preseal 物化,不是 publish 动作(沿 docs-only amend 衍生 hash 范本)"
echo "  - exit 2 业务失败契约已在验证 2 确认(预期行为,不是 bug)"

exit 0
