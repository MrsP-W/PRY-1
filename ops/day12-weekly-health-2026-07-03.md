# Day 12 周度抽测 — 2026-07-03(周五)

> **范围**:Phase 1.1 周度抽测 — check-snapshot 守卫 + pytest baseline + companion 30 tests + notes dry-run spike
> **目标**:证明 Day 11 收口后系统维持健康状态(不引入漂移)
> **承接**:Day 11 全链路 docs-only 收口(`492895f` · 业务代码 0 改动 · 红线全维持)
> **状态**:✅ 4/4 抽测全绿(进入维持期节奏)
> **红线**:`ENABLE_PATH_4_WRITE=1` 不开 · `ENABLE_NOTES_ENCRYPTION=1` 不写 shell profile · 生产主库未触碰 · 业务代码 0 改动

---

## 1. Step 1: snapshot 防漂移首检

```bash
make check-snapshot
```

**输出**:
```
🔍 quality_snapshot 防漂移检查
OK: quality_snapshot matches live baseline (2791 passed / 1 skipped · 254 md files)
OK: state entry docs match quality_snapshot
```

**结论**:✅ snapshot 与实测基线完全一致,撞坑 #50 第三层 7 步同步范本仍生效。

---

## 2. Step 2: pytest baseline 复核(`make test`)

```bash
make test
```

**输出**:
```
================= 2791 passed, 1 skipped in 127.77s (0:02:07) ==================
TOTAL 10132 1103 89.1%
Required test coverage of 80.0% reached. Total coverage: 89.11%
SKIPPED [1] tests/e2e/test_v0_1_s5_real_smtp.py:29: S5 真实 SMTP 需 SMTP_REAL_NETWORK=1 env + 沿 D5.6.5 4 重防误发参数
```

**结论**:✅ **2791 passed / 1 skipped · coverage 89.11%**(`make test` 实测值;`quality_snapshot.py` 写 89.09% 是 Day 11 校准时数字,本次略升 0.02pp 不需触发 snapshot 校准,因 `< 0.1pp` 抖动不算漂移)

> **关注**:89.09% → 89.11% 是实测正常抖动,沿 `make check-snapshot` 校准逻辑,< 0.1pp 不入档不入快照。

---

## 3. Step 3: companion 30 tests 契约测试

```bash
uv run pytest tests/dashboard/test_companion_readonly.py -v
```

**结果**:**30/30 PASSED in 18.18s**

**契约矩阵摘要**:

