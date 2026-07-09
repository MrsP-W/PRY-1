# 撞坑 #91 — macOS `~/Documents/` 对 sh exec 的 OS 层拦截

> 日期:2026-07-08
> 范围:P3-A T3 数字员工 launchd / `ops/start-digital-employee.sh`
> 性质:打破 docs/v0.2.67 对撞坑 #81 的「TCC Python.framework」误判

## 现象

```text
bash: /Users/wei/Documents/DesktopOrganizer/我的AI员工/ops/start-digital-employee.sh: Operation not permitted
```

- 出在 **bash exec 脚本路径** 一步,不是 Python 解释器启动后。
- `~/bin/my-ai-employee-start` → `exec bash ".../ops/start-digital-employee.sh"`。
- 数字员工 plist 仍 bootout;`agent` / `imap-sync` 可注册。

## 根因

- 仓库位于 `~/Documents/...`(常为 iCloud Desktop & Documents 同步树)。
- launchd / 受限上下文对同步目录内 `.sh` 的 **OS 层 exec** 可能返回 `Operation not permitted`。
- 这与「Python.framework TCC 弹窗 / exit 126」不是同一条证据链。

## 修复候选(D-step 评估,本会话不落地)

| # | 路径 | 风险 | 推荐 |
|---|------|------|------|
| A | 将 start 脚本/工作副本放到非 Documents 路径(如 `~/bin` / `~/my-ai-employee`)并改 wrapper | 🟢 | ✅ 首选 |
| B | wrapper 用 `bash < script` / `cat \| bash`(非直接 exec 路径) | 🟡 | 次选 |
| C | `osascript` 包一层 | 🟡 仍可能撞 TCC | 不优先 |
| D | 手改 TCC DB Allow | 🔴 | 绝不 |

## 验证命令

```bash
cat ~/Library/Logs/MyAIEmployee/digital-employee.err.log
bash -n ops/start-digital-employee.sh
# 勿在未授权时: launchctl load -w ...digital-employee.plist
```

## 关联

- `docs/v0.2.71-p3-a-t3-launchd-audit-2026-07-08.md`
- `docs/v0.2.67-p2-install-2026-07-08.md`(历史误判入口,不改历史正文)
- 撞坑 #81 / #90
