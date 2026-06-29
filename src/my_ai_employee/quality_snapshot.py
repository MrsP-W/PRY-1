"""质量门只读快照 — Dashboard API 与菜单栏系统健康共用.

单一事实源,避免 `context.py` / `menu_bar/app.py` 硬编码漂移。
更新时机:每次质量门基线变更后同步此处(以 `make test` / `make coverage` / `make lint` 实测为准)。
docs-only 规则:不前进 pytest/coverage;新增 Markdown 后必须同步 MD lint 计数(与 `git ls-files '*.md'` 对齐 · `make lint` 仅扫 tracked 文件)。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QualityGateSnapshot:
    """质量门只读快照(不跑 CI,沿菜单栏系统健康范本)."""

    pytest: str = "2546 passed / 1 skipped"
    coverage: str = "88.81%"
    mypy: str = "0 errors"
    lint: str = "189 files 0 errors"


DEFAULT_QUALITY_GATES = QualityGateSnapshot()


def format_system_health_body(*, git_head: str) -> str:
    """菜单栏「系统健康」弹窗正文."""
    qg = DEFAULT_QUALITY_GATES
    return (
        f"pytest: {qg.pytest}\n"
        f"coverage: {qg.coverage}\n"
        f"mypy --strict: {qg.mypy}\n"
        f"MD lint: {qg.lint}\n"
        "ruff + format: 全绿\n"
        f"HEAD: {git_head}\n"
        "SMTP 真实发送: 未解锁(需 Keychain + SMTP_REAL_NETWORK)"
    )


__all__ = [
    "DEFAULT_QUALITY_GATES",
    "QualityGateSnapshot",
    "format_system_health_body",
]
