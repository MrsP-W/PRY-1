---
description: 在首份日报门槛后安全归档当前 P3 epoch 并启动新 Day0
argument-hint: ""
allowed-tools: Bash(python3 scripts/p3_rollover_epoch.py), Read
---

执行 `python3 scripts/p3_rollover_epoch.py`，并原样读取其 JSON 结果。

- 脚本内置首日报时间门，绝不使用 `--force`。
- `too_early`、`not_started` 或 `archive_target_exists` 时停止；绝不覆盖、删除或手工移动目录。
- 其他已过门槛的 verify 结果（包括 `fail_attention`）按既定 P3 治理策略归档旧 epoch 后新开 Day0。
- 结束时简报：日报核验结论、归档路径、新 Day0 时间、health/news attention。
- 不修改 LaunchAgent/调度、SMTP、WIP、git 或 Cursor GUI。
