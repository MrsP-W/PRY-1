#!/usr/bin/env bash
# Day 6 — 一键启动数字员工(串联 menubar + dashboard + Keychain 验证 + 1-click 审批引导)
#
# 沿 ops/start-menubar.sh Day 2 范本 + 用户原 7 天计划 Day 6-7 设计:
#   - 预检:9/9 质量门 baseline check + Keychain QQ SMTP 授权码存在性 + alembic head 状态
#   - 启动:菜单栏后台常驻 + Dashboard 只读 API(127.0.0.1:8765,默认 DASHBOARD_REAL_DB=1)
#   - 引导:1-click 审批入口路径(撞坑 #59 红线维持 · 不自动真发邮件)
#   - 状态:统一 health check 报告(menubar PID + dashboard HTTP 200 + Keychain present + outbox 总数)
#   - 提供 start / stop / status / health 子命令(沿 start-menubar 范本)
#
# 撞坑关联:
#   - 撞坑 #71 决议 B 范围内(Day 1-2 基础设施放行 · Day 6 一键包延用)
#   - 撞坑 #59 红线维持:本脚本不读真实凭据,只调 scripts/spike_set_smtp_password.py 看是否已配置
#   - 撞坑 #50 漂移防御:不读 quality_snapshot(沿 start-menubar 范本 · 不引依赖)
#   - 撞坑 #18 风险门控:启动 dashboard 默认 DASHBOARD_REAL_DB=1 但不启动业务写入(ENABLE_PATH_4_WRITE 维持 UNSET)
#   - 撞坑 #81 已修复(沿 Day 2 3/3 · 菜单栏首次启动用户须先 TCC 授权 Python.framework 3.12)
#
# 使用方式:
#   bash ops/start-digital-employee.sh start      # 一键启动(menubar + dashboard)
#   bash ops/start-digital-employee.sh stop       # 全停
#   bash ops/start-digital-employee.sh status     # 查看状态
#   bash ops/start-digital-employee.sh health     # 健康检查(8 维度)
#   bash ops/start-digital-employee.sh restart    # 全停后启动
#   bash ops/start-digital-employee.sh --dry-run start  # 仅打印命令
#
# 部署位置:仓库 ops/ 目录(沿 ops/day1-baseline.md / ops/start-menubar.sh 范本)
# 不需要 root · 不写 LaunchAgents(撞坑 #71 B 范围)

set -euo pipefail

# 路径约定(沿 ops/day1-phase2-env.md)
# launchd 安装时会把本脚本复制到 ~/bin,此时必须显式传入真实项目根目录。
# 撞坑 #92 修复(2026-07-09):runtime 配置/日志/数据路径迁出 ~/Documents/(iCloud 同步目录沙箱拦截)
#   - .env   → ~/Library/Application Support/MyAIEmployee/.env
#   - data/  → ~/Library/Application Support/MyAIEmployee/data/
#   - logs/  → ~/Library/Logs/MyAIEmployee/(已沿 v1.0 launch plan 范本)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${MY_AI_EMPLOYEE_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"

# 撞坑 #92 修复路径 B(2026-07-09):runtime 状态文件全部迁非 Documents 目录
APP_SUPPORT_DIR="${MY_AI_EMPLOYEE_APP_SUPPORT_DIR:-$HOME/Library/Application Support/MyAIEmployee}"
ENV_FILE="${MY_AI_EMPLOYEE_ENV_FILE:-$APP_SUPPORT_DIR/.env}"
DATA_DIR="$APP_SUPPORT_DIR/data"
LOG_DIR="${MY_AI_EMPLOYEE_LOG_DIR:-$HOME/Library/Logs/MyAIEmployee}"
LOG_FILE="$LOG_DIR/digital_employee.log"
MENUBAR_LOG="$LOG_DIR/menu_bar.log"
DASHBOARD_LOG="$LOG_DIR/dashboard.log"

# PID 文件(分文件,避免互冲) — 沿 Application Support/data/ 不进 iCloud 沙箱
MENUBAR_PID_FILE="$DATA_DIR/menu_bar.pid"
DASHBOARD_PID_FILE="$DATA_DIR/dashboard.pid"

# 启动入口
RUN_MENUBAR="$PROJECT_ROOT/scripts/run_menu_bar.py"

