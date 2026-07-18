"""v0.1 端到端 9 场景共享 fixture.

沿 D4.8.11 spike_outbox_100.py + D5.6.1 spike_send_100.py 范本:
    - 临时 SQLite + Keychain monkeypatch(不污染真实 ~/Library)
    - InMemorySmtpTransport 模拟(默认不走真实 SMTP)
    - 共享 Database sessionmaker

D6.0 范围(2026-06-14 启动):
    - 4 个核心 fixture(临时 DB / session_factory / keychain monkeypatch / SmtpLib 注入)
    - 1 个 env 门控 fixture(SMTP_REAL_NETWORK 严判)
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== 临时 DB + Keychain monkeypatch 范本(沿 spike_outbox_100.py)=====

_FAKE_KEYCHAIN: dict[tuple[str, str], str] = {}
_S5_CLI_CONFIRM_ENV = "MYAI_EMPLOYEE_S5_CLI_CONFIRMED"
_S5_CLI_CONFIRM_VALUE = "1"


def _install_fake_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    """in-memory dict 模拟 Keychain(e2e 不污染真实凭证)."""
    from my_ai_employee.core import keychain

    def fake_get(*, service: str, account: str) -> keychain.KeychainResult:
        value = _FAKE_KEYCHAIN.get((service, account))
        if value is None:
            return keychain.KeychainResult(ok=False, value=None)
        return keychain.KeychainResult(ok=True, value=value)

    def fake_set(*, service: str, account: str, value: str) -> keychain.KeychainResult:
        _FAKE_KEYCHAIN[(service, account)] = value
        return keychain.KeychainResult(ok=True, value=value)

    # get/set 是 e2e 专用的动态兼容接口；必须随 fixture 自动恢复，
    # 以免同一 pytest 进程内的后续用例读取到 fake hook。
    keychain_module: Any = keychain
    monkeypatch.setattr(keychain_module, "get", fake_get, raising=False)
    monkeypatch.setattr(keychain_module, "set", fake_set, raising=False)


@pytest.fixture
def fake_keychain(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """装 fake keychain(逐 test 隔离)."""
    _FAKE_KEYCHAIN.clear()
    _install_fake_keychain(monkeypatch)
    yield


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """临时 SQLite DB 路径(逐 test 隔离)."""
    db_file = tmp_path / "e2e_v0.1.db"
    return db_file


@pytest.fixture
def session_factory(temp_db_path: Path, fake_keychain: Any) -> Any:
    """构造 SQLAlchemy sessionmaker,跑 0001-0006 migration.

    D6.0 e2e 决策:用明文 sqlite + SQLAlchemy create_engine(不调 SQLCipher),
    理由:e2e 测业务流程,不需要测加密层。Base.metadata.create_all 应用 ORM schema。

    注意:Event / OutboxEntry 分别在 events.models / core.outbox 注册到 Base.metadata,
    需要显式 import 才能让 create_all 稳定建 events/outbox 表。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # 显式注册跨模块 ORM 表,避免依赖其他测试的 import 顺序。
    import my_ai_employee.core.outbox  # noqa: F401
    import my_ai_employee.db.notes  # noqa: F401  # 触发 Note 10 列注册到 Base.metadata(S7 e2e 用)
    import my_ai_employee.db.transactions  # noqa: F401  # 触发 Transaction 16 列注册到 Base.metadata(S6.1/S6.2/S6.3 e2e 用)
    import my_ai_employee.events.models  # noqa: F401
    from my_ai_employee.core.models import Base

    # 明文 sqlite(测试不加密,e2e 不测 SQLCipher 加密层)
    engine = create_engine(
        f"sqlite:///{temp_db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def smtp_inmemory() -> Any:
    """InMemorySmtpTransport 实例(默认 e2e 走模拟)."""
    from my_ai_employee.connectors.smtp import InMemorySmtpTransport

    return InMemorySmtpTransport()


# ===== Env 门控(沿 D5.6.5 4 重防误发)=====


def pytest_collection_modifyitems(config: Any, items: Any) -> Any:
    """默认 skip S5(需真实 SMTP);S6-S9 已实化(D6+D7+D9+D10 全部落地).

    S6 已实化(S6.1+S6.2+S6.3 真实断言在 test_v0_1_s6_finance.py):
        - 微信/支付宝 InMemory 100 笔导入
        - 跨源去重(L2 needs_confirm + candidate_match_id)
        - 菜单栏支出总额(沿 core.expense_aggregate 聚合)

    S7 已实化(S7.1+S7.2 真实断言在 test_v0_1_s7_clipboard_notes.py):
        - 剪贴板 → NoteStore.insert → NoteStructurerService.structure_and_emit
        - sync_notes.py spike --n 30 subprocess 真跑断言

    S8 已实化(S8.1-S8.3 真实断言在 test_v0_1_s8_monthly_report.py,D10.4 启动):
        - monthly_report.py generate subprocess 真跑(2026-06 或上月)
        - 审计员通知频率 ≤ 1 次/月 契约
        - 月报模板 9 段 10 占位符 验证

    S9 已实化(S9.1-S9.6 真实断言在 test_v0_1_s9_launchd_recovery.py,D10.4 启动):
        - plist 部署结构 + Label + StartCalendarInterval(1 号 09:00)
        - install.sh ~/bin/ 部署 + 5 源验证
        - uninstall.sh 卸载 plist + --purge-bin
        - 管家 24h 在岗 + D5.5 SLA/Heartbeat 联动
        - shell -n 语法验证(install.sh + uninstall.sh)
    """
    skip_real = pytest.mark.skip(
        reason="S5 真实 SMTP 未设置 SMTP_REAL_NETWORK=1，默认不执行",
    )

    for item in items:
        # S5:未显式开网络才 skip；已开网络但未获 CLI 确认时，测试体必须 fail-closed，
        # 不能以 pytest 的 0 退出码伪装为成功。
        if "s5_real_smtp" in item.nodeid and os.environ.get("SMTP_REAL_NETWORK") != "1":
            item.add_marker(skip_real)
        # S8-S9:已实化(D10.4 commit 即将落),不再 skip
