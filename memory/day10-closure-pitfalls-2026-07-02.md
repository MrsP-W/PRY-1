---
name: day10-closure-pitfalls-2026-07-02
description: Day 10 收口新增撞坑汇总（#79-#84）· spike 链 4 坑 #84 范本
metadata:
  type: project
---

# Day 10 收口新增撞坑汇总（2026-07-02）

> **范围**:Day 10 Phase 1.1 Keychain 接线 + Phase 1.2 fallback + Phase 2 COUNT(*) 优化 + Phase 3 companion dry-run closure + Phase 3.5 Notes 真加密 dry-run spike 期间新增撞坑 6 类（#79-#84）
> **状态**:Day 10 收口 ✅ · 6 commits · 9/9 质量门全绿 · 业务代码 0 改动
> **红线全维持**:`ENABLE_PATH_4_WRITE=1` 不开 · `ENABLE_NOTES_ENCRYPTION=1` 不写 shell profile · 生产主库未触碰

---

## 撞坑累计 Day 10 = 84 类(新增 6 类)

### #79 redactor 不能匹配 email 后半部

- **现象**:`scripts/check_keychain_redaction.py` 误把 `*@qq.com` 中的 `qq.com` 当 secret 报红
- **原因**:redactor 正则太宽,匹配到 email 后半部
- **修复**:调整 redactor 匹配规则,只匹配 `*@<domain>` 的前半部 + 不匹配常见公开域名
- **触发场景**:撞坑 #1 凭据脱敏校验
- **Why**:确保 SMTP 凭据检测不会误报公开域名
- **How to apply**:任何凭据检测脚本都要先 fuzz 一遍公开域名(yahoo/gmail/qq/outlook)避免误报

### #80 CLAUDE.md 阶段漂移(docs-only 阶段也要同步顶部)

- **现象**:docs-only 阶段(Phase 3 closure docs)只更新了 reports/,CLAUDE.md 顶部状态行没同步,导致 D-step 收官时 @检查员才发现 drift
- **原因**:`CLAUDE.md` 顶部状态行是 docs-only 的「隐形质量门」,容易被忽略
- **修复**:每次 D-step 收官前先更新 `CLAUDE.md` 顶部状态行(state file 5 件套之一)
- **触发场景**:任何 docs-only 阶段(D-step 收官、月度复盘、8/1 release tag)
- **Why**:CLAUDE.md 顶部状态行是「会话生命周期第一信号」
- **How to apply**:docs-only commit 前 5 件套检查(CLAUDE.md / README.md / SESSION-STATE.md / MODIFICATION-LOG.md / docs/v0.2-launch-plan.md)

### #81 真实模式 `--count=1`

- **现象**:spike 在 real 模式下 `--count` 参数被忽略,跑了 100 条
- **原因**:spike 脚本对 `--count` 参数解析不严,real 模式应该是 1
- **修复**:spike 脚本强制 real 模式 count=1,违者退出码 1
- **触发场景**:任何 spike 脚本对接真实链路
- **Why**:real 模式防误发 / 防误触
- **How to apply**:spike 脚本设计时 real 模式参数钉死 count=1,无 override 入口

### #82 真实写 outbox 契约

- **现象**:`test_companion_decide_post_matches_native_dry_run` 实写路径误触真实 Outbox
- **原因**:mobile companion POST dry-run 默认 `dry_run=True`,但调用层没严判,允许 override
- **修复**:mobile companion POST 钉死 `dry_run=True`(不可 override)+ 5 重门控
- **触发场景**:mobile companion 任何 POST 端点
- **Why**:companion 干路是 dry-run,实写只能走 8/1 后 `ENABLE_PATH_4_WRITE=1` + 5 门全开
- **How to apply**:任何 dry-run API 都要钉死 `dry_run=True` 默认值,不暴露 override

### #83 微信/Notes 真同步

- **现象**:Day 7 B Notes 真同步时 `NOTES_REAL_NETWORK=1` + TCC 通过但同步 0 条
- **原因**:Notes 适配器 opt-in 链路 + TCC 系统授权需双开
- **修复**:Day 7 B 启用 checklist = `NOTES_REAL_NETWORK=1` + TCC 通过 + 30s 等待
- **触发场景**:任何 Notes 真同步
- **Why**:Notes 真同步是 P3 可选,默认不动
- **How to apply**:Notes 真同步必须走 ops/day10-notes-encryption-dryrun-closure.md 范本

### #84 spike 实施链 4 坑(本撞坑 # 重点沉淀)

- **现象**:Phase 3.5 Notes 真加密 dry-run spike 实施链 4 撞坑(全在 spike 脚本范围内,业务代码 0 改动)
- **4 坑清单**:
  1. **`Note` import 顺序**:`Base.metadata.create_all` 在 `from db.notes import Note` 之前调用 → Note 未注册到 metadata → `sqlalchemy.exc.OperationalError: no such table: notes`
  2. **`is_private` bool 严判**:`NoteStore.insert` 严判 bool,spike 直接传 `is_private=0`(int)→ `TypeError`
  3. **`list_all` vs `list_by_needs_confirm`**:`NoteStore.insert` 新 note 无指纹冲突 → `needs_confirm=0`,而 `list_by_needs_confirm` 仅返回 needs_confirm=1 → "encrypted_id 不在 pending 列表中"
  4. **`NoteConfirmServiceImpl` kwarg**:真实 kwarg 是 `note_store=`,不是 `store=` → `unexpected keyword argument 'store'`
- **Why**:spike 脚本作为「真实链路 dry-run」,业务代码是契约源(spike 改),不能改业务
- **How to apply**:spike 脚本实施时严判 4 项
  - **`Note` import 顺序**:所有 `Base.metadata.create_all(engine)` 调用前必须 `from my_ai_employee.db.<table> import <Model>  # noqa: F401`(与 ORM 同源)
  - **`is_private` bool 严判**:`NoteStore.insert(..., is_private=...)` 必须 bool,不可 int
  - **`list_all` vs `list_by_needs_confirm`**:`NoteStore.insert` 默认 `needs_confirm=0`(新 note),新 note 验证用 `list_all` + `get_by_id`(沿 Phase 1.2 test_impl_cipher_mixed_plaintext_and_encrypted 范本),不用 `list_by_needs_confirm`
  - **`NoteConfirmServiceImpl` kwarg**:真实 kwarg 是 `note_store=`,非 `store=`(撞坑 #64 公共 API 一致性沿用)

---

## 与撞坑 #50/#64/#65/#71 沿用

| 沿用撞坑 | Day 10 严判点 |
|---------|-------------|
| **#50** | `make check-snapshot`(防 baseline 漂移四重防御) |
| **#64** | 公共 API 一致性(mobile companion POST = native API 响应字典完全一致) |
| **#65** | `NotesCipherImpl.decrypt` 显式 `startswith("enc:v1:")` 短路 fallback |
| **#71** | 业务代码改动日 ✅ Day 8 解除 · Day 10 累计 0 业务改动 |
| **#76/#78** | 5 重门控严判 + spike 脚本 thread-safe |

---

## 沿用 5 件套(state file 防漂移)

每次 D-step 收官必须同步:
1. `CLAUDE.md` 顶部状态行
2. `README.md` L7 + L71
3. `SESSION-STATE.md` 顶部
4. `MODIFICATION-LOG.md` 末尾 +1 条
5. `docs/v0.2-launch-plan.md`(沿用端午节版本)

---

**最后更新**:2026-07-02(Day 10 收口后)
**维护者**:Mr-PRY
**撞坑累计**:84 类(本周期新增 6 类)