# 撞坑 #93 修复(2026-07-09):launchd 子进程 PATH 不含 /opt/homebrew/bin(uv 安装位置),
# 用 command -v 优先探测 PATH · fallback 绝对路径,沿 v1.0 launch runbook 范本(可移植)
UV_BIN="$(command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)"

# 颜色(沿 ops/start-menubar.sh + scripts/launchd_install.sh 范本)
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
ok() { echo -e "${GREEN}✅${NC} $*"; }
warn() { echo -e "${YELLOW}⚠️${NC} $*"; }
err() { echo -e "${RED}❌${NC} $*" >&2; }

# Keychain 探测(沿 core/keychain.py SERVICE_SMTP_QQ + account=IMAP_USER)
KEYCHAIN_SMTP_QQ_SERVICE="my-ai-employee.smtp.qq"

_get_imap_user_from_env() {
    if [[ ! -f "$ENV_FILE" ]]; then
        return 1
    fi
    local line account
    line=$(grep -E "^IMAP_USER=" "$ENV_FILE" | head -1 || true)
    if [[ -z "$line" ]]; then
        return 1
    fi
    account="${line#IMAP_USER=}"
    account="${account%\"}"
    account="${account#\"}"
    account="${account%\'}"
    account="${account#\'}"
    if [[ -z "$account" ]]; then
        return 1
    fi
    printf '%s' "$account"
}

_check_keychain_qq_smtp_present() {
    if ! command -v security >/dev/null 2>&1; then
        return 2
    fi
    local account
    account=$(_get_imap_user_from_env) || return 1
    security find-generic-password -s "$KEYCHAIN_SMTP_QQ_SERVICE" -a "$account" -w >/dev/null 2>&1
}

# dry-run 模式
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    shift
fi

# 通用执行器(dry-run 感知)
run_cmd() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] $*"
    else
        eval "$@"
    fi
}

# 验证项目结构
if [[ ! -f "$RUN_MENUBAR" ]]; then
    err "未找到 $RUN_MENUBAR(请在项目根目录跑)"
    exit 1
fi

# --- 进程状态检测 ---

