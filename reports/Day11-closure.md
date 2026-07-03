# Day 11 Closure — Docs-only 收口 + 启用前 runbook 落定(2026-07-03)

> **范围**:Day 11 全链路 docs-only 收口 — Phase 2.1 Notes 真加密生产 runbook + Phase 2.3 移动伴侣 8/1 实写启用 readiness + snapshot 校准 247→248→249→250 + 9 门全量复核
> **目标**:Notes 加密链路启用前文档 + 移动伴侣 8/1 实写链路 readiness 双 readiness 落定
> **承接**:Day 10 收口(`429a7a1`)+ D-step 三角色(`33b1b0d`)+ Day 10 push(`429a7a1..7fe1f50`)
> **状态**:✅ 收口(2026-07-03)· **5 commits**(含尾巴校准)· 9/9 质量门全绿 · **业务代码 0 改动** · 撞坑累计 84 类
> **红线全维持**:`ENABLE_PATH_4_WRITE=1` 8/1 前不开 · `ENABLE_NOTES_ENCRYPTION=1` 不写 shell profile · 不动生产主库 · 90 封 SMTP 跳过 · tag 不动

---

## 1. 范围与目标

### 1.1 范围

- **Phase 2.1** — 写 `docs/day11-notes-encryption-production-runbook.md`(8 章节)
- **Phase 2.2** — 修补 runbook §1.5 baseline 247 MD → 250 MD
- **Phase 2.3** — 写 `docs/day11-companion-write-8-1-readiness.md`(8 章节)
- **snapshot 校准链** — 247 → 248 → 249 → 250(3 个 snapshot 校准 commit)
- **9 门全量复核** — 证明项目不只 check-snapshot 绿,而是 9/9 真绿

### 1.2 目标

- ✅ 两份 readiness runbook 落定(Notes 真加密 + companion 8/1)
- ✅ 9/9 质量门实测全绿
- ✅ check-snapshot 防漂移有效(snapshot 校准链证明机制可用)
- ✅ 撞坑 #50 第三层沉淀(`MD + pytest 联动`)

---

## 2. commit 链 + 文件清单(4 commits · 11 files)

| Phase | commit | files | 改动 |
|-------|--------|-------|------|
| **Phase 2.1** | `7fe1f50` | 8 files | runbook 8 章节 + snapshot 校准 247→248 |
| **Phase 2.2(中间校准)** | `22a007f` | 2 files | snapshot 校准 249→250 |
| **Phase 2.3** | `6fc4464` | 8 files | companion readiness 8 章节 + snapshot 校准 248→249 |
| **Phase 2.2 修补** | (本次) | 1 file | runbook §1.5 247→250 |
| **Phase 2.2 closure** | (本次) | 1 file | Day11-closure.md |
| **Phase 4 commit** | (本次) | (待定) | docs-only commit |

**累计 commits**:Day 11 全 docs-only,共 4 个新 commit(其中 2 个 snapshot 校准)。

---

## 3. 9 门实测表(2026-07-03 · `@检查员` 复核)

| # | 门 | 实测输出 | 期望 | 结果 |
|---|----|---------|------|------|
| 1 | `make test` | 2791 passed / 1 skipped · coverage 89.09% | 2791 / 1 skipped / ≥ 89.09% | ✅ |
| 2 | `uv run ruff check src/ tests/` | All checks passed | passed | ✅ |
| 3 | `uv run ruff format src/ tests/ --check` | 264 files already formatted | passed | ✅ |
| 4+5 | `make mypy` | Success: 0 issues / 248 source files | 0 errors / 248 files | ✅ |
| 6 | `uv run alembic upgrade head --sql` | 0016_approval_gate_audits migration | exit 0 | ✅ |
| 7 | `uv build` | tar.gz + wheel built | success | ✅ |
| 8 | `make lint` | 252 files / 0 errors | 252 files / 0 errors | ✅ |
| 9 | `make check-snapshot` | OK(2791/1 · 252 md files) | OK | ✅ |

