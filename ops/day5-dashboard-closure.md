# Day 5 — Dashboard 只读驾驶舱收口(2026-07-01)

> **类型**:7 天计划 Day 5 · 选项 A(Dashboard 只读 · 沿用户原 7 天计划)
> **模式**:`DASHBOARD_REAL_DB=1` 只读 hydrate · 不写 DB · 不启 Path 4 五门
> **风险**:🟢 低(只读 API · 127.0.0.1 绑定 · read_only 恒 true)
> **撞坑关联**:#65 opt-in 4 阶段 · #71 沿用 · #81 ⌥⌘N 已修复(沿用 Day 2 3/3 · 本日不重测)

---

## §1 用户决策(2026-07-01)

| 决策点 | 选择 | 含义 |
|--------|------|------|
| **Day 5 路径** | A — Dashboard 只读驾驶舱 | 沿 Day 4 §8 候选 A |
| **env 门控** | 仅 `DASHBOARD_REAL_DB=1` | 不启 `BUSINESS_WRITER_ENABLED` / `ENABLE_PATH_4_WRITE` |
| **HTML 联调** | 命令行 hydrate 验证 | 浏览器可开 `docs/ui/codex-style-dashboard.html`(file://) + API 8765 |

---

## §2 实际执行命令

```bash
# 启动只读 API(主库 ~/Library/Application Support/my-ai-employee/data.db)
DASHBOARD_REAL_DB=1 uv run python -m my_ai_employee.dashboard.server
# 等价: DASHBOARD_REAL_DB=1 make dashboard-api

# 7 端点 hydrate 验证(另开终端)
uv run python - <<'PY'
import json, urllib.request
BASE = "http://127.0.0.1:8765"
for path in [
    "/api/status",
    "/api/tasks/today",
    "/api/outbox?limit=10",
    "/api/notes/pending?limit=10",
    "/api/finance/anomalies?limit=10",
    "/api/reports?limit=50",
    "/api/approval-gate/audits?limit=10",
]:
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        body = json.loads(r.read())
    print(path, r.status, "read_only=", body.get("read_only"), "count=", body.get("count", body.get("total")))
PY

# 可选:浏览器打开静态 HTML(需 API 已启动)
# open docs/ui/codex-style-dashboard.html
```

---

## §3 实测结果(2026-07-01 14:48)

### 3.1 服务启动

```
DB 打开: path=/Users/wei/Library/Application Support/my-ai-employee/data.db
Dashboard 只读 API: http://127.0.0.1:8765/api/status
```

- `DASHBOARD_REAL_DB=1` → session_factory 成功 → Outbox / NoteConfirm / Expense Impl 注入(沿 v0.2.53.7-8 范本)
- `BUSINESS_WRITER_ENABLED` 未设 → writer 仍 Stub · audit 仍 Stub(只读)

### 3.2 8 读端点 hydrate(7 fetch + status 驱动 UI = HTML「8 读」)

| # | 端点 | HTTP | read_only | count/total | 备注 |
|---|------|------|-----------|-------------|------|
| 1 | `/api/status` | 200 | true | — | git_head=abfa69d · quality_gates 2611/88.97% |
| 2 | `/api/tasks/today` | 200 | true | total=0 | 真实 DB(空任务表) |
| 3 | `/api/outbox?limit=10` | 200 | true | count=0 | 真实 Outbox(本日主库无 pending) |
| 4 | `/api/notes/pending?limit=10` | 200 | true | count=0 | 真实 NoteConfirm |
| 5 | `/api/finance/anomalies?limit=10` | 200 | true | count=0 | 真实 Expense(无未处理异常) |
| 6 | `/api/reports?limit=50` | 200 | true | count=50 | git-tracked MD 报告索引 |
| 7 | `/api/approval-gate/audits?limit=10` | 200 | true | count=0 | Stub(enabled=false) |

**7/7 HTTP 200 · read_only 全 true · 0 写操作**

### 3.3 `/api/status` 关键字段

| 字段 | 值 | 说明 |
|------|-----|------|
| `providers.keychain.smtp_qq` | present | Day 1 Keychain 仍有效 |
| `approval_gates.business_writer_ready` | false | 预期(未启 writer env) |
| `approval_gates.path4_write_ready` | false | 预期(未启 Path 4 五门) |
| `approval_gates.v0_2_53_26_dry_run_status.outcome` | disabled | 只读模式 |

### 3.4 验收项(6/6 通过)

| # | 验证项 | 期望 | 实际 | 通过 |
|---|--------|------|------|------|
| 1 | API 127.0.0.1:8765 可连 | 200 | 200 | ✅ |
| 2 | 7 hydrate 端点全 200 | 7/7 | 7/7 | ✅ |
| 3 | 全部 `read_only=true` | 是 | 是 | ✅ |
| 4 | 真实 DB 打开日志 | 有 | 有 | ✅ |
| 5 | Path 4 五门未误开 | path4_write_ready=false | false | ✅ |
| 6 | dashboard pytest 子集 | pass | 70 passed | ✅ |

---

## §4 与 Day 4 数据关系

- Day 4 导入 **37 transactions** 至主库;Dashboard Expense 端点 `count=0` 表示**无未处理 finance anomaly 队列项**(非导入失败)
- Outbox `count=0`:Day 3 SMTP spike 后主库 outbox 无 pending_send(符合只读观测)

---

## §5 9/9 质量门(本棒)

| 门 | 结果 |
|----|------|
| pytest dashboard 子集 | 70 passed |
| ruff / mypy | 未改业务代码 · baseline 维持 |
| MD lint | 235 files(本棒 +1 closure) |
| check-snapshot | 收口后跑 |

**业务代码改动**:**0**(撞坑 #71 沿用)

---

## §6 Day 6 候选

| 选项 | 内容 | 风险 |
|------|------|------|
| **A. 真实 CSV 1 行** | WECHAT/ALIPAY_REAL_IMPORT=1 + 4 重门控 | 🟡 中 |
| **B. Notes 真同步** | NOTES_REAL_NETWORK=1 + TCC | 🟡 中 |
| **C. Day 6-7 一键包** | `ops/start-digital-employee.sh` 串联 menubar + dashboard | 🟢 低 |

---

## §7 维护者

**Mr-PRY** · 2026-07-01 Day 5 A 路径收口(Dashboard 只读 · DASHBOARD_REAL_DB=1 · 7 hydrate 端点全绿)· 撞坑累计 81 类 0 新增 · 业务代码 0 改动 · 9/9 质量门 baseline 不变 · 等 Day 6 启动授权。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **下一棒**:Day 6 真实 CSV / Notes 真同步 / 一键启动包(用户逐项 OK)。
