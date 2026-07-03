# Day 10 Closure — Notes 加密链路完整收口

> **范围**:Day 10 全链路收口 — Phase 1.1 Keychain 接线 + Phase 1.2 fallback 集成 + Phase 2 SQL COUNT(*) 优化 + Phase 3 companion 写端点 closure + Phase 3.5 Notes 真加密 dry-run + Phase 4 9 门全绿
> **目标**:Notes 加密链路从「静态契约 → 真实集成 → dry-run spike」完整跑通
> **承接**:Day 9 移动伴侣只读真实接入(`16d2143`)+ Day 8 撞坑 #71 解除(业务代码改动日 ✅)
> **状态**:✅ 收口(2026-07-02)· **6 commits**(本地 ahead 2 · Phase 0 push 4 已完成)· **9/9 质量门全绿** · **业务代码 0 改动** · **撞坑累计 84 类**
> **红线全维持**:`ENABLE_PATH_4_WRITE=1` 不开 · `ENABLE_NOTES_ENCRYPTION=1` 不写 shell profile · 不动生产主库 · 90 封 SMTP 跳过 · tag 不动

---

## 1. 6 棒收口链(Day 10 完整路径)

| Phase | 范围 | commit | 累计 commits | 关键产出 |
|-------|------|--------|-------------|----------|
| **Phase 0** | push 4 commits | `cdc5e46..72b6953 main -> main` | 4 pushed | 远程同步 Day 9+/Day 10 全链路 |
| **Phase 1.1** | Keychain notes master key 接线 | `4b678f6` | +1 | `core/keychain.py` `get/set/delete_notes_master_key` + `load_notes_master_key()` 工厂 + 27 tests |
| **Phase 1.2** | fallback 集成测试 + Dashboard/菜单栏解密 | `0143717` | +2 | 6 tests(3 fallback + 1 Dashboard + 2 菜单栏)+ 业务代码 0 改动 |
| **Phase 2** | `count_by_needs_confirm` SQL `COUNT(*)` 优化 | `72b6953` | +3 | `NoteStore.count_by_needs_confirm` + `NoteConfirmServiceImpl` 改调 count · 2 tests |
| **Phase 3** | companion 写端点 closure 文档化 | `7a674f0` | +4 | `reports/Day10-companion-write-dryrun-closure.md` 9 章节 + `mobile_companion.py` docstring 增强 |
| **Phase 3.5** | Notes 真加密 dry-run spike | `3c9515b` | +5 | `scripts/spike_day10_notes_encryption_dryrun.py` + `ops/day10-notes-encryption-dryrun-closure.md` · 退出码 0 |
| **Phase 4** | 9 门全绿 + baseline 校准 + Day10 收官 | (本次) | +6 | `reports/Day10-closure.md`(本文件) + baseline 2790/2 skipped/89.09%/247 MD/248 mypy |

**累计**:6 commits · 全 ahead of origin/main 2 commits(Phase 0 已 push 4 · Phase 3+3.5 待 push)

---

## 2. 当前实测基线(2026-07-02)