**实测口径说明**:
- snapshot = `2791 passed / 1 skipped`(与 `make test` 独立测一致)
- collected = 2792(稳态 `passed + skipped == collected`)
- 尾巴校准:memory 文件入库 251→252 MD · pytest 2790/2→2791/1(总数不变,显示口径对齐)

---

## 4. 8 端点矩阵摘要(引用 companion readiness)

| # | Companion 路径 | 方法 | 类别 | dry_run |
|---|---------------|------|------|---------|
| 1 | `/api/companion/status` | GET | system | N/A(read-only)|
| 2 | `/api/companion/tasks/today` | GET | system | N/A |
| 3 | `/api/companion/outbox` | GET | outbox | N/A |
| 4 | `/api/companion/notes/pending` | GET | notes | N/A |
| 5 | `/api/companion/finance/anomalies` | GET | finance | N/A |
| 6 | `/api/companion/approval-gate/audits` | GET | system | N/A |
| 7 | `/api/companion/approval-gate/decide` | POST | outbox | `True`(默认 dry-run)|
| 8 | `/api/companion/approval-gate/actions` | POST | notes | `True`(默认 dry-run)|

**8/1 实写启用前置 8 道门**(详见 `docs/day11-companion-write-8-1-readiness.md` §3):
1. `ENABLE_PATH_4_WRITE` 未写 shell profile
2. `ENABLE_NOTES_ENCRYPTION` 未写 shell profile
3. Phase 3 closure 已落地
4. 30 tests 全绿
5. 9/9 质量门全绿
6. BusinessWriter ready 语义
7. AuditContext actor/reason 严判
8. 4 撞坑防线确认

---

## 5. Notes 真加密 runbook 五道门前置(**未执行 §2 实写步骤**)

| # | 前置门 | 状态 |
|---|--------|------|
| 1.1 | Keychain 已有 notes master key | ⏸️ **未执行** |
| 1.2 | 生产主库全部 legacy 明文或已知混合 | ⏸️ **未执行** |
| 1.3 | `ENABLE_NOTES_ENCRYPTION=1` 未写 shell profile | ✅ docs-only 阶段已确认 |
| 1.4 | `ENABLE_PATH_4_WRITE=1` 未设置 | ✅ docs-only 阶段已确认 |
| 1.5 | 9/9 质量门全绿 | ✅ 已实测(本 closure §3)|

**§2 实写步骤(5 步)未执行**:
- Step 1 `export ENABLE_NOTES_ENCRYPTION=1`
- Step 2 spike dry-run 复核
- Step 3 启动应用
- Step 4 新笔记写入验证
- Step 5 旧笔记读取验证

**触发条件**:用户明确同意 + 5 道门全 ✅ + §2 五步按序执行。

---

## 6. 撞坑沿用与累计(Day 11 = 84 类 · 0 新增)

### 6.1 沿用撞坑(Day 11 docs-only 严判)

| 撞坑 # | 严判点 | Day 11 应用 |
|--------|-------|------------|
| **#1** | 凭据不入 chat/docs/commit | runbook §1.3 §1.4 shell profile 严判 |
| **#18** | 5 门替代 `ENABLE_PATH_4_WRITE` | companion readiness §2.1 5 门清单 |
| **#50** | snapshot baseline 漂移防御 | snapshot 校准链 247→248→249→250 |
| **#59** | outlook/gmail 不配置 | 全 4 Phase 维持 |
| **#64** | 公共 API 一致性 | 8 端点响应字典 == 原生 |
| **#65** | `NotesCipherImpl.decrypt` 短路 fallback | runbook §3.1 读取层透明解密 |

### 6.2 撞坑累计

