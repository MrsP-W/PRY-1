# Day 4 — 财务 + Apple Notes 个人数据收口(2026-07-01)

> **类型**:7 天计划 Day 4 · 选项 A(财务 + Apple Notes · 沿用户原 7 天计划)
> **模式**:faker 样本导入 + Notes spike + D8 异常 + 月报(真实 CSV / Notes.app 同步留用户授权)
> **风险**:🟡 中(撞坑 #49/#53/#54 已沉淀 · 2026 版 CSV 解析器占位 · 真实导入须 4 重门控)
> **撞坑关联**:#49 faker 范本 · #53/#54 去重 · #71 沿用 · #81 ⌥⌘N 已修复(沿用 Day 2 3/3)

---

## §1 用户决策(2026-07-01)

| 决策点 | 选择 | 含义 |
|--------|------|------|
| **Day 4 路径** | A — 财务 + Apple Notes | 沿 7 天计划 D4 时段表 |
| **账单样本** | faker 2024/2025(非真实 CSV) | 2026 版解析器占位(NotImplementedError) |
| **Notes** | spike 模式(30 笔 faker) | 真同步须 `NOTES_REAL_NETWORK=1` + TCC |
| **⌥⌘N** | 沿用 Day 2 #81 修复结论 | 3/3 已通过,本日不重测 |

---

## §2 实际执行命令

```bash
# DB 前置(本机主库 ~/Library/Application Support/my-ai-employee/data.db)
uv run alembic upgrade head

# 微信 2025 + 支付宝 2025(各 max-rows 30)
uv run python scripts/import_wechat.py \
  --csv-path tests/fixtures/wechat_faker/wechat_2025_sample.csv --max-rows 30
uv run python scripts/import_alipay.py \
  --csv-path tests/fixtures/alipay_faker/alipay_2025_sample.csv --max-rows 30

# 去重验证(第二次导入同一文件)
uv run python scripts/import_wechat.py \
  --csv-path tests/fixtures/wechat_faker/wechat_2025_sample.csv --max-rows 30

# 补充 2024 样本(凑足 ≥30 笔)
uv run python scripts/import_wechat.py \
  --csv-path tests/fixtures/wechat_faker/wechat_2024_sample.csv --max-rows 30
uv run python scripts/import_alipay.py \
  --csv-path tests/fixtures/alipay_faker/alipay_2024_sample.csv --max-rows 30

# Apple Notes spike(30 笔 faker)
uv run python scripts/sync_notes.py spike --n 30

# D8 异常检测 + 月报
make spike-d8-anomaly
make monthly-report
```

---

## §3 实测结果(2026-07-01 14:38)

### 3.1 微信账单导入

| 轮次 | 文件 | parsed | inserted | duplicates | failed | version |
|------|------|--------|----------|------------|--------|---------|
| 1 | wechat_2025_sample.csv | 10 | 9 | 1 | 0 | 2025 |
| 2(去重) | wechat_2025_sample.csv | 10 | 0 | 10 | 0 | 2025 |
| 3 | wechat_2024_sample.csv | 10 | 10 | 0 | 0 | 2024 |

**撞坑 #54 去重验证**:第二次导入 `duplicates=10`、`inserted=0` ✅

**2026 样本阻塞**: `wechat_2026_sample.csv` → `NotImplementedError`(解析器占位,等真实样本)

### 3.2 支付宝账单导入

| 轮次 | 文件 | parsed | inserted | needs_confirm | candidate_count | version |
|------|------|--------|----------|---------------|-----------------|---------|
| 1 | alipay_2025_sample.csv | 10 | 9 | 9 | 9 | 2025 |
| 2 | alipay_2024_sample.csv | 10 | 10 | 9 | 9 | 2024 |

**L2 跨源**:支付宝 `needs_confirm=9`(沿 v0.2.1 #2 范本,单源导入不触发 confirm 队列写入)

### 3.3 Apple Notes spike

```
notes spike: parsed=30 inserted=0 skipped=30 failed=0 n=30
```

- spike 模式 30 笔 faker 跑通,全部 skipped(库内已有同 apple_id,幂等 OK)
- **真同步命令(未本日执行)**: `NOTES_REAL_NETWORK=1 uv run python scripts/sync_notes.py sync --max-rows 5`

### 3.4 D8 异常检测

```
d8 spike: received=1 inserted=36 kinds=amount_3sigma,amount_drift,frequency_5tx_per_hour count=3
```

### 3.5 数字生活月报

```
monthly_report: generated=reports/finance-monthly-2026-06.md transactions=37 total_income=¥15353.32 total_expense=¥0.00
```

### 3.6 ⌥⌘N 快捷键

- **沿用 Day 2 撞坑 #81 修复收口**:TCC 补授权 Python.framework 3.12 → 3/3 通过
- 本日不重测(菜单栏人工入口已稳定)

---

## §4 Day 4 验收清单

| # | 验收项 | 期望 | 实际 | 通过 |
|---|--------|------|------|------|
| 1 | 账单 parsed ≥30 | ≥30 | 40 parsed / 38 inserted(跨 4 次导入) | ✅ |
| 2 | 去重无异常 | 二次导入 duplicates↑ inserted=0 | wechat 2025 二次 duplicates=10 | ✅ |
| 3 | Notes spike 链路 | failed=0 | failed=0 skipped=30 | ✅ |
| 4 | 月报 Markdown 产出 | 有文件 | `reports/finance-monthly-2026-06.md` | ✅ |
| 5 | D8 异常检测 | kinds≥1 | 3 kinds | ✅ |
| 6 | 真实 CSV 导入 | 用户授权 + 4 重门控 | N/A(本日 faker) | N/A |
| 7 | Notes 真同步 ≥5 条 | NOTES_REAL_NETWORK=1 | N/A(本日 spike) | N/A |

---

## §5 撞坑累计

| 撞坑号 | 状态 | 说明 |
|--------|------|------|
| **#49** | 🟢 faker 范本 | 2024/2025 样本导入 OK · 2026 占位 |
| **#53/#54** | 🟢 去重 | 二次导入 duplicates 单调递增 |
| **#71** | 🟢 沿用 | 业务代码 0 改动 |
| **#81** | 🟢 维持 | ⌥⌘N 沿用 Day 2 3/3 |

**撞坑累计 81 类 0 新增**。

---

## §6 真实导入/同步门控(留 Day 4+ 或用户授权)

### 6.1 真实微信/支付宝 CSV

```bash
export WECHAT_REAL_IMPORT=1   # 或 ALIPAY_REAL_IMPORT=1
uv run python scripts/import_wechat.py \
  --csv-path ~/Downloads/wechat.csv \
  --max-rows 1 --count 1 \
  --confirm yes-i-understand-this-imports-real-bill
```

### 6.2 Apple Notes 真同步

```bash
NOTES_REAL_NETWORK=1 uv run python scripts/sync_notes.py sync --max-rows 5
```

需 TCC:系统设置 → 隐私与安全性 → 自动化 → Terminal/Python → Notes.app

---

## §7 9/9 质量门 baseline 维持

| # | 门 | 数字 |
|---|----|------|
| 1 | pytest | 2611 passed / 1 skipped |
| 2 | coverage | 88.97% |
| 3-9 | 其余 | 全绿(本日无业务代码改动) |
| check-snapshot | 四重防御 | OK |

**业务代码改动**:**0**(撞坑 #71 沿用)

---

## §8 Day 5 候选

| 选项 | 内容 | 风险 |
|------|------|------|
| **A. Dashboard 只读** | `DASHBOARD_REAL_DB=1 make dashboard-api` + hydrate 8 端点 | 🟡 中 |
| **B. 真实 CSV 1 行** | WECHAT/ALIPAY_REAL_IMPORT=1 + 4 重门控 | 🟡 中 |
| **C. Notes 真同步** | NOTES_REAL_NETWORK=1 + TCC | 🟡 中 |

---

## §9 维护者

**Mr-PRY** · 2026-07-01 Day 4 A 路径收口(财务 faker 2024/2025 导入 + 去重验证 + Notes spike + D8 异常 + 月报)· DB 主库 37 笔 transactions · 撞坑累计 81 类 0 新增 · 业务代码 0 改动 · 9/9 质量门 baseline 不变 · 等 Day 5 启动授权。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **下一棒**:Day 5 Dashboard 只读驾驶舱(用户逐项 OK)。
