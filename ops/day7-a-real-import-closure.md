# Day 7 — A 路径真实账单 1 行导入收口(2026-07-01)

> **类型**:7 天计划 Day 7 · 选项 A(真实微信/支付宝各真导 1 行)
> **模式**:微信 ✅ 真导 1 行 · 支付宝 ⏸️ zip 解压密码待用户提供
> **撞坑关联**:#82 4 重门控 · #49 真实格式(微信 xlsx≠CSV · 表头混 2024/2025)

---

## §1 用户提供的文件

| 来源 | 路径 | 格式 | 状态 |
|------|------|------|------|
| 支付宝 | `~/Desktop/支付宝交易明细(20260524-20260624).zip` | ZIP(内含 CSV) | ⏸️ **加密 zip**,需解压密码 |
| 微信 | `~/Desktop/微信支付账单流水文件(20260401-20260701)_20260701173433.xlsx` | XLSX | ✅ 已转 CSV 并真导 1 行 |

---

## §2 微信真导(✅ 完成)

### 2.1 格式发现

- 官方导出为 **xlsx**,非教程中的 zip+csv;前 15 行为说明段,第 16 行起为数据。
- 表头:`交易时间, 交易类型, 交易对方, 商品, 收/支, 金额(元), …, 交易单号`(混 2024/2025 字段)。
- `交易时间`为 Excel 序列号,须转 `YYYY-MM-DD HH:MM:SS` 后导入。
- 嗅探为 **2025 parser**(`交易单号` 独有字段);`收/支` 映射为 `收/付`。

### 2.2 转换(本地 spike,不入库)

```bash
# 输出至 output/spike/day7-real/wechat_real_converted.csv(gitignore)
# 144 行有效交易(跳过 收/支=/ 的中性行)
```

### 2.3 4 重门控真导命令

```bash
WECHAT_REAL_IMPORT=1 uv run python scripts/import_wechat.py \
  --csv-path output/spike/day7-real/wechat_real_converted.csv \
  --max-rows 1 --count 1 \
  --confirm yes-i-understand-this-imports-real-bill
```

### 2.4 实测结果(2026-07-01 17:37)

```text
wechat import: parsed=1 inserted=1 categorized=1 duplicates=0 needs_confirm=0 failed=0 candidate_count=0 version=2025
```

**DB 末行**(主库 `~/Library/Application Support/my-ai-employee/data.db`):

| 字段 | 值 |
|------|-----|
| id | 90 |
| source | wechat |
| external_transaction_id | 4500000253202606303788041246 |
| amount | 33.15 |
| category | other |
| status | categorized |

---

## §3 支付宝(⏸️ 阻塞:zip 密码)

```text
unzip: skipping ... unable to get password
```

**下一步(需用户)**:

1. 查收支付宝导出邮件中的 **解压密码**(通常为身份证后 6 位,以邮件正文为准)。
2. 解压 zip 得到 CSV(文件名类似 `支付宝交易明细(20260524-20260624).csv`)。
3. 执行:

```bash
ALIPAY_REAL_IMPORT=1 uv run python scripts/import_alipay.py \
  --csv-path <解压后CSV绝对路径> \
  --max-rows 1 --count 1 \
  --confirm yes-i-understand-this-imports-real-bill
```

预期嗅探为 **2027 parser**(`交易时间` + `交易订单号`,沿撞坑 #49)。

---

## §4 Day 7 B(未启动)

Notes 真同步 5 条仍须:`NOTES_REAL_NETWORK=1` + TCC 自动化授权 + 用户明确 OK。

---

## §5 维护者

**Mr-PRY** · 2026-07-01 Day 7 A 部分收口(微信 ✅ · 支付宝待 zip 密码) · 4 重门控验证通过 · 业务代码 0 改动。
