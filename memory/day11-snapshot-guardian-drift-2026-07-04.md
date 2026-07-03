---
name: day11-snapshot-guardian-drift-2026-07-04
description: 撞坑 #50 第三层 — snapshot 守护 MD + pytest 联动漂移范本（Day 11 docs-only）
metadata:
  type: project
---

# 撞坑 #50 第三层 — snapshot 守护 MD + pytest 联动漂移范本(2026-07-04)

> **范围**:Day 11 docs-only 阶段(`docs/day11-*.md` 2 个新增)引发的 snapshot 校准链 247→248→249→250 沉淀
> **场景**:docs-only 阶段新增 MD 文件,触发 snapshot baseline 联动漂移的防御与同步范本
> **撞坑历史**:撞坑 #50 Day 10 P2 严格快照守护 · Day 11 第三层(本次新增)

---

## 撞坑 #50 演化历史

| 层 | Day | 严判内容 | 范本 |
|----|-----|---------|------|
| **第一层** | 6/24 | `tests/db/ FK 循环依赖 57 errors` 修复 | `tests/db/conftest.py` 隔离 |
| **第二层** | 6/24-6/25 | `mypy --check-untyped-defs` + `--disallow-untyped-defs` + `--strict` 三重锁死 | `pyproject.toml` + Makefile |
| **第三层(本次)** | 7/2-7/4 | docs-only 阶段新增 MD 触发 snapshot 校准 + pytest drift 联动漂移 | docs/day11-*.md 新增校准链 |

---

## 第三层现象详解

### 现象 1:MD lint 漂移(基础)

```bash
$ make lint
Linting: 251 file(s)  # ← 实际多了 1 MD
$ make check-snapshot
ERROR: MD lint drift: quality_snapshot claims 250 files, git ls-files '*.md' has 251
```

**根因**:`docs/day11-*.md` 新增未同步到 `quality_snapshot.py: lint` 字段 + 5 状态入口。

### 现象 2:pytest drift 级联(MD 漂移的连锁反应)

```bash
$ make check-snapshot
ERROR: pytest drift: quality_snapshot claims 2790 passed / 2 skipped,
       pytest --collect-only has 2792, expected 2794 (passed+skipped=2792 +
       baseline guardian failures=2)
```

**根因**:
1. `tests/test_quality_snapshot.py::test_check_quality_snapshot_script_exits_zero` 测试
   跑 `scripts/check_quality_snapshot.py`,期望 exit 0
2. 如果 `make check-snapshot` 因 MD drift 退出 1,该测试本身失败
3. 该测试失败计入 guardian_failures(=2)
4. guardian_failures 计入了 collected vs expected 的差值
5. **结果**:MD drift 导致 pytest drift 报告 → 双重 ERROR

**修复范本(7 步骤)**:

1. **更新 `src/my_ai_employee/quality_snapshot.py`**:`lint: 250 → 251 files 0 errors`
2. **更新 5 状态入口**(同时改):
   - `CLAUDE.md` 顶部状态行 L7, L16
   - `README.md` L7 顶部状态块
   - `SESSION-STATE.md` L4, L18, L33
   - `MODIFICATION-LOG.md` L116 质量基线行
   - `docs/v0.2-launch-plan.md` L264 当前实测基线行
3. **更新 closure 报告**(如新增 `reports/Day11-closure.md`):§2/§12 数字同步
4. **更新 runbook baseline**(如有):`docs/day11-notes-encryption-production-runbook.md` §1.5
5. **更新 memory**(如有):本次新增 `memory/day11-snapshot-guardian-drift-2026-07-04.md`
6. **重新 `make check-snapshot`**:确认 OK
7. **commit**:`fix(snapshot): MD lint N→N+1 校准 check-snapshot`

---

## 与第一层/第二层的关系

| 层 | 严判范围 | 与第三层的关系 |
|----|---------|---------------|
| 第一层(FK 循环)| `tests/db/` 测试隔离 | 单元层 · 不影响 snapshot |
| 第二层(mypy strict)| `pyproject.toml` + Makefile 锁死 | 配置层 · 影响测试而非 snapshot |
| **第三层(docs drift)** | snapshot + 5 状态入口联动 | **新增 docs 时 7 步同步** |

---

## 沉淀要点

### Why:Docs-only 阶段为什么容易触发第三层

1. **docs-only 不触发 pytest,但触发 MD lint 计数**
2. **MD lint 计数改动 → snapshot 守卫 ERROR → guardian tests 失败 → pytest drift 报告**
3. **整个机制是「自洽约束」**:任何 docs-only 改动必须 7 步同步,否则 guard 失败

### How to apply:7 步同步范本(任何 docs-only 阶段)

| 步骤 | 文件 | 强制 |
|------|------|------|
| 1 | `src/my_ai_employee/quality_snapshot.py` | 必 |
| 2 | `CLAUDE.md` 顶部 L7, L16 | 必 |
| 3 | `README.md` 顶部 L7 | 必 |
| 4 | `SESSION-STATE.md` L4, L18, L33 | 必 |
| 5 | `MODIFICATION-LOG.md` L116 | 必 |
| 6 | `docs/v0.2-launch-plan.md` L264 | 必 |
| 7 | `make check-snapshot` 验证 OK | 必 |

**违反任意步骤 → guardian 报 ERROR → commit 失败。**

### 沿用撞坑 #50 第一二层 + 三层

- ✅ Day 8+ 任何 docs-only 阶段:沿用 7 步范本
- ✅ Day 10 落地 P2 严格快照守护(`tests/test_quality_snapshot.py` 7 测试)
- ✅ Day 11 落地第三层:docs-only 阶段同时维护 MD + state entries(本次 250→251 实践)

---

**最后更新**:2026-07-04(Day 11 收官后 7 步同步实践)
**沿用**:撞坑 #50 三层防御机制守门
**维护者**:Mr-PRY