#!/usr/bin/env bash
# Day 2 — 菜单栏常驻封装(nohup + 日志重定向 + PID 文件)
#
# 沿 ops/day1-phase2-env.md §5 验证 + 用户原 7 天计划 Day 2 17:30 时段设计:
#   - 封装 scripts/run_menu_bar.py 启动到后台
#   - 日志输出到 data/menu_bar.log(与 Day 7 一键包 ops/start-digital-employee.sh 共享路径)
#   - PID 文件 data/menu_bar.pid 方便 stop
#   - 提供 start / stop / status / restart 子命令
#   - 默认后台运行(Week 1 方案 A:手动 nohup · 沿用户原计划)
#
# 撞坑关联:
#   - 撞坑 #71 决议 B 范围内(Day 1-2 基础设施放行 · 零业务风险)
#   - 撞坑 #59 红线维持:本脚本不读真实凭据,只调 run_menu_bar.py(其内部读 Keychain)
#   - 撞坑 #50 漂移防御:不读 quality_snapshot,只引项目目录约定
#
# 使用方式:
#   bash ops/start-menubar.sh start      # 启动菜单栏后台(默认)
#   bash ops/start-menubar.sh stop       # 通过 PID 文件停止
#   bash ops/start-menubar.sh status     # 检查是否在跑
#   bash ops/start-menubar.sh restart    # stop + start
#   bash ops/start-menubar.sh --dry-run  # 仅打印命令不执行(安全验证)
#
# 部署位置:仓库 ops/ 目录(沿 ops/day1-baseline.md / ops/day1-phase2-env.md 范本)
# 不需要 root · 不写 LaunchAgents(Week 1 方案 A · 方案 B 留 Week 2)

set -euo pipefail

# 路径约定(沿 ops/day1-phase2-env.md)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$PROJECT_ROOT/data"
LOG_FILE="$DATA_DIR/menu_bar.log"
PID_FILE="$DATA_DIR/menu_bar.pid"
RUN_SCRIPT="$PROJECT_ROOT/scripts/run_menu_bar.py"

# 颜色(沿 scripts/launchd_install.sh 范本)
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
ok() { echo -e "${GREEN}✅${NC} $*"; }
warn() { echo -e "${YELLOW}⚠️${NC} $*"; }
err() { echo -e "${RED}❌${NC} $*" >&2; }

# dry-run 模式
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    shift
fi

# 验证项目结构
if [[ ! -f "$RUN_SCRIPT" ]]; then
    err "未找到 $RUN_SCRIPT(请在项目根目录跑)"
    exit 1
fi

# PID 是否存活
is_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

cmd_start() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        warn "菜单栏已在跑(PID=$pid,log=$LOG_FILE)"
        return 0
    fi

    log "启动菜单栏后台常驻..."
    mkdir -p "$DATA_DIR"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] nohup uv run python $RUN_SCRIPT > $LOG_FILE 2>&1 &"
        echo "[dry-run] echo \$! > $PID_FILE"
        ok "dry-run 完成(未实际启动)"
        return 0
    fi

    cd "$PROJECT_ROOT"
    nohup uv run python "$RUN_SCRIPT" > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        ok "菜单栏已启动(PID=$pid,log=$LOG_FILE)"
        log "查看实时日志:tail -f $LOG_FILE"
        log "停止菜单栏:bash ops/start-menubar.sh stop"
    else
        err "菜单栏启动失败(PID=$pid 已退出 · 查看日志:tail $LOG_FILE)"
        rm -f "$PID_FILE"
        return 1
    fi
}

cmd_stop() {
    if ! is_running; then
        warn "菜单栏未在跑(无 PID 文件或进程已退出)"
        rm -f "$PID_FILE"
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")
    log "停止菜单栏(PID=$pid)..."

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] kill $pid"
        echo "[dry-run] rm -f $PID_FILE"
        ok "dry-run 完成(未实际停止)"
        return 0
    fi

    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        warn "进程未响应 SIGTERM,尝试 SIGKILL..."
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
    ok "菜单栏已停止"
}

cmd_status() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        ok "菜单栏在跑(PID=$pid)"
        if [[ -f "$LOG_FILE" ]]; then
            log "最近日志(最后 5 行):"
            tail -5 "$LOG_FILE" | sed 's/^/    /'
        fi
    else
        warn "菜单栏未在跑"
        log "启动:bash ops/start-menubar.sh start"
    fi
}

cmd_restart() {
    cmd_stop || true
    sleep 1
    cmd_start
}

# 默认子命令(无参数 → start,沿 user-friendly 范本)
SUBCMD="${1:-start}"

case "$SUBCMD" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    restart) cmd_restart ;;
    *)
        err "未知子命令: $SUBCMD"
        echo "用法:bash ops/start-menubar.sh {start|stop|status|restart|--dry-run start}"
        exit 1
        ;;
esac