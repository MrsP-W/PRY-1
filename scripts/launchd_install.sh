#!/usr/bin/env bash
# D10.3 — launchd 部署脚本(数字生活月报保活)
#
# 承接 docs/v0.1-launch-plan.md:170-176 + docs/week2-mvp.md:245-256 D10 任务
# + v0.1-launch.md 沿 D5.6 代理故障排查 memory ~/bin/ 部署范本
#
# 5 源判定(沿 Agent Assistant scripts/proxy_health.sh 范本):
#   1. 目录:~/bin/ 存在性 + 可写
#   2. 脚本源:scripts/monthly_report.py 必存在
#   3. plist:launchd_plist/com.myaiemployee.agent.plist 必存在
#   4. 目标位置:~/Library/LaunchAgents/com.myaiemployee.agent.plist 必可写
#   5. launchctl:launchctl list 必能跑(macOS 必现)
#
# 部署步骤:
#   1. ~/bin/ 不存在 → 创建
#   2. 复制 monthly_report.py → ~/bin/my-ai-employee-monthly-report
#   3. 复制 plist → ~/Library/LaunchAgents/com.myaiemployee.agent.plist
#   4. launchctl load -w ~/Library/LaunchAgents/com.myaiemployee.agent.plist
#   5. 验证:launchctl list | grep myaiemployee
#
# 退出码(沿 D5.6.5 范本):
#   0 = 成功部署 + launchctl load 成功
#   1 = 源缺失(monthly_report.py / plist 缺失)
#   2 = 目标位置不可写(~/bin/ 或 ~/Library/LaunchAgents/)
#   3 = launchctl load 失败

set -euo pipefail

# ===== 0. 路径定位 =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_SCRIPT="${PROJECT_ROOT}/scripts/monthly_report.py"
SOURCE_PLIST="${PROJECT_ROOT}/launchd_plist/com.myaiemployee.agent.plist"

HOME_BIN="${HOME}/bin"
TARGET_SCRIPT="${HOME_BIN}/my-ai-employee-monthly-report"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/com.myaiemployee.agent.plist"
LOG_DIR="${HOME}/Library/Logs/MyAIEmployee"

# ===== 1. 源存在性校验 =====
if [[ ! -f "${SOURCE_SCRIPT}" ]]; then
    echo "❌ 源脚本不存在: ${SOURCE_SCRIPT}" >&2
    exit 1
fi
if [[ ! -f "${SOURCE_PLIST}" ]]; then
    echo "❌ 源 plist 不存在: ${SOURCE_PLIST}" >&2
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

# ===== 3. 复制脚本到 ~/bin/(沿 D5.6 memory ~/bin/ 部署范本) =====
echo "📋 复制 ${SOURCE_SCRIPT} → ${TARGET_SCRIPT}"
# 用 awk 把 shebang 写第一行(原 monthly_report.py 没用 shebang)
{
    echo "#!/usr/bin/env bash"
    echo "# 部署于 $(date '+%Y-%m-%d %H:%M:%S') by scripts/launchd_install.sh"
    echo "exec uv run --project \"${PROJECT_ROOT}\" python -m scripts.monthly_report \"\$@\""
} > "${TARGET_SCRIPT}"
chmod +x "${TARGET_SCRIPT}"
echo "✅ ${TARGET_SCRIPT} 部署完成"

# ===== 4. 复制 plist(替换 $USER 占位符) =====
echo "📋 复制 ${SOURCE_PLIST} → ${TARGET_PLIST}"
# 替换 $USER 占位符为当前用户名
sed "s|\$USER|$(whoami)|g" "${SOURCE_PLIST}" > "${TARGET_PLIST}"
chmod 644 "${TARGET_PLIST}"
echo "✅ ${TARGET_PLIST} 部署完成"

# ===== 5. 确保日志目录存在 =====
mkdir -p "${LOG_DIR}"
touch "${LOG_DIR}/agent.out.log" "${LOG_DIR}/agent.err.log"
echo "✅ ${LOG_DIR}/ 日志目录就绪"

# ===== 6. launchctl load(沿 D5.6 范本) =====
# 先 unload 防止重复装载
if launchctl list | grep -q "com.myaiemployee.agent"; then
    echo "⚠️  已有装载,先 unload"
    launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
fi
echo "🚀 launchctl load -w ${TARGET_PLIST}"
if ! launchctl load -w "${TARGET_PLIST}"; then
    echo "❌ launchctl load 失败" >&2
    exit 3
fi

# ===== 7. 5 源验证 =====
echo ""
echo "===== 5 源验证 ====="
# 1. 目录
[[ -d "${HOME_BIN}" ]] && echo "✅ 源 1(目录): ${HOME_BIN}/ 存在" || echo "❌ 源 1: 缺失"
# 2. 脚本
[[ -x "${TARGET_SCRIPT}" ]] && echo "✅ 源 2(脚本): ${TARGET_SCRIPT} 可执行" || echo "❌ 源 2: 不可执行"
# 3. plist
[[ -f "${TARGET_PLIST}" ]] && echo "✅ 源 3(plist): ${TARGET_PLIST} 存在" || echo "❌ 源 3: 缺失"
# 4. launchctl list
if launchctl list | grep -q "com.myaiemployee.agent"; then
    echo "✅ 源 4(launchctl list): com.myaiemployee.agent 已注册"
else
    echo "❌ 源 4: launchctl list 未见 com.myaiemployee.agent"
    exit 3
fi
# 5. 日志可写
[[ -w "${LOG_DIR}/agent.out.log" ]] && echo "✅ 源 5(日志): ${LOG_DIR}/agent.out.log 可写" || echo "❌ 源 5: 日志不可写"

echo ""
echo "🎉 launchd 部署完成!"
echo "下次触发:每月 1 号 09:00(沿 StartCalendarInterval)"
echo "手动测试:open 'x-launchd://run/com.myaiemployee.agent'  或 launchctl kickstart -k user/$(id -u)/com.myaiemployee.agent"
echo "查看日志:tail -f ${LOG_DIR}/agent.out.log"

# 显式 exit 0(供测试 grep 验证,也是 bash 严格模式的明确结束)
exit 0
