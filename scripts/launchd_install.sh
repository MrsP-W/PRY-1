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
# 使用方式(2026-07-09 新增 deploy-only/no-load 安全模式):
#   bash scripts/launchd_install.sh install      # 部署 + launchctl load
#   bash scripts/launchd_install.sh deploy-only # 只部署 wrapper/plist/log,不 load
#   bash scripts/launchd_install.sh no-load     # deploy-only 别名
#   bash scripts/launchd_install.sh uninstall    # 清理:unload + 删 plist + 删脚本 + 删日志
#   bash scripts/launchd_install.sh              # 默认 install(向后兼容)
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
DEPLOY_ONLY=false
case "${MODE}" in
    install)
        : # 继续走 install 流程(向后兼容)
        ;;
    deploy-only | no-load)
        DEPLOY_ONLY=true
        ;;
    uninstall)
        # 跳到 uninstall 段
        MODE_TAG="uninstall"
        ;;
    *)
        echo "❌ 未知模式: ${MODE}(只支持 install / deploy-only / no-load / uninstall)" >&2
        echo "用法: bash $0 [install|deploy-only|no-load|uninstall]" >&2
        exit 1
        ;;
esac

# ===== 0. 路径定位 =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_SCRIPT="${PROJECT_ROOT}/scripts/monthly_report.py"
SOURCE_PLIST="${PROJECT_ROOT}/launchd_plist/com.myaiemployee.agent.plist"
SOURCE_PLIST_IMAP="${PROJECT_ROOT}/launchd_plist/com.myaiemployee.imap-sync.plist"
SOURCE_PLIST_MENUBAR="${PROJECT_ROOT}/launchd_plist/com.myaiemployee.menu-bar.plist"
SOURCE_PLIST_DASHBOARD="${PROJECT_ROOT}/launchd_plist/com.myaiemployee.dashboard.plist"
SOURCE_SYNC_IMAP="${PROJECT_ROOT}/scripts/sync_imap.py"

HOME_BIN="${HOME}/bin"
TARGET_SCRIPT="${HOME_BIN}/my-ai-employee-monthly-report"
TARGET_IMAP_SCRIPT="${HOME_BIN}/my-ai-employee-imap-sync"
TARGET_MENUBAR_WRAPPER="${HOME_BIN}/my-ai-employee-menu-bar-runner"
TARGET_DASHBOARD_WRAPPER="${HOME_BIN}/my-ai-employee-dashboard-runner"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/com.myaiemployee.agent.plist"
TARGET_PLIST_IMAP="${LAUNCH_AGENTS_DIR}/com.myaiemployee.imap-sync.plist"
TARGET_PLIST_MENUBAR="${LAUNCH_AGENTS_DIR}/com.myaiemployee.menu-bar.plist"
TARGET_PLIST_DASHBOARD="${LAUNCH_AGENTS_DIR}/com.myaiemployee.dashboard.plist"
LOG_DIR="${HOME}/Library/Logs/MyAIEmployee"

# 撞坑 #92 修复(2026-07-09):runtime .env / data/ 路径迁出 ~/Documents/ iCloud 同步目录
APP_SUPPORT_DIR="${HOME}/Library/Application Support/MyAIEmployee"
APP_SUPPORT_ENV="${APP_SUPPORT_DIR}/.env"

# Day 14 (撞坑 #95 修复 2026-07-10):4 job label(月报 / IMAP 同步 / 菜单栏 / Dashboard 独立)
#   取代原 3 job 模式:com.myaiemployee.digital-employee(父子进程 + ProcessType=Background)被拆
LAUNCHD_LABELS=(
    "com.myaiemployee.agent"
    "com.myaiemployee.imap-sync"
    "com.myaiemployee.menu-bar"
    "com.myaiemployee.dashboard"
)

