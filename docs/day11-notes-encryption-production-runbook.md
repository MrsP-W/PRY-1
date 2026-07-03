# Day 11 — Notes 真加密生产启用 runbook (docs-only · 2026-07-02)

> **状态**:**docs-only · 不启用生产**。本文档是 8/1 后用户明确同意启用 Notes 真加密生产链路前的必备 checklist。
> **承接**:Day 10 Phase 1.1 Keychain 接线(`4b678f6`)+ Phase 1.2 fallback 集成测试(`0143717`)+ Phase 3.5 spike(`3c9515b`)+ Phase 4 9 门全绿(`429a7a1`)。
> **红线全维持**:`ENABLE_NOTES_ENCRYPTION=1` 默认 UNSET · 不写 shell profile · 不动生产主库 · 90 封 SMTP 跳过 · tag 不动。

---

## 1. 启用前置条件(5 道门 · 全部 ✅ 才允许进入 §2)

| # | 门 | 验证命令 | 期望输出 |
|---|----|---------|---------|
| **1.1** | Keychain 已有 notes master key | `security find-generic-password -s "com.my-ai-employee.notes-encryption" -a "notes_master_key" -w` | 输出 64 字符 hex(32 字节随机) |
| **1.2** | 当前生产主库全部为 legacy 明文或已知混合 | `sqlite3 ~/Library/Application\ Support/my-ai-employee/data.db "SELECT COUNT(*) FROM notes WHERE title NOT LIKE 'enc:v1:%' AND body NOT LIKE 'enc:v1:%'"` | 输出 = 笔记总数(全部明文) |
| **1.3** | `ENABLE_NOTES_ENCRYPTION=1` 未写 shell profile | `grep -r "ENABLE_NOTES_ENCRYPTION" ~/.zshrc ~/.bash_profile ~/.zprofile 2>/dev/null` | 无输出 |
| **1.4** | `ENABLE_PATH_4_WRITE=1` 未设置 | `echo "ENABLE_PATH_4_WRITE=${ENABLE_PATH_4_WRITE:-UNSET}"` | 输出 `UNSET` |
| **1.5** | 9/9 质量门全绿 | `make ci` | 全部绿 · 沿用 Day 11+12 baseline 2791 / 1 skipped / 89.09% / 248 mypy / **254 MD**(2026-07-03 Day 12 checkpoint 补齐后 baseline 升 253→254) |

**任一不满足 → 终止并修复,绝不进入 §2**。

---

## 2. opt-in 步骤(5 步 · docs-only 阶段禁止执行)

### Step 1 · 临时环境变量导出(不写 shell profile)

```bash
# 仅当前 shell 生效,关掉即失效(沿撞坑 #1 红线)
export ENABLE_NOTES_ENCRYPTION=1
```

### Step 2 · 启动 spike dry-run 复核(沿 Day 10 Phase 3.5 spike 范本)

```bash
uv run python scripts/spike_day10_notes_encryption_dryrun.py
```