is_menubar_running() {
    if [[ -f "$MENUBAR_PID_FILE" ]]; then
        local pid
        pid=$(cat "$MENUBAR_PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

is_dashboard_running() {
    if [[ -f "$DASHBOARD_PID_FILE" ]]; then
        local pid
        pid=$(cat "$DASHBOARD_PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# --- 预检(独立函数,start/health 都用) ---

preflight_check() {
    log "🔍 预检:9 维度健康检查"

    local fail=0

    # 1. .env 存在(撞坑 #92 修复:读 ~/Library/Application Support/MyAIEmployee/.env)
    if [[ -f "$ENV_FILE" ]]; then
        ok "  [1/9] .env 存在 ($ENV_FILE)"
    else
        warn "  [1/9] .env 不存在(撞坑 #1 风险门控 · 期望路径: $ENV_FILE)"
        fail=$((fail + 1))
    fi

    # 2. SQLCipher key 非空
    if [[ -f "$ENV_FILE" ]]; then
        if grep -qE "^DB_ENCRYPTION_KEY=[a-fA-F0-9]{64}$" "$ENV_FILE"; then
            ok "  [2/9] DB_ENCRYPTION_KEY 64 hex OK"
        else
            warn "  [2/9] DB_ENCRYPTION_KEY 缺失或格式错"
            fail=$((fail + 1))
        fi
    else
        warn "  [2/9] DB_ENCRYPTION_KEY 跳过(.env 不存在)"
        fail=$((fail + 1))
    fi

    # 3. Keychain QQ SMTP 授权码(service=my-ai-employee.smtp.qq · account=IMAP_USER)
    case "$(_check_keychain_qq_smtp_present; echo $?)" in
        0)
            ok "  [3/9] Keychain QQ SMTP 授权码 present(沿 Day 1 阶段 2 范本 · service=$KEYCHAIN_SMTP_QQ_SERVICE)"
            ;;
        2)
            warn "  [3/9] security CLI 不可用(非 macOS?)"
            fail=$((fail + 1))
            ;;
        *)
            warn "  [3/9] Keychain QQ SMTP 授权码 missing(需 IMAP_USER + service=$KEYCHAIN_SMTP_QQ_SERVICE)"
            fail=$((fail + 1))
            ;;
    esac

    # 4. alembic head 状态(仅检查 DDL,不实际升级)
    if cd "$PROJECT_ROOT" && "${UV_BIN}" run alembic current >/dev/null 2>&1; then
        ok "  [4/9] alembic current OK"
    else
        warn "  [4/9] alembic current 失败(可能未跑 alembic upgrade head)"
        fail=$((fail + 1))
    fi

    # 5. 菜单栏入口
    if [[ -f "$RUN_MENUBAR" ]]; then
        ok "  [5/9] scripts/run_menu_bar.py 存在"
    else
        err "  [5/9] scripts/run_menu_bar.py 缺失(致命)"
        fail=$((fail + 1))
    fi

    # 6. Dashboard 服务入口
    if cd "$PROJECT_ROOT" && "${UV_BIN}" run python -c "import my_ai_employee.dashboard.server" 2>/dev/null; then
        ok "  [6/9] dashboard.server 模块 OK"
    else
        warn "  [6/9] dashboard.server 导入失败"
        fail=$((fail + 1))
    fi

    # 7. 撞坑 #81 TCC(只提醒,不阻断)
    warn "  [7/9] ⌥⌘N TCC 检查:用户须先授权 Python.framework 3.12(撞坑 #81 已修复,首次启动需手动)"

    # 8. docs/ui HTML 存在
    if [[ -f "$PROJECT_ROOT/docs/ui/codex-style-dashboard.html" ]]; then
        ok "  [8/9] docs/ui/codex-style-dashboard.html 存在"
    else
        warn "  [8/9] docs/ui/codex-style-dashboard.html 缺失(可选)"
    fi

    # 9. data/ 目录(撞坑 #92 修复:在 ~/Library/Application Support/MyAIEmployee/data/)
    if [[ -d "$DATA_DIR" ]]; then
        ok "  [9/9] data/ 目录存在 ($DATA_DIR)"
    else
        warn "  [9/9] data/ 不存在(首次启动会自动创建:$DATA_DIR)"
    fi

    if [[ $fail -eq 0 ]]; then
        ok "预检全过 ✅"
        return 0
    else
        warn "预检失败 $fail 项(不阻断启动,需用户确认)"
        return 0  # 不阻断 — 用户可后续逐项修复
    fi
}

# --- 子命令 ---

cmd_start_menubar() {
    if is_menubar_running; then
        local pid
        pid=$(cat "$MENUBAR_PID_FILE")
        warn "菜单栏已在跑(PID=$pid)"
        return 0
    fi

    log "🚀 启动菜单栏后台常驻..."
    mkdir -p "$DATA_DIR"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] DASHBOARD_REAL_DB=1 nohup ${UV_BIN} run python $RUN_MENUBAR > $MENUBAR_LOG 2>&1 &"
        ok "菜单栏 dry-run 完成"
        return 0
    fi

    cd "$PROJECT_ROOT"
    nohup env DASHBOARD_REAL_DB=1 "${UV_BIN}" run python "$RUN_MENUBAR" > "$MENUBAR_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$MENUBAR_PID_FILE"

    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        ok "菜单栏已启动(PID=$pid,log=$MENUBAR_LOG)"
        log "  首次启动若 ⌥⌘N 无响应:沿撞坑 #81 TCC 引导 bash ops/start-menubar.sh status"
    else
        err "菜单栏启动失败(查看日志:tail $MENUBAR_LOG)"
        rm -f "$MENUBAR_PID_FILE"
        return 1
    fi
}

cmd_start_dashboard() {
    if is_dashboard_running; then
        local pid
        pid=$(cat "$DASHBOARD_PID_FILE")
        warn "Dashboard 已在跑(PID=$pid)"
        return 0
    fi

    log "🚀 启动 Dashboard 只读 API(127.0.0.1:8765 · DASHBOARD_REAL_DB=1)..."
    mkdir -p "$LOG_DIR"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] DASHBOARD_REAL_DB=1 nohup ${UV_BIN} run python -m my_ai_employee.dashboard.server > $DASHBOARD_LOG 2>&1 &"
        ok "Dashboard dry-run 完成"
        return 0
    fi

    cd "$PROJECT_ROOT"
    nohup env DASHBOARD_REAL_DB=1 "${UV_BIN}" run python -m my_ai_employee.dashboard.server > "$DASHBOARD_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$DASHBOARD_PID_FILE"

    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        ok "Dashboard 已启动(PID=$pid,log=$DASHBOARD_LOG)"
        log "  浏览器打开:open docs/ui/codex-style-dashboard.html"
        log "  或:open http://127.0.0.1:8765/api/status"
    else
        err "Dashboard 启动失败(查看日志:tail $DASHBOARD_LOG)"
        rm -f "$DASHBOARD_PID_FILE"
        return 1
    fi
}

