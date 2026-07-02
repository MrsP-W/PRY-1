# Day 10 — Companion 写端点 Dry-run Closure

> **范围**:Day 10 Phase 3 — 移动伴侣写端点契约文档化(沿 Day 8 候选 C + Day 9 真实接入)
> **目标**:mobile 端只允许 dry-run,契约 / handler / 测试三处一致,**不写新真实写路径**
> **承接**:Day 8 候选 C 契约定义(`src/my_ai_employee/api/mobile_companion.py`)+ Day 9 6 只读真实接入(commit `16d2143`)+ Day 10 Phase 1.1/1.2/2 已收口
> **状态**:✅ 收口(2026-07-02)· **契约**:`COMPANION_API_VERSION = v0.2.57-companion` · **端点**:8 个(6 GET 只读 + 2 POST dry-run)· **测试**:30 cases(沿 Day 9)
> **红线维持**:❌ 不开 `ENABLE_PATH_4_WRITE=1` · ❌ mobile 不做离线写队列 · ❌ 不写新真实写代码

---

## 1. 端点矩阵(8 端点契约)

> **契约源**:`src/my_ai_employee/api/mobile_companion.py` (`COMPANION_ROUTES`)
> **Handler 映射**:`src/my_ai_employee/dashboard/handlers.py` `_COMPANION_READ_ONLY_ALIASES` + `_COMPANION_WRITE_ALIASES`
> **测试**:`tests/dashboard/test_companion_readonly.py`(30 cases)

### 1.1 6 GET 只读端点(精确白名单改写 → 原生 `/api/*`)

| # | Companion 路径 | 原生路径 | 类别 | offline_fallback |
|---|---------------|---------|------|-----------------|
| 1 | `GET /api/companion/status` | `/api/status` | system | `{}`(显示 'offline' badge) |
| 2 | `GET /api/companion/tasks/today` | `/api/tasks/today` | system | `[]`(显示 '上次同步于 HH:MM') |
| 3 | `GET /api/companion/outbox` | `/api/outbox` | outbox | `[]`(mobile 缓存最近一次) |
| 4 | `GET /api/companion/notes/pending` | `/api/notes/pending` | notes | `[]`(mobile 缓存最近一次) |
| 5 | `GET /api/companion/finance/anomalies` | `/api/finance/anomalies` | finance | `[]`(mobile 缓存最近一次) |
| 6 | `GET /api/companion/approval-gate/audits` | `/api/approval-gate/audits` | system | `[]`(mobile 缓存最近 1 小时) |

