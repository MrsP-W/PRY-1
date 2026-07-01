# Day 6 — D 路径今天到此 · Day 7 留明天(2026-07-01)

> **类型**:7 天计划 Day 6 · 选项 D(状态收口 · 不启动 Day 7)
> **模式**:docs-only 状态收口 · 等用户明确 Day 7 候选 + 真实凭据授权
> **风险**:🟢 零(纯状态收口)
> **撞坑关联**:#71 沿用 · #59 红线维持 · 撞坑累计 83 类(本棒 0 新增)

---

## §1 用户决策(2026-07-01)

| 决策点 | 选择 | 含义 |
|--------|------|------|
| **Day 6 D 路径** | 今天到此 · Day 7 留明天 | A/B 等真实凭据,C 脚本已就位,D 状态收口 |
| **撞坑累计** | 83 类(本棒 0 新增 · Day 6 A/B 各登记 #82/#83) | 撞坑累计翻牌 |
| **Day 7 候选** | 待用户决策 | 真实 CSV 1 行真导 / Notes 真同步 / 撞坑 #31 mypy 13 errors / 撞坑 #59 outlook-gmail 反转候选 |

---

## §2 Day 6 当日累计 3 commits + 5 docs + 1 ops 脚本

```
9a5c3cc fix(finance): Day6 前月报收支口径 + 账单导入默认拒写           ← Day 6 前 P0/P1(用户已 commit)
d6a7136 fix(closure): Day 4 月报产物入库 + MD count 235→236(撞坑 #50 漂移防御)  ← Day 5 收口同步
1b0fc14 feat(closure): Day 5 Dashboard 只读驾驶舱 DASHBOARD_REAL_DB=1 hydrate 7/7  ← Day 5 主 commit
```

**本棒 Day 6 ABC 三路径收口**:`ops/start-digital-employee.sh` + `ops/day6-a-csv-real-launch.md` + `ops/day6-b-notes-real-launch.md` + `ops/day6-c-onestart-closure.md` + 本文件(共 4 个新 docs + 1 个新脚本)。

---

## §3 Day 6 解锁的能力矩阵

| 维度 | 现状 | Day 7 启动准备 |
|------|------|--------------|
| **真实账单导入** | 🟡 4 重门控上线 · `import_real_gate.py` 共用模块 | 等用户 CSV 路径 + 「OK 真导 1 行」|
| **真实 Notes 同步** | 🟡 NOTES_REAL_NETWORK 维持 UNSET · TCC 引导就位 | 等 Apple ID + TCC + 「OK 真同步 5 条」|
| **一键启动** | 🟢 `ops/start-digital-employee.sh` 已就位(290 行 · 5 子命令 + dry-run)| 用户首次 `start` 前须手动授权 TCC(撞坑 #81)|
| **撞坑累计** | **83 类**(撞坑 #82 账单门控 + #83 Notes 真同步)| — |

---

## §4 Day 7 候选(用户决策点)

| 选项 | 内容 | 风险 | 撞坑关联 |
|------|------|------|---------|
| **A. 真实 CSV 1 行真导** | A 路径 §3.1 命令范本真跑 | 🟡 中 | 撞坑 #82 4 重门控验证 |
| **B. Notes 真同步 5 条** | B 路径 §3.1 命令范本真跑 | 🟡 中 | 撞坑 #83 验证 + 撞坑 #81 TCC |
| **C. mypy tests 14 errors 修复** | ✅ 2026-07-01 已修复(撞坑 #31 · 7 文件 `[no-any-return]` · `cast(int/bool, ...)`) | 🟢 低 | 沿 v0.2.23 范本 |
| **D. outlook/gmail 真实凭据激活** | 撞坑 #59 反转候选 | 🟡 中 | 撞坑 #59 红线维持 · 用户明确反转才动 |
| **E. Day 7 留 Day 8+** | 全部沿用 · 维护当前状态 | 🟢 零 | — |

---

## §5 7 天计划总览(Day 1-6)

| Day | 选项 | 状态 | 关键产出 |
|-----|------|------|---------|
| **Day 1** | 基础设施落地 | ✅ | `scripts/run_menu_bar.py` + `ops/start-menubar.sh` 设计 |
| **Day 2** | 菜单栏后台常驻 + 撞坑 #81 | ✅ | `bash ops/start-menubar.sh start` PID=38516 + TCC 修复收口 |
| **Day 3** | C 路径 SMTP 真发 1 封 | ✅ | 1 封 SENT 成功(撞坑 #76/#78/#79 5 重门控)|
| **Day 4** | A 路径财务 + Notes faker | ✅ | 37 笔 transactions + D8 异常 + 月报(撞坑 #49/#53/#54)|
| **Day 5** | A 路径 Dashboard 只读 | ✅ | DASHBOARD_REAL_DB=1 + 7 hydrate 端点全绿 |
| **Day 6 前** | P0/P1 修复 | ✅ | commit `9a5c3cc`(月报口径 + 4 重门控 + coverage 统一) |
| **Day 6 ABCD** | A/B docs-only + C 真写脚本 + D 收口 | ✅(本棒)| `ops/start-digital-employee.sh` + 撞坑 #82/#83 登记 |
| **Day 7** | 候选 A/B/C/D/E(待用户决策) | ⏸️ | 等真实凭据 + 反转授权 |

---

## §6 撞坑累计翻牌(81 → 83)

| 撞坑号 | 状态 | 说明 | Day 登记 |
|--------|------|------|---------|
| **#82** | 🟢 docs-only(等真导时验证) | 账单导入 4 重门控默认拒写范本(`import_real_gate.py`)| Day 6 A |
| **#83** | 🟢 docs-only(等真同步时验证)| Apple Notes 真同步链路(NOTES_REAL_NETWORK + TCC) | Day 6 B |
| **#81** | 🟢 已修复 | ⌥⌘N TCC 修复(Day 2 3/3) | Day 2 |

---

## §7 业务代码改动

| 类别 | Day 1-6 累计 | 撞坑 |
|------|------------|------|
| **`src/` 业务代码** | 0 改动(撞坑 #71 沿用)| Day 1-6 全期 |
| **`scripts/` 基础设施** | 1 新文件(`run_menu_bar.py` 52 行 · Day 1)| Day 1 |
| **`scripts/` 业务辅助** | 1 新文件(`import_real_gate.py` 32 行 · Day 6 前 P0/P1)| Day 6 前 |
| **`scripts/` 业务改动** | `monthly_report.py` +48/-3 · `import_wechat.py` +27/- · `import_alipay.py` +26/- (Day 6 前)| Day 6 前 |
| **`ops/` 基础设施** | 4 文件(`start-menubar.sh` · `check-pitfall-81.sh` · `start-digital-employee.sh` + 启动文档)| Day 2 + Day 6 |
| **`tests/` 新测试** | +9(Day 6 前 P0/P1) | Day 6 前 |

**撞坑 #71 维持**:业务代码(src/)0 改动,仅 ops/scripts 基础设施文件新增。

---

## §8 9/9 质量门 baseline 维持

| 维度 | 数值 | 来源 |
|------|------|------|
| pytest | **2620 passed / 1 skipped** | Day 6 前 commit `9a5c3cc` +9 tests |
| coverage | **88.95%** | Day 6 前 commit `9a5c3cc` 统一口径(-0.02pp)|
| mypy | 0 errors / **238 files** | 撞坑 #31 宽松版(13 errors 已知技术债) |
| ruff check / format | 全绿 | — |
| alembic --sql | exit 0 | — |
| uv build | OK | — |
| MD lint | **236 files** 0 errors | Day 5 收口后 + 月报入库 |

---

## §9 维护者

**Mr-PRY** · 2026-07-01 Day 6 D 路径收口(Day 1-6 全部收口 · 撞坑累计 83 类 · 业务代码 0 改动 · 9/9 质量门 baseline 不变 · 等 Day 7 启动授权)。

**模型**:MiniMax-M3 · **最后更新**:2026-07-01 · **下一棒**:Day 7 候选(A 真实 CSV 1 行 / B Notes 真同步 / C mypy 13 errors / D outlook-gmail 反转 / E 留 Day 8+ · 用户逐项 OK)。

**7 天计划总评**:Day 1-6 全部收口 · 撞坑累计 83 类(撞坑 #81 已修复 · #82/#83 已登记待真触发验证)· **`v0.2.1` tag 已落地** · Phase A+B+C 全收 · 业务代码 0 改动 6 周 + 1 天(撞坑 #71 沿用)。