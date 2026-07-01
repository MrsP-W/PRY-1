#!/usr/bin/env bash
# 撞坑 #81 诊断 — 打印真实 TCC 客户端路径 + 菜单栏状态 + 打开系统设置深链
#
# 用法:
#   bash ops/check-pitfall-81.sh           # 诊断 + 打印修复指引
#   bash ops/check-pitfall-81.sh --open    # 额外打开辅助功能/自动化设置页
#
# 撞坑:#81 菜单栏点击无响应 · 零业务风险 · docs-only 配套

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$PROJECT_ROOT/data/menu_bar.pid"
LOG_FILE="$PROJECT_ROOT/data/menu_bar.log"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

section() { echo -e "\n${BLUE}=== $* ===${NC}"; }
ok() { echo -e "${GREEN}✅${NC} $*"; }
warn() { echo -e "${YELLOW}⚠️${NC} $*"; }

OPEN_SETTINGS=false
if [[ "${1:-}" == "--open" ]]; then
    OPEN_SETTINGS=true
fi

section "撞坑 #81 诊断 · $(date '+%Y-%m-%d %H:%M:%S')"

# 1. 菜单栏进程
if [[ -f "$PID_FILE" ]]; then
    pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        ok "菜单栏在跑 PID=$pid"
        echo "    进程树:"
        ps -ef | awk -v p="$pid" '$2==p || $3==p {printf "    %s\n", $0}'
        # 找子 Python 进程
        child=$(pgrep -P "$pid" 2>/dev/null | head -1 || true)
        if [[ -n "$child" ]]; then
            py_bin=$(ps -p "$child" -o args= 2>/dev/null | awk '{print $1}' || true)
            if [[ -n "$py_bin" && -x "$py_bin" ]]; then
                ok "TCC 应授权此二进制: $py_bin"
            fi
        fi
    else
        warn "PID 文件存在但进程未存活(PID=$pid)"
    fi
else
    warn "菜单栏未在跑 · 启动: bash ops/start-menubar.sh start"
fi

# 2. 预期 Python 路径(uv run 实测范本)
section "TCC 授权目标(沿 2026-07-01 实测)"
echo "  主客户端(必加):"
echo "    /Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
echo "  可选:"
echo "    $(command -v uv 2>/dev/null || echo '(uv 未在 PATH)')"
echo "  不建议只加:"
echo "    $PROJECT_ROOT/.venv/bin/python3  ← uv run 本机未用此路径 spawn GUI"

# 3. 日志
section "最近日志(最后 10 行)"
if [[ -f "$LOG_FILE" ]]; then
    if [[ -s "$LOG_FILE" ]]; then
        tail -10 "$LOG_FILE" | sed 's/^/    /'
    else
        echo "    (空 — 无 stderr,正常)"
    fi
else
    echo "    (无 log 文件)"
fi

# 4. 复测命令
section "下一步(用户决策 B)"
cat <<'EOF'
  1. bash ops/start-menubar.sh stop
  2. 系统设置 → 辅助功能 → 添加上方 Python.framework 3.12 二进制
  3. make menu-bar  # 前台复测 · 桌面失焦后点「系统健康」
  4. 三项全过 → 回报「#81 复测通过」→ 再授权 Day 3 真发
  详: ops/day2-81-tcc-fix-runbook.md
EOF

# 5. 可选打开设置
if [[ "$OPEN_SETTINGS" == "true" ]]; then
    section "打开系统设置(TCC 深链)"
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" || true
    sleep 0.5
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation" || true
    ok "已尝试打开辅助功能 + 自动化页"
fi
