#!/usr/bin/env bash
# 供外部定时器调用：仅巡检和诊断，默认不自动修复。
# 沿用 needs-human-sol-fail2-record-2026-08-17 §2.2 v2 修复设计：
#  - pre-flight JSON 解析：python3 -c "import sys,json;..." 提取 .result 字段
#  - 零预算 wrapper：直接调 scripts/watch_p3_ops.py 而非 claude（不花 Anthropic budget）
#  - 不传 --permission-mode（依赖 shell wrapper 逐次 prompt；CLI 不支持 --permission-prompt-tool）
#  - 不传 --max-budget-usd（零预算口径）
#  - stderr 重定向到 ~/Library/Logs/MyAIEmployee/claude-p3-watch.err.log
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${HOME}/Library/Logs/MyAIEmployee"
ERR_LOG="${HOME}/Library/Logs/MyAIEmployee/claude-p3-watch.err.log"

# P3 pre-flight 检查：解析 JSON 仅比较 .result 字段
# 修复 SOL FAIL #2 -002 阻断 "pre-flight 把完整 JSON 与 "pass" 比较，永远无法放行"
VERIFY_JSON=$(uv run python3 "${PROJECT_ROOT}/scripts/verify_p3_first_daily.py" \
  --app-support-dir "${HOME}/Library/Application Support/MyAIEmployee" \
  2>>"$ERR_LOG" || echo '{"result": "error"}')
VERIFY_RESULT=$(printf '%s' "$VERIFY_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result', 'error'))" 2>>"$ERR_LOG" || echo "error")
if [ "$VERIFY_RESULT" != "pass" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) P3 pre-flight FAIL (result=$VERIFY_RESULT); skip" >>"$ERR_LOG"
  exit 0
fi

# 零预算 wrapper：直接调本地 watch_p3_ops.py 而非 claude
# 修复 SOL FAIL #2 -006 阻断 "$12/天 不符合零预算诊断口径"
exec uv run python3 "${PROJECT_ROOT}/scripts/watch_p3_ops.py" \
  --app-support-dir "${HOME}/Library/Application Support/MyAIEmployee" \
  2>>"$ERR_LOG"
