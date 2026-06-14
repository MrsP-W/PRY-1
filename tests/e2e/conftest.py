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

import pytest

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== 临时 DB + Keychain monkeypatch 范本(沿 spike_outbox_100.py)=====

_FAKE_KEYCHAIN: dict[tuple[str, str], str] = {}


def _install_fake_keychain() -> None:
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

    # 透传原 keychain 行为(keychain 模块动态添加 .get/.set 属性,需 attr-defined 严判)
    keychain.get = fake_get  # type: ignore[attr-defined]
    keychain.set = fake_set  # type: ignore[attr-defined]


@pytest.fixture
def fake_keychain(monkeypatch) -> Iterator[None]:
    """装 fake keychain(逐 test 隔离)."""
    _FAKE_KEYCHAIN.clear()
    _install_fake_keychain()
    yield


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """临时 SQLite DB 路径(逐 test 隔离)."""
    db_file = tmp_path / "e2e_v0.1.db"
    return db_file


@pytest.fixture
def session_factory(temp_db_path: Path, fake_keychain):
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
def smtp_inmemory():
    """InMemorySmtpTransport 实例(默认 e2e 走模拟)."""
    from my_ai_employee.connectors.smtp import InMemorySmtpTransport

    return InMemorySmtpTransport()


# ===== Env 门控(沿 D5.6.5 4 重防误发)=====


def pytest_collection_modifyitems(config, items):
    """默认 skip S5(需真实 SMTP)+ S6-S9(待 D6/D7/D9/D10 落地)."""
    skip_real = pytest.mark.skip(
        reason="S5 真实 SMTP 需 SMTP_REAL_NETWORK=1 env + 沿 D5.6.5 4 重防误发参数"
    )
    skip_s6 = pytest.mark.skip(reason="S6 微信/支付宝 CSV 导入 — 等 D6/D7 落地")
    skip_s7 = pytest.mark.skip(reason="S7 ⌥⌘N 剪贴板 → Notes — 等 D9 落地")
    skip_s8 = pytest.mark.skip(reason="S8 每月 1 号 09:00 月报 — 等 D10 落地")
    skip_s9 = pytest.mark.skip(reason="S9 launchd 重启自愈 — 等 D10 落地")

    for item in items:
        # S5:仅当 SMTP_REAL_NETWORK != "1" 时 skip
        if "s5_real_smtp" in item.nodeid:
            if os.environ.get("SMTP_REAL_NETWORK") != "1":
                item.add_marker(skip_real)
        # S6-S9:始终 skip(等 D6/D7/D9/D10 落地后去除 skip)
        elif "s6_finance" in item.nodeid:
            item.add_marker(skip_s6)
        elif "s7_clipboard_notes" in item.nodeid:
            item.add_marker(skip_s7)
        elif "s8_monthly_report" in item.nodeid:
            item.add_marker(skip_s8)
        elif "s9_launchd_recovery" in item.nodeid:
            item.add_marker(skip_s9)
