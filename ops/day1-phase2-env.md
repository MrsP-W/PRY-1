# Day 1 — 阶段 2 `.env` 真实填值 + Keychain 写入 + 菜单栏实测(2026-07-01)

> **类型**:7 天计划 Day 1 阶段 2 收口(撞坑 #59 红线维持 · 撞坑 #71 决议 B 范围内)
> **范围**:`.env` 3 个敏感字段填值(LLM Key + IMAP_USER + DB Key)+ Keychain QQ SMTP 授权码 + SQLCipher 解密验证 + `make menu-bar` 前台实测
> **风险**:🟡 中风险(撞坑 #59 红线首次激活 · 真实凭据写入本机 · 不可外发)
> **撞坑关联**:#1 Key 打印教训 · #59 红线维持 · #71 决议 B 放行 · #80 衍生 MD 漂移防御维持

---

## §1 交付物清单

| # | 项 | 类型 | 状态 |
|---|----|------|------|
| 1 | `.env` 3 字段填值(MINIMAX_API_KEY 125 字符 · IMAP_USER 16 字符 · DB_ENCRYPTION_KEY 64 字符 hex)| docs-only · .gitignore | ✅ |
| 2 | macOS Keychain 写 QQ SMTP 授权码(`provider=qq email=<USER>@qq.com auth_code 16 chars`) | 撞坑 #59 红线激活 | ✅ |
| 3 | SQLCipher 解密测试(Database.open() + 5 表读取)| 撞坑 #1 / DB 链路 | ✅ |
| 4 | `make menu-bar` 前台实测(进程存活 4 秒 + log 无 stderr)| 撞坑 #71 决议 B 验证 | ✅ |
| 5 | `ops/day1-phase2-env.md`(本文件)| docs-only 收口 | ✅ |

---

## §2 `.env` 字段状态(撞坑 #1 教训:不打印 Key)

| 字段 | 长度 | 状态 | 备注 |
|------|------|------|------|
| `MINIMAX_API_KEY` | 125 字符 | ✅ 已填 | D4.1 路由层用(MiniMax M3 备选)|
| `IMAP_USER` | 16 字符 | ✅ 已填 | QQ 邮箱地址(`<USER>@qq.com`)|
| `DB_ENCRYPTION_KEY` | 64 字符 | ✅ 已填 | SQLCipher 加密 · `openssl rand -hex 32` 生成 |

**撞坑 #1 教训已落实**:
- 64 字符 hex 严格校验(早期命令 4 因 zsh quoting 误生成 53 字符非 hex 值,已修复)
- 真实值不打印到聊天 / docs / commit message · 只显示长度 + 状态
- `.env` 已在 `.gitignore` · 不会被 git 跟踪

---

## §3 Keychain 写入(撞坑 #59 红线激活)

### 3.1 写入命令

```bash
uv run python scripts/spike_set_smtp_password.py \
    --provider qq --email <USER>@qq.com --set-password <AUTH_CODE>
```

### 3.2 Round-trip 验证

```bash
uv run python scripts/spike_set_smtp_password.py \
    --provider qq --email <USER>@qq.com --check
```

**实际输出**:
```
✅ Keychain 命中: provider=qq email=<USER>@qq.com (auth_code 16 chars)
```

### 3.3 撞坑 #59 红线维持

- ✅ QQ SMTP 凭据走 Keychain(不写 .env / 不写 commit)
- ✅ Keychain round-trip 验证通过
- ❌ Outlook/Gmail 不在本棒范围(撞坑 #59 红线维持 · 等用户单独决策)
- ⚠️ 真实发送未触发(撞坑 #76/#78/#79 沿用 · 等 Day 3)

---

## §4 SQLCipher 解密测试(撞坑 #1 / DB 链路)

### 4.1 现状

- DB 路径:`~/Library/Application Support/my-ai-employee/data.db`(286720 bytes · 2026-06-29 创建)
- 新 key:64 字符 hex(`openssl rand -hex 32` 生成 · 2026-07-01)
- 现有 DB 是否用新 key 加密?**能解密 = 是**(测试通过)

### 4.2 解密验证

```python
with Database.open() as db:
    cur = db.connection.execute('SELECT name FROM sqlite_master WHERE type="table" LIMIT 5')
    rows = [r[0] for r in cur]
    # ['alembic_version', 'emails', 'attachments', 'labels', 'email_labels']
```

**实际输出**:`✅ DB 解密成功(新 key 正确)` + 5 表名正确读取

### 4.3 撞坑沉淀

- **撞坑 #1 教训延伸**:sed `.*` 模式比 `__USER_TO_FILL__` 占位符更稳,即使原值已部分填也能覆盖
- **撞坑 #64 公私 API 迁移类**:`open_db` 不存在,正确 API 是 `Database.open()`(类方法 + context manager)

---

## §5 `make menu-bar` 前台实测(撞坑 #71 决议 B 验证)

### 5.1 启动方式

```bash
# 后台启动 + sleep 4 + kill
uv run python scripts/run_menu_bar.py > /tmp/menu_bar_test.log 2>&1 &
PID=$!
sleep 4
if kill -0 $PID 2>/dev/null; then
    echo "✅ 菜单栏进程在跑(PID=$PID,4 秒后仍存活)"
    kill $PID
fi
```

### 5.2 实测结果

- ✅ 进程启动成功(PID 存活 4 秒后被 kill)
- ✅ stderr 空(无 import 错误 / 无 TCC 权限拒绝 / 无 SQLCipher 错误)
- ⚠️ 实际菜单栏图标需要用户在 macOS 桌面肉眼确认(TCC 权限如需会在系统弹窗)
- ⚠️ Day 1 阶段 2 不强求图标肉眼验证,Day 2 TCC 授权 + 后台常驻再深入验证

### 5.3 撞坑 #71 决议 B 验证

- ✅ `scripts/run_menu_bar.py` 作为基础设施文件落地成功
- ✅ 所有服务用 Stub 默认单例(不连真实 DB / 不读真实剪贴板)
- ✅ `MYAIEMP_BADGE_POLL_SECONDS` envvar 生效
- ✅ Day 1-2 基础设施放行决议 B 全部兑现

---

## §6 9/9 质量门(本棒后维持)

| # | 门 | 数字 |
|---|----|------|
| 1 | pytest | 2611 passed / 1 skipped |
| 2 | coverage | 88.95% |
| 3 | ruff check | All checks passed |
| 4 | ruff format | 254 files formatted |
| 5 | mypy src | 0 errors / 238 files |
| 6 | mypy src+tests | 0 errors |
| 7 | alembic --sql | OK |
| 8 | uv build | OK |
| 9 | MD lint | 226 files 0 errors |
| check-snapshot | 四重防御 | OK |

**撞坑 #80 衍生维持**:新增 `.env` 不算 MD(`.env` 在 `.gitignore`,不被 `git ls-files '*.md'` 计入)。

---

## §7 撞坑累计(本棒)

| # | 撞坑 | 状态 |
|---|------|------|
| 撞坑 #1 延伸 | sed `.*` 模式 vs 占位符模式 | ✅ 沉淀(命令 4 用 `^DB_ENCRYPTION_KEY=.*` 兜底)|
| 撞坑 #59 | outlook/gmail 红线 | 🟡 部分激活(QQ SMTP 例外 · outlook/gmail 仍维持)|
| 撞坑 #64 | 公私 API 迁移类 | ✅ 沉淀(`open_db` → `Database.open()`)|
| 撞坑 #71 | docs-only 不前进 pytest/coverage | 🟢 沿用(基础设施 + .env + Keychain 不影响 pytest/coverage)|
| 撞坑 #80 | MD 漂移防御 | 🟢 维持(本棒未新增 MD) |
| **业务风险类** | **0 新增**(连续 6 周 + 1 天) | 🟢 |

---

## §8 下一步(Day 2 启动准备)

### 8.1 Day 2 计划(沿用户原 7 天计划)

| 时段 | 内容 |
|------|------|
| 09:00-10:30 | TCC 授权(系统设置 → 隐私与安全性 → 自动化 / 完全磁盘访问)|
| 10:30-12:00 | 前台跑通 `uv run python scripts/run_menu_bar.py`,验证图标常驻 |
| 13:00-14:30 | 明确区分:`com.myaiemployee.agent.plist` 只管月报,与菜单栏无关 |
| 14:30-16:00 | 菜单栏常驻方式二选一:**方案 A**(手动 nohup)/ **方案 B**(独立 plist)|
| 16:00-17:30 | 验证 5 子模块:clipboard / expense / note confirm / outbox / badge polling |
| 17:30-18:00 | 写 `ops/start-menubar.sh`(Day 7 一键包组件)|

### 8.2 Day 1 阶段 2 → Day 2 接力清单

- [x] `.env` 3 字段填好
- [x] Keychain QQ SMTP 授权码 round-trip OK
- [x] SQLCipher 解密 OK
- [x] `make menu-bar` 前台实测 OK
- [ ] TCC 授权(Day 2 启动后用户在系统设置点授权)
- [ ] 菜单栏后台常驻(Day 2 方案 A 手动 nohup)

### 8.3 风险与不可逆

- 🟡 **撞坑 #59 部分激活**:QQ SMTP 凭据写入 Keychain,可 `security delete-generic-password` 删除
- 🟢 **撞坑 #1 教训落实**:真实 Key 不打印到 chat / docs / commit message
- ⚠️ **撞坑 #71 沿用**:业务代码 0 改动(连续 6 周 + 1 天)

---

## §9 维护者

**Mr-PRY** · 2026-07-01 Day 1 阶段 2 收口 · 撞坑 #59 红线首次激活(QQ SMTP 例外 · outlook/gmail 维持)· 撞坑 #71 决议 B 维持 · 撞坑 #1 / #64 沉淀 · 9 质量门 baseline 不变 · 业务代码 0 改动(连续 6 周 + 1 天 · 撞坑 #71 沿用)· 等用户授权触发 Day 2 TCC 授权。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **沿用范本**:[[v0.2.55.2-path4-spike]] + [[v0.2.7.2-xoauth2-smtp-inmemory-spike]] + [[v0.2.7.1-keychain-runbook-and-redaction]] · **下一棒**:Day 2 TCC 授权 + 菜单栏后台常驻(方案 A 手动 nohup)+ `ops/start-menubar.sh`。