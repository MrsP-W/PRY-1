# Day 1 — 基础设施落地 + 9 质量门 baseline(2026-07-01)

> **类型**:7 天计划 Day 1 阶段 1 交付物(撞坑 #71 决议 B 范围内)
> **范围**:`make install` + `make hello` + `alembic upgrade head` + `make ci` baseline + 新写 `scripts/run_menu_bar.py` + Makefile `menu-bar` target
> **风险**:🟢 零业务风险(只写基础设施文件,不读真实凭据 / 不写真实 DB / 不发邮件)
> **下一阶段**:Day 1 阶段 2(等用户提供 LLM API Key + QQ 授权码 → .env 真实填值 + Keychain 写入)

---

## §1 交付物清单

| # | 文件 | 类型 | 行数 | 状态 |
|---|------|------|------|------|
| 1 | `scripts/run_menu_bar.py` | 新增 | 52 | ✅ ruff check/format/mypy 全绿 |
| 2 | `Makefile` | 修改 | +5 行(menu-bar target + help 文案) | ✅ |
| 3 | `ops/day1-baseline.md`(本文件)| 新增 | 9 节 | ✅ |

---

## §2 9/9 质量门 baseline(撞坑 #50 第三层防御)

| # | 门 | 状态 | 数字 |
|---|----|------|------|
| 1 | pytest | ✅ | 2611 passed / 1 skipped / 88.95% coverage |
| 2 | ruff check | ✅ | All checks passed |
| 3 | ruff format | ✅ | 254 files already formatted |
| 4 | mypy src | ✅ | 0 errors / 238 source files |
| 5 | mypy src+tests | ✅ | 0 errors |
| 6 | alembic --sql | ✅ | head 16 (0016_approval_gate_audits) |
| 7 | uv build | ✅ | wheel + sdist OK |
| 8 | MD lint | ✅ | 225 files 0 errors(未变) |
| 9 | coverage | ✅ | 88.95% ≥ 80% |

`make check-snapshot` 四重防御 OK(quality_snapshot + state entries + pytest collect + CLAUDE 入口)。

---

## §3 `scripts/run_menu_bar.py` 设计要点

### 3.1 为什么需要新脚本(用户原计划描述)

- `menu_bar/app.py` 没有 `__main__` 守卫,无法 `python -m menu_bar.app` 直接启动
- 用户原计划里 Day 1 15:30-17:30 时段明确要求"新写 `scripts/run_menu_bar.py`(菜单栏当前无可执行入口,`app.py` 没有 `__main__`)"

### 3.2 实现要点

1. **sys.path 注入 `src/`**:`uv run python scripts/run_menu_bar.py` 直接可用,无需 PYTHONPATH
2. **所有服务用 None 默认值**:不连真实 DB / 不读真实剪贴板(Stub 默认单例)
3. **`MYAIEMP_BADGE_POLL_SECONDS` envvar 覆盖默认 30s**(沿 v0.2.2 启动候选 #6 范本)
4. **范围 [0, 3600] 严判**:避免负值 / > 1h 异常,沿 v0.2.2 启动候选 #6 type 严判范本
5. **noqa: E402**:沿 `scripts/check_state_entries.py` 范本(sys.path.insert 后 import)
6. **撞坑 #71 决议 B 明确**:文件 docstring 内说明"撞坑 #71 docs-only 边界外,撞坑 #59 红线维持"

### 3.3 启动方式

| 方式 | 命令 | 用途 |
|------|------|------|
| 前台调试 | `uv run python scripts/run_menu_bar.py` | 看到 stderr 输出 + Ctrl+C 退出 |
| 前台(make)| `make menu-bar` | Makefile target,Day 1 验收用 |
| 后台常驻(Week 1 方案 A)| `nohup uv run python scripts/run_menu_bar.py > data/menu_bar.log 2>&1 &` | Day 2 落地 |
| 后台封装(Week 1 方案 B)| `bash ops/start-menubar.sh`(Day 2 写) | 一键启动 + 日志重定向 |
| Day 7 一键包 | `bash ops/start-digital-employee.sh`(Day 7 写)| 菜单栏 + Dashboard 同时启动 |

---

## §4 Makefile menu-bar target

```makefile
.PHONY: menu-bar
menu-bar: ## Day 1 — 启动菜单栏常驻(前台,Ctrl+C 退出;后台用 nohup 或 ops/start-menubar.sh)
	@echo "$(BLUE)🍎 启动菜单栏常驻(Day 1 基础设施)$(RESET)"
	@$(PYTHON) scripts/run_menu_bar.py
```

help 文案同步追加:`make menu-bar` 显示在 `make help` 输出中。

---

## §5 DB 初始化状态

```
$ uv run alembic current
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
0016_approval_gate_audits (head)
```

- DB 路径:`~/Library/Application Support/my-ai-employee/data.db`(286720 bytes)
- 最新迁移:`0016_approval_gate_audits`(沿 v0.2.53 收口范本)
- 已存在(2026-06-29 创建),无需重新初始化
- 阶段 2 真实凭据激活后会通过 SQLCipher key 解密(用户必须先设 `SQLCIPHER_KEY` env)

---

## §6 撞坑决议(本棒明确)

### 6.1 撞坑 #71 决议 B(部分反转)

- **范围**:Day 1 仅基础设施文件(脚本 + Makefile + ops/)在撞坑 #71 docs-only 边界外
- **理由**:基础设施文件零业务风险,失败可独立 revert,不破坏 pytest/coverage baseline
- **不反转**:业务代码(`src/my_ai_employee/`)沿撞坑 #71 docs-only 边界
- **下次评审**:Day 2 收口时检查业务代码是否仍 0 改动

### 6.2 撞坑 #59 红线维持(本棒明确)

- **本脚本不读取真实凭据**:所有服务用 Stub 默认单例
- **不写 Keychain**:本棒不动 macOS Keychain
- **不发送邮件**:无 SMTP / OAuth 调用
- **下一次撞坑 #59 接触点**:Day 1 阶段 2(用户提供凭据后,Keychain 写入需用户逐项 OK)

### 6.3 撞坑 #60 沿用(本棒不触发)

- 不涉及 tag 操作
- v0.2.1 tag 仍维持(`71b4602` annotated,撞坑 #60 反转后状态)

---

## §7 验证清单(Day 1 阶段 1 全部完成)

- [x] `make install` ✅(uv sync OK,99 packages resolved)
- [x] `make hello` ✅(菜单栏 ASCII banner 输出)
- [x] `alembic upgrade head` ✅(head 16)
- [x] `make ci` 9 质量门 ✅(2611 passed / 88.95% / 238 files / 225 md)
- [x] `scripts/run_menu_bar.py` 新写 + ruff/mypy ✅
- [x] Makefile `menu-bar` target + help 文案 ✅
- [x] `ops/` 目录创建 + `ops/day1-baseline.md` ✅
- [ ] `make menu-bar` 实际弹菜单栏图标 ⏸️(阶段 2 验证,需要 .env + Keychain)
- [ ] TCC 授权引导 ⏸️(Day 2)

---

## §8 下一步(Day 1 阶段 2 + Day 2 启动)

### 8.1 Day 1 阶段 2(需用户输入)

**阻塞**:撞坑 #59 红线决策 + 真实凭据

需要的输入(任选一种):
- **A**:**用户已准备 LLM API Key + QQ 邮箱 + QQ 授权码** → 立刻执行 `.env` 真实填值 + Keychain 写入 + `make menu-bar` 验收
- **B**:**仅 LLM Key**(QQ 部分延后到 Day 3)→ 仅填 LLM Key,跳过 QQ 凭据
- **C**:**都不准备**(Day 1 阶段 1 已足够,Day 1 结束)→ 直接 commit + 等 Day 2 启动

### 8.2 Day 2 启动准备(沿用户原计划)

- 09:00-10:30 TCC 授权(系统设置 → 隐私与安全性 → 自动化 / 完全磁盘访问)
- 10:30-12:00 前台跑通 `uv run python scripts/run_menu_bar.py`
- 13:00-14:30 明确区分:`com.myaiemployee.agent.plist` 只管月报(已确认),与菜单栏无关
- 14:30-16:00 菜单栏常驻方式二选一:方案 A(手动 nohup)/ 方案 B(独立 plist)
- 16:00-17:30 验证 5 子模块:clipboard capture / expense 告警 / note confirm / outbox draft / badge polling
- 17:30-18:00 写 `ops/start-menubar.sh`(Day 7 一键包的组件之一)

---

## §9 维护者

**Mr-PRY** · 2026-07-01 Day 1 阶段 1 收口 · 撞坑 #71 决议 B(部分反转)· 撞坑 #59 红线维持 · 9 质量门 baseline 不变 · 业务代码 0 改动(Day 1)· 等用户输入触发 Day 1 阶段 2。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **沿用范本**:[[v0.2.55.2-path4-spike]] + [[v0.2.7.2-xoauth2-smtp-inmemory-spike]] · **下一棒**:Day 1 阶段 2(LLM Key + QQ 授权码 + Keychain 写入)。