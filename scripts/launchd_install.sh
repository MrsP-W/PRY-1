#!/usr/bin/env bash
# D10.3 / D10.5.3 — launchd 部署脚本(数字生活月报保活)
#
# 承接 docs/v0.1-launch-plan.md:170-176 + docs/week2-mvp.md:245-256 D10 任务
# + v0.1-launch.md 沿 D5.6 代理故障排查 memory ~/bin/ 部署范本
#
# 5 源判定(沿 Agent Assistant scripts/proxy_health.sh 范本):
#   1. 目录:~/bin/ 存在性 + 可写
#   2. 脚本源:scripts/monthly_report.py 必存在
#   3. plist:launchd_plist/com.myaiemployee.agent.plist 必存在
#   4. 目标位置:~/Library/LaunchAgents/com.myaiemployee.agent.plist 必可写
#   5. launchctl:launchctl list 必见 com.myaiemployee.agent(macOS 必现)
#
# 使用方式(2026-06-15 D10.5.3 新增 install/uninstall 双模式):
#   bash scripts/launchd_install.sh install    # 部署 + launchctl load
#   bash scripts/launchd_install.sh uninstall  # 清理:unload + 删 plist + 删脚本 + 删日志
#   bash scripts/launchd_install.sh            # 默认 install(向后兼容)
#
# 部署步骤(install 模式):
#   1. ~/bin/ 不存在 → 创建
#   2. 复制 monthly_report.py → ~/bin/my-ai-employee-monthly-report
#   3. 复制 plist → ~/Library/LaunchAgents/com.myaiemployee.agent.plist
#   4. launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.agent.plist
#   5. 验证:launchctl list | grep myaiemployee(sleep 1 + retry 缓解 cache race)
#
# 清理步骤(uninstall 模式,2026-06-15 D10.5.3 新增,沿 Spike A 手动 cleanup 范本):
#   1. launchctl unload ~/Library/LaunchAgents/com.myaiemployee.agent.plist
#   2. rm -f ~/Library/LaunchAgents/com.myaiemployee.agent.plist
#   3. rm -f ~/bin/my-ai-employee-monthly-report
#   4. rm -rf ~/Library/Logs/MyAIEmployee/
#   5. 验证:launchctl list | grep myaiemployee 应为空(无残留)
#
# 退出码(沿 D5.6.5 范本):
#   0 = 成功(install 完成 / uninstall 无残留)
#   1 = 源缺失(monthly_report.py / plist 缺失) / 模式参数错误
#   2 = 目标位置不可写(~/bin/ 或 ~/Library/LaunchAgents/)
#   3 = launchctl load / unload 失败 / 5 源验证最终失败

set -euo pipefail

# ===== 0. 模式分发(2026-06-15 D10.5.3 新增) =====
MODE="${1:-install}"
case "${MODE}" in
    install)
        : # 继续走 install 流程(向后兼容)
        ;;
    uninstall)
        # 跳到 uninstall 段
        MODE_TAG="uninstall"
        ;;
    *)
        echo "❌ 未知模式: ${MODE}(只支持 install / uninstall)" >&2
        echo "用法: bash $0 [install|uninstall]" >&2
        exit 1
        ;;
esac

# ===== 0. 路径定位 =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_SCRIPT="${PROJECT_ROOT}/scripts/monthly_report.py"
SOURCE_PLIST="${PROJECT_ROOT}/launchd_plist/com.myaiemployee.agent.plist"
SOURCE_PLIST_IMAP="${PROJECT_ROOT}/launchd_plist/com.myaiemployee.imap-sync.plist"
SOURCE_PLIST_START="${PROJECT_ROOT}/launchd_plist/com.myaiemployee.digital-employee.plist"
SOURCE_SYNC_IMAP="${PROJECT_ROOT}/scripts/sync_imap.py"
SOURCE_START_SH="${PROJECT_ROOT}/ops/start-digital-employee.sh"

HOME_BIN="${HOME}/bin"
TARGET_SCRIPT="${HOME_BIN}/my-ai-employee-monthly-report"
TARGET_IMAP_SCRIPT="${HOME_BIN}/my-ai-employee-imap-sync"
TARGET_START_SCRIPT="${HOME_BIN}/my-ai-employee-start"
TARGET_START_RUNNER="${HOME_BIN}/my-ai-employee-digital-runner"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/com.myaiemployee.agent.plist"
TARGET_PLIST_IMAP="${LAUNCH_AGENTS_DIR}/com.myaiemployee.imap-sync.plist"
TARGET_PLIST_START="${LAUNCH_AGENTS_DIR}/com.myaiemployee.digital-employee.plist"
LOG_DIR="${HOME}/Library/Logs/MyAIEmployee"