**契约字段**(6 端点统一):
- `read_only: bool = True`(恒为 True,撞坑 #65 离线兜底契约)
- 响应 schema 与原生 `/api/*` 完全一致(撞坑 #64 公共 API 一致性)

### 1.2 2 POST 写端点(精确白名单改写 → 原生 5 门 dry-run)

| # | Companion 路径 | 原生路径 | 类别 | 必填字段 | 默认 dry_run |
|---|---------------|---------|------|---------|-------------|
| 1 | `POST /api/companion/approval-gate/decide` | `/api/approval-gate/decide` | outbox | `audit_id`, `decision`, `confirm_text=CONFIRM_WRITE` | `True` |
| 2 | `POST /api/companion/approval-gate/actions` | `/api/approval-gate/actions` | notes | `action`, `target_id`, `confirm_text=CONFIRM_WRITE` | `True` |

**5 门严判**(沿撞坑 #18 + v0.2.53.22 `BUSINESS_WRITER_ENABLED` + v0.2.55 `ENABLE_PATH_4_WRITE=1` 第 5 门):
1. `DASHBOARD_WRITE_API=1` — 默认禁用
2. `confirm_text=CONFIRM_WRITE` — 必填显式确认
3. `BUSINESS_WRITER_ENABLED=1` — 严判环境
4. `real_write_handler_enabled` — BusinessWriterImpl 实际注入
5. `ENABLE_PATH_4_WRITE=1` — 路径 4 第 5 门(全局禁用)

**`write_executed: bool = False`**(dry-run 默认值,实际写入需 5 门全过)

---

## 2. Dry-run 实测样例

### 2.1 decide 端点(dry_run=True,write_executed=False)

```bash
$ curl -X POST http://127.0.0.1:8765/api/companion/approval-gate/decide \
    -H "Content-Type: application/json" \
    -d '{
      "audit_id": "outbox-1",
      "decision": "approve",
      "confirm_text": "CONFIRM_WRITE",
      "dry_run": true,
      "actor": "mobile_companion",
      "reason": "companion dry-run"
    }'
```

**响应**(沿 `tests/dashboard/test_companion_readonly.py::TestCompanionWritePostAliases::test_companion_decide_post_matches_native_dry_run`):

```json
{
  "endpoint": "decide",
  "decision": "approve",
  "audit_id": "outbox-1",
  "mapped_action": "outbox.approve",
  "approval_gate_passed": true,
  "would_allow": false,
  "write_executed": false,
  "dry_run": true,
  "error": null,
  "reason": null,
  "business_writer_env_enabled": false,
  "business_writer_impl_injected": false,
  "business_writer_ready": false
}
```

**关键不变量**:
- `write_executed == false`(默认 dry-run)
- `dry_run == true`(默认)
- 响应与原生 `/api/approval-gate/decide` 完全一致(测试断言 `companion_body == native_body`)
- `would_allow == false`(因 `BUSINESS_WRITER_ENABLED=0`,沿 v0.2.53.30 Stub 严判)

### 2.2 actions 端点(dry_run=True)

```bash
$ curl -X POST http://127.0.0.1:8765/api/companion/approval-gate/actions \
    -H "Content-Type: application/json" \
    -d '{
      "action": "notes.confirm",
      "target_id": "note-1",
      "confirm_text": "CONFIRM_WRITE",
      "dry_run": true,
      "actor": "mobile_companion",
      "reason": "companion dry-run"
    }'
```

**响应**:与原生 `/api/approval-gate/actions` 完全一致,`write_executed=false`。

### 2.3 GET 写端点 → 404(写端点仅 POST)

```bash
$ curl http://127.0.0.1:8765/api/companion/approval-gate/decide
# HTTPError 404(沿 TestCompanionWritePostAliases::test_companion_decide_get_returns_404)
```

---

## 3. 与原生 `/api/approval-gate/*` 响应一致性断言

> **撞坑**:撞坑 #64 公共 API 一致性 — companion 改写后**响应字典必须与原生端点完全相等**,不允许字段裁剪 / 字段重命名。

### 3.1 测试断言(30 cases 摘要)

| 测试类 | 测试数 | 覆盖 |
|--------|-------|------|
| `TestCompanionReadOnlyEndpoints` | 7 | 6 GET 200 + read_only=True + 全遍历 |
| `TestCompanionMatchesLegacyApi` | 6 | 6 GET 响应字典 == 原生(撞坑 #64) |
| `TestCompanionWritePostAliases` | 4 | 2 POST GET → 404 + 2 POST 响应 == 原生 |
| `TestCompanionAliasWhitelistStrict` | 7 | 6 路径混淆攻击 + 1 fixture |
| `TestCompanionWhitelistExported` | 1 | handler 白名单 == 契约 `COMPANION_ROUTES` |
| `TestCompanionReadOnlyOfflineFallbackContract` | 6 | 6 GET `read_only=True` 兜底契约 |
| **合计** | **30+** | 全部 8 端点 + 严判 + 契约稳定 |

### 3.2 契约稳定测试(撞坑 #64)

```python
def test_handler_aliases_match_contract_read_only_gets(self) -> None:
    from my_ai_employee.api.mobile_companion import COMPANION_ROUTES, CompanionMethod
    from my_ai_employee.dashboard.handlers import _COMPANION_READ_ONLY_ALIASES

    contract_read_only_paths = {
        r.path for r in COMPANION_ROUTES
        if r.method == CompanionMethod.GET and not r.requires_write_gate
    }
    handler_paths = set(_COMPANION_READ_ONLY_ALIASES.keys())
    assert contract_read_only_paths == handler_paths  # 契约 == handler
    assert len(handler_paths) == 6
```

**保证**:契约模块添加新 GET 端点 → 测试失败 → 必须同步 handler 白名单。

---

## 4. 路径混淆攻击防御(撞坑 #18 5 门严判)

> **撞坑**:`startswith` 一刀切会被 `/api/companion-decide`、`/api/companionX/status` 等路径绕过白名单严判。

### 4.1 防御策略

handler `do_GET` / `do_POST` 使用 **dict 精确匹配**:

```python
# handlers.py L77-78
if path in _COMPANION_READ_ONLY_ALIASES:
    path = _COMPANION_READ_ONLY_ALIASES[path]

# handlers.py L152-153
if path in _COMPANION_WRITE_ALIASES:
    path = _COMPANION_WRITE_ALIASES[path]
```

### 4.2 测试断言(`TestCompanionAliasWhitelistStrict`)

6 个伪造路径全部断言 `HTTPError 404`:

| 伪造路径 | 攻击向量 |
|---------|---------|
| `/api/companion-status` | 无斜杠前缀混淆 |
| `/api/companion/statusX` | 尾部追加 |
| `/api/companionX/status` | 中间插入 |
| `/api/companionstatus` | 完全拼接 |
| `/api/companion/` | 空 action |
| `/api/companion` | 裸前缀 |

---

## 5. Mobile 红线声明

### 5.1 离线兜底契约(沿撞坑 #65 + 契约 §4)

> **原则**:移动伴侣可缓存最近一次响应,**网络断开时不绕过 Dashboard 写入**。

| 场景 | 行为 |
|------|------|
| 6 GET 只读 | 移动伴侣缓存最近一次响应 + 显示 'offline' badge 或 '上次同步于 HH:MM' |
| 2 POST 写 | **必须先联机**;离线时按钮置灰(沿契约 `offline_fallback` 字段) |
| `read_only: bool = True` | 6 GET 响应恒为 True(测试断言) |

### 5.2 不做的事(明确边界)

- ❌ **不开** `ENABLE_PATH_4_WRITE=1` — 移动伴侣永远走 dry-run,实写需 8/1 后单独授权
- ❌ **不做** mobile 离线写队列 — 离线时按钮置灰,不缓存待发写操作
- ❌ **不写** 新真实写代码 — 所有 POST 仅复用原生 `/api/approval-gate/{decide,actions}`
- ❌ **不抢控制权** — 5 门严判替代 ENABLE_PATH_4_WRITE(撞坑 #18)

### 5.3 未来扩展(8/1 后决策)

> **Day 10+ 计划**:仅当用户明确授权且 8/1 后单独启动,才会:
> 1. 评估 Path 4 实写启用(`ENABLE_PATH_4_WRITE=1` + 5 门全过)
> 2. 升级 `COMPANION_API_VERSION` 到 `v0.2.66-companion-write`
> 3. 沿 v0.2.53.33 BusinessWriter 实写路径端到端设计稿 + v0.2.53.55 5th gate preflight

---

## 6. 三处契约一致性核对

> **撞坑**:#64 公共 API 一致性 + #18 5 门严判 — 三处必须 8 端点对齐。

| 维度 | 文件 | 端点数 | 一致性 |
|------|------|--------|-------|
| **契约** | `src/my_ai_employee/api/mobile_companion.py` `COMPANION_ROUTES` | 8(6 GET + 2 POST) | ✅ |
| **Handler** | `src/my_ai_employee/dashboard/handlers.py` `_COMPANION_*_ALIASES` | 6 GET + 2 POST | ✅(测试断言 ==) |
| **测试** | `tests/dashboard/test_companion_readonly.py` `TestCompanionWhitelistExported` | 6 GET 全覆盖 + 2 POST 单独测 | ✅ |

**不变量**:契约添加新端点 → 测试 `test_handler_aliases_match_contract_read_only_gets` 失败 → 必须同步 handler 白名单。

---

## 7. 撞坑关联

| 撞坑 # | 关联点 | 严判位置 |
|--------|-------|---------|
| **#1** | 不直连 DB,所有数据经 Dashboard API | 移动伴侣 client 端(契约外) |
| **#18** | `ENABLE_PATH_4_WRITE=1` 维持 UNSET,5 门替代 | `evaluate_writer_dry_run` 第三道门 |
| **#59** | outlook/gmail 仍不配置 | 移动伴侣不发邮件(契约限制) |
| **#64** | 公共 API 一致性 | 测试 `test_companion_response_equals_legacy` |
| **#65** | BusinessWriter + AuditContext 沿用 | `TestCompanionWritePostAliases` dry-run |
| **#71** | 业务代码改动日 ✅ Day 8 解除 | Day 9 真实接入 + Day 10 Phase 3 文档化 |

---

## 8. Day 9/10 闭环状态

| Day | 范围 | commits | 端点状态 |
|-----|------|---------|---------|
| **Day 8** | 候选 C 契约定义 | 撞坑 #71 解除 | docs-only 8 端点契约 |
| **Day 9** | 6 GET 真实接入 | `16d2143` | 只读 6 端点接通,30 tests |
| **Day 9+** | 2 POST dry-run 映射 | 沿 `16d2143` | 写路径 5 门 dry-run |
| **Day 10 Phase 3** | 写端点 closure 文档化 | 本报告 | 契约 / handler / 测试 三处对齐 |

**累计**:Day 8-10 三棒收口,**移动伴侣仅 dry-run,无真实写代码**,严格沿 v0.2.53.20 / v0.2.55 / v0.2.55.1 / v0.2.55.2 决策矩阵。

---

## 9. 后续锚点

- ✅ Phase 0 push 4 commits(2026-07-02 · `72b6953` ahead 0)
- ✅ Phase 1.1/1.2/2 全部收口(`4b678f6` + `0143717` + `72b6953`)
- 🔄 Phase 3.5 Notes 真加密 dry-run(spike 脚本 + ops/day10-notes-encryption-dryrun-closure.md)
- 🔄 Phase 4 全量 9 门 + Day 10 收官(`make ci` + `reports/Day10-closure.md`)
- ⏸️ Day 7 A 支付宝真导(用户提供 zip 密码后启动,4 重门控 `--max-rows 1`)
- ⏸️ Day 7 B Notes 真同步(可选,`NOTES_REAL_NETWORK=1` + TCC,2026-07-01 已通过)

**红线全维持**(整段项目不变):
- ❌ 不开 `ENABLE_PATH_4_WRITE=1`
- ❌ 不写 shell profile / launchd 的 `ENABLE_NOTES_ENCRYPTION=1`
- ❌ 不对生产主库批量 re-encrypt
- ❌ 不跑 90 封 SMTP · 不配 Outlook/Gmail
- ❌ 不移动 `v0.1.0` / `v0.2.1-rc1` / `v0.2.1` tag
- ❌ 不写新真实写代码(mobile 仅 dry-run)