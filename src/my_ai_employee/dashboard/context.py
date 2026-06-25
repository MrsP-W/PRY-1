"""Dashboard 只读上下文 — 注入 menu_bar 服务 Stub(沿 P1 范本).

v0.2.53.7 opt-in 真实数据:
    - 默认全 Stub(沿 v0.2.53.6 行为不变)
    - 设 `DASHBOARD_REAL_DB=1` 时,`DashboardContext.default()` 尝试注入真实
      `OutboxDraftServiceImpl(OutboxStore(session_factory))`
    - 任何失败(Keychain 缺密码 / DB 不存在 / SQLCipher 错 / 网络错)静默降级 Stub,
      不阻塞 Dashboard 启动
"""

from __future__ import annotations

import os
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
    OutboxDraftServiceImpl,
    OutboxDraftServiceStub,
)

GitHeadResolver = Callable[[], str]
KeychainProbe = Callable[[str], bool]

# v0.2.53.7 opt-in 真实 DB env 门控
#   - 未设或 "0" / "false" / "no" → 默认全 Stub(沿 v0.2.53.6 行为)
#   - "1" / "true" / "yes" → 尝试注入 OutboxDraftServiceImpl(OutboxStore(...))
_DASHBOARD_REAL_DB_ENV = "DASHBOARD_REAL_DB"


@dataclass(frozen=True, slots=True)
class QualityGateSnapshot:
    """质量门只读快照(不跑 CI,沿菜单栏系统健康范本)."""

    pytest: str = "2300 passed / 1 skipped"
    coverage: str = "88.54%"
    mypy: str = "0 errors"
    lint: str = "155 files 0 errors"


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
        """默认上下文 — 默认全 Stub;`DASHBOARD_REAL_DB=1` 时 opt-in 真实 Outbox.

        边界(沿 v0.2.53.6 + v0.2.53.7):
            - 未设 env → 全 Stub(行为不变)
            - 设 env 但失败(Keychain 缺密码 / DB 不存在 / 错密码等)→ 静默降级 Stub
            - 设 env 且成功 → OutboxDraftServiceImpl(OutboxStore(session_factory))
              只读查询 pending_send + approved,不含 body
            - NoteConfirmService / ExpenseService 仍 Stub(v0.2.53.8 候选)
            - 不真发 SMTP / 不写 DB / 不移动 v0.1.0 tag / 不打 v0.2.x tag
        """
        ctx = cls()
        if _is_real_db_enabled():
            real_service = _try_build_real_outbox_drafts()
            if real_service is not None:
                ctx = ctx.with_outbox_drafts(real_service)
        return ctx

    def with_outbox_drafts(self, service: OutboxDraftService) -> DashboardContext:
        """返回替换 outbox_draft_service 的新 ctx(不可变更新)."""
        return DashboardContext(
            expense_service=self.expense_service,
            note_confirm_service=self.note_confirm_service,
            outbox_draft_service=service,
            version=self.version,
            quality_gates=self.quality_gates,
            git_head_resolver=self.git_head_resolver,
            keychain_probe=self.keychain_probe,
        )


def _is_real_db_enabled() -> bool:
    """`DASHBOARD_REAL_DB=1` opt-in 判定 — 仅识别 truthy 字面量,避免意外触发."""
    raw = os.environ.get(_DASHBOARD_REAL_DB_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _try_build_real_outbox_drafts() -> OutboxDraftService | None:
    """尝试构造真实 OutboxDraftServiceImpl;失败返回 None(降级 Stub).

    失败模式(全部静默降级):
        - ImportError:缺少依赖(理论上不会,沿现有依赖)
        - PermissionError / OSError:Keychain 不可访问或 DB 锁
        - FileNotFoundError:DB 文件不存在(首次未 init_schema)
        - sqlcipher3.DatabaseError:密码错
        - 其他 Exception:兜底降级
    """
    try:
        from sqlalchemy.orm import sessionmaker

        from my_ai_employee.core.db import Database
        from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine
        from my_ai_employee.db.outbox import OutboxStore
    except ImportError:
        return None
    try:
        with Database.open() as db:
            engine = make_sqlalchemy_engine(db)
        if engine is None:
            return None
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        store = OutboxStore(session_factory)
        return OutboxDraftServiceImpl(store)
    except Exception:  # noqa: BLE001 — 任何失败都降级 Stub,不阻塞 Dashboard
        return None


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
