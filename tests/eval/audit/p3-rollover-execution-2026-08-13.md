# P3 rollover 执行报告 — 2026-08-13

## 授权

- 关键词：用户发送「授权 rollover」
- Day0 执行前核验：`started_at=2026-07-30T07:04:45.527698+00:00`（与约定一致）
- 归档碰撞：`epoch-2026-07-30T07-04-45Z` 执行前不存在

## 备份（§5.1）

- 路径：`~/Library/Application Support/MyAIEmployee/burn-in.backup-2026-08-13T08-42-00Z`
- 文件数：27 / 27 与源树一致
- `state.json` md5：`618a31322c4bb16766cc7fd9b54f399b`
- 备份仍在，未被 rollover 移动

## 执行

- 命令：`python3 scripts/p3_rollover_epoch.py`（无 `--force`）
- 文件系统结果：**已归档 + 已开新 Day0**
- CLI 当时 exit=1：`watch_once() got an unexpected keyword argument 'app_support_dir'`
  （撞坑 #107；发生在 `os.replace` 与 `start_burn_in` 成功之后，未回滚）

## 结果

| 项 | 值 |
| --- | --- |
| archive_path | `~/Library/Application Support/MyAIEmployee/burn-in-archive/epoch-2026-07-30T07-04-45Z` |
| 旧 Day0 | `2026-07-30T07:04:45.527698+00:00`（仅在 archive / backup） |
| new_day0 | `2026-08-13T08:42:06.833689+00:00` |
| report.status | `collecting` |
| report.attention | `[]` |
| watch.burn_in.status | `collecting` |
| Dashboard `/health` | HTTP 200，`ok=true`，`read_only=true` |
| first_daily_gate | `2026-08-15T00:00:00+00:00` |

未二次执行 rollover。未改 LaunchAgent / SMTP / Feature Flag。

## 回滚 SOP（仅当新 Day0 异常时使用，本次不执行）

```bash
rm -rf "$HOME/Library/Application Support/MyAIEmployee/burn-in"
cp -a "$HOME/Library/Application Support/MyAIEmployee/burn-in-archive/epoch-2026-07-30T07-04-45Z" \
      "$HOME/Library/Application Support/MyAIEmployee/burn-in"
```

或从备份恢复：

```bash
rm -rf "$HOME/Library/Application Support/MyAIEmployee/burn-in"
cp -a "$HOME/Library/Application Support/MyAIEmployee/burn-in.backup-2026-08-13T08-42-00Z" \
      "$HOME/Library/Application Support/MyAIEmployee/burn-in"
```

## 下一棒

- 新 7d 门最早约 `2026-08-20T08:42:06Z`；30d 约 `2026-09-12T08:42:06Z`
- 首份日报门：`2026-08-15T00:00:00Z`
- v1.1-A 仍须等新 epoch 证据，不因本次 rollover 立即解锁
