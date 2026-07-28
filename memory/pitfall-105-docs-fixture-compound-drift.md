## 撞坑 #105 docs-only + fixture 复合漂移(2026-07-27)

**用户纠错背景**：D6.10.1 评测样本 4→15（+11 fixture JSON）交付后，与 撞坑 #104 docs-only 留下的 MD 漂移叠加，形成**双层基线漂移**。

### 症状与诊断

1. **第 1 层漂移(MD 漂移)** — 撞坑 #104 已沉淀：`make test` 暴露 `test_tracked_md_count_matches_snapshot_lint` RED + check-snapshot state-entries 红
2. **第 2 层漂移(pytest 基线)** — 11 fixture 加 11 contract test + 上游/下游影响 → `passed` 累进 3176 → 3177 → 3178
3. **复合漂移** — 两个基线同时漂移，需**单原子 update** `quality_snapshot.py` + 5件套 11 处同步

### 抢修路径(沿 撞坑 #104 范本 + 额外 4 发现)

#### 1. baseline 单一事实源同步

```python
# src/my_ai_employee/quality_snapshot.py
@pytesttest: str = "3178 passed / 1 skipped"  # 实际累进值
coverage: str = "90.26%"
lint: str = "301 files 0 errors"  # fixture 不增 MD
mypy_files: str = "292 files"
```

#### 2. 5件套 11 处同步(全 grep 验证)

```
CLAUDE.md L9 + L18
README.md L9
SESSION-STATE.md L6 + L20 + L35  ← 踩坑:见 #3
MODIFICATION-LOG.md L118
docs/v0.2-launch-plan.md L264
```

#### 3. Replace_all 不跨 format 变体 ← 关键新发现

**症状**:首次 `Edit replace_all=true` 用 `**3173 passed / 1 skipped** / **90.26%**` → 11 处命中 9 处
**遗漏 2 处**:
- `SESSION-STATE.md L20` 格式 `**3173 passed / 1 skipped** / **90.26%**` ✓ 命中
- `SESSION-STATE.md L35` 格式 `**3173 passed / 1 skipped** · **90.26%**` ✗ 漏(分隔符是 `·` 不是 `/`)

**修法**:逐行扫 grep 确认 `3173` 残留,逐行 Edit

#### 4. ruff format 也会 WIP test 触发

**症状**:`make ci` 暴露 `Would reformat: tests/scripts/test_p3_rollover_epoch.py`
**根因**:之前 WIP 范本未 format,ci 检出后 fail
**修法**:`uv run ruff format tests/scripts/test_p3_rollover_epoch.py` → 1 file reformatted → 重跑 `make ci`

#### 5. check-snapshot 一票否决

- 漂移未修复 → `make check-snapshot` ERROR exit 1
- 漂移修复 → `make ci` 9 门全绿 + check-snapshot OK

### 范本(docs-only + 测试增量 复合收口 5 步)

```
Step 1: 跑 `make ci` 暴露所有门 RED(预期 baseline + lint + 5件套)
Step 2: grep "3173" 找 5件套残留 → 逐行 Edit
Step 3: lint 报 WIP test → ruff format 修复
Step 4: `make check-snapshot` 一票验证 OK
Step 5: `make ci` 9 门全绿 → single commit + push 授权
```

### Why

docs-only + tests-only 复合时(如 D6.10.1 扩评测样本),两个基线同时漂移,需**单原子 commit** 收口,避免分拆导致状态入口反复不同步。

### How to apply

- 任何"docs-only + tests-only" 复合 D-step(扩 fixture / 加 reference doc):先跑 `make ci` 暴露,再单原子 commit
- 5件套同步必跑 grep 验证,Replace_all 不保证 100% 命中(format 变体)
- ruff format 失败也是 ci 阻断,不能跳过
- 撞坑 #105 commit 信息必须说明:**同步 5件套 + baseline + 11 fixture + pitfall-105 沉淀**

### 关联

- [[pitfall-104-docs-only-md-drift]] 撞坑 #104 docs-only 单层漂移(本坑是其 + tests 复合版)
- [[pitfall-87-snapshot-self-referential-drift]] 撞坑 #87 自我引用基线
- [[pitfall-50 第三层 MD+pytest 联动漂移]] 撞坑 #50 docs-only 阶段 7 步同步范本
- [[checkpoint-2026-07-27-pitfall-104-quickfix]] 撞坑 #104 quickfix 收口
- [[checkpoint-2026-07-27-p3-epoch-governance]] P3 epoch 治理