# Day 2: 全部 launchd job label(月报 / IMAP 每日同步 / 数字员工开机自启)
LAUNCHD_LABELS=(
    "com.myaiemployee.agent"
    "com.myaiemployee.imap-sync"
    "com.myaiemployee.digital-employee"
)

# ===== uninstall 流程(2026-06-15 D10.5.3 新增,沿 Spike A 手动 cleanup 4 步范本) =====
if [[ "${MODE}" == "uninstall" ]]; then
    echo "===== uninstall 流程 ====="
    # 1. launchctl unload(3 job)
    LC_OUT_UNINSTALL="$(mktemp -t launchctl_list_uninstall.XXXXXX)"
    trap 'rm -f "${LC_OUT_UNINSTALL:-}" "${LC_OUT_LOAD:-}" "${LC_OUT:-}"' EXIT
    for label in com.myaiemployee.agent com.myaiemployee.imap-sync com.myaiemployee.digital-employee; do
        target_plist="${LAUNCH_AGENTS_DIR}/${label}.plist"
        launchctl list > "${LC_OUT_UNINSTALL}" 2>&1 || true
        if grep -q "${label}" "${LC_OUT_UNINSTALL}"; then
            echo "🔻 launchctl unload ${target_plist}"
            launchctl unload "${target_plist}" 2>/dev/null || true
            sleep 1
            launchctl list > "${LC_OUT_UNINSTALL}" 2>&1 || true
            if grep -q "${label}" "${LC_OUT_UNINSTALL}"; then
                echo "⚠️  unload 后 list 仍见 ${label},尝试 bootout"
                launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
                sleep 1
            fi
        else
            echo "ℹ️  ${label} 未注册,跳过 unload"
        fi
    done
    # 2. 删 plist(3 job)
    for label in com.myaiemployee.agent com.myaiemployee.imap-sync com.myaiemployee.digital-employee; do
        target_plist="${LAUNCH_AGENTS_DIR}/${label}.plist"
        if [[ -f "${target_plist}" ]]; then
            rm -f "${target_plist}"
            echo "✅ 删除 plist: ${target_plist}"
        else
            echo "ℹ️  plist 不存在,跳过: ${target_plist}"
        fi
    done
    # 3. 删 ~/bin/ 脚本(3 wrapper)
    for script in \
        "${HOME_BIN}/my-ai-employee-monthly-report" \
        "${HOME_BIN}/my-ai-employee-imap-sync" \
        "${HOME_BIN}/my-ai-employee-start" \
        "${HOME_BIN}/my-ai-employee-digital-runner"; do
        if [[ -f "${script}" ]]; then
            rm -f "${script}"
            echo "✅ 删除脚本: ${script}"
        else
            echo "ℹ️  脚本不存在,跳过: ${script}"
        fi
    done
    # 4. 删日志目录
    if [[ -d "${LOG_DIR}" ]]; then
        rm -rf "${LOG_DIR}"
        echo "✅ 删除日志目录: ${LOG_DIR}"
    else
        echo "ℹ️  日志目录不存在,跳过"
    fi
    # 5. 验证无残留(3 job)
    launchctl list > "${LC_OUT_UNINSTALL}" 2>&1 || true
    for label in com.myaiemployee.agent com.myaiemployee.imap-sync com.myaiemployee.digital-employee; do
        if grep -q "${label}" "${LC_OUT_UNINSTALL}"; then
            echo "❌ 验证失败:launchctl list 仍见 ${label}" >&2
            exit 3
        fi
    done
    echo ""
    echo "🎉 uninstall 完成(无残留)"
    exit 0
fi

# ===== install 流程 =====
echo "===== install 流程 ====="

# ===== 1. 源存在性校验 =====
if [[ ! -f "${SOURCE_SCRIPT}" ]]; then
    echo "❌ 源脚本不存在: ${SOURCE_SCRIPT}" >&2
    exit 1
fi
if [[ ! -f "${SOURCE_PLIST}" ]]; then
    echo "❌ 源 plist 不存在: ${SOURCE_PLIST}" >&2
    exit 1
fi
if [[ ! -f "${SOURCE_PLIST_IMAP}" ]]; then
    echo "❌ 源 plist 不存在: ${SOURCE_PLIST_IMAP}" >&2
    exit 1
