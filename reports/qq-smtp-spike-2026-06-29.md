# QQ SMTP 真实 1 封 spike 收口(2026-06-29)

> **状态**:✅ **sent=1/4.31s** — QQ 真实 SMTP 端到端复验通过
> **范围**:OutboxDispatcher + Keychain + smtp.qq.com:465 SSL · 自发自收 1 封
> **边界**:Outlook/Gmail 未执行 · 不打 tag · 不接 BusinessWriter 实写

---

## 1. 执行命令

```bash
uv run python scripts/spike_set_smtp_password.py \
  --provider qq --email "477***009@qq.com" --check

SMTP_REAL_NETWORK=1 uv run python scripts/spike_send_100.py --real \
  --smtp-provider qq --count 1 --max-recipients 1 --batch-size 1 \
  --recipient "477***009@qq.com" \
  --confirm yes-i-understand-this-sends-real-email \
  --smtp-host smtp.qq.com --smtp-port 465 \
  --smtp-username "477***009@qq.com"
```

---

## 2. 五重防误发门控

| # | 门控 | 实测 |
|---|------|------|
| 1 | `SMTP_REAL_NETWORK=1` | ✅ |
| 2 | `--count 1` | ✅ |
| 3 | `--max-recipients 1` | ✅ |
| 4 | `--recipient` 白名单(自发自收) | ✅ |
| 5 | `--confirm yes-i-understand-this-sends-real-email` | ✅ |
| + | Keychain round-trip(16 chars,不打印) | ✅ |

---

## 3. 关键结果

| 维度 | 值 |
|------|-----|
| provider | qq |
| host | smtp.qq.com:465 SSL |
| from / to | 477***009@qq.com(脱敏) |
| total_picked | 1 |
| **sent** | **1** |
| technical_failed | 0 |
| duration | **4.31s**(调度延迟 ~4309ms) |
| 状态机 | PENDING_SEND → APPROVED → SENDING → SENT ✅ |
| Heartbeat | healthy |

**详细报告**(gitignore 本地):`output/spike/spike_send_100_20260629_140047.md`

---

## 4. vs D5.6.5 基线(2026-06-14)

| 维度 | D5.6.5 | 本棒 2026-06-29 |
|------|--------|----------------|
| sent | 1 | 1 ✅ |
| latency | 1.27s | 4.31s(网络波动,可接受) |
| 门控 | 4 重 + env | 5 重 + env ✅ |
| 链路 | OutboxDispatcher | 同链路复验 ✅ |

---

## 5. 8/1 readiness 影响

| # | 前置条件 | 本棒后 |
|---|----------|--------|
| 1 | QQ SMTP 送达 | ✅ **复验通过**(2026-06-29 · sent=1/4.31s) |
| 2 | outlook/gmail Keychain | ⏭️ **用户决策不配置**(2026-06-29 · 非阻塞) |
| 9 | outlook/gmail SMTP spike | ⏭️ **用户决策不配置**(2026-06-29 · 非阻塞) |

**SMTP 发布范围**:本项目 **QQ-only**;Outlook/Gmail 代码保留但不激活、不配置凭据。

**剩余 8/1 阻塞项**:路径 4 实写(8/1 后独立 launch) — 非 SMTP 缺口。

---

## 6. 下一棒

- 8/1 readiness 二次刷新 docs-only(QQ-only SMTP 口径)
- 7/10 WAIC 窗口 B 类延后项
- 路径 4 BusinessWriter 实写(8/1 后独立 launch)

---

## 7. 沿用边界

- ❌ 不配置 Outlook/Gmail Keychain(用户决策 2026-06-29)
- ❌ 不真发 Outlook/Gmail
- ❌ 不打 `v0.2.x` tag
- ❌ 不接真实 BusinessWriter / 不写 DB
- ✅ `write_executed` 生产路径仍恒 False(本 spike 走 OutboxDispatcher 测试链路)