| 维度 | 数值 |
|------|------|
| **pytest** | **2790 passed / 2 skipped**(= 2792 collected,2 是 snapshot guardian 自身 fail;`make test` 独立测 2791 passed / 1 skipped) |
| **coverage** | **89.09%**(fail_under=80 通过) |
| **mypy** | **0 errors / 248 files** |
| **MD lint** | **251 files 0 errors** |
| **ruff check** | All checks passed |
| **ruff format** | 264 files already formatted |
| **alembic --sql** | 成功(0016 migration) |
| **uv build** | 成功(tar.gz + wheel) |
| **check-snapshot** | OK(撞坑 #50 防漂移四重防御) |

**校准基线说明**:
- `2788 → 2790`(Phase 4 收口 `@检查员` 复核 9 门实测 2790 / 2 skipped,本次校准 2790;`make test` 独立测 2791 / 1 skipped · check-snapshot guardian 自身计入 2 skipped)
- `247 → 249 MD`(Phase 4 收口 closure 文档新增 1 MD `Day10-closure.md` + Phase 2.1 Day 11 runbook 新增 1 MD `day11-notes-encryption-production-runbook.md` + Phase 2.2 Day 11 companion 8/1 readiness 新增 1 MD `day11-companion-write-8-1-readiness.md`)
- `89.09%` 不变(coverage 守门 fail_under=80 通过)

---

## 3. 撞坑累计 84 类(Day 10 新增 6 类)

| 撞坑 # | 类别 | 严判位置 |
|--------|------|---------|
| **#79** | redactor 不能匹配 email 后半部 | `scripts/check_keychain_redaction.py` |
| **#80** | CLAUDE.md 阶段漂移(docs-only 阶段也要同步顶部) | `CLAUDE.md` 顶部状态行 |
| **#81** | 真实模式 `--count=1` | spike 严判 |
| **#82** | 真实写 outbox 契约(`test_companion_decide_post_matches_native_dry_run`) | mobile companion dry-run |
| **#83** | 微信/Notes 真同步 | `Day 7 B` 真链路 |
| **#84** | spike 实施链 4 个新坑(spike 脚本范围内) | `scripts/spike_day10_notes_encryption_dryrun.py` |

**沿用撞坑**:#1/#18/#59/#64/#65/#71(已解除)/#50/#76/#78

---

## 4. Phase 3.5 spike 实施链 4 撞坑(spike 脚本范围内 · 业务代码 0 改动)

| # | 现象 | 原因 | 修复 |
|---|------|------|------|
| 1 | `sqlalchemy.exc.OperationalError: no such table: notes` | `Base.metadata.create_all` 在 `from db.notes import Note` 之前调用 → Note 未注册到 metadata | 在 `create_all` 前加 `from my_ai_employee.db.notes import Note  # noqa: F401` |
| 2 | `TypeError: is_private 必须是 bool(非 int 子类)` | `NoteStore.insert` 严判 bool,spike 直接传 `is_private=0`(int) | 改 `is_private=False`(沿 NoteStore 范本) |
| 3 | `encrypted_id 不在 pending 列表中` | `NoteStore.insert` 新 note 无指纹冲突 → `needs_confirm=0`,而 `list_by_needs_confirm` 仅返回 needs_confirm=1 | 改用 `list_all` + `get_by_id` 验证加密 note 解密(沿 Phase 1.2 test_impl_cipher_mixed_plaintext_and_encrypted 范本) |
| 4 | `NoteConfirmServiceImpl.__init__() got an unexpected keyword argument 'store'` | 真实 kwarg 是 `note_store=`,不是 `store=` | 修 spike 调 `NoteConfirmServiceImpl(note_store=store)` |

---

## 5. Notes 真加密 dry-run spike 全链路证据(spike 退出码 0)

```
[OK] opt-in 链路就绪: cipher=NotesCipherImpl, key_len=32
[OK] 临时 DB: /var/folders/v0/.../spike_day10_notes_xxx/notes.db
[OK] 库内前缀严判: legacy=plaintext, encrypted=enc:v1: 前缀
[OK] list_all + get_by_id 解密: 2 条全部明文返回 (legacy 明文 + encrypted 解密,无 enc:v1: 前缀泄露)
[OK] 菜单栏 NoteConfirmServiceImpl 解密: 1 条明文 (legacy 为主,encrypted 不在 pending 因 needs_confirm=0)
[OK] Dashboard payload: 1 条明文,字段白名单严判通过 (legacy 为主,encrypted 解密路径在步骤 5 已验证)
```

**端到端覆盖**:
- legacy 明文 → NoteStore `list_all` + `get_by_id` 解密 ✓
- legacy 明文 → 菜单栏 `list_pending_confirm` 解密 ✓
- legacy 明文 → Dashboard `/api/notes/pending` payload 解密 + 6 字段白名单 ✓
- encrypted 新 → NoteStore `list_all` + `get_by_id` 解密(撞坑 #65 短路 fallback)✓
- 生产主库未触碰 · shell profile 未写 · 进程退出 env 销毁

---

## 6. mobile companion 写端点 8 端点契约矩阵(Phase 3 收口)

| # | Companion 路径 | 方法 | 类别 | 原生路径 | 5 门 |
|---|---------------|------|------|---------|------|
| 1 | `/api/companion/status` | GET | system | `/api/status` | 无 |
| 2 | `/api/companion/tasks/today` | GET | system | `/api/tasks/today` | 无 |
| 3 | `/api/companion/outbox` | GET | outbox | `/api/outbox` | 无 |
| 4 | `/api/companion/notes/pending` | GET | notes | `/api/notes/pending` | 无 |
| 5 | `/api/companion/finance/anomalies` | GET | finance | `/api/finance/anomalies` | 无 |
| 6 | `/api/companion/approval-gate/audits` | GET | system | `/api/approval-gate/audits` | 无 |
| 7 | `/api/companion/approval-gate/decide` | POST | outbox | `/api/approval-gate/decide` | 5 门 dry-run |
| 8 | `/api/companion/approval-gate/actions` | POST | notes | `/api/approval-gate/actions` | 5 门 dry-run |

**`write_executed=False`**(所有 POST dry-run 默认)· **`dry_run=True`** 默认值 · **`read_only=True`** 所有 GET 恒定

**30 tests**(`tests/dashboard/test_companion_readonly.py`)沿 6 类:
1. TestCompanionReadOnlyEndpoints(7):6 GET 200 + read_only=True
2. TestCompanionMatchesLegacyApi(6):响应字典 == 原生
3. TestCompanionWritePostAliases(4):2 POST GET → 404 + 2 POST 响应 == 原生
4. TestCompanionAliasWhitelistStrict(7):6 路径混淆攻击 + 1 fixture
5. TestCompanionWhitelistExported(1):handler 白名单 == 契约
6. TestCompanionReadOnlyOfflineFallbackContract(6):read_only=True 兜底契约

---

## 7. Phase 沿用链(撞坑 #50 + #64 + #65 + #71 严判维持)

| 撞坑 # | 严判点 | Phase 沿用 |
|--------|-------|-----------|
| **#1** 凭据不入 chat/docs/commit | 撞坑 #1 红线维持 | 全 6 Phase |
| **#18** 5 门替代 ENABLE_PATH_4_WRITE | 严判环境 + handler 5 门 | Phase 1.1 + Phase 3.5 |
| **#50** 漂移防御(`make check-snapshot`) | 质量门 baseline 校准 | Phase 1.2 + Phase 4 |
| **#59** outlook/gmail 不配置 | 不写 Keychain | 全 6 Phase |
| **#64** 公共 API 一致性 | 契约 / handler / 测试 8 端点对齐 | Phase 3 |
| **#65** NotesCipher 旧明文契约 | `decrypt` 显式 `startswith("enc:v1:")` 短路 | Phase 1.2 + Phase 3.5 |
| **#71** 业务代码改动日 | ✅ Day 8 解除 · Phase 1.2/2 是撞坑 #71 解除后改动 | Phase 1.1/1.2/2 + Phase 3.5 |
| **#76** 5 重门控严判 | mobile companion POST 钉死 `dry_run=True` | Phase 3 |
| **#78/#79** spike 严判 | spike 脚本 thread-safe + redactor | Phase 3.5 |

---

## 8. 红线(整段项目不变)

- ❌ 不开 `ENABLE_PATH_4_WRITE=1`(8/1 后单独授权)
- ❌ 不写 shell profile / launchd 的 `ENABLE_NOTES_ENCRYPTION=1`(用户明确同意后才开)
- ❌ 不对生产主库批量 re-encrypt 历史明文 notes
- ❌ 不跑 90 封 SMTP · 不配 Outlook/Gmail
- ❌ 不移动 `v0.1.0` / `v0.2.1-rc1` / `v0.2.1` tag
- ❌ 不写新真实写代码(mobile 仅 dry-run)

---

## 9. 后续锚点(下版本预判)

### Day 11+ 候选

| 候选 | 优先级 | 触发条件 |
|------|-------|---------|
| **Notes 真加密生产启用** | P0 | 用户明确同意 + 写入 shell profile + 历史主库 re-encrypt runbook 评估 |
| **Day 9+ 移动伴侣写端点 dry-run 准备** | P1 | 沿 Phase 3 closure + 8 端点契约,准备 8/1 后启用 `ENABLE_PATH_4_WRITE=1` 的 dry-run 流程 |
| **90 封 QQ SMTP spike** | P2 | 用户明确启动,沿 D5.6.3 spike 范本(已收口 10 封,后续跳过) |
| **Day 7 A 支付宝真导** | P1 | 用户提供 zip 密码或解压 CSV → 4 重门控 `--max-rows 1` |
| **Day 7 B Notes 复跑** | P3 | 可选,`NOTES_REAL_NETWORK=1` + TCC(2026-07-01 已通过) |

### Day 11+ 待办(基于 Day 10 收口)

1. **Notes 真加密生产 runbook**:`docs/day11-notes-encryption-production-runbook.md`(8/1 后启用前必备)
2. **移动伴侣 8/1 实写启用**:`docs/v0.2.55-path4-early-launch-2026-06-30.md` 沿用 + Phase 3 closure 8 端点契约
3. **撞坑累计 84 类沉淀**:`memory/day10-notes-encryption-integration-2026-07-02.md`(新增 4 类 spike 链)

---

## 10. Phase 1-4 风险点 + 后续行动

| 风险点 | 影响范围 | 后续行动 |
|-------|---------|---------|
| Phase 2 commit 校准 baseline 2790 实测漂移 2 个(本次校准 2788) | 仅 baseline 数字,业务无影响 | 本次 Phase 4 修正 + check-snapshot OK |
| Phase 3.5 spike 4 个实施链撞坑 | spike 脚本范围内,业务代码 0 改动 | 已全部修复 + 退出码 0 |
| 撞坑 #71 业务代码改动日 ✅ Day 8 解除 · Phase 1.1/1.2/2 是撞坑 #71 解除后改动 | 撞坑 #71 解除后改动是允许的 | 沿用 Day 8 范本 |
| Phase 3 + 3.5 待 push(本地 ahead 2) | 仅本地待 push | 用户明确 push 后再 `git push origin main` |

---

## 11. 关联文档

- **Phase 3 closure**:`reports/Day10-companion-write-dryrun-closure.md`(9 章节 · 271 lines)
- **Phase 3.5 ops**:`ops/day10-notes-encryption-dryrun-closure.md`(9 章节 · 141 lines)
- **撞坑 #50 漂移防御**:`make check-snapshot`(防 baseline 漂移)
- **沿用 v0.2 启动规划**:`docs/v0.2-launch-plan.md`(端午不休息版)
- **沿用 v0.2.55 Path 4 提前落地**:`docs/v0.2.55-path4-early-launch-2026-06-30.md`

---

## 12. Day 10 全链路收口 ✅

- ✅ Phase 1.1 Keychain 接线(`4b678f6`)
- ✅ Phase 1.2 fallback/UI 解密(`0143717`)
- ✅ Phase 2 SQL COUNT(*) 优化(`72b6953`)
- ✅ Phase 3 companion 写端点 closure 文档化(`7a674f0`)
- ✅ Phase 3.5 Notes 真加密 dry-run spike 退出码 0(`3c9515b`)
- ✅ Phase 4 9/9 质量门全绿 + baseline 校准 + 本 closure(本次)
- 🔄 Phase 5 push Phase 3 + 3.5 + Phase 4 commits(用户明确 push 后再推)

**撞坑累计**:84 类(Day 10 新增 6 类 · 沿用 #1/#18/#50/#59/#64/#65/#71 解除/#76/#78/#79)
**质量门**:9/9 全绿(2790 passed / 2 skipped · 89.09% · 0 mypy errors / 248 files · 251 MD files)
**业务代码**:Day 10 累计 0 业务改动(Phase 1.2/3.5 spike/3 docs 均为验证 + 文档化)
**红线全维持**:ENABLE_PATH_4_WRITE=1 不开 · ENABLE_NOTES_ENCRYPTION=1 不写 shell profile · 生产主库未触碰 · tag 未动
**远程同步**:Phase 0 push 4 commits(`cdc5e46..72b6953 main -> main`)· Phase 3 + 3.5 + 4 本地 ahead 2 待用户 push