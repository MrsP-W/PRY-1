---
description: 执行 P3 两小时巡检；只在需要时诊断或提出受控修复
argument-hint: "[--repair]"
allowed-tools: Bash(python3 scripts/watch_p3_ops.py), Bash(uv run pytest tests/scripts/test_watch_p3_ops.py -q), Bash(uv run pytest tests/scripts/test_verify_p3_first_daily.py -q), Read
---

在项目根目录执行 `python3 scripts/watch_p3_ops.py`，并以 JSON 输出作为唯一事实源。

- `burn_in.attention=[]`、`dashboard_health.ok=true` 且 `stderr.delta_vs_baseline.new_recent_hits=[]`：简报后停止，不改任何文件。
- 否则先只读定位：说明哪一项异常、影响和最小复现命令；默认不修复。
- 只有用户显式传入 `--repair` 时，才可修复可复现的项目内 P3 脚本缺陷；先运行对应最小测试，修复后再运行同一测试和本巡检命令。
- 永远不得使用 `verify_p3_first_daily.py --force`，不得修改 LaunchAgent/调度、SMTP、P3 状态目录或 Cursor GUI。
- 不处理日志中可能出现的凭据；输出只引用状态码、原因码和脱敏摘要。
