# P3 Claude Code 编排插件

本插件只编排既有 P3 脚本，不控制 Cursor GUI。

- `/p3-watch`：两小时巡检；默认仅诊断，传入 `--repair` 才允许处理可复现的项目内脚本问题。
- `/p3-rollover`：首日报门槛后执行安全归档和新 Day0 初始化。

本地临时加载：

```bash
claude --plugin-dir plugins/p3-ops-claude
```

`ops/claude-p3-watch-launchd.plist.example` 只是未安装模板；运行 `ops/run-claude-p3-watch.sh` 时使用 `dontAsk`，因此不会进行自动修复或外部写入。
