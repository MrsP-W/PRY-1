# Day 11 — 移动伴侣 8/1 实写启用 readiness checklist (docs-only · 2026-07-03)

> **状态**:**docs-only · 8/1 前必备 checklist**。本文档是 2026-08-01 后用户明确同意启用移动伴侣 POST 实写链路前的对齐文档。
> **承接**:Day 10 Phase 3 companion 写端点 closure(`reports/Day10-companion-write-dryrun-closure.md`)+ Day 10 Phase 1 D-step 收官 + Day 11 Phase 2.1 Notes 真加密生产 runbook。
> **红线全维持**:`ENABLE_PATH_4_WRITE=1` 默认 UNSET · 8/1 前不实施实写链路 · 仅 dry-run。

---

## 1. 8 端点矩阵复核(沿 Phase 3 closure)

| # | Companion 路径 | 方法 | 类别 | 原生路径 | Handler 白名单 | dry_run 默认 |
|---|---------------|------|------|---------|--------------|--------------|
| 1 | `/api/companion/status` | GET | system | `/api/status` | `_COMPANION_READ_ONLY_ALIASES` | N/A(read-only) |
| 2 | `/api/companion/tasks/today` | GET | system | `/api/tasks/today` | `_COMPANION_READ_ONLY_ALIASES` | N/A |
| 3 | `/api/companion/outbox` | GET | outbox | `/api/outbox` | `_COMPANION_READ_ONLY_ALIASES` | N/A |
| 4 | `/api/companion/notes/pending` | GET | notes | `/api/notes/pending` | `_COMPANION_READ_ONLY_ALIASES` | N/A |
| 5 | `/api/companion/finance/anomalies` | GET | finance | `/api/finance/anomalies` | `_COMPANION_READ_ONLY_ALIASES` | N/A |
| 6 | `/api/companion/approval-gate/audits` | GET | system | `/api/approval-gate/audits` | `_COMPANION_READ_ONLY_ALIASES` | N/A |
| 7 | `/api/companion/approval-gate/decide` | POST | outbox | `/api/approval-gate/decide` | `_COMPANION_WRITE_ALIASES` | `True`(默认 dry-run)|
| 8 | `/api/companion/approval-gate/actions` | POST | notes | `/api/approval-gate/actions` | `_COMPANION_WRITE_ALIASES` | `True`(默认 dry-run)|

**30 tests 沿用**(`tests/dashboard/test_companion_readonly.py`):
- TestCompanionReadOnlyEndpoints(7):6 GET 200 + read_only=True
- TestCompanionMatchesLegacyApi(6):响应字典 == 原生
- TestCompanionWritePostAliases(4):2 POST GET → 404 + 2 POST 响应 == 原生
- TestCompanionAliasWhitelistStrict(7):6 路径混淆攻击 + 1 fixture
- TestCompanionWhitelistExported(1):handler 白名单 == 契约
- TestCompanionReadOnlyOfflineFallbackContract(6):read_only=True 兜底契约

---

## 2. 5 门对照(沿 v0.2.53.53 Path 4 launch checklist v2)

### 2.1 5 门完整清单(`ENABLE_PATH_4_WRITE=1` 启用前必须全 ✅)

| # | 门 | 严判位置 | 关闭后果 |
|---|----|---------|---------|
| **1** | `DASHBOARD_WRITE_API` | handler 顶层(env `DASHBOARD_WRITE_API=1`)| 不响应 POST 请求(返回 404)|
| **2** | `confirm_text` | `BusinessWriter.dry_run(confirm_text=...)` 严判 | `would_allow=False` · 干路失败 |
| **3** | `BUSINESS_WRITER_ENABLED` | env `BUSINESS_WRITER_ENABLED=1` | 走 Stub(`would_allow=False`)|
| **4** | `real_write_handler_enabled` | `BusinessWriterImpl._real_write_handler_enabled` 字段 | 立即 `raise NotImplementedError` |
| **5** | `ENABLE_PATH_4_WRITE` | 顶级 env `ENABLE_PATH_4_WRITE=1`(v2 新增)| `BusinessWriterImpl` 内部 raise NotImplementedError |

### 2.2 8 路径决策矩阵(5 门 × 8 路径)

| 路径 | 1 | 2 | 3 | 4 | 5 | outcome |
|------|---|---|---|---|---|---------|
| 1 GET(read-only)| - | - | - | - | - | 200 OK(不受 5 门影响)|
| 2 POST dry-run | ✅ | ✅ | - | - | - | 200 OK + `write_executed=False` |
| 3 POST 实写 | ✅ | ✅ | ✅ | ✅ | ✅ | 200 OK + `write_executed=True` |
| 4 POST 实写(任一门关)| - | - | - | - | - | raise NotImplementedError / 403 / 404 |

