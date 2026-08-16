# 撞坑 #106 二修任务包(2026-07-28 needs_human 触发)

> **状态**:📋 任务包建立 · 未启动实施 · 等用户独立 worktree 授权
> **触发**:2026-07-28 needs_human 审查发现本轮 `commit 4726ebd` 修复不完整
> **建议路径**:独立 worktree 修复 + 补质量门覆盖 + 补 ruff scripts/ scope
> **沿用范本**:撞坑 #50 / #104 / #105 / #106 docs-only sync + 撞坑 #91 wrapper 独立 worktree 修复范本

---

## 1. 问题清单(needs_human 结论)

### 1.1 我本轮修过的(commit `4726ebd` 已落 main)

| 文件 | 行 | 改动 |
|------|-----|------|
| `scripts/check_quality_snapshot.py` | L16 + L97-110 | 加 `import sys` + `count_collected_tests` 子进程改用 `sys.executable -m pytest` |

### 1.2 **没修完的(needs_human 指出)**

| # | 文件 | 行 | 问题 | 影响 |
|---|------|-----|------|------|
| **A1** | `scripts/check_quality_snapshot.py` | **L180** | `count_baseline_guardian_failures` 仍用 `["uv", "run", "pytest", ...]` 子进程 | 干净 worktree uv 环境缺 pytest → **检查失败** |
| **A2** | `scripts/check_quality_snapshot.py` | **L214** | `count_live_pytest_outcomes` 仍用 `["uv", "run", "pytest", ...]` 子进程 | 同上 |
| **B1** | `scripts/check_quality_snapshot.py` | **L16 + L17** | 重复 `import sys`(我加 `import sys` 时未察觉已存在)| ruff / pyflakes 警告,无功能影响 |

### 1.3 构建配置缺口

| # | 文件 | 问题 | 影响 |
|---|------|------|------|
| **C1** | `Makefile` `make ruff` | 只扫 `src/` + `tests/`,**不扫 `scripts/`** | `scripts/check_quality_snapshot.py` 的重复 `import` / 未来 lint 问题不会被 ruff 检测 |

---

## 2. 修复要点(独立 worktree 路径)

### 2.1 推荐 worktree

```bash
git worktree add /tmp/my-ai-employee-106-fix-v2 \
    -b codex/pitfall-106-fix-v2 main
```

### 2.2 修复点 A1 + A2(子进程 2 处)

**A1 — `count_baseline_guardian_failures` (L180)**:

```python
# 旧:
result = subprocess.run(
    [
        "uv", "run", "pytest",
        str(_BASELINE_GUARDIAN_REL),
        "-q", "--no-cov", "--tb=no",
    ],
    cwd=root, capture_output=True, text=True, check=False, env=env,
)

# 新:
result = subprocess.run(
    [
        sys.executable, "-m", "pytest",
        str(_BASELINE_GUARDIAN_REL),
        "-q", "--no-cov", "--tb=no",
    ],
    cwd=root, capture_output=True, text=True, check=False, env=env,
)
```

**A2 — `count_live_pytest_outcomes` (L214)**:

```python
# 旧:
result = subprocess.run(
    [
        "uv", "run", "pytest",
        "-q", "--no-cov", "--tb=no",
    ],
    cwd=root, capture_output=True, text=True, check=False, env=env,
)

# 新:
result = subprocess.run(
    [
        sys.executable, "-m", "pytest",
        "-q", "--no-cov", "--tb=no",
    ],
    cwd=root, capture_output=True, text=True, check=False, env=env,
)
```

### 2.3 修复点 B1(重复 import)

**`scripts/check_quality_snapshot.py` L16-17**:

```python
# 旧:
import re
import subprocess
import sys   # ← 我加的(行 17)

# 新:
import re
import subprocess
import sys   # ← 保留唯一一处
```

(我加 `import sys` 时与原有 L16 的 `import sys` 冲突。需删除我加的那一行或原有一行。**先 grep 确认是同一 import,然后保留一处**。)

### 2.4 修复点 C1(`make ruff` scripts/ scope)

**Makefile 修改**:

```makefile
# 旧:
ruff:
<!-- markdownlint-disable MD010 -->
	uv run ruff check src/ tests/

# 新:
ruff:
	uv run ruff check src/ tests/ scripts/
```
<!-- markdownlint-enable MD010 -->

(确保 `make ruff` / `make ruff-fix` / `make ci` 都覆盖 scripts/。)

---

## 3. 质量门覆盖(沿 #106 一修范本)

### 3.1 必跑(干净 worktree 内)

```bash
cd /tmp/my-ai-employee-106-fix-v2

# 1. import sys 唯一性测试
grep -c "^import sys$" scripts/check_quality_snapshot.py  # 期望 = 1

# 2. 子进程全部用 sys.executable
grep -n '"uv"' scripts/check_quality_snapshot.py  # 期望 = 0
grep -n 'sys.executable' scripts/check_quality_snapshot.py  # 期望 = 3 (count_collected_tests + count_baseline_guardian_failures + count_live_pytest_outcomes)

# 3. clean worktree 全跑
uv run pytest tests/ -q --no-cov  # 期望 3175 passed / 1 skipped / 0 failed

# 4. check-snapshot
uv run python scripts/check_quality_snapshot.py  # 期望 exit 0

# 5. make ruff 覆盖 scripts/
make ruff  # 期望 0 errors

# 6. make ci 全过
make ci  # 期望 9/9 全绿
```

### 3.2 新增测试(回归 + 防漂移)

