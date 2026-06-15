# 📊 数字生活月报 — {month}

> **生成时间**:{generated_at}
> **数据来源**:本地 SQLite (`data/v0.1.db` 表 `transactions`)
> **审计员**:@审计员(D10 启动 — 每月 1 号 09:00 自动触发)

---

## 💰 总览

| 维度 | 金额 | 同比上月 | 环比上月 |
|------|------|---------|---------|
| 收入 | ¥{total_income} | {income_mom} | {income_yoy} |
| 支出 | ¥{total_expense} | {expense_mom} | {expense_yoy} |
| 结余 | ¥{net_balance} | — | — |
| 交易笔数 | {transaction_count} | — | — |

---

## 📂 支出分类 Top 5

{category_breakdown}

---

## ⚠️ 异常高亮

{anomaly_highlights}

---

## 📝 备注

- 报告由 `@审计员` 自动生成(D10 启动)
- 通知频率:每月 ≤ 1 次(沿 week2-mvp.md L222 决策)
- 数据本地化:本机 `data/` 目录,**绝不上传**
- 下一棒:如需调整通知时间或分类规则,召唤 `@管家`
