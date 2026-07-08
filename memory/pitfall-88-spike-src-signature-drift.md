# 撞坑 #88 — spike 与 src API / 状态机漂移

> 日期:2026-07-08
> 范围:P3-C dry-run / `scripts/spike_outbox_100.py`
> 性质:spike 脚本滞后于 `src` 层 API 与状态机契约

## 现象

`scripts/spike_outbox_100.py` 首跑时连续暴露两类漂移:

1. `OutboxStore.update_status()` 缺少必传关键字 `from_status`。
2. spike 旧路径直接执行 `approved → sent`,但当前状态机要求 `approved → sending → sent`。

## 根因

- D5.2 后 `update_status` 增加 `from_status`,用于防止并发状态漂移。
- D5.6.3 P1-1 后 `approved` 状态需要写入 `last_approved_at_ms`。
- 当前 `ALLOWED_TRANSITIONS` 不允许 `approved → sent` 直跳,必须经 `sending`。

## 修复范本

```python
now_ms = int(time.time() * 1000)

row = outbox_store.update_status(
    outbox_id,
    OutboxStatus.APPROVED.value,
    from_status=OutboxStatus.PENDING_SEND.value,
    last_approved_at_ms=now_ms,
)
assert row.status == "approved"

row = outbox_store.update_status(
    outbox_id,
    OutboxStatus.SENDING.value,
    from_status=OutboxStatus.APPROVED.value,
    last_approved_at_ms=None,
)
assert row.status == "sending"

row = outbox_store.update_status(
    outbox_id,
    OutboxStatus.SENT.value,
    from_status=OutboxStatus.SENDING.value,
    last_approved_at_ms=None,
)
assert row.status == "sent"
```

## 后续检查

1. 任何 `scripts/spike_*.py` 调 `OutboxStore.update_status` 时,先 grep `from_status=`。
2. 状态机模拟不要跳过 `sending`。
3. 更新 spike 后必须跑对应 spike + `make check-snapshot`。
4. 若新增 Markdown,同步 `quality_snapshot.py` 的 MD lint 计数与入口文档。
