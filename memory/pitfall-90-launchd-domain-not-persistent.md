# 撞坑 #90 — launchd user-agent job 不跨 session 持久化

> 日期:2026-07-08
> 范围:P3-A T3 launchd 盘点 / `gui/$UID` LaunchAgents
> 性质:user domain 注册在 logout/reboot 后丢失,plist 文件仍在

## 现象

`docs/v0.2.67` 报告 agent + imap-sync 2/3 已 `load -w` 注册;约 9.5 小时后复测 `launchctl list | grep myaiemployee` 变为 **0/3**。plist 文件与 `print-disabled` enabled 状态仍在。

## 根因

- `launchctl load -w` 注册到 **user domain `gui/$UID`**,该 domain 随用户 session 生命周期清空。
- logout / reboot 后需重新 `launchctl load -w` 各 plist。
- `Load failed: 5: Input/output error` 在已注册场景下可能是 false alarm(list 仍可见 job)。

## 修复候选(D-step 评估,本会话不落地)

| # | 路径 | 风险 |
|---|------|------|
| A | reboot 后手动 `load -w × 3`(当前范本) | 🟢 低 |
| B | Login 后脚本 / `~/.zshrc` 末尾 re-load | 🟡 写 shell profile 需授权 |
| C | `sudo launchctl bootstrap` 到 system domain | 🔴 高权限 |
| D | 文档 runbook 明示「每次登录后 re-load」 | 🟢 docs-only |

## 验证命令

```bash
launchctl list | grep myaiemployee
launchctl print-disabled "gui/$(id -u)" | grep myaiemployee
ls ~/Library/LaunchAgents/com.myaiemployee.*.plist
```

## 关联

- `docs/v0.2.71-p3-a-t3-launchd-audit-2026-07-08.md`
- 撞坑 #81(历史误判入口) / #91(数字员工真实根因)