**唯一实写路径 = 路径 3**:**5 门全部 open**。任一关闭 → 立即 raise(沿 v0.2.53.46)。

---

## 3. 启用前置条件(8 道门 · 全部 ✅ 才允许进入 §4)

| # | 门 | 验证命令 | 期望输出 |
|---|----|---------|---------|
| **3.1** | `ENABLE_PATH_4_WRITE=1` 未写 shell profile | `grep -r "ENABLE_PATH_4_WRITE" ~/.zshrc ~/.bash_profile ~/.zprofile 2>/dev/null` | 无输出 |
| **3.2** | `ENABLE_NOTES_ENCRYPTION=1` 未写 shell profile | `grep -r "ENABLE_NOTES_ENCRYPTION" ~/.zshrc ~/.bash_profile ~/.zprofile 2>/dev/null` | 无输出 |
| **3.3** | Phase 3 closure 已落地 | `cat reports/Day10-companion-write-dryrun-closure.md | head -3` | 有「Day 10 Phase 3 closure」标记 |
| **3.4** | 30 tests 全绿 | `uv run pytest tests/dashboard/test_companion_readonly.py -q --no-cov --tb=line` | 30 passed, 0 failed |
| **3.5** | 9/9 质量门全绿 | `make ci` | 全部绿 · 沿用 Day 10 baseline 2790 / 89.09% / 248 mypy / 248 MD |
| **3.6** | BusinessWriter ready 语义 | `cat src/my_ai_employee/agents/审计员.md | grep "BusinessWriter"` | 有「ready」状态描述 |
| **3.7** | AuditContext actor/reason 严判 | `grep -rn "actor ≤ 80\|reason ≤ 240" src/my_ai_employee/ 2>/dev/null` | 有 2 处命中 |
| **3.8** | 4 撞坑防线确认 | `grep -rn "撞坑 #1\|撞坑 #18\|撞坑 #64\|撞坑 #65" docs/day11-companion-write-8-1-readiness.md` | 4 处命中 |

**任一不满足 → 终止并修复,绝不进入 §4**。

---

## 4. 启用步骤(8 步 · docs-only 阶段禁止执行)

### Step 1 · 临时环境变量导出(不写 shell profile)

```bash
# 5 门全部开(沿撞坑 #1 红线 · 仅当前 shell 生效)
export DASHBOARD_WRITE_API=1
export BUSINESS_WRITER_ENABLED=1
# 4 门 + 5th flag
export ENABLE_PATH_4_WRITE=1
```

### Step 2 · 启动 spike dry-run 复核

```bash
uv run pytest tests/dashboard/test_companion_readonly.py -v
```

期望:30 tests 全绿。

### Step 3 · 启动 Dashboard(单端口)

```bash
make dashboard    # 沿 D5.7 范本
```

期望:Dashboard 健康弹窗 → "Path 4: enabled(仅当前 session)"。

### Step 4 · 触发 6 只读端点

```bash
# 沿 Phase 3 8 端点矩阵 #1-6
for path in status tasks/today outbox notes/pending finance/anomalies approval-gate/audits; do
  curl -s http://127.0.0.1:8765/api/companion/$path | head -c 100
done
```

期望:全部 200 OK + `read_only=True`。

### Step 5 · 触发 POST dry-run(#7-8)

```bash
curl -s -X POST http://127.0.0.1:8765/api/companion/approval-gate/decide \
  -H "Content-Type: application/json" \
  -d '{"audit_id": 1, "decision": "approve", "actor": "spike-2026-08-01", "reason": "Day 11 readiness verification"}'
```

期望:200 OK + `dry_run=True` + `would_allow=True` + `write_executed=False`。

### Step 6 · 单条实写测试(可选 · 严格审批)

```bash
# 必传 confirm_text(撞坑 #18 严判)
curl -s -X POST http://127.0.0.1:8765/api/companion/approval-gate/decide \
  -H "Content-Type: application/json" \
  -d '{"audit_id": 1, "decision": "approve", "actor": "spike-2026-08-01", "reason": "Day 11 readiness real-write test", "confirm_text": "approve"}'
```

期望:`write_executed=True` + ApprovalGate 真实写入 + AuditContext 落档。

### Step 7 · 验证 audit 落档

```bash
sqlite3 ~/Library/Application\ Support/my-ai-employee/data.db "SELECT * FROM approval_gate_audits ORDER BY executed_at_ms DESC LIMIT 1"
```

