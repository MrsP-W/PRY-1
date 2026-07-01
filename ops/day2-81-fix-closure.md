# Day 2 — 撞坑 #81 TCC 修复收口(2026-07-01)

> **类型**:撞坑 #81 修复收口(用户实测「3/3 通过」+ docs-only)
> **关联**:`ops/day2-b-no-response.md`(撞坑 #81 登记)+ `ops/day2-81-tcc-fix-runbook.md`(修复 runbook)
> **风险**:🟢 零业务风险(只改系统授权 + 重启进程 · 不发邮件 · 不写 DB)
> **撞坑**:**撞坑 #81**(docs-only → 已修复)

---

## §1 用户实测复测结果(2026-07-01)

| # | 操作 | 期望 | 实测 | 状态 |
|---|------|------|------|------|
| 1 | 点 **「系统健康」** | macOS 通知弹出(含 pytest/coverage 基线) | ✅ 弹窗 | OK |
| 2 | 点 **「授权引导」** | 系统设置 → 自动化页打开 | ✅ 跳转 | OK |
| 3 | **⌥⌘N**(先复制一段文字)| 通知或 badge 有反馈(Stub 阶段至少不 silent fail) | ✅ 有反馈 | OK |

**撞坑 #81 复测 3/3 全过**(沿 runbook §4 清单)。

---

## §2 修复路径(沿 runbook)

### 2.1 用户执行步骤

1. **Step 1(诊断)**:跑 `bash ops/check-pitfall-81.sh --open` → 打开辅助功能 + 自动化设置深链
2. **Step 2(TCC 补授权)**:系统设置 → 隐私与安全性 → 辅助功能 → 添加 `Python.framework 3.12` 二进制
3. **Step 3(进程清理 + 前台复测)**:
   - `bash ops/start-menubar.sh stop`(旧进程清理)
   - `make menu-bar`(前台启动)
   - 点击 macOS **桌面空白处**失焦
   - 点菜单栏 🧑‍💼 图标
   - 依次测 3 项 ✅

### 2.2 关键洞察(用户实测发现)

> **TCC 应授权 `Python.framework 3.12`,不是 `.venv/bin/python3`**

- `uv run` 在本机实际 spawn 的是 Framework Python(uv 是包装器,不是 GUI 客户端)
- 若只加了 venv 路径,补授权也可能无效
- 进程链实测:`uv` → `Python.framework/Versions/3.12/.../Python`(不是 `.venv`)

### 2.3 撞坑 #81 类别升级

- **修复前**:撞坑 #81 状态 = docs-only 登记 + Week 2 处理
- **修复后**:撞坑 #81 状态 = **已修复(用户实测 3/3 通过)**
- **影响范围**:仅交互层(rumps callback)· 数据层 / pytest / coverage / 9 质量门全绿
- **业务代码改动**:0(撞坑 #71 沿用)
- **下次评审**:不需再评审(已收口)

---

## §3 撞坑累计更新

| 撞坑号 | 状态 | 说明 |
|--------|------|------|
| **#71** | 🟢 沿用 | docs-only 不前进 pytest/coverage |
| **#59** | 🟢 维持 | outlook/gmail 红线(QQ SMTP 例外) |
| **#1** | 🟢 维持 | 不打印 Key/auth_code 到 chat/docs/commit |
| **#81** | 🟢 **已修复** | 菜单栏点击无响应 · TCC 补授权 + 前台复测 3/3 通过 |

**撞坑累计 81 类**(本棒 0 新增 · 撞坑 #81 收口不新增撞坑号)。

---

## §4 Day 3 启动准备

### 4.1 Day 3 撞坑红线解锁状态

| # | 撞坑 | 修复前 | 修复后 |
|---|------|--------|--------|
| **#81** 菜单栏点击无响应 | 🔧 Day 3 前必修 | ✅ **已修复**(3/3 通过)|
| **#76/#78/#79** 业务真实发送门控 | ⚠️ 5 重门控全开 + 用户明确授权 | ⏸️ 等用户逐项 OK |
| **#59** outlook/gmail 红线 | 🟢 维持 | 🟢 维持(QQ SMTP 例外 · outlook/gmail 不在 Day 3) |
| **#71** docs-only | 🟢 沿用 | 🟢 沿用(Day 3 真发不影响 pytest/coverage) |

### 4.2 Day 3 5 重门控清单(撞坑 #76/#78/#79)

| # | 门控 | 默认 | Day 3 需 |
|---|------|------|----------|
| 1 | `SMTP_REAL_NETWORK=1` | UNSET(显式禁止)| ✅ 激活 |
| 2 | `--confirm yes-i-understand-this-sends-real-email` | 缺失 | ✅ 必传 |
| 3 | `--count 1` | 0 | ✅ 1 封 |
| 4 | `--max-recipients 1` | 无限制 | ✅ 1 收件人 |
| 5 | **用户明确授权**(逐项 OK)| 缺失 | ⏸️ 等用户 |

### 4.3 Day 3 真发 1 封(用户决策点)

- 收件人:用户自己的 QQ 邮箱(可撤回)
- 主题:测试发送
- 真实凭据:Keychain 已就位(16 位授权码 · commit 9557179)
- 预演:先 dry-run 演示 → 再真发

---

## §5 9/9 质量门 baseline 维持

| # | 门 | 数字 |
|---|----|------|
| 1 | pytest | 2611 passed / 1 skipped |
| 2 | coverage | 88.97% |
| 3 | ruff check | All checks passed |
| 4 | ruff format | 254 files formatted |
| 5 | mypy src | 0 errors / 238 files |
| 6 | mypy src+tests | 0 errors |
| 7 | alembic --sql | OK |
| 8 | uv build | OK |
| 9 | MD lint | 231 files 0 errors |
| check-snapshot | 四重防御 | OK |

---

## §6 维护者

**Mr-PRY** · 2026-07-01 Day 2 撞坑 #81 修复收口 · 用户实测「3/3 通过」+ docs-only · 撞坑累计 81 类(撞坑 #81 收口不新增)· 业务代码 0 改动(连续 6 周 + 1 天 · 撞坑 #71 沿用)· 9 质量门 baseline 不变(2611 / 88.97% / 231 md / 238 mypy)· 等 Day 3 启动授权(5 重门控逐项 OK)。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **沿用范本**:[[ops/day2-b-no-response.md]] + [[ops/day2-81-tcc-fix-runbook.md]] + [[ops/check-pitfall-81.sh]] + `scripts/run_menu_bar.py`(撞坑 #71 B 放行 commit b9e086a)· **下一棒**:Day 3 IMAP 同步 + QQ SMTP 真发 1 封(撞坑 #76/#78/#79 需用户逐项 OK 5 重门控)。
