# Day 2 — 菜单栏后台常驻 + 5 子模块验证(2026-07-01)

> **类型**:Day 2 收口(沿用户原 7 天计划 Day 2 时段)
> **文件**:`ops/start-menubar.sh` 后台启动 + 5 子模块代码路径验证
> **风险**:🟡 中风险(撞坑 #59 红线部分激活 · 撞坑 #71 决议 B 范围内)
> **撞坑关联**:#71 决议 B 放行 · #59 红线维持 · #50 漂移防御 · #80 衍生 MD 漂移

---

## §1 Day 2 时段完成度

| 时段 | 内容 | 状态 |
|------|------|------|
| 09:00-10:30 | TCC 授权(系统设置 → 隐私与安全性 → 自动化 / 完全磁盘访问)| ⏸️ 用户物理操作(如未授权,菜单栏启动时会触发系统弹窗)|
| 10:30-12:00 | 前台跑通菜单栏 + 肉眼确认图标 | ⏸️ 用户物理确认 |
| 13:00-14:30 | 明确区分:`com.myaiemployee.agent.plist` 只管月报 | ✅ 已 Day 1 阶段 1 确认(沿用)|
| 14:30-16:00 | 菜单栏常驻方式二选一:**方案 A** | ✅ 选 A(手动 nohup 走 `ops/start-menubar.sh`)|
| 16:00-17:30 | 验证 5 子模块:clipboard / expense / note confirm / outbox / badge polling | ✅ 代码路径 5/5 验证通过 |
| 17:30-18:00 | 写 `ops/start-menubar.sh`(Day 7 一键包组件)| ✅ 提前到 Day 1 commit `2f97fdd` |

**Day 2 实际完成度 = 95%**(代码路径全绿,仅剩用户物理确认图标 + TCC 授权)

---

## §2 菜单栏后台启动(方案 A)

### 2.1 启动命令

```bash
bash ops/start-menubar.sh start
```

### 2.2 实测结果

```
[13:20:39] 启动菜单栏后台常驻...
✅ 菜单栏已启动(PID=38516,log=/Users/wei/.../data/menu_bar.log)
[13:20:44] 最近日志(最后 5 行):
(空 — 无 stderr 输出)
```

### 2.3 状态确认

```bash
$ bash ops/start-menubar.sh status
✅ 菜单栏在跑(PID=38516)
```

### 2.4 关键路径

| 路径 | 用途 | 状态 |
|------|------|------|
| `data/menu_bar.log` | stdout/stderr 日志 | ✅ 存在(0 字节,无错误)|
| `data/menu_bar.pid` | 当前进程 PID | ✅ 38516 |
| `scripts/run_menu_bar.py` | 实际启动脚本 | ✅ 撞坑 #71 B 放行(commit b9e086a)|

---

## §3 5 子模块代码路径验证

### 3.1 测试文件清单

| 子模块 | 测试文件 | 测试数 | 状态 |
|--------|---------|--------|------|
| **clipboard capture** | `tests/menu_bar/test_clipboard_capture.py` | 13 | ✅ |
| **note confirm** | `tests/menu_bar/test_note_confirm_service.py` | 23 | ✅ |
| **outbox draft** | `tests/menu_bar/test_outbox_draft_service.py` | 7 | ✅ |
| **badge polling** | `tests/menu_bar/test_badge_realtime_refresh.py` | 17 | ✅ |
| **expense service** | `tests/core/test_expense_service.py` + `test_expense_aggregate.py` | 撞坑 #72 ExpenseServiceStub 实化收口 | ✅ |
| **小计(menu_bar/)** | 4 文件 | **60 tests** | ✅ |
| **总 pytest menu_bar** | — | **122 passed** | ✅ |

### 3.2 菜单项实际定义(`src/my_ai_employee/menu_bar/app.py` L332-345)

```python
self.menu: list[Any] = [
    f"{_MENU_TODAY_PENDING} (0)",       # badge: 今日待办
    f"{_MENU_MAIL_DRAFT} (0)",          # badge: 待发邮件
    f"{_MENU_NOTES_CONFIRM} (0)",       # badge: 笔记待确认
    f"{_MENU_FINANCE_ANOMALY} (0)",     # badge: 财务异常
    "快捷捕获 ⌥⌘N",                     # clipboard capture
    "📥 确认第 1 条",                    # note confirm
    "立即同步",                          # clipboard capture / sync
    "打开 Notes",                        # Apple Notes
    "打开工作台",                        # dashboard 入口
    "系统健康",                          # quality snapshot
    None,                                # 分隔符
    "授权引导",                          # TCC 授权
    "退出",                              # 退出 menu bar
]
```

### 3.3 5 子模块 vs 菜单项映射

| 5 子模块 | 对应菜单项 | 真实功能(撞坑 #59 红线内) |
|---------|----------|--------------------------|
| clipboard capture | 快捷捕获 ⌥⌘N · 立即同步 | ⌥⌘N 捕获剪贴板 → NoteStructurerService |
| expense 告警 | 财务异常 (badge)| 异常检测 → 5 分钟缓存 → badge 实时刷新 |
| note confirm | 📥 确认第 1 条 · 笔记待确认 (badge)| NoteStore 5 状态机(NEW/STRUCTURED/PRIVATE_SKIP/FAILED/ARCHIVED)|
| outbox draft | 待发邮件 (badge)| OutboxDraftService → outbox 库草稿计数 |
| badge polling | 4 个 badge | `_refresh_all_badges()` + polling thread(默认 30s)|

---

## §4 撞坑累计(本棒)

| # | 撞坑 | 状态 |
|---|------|------|
| **#71** docs-only 不前进 pytest/coverage | 🟢 沿用(本棒新行为:菜单栏后台启动,不影响 pytest/coverage)|
| **#59** outlook/gmail 红线 | 🟡 部分激活(QQ SMTP Keychain · outlook/gmail 仍维持)|
| **#50** 漂移防御 | 🟢 维持(228 md 同步)|
| **#80** MD 漂移防御 | 🟢 维持(无新增 MD)|
| **业务风险类 0 新增** | 🟢 沿用(连续 6 周 + 1 天) |

---

## §5 用户本人物理操作(Day 2 收口前必做)

### 5.1 ⏸️ 肉眼确认菜单栏图标

1. 打开 macOS 桌面右上角菜单栏(时钟旁边)
2. 查找新增的菜单栏图标(应该是 🔥 或类似 emoji,具体看 app.py 默认 icon)
3. 点击图标 → 应弹出 13 项菜单(§3.2 列表)
4. 截图 / 确认后告诉我"图标已确认"

### 5.2 ⏸️ TCC 授权(若系统弹窗)

如果点击菜单栏功能时 macOS 弹窗询问:
- **完全磁盘访问**:同意
- **自动化**:允许(Apple Notes / Mail 等)
- **辅助功能**(若用 ⌥⌘N 快捷键):同意

### 5.3 ⏸️ 5 子模块真实功能验证(可选 Day 2 收口前)

| 子模块 | 真实功能触发 |
|--------|------------|
| clipboard | ⌥⌘N 触发 → 看菜单栏 badge 是否更新 |
| expense | 触发 expense_service → 看「财务异常 (N)」badge 是否更新 |
| note confirm | 创建 1 条 note → 看「笔记待确认 (N)」badge 是否更新 |
| outbox draft | 创建 1 封草稿 → 看「待发邮件 (N)」badge 是否更新 |
| badge polling | 默认 30s 间隔,看 badge 是否自动刷新 |

---

## §6 9/9 质量门 baseline 维持

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
| 9 | MD lint | 228 files 0 errors |
| check-snapshot | 四重防御 | OK |

---

## §7 下一步(Day 3 启动准备)

### 7.1 Day 3 计划回顾(沿用户原 7 天计划)

| 时段 | 内容 |
|------|------|
| 09:00-10:00 | 先跑 `--help` 确认参数:`uv run python scripts/sync_imap.py --help` |
| 10:00-12:00 | IMAP 首次同步:`uv run python scripts/sync_imap.py --provider qq --email <USER>@qq.com` |
| 13:00-14:30 | 分类/草稿链路冒烟 |
| 14:30-16:00 | **QQ SMTP 真发 1 封**(5 重门控全开)|
| 16:00-17:00 | 菜单栏 1-click 审批 → 发送闭环 |
| 17:00-18:00 | 记录 audit 日志 + 失败重试行为 |

### 7.2 Day 3 撞坑红线

| # | 撞坑 | 影响 |
|---|------|------|
| **#76/#78/#79** 业务真实发送门控 | ⚠️ Day 3 真发 1 封触达撞坑红线 | 必须 5 重门控全开 + 用户明确授权 |
| **#59** outlook/gmail 红线 | 🟢 维持(QQ SMTP 例外 · outlook/gmail 不在 Day 3)|
| **#71** docs-only 不前进 pytest/coverage | 🟢 沿用(Day 3 真发不影响 pytest/coverage)|

---

## §8 维护者

**Mr-PRY** · 2026-07-01 Day 2 收口(95% · 仅缺用户物理确认)· 撞坑 #71 决议 B 范围内 · 撞坑 #59 红线部分激活(QQ SMTP 例外)· 9 质量门 baseline 不变 · 业务代码 0 改动(连续 6 周 + 1 天 · 撞坑 #71 沿用)· 等用户肉眼确认 + Day 3 启动授权。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **沿用范本**:[[ops/day1-phase2-env.md]] + [[ops/day2-start-menubar-prereq.md]] + `scripts/run_menu_bar.py`(撞坑 #71 B 放行 commit b9e086a)· **下一棒**:Day 3 IMAP 同步 + QQ SMTP 真发 1 封(撞坑 #76/#78/#79 需用户明确授权)。