期望:1 条新记录,actor=spike-2026-08-01,reason 含「Day 11 readiness」。

### Step 8 · 关 opt-in + 清理

```bash
unset DASHBOARD_WRITE_API BUSINESS_WRITER_ENABLED ENABLE_PATH_4_WRITE
```

---

## 5. 回滚策略(3 步 · 任何阶段失败立即执行)

### Step 1 · 关 opt-in

```bash
unset DASHBOARD_WRITE_API BUSINESS_WRITER_ENABLED ENABLE_PATH_4_WRITE
```

### Step 2 · 重启 Dashboard

```bash
# 关闭后重启(沿 v0.2.53.19 §3 范本)
make dashboard
```

### Step 3 · 验证仍可 dry-run

```bash
# 重新跑 Step 5
curl -s -X POST http://127.0.0.1:8765/api/companion/approval-gate/decide \
  -H "Content-Type: application/json" \
  -d '{"audit_id": 1, "decision": "approve", "actor": "rollback-test", "reason": "Day 11 readiness rollback test"}'
```

期望:200 OK + `dry_run=True`(即使 opt-in 全关,dry-run 仍工作) + `write_executed=False`。

**回滚后状态**:
- opt-in 全关 → POST 仍可调用,但全部走 dry-run(路径 2)
- 实写路径(路径 3)需 5 门全开才能走
- AuditRecord 不可删除(只追加,沿撞坑 #82)

---

## 6. 与 Day 10 范本对齐(避免重复)

| Day 10 范本 | Day 11 沿用 |
|------------|-----------|
| `reports/Day10-companion-write-dryrun-closure.md` 9 章节 | ✅ 引用为「8 端点契约收口证据」 |
| `docs/v0.2.53.53-path4-launch-checklist-2026-06-30.md` 5 门 v2 升级 | ✅ 引用为「5 门清单 + 5th flag 文档源」 |
| `src/my_ai_employee/dashboard/handlers.py` `_COMPANION_READ_ONLY_ALIASES` / `_COMPANION_WRITE_ALIASES` | ✅ 引用为「handler 白名单实装位置」 |
| `tests/dashboard/test_companion_readonly.py` 30 tests | ✅ 引用为「端点契约测试」 |
| 撞坑 #1 凭据红线 | ✅ 沿用 §3.1 §3.2 shell profile 严判 |
| 撞坑 #18 5 门替代 ENABLE_PATH_4_WRITE | ✅ 沿用 §2.1 5 门清单 |
| 撞坑 #64 公共 API 一致性 | ✅ 沿用 §1 8 端点响应字典 == 原生 |
| 撞坑 #65 BusinessWriter ready 语义 | ✅ 沿用 §3.6 ready 状态严判 |
| 撞坑 #82 AuditRecord 落档 | ✅ 沿用 §4 Step 7 audit 验证 |

---

## 7. 不做的事(整段项目红线)

- ❌ **不**写 `ENABLE_PATH_4_WRITE=1` 到 shell profile / launchd plist
- ❌ **不**写 `ENABLE_NOTES_ENCRYPTION=1` 到 shell profile / launchd plist
- ❌ **不**实施实写代码(仅文档 + 现有 30 tests 引用)
- ❌ **不**移动 `v0.1.0` / `v0.2.1-rc1` / `v0.2.1` tag
- ❌ **不**跑 90 封 SMTP / 不配置 Outlook/Gmail
- ❌ **不**自动启用(必须用户明确同意 + 8 道门全 ✅ + 单次手动 export)

---

## 8. 后续锚点(Day 11+ 决策点)

| 决策项 | 当前 | 触发 |
|-------|------|------|
| **8/1 release tag readiness** | ⏸️ 沿 `docs/v0.2.59-8-1-tag-evaluation-2026-08-01.md` | 2026-08-01 当天决策 |
| **移动伴侣实写启用** | ⏸️ 8/1 后 | 用户明确同意 + §3 八道门全 ✅ + §4 八步按序执行 |
| **Notes 真加密生产启用** | ⏸️ 沿 Day 11 Phase 2.1 runbook | 用户明确同意 + runbook §1 五道门全 ✅ |
| **撞坑累计沉淀** | ✅ Day 10 = 84 类 | 沿 `memory/day10-closure-pitfalls-2026-07-02.md` |
| **Day 7 A 支付宝真导** | ⏸️ 用户决策 | 用户提供 ZIP 密码或解压 CSV |

---

**最后更新**:2026-07-03(Day 11 启动后 docs-only 落定)
**状态**:📘 docs-only · 不启用 · 等待 8/1 后用户决策
**维护者**:Mr-PRY