fi
if [[ ! -f "${SOURCE_PLIST_START}" ]]; then
    echo "❌ 源 plist 不存在: ${SOURCE_PLIST_START}" >&2
    exit 1
fi
if [[ ! -f "${SOURCE_SYNC_IMAP}" ]]; then
    echo "❌ 源脚本不存在: ${SOURCE_SYNC_IMAP}" >&2
    exit 1
fi
if [[ ! -f "${SOURCE_START_SH}" ]]; then
    echo "❌ 源脚本不存在: ${SOURCE_START_SH}" >&2
    exit 1
fi

# ===== 2. 目标目录校验 + 自动创建 =====
if [[ ! -d "${HOME_BIN}" ]]; then
    echo "📁 创建 ${HOME_BIN}/ 目录"
    mkdir -p "${HOME_BIN}"
fi
if [[ ! -w "${HOME_BIN}" ]]; then
    echo "❌ ${HOME_BIN}/ 不可写" >&2
    exit 2
fi
if [[ ! -d "${LAUNCH_AGENTS_DIR}" ]]; then
    echo "📁 创建 ${LAUNCH_AGENTS_DIR}/ 目录"
    mkdir -p "${LAUNCH_AGENTS_DIR}"
fi
if [[ ! -w "${LAUNCH_AGENTS_DIR}" ]]; then
    echo "❌ ${LAUNCH_AGENTS_DIR}/ 不可写" >&2
    exit 2
fi

# ===== 3. 部署 ~/bin/ wrapper 脚本 =====
echo "📋 部署 ${TARGET_SCRIPT}(动态月份)"
{
    echo "#!/usr/bin/env bash"
    echo "# 部署于 $(date '+%Y-%m-%d %H:%M:%S') by scripts/launchd_install.sh"
    echo "MONTH=\$(date -v-1d +%Y-%m 2>/dev/null || date -d 'last month' +%Y-%m)"
    echo "exec uv run --project \"${PROJECT_ROOT}\" python -m scripts.monthly_report generate --month \"\${MONTH}\""
} > "${TARGET_SCRIPT}"
chmod +x "${TARGET_SCRIPT}"
echo "✅ ${TARGET_SCRIPT} 部署完成"

echo "📋 部署 ${TARGET_IMAP_SCRIPT}(IMAP 每日同步)"
{
    echo "#!/usr/bin/env bash"
    echo "# 部署于 $(date '+%Y-%m-%d %H:%M:%S') by scripts/launchd_install.sh"
    echo "ENV_FILE=\"${PROJECT_ROOT}/.env\""
    echo "IMAP_USER=\"\""
    echo "if [[ -f \"\${ENV_FILE}\" ]]; then"
    echo "  IMAP_USER=\$(grep -E '^IMAP_USER=' \"\${ENV_FILE}\" | head -1 | cut -d= -f2- | tr -d '\"' | tr -d \"'\")"
    echo "fi"
    echo "if [[ -z \"\${IMAP_USER}\" ]]; then"
    echo "  echo 'IMAP_USER not set in .env' >&2"
    echo "  exit 2"
    echo "fi"
    echo "exec uv run --project \"${PROJECT_ROOT}\" python scripts/sync_imap.py sync --provider qq --email \"\${IMAP_USER}\""
} > "${TARGET_IMAP_SCRIPT}"
chmod +x "${TARGET_IMAP_SCRIPT}"
echo "✅ ${TARGET_IMAP_SCRIPT} 部署完成"

echo "📋 部署 ${TARGET_START_SCRIPT}(数字员工开机自启)"
echo "📋 部署 ${TARGET_START_RUNNER}(数字员工 runner · 非 Documents 执行)"
cp "${SOURCE_START_SH}" "${TARGET_START_RUNNER}"
chmod +x "${TARGET_START_RUNNER}"
echo "✅ ${TARGET_START_RUNNER} 部署完成"

{
    echo "#!/usr/bin/env bash"
    echo "# 部署于 $(date '+%Y-%m-%d %H:%M:%S') by scripts/launchd_install.sh"
    echo "set -euo pipefail"
    echo "export MY_AI_EMPLOYEE_PROJECT_ROOT=\"${PROJECT_ROOT}\""
    echo "exec \"${TARGET_START_RUNNER}\" start"
} > "${TARGET_START_SCRIPT}"
chmod +x "${TARGET_START_SCRIPT}"
echo "✅ ${TARGET_START_SCRIPT} 部署完成"

