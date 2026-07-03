# Day 12 — 8/1 release tag 预热 preflight checklist (docs-only · 2026-07-03)

> **状态**:📘 docs-only 预热 · **8/1 当天不打 tag**(沿 7/1 复盘决议 #25 + `docs/v0.2.59-8-1-tag-evaluation-2026-08-01.md`)
> **节点 2 锚定**(2026-07-20):8/1 preflight §1 baseline 校准日,沿 7/16 weekly #3 baseline 重验(2791 / 89.09% / 256 MD / 248 mypy)· 9/9 项实质满足沿用 · 撞坑累计 84 类沿用 · docs-only 不前进 pytest/coverage(撞坑 #50 第三/四层沿用)
> **承接**:Day 11 companion 8/1 readiness + Day 12 周度抽测全绿 + push `4bdf3a3`
> **当前基线(2026-07-03 校准)**:**2791 passed / 1 skipped / 89.09% / 256 MD / 248 mypy**(沿 7/3 校准 254→256,撞坑 #50 第三/四层沿用)

---

## 1. 9 项前置条件刷新(当前实测)

| # | 前置条件 | 当前状态 | 8/1 评估 |
|---|----------|---------|---------|
| 1 | QQ SMTP 真实送达 | ✅ D5.6.5 + v0.2.55.5 sent=10 | 沿用 |
| 2 | outlook/gmail Keychain | ⏭️ 用户豁免(QQ-only) | 不阻塞 |
| 3 | W3 真账单 spike | ✅ v0.2.36 spike-49 | 沿用 |
| 4 | v0.2.53.x UI 收口 | ✅ v0.2.53.1-58 + Day 9 companion 只读 | 沿用 |
| 5 | 撞坑 #50 snapshot 防御 | ✅ 256 MD · check-snapshot 全绿 | 沿用 |
| 6 | ApprovalGate dry-run | ✅ Day 8 decide + 1-click UI | 沿用 |
| 7 | 撞坑累计 | **84 类**(Day 10-12 无业务新增) | 沿用 |
| 8 | Path 4 设计稿 + 5 门 | ✅ v0.2.53.53 v2 + Day 11 readiness | 实施留 8/1 后 |
| 9 | outlook/gmail SMTP spike | ⏭️ 用户豁免 | 不阻塞 |

**结论**:9/9 项实质满足(QQ-only 口径) · **仍建议选项 B 继续延后打 tag**。

---

## 2. 8/1 决策矩阵(预热版)

| 选项 | 8/1 预热评估 | 触发条件 |
|------|-------------|---------|
| **A 打 `v0.2.1` tag** | ❌ 不建议 | Path4 实写未启用 + 用户未授权 |
| **B 继续延后** | ✅ **推荐** | 沿 7/1 决议 #25 · `v0.1.0` 不动 |
| **C 打 `v0.2.1-rc1`** | 🟡 候选 | 8/1 后用户明确授权 |

---

## 3. 预热时间线(7/20–8/1)

| 日期 | 动作 | 产出 |
|------|------|------|
| **7/9** | 周度抽测第 2 轮 | `ops/day12-weekly-health-2026-07-09.md` ✅ |
| **7/20** | 重读 v0.2.59 评估矩阵 | 本 checklist §1 复核 |
| **7/25** | A3 readiness 第 1 次刷新 | 沿 `docs/v0.2.58-a3-readiness-2026-07-25.md` 范本 |
| **7/31** | companion 5 门 + 30 tests 终检 | 沿 `docs/day11-companion-write-8-1-readiness.md` §3 |
| **8/1** | tag 决策日(docs-only) | 更新 `docs/v0.2.59` 或新建 8/1 收官条目 · **默认不打 tag** |

---

## 4. 8/1 前每周抽测命令(维持期)

```bash
make check-snapshot
uv run pytest tests/dashboard/test_companion_readonly.py -q --no-cov
uv run python scripts/spike_day10_notes_encryption_dryrun.py
```

期望:check-snapshot OK · 30 passed · spike exit 0。

---

## 5. 关联文档

- `docs/v0.2.59-8-1-tag-evaluation-2026-08-01.md` — 历史 8/1 评估范本
- `docs/day11-companion-write-8-1-readiness.md` — companion 8 端点 + 5 门
- `docs/day11-notes-encryption-production-runbook.md` — Notes 生产启用前 runbook
- `docs/v0.2.53.53-path4-launch-checklist-2026-06-30.md` — Path4 5 门 v2

---

## 6. 红线(8/1 前全程)

- ❌ 不写 `ENABLE_PATH_4_WRITE=1` / `ENABLE_NOTES_ENCRYPTION=1` 到 shell profile
- ❌ 不移动 `v0.1.0` / `v0.2.1-rc1` / `v0.2.1` tag
- ❌ 不跑 90 封 SMTP · 不配置 Outlook/Gmail
- ❌ 8/1 前不实施 Path4 实写

---

**最后更新**:2026-07-03 · 预热启动(原规划 7/20,提前落地)
**维护者**:Mr-PRY
