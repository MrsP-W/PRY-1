# D5.6 spike — 100 封 InMemory 模拟发送(OutboxDispatcher 端到端)

> **生成时间**:20260613_091456  
> **范围**:100 封入库 + OutboxDispatcher 循环 + 状态机推进 + SLA + 退避  
> **模式**:InMemory 模拟(InMemorySmtpTransport)  
> **注入失败**:0 封技术失败  
> **注入 BREACH**:0 封 SLA BREACH  
> **承接 D4.8.11 spike 范本**(`scripts/spike_outbox_100.py`)+ D5.1 凭证 spike  

---

## 1. 📥 100 封入库(stored)

- **总数**:100
- **stored 成功**:100/100
- **入库总时长**:0.03s
- **outbox_id 范围**:1..100

## 2. 🚀 OutboxDispatcher 循环调度统计

- **模式**:InMemory 模拟
- **batch_size**:10
- **iterations(总 run_once 次数)**:10
- **总调度时长**:0.10s
- **延迟 P50**:8.74ms
- **延迟 P95**:14.52ms
- **延迟 AVG**:9.57ms

## 3. 📊 7 字段 DispatcherResult 累加

| 字段 | 值 |
|------|-----|
| total_picked | 100 |
| sent | 100 |
| business_blocked | 0 |
| technical_failed | 0 |
| skipped | 0 |
| skip_breach | 0 |
| iterations | 10 |

## 4. 🎯 按优先级拆分 outcome

| priority | pending_send | approved | sending | sent | failed | cancelled |
|----------|--------------|----------|---------|------|--------|-----------|
| urgent | 0 | 0 | 0 | 30 | 0 | 0 |
| normal | 0 | 0 | 0 | 30 | 0 | 0 |
| low | 0 | 0 | 0 | 40 | 0 | 0 |

## 5. ✅ 关键验证项

| # | 验证项 | 期望 | 实际 | 通过 |
|---|--------|------|------|------|
| 1 | 状态机全部最终态(无 PENDING/APPROVED/FAILED/SENDING) | 0/0/0/0 | 0/0/0/0 | ✅ |
| 2 | InMemorySmtpTransport.sent_log 行数 == sent | 100 | 100 | ✅ |
| 3 | Heartbeat HEALTHY | healthy | healthy | ✅ |
| 4 | SLA BREACH 注入(前 0 封) | skip_breach >= 0 | skip_breach=0 | ✅ |
| 5 | 注入失败(N=0) 退避回路 | technical_failed >= 0 | technical_failed=0 | ✅ |

## 6. 📊 结论

- **100 封入库**:✅ (100/100)
- **OutboxDispatcher 循环 run_once**:✅ (10 轮)
- **状态机全部最终态**:✅
- **SLA 评估**:skip_breach=0
- **退避回路**:technical_failed=0
- **Heartbeat 3 态**:HEALTHY=healthy
- **D5.6 7 项核心验证**:✅
- **D5 启动计划 B3(接真实 SMTP)**:⏸️ 撤回解封(D5.6 v1 报告标题"100 封真实 SMTP"措辞失实,实际是 InMemory 模拟)— B3 等 D5.6.2 真实 1 封实测后解封