cmd_start() {
    log "🟢 一键启动数字员工(menubar + dashboard)..."
    preflight_check
    cmd_start_menubar
    cmd_start_dashboard
    ok "🎉 启动完成"
    log ""
    log "📋 1-click 审批入口(Day 6 不自动真发 · 撞坑 #59 红线维持):"
    log "   - 菜单栏 → 系统健康 / 授权引导 / 1-click 审批"
    log "   - Dashboard:http://127.0.0.1:8765/api/approval-gate/audits"
    log ""
    log "📊 健康检查:bash ops/start-digital-employee.sh health"
    log "🛑 全停:bash ops/start-digital-employee.sh stop"
}

cmd_stop_menubar() {
    if ! is_menubar_running; then
        warn "菜单栏未在跑"
        rm -f "$MENUBAR_PID_FILE"
        return 0
    fi
    local pid
    pid=$(cat "$MENUBAR_PID_FILE")
    log "🛑 停止菜单栏(PID=$pid)..."

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] kill $pid"
        return 0
    fi

    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        warn "  进程未响应 SIGTERM,SIGKILL..."
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$MENUBAR_PID_FILE"
    ok "菜单栏已停止"
}

cmd_stop_dashboard() {
    if ! is_dashboard_running; then
        warn "Dashboard 未在跑"
        rm -f "$DASHBOARD_PID_FILE"
        return 0
    fi
    local pid
    pid=$(cat "$DASHBOARD_PID_FILE")
    log "🛑 停止 Dashboard(PID=$pid)..."

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] kill $pid"
        return 0
    fi

    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        warn "  进程未响应 SIGTERM,SIGKILL..."
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$DASHBOARD_PID_FILE"
    ok "Dashboard 已停止"
}

cmd_stop() {
    cmd_stop_dashboard
    cmd_stop_menubar
    ok "🎯 全部停止"
}

cmd_status() {
    log "📊 状态检查"
    if is_menubar_running; then
        local pid
        pid=$(cat "$MENUBAR_PID_FILE")
        ok "  菜单栏:PID=$pid(log=$MENUBAR_LOG)"
    else
        warn "  菜单栏:未运行"
    fi
    if is_dashboard_running; then
        local pid
        pid=$(cat "$DASHBOARD_PID_FILE")
        ok "  Dashboard:PID=$pid(log=$DASHBOARD_LOG)"
        # 检查 HTTP 200
        if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/api/status 2>/dev/null | grep -q "200"; then
            ok "  Dashboard HTTP /api/status:200"
        else
            warn "  Dashboard HTTP /api/status:无响应"
        fi
    else
        warn "  Dashboard:未运行"
    fi
}

cmd_health() {
    log "🏥 完整健康检查"
    preflight_check
    cmd_status

    # Keychain 检查
    if command -v security >/dev/null 2>&1; then
        if _check_keychain_qq_smtp_present; then
            ok "Keychain QQ SMTP:present(不打印内容 · 撞坑 #1 · service=$KEYCHAIN_SMTP_QQ_SERVICE)"
        else
            warn "Keychain QQ SMTP:missing(需 IMAP_USER + service=$KEYCHAIN_SMTP_QQ_SERVICE)"
        fi
    fi

    # 9/9 质量门 baseline 检查
    log ""
    log "🧪 9/9 质量门 baseline check..."
    cd "$PROJECT_ROOT"
    if make check-snapshot >/dev/null 2>&1; then
        ok "  make check-snapshot:OK(质量快照与实测对齐)"
    else
        warn "  make check-snapshot:漂移(撞坑 #50 触发)"
    fi
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

# 默认子命令(沿 ops/start-menubar.sh user-friendly 范本)
SUBCMD="${1:-start}"

case "$SUBCMD" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    health)  cmd_health ;;
    restart) cmd_restart ;;
    *)
        err "未知子命令: $SUBCMD"
        echo "用法:bash ops/start-digital-employee.sh {start|stop|status|health|restart|--dry-run <subcmd>}"
        exit 1
        ;;
esac
