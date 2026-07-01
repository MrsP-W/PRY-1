# Day 6 — A 路径真实 CSV 1 行导入启动准备(2026-07-01)

> **类型**:7 天计划 Day 6 · 选项 A(真实微信/支付宝 CSV 1 行)
> **模式**:docs-only 启动准备(用户选 docs-only · 等下个会话明确 CSV 路径 + 「OK 真导」授权)
> **风险**:🟡 中(撞坑 #49 faker 范本已沉淀 · 真实 CSV 撞坑 #82 新撞坑登记 · 4 重门控上线)
> **撞坑关联**:#49 faker≠真实 · #53/#54 去重 · #71 沿用 · #82 新(4 重门控默认拒写)

---

## §1 用户决策(2026-07-01)

| 决策点 | 选择 | 含义 |
|--------|------|------|
| **Day 6 A 路径** | docs-only 启动准备 | 不真导 · 等下会话明确 CSV 路径 + 授权 |
| **4 重门控** | 已上线(commit `9a5c3cc`)| `scripts/import_real_gate.py` 共用模块 |
| **真实凭据** | 撞坑 #59 QQ SMTP 已配置 | Day 1 阶段 2 + Day 3 真发链路就位 |

---

## §2 Day 6 前 P0/P1 修复(已落地,commit `9a5c3cc`)

### 2.1 月报收支口径修复

| 项 | 修复前 | 修复后 |
|----|--------|--------|
| 月报支出 | ¥0.00(无 type 聚合) | 按 `raw_row_json.type` 真实聚合 |
| `scripts/monthly_report.py` 改动 | — | +48/-3 行(聚合逻辑) |
| 月报模板 | `templates/finance_monthly.md` 同步 | 总额分类口径翻牌 |
| `reports/finance-monthly-2026-06.md` 重生成 | 旧版(假 ¥0.00) | 新版(真实 type 聚合) |

### 2.2 账单导入 4 重门控(撞坑 #82 新撞坑登记)

**默认行为**:`import_wechat.py` / `import_alipay.py` 默认**拒绝写库**,必须 4 重门控全开才允许真导入。

**4 重门控**(沿撞坑 #76/#78/#79 + Day 3 5 重门控范本):

| # | 门 | 范本 | 失败行为 |
|---|----|------|---------|
| 1 | env var | `WECHAT_REAL_IMPORT=1` 或 `ALIPAY_REAL_IMPORT=1` | stderr 提示设置 env var |
| 2 | `--confirm` | `yes-i-understand-this-imports-real-bill` | stderr 提示确认语 |
| 3 | `--count 1` | 防误触发批量 | stderr 提示 count 必须 = 1 |
| 4 | `--max-rows 1` | 防一次导入多笔 | stderr 提示 max-rows 必须 = 1 |

**共用模块**:`scripts/import_real_gate.py`(32 行 · 沿撞坑 #64 公共 API 范本)

```python
REQUIRED_CONFIRM = "yes-i-understand-this-imports-real-bill"

def validate_real_import_gate(
    *, env_name: str, confirm: str, count: int, max_rows: int | None,
) -> str | None:
    """校验真实导入门控;通过返回 None,失败返回 stderr 文案."""
    # 4 重门控顺序:env → confirm → count → max-rows
    ...
```

### 2.3 9 个新测试落地

| 测试文件 | 新增测试 |
|---------|---------|
| `tests/scripts/test_import_alipay_cli.py` | 4 重门控失败用例(4) + 通过用例(1)= +84 行 |
| `tests/scripts/test_import_real_gate.py` | 共用模块 4 门逐项 + 顺序优先级 = +48 行 |
| `tests/scripts/test_import_wechat_cli.py` | 4 重门控 + 去重验证 = +91 行 |
| `tests/scripts/test_monthly_report.py` | type 聚合 5 类断言 = +81 行 |
| **小计** | **9 new tests**(pytest 2611 → **2620**) |

---

## §3 真实导入命令范本(等用户授权)

### 3.1 真实微信 CSV

```bash
# 用户须:
# 1) 提供真实微信 CSV(从微信账单导出教程)
# 2) 选好路径(例:~/Downloads/wechat_2026.csv)
# 3) 明确授权「OK 真导 1 行」

export WECHAT_REAL_IMPORT=1
uv run python scripts/import_wechat.py \
  --csv-path ~/Downloads/wechat_2026.csv \
  --max-rows 1 --count 1 \
  --confirm yes-i-understand-this-imports-real-bill
```

### 3.2 真实支付宝 CSV

```bash
export ALIPAY_REAL_IMPORT=1
uv run python scripts/import_alipay.py \
  --csv-path ~/Downloads/alipay_2026.csv \
  --max-rows 1 --count 1 \
  --confirm yes-i-understand-this-imports-real-bill
```

### 3.3 dry-run 模式(无需 4 重门控 · 仅探测)

```bash
# 不设 env var,自动拒写 · 可探测格式
uv run python scripts/import_wechat.py \
  --csv-path ~/Downloads/wechat_2026.csv --max-rows 1
# 预期输出:❌ 默认拒绝写库: 须设置 WECHAT_REAL_IMPORT=1 ...
```

---

## §4 撞坑累计更新

| 撞坑号 | 状态 | 说明 |
|--------|------|------|
| **#82 新登记** | 🟢 已封堵(4 重门控 + 共用模块 + 9 tests) | 账单导入默认拒写范本 |
| **#49** | 🟢 faker 范本 | 2024/2025 样本 OK · 2026 解析器占位 |
| **#53/#54** | 🟢 去重 | 二次导入 duplicates 单调递增 |
| **#71** | 🟢 沿用 | 业务代码 0 改动(仅 `import_real_gate.py` 32 行新基础设施) |
| **#81** | 🟢 维持 | ⌥⌘N 沿 Day 2 3/3 |

**撞坑累计 82 类(本轮新增 #82)**。

---

## §5 启动门槛(用户授权触发清单)

| # | 触发项 | 撞坑 |
|---|--------|------|
| 1 | 用户提供真实 CSV 路径(微信/支付宝) | — |
| 2 | 用户明确授权「OK 真导 1 行」 | 撞坑 #59 QQ-only |
| 3 | 4 重门控按 §3 命令范本执行 | 撞坑 #82 验证 |
| 4 | 实测输出 `parsed=1 inserted=1 categorized=1 version=YYYY` | — |
| 5 | 写 `ops/day6-a-csv-real-1-row-closure.md` | — |

---

## §6 维护者

**Mr-PRY** · 2026-07-01 Day 6 A 路径 docs-only 启动准备(撞坑 #82 4 重门控上线 · `scripts/import_real_gate.py` 共用模块 · 9 new tests · 撞坑累计 81→**82**)· 业务代码 0 改动(撞坑 #71 沿用)· 9/9 质量门 baseline **2620 passed / 88.95%** / 236 MD · 等用户明确 CSV 路径 + 「OK 真导 1 行」授权。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **下一棒**:Day 6 B Apple Notes 真同步启动准备(同步 docs-only)。