**测试位置**:`tests/scripts/test_check_quality_snapshot_pytest_subprocess.py`(新建)

```python
"""防 #106 修复回退 + 防 #106 二修遗漏."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_quality_snapshot.py"


def test_no_uv_run_in_subprocess_pytest_calls() -> None:
    """scripts/check_quality_snapshot.py 中不应有 subprocess.run([\"uv\", ...] 调 pytest.

    沿 撞坑 #106:干净 worktree 的 uv 环境缺 pytest,子进程需用 sys.executable.
    """
    content = SCRIPT.read_text(encoding="utf-8")
    # 允许 "uv run python ..." 这种 docs/header,但禁止在 subprocess.run 数组里
    uv_in_subprocess = re.findall(
        r'subprocess\.run\(\s*\[\s*"uv"', content
    )
    assert uv_in_subprocess == [], (
        f"发现 subprocess.run([\"uv\", ...]) 调用:"
        f"\n{uv_in_subprocess}"
        f"\n需改为 [sys.executable, '-m', ...]"
    )


def test_import_sys_appears_once() -> None:
    """scripts/check_quality_snapshot.py 中 import sys 必须唯一(防 B1 重复)."""
    content = SCRIPT.read_text(encoding="utf-8")
    count = content.count("^import sys$") + len(
        re.findall(r"^import sys$", content, re.MULTILINE)
    )
    assert count == 1, f"import sys 出现 {count} 次,期望 1"


def test_subprocess_uses_sys_executable_three_times() -> None:
    """sys.executable 必须在 3 处子进程调用中出现(count_collected_tests + count_baseline_guardian_failures + count_live_pytest_outcomes)."""
    content = SCRIPT.read_text(encoding="utf-8")
    count = content.count("sys.executable")
    assert count >= 3, f"sys.executable 出现 {count} 次,期望 ≥ 3"
```

### 3.3 Makefile ruff scope 测试

**新增测试**:`tests/scripts/test_makefile_ruff_scope.py`

```python
"""防 #106 二修 Makefile ruff scope 回退."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"


def test_makefile_ruff_includes_scripts_dir() -> None:
    """`make ruff` 必须覆盖 scripts/ 目录(沿 #106 二修 C1)."""
    content = MAKEFILE.read_text(encoding="utf-8")
    # 找 ruff 目标块
    assert "ruff check src/ tests/ scripts/" in content, (
        "make ruff 必须覆盖 scripts/ · 沿撞坑 #106 二修 C1"
    )
```

---

## 4. 提交与 PR 路径

### 4.1 Commit 策略

```bash
git add scripts/check_quality_snapshot.py \
        tests/scripts/test_check_quality_snapshot_pytest_subprocess.py \
        tests/scripts/test_makefile_ruff_scope.py \
        Makefile

git commit -m "fix(ops+tests): 撞坑 #106 二修 — 子进程 uv run pytest 全部清零 + 重复 import 修复 + Makefile ruff 覆盖 scripts/

撞坑 #106 二修触发 (needs_human 2026-07-28):
- scripts/check_quality_snapshot.py L180 子进程 uv run pytest → sys.executable -m pytest
- scripts/check_quality_snapshot.py L214 子进程 uv run pytest → sys.executable -m pytest
- scripts/check_quality_snapshot.py L16-L17 重复 import sys → 唯一
- Makefile ruff check 覆盖 scripts/

新增回归测试:
- tests/scripts/test_check_quality_snapshot_pytest_subprocess.py (3 tests)
- tests/scripts/test_makefile_ruff_scope.py (1 test)

干净 worktree 验证:
- pytest 3175 passed / 1 skipped / 0 failed
- check-snapshot exit 0
- make ruff 0 errors
- make ci 9/9 全绿

沿撞坑 #106 一修范本 + #50/#104/#105 docs-only sync"
```

### 4.2 PR 创建

```bash
git push origin codex/pitfall-106-fix-v2
gh pr create --base main --head codex/pitfall-106-fix-v2 \
    --title "fix(ops+tests): 撞坑 #106 二修 (3 子进程 + 重复 import + ruff scope)" \
    --body "沿用 PR #4 范本,详见 commit message"
```

### 4.3 Merge 时机

- 等 PR CI / 本地 `make ci` 全绿
- 等干净 worktree 全跑 3175/0 fail
- 等用户单独 `merge` 授权

---

## 5. 红线(本任务包不动)

- ❌ 不在主工作树直接修 — 必须在独立 worktree `/tmp/my-ai-employee-106-fix-v2`
- ❌ 不修其他文件(只动 `scripts/check_quality_snapshot.py` + `Makefile` + 新增 2 个 test)
- ❌ 不动 11 untracked(LaunchAgent / rollover / dontAsk watcher)
- ❌ 不动 18 worktree
- ❌ 不动 P3 epoch 文件
- ❌ 不替用户做 sudo
- ❌ 不 merge(等用户单独 `merge` 授权)

---

## 6. 关联

- **撞坑 #106 一修**:`commit 4726ebd`(`scripts/check_quality_snapshot.py:97` 子进程) — 已落 main 但**不完整**
- **撞坑 #105 范本**:docs-only commit 后必同步 baseline(本任务包也走 5件套 sync)
- **撞坑 #50 范本**:snapshot baseline 守护测试同步
- **撞坑 #91 范本**:独立 worktree 修复 launchd wrapper(本任务包沿用)
- **PR #4**(已 merge):本任务包可作为"撞坑 #106 二修"独立 PR

---

**等用户授权**:启动独立 worktree 修复 → PR #5 创建 → 用户 merge