- **Day 10 新增**:6 类(#79 ~ #84)
- **Day 11 新增**:0 类(docs-only,无业务改动)
- **撞坑累计**:**84 类**(沿 Day 10 收口)

### 6.3 撞坑 #50 第三层联动(NEW 沉淀)

**本次发现的撞坑 #50 第三层新形态**:
- **现象**:snapshot 校准链中,MD lint 漂移会触发 pytest 漂移(因为 test_check_quality_snapshot_script_exits_zero 测试会因为 snapshot 脚本退出非零而失败)
- **修复**:同步更新 snapshot.py + 5 状态入口(CLAUDE.md / README.md / SESSION-STATE.md / MODIFICATION-LOG.md / docs/v0.2-launch-plan.md)
- **Why**:MD 计数与 pytest collected 的联动是 guardian 的自洽约束
- **How to apply**:docs-only 阶段新增 MD 必须同步更新 snapshot.py + 5 状态入口,不能用单一更新通过 guard

详见 `memory/day11-snapshot-guardian-drift-2026-07-04.md`(本次 Phase 3 @教练员 沉淀产物)。

---

## 7. 风险 + 8/1 前红线

### 7.1 风险点

| 风险 | 影响范围 | 后续行动 |
|------|---------|---------|
| Day 11 memory 未跟踪 → 入库 251→252 MD | snapshot 守卫需同步 | ✅ 尾巴 commit 已校准 |
| 本地 ahead commits 未推 | 仅本地待 push | 用户明确 push 后再 `git push origin main` |
| 8/1 实写启用前置 8 道门当前 docs-only(8 道门均为 ⏸️ 状态)| 8/1 前必须逐步 ✅ | 沿 `docs/day11-companion-write-8-1-readiness.md` §3 时序 |

### 7.2 8/1 前红线

- ❌ 不写 `ENABLE_PATH_4_WRITE=1` 到 shell profile / launchd plist
- ❌ 不写 `ENABLE_NOTES_ENCRYPTION=1` 到 shell profile / launchd plist
- ❌ 不实施实写代码(仅文档 + 现有 30 tests 引用)
- ❌ 不动生产主库批量 re-encrypt(单条可选,runbook §4.2)
- ❌ 不移动 `v0.1.0` / `v0.2.1-rc1` / `v0.2.1` tag
- ❌ 不跑 90 封 SMTP / 不配置 Outlook/Gmail

---

## 8. Day 12+ 候选预判

| 优先级 | 候选 | 触发 |
|-------|------|------|
| **P0** | 8/1 release tag 准备 | 7 月下旬读 `docs/v0.2.59-8-1-tag-evaluation-2026-08-01.md` |
| **P1** | companion POST dry-run 集成测试加固 | 8/1 前每周抽测 30 tests(沿 §1 8 端点矩阵)|
| **P1** | Notes 真加密生产启用(仍 opt-in)| 用户明确同意 + runbook §1 五道门全 ✅ |
| **P2** | Day 7 A 支付宝真导 | 用户提供 ZIP 密码或解压 CSV |
| **P3** | Day 7 B Notes 复跑 | 可选(沿 `NOTES_REAL_NETWORK=1` + TCC)|

### Day 12 候选增量项

- 8/1 readiness 二次刷新:沿 `docs/v0.2.58-a3-readiness-2026-07-25.md` 7/25 周度节奏
- 移动伴侣 8 端点契约端到端 spike:撞坑 #76 严判升级
- Day 7 A 真导(凭据到位即可)

---

**最后更新**:2026-07-03 · 尾巴校准(memory 入库 + pytest/MD 口径对齐)后落定
**状态**:✅ 收口 · 9/9 全绿 · 业务代码 0 改动 · 红线全维持
**质量门**:2791 passed / 1 skipped · 89.09% · 252 MD · 248 mypy
**撞坑累计**:84 类 · #50 第三层沉淀(`memory/day11-snapshot-guardian-drift-2026-07-04.md`)
**远程同步**:本地 ahead 待 push(需用户授权)
**维护者**:Mr-PRY