# ===== uninstall 流程(2026-06-15 D10.5.3 新增,沿 Spike A 手动 cleanup 4 步范本) =====
if [[ "${MODE}" == "uninstall" ]]; then
    echo "===== uninstall 流程 ====="
    # 1. launchctl unload(5 label — Day 14 #95 修复后:menu-bar + dashboard 独立 + legacy digital-employee)
    LC_OUT_UNINSTALL="$(mktemp -t launchctl_list_uninstall.XXXXXX)"
    trap 'rm -f "${LC_OUT_UNINSTALL:-}" "${LC_OUT_LOAD:-}" "${LC_OUT:-}"' EXIT
    for label in \
        com.myaiemployee.agent \
        com.myaiemployee.imap-sync \
        com.myaiemployee.menu-bar \
        com.myaiemployee.dashboard \
        com.myaiemployee.digital-employee; do
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
    # 2. 删 plist(5 label · 含 legacy digital-employee)
    for label in \
        com.myaiemployee.agent \
        com.myaiemployee.imap-sync \
        com.myaiemployee.menu-bar \
        com.myaiemployee.dashboard \
        com.myaiemployee.digital-employee; do
        target_plist="${LAUNCH_AGENTS_DIR}/${label}.plist"
        if [[ -f "${target_plist}" ]]; then
            rm -f "${target_plist}"
            echo "✅ 删除 plist: ${target_plist}"
        else
            echo "ℹ️  plist 不存在,跳过: ${target_plist}"
        fi
    done
    # 3. 删 ~/bin/ 脚本(5 wrapper — 撞坑 #95 修复:拆 menu-bar + dashboard 独立 runner + legacy start)
    for script in \
        "${HOME_BIN}/my-ai-employee-monthly-report" \
        "${HOME_BIN}/my-ai-employee-imap-sync" \
        "${HOME_BIN}/my-ai-employee-menu-bar-runner" \
        "${HOME_BIN}/my-ai-employee-dashboard-runner" \
        "${HOME_BIN}/my-ai-employee-start"; do
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
    # 5. 验证无残留(5 label · 含 legacy digital-employee)
    launchctl list > "${LC_OUT_UNINSTALL}" 2>&1 || true
    for label in \
        com.myaiemployee.agent \
        com.myaiemployee.imap-sync \
        com.myaiemployee.menu-bar \
        com.myaiemployee.dashboard \
        com.myaiemployee.digital-employee; do
        if grep -q "${label}" "${LC_OUT_UNINSTALL}"; then
            echo "❌ 验证失败:launchctl list 仍见 ${label}" >&2
            exit 3
        fi
    done
    echo ""
    echo "🎉 uninstall 完成(无残留 · 含 legacy retirement)"
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
# 撞坑 #95 修复(2026-07-10):菜单栏 + Dashboard 拆 2 个独立 LaunchAgent
if [[ ! -f "${SOURCE_PLIST_MENUBAR}" ]]; then
    echo "❌ 源 plist 不存在: ${SOURCE_PLIST_MENUBAR}" >&2
    exit 1
fi
if [[ ! -f "${SOURCE_PLIST_DASHBOARD}" ]]; then
    echo "❌ 源 plist 不存在: ${SOURCE_PLIST_DASHBOARD}" >&2
    exit 1
fi
if [[ ! -f "${SOURCE_SYNC_IMAP}" ]]; then
    echo "❌ 源脚本不存在: ${SOURCE_SYNC_IMAP}" >&2
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
# 撞坑 #92 修复:APP_SUPPORT_DIR 创建 + 权限校验
if [[ ! -d "${APP_SUPPORT_DIR}" ]]; then
    echo "📁 创建 ${APP_SUPPORT_DIR}/ 目录(撞坑 #92 修复 · runtime .env/data/ 迁出 ~/Documents/)"
    mkdir -p "${APP_SUPPORT_DIR}"
fi
if [[ ! -w "${APP_SUPPORT_DIR}" ]]; then
    echo "❌ ${APP_SUPPORT_DIR}/ 不可写" >&2
    exit 2
fi
# 撞坑 #92 修复:.env 首次迁移(若 PROJECT_ROOT/.env 存在且 APP_SUPPORT_ENV 不存在 → 自动 cp)
if [[ -f "${PROJECT_ROOT}/.env" && ! -f "${APP_SUPPORT_ENV}" ]]; then
    cp "${PROJECT_ROOT}/.env" "${APP_SUPPORT_ENV}"
    echo "✅ 首次迁移 .env:${PROJECT_ROOT}/.env → ${APP_SUPPORT_ENV}(撞坑 #92 修复)"
elif [[ -f "${APP_SUPPORT_ENV}" ]]; then
    echo "ℹ️  .env 已存在:${APP_SUPPORT_ENV}(不覆盖,撞坑 #92 修复)"
else
    echo "ℹ️  .env 待用户创建:${APP_SUPPORT_ENV}(撞坑 #92 修复)"
fi

# ===== 3. 部署 ~/bin/ wrapper 脚本 =====
echo "📋 部署 ${TARGET_SCRIPT}(动态月份)"
{
    echo "#!/usr/bin/env bash"
    echo "# 部署于 $(date '+%Y-%m-%d %H:%M:%S') by scripts/launchd_install.sh"
    echo "MONTH=\$(date -v-1d +%Y-%m 2>/dev/null || date -d 'last month' +%Y-%m)"
    # 撞坑 #93 修复(2026-07-09):launchd 子进程 PATH 不含 /opt/homebrew/bin(uv 安装位置),用绝对路径
    echo "exec /opt/homebrew/bin/uv run --project \"${PROJECT_ROOT}\" python -m scripts.monthly_report generate --month \"\${MONTH}\""
} > "${TARGET_SCRIPT}"
chmod +x "${TARGET_SCRIPT}"
echo "✅ ${TARGET_SCRIPT} 部署完成"

echo "📋 部署 ${TARGET_IMAP_SCRIPT}(IMAP 每日同步)"
# 撞坑 #92 修复:用 heredoc 直接写 wrapper(避免 echo 转义地狱,F10 易校验)
#   - \$VAR 留给 wrapper 运行期展开
#   - 不转义的 ${VAR}/${PROJECT_ROOT} 在 install 期展开
cat << EOF > "${TARGET_IMAP_SCRIPT}"
#!/usr/bin/env bash
# 部署于 $(date '+%Y-%m-%d %H:%M:%S') by scripts/launchd_install.sh
# 撞坑 #92 修复(2026-07-09):ENV_FILE 路径从 PROJECT_ROOT/.env → APP_SUPPORT/.env
# 撞坑 #96 修复(2026-07-10):用 \${PROJECT_ROOT}/scripts/sync_imap.py 绝对路径,
#   取代 python scripts/sync_imap.py 相对路径。
#   launchd plist WorkingDirectory=\$HOME 下,相对路径会被解析成 /Users/wei/scripts/sync_imap.py
#   python -m scripts.sync_imap 也失败:Python sys.path 不含 \${PROJECT_ROOT},ModuleNotFoundError
#   → 实测绝对路径是唯一稳妥方案,已用 \$HOME=/Users/wei + PATH minimal 验证通过
ENV_FILE="${APP_SUPPORT_ENV}"
IMAP_USER=""
if [[ -f "\${ENV_FILE}" ]]; then
  IMAP_USER=\$(grep -E '^IMAP_USER=' "\${ENV_FILE}" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
fi
if [[ -z "\${IMAP_USER}" ]]; then
  echo 'IMAP_USER not set in .env' >&2
  exit 2
fi
exec /opt/homebrew/bin/uv run --project "${PROJECT_ROOT}" python "${PROJECT_ROOT}/scripts/sync_imap.py" sync --provider qq --email "\${IMAP_USER}"
EOF
chmod +x "${TARGET_IMAP_SCRIPT}"
echo "✅ ${TARGET_IMAP_SCRIPT} 部署完成"

echo "📋 部署 ${TARGET_MENUBAR_WRAPPER}(撞坑 #95 修复 · 菜单栏独立 LaunchAgent runner)"
# 撞坑 #95 修复(2026-07-10):用 heredoc 直接写 wrapper(沿 P0-1 #96 范本,绝对路径 + set -euo pipefail)
cat << EOF > "${TARGET_MENUBAR_WRAPPER}"
#!/usr/bin/env bash
# 部署于 $(date '+%Y-%m-%d %H:%M:%S') by scripts/launchd_install.sh
# 撞坑 #95 修复(2026-07-10):菜单栏独立 LaunchAgent runner
#   取代原 com.myaiemployee.digital-employee(父子进程 + ProcessType=Background 禁 fork)
#   现 com.myaiemployee.menu-bar 用 ProcessType=Standard + KeepAlive=true
# 撞坑 #92 修复(2026-07-09):runtime APP_SUPPORT_DIR / ENV_FILE 显式导出
# 撞坑 #96 修复(2026-07-10):用绝对路径 \${PROJECT_ROOT}/scripts/run_menu_bar.py,
#   launchd plist WorkingDirectory=\$HOME 下相对路径解析错误
set -euo pipefail
export MY_AI_EMPLOYEE_PROJECT_ROOT="${PROJECT_ROOT}"
export MY_AI_EMPLOYEE_APP_SUPPORT_DIR="${APP_SUPPORT_DIR}"
export MY_AI_EMPLOYEE_ENV_FILE="${APP_SUPPORT_ENV}"
# 撞坑 #93 修复(2026-07-09):launchd 子进程 PATH 不含 /opt/homebrew/bin(uv 安装位置),用绝对路径
exec /opt/homebrew/bin/uv run --project "${PROJECT_ROOT}" python "${PROJECT_ROOT}/scripts/run_menu_bar.py"
EOF
chmod +x "${TARGET_MENUBAR_WRAPPER}"
echo "✅ ${TARGET_MENUBAR_WRAPPER} 部署完成"

echo "📋 部署 ${TARGET_DASHBOARD_WRAPPER}(撞坑 #95 修复 · Dashboard 独立 LaunchAgent runner)"
# 撞坑 #95 修复(2026-07-10):Dashboard 独立 LaunchAgent runner
cat << EOF > "${TARGET_DASHBOARD_WRAPPER}"
#!/usr/bin/env bash
# 部署于 $(date '+%Y-%m-%d %H:%M:%S') by scripts/launchd_install.sh
# 撞坑 #95 修复(2026-07-10):Dashboard 独立 LaunchAgent runner
#   取代原 com.myaiemployee.digital-employee(父子进程 + ProcessType=Background 禁 fork)
#   现 com.myaiemployee.dashboard 用 ProcessType=Standard + KeepAlive=true
# 撞坑 #92 修复(2026-07-09):runtime APP_SUPPORT_DIR / ENV_FILE 显式导出
# 撞坑 #96 修复(2026-07-10):用绝对路径 \${PROJECT_ROOT} + python -m 形式调 my_ai_employee.dashboard.server
set -euo pipefail
export MY_AI_EMPLOYEE_PROJECT_ROOT="${PROJECT_ROOT}"
export MY_AI_EMPLOYEE_APP_SUPPORT_DIR="${APP_SUPPORT_DIR}"
export MY_AI_EMPLOYEE_ENV_FILE="${APP_SUPPORT_ENV}"
# DASHBOARD_REAL_DB=1 + DASHBOARD_PORT=8765 已在 plist EnvironmentVariables 注入
# 撞坑 #93 修复(2026-07-09):launchd 子进程 PATH 不含 /opt/homebrew/bin,用绝对路径
exec /opt/homebrew/bin/uv run --project "${PROJECT_ROOT}" python -m my_ai_employee.dashboard.server
EOF
chmod +x "${TARGET_DASHBOARD_WRAPPER}"
echo "✅ ${TARGET_DASHBOARD_WRAPPER} 部署完成"

# ===== 4. 复制 plist(替换 $USER 占位符 · 撞坑 #95 修复:4 job) =====
for src_plist in \
    "${SOURCE_PLIST}" \
    "${SOURCE_PLIST_IMAP}" \
    "${SOURCE_PLIST_MENUBAR}" \
    "${SOURCE_PLIST_DASHBOARD}"; do
    base_name="$(basename "${src_plist}")"
    target_plist="${LAUNCH_AGENTS_DIR}/${base_name}"
    echo "📋 复制 ${src_plist} → ${target_plist}"
    sed "s|\$USER|$(whoami)|g" "${src_plist}" > "${target_plist}"
    chmod 644 "${target_plist}"
    echo "✅ ${target_plist} 部署完成"
done

# ===== 5. 确保日志目录存在(撞坑 #95 修复:4 job 日志) =====
mkdir -p "${LOG_DIR}"
touch "${LOG_DIR}/agent.out.log" "${LOG_DIR}/agent.err.log"
touch "${LOG_DIR}/imap-sync.out.log" "${LOG_DIR}/imap-sync.err.log"
touch "${LOG_DIR}/menu-bar.out.log" "${LOG_DIR}/menu-bar.err.log"
touch "${LOG_DIR}/dashboard.out.log" "${LOG_DIR}/dashboard.err.log"
echo "✅ ${LOG_DIR}/ 日志目录就绪"

# ===== 5.5 Day 14 撞坑 #95 修复补遗(2026-07-10 P1-2):legacy retirement =====
#   升级场景:旧版 com.myaiemployee.digital-employee(父子进程 + ProcessType=Background)
#   已部署但撞坑 #95 50s 内被 launchd 强制回收。Day 14 #95 修复后拆为 menu-bar + dashboard
#   两个独立 LaunchAgent,但旧 plist/wrapper 若仍残留会导致:
#     - 旧 Dashboard 可能继续占用 port 8765 → 新 Dashboard 加载失败
#     - 双实例同时监听 8765 → 行为不确定
#   此步在加载新 job 前强制 retire legacy,幂等(已 retire 直接跳过)。
LEGACY_LABEL="com.myaiemployee.digital-employee"
LEGACY_PLIST="${LAUNCH_AGENTS_DIR}/${LEGACY_LABEL}.plist"
LEGACY_WRAPPER="${HOME_BIN}/my-ai-employee-start"
LEGACY_LOG_OUT="${LOG_DIR}/digital-employee.out.log"
LEGACY_LOG_ERR="${LOG_DIR}/digital-employee.err.log"

echo "📋 legacy retirement:${LEGACY_LABEL}(撞坑 #95 修复补遗)"
LC_OUT_LEGACY="$(mktemp -t launchctl_legacy.XXXXXX)"
trap 'rm -f "${LC_OUT_LEGACY:-}" "${LC_OUT_LOAD:-}" "${LC_OUT:-}"' EXIT
launchctl list > "${LC_OUT_LEGACY}" 2>&1 || true
if grep -q "${LEGACY_LABEL}" "${LC_OUT_LEGACY}"; then
    echo "🔻 legacy 仍注册,launchctl unload"
    launchctl unload "${LEGACY_PLIST}" 2>/dev/null || true
    sleep 1
    launchctl list > "${LC_OUT_LEGACY}" 2>&1 || true
    if grep -q "${LEGACY_LABEL}" "${LC_OUT_LEGACY}"; then
        echo "⚠️  unload 后 list 仍见 ${LEGACY_LABEL},尝试 bootout"
        launchctl bootout "gui/$(id -u)/${LEGACY_LABEL}" 2>/dev/null || true
        sleep 1
    fi
else
    echo "ℹ️  ${LEGACY_LABEL} 未注册,跳过 unload"
fi
# 删 legacy plist / wrapper / 日志(幂等,文件不存在则跳过)
for legacy_path in \
    "${LEGACY_PLIST}" \
    "${LEGACY_WRAPPER}" \
    "${LEGACY_LOG_OUT}" \
    "${LEGACY_LOG_ERR}"; do
    if [[ -f "${legacy_path}" || -L "${legacy_path}" ]]; then
        rm -f "${legacy_path}"
        echo "✅ 删除 legacy: ${legacy_path}"
    else
        echo "ℹ️  legacy 不存在,跳过: ${legacy_path}"
    fi
done
# 验证 legacy 已彻底清除
launchctl list > "${LC_OUT_LEGACY}" 2>&1 || true
if grep -q "${LEGACY_LABEL}" "${LC_OUT_LEGACY}"; then
    echo "❌ legacy retirement 失败:launchctl list 仍见 ${LEGACY_LABEL}" >&2
    exit 4
fi
echo "✅ legacy retirement 完成(无残留)"

if [[ "${DEPLOY_ONLY}" == "true" ]]; then
    echo ""
    echo "🎉 deploy-only 完成(未调用 launchctl load -w · 撞坑 #95 修复:4 job 部署)"
    echo "  已更新 wrapper:${TARGET_MENUBAR_WRAPPER}"
    echo "  已更新 wrapper:${TARGET_DASHBOARD_WRAPPER}"
    echo "  已更新 plist:${TARGET_PLIST_MENUBAR}"
    echo "  已更新 plist:${TARGET_PLIST_DASHBOARD}"
    echo "  下一步如需真实加载,需用户单独授权 launchctl load -w"
    exit 0
fi

# ===== 6. launchctl load(4 job · 撞坑 #95 修复:menu-bar + dashboard 独立) =====
LC_OUT_LOAD="$(mktemp -t launchctl_list_load.XXXXXX)"
trap 'rm -f "${LC_OUT_LOAD}" "${LC_OUT:-}"' EXIT
for target_plist in \
    "${TARGET_PLIST}" \
    "${TARGET_PLIST_IMAP}" \
    "${TARGET_PLIST_MENUBAR}" \
    "${TARGET_PLIST_DASHBOARD}"; do
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

# ===== 7. 5 源验证(4 job · 撞坑 #95 修复) =====
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
        echo "✅ 源 4(launchctl list): 4 job 已注册(retry ${i}/5)"
        break
    fi
done
if [[ "${LAUNCHCTL_OK}" -eq 0 ]]; then
    echo "❌ 源 4: launchctl list 未见全部 4 job(retry 5 次)" >&2
    cat "${LC_OUT}" >&2 || true
    exit 3
fi
[[ -w "${LOG_DIR}/agent.out.log" ]] && echo "✅ 源 5(日志): ${LOG_DIR}/agent.out.log 可写" || echo "❌ 源 5: 日志不可写"

echo ""
echo "🎉 launchd 部署完成(4 job · 撞坑 #95 修复)!"
echo "  月报:每月 1 号 09:00 · 动态月份 wrapper"
echo "  IMAP:每日 07:00 · 读 .env IMAP_USER"
echo "  菜单栏:RunAtLoad + KeepAlive · 独立 LaunchAgent (ProcessType=Standard)"
echo "  Dashboard:RunAtLoad + KeepAlive · 独立 LaunchAgent (ProcessType=Standard · 127.0.0.1:8765)"

# 显式 exit 0(供测试 grep 验证,也是 bash 严格模式的明确结束)
exit 0
