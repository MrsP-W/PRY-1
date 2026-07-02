# Day 10 Phase 3.5 — Notes 真加密生产链路 Dry-run 收口

> **范围**:Day 10 Phase 3.5 — Notes 真加密 dry-run spike(沿 Day 10 Phase 1.1 Keychain 接线 + Phase 1.2 fallback 集成测试)
> **目标**:端到端验证 Notes 真加密生产链路在 `ENABLE_NOTES_ENCRYPTION=1` opt-in 下完整可行
> **原则**:仅 mock Keychain + 临时 SQLite DB,**不写** shell profile / launchd · **不碰** 生产主库 · **不开** Notes 真加密生产
> **承接**:Day 10 Phase 1.1 Keychain notes master key 接线(`4b678f6`)+ Phase 1.2 fallback 集成测试(`0143717`)+ Phase 2 SQL COUNT(*) 优化(`72b6953`)
> **状态**:✅ 收口(2026-07-02)· **spike 退出码 0** · **业务代码 0 改动** · **生产主库未触碰**

---

## 1. 边界(严判维持)

| 红线 | 状态 |
|------|------|
| 不开 `ENABLE_NOTES_ENCRYPTION=1` 生产 | ✅ 仅 spike 进程内 `monkeypatch.setenv`,不写 shell profile / launchd |
| 不动 `~/Library/Application Support/my-ai-employee/data.db` | ✅ 临时 DB 路径 `/tmp/spike_day10_notes_<random>/notes.db`,跑完 `shutil.rmtree` |
| 不写 `ENABLE_NOTES_ENCRYPTION=1` 到 shell profile | ✅ 仅进程内 setenv,进程退出 env 销毁 |
| 不跑 90 封 SMTP · 不配 Outlook/Gmail | ✅ 沿用红线 |
| 不移动 `v0.1.0` / `v0.2.1-rc1` / `v0.2.1` tag | ✅ 沿用红线 |

---

## 2. Spike 设计(7 阶段流程)

```
spike_day10_notes_encryption_dryrun.py — 沿 scripts/spike_d8_1000.py 4 退出码契约
```

| # | 阶段 | 验证点 |
|---|------|--------|
| 1 | **opt-in 链路** | `ENABLE_NOTES_ENCRYPTION=1` 进程内 setenv + mock Keychain `load_notes_master_key()` → `build_notes_cipher()` 返回 `NotesCipherImpl` |
| 2 | **临时 DB** | `tempfile.mkdtemp` + `Base.metadata.create_all(engine)` + `Note` 表 import |
| 3 | **Seed 2 notes** | 1 条明文(SQLAlchemy `session.add`,模拟历史)+ 1 条新加密(`NoteStore.insert` → Impl cipher) |
| 4 | **库内前缀严判** | legacy 无 `enc:v1:` 前缀;encrypted 有 `enc:v1:` 前缀 |
| 5 | **NoteStore 解密** | `list_all(limit=10)` + `get_by_id(encrypted_id)` 返回明文,无 `enc:v1:` 泄露 |
| 6 | **菜单栏解密** | `NoteConfirmServiceImpl.list_pending_confirm(limit=10)` 返回明文(legacy 为主,encrypted `needs_confirm=0` 故不在 pending 列表) |
| 7 | **Dashboard payload** | `build_notes_pending_payload` 返回 6 字段白名单(apple_note_id/title/folder/synced_at_ms/candidate_match_id/needs_confirm),无密文泄露 |

---

## 3. 实测输出(2026-07-02)

```
[OK] opt-in 链路就绪: cipher=NotesCipherImpl, key_len=32
[OK] 临时 DB: /var/folders/v0/.../spike_day10_notes_xxx/notes.db
[OK] 库内前缀严判: legacy=plaintext, encrypted=enc:v1: 前缀
[OK] list_all + get_by_id 解密: 2 条全部明文返回 (legacy 明文 + encrypted 解密,无 enc:v1: 前缀泄露)
[OK] 菜单栏 NoteConfirmServiceImpl 解密: 1 条明文 (legacy 明文为主,encrypted 不在 pending 因 needs_confirm=0)
[OK] Dashboard payload: 1 条明文,字段白名单严判通过 (legacy 为主,encrypted 解密路径在步骤 5 已验证)

============================================================
Day 10 Phase 3.5 Notes 真加密 dry-run spike — 全绿
============================================================
  opt-in: ENABLE_NOTES_ENCRYPTION=1 (进程内)
  master key: 32 bytes (mock,run-end 自动销毁)
  cipher: NotesCipherImpl (Phase 1.1 P1 默认)
  DB: 临时 SQLite file (跑完删除)
  notes: 2 (1 legacy plaintext + 1 new enc:v1:)
  NoteStore.list_all + get_by_id 解密: 2 条明文
  NoteConfirmServiceImpl.list_pending_confirm: 1 条明文 (legacy 为主,encrypted needs_confirm=0)
  Dashboard /api/notes/pending payload: 1 条明文 + 6 字段白名单
  生产主库未触碰 ~/Library/Application Support/my-ai-employee/data.db
  shell profile 未写 ENABLE_NOTES_ENCRYPTION=1
```

**退出码**:`0`(沿 `scripts/spike_d8_1000.py` 4 退出码契约)

---

## 4. 撞坑汇总(spike 实施链踩过的坑)

