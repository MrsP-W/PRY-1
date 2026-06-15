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

HOME_BIN="${HOME}/bin"
TARGET_SCRIPT="${HOME_BIN}/my-ai-employee-monthly-report"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/com.myaiemployee.agent.plist"
LOG_DIR="${HOME}/Library/Logs/MyAIEmployee"

# ===== uninstall 流程(2026-06-15 D10.5.3 新增,沿 Spike A 手动 cleanup 4 步范本) =====
if [[ "${MODE}" == "uninstall" ]]; then
    echo "===== uninstall 流程 ====="
    # 1. launchctl unload(如果已注册 — D10.5.3 修正:用临时文件绕开 pipefail 影响)
    LC_OUT_UNINSTALL="$(mktemp -t launchctl_list_uninstall.XXXXXX)"
    trap 'rm -f "${LC_OUT_UNINSTALL:-}" "${LC_OUT_LOAD:-}" "${LC_OUT:-}"' EXIT
    launchctl list > "${LC_OUT_UNINSTALL}" 2>&1 || true
    if grep -q "com.myaiemployee.agent" "${LC_OUT_UNINSTALL}"; then
        echo "🔻 launchctl unload ${TARGET_PLIST}"
        launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
        sleep 1
        # 再次验证已真 unload
        launchctl list > "${LC_OUT_UNINSTALL}" 2>&1 || true
        if grep -q "com.myaiemployee.agent" "${LC_OUT_UNINSTALL}"; then
            echo "⚠️  unload 后 list 仍见条目,尝试 bootout"
            launchctl bootout "gui/$(id -u)/com.myaiemployee.agent" 2>/dev/null || true
            sleep 1
        fi
    else
        echo "ℹ️  未注册,跳过 unload"
    fi
    # 2. 删 plist
    if [[ -f "${TARGET_PLIST}" ]]; then
        rm -f "${TARGET_PLIST}"
        echo "✅ 删除 plist: ${TARGET_PLIST}"
    else
        echo "ℹ️  plist 不存在,跳过"
    fi
    # 3. 删 ~/bin/ 脚本
    if [[ -f "${TARGET_SCRIPT}" ]]; then
        rm -f "${TARGET_SCRIPT}"
        echo "✅ 删除脚本: ${TARGET_SCRIPT}"
    else
        echo "ℹ️  脚本不存在,跳过"
    fi
    # 4. 删日志目录
    if [[ -d "${LOG_DIR}" ]]; then
        rm -rf "${LOG_DIR}"
        echo "✅ 删除日志目录: ${LOG_DIR}"
    else
        echo "ℹ️  日志目录不存在,跳过"
    fi
    # 5. 验证无残留(D10.5.3 修正:同样用临时文件方案)
    launchctl list > "${LC_OUT_UNINSTALL}" 2>&1 || true
    if grep -q "com.myaiemployee.agent" "${LC_OUT_UNINSTALL}"; then
        echo "❌ 验证失败:launchctl list 仍见 com.myaiemployee.agent" >&2
        exit 3
    fi
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

# ===== 6. launchctl load(沿 D5.6 范本 + D10.5.3 调整:容忍已注册状态) =====
# D10.5.3 修正: macOS 26 (Tahoe) launchd 对已注册的 plist 重复 load 会报
# "Load failed: 5: Input/output error" 但 entry 实际已存在。Spike A §3.3
# 也观察到同样行为。改为"已注册则跳过 unload+load,未注册则 load"语义。
LC_OUT_LOAD="$(mktemp -t launchctl_list_load.XXXXXX)"
trap 'rm -f "${LC_OUT_LOAD}" "${LC_OUT:-}"' EXIT
launchctl list > "${LC_OUT_LOAD}" 2>&1 || true
if grep -q "com.myaiemployee.agent" "${LC_OUT_LOAD}"; then
    echo "ℹ️  已注册(com.myaiemployee.agent),先 unload 再 reload 防止 stale 配置"
    launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
    sleep 1
fi
echo "🚀 launchctl load -w ${TARGET_PLIST}"
if ! launchctl load -w "${TARGET_PLIST}" 2>/dev/null; then
    # 退出码非 0 不一定是真失败(macOS 26 已注册则报 5)
    # 用 list 探测最终状态:已注册则视为成功
    sleep 1
    launchctl list > "${LC_OUT_LOAD}" 2>&1 || true
    if grep -q "com.myaiemployee.agent" "${LC_OUT_LOAD}"; then
        echo "⚠️  launchctl load 报非 0 但 list 已见 com.myaiemployee.agent(macOS 26 已注册语义,沿 Spike A §3.3)"
    else
        echo "❌ launchctl load 失败且 list 未见 com.myaiemployee.agent" >&2
        exit 3
    fi
fi

# ===== 7. 5 源验证(2026-06-15 D10.5.3 修复 P2-2:加 sleep 1 + retry 3 次,缓解 launchctl cache race) =====
echo ""
echo "===== 5 源验证 ====="
# 1. 目录
[[ -d "${HOME_BIN}" ]] && echo "✅ 源 1(目录): ${HOME_BIN}/ 存在" || echo "❌ 源 1: 缺失"
# 2. 脚本
[[ -x "${TARGET_SCRIPT}" ]] && echo "✅ 源 2(脚本): ${TARGET_SCRIPT} 可执行" || echo "❌ 源 2: 不可执行"
# 3. plist
[[ -f "${TARGET_PLIST}" ]] && echo "✅ 源 3(plist): ${TARGET_PLIST} 存在" || echo "❌ 源 3: 缺失"
# 4. launchctl list(sleep + retry 缓解 cache race + 用临时文件绕开 pipefail 对 pipeline 的影响)
# D10.5.3 实测: pipefail 下 "launchctl list | grep -q" 即使已注册也返回 1,
# 根因是 pipefail 让 launchctl list 的输出 buffer 行为变化;改用临时文件捕获可解。
LAUNCHCTL_OK=0
LC_OUT="$(mktemp -t launchctl_list_verify.XXXXXX)"
# trap 在 §6 已设置(覆盖 LC_OUT_LOAD + LC_OUT),无需再设
for i in 1 2 3 4 5; do
    sleep 1
    launchctl list > "${LC_OUT}" 2>&1 || true
    if grep -q "com.myaiemployee.agent" "${LC_OUT}"; then
        LAUNCHCTL_OK=1
        echo "✅ 源 4(launchctl list): com.myaiemployee.agent 已注册(retry ${i}/5,共睡 ${i}s)"
        break
    fi
done
if [[ "${LAUNCHCTL_OK}" -eq 0 ]]; then
    echo "❌ 源 4: launchctl list 仍未见 com.myaiemployee.agent(retry 5 次,共睡 5s)" >&2
    echo "--- launchctl list 实际输出 ---" >&2
    cat "${LC_OUT}" >&2 || true
    exit 3
fi
# 5. 日志可写
[[ -w "${LOG_DIR}/agent.out.log" ]] && echo "✅ 源 5(日志): ${LOG_DIR}/agent.out.log 可写" || echo "❌ 源 5: 日志不可写"

echo ""
echo "🎉 launchd 部署完成!"
echo "下次触发:每月 1 号 09:00(沿 StartCalendarInterval)"
echo "手动测试:open 'x-launchd://run/com.myaiemployee.agent'  或 launchctl kickstart -k user/$(id -u)/com.myaiemployee.agent"
echo "查看日志:tail -f ${LOG_DIR}/agent.out.log"
echo "清理:bash scripts/launchd_install.sh uninstall"

# 显式 exit 0(供测试 grep 验证,也是 bash 严格模式的明确结束)
exit 0
