"""Dashboard 只读上下文 — 注入 menu_bar 服务 Stub(沿 P1 范本)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from my_ai_employee import __version__
from my_ai_employee.menu_bar.expense_service import ExpenseService, ExpenseServiceStub
from my_ai_employee.menu_bar.note_confirm_service import (
    NoteConfirmService,
    NoteConfirmServiceStub,
)
from my_ai_employee.menu_bar.outbox_draft_service import (
    OutboxDraftService,
    OutboxDraftServiceStub,
)

GitHeadResolver = Callable[[], str]
KeychainProbe = Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class QualityGateSnapshot:
    """质量门只读快照(不跑 CI,沿菜单栏系统健康范本)."""

    pytest: str = "2278 passed / 1 skipped"
    coverage: str = "88.68%"
    mypy: str = "0 errors"
    lint: str = "150 files 0 errors"


@dataclass(slots=True)
class DashboardContext:
    """Dashboard API 依赖注入容器."""

    expense_service: ExpenseService = field(default_factory=ExpenseServiceStub.get_default_stub)
    note_confirm_service: NoteConfirmService = field(
        default_factory=NoteConfirmServiceStub.get_default_stub
    )
    outbox_draft_service: OutboxDraftService = field(
        default_factory=OutboxDraftServiceStub.get_default_stub
    )
    version: str = __version__
    quality_gates: QualityGateSnapshot = field(default_factory=QualityGateSnapshot)
    git_head_resolver: GitHeadResolver = field(default=lambda: _default_git_head())
    keychain_probe: KeychainProbe = field(default=lambda s: _default_keychain_probe(s))

    @classmethod
    def default(cls) -> DashboardContext:
        return cls()


def _default_git_head() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _default_keychain_probe(service: str) -> bool:
    """Keychain 项是否存在(不读密码,不用 -w)."""
    import sys

    if sys.platform != "darwin":
        return False
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def safe_count(getter: Callable[[], int]) -> int:
    """单项计数静默降级 → 0."""
    try:
        return int(getter())
    except Exception:  # noqa: BLE001 — API 层不崩
        return 0


def safe_list(getter: Callable[[], list[Any]]) -> list[Any]:
    """列表查询静默降级 → []."""
    try:
        result = getter()
        return list(result) if isinstance(result, list) else []
    except Exception:  # noqa: BLE001 — API 层不崩
        return []


def parse_limit(raw: str | None, *, default: int = 10, maximum: int = 100) -> int:
    """解析 ?limit= 查询参数(严判范围)."""
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < 1:
        return 1
    if value > maximum:
        return maximum
    return value