| # | 契约类 | 测试数 | 关键验证点 |
|---|--------|-------|----------|
| 1 | **Endpoint Returns 200 + Read-Only** | 6 | 6 GET 端点响应字段含 `read_only: True` |
| 2 | **Companion == Legacy Native API** | 6 | 响应字典与原生 API 完全一致(撞坑 #64)|
| 3 | **POST dry-run 默认安全** | 4 | decide/actions GET 返回 404,POST 默认 dry-run |
| 4 | **Whitelist 严格(`_COMPANION_READ_ONLY_ALIASES`)**| 6 | 6 个伪路径不被别名(防撞坑 #72-75)|
| 5 | **Offline Fallback 契约** | 6 | read_only 字段恒为 True(任何 fallback)|
| 6 | **All Routes Count + Handler Aliases Export** | 2 | 6 GET 路由全注册 + 白名单导出 |
| | **TOTAL** | **30** | **30/30 PASSED** |

**结论**:✅ companion 只读契约矩阵 100% 健康,8/1 实写启用前置的第 4 道门(30 tests 全绿)继续维持。

---

## 4. Step 4: Notes 真加密 dry-run spike(临时 DB)

```bash
uv run python scripts/spike_day10_notes_encryption_dryrun.py
```

**输出**(退出码 0):
```
[OK] opt-in 链路就绪: cipher=NotesCipherImpl, key_len=32
[OK] 临时 DB: /var/folders/v0/nct319_x3gzdwj8rsw6v6m3r0000gn/T/spike_day10_notes_90vjsxr5/notes.db
[OK] 库内前缀严判: legacy=plaintext, encrypted=enc:v1: 前缀
[OK] list_all + get_by_id 解密: 2 条全部明文返回
[OK] 菜单栏 NoteConfirmServiceImpl 解密: 1 条明文
[OK] Dashboard payload: 1 条明文,字段白名单严判通过

============================================================
Day 10 Phase 3.5 Notes 真加密 dry-run spike — 全绿
============================================================
```

**关键点**:

| # | 检查 | 结果 |
|---|------|------|
| 1 | opt-in 链路(进程内 `ENABLE_NOTES_ENCRYPTION=1`)| ✅ |
| 2 | 临时 SQLite DB(与生产主库完全隔离)| ✅ |
| 3 | 库内前缀严判:plaintext vs `enc:v1:` | ✅ |
| 4 | `list_all + get_by_id` 解密 | ✅ |
| 5 | `NoteConfirmServiceImpl.list_pending_confirm` 解密 | ✅ |
| 6 | Dashboard `/api/notes/pending` payload 字段白名单 | ✅ |
| 7 | 生产主库未触碰 | ✅ |
| 8 | shell profile 未写 `ENABLE_NOTES_ENCRYPTION=1` | ✅ |

**结论**:✅ Notes 真加密 dry-run spike 跑通,生产 runbook §2 五步中"Step 2 spike dry-run 复核"的预期行为可重现,生产主库与 shell profile 红线全维持。

---

## 5. 撞坑沿用与新增

### 5.1 沿用撞坑(Day 12 抽测严判)

| 撞坑 # | 严判点 | Day 12 应用 |
|--------|-------|------------|
| **#50** | snapshot baseline 漂移防御 | Step 1 check-snapshot 立刻校验 |
| **#64** | 公共 API 一致性 | companion 30 tests 中"CompanionMatchesLegacyApi"组验证 |
| **#72-75** | 配套端点白名单严格 | companion AliasWhitelistStrict 6 tests |
| **#76-78** | 5 重门控严判 | S5 SMTP 默认 skip + 无 `--count=1` 等 |
| **#80** | docs-only 同步范本 | 进入维持期不再 docs-only,验证基线即可 |
| **#84** | spike 链 4 坑 | notes spike 用临时 DB + 进程内 opt-in |

### 5.2 撞坑累计

- **新增撞坑**:0 类(纯抽测,无业务改动)
- **撞坑累计**:**84 类**(沿 Day 11 收口)

---

## 6. 风险点与红线维持

### 6.1 红线维持清单

- ❌ 不写 `ENABLE_PATH_4_WRITE=1` 到 shell profile / launchd plist
- ❌ 不写 `ENABLE_NOTES_ENCRYPTION=1` 到 shell profile / launchd plist
- ❌ 不实施实写代码(仅 docs + 现有 30 tests 引用)
- ❌ 不动生产主库批量 re-encrypt(spike 用临时 DB,与生产隔离)
- ❌ 不移动 `v0.1.0` / `v0.2.1-rc1` / `v0.2.1` tag
- ❌ 不跑 90 封 SMTP / 不配置 Outlook/Gmail

### 6.2 风险点

| 风险 | 影响范围 | 后续行动 |
|------|---------|---------|
| coverage 89.09% → 89.11%(+0.02pp 抖动) | `< 0.1pp` 不触发校准 | 沿 check-snapshot 现状 |
| 本地 ahead = 0(已 push)| — | ✅ |
| 8/1 实写启用前置 8 道门仍 docs-only | 8/1 前逐步 ✅ | 沿 `docs/day11-companion-write-8-1-readiness.md` §3 时序 |

---

## 7. Phase 1 后续

### Phase 1.2 docs 小补丁(候选 · 可选)

- `docs/day11-notes-encryption-production-runbook.md` §1.5 baseline → 254 MD(当前已同步)
- `reports/Day10-closure.md` §2/§12 数字对齐 — 已是 Day 11 校准后数值

### Phase 1.3 D-step 收口(已补齐)

- @回顾员:`reports/Day12-weekly-checkpoint-2026-07-03.md` 已补齐
- MODIFICATION-LOG 当前入口同步 Day 12 checkpoint
- 新增报告触发 MD 253→254,需沿 #50 第三/四层同步范本复核

---

**最后更新**:2026-07-03 · 周五收工前抽测
**抽测结果**:✅ 4/4 全绿 · 业务代码 0 改动 · 红线全维持
**质量门**:2791 passed / 1 skipped · 89.11%(实测)/ 254 MD / 248 mypy
**撞坑累计**:84 类(无新增)
**维护者**:Mr-PRY