| # | 现象 | 原因 | 修复 |
|---|------|------|------|
| 1 | `sqlalchemy.exc.OperationalError: no such table: notes` | `Base.metadata.create_all` 在 `from db.notes import Note` 之前调用 → Note 未注册到 metadata | 在 `create_all` 前加 `from my_ai_employee.db.notes import Note  # noqa: F401` |
| 2 | `TypeError: is_private 必须是 bool(非 int 子类)` | `NoteStore.insert` 严判 bool,spike 直接传 `is_private=0`(int) | 改 `is_private=False`(沿 NoteStore 范本) |
| 3 | `encrypted_id 不在 pending 列表中` | `NoteStore.insert` 新 note 无指纹冲突 → `needs_confirm=0`,而 `list_by_needs_confirm` 仅返回 needs_confirm=1 | 改用 `list_all` + `get_by_id` 验证加密 note 解密(沿 Phase 1.2 test_impl_cipher_mixed_plaintext_and_encrypted 范本) |
| 4 | `NoteConfirmServiceImpl.__init__() got an unexpected keyword argument 'store'` | 真实 kwarg 是 `note_store=`,不是 `store=` | 修 spike 调 `NoteConfirmServiceImpl(note_store=store)` |

**累计 4 个撞坑**,全部在 spike 脚本范围内修复,**业务代码 0 改动**(沿撞坑 #71 业务代码改动日已 Day 8 解除)。

---

## 5. 端到端覆盖矩阵

| 阶段 | 库内状态 | NoteStore | 菜单栏 NoteConfirmServiceImpl | Dashboard /api/notes/pending |
|------|---------|-----------|-------------------------------|------------------------------|
| **legacy 明文** | title/body 明文,无 `enc:v1:` | `list_all` 解密→明文 ✓ | `list_pending_confirm` 解密→明文 ✓ | `build_notes_pending_payload` 解密→明文 + 6 字段 ✓ |
| **encrypted 新** | title/body `enc:v1:` 前缀 | `get_by_id` 解密→明文 ✓ | 不在 pending 因 `needs_confirm=0` | 不在 payload 因 `needs_confirm=0`(沿业务逻辑) |

**核心验证**:encrypted note 在 DB 落 `enc:v1:` 前缀,NoteStore 解密路径返明文 → **撞坑 #65 旧明文 fallback 不受影响**(新增 1 阶段 spike 验证)。

---

## 6. 与 Phase 1.1 / 1.2 / 2 收口链关系

| Phase | 范围 | 与 Phase 3.5 关系 |
|-------|------|------------------|
| **Phase 1.1** (`4b678f6`) | Keychain notes master key 接线 + `load_notes_master_key()` 工厂 | Phase 3.5 spike **mock** `load_notes_master_key` 替代真 Keychain(避免污染) |
| **Phase 1.2** (`0143717`) | fallback 集成测试 + Dashboard/菜单栏解密展示测试 | Phase 3.5 spike **复用** 同样的明文/加密混合验证范本(`list_all` + `get_by_id`) |
| **Phase 2** (`72b6953`) | `count_by_needs_confirm` SQL `COUNT(*)` 优化 | Phase 3.5 spike **未触**(纯功能验证,不走 count 路径) |
| **Phase 3.5** (本次) | Notes 真加密生产链路 dry-run spike | ✅ 收口 |

---

## 7. 不做的事(明确边界)

- ❌ **不**将 `ENABLE_NOTES_ENCRYPTION=1` 写入 shell profile / launchd / `.env`(`.env` 在 `.gitignore`)
- ❌ **不**对生产主库 `~/Library/Application Support/my-ai-employee/data.db` 批量 re-encrypt 历史明文 notes
- ❌ **不**改 `NoteStore` 默认构造(Phase 1.1 P1 已 default `build_notes_cipher(load_notes_master_key())`,沿用)
- ❌ **不**改业务代码(撞坑 #71 业务代码改动日 ✅ Day 8 解除,本次纯 spike 脚本新增)
- ❌ **不**新增真实写路径(mobile 仅 dry-run,沿 Phase 3 closure 红线)

---

## 8. 后续锚点

- ✅ Phase 0 push 4 commits(2026-07-02 · `cdc5e46..72b6953 main -> main`)
- ✅ Phase 1.1 Keychain 接线(`4b678f6`)
- ✅ Phase 1.2 fallback 集成测试(`0143717`)
- ✅ Phase 2 SQL COUNT(*) 优化(`72b6953`)
- ✅ Phase 3 companion 写端点 closure 文档化(`7a674f0`)
- ✅ **Phase 3.5 Notes 真加密 dry-run(本次)** — spike 全绿 · 退出码 0
- 🔄 Phase 4 全量 9 门 + Day 10 收官(`make ci` + `reports/Day10-closure.md`)
- ⏸️ Day 7 A 支付宝真导(用户提供 zip 密码后启动,4 重门控 `--max-rows 1`)
- ⏸️ Notes 真加密生产启用 — **等用户明确授权**(需用户口头/书面同意,本 spike 仅验证链路,不开生产)

---

## 9. 用户决策点(等用户授权)

| 决策项 | 当前状态 | 解锁条件 |
|--------|---------|---------|
| **Notes 真加密生产启用** | ⏸️ 延后 | 用户明确同意 + 写入 shell profile `export ENABLE_NOTES_ENCRYPTION=1` + 历史主库 re-encrypt runbook 评估 |
| **Phase 4 全量 9 门** | 🔄 准备 | 直接跑 `make ci`(本地 2790 → 待实测)|
| **push 4 commits** | ⏸️ 用户决策 | 用户说 push 我再推 `git push origin main` |

---

**撞坑累计**:本次 spike 链 4 个新踩坑(spike 脚本范围内,业务代码 0 改动)
**质量门**:Phase 3.5 docs-only,无业务代码变更,无需重跑 9 门
**红线维持**:整段项目红线全部维持,本次 spike 在严判边界内实施