期望:`exit 0` · 输出 `6 段 [OK] opt-in / DB / prefix / decrypt / 菜单栏 / Dashboard`。**非 0 → 终止并排查**(撞坑 #84 链)。

### Step 3 · 启动应用(菜单栏 / Dashboard 任一)

```bash
make dev    # 菜单栏
# 或
make dashboard    # Dashboard(若已实现启动入口)
```

期望:菜单栏系统健康弹窗 → "Notes 加密: opt-in(仅当前 session)"。

### Step 4 · 新笔记写入验证(单条)

```bash
# 触发一次剪贴板 → Notes 端到端(沿 D9.6 范本)
echo "Day 11 opt-in 验证笔记 $(date)" | pbcopy
```

期望:菜单栏 → Notes → 新笔记入库,title/body 以 `enc:v1:` 开头(SELECT 库内前缀验证)。

### Step 5 · 旧笔记读取验证(混合模式)

- 打开菜单栏 → 笔记 → 待确认列表
- 期望:legacy 明文笔记正常显示(明文存储,不需要解密)
- 期望:新写入的加密笔记正常显示(透明解密,撞坑 #65 短路 fallback 沿用)

---

## 3. 历史明文混合读取策略(撞坑 #65 沿用)

### 3.1 读取层透明解密

`NotesCipherImpl.decrypt` 严判 `startswith("enc:v1:")`:

- ✅ `enc:v1:<hex>` → AES-GCM 解密 + 验签 → 返回明文
- ✅ 任意 legacy 明文 → 短路返回(不报错,不二次加密)

### 3.2 写入层 opt-in 门控

`NoteStore.insert(..., encrypted=False)` 默认值 + opt-in 时 `NoteStore(cipher=NotesCipherImpl)`:

- ✅ opt-in UNSET → `encrypted=False`(明文写入,沿用历史)
- ✅ opt-in SET → `cipher.encrypt()` 透明加密(沿 `enc:v1:` 前缀)

### 3.3 库内混合状态可观测

```sql
SELECT
  CASE WHEN title LIKE 'enc:v1:%' THEN 'encrypted' ELSE 'plaintext' END AS status,
  COUNT(*) AS cnt
FROM notes
GROUP BY status;
```

期望:opt-in 前 = `plaintext=N`,opt-in 后新写入 = `encrypted=1+`,legacy 不变。

---

## 4. re-encrypt 策略(**默认不做 bulk · 单条级可选**)

### 4.1 为什么不做 bulk re-encrypt

- ❌ **撞坑 #1 红线**:bulk 操作触发整库写入,误操作风险高(全量 re-encrypt 失误 = 全库不可读)
- ❌ **撞坑 #71 业务代码改动日**:bulk re-encrypt 需引入一次性迁移脚本,撞坑 #71 解除后改动也要严判
- ❌ **撞坑 #50 baseline 漂移**:bulk 操作会触发覆盖率/mypy 报告短时漂移,需手动校准
- ✅ **沿 Day 10 Phase 3.5 spike 范本**:每条新笔记 opt-in 写入时自动加密,legacy 笔记「不动」

### 4.2 单条 re-encrypt 流程(可选 · 用户明确请求时执行)

```bash
# 仅针对特定 id 单条 re-encrypt(沿撞坑 #76 五重门控)
# 步骤:
# 1) SELECT 当前 note(明文)
# 2) UPDATE title/body = cipher.encrypt(title/body)
# 3) SELECT 验证前缀 enc:v1:
# 4) SELECT 验证解密 round-trip
# 5) AuditRecord 落档(撞坑 #82 沿用)
```

### 4.3 不可逆约束

- ✅ re-encrypt 不可批量(单条 ≤ 5 分钟人工操作)
- ✅ re-encrypt 前必须 SELECT + UPDATE + SELECT 三段审计
- ✅ re-encrypt 必须留 backup(db.copy(~/backup/notes_pre_reencrypt_<ts>.db))

---

## 5. 回滚策略(3 步 · 任何阶段失败立即执行)

### Step 1 · 关 opt-in

```bash
unset ENABLE_NOTES_ENCRYPTION
```

### Step 2 · 重启应用

```bash
# 菜单栏 / Dashboard 重启
make dev
```

### Step 3 · 验证 legacy 仍可读

- 打开菜单栏 → 笔记 → 列表正常显示
- 打开 Dashboard → /api/notes/pending 正常响应
- 新写入的 `enc:v1:` 笔记通过 `startswith` 短路返回(明文视图)

**回滚后状态**:
- opt-in 关闭 → 新写入明文(legacy 模式)
- 已写入的 `enc:v1:` 笔记 → 通过短路 fallback 仍可读(撞坑 #65 沿用)
- Keychain 密钥不动(下次 opt-in 仍可复用)

---

## 6. TCC / 隐私 / 合规

### 6.1 TCC(Transparency, Consent, Control)

- ✅ Notes 加密启用是**本地行为**,不触发系统 TCC 弹窗(与 Day 6/7 微信账单 TCC 不同)
- ✅ Keychain 密钥存储是 macOS Keychain 本地加密(撞坑 #1 红线,系统级保护)
- ❌ **不做** 网络上传 / 跨设备同步 / 云备份

### 6.2 隐私边界

- ✅ master key 仅存 macOS Keychain,服务名 `com.my-ai-employee.notes-encryption`,账号 `notes_master_key`
- ❌ **不写** `~/.env` / `.env.local` / 任何 dotenv 文件(沿撞坑 #1)
- ❌ **不写** shell profile / launchd plist(沿 Day 10 红线)
- ❌ **不打印** key 到 chat / docs / commit message(沿撞坑 #1)

### 6.3 合规与审计

- ✅ opt-in / opt-out 不触发任何 audit log(本地行为)
- ✅ re-encrypt 单条操作必须留 AuditRecord(撞坑 #82)
- ❌ **不引入** GDPR / CCPA / 等保 相关流程(本地工具,无云服务)

---

## 7. 与 Day 10 范本对齐(避免重复)

| Day 10 范本 | Day 11 沿用 |
|------------|-----------|
| `scripts/spike_day10_notes_encryption_dryrun.py` | ✅ 复用为 §2 Step 2 dry-run 复核 |
| `ops/day10-notes-encryption-dryrun-closure.md` | ✅ 引用为「前置链路收口证据」 |
| `core/notes_encryption.py` `ENABLE_NOTES_ENCRYPTION_ENV` | ✅ 沿用 §2 Step 1 环境变量名 |
| `core/keychain.py` `KEYCHAIN_SERVICE_NOTES` | ✅ 沿用 §1.1 Keychain 服务名 |
| 撞坑 #65 短路 fallback | ✅ 沿用 §3.1 读取层透明解密 |
| 撞坑 #50 baseline 漂移防御 | ✅ 沿用 §1.5 质量门验证 |

---

## 8. 不做的事(整段项目红线)

- ❌ **不**写 `ENABLE_NOTES_ENCRYPTION=1` 到 shell profile / launchd plist
- ❌ **不**对生产主库批量 re-encrypt(只单条可选,§4.2)
- ❌ **不**移动 `v0.1.0` / `v0.2.1-rc1` / `v0.2.1` tag
- ❌ **不**跑 90 封 SMTP / 不配置 Outlook/Gmail
- ❌ **不**自动启用(必须用户明确同意 + 5 道门全 ✅ + 单次手动 export)

---

## 9. 后续锚点(Day 11+ 决策点)

| 决策项 | 当前 | 触发 |
|-------|------|------|
| **启用 Notes 真加密生产** | ⏸️ 延后 | 用户明确同意 + §1 五道门全 ✅ + §2 五步按序执行 |
| **Day 9+ 移动伴侣写端点 dry-run** | ⏸️ 沿 Phase 3 closure | 8/1 后 `ENABLE_PATH_4_WRITE=1` 启用准备 |
| **撞坑累计沉淀** | ✅ Day 10 = 84 类 | 沿 `memory/day10-closure-pitfalls-2026-07-02.md` |
| **Day 7 A 支付宝真导** | ⏸️ 用户决策 | 用户提供 ZIP 密码或解压 CSV |

---

**最后更新**:2026-07-02(Day 10 收口后 docs-only 启动)
**状态**:📘 docs-only · 不启用生产 · 等待用户决策
**维护者**:Mr-PRY
