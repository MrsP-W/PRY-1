"""D2.7 — IMAP 适配器单元测试（mock，不开 socket）。

覆盖（[docs/week1-mvp.md §D2.7 验收：覆盖率 ≥ 70%]）：

    - 健康检查成功 / 失败
    - safe_fetch 成功 / 失败隔离 / 熔断开启
    - envelope → dict 转换
    - Keychain 凭证缺失 → PermissionError
    - 登录失败 → ConnectionError
    - logout 调用
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

# 让 tests/ 目录能 import 兄弟包
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.connectors.base import (  # noqa: E402
    CIRCUIT_BREAKER_COOLDOWN,
    CIRCUIT_BREAKER_THRESHOLD,
)
from my_ai_employee.connectors.imap import IMAPConnector  # noqa: E402
from my_ai_employee.core import keychain  # noqa: E402

from .mock_imap import MockIMAPClient, install_mock, make_envelope  # noqa: E402

# ===== Fixtures =====


@pytest.fixture
def mock_client() -> MockIMAPClient:
    """默认 mock：登录成功、search 空。"""
    return MockIMAPClient()


@pytest.fixture
def installed_connector(monkeypatch: Any, mock_client: Any) -> IMAPConnector:
    """构造 IMAPConnector 并把 MockIMAPClient 注入。"""
    conn = IMAPConnector(provider="qq", email="test@qq.com")
    install_mock(monkeypatch, conn, mock_client)
    # 预填 Keychain（绕过真实 keychain 读）
    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=True, value="mock-auth-code"),
    )
    return conn


# ===== IMAPConnector 构造 =====


def test_connector_source_name_qq() -> None:
    """QQ 适配器 source_name = "qq"。"""
    conn = IMAPConnector(provider="qq", email="you@qq.com")
    assert conn.source_name == "qq"


def test_connector_unknown_provider_raises() -> None:
    """未知 provider 抛 ValueError。"""
    with pytest.raises(ValueError, match="未知 provider"):
        IMAPConnector(provider="unknown", email="x@x.com")  # type: ignore[arg-type]


def test_connector_outlook_raises_not_implemented() -> None:
    """Outlook provider 抛 NotImplementedError（D2 阶段白名单）。"""
    with pytest.raises(NotImplementedError, match="outlook"):
        IMAPConnector(provider="outlook", email="x@outlook.com")


def test_connector_gmail_raises_not_implemented() -> None:
    """Gmail provider 抛 NotImplementedError（D2 阶段白名单）。"""
    with pytest.raises(NotImplementedError, match="gmail"):
        IMAPConnector(provider="gmail", email="x@gmail.com")


# ===== 健康检查 =====


def test_healthcheck_success(installed_connector: IMAPConnector) -> None:
    """健康检查成功：latency > 0，ok=True。"""
    status = asyncio.run(installed_connector.healthcheck())
    assert status.ok is True
    assert status.latency_ms > 0
    assert status.error is None
    assert status.circuit_open is False


def test_healthcheck_auth_failure(monkeypatch: Any) -> None:
    """鉴权失败：healthcheck 返回 ok=False。"""
    mock = MockIMAPClient()
    mock.login_should_fail = True
    conn = IMAPConnector(provider="qq", email="test@qq.com")
    install_mock(monkeypatch, conn, mock)
    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=True, value="wrong"),
    )
    status = asyncio.run(conn.healthcheck())
    assert status.ok is False
    # mypy 类型守卫：error 是 Optional，必须先断言非 None 再做子串检查
    assert status.error is not None
    assert "登录" in status.error or "login" in status.error.lower()


def test_healthcheck_no_credential(monkeypatch: Any) -> None:
    """Keychain 缺凭证：healthcheck 返回 ok=False。"""
    conn = IMAPConnector(provider="qq", email="test@qq.com")
    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=False, error="not found"),
    )
    status = asyncio.run(conn.healthcheck())
    assert status.ok is False
    # mypy 类型守卫：error 是 Optional，必须先断言非 None 再做子串检查
    assert status.error is not None
    assert "Keychain" in status.error


def test_healthcheck_triggers_circuit_breaker(monkeypatch: Any) -> None:
    """healthcheck 失败也会进入熔断计数（P1-2 review 修复）。

    连续 3 次失败 → 熔断开启。
    """
    mock = MockIMAPClient()
    mock.login_should_fail = True
    conn = IMAPConnector(provider="qq", email="test@qq.com")
    install_mock(monkeypatch, conn, mock)
    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=True, value="wrong"),
    )

    for i in range(CIRCUIT_BREAKER_THRESHOLD):
        status = asyncio.run(conn.healthcheck())
        assert status.ok is False, f"第 {i + 1} 次 healthcheck 应失败"

    # 第 3 次失败后，熔断应已开启
    assert conn.circuit_state["is_open"] is True
    assert conn.circuit_state["consecutive_failures"] == CIRCUIT_BREAKER_THRESHOLD


def test_healthcheck_closes_connection(
    installed_connector: IMAPConnector, mock_client: MockIMAPClient
) -> None:
    """healthcheck 成功后 close 连接（避免多次调用累积 IMAP 连接）。"""
    asyncio.run(installed_connector.healthcheck())
    # 无论 healthcheck 成功/失败，close 都会被调用
    assert mock_client.logout_called is True
    # 二次 healthcheck 应能再次连接（验证连接确实被释放）
    mock_client.logout_called = False
    status2 = asyncio.run(installed_connector.healthcheck())
    assert status2.ok is True
    assert mock_client.logout_called is True


def test_connect_calls_select_folder_inbox(
    installed_connector: IMAPConnector, mock_client: MockIMAPClient
) -> None:
    """登录后必须 select_folder('INBOX', readonly=True)（P0-1 review 修复）。"""
    asyncio.run(installed_connector.connect())
    assert mock_client.select_folder_calls == [("INBOX", True)]


# ===== fetch + safe_fetch =====


def test_fetch_no_new_emails(installed_connector: IMAPConnector) -> None:
    """search 返回空：fetch 返回空 list。"""
    since = datetime.now(UTC) - timedelta(days=7)
    result = asyncio.run(installed_connector.fetch(since))
    assert result == []


def test_fetch_returns_envelope_dicts(
    installed_connector: IMAPConnector, mock_client: MockIMAPClient
) -> None:
    """search 返回 2 个 UID，fetch 返回 2 个 envelope dict。"""
    now = datetime.now(UTC)
    mock_client.search_uids = [1, 2]
    mock_client.fetch_data = {
        **make_envelope(1, subject="First", sender="a@x.com", received_at=now),
        **make_envelope(
            2, subject="Second", sender="b@x.com", received_at=now - timedelta(hours=1)
        ),
    }
    since = datetime.now(UTC) - timedelta(days=7)
    result = asyncio.run(installed_connector.fetch(since))
    assert len(result) == 2
    # source 字段
    assert all(e["source"] == "qq" for e in result)
    # UID 字段
    uids = sorted(e["uid"] for e in result)
    assert uids == [1, 2]
    # subject 解码
    subjects = {e["subject"] for e in result}
    assert subjects == {"First", "Second"}


def test_safe_fetch_isolates_failure(monkeypatch: Any) -> None:
    """fetch 抛异常 → safe_fetch 返回空 list，不传染。"""
    mock = MockIMAPClient()
    conn = IMAPConnector(provider="qq", email="test@qq.com")
    install_mock(monkeypatch, conn, mock)
    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=True, value="x"),
    )

    # 让 search 抛错
    def boom(_criteria: Any) -> Any:
        raise ConnectionError("Mock: network down")

    monkeypatch.setattr(mock, "search", boom)

    since = datetime.now(UTC) - timedelta(days=1)
    result = asyncio.run(conn.safe_fetch(since))
    assert result == []
    # 熔断计数 +1
    assert conn.circuit_state["consecutive_failures"] == 1


def test_safe_fetch_circuit_breaker_opens(monkeypatch: Any) -> None:
    """连续失败 3 次 → 熔断开启。"""
    mock = MockIMAPClient()
    conn = IMAPConnector(provider="qq", email="test@qq.com")
    install_mock(monkeypatch, conn, mock)
    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=True, value="x"),
    )
    monkeypatch.setattr(mock, "search", lambda _c: (_ for _ in ()).throw(ConnectionError("boom")))

    since = datetime.now(UTC) - timedelta(days=1)
    for _ in range(CIRCUIT_BREAKER_THRESHOLD):
        asyncio.run(conn.safe_fetch(since))

    state = conn.circuit_state
    assert state["consecutive_failures"] == CIRCUIT_BREAKER_THRESHOLD
    assert state["is_open"] is True


def test_safe_fetch_circuit_skips_when_open(monkeypatch: Any) -> None:
    """熔断开启后 → 跳过 fetch（不调用底层）。"""
    mock = MockIMAPClient()
    conn = IMAPConnector(provider="qq", email="test@qq.com")
    install_mock(monkeypatch, conn, mock)
    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=True, value="x"),
    )

    # 强制开启熔断（不真跑失败 3 次）
    conn._circuit.consecutive_failures = CIRCUIT_BREAKER_THRESHOLD
    conn._circuit.open_until = 9999999999.0  # 很久以后才到期

    called = {"search": 0}

    def track(_criteria: Any) -> Any:
        called["search"] += 1
        return []

    monkeypatch.setattr(mock, "search", track)

    since = datetime.now(UTC) - timedelta(days=1)
    result = asyncio.run(conn.safe_fetch(since))
    assert result == []
    assert called["search"] == 0  # 没调用 search


def test_safe_fetch_success_resets_counter(
    installed_connector: IMAPConnector, mock_client: MockIMAPClient
) -> None:
    """成功 fetch 重置失败计数。"""
    installed_connector._circuit.consecutive_failures = 2  # 模拟之前失败过
    installed_connector._client = mock_client  # 已连上

    since = datetime.now(UTC) - timedelta(days=1)
    result = asyncio.run(installed_connector.safe_fetch(since))
    assert result == []
    assert installed_connector.circuit_state["consecutive_failures"] == 0


# ===== close / logout =====


def test_close_calls_logout(
    installed_connector: IMAPConnector, mock_client: MockIMAPClient
) -> None:
    """close() 调用底层 logout。"""
    installed_connector._client = mock_client
    asyncio.run(installed_connector.close())
    assert mock_client.logout_called is True
    assert installed_connector._client is None


def test_close_handles_already_disconnected(installed_connector: IMAPConnector) -> None:
    """重复 close 不抛错。"""
    installed_connector._client = None
    asyncio.run(installed_connector.close())  # 不抛


# ===== 模块常量 =====


def test_circuit_breaker_constants() -> None:
    """熔断配置可读。"""
    assert CIRCUIT_BREAKER_THRESHOLD == 3
    assert CIRCUIT_BREAKER_COOLDOWN == 30 * 60