# ===== 4. 复制 plist(替换 $USER 占位符) =====
for src_plist in "${SOURCE_PLIST}" "${SOURCE_PLIST_IMAP}" "${SOURCE_PLIST_START}"; do
    base_name="$(basename "${src_plist}")"
    target_plist="${LAUNCH_AGENTS_DIR}/${base_name}"
    echo "📋 复制 ${src_plist} → ${target_plist}"
    sed "s|\$USER|$(whoami)|g" "${src_plist}" > "${target_plist}"
    chmod 644 "${target_plist}"
    echo "✅ ${target_plist} 部署完成"
done

# ===== 5. 确保日志目录存在 =====
mkdir -p "${LOG_DIR}"
touch "${LOG_DIR}/agent.out.log" "${LOG_DIR}/agent.err.log"
touch "${LOG_DIR}/imap-sync.out.log" "${LOG_DIR}/imap-sync.err.log"
touch "${LOG_DIR}/digital-employee.out.log" "${LOG_DIR}/digital-employee.err.log"
echo "✅ ${LOG_DIR}/ 日志目录就绪"

# ===== 6. launchctl load(3 job) =====
LC_OUT_LOAD="$(mktemp -t launchctl_list_load.XXXXXX)"
trap 'rm -f "${LC_OUT_LOAD}" "${LC_OUT:-}"' EXIT
for target_plist in "${TARGET_PLIST}" "${TARGET_PLIST_IMAP}" "${TARGET_PLIST_START}"; do
    label="$(basename "${target_plist}" .plist)"
    launchctl list > "${LC_OUT_LOAD}" 2>&1 || true
    if grep -q "${label}" "${LC_OUT_LOAD}"; then
        echo "ℹ️  已注册(${label}),先 unload 再 reload"
        launchctl unload "${target_plist}" 2>/dev/null || true
        sleep 1
    fi
    echo "🚀 launchctl load -w ${target_plist}"
    if ! launchctl load -w "${target_plist}" 2>/dev/null; then
        sleep 1
        launchctl list > "${LC_OUT_LOAD}" 2>&1 || true
        if ! grep -q "${label}" "${LC_OUT_LOAD}"; then
            echo "❌ launchctl load 失败且 list 未见 ${label}" >&2
            exit 3
        fi
        echo "⚠️  launchctl load 报非 0 但 list 已见 ${label}"
    fi
done

# ===== 7. 5 源验证(3 job) =====
echo ""
echo "===== 5 源验证 ====="
[[ -d "${HOME_BIN}" ]] && echo "✅ 源 1(目录): ${HOME_BIN}/ 存在" || echo "❌ 源 1: 缺失"
[[ -x "${TARGET_SCRIPT}" ]] && echo "✅ 源 2(脚本): ${TARGET_SCRIPT} 可执行" || echo "❌ 源 2: 不可执行"
[[ -f "${TARGET_PLIST}" ]] && echo "✅ 源 3(plist): ${TARGET_PLIST} 存在" || echo "❌ 源 3: 缺失"
LAUNCHCTL_OK=0
LC_OUT="$(mktemp -t launchctl_list_verify.XXXXXX)"
for i in 1 2 3 4 5; do
    sleep 1
    launchctl list > "${LC_OUT}" 2>&1 || true
    missing=0
    for label in "${LAUNCHD_LABELS[@]}"; do
        if ! grep -q "${label}" "${LC_OUT}"; then
            missing=1
            break
        fi
    done
    if [[ "${missing}" -eq 0 ]]; then
        LAUNCHCTL_OK=1
        echo "✅ 源 4(launchctl list): 3 job 已注册(retry ${i}/5)"
        break
    fi
done
if [[ "${LAUNCHCTL_OK}" -eq 0 ]]; then
    echo "❌ 源 4: launchctl list 未见全部 3 job(retry 5 次)" >&2
    cat "${LC_OUT}" >&2 || true
    exit 3
fi
[[ -w "${LOG_DIR}/agent.out.log" ]] && echo "✅ 源 5(日志): ${LOG_DIR}/agent.out.log 可写" || echo "❌ 源 5: 日志不可写"

echo ""
echo "🎉 launchd 部署完成(3 job)!"
echo "  月报:每月 1 号 09:00 · 动态月份 wrapper"
echo "  IMAP:每日 07:00 · 读 .env IMAP_USER"
echo "  数字员工:RunAtLoad · menubar + dashboard"

# 显式 exit 0(供测试 grep 验证,也是 bash 严格模式的明确结束)
exit 0
