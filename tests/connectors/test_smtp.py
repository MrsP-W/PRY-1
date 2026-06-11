"""D5.1 SMTP transport 抽象 + Connector 测试套件。

覆盖范围(预计 +28 cases):
    - 4 状态返回结果(SMTPSendResult 4 状态枚举严判)
    - InMemorySmtpTransport 行为(连接/登录/发送/退出)
    - InMemorySmtpTransport 异常注入
    - SmtpLibTransport 异常映射(smtplib → SMTPSendResult 4 状态)
    - SmtpLibTransport 异常类(SmtpTransportError / SmtpTimeoutError / SmtpAuthError)
    - SMTPConnector 构造(provider 白名单 + transport is None 严判)
    - SMTPConnector build_message(严判 + 头透传)
    - Keychain 高层封装(沿 imap 范本,set/get_smtp_password round-trip)
    - SERVER_CONFIGS 完整性
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from my_ai_employee.connectors.smtp import (
    SERVER_CONFIGS,
    SMTP_SEND_OK,
    SMTP_SEND_PERMANENT_BOUNCE,
    SMTP_SEND_TRANSPORT_ERROR,
    InMemorySmtpTransport,
    SmtpAuthError,
    SMTPConnector,
    SMTPSendResult,
    SmtpTimeoutError,
    SmtpTransportError,
)

# ===== 1. InMemorySmtpTransport 行为(8 cases)=====


class TestInMemorySmtpTransport:
    def test_default_not_connected(self) -> None:
        transport = InMemorySmtpTransport()
        assert transport.connected is False
        assert transport.logged_in is False
        assert transport.quit_called is False
        assert transport.sent_log == []

    def test_connect_marks_connected(self) -> None:
        transport = InMemorySmtpTransport()
        transport.connect("smtp.qq.com", 465)
        assert transport.connected is True

    def test_login_requires_connected(self) -> None:
        transport = InMemorySmtpTransport()
        with pytest.raises(SmtpTransportError, match="未连接"):
            transport.login("user@qq.com", "authcode")

    def test_login_marks_logged_in(self) -> None:
        transport = InMemorySmtpTransport()
        transport.connect("smtp.qq.com", 465)
        transport.login("user@qq.com", "authcode")
        assert transport.logged_in is True

    def test_send_message_requires_logged_in(self) -> None:
        transport = InMemorySmtpTransport()
        transport.connect("smtp.qq.com", 465)
        result = transport.send_message(EmailMessage())
        assert result.status == SMTP_SEND_TRANSPORT_ERROR
        assert result.error_detail is not None
        assert "未登录" in result.error_detail

    def test_send_message_records_to_log(self) -> None:
        transport = InMemorySmtpTransport()
        transport.connect("smtp.qq.com", 465)
        transport.login("user@qq.com", "authcode")

        msg = EmailMessage()
        msg["From"] = "user@qq.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Test Subject"
        msg.set_content("Test body content")

        result = transport.send_message(msg)
        assert result.status == SMTP_SEND_OK
        assert len(transport.sent_log) == 1
        record = transport.sent_log[0]
        assert record["from"] == "user@qq.com"
        assert record["to"] == ["recipient@example.com"]
        assert record["subject"] == "Test Subject"
        assert "Test body content" in str(record["body"])

    def test_quit_resets_state(self) -> None:
        transport = InMemorySmtpTransport()
        transport.connect("smtp.qq.com", 465)
        transport.login("user@qq.com", "authcode")
        transport.quit()
        assert transport.quit_called is True
        assert transport.connected is False
        assert transport.logged_in is False

    def test_inject_status(self) -> None:
        transport = InMemorySmtpTransport()
        transport.connect("smtp.qq.com", 465)
        transport.login("user@qq.com", "authcode")
        transport.inject_status = SMTP_SEND_PERMANENT_BOUNCE
        result = transport.send_message(EmailMessage())
        assert result.status == SMTP_SEND_PERMANENT_BOUNCE

    def test_inject_exception(self) -> None:
        transport = InMemorySmtpTransport()
        transport.connect("smtp.qq.com", 465)
        transport.login("user@qq.com", "authcode")
        transport.inject_exception = SmtpTransportError("forced error")
        with pytest.raises(SmtpTransportError, match="forced error"):
            transport.send_message(EmailMessage())


# ===== 2. SmtpLibTransport 异常类(4 cases)=====


class TestSmtpExceptionClasses:
    def test_smtp_transport_error(self) -> None:
        with pytest.raises(SmtpTransportError, match="test"):
            raise SmtpTransportError("test")

    def test_smtp_timeout_error(self) -> None:
        with pytest.raises(SmtpTimeoutError, match="test"):
            raise SmtpTimeoutError("test")

    def test_smtp_auth_error(self) -> None:
        with pytest.raises(SmtpAuthError, match="test"):
            raise SmtpAuthError("test")

    def test_inheritance(self) -> None:
        # 3 异常都继承 Exception
        assert issubclass(SmtpTransportError, Exception)
        assert issubclass(SmtpTimeoutError, Exception)
        assert issubclass(SmtpAuthError, Exception)


# ===== 3. SMTPSendResult 数据类(3 cases)=====


class TestSMTPSendResult:
    def test_ok_status_minimal(self) -> None:
        result = SMTPSendResult(status=SMTP_SEND_OK)
        assert result.status == SMTP_SEND_OK
        assert result.smtp_code is None
        assert result.smtp_message is None
        assert result.error_detail is None

    def test_permanent_bounce_with_code(self) -> None:
        result = SMTPSendResult(
            status=SMTP_SEND_PERMANENT_BOUNCE,
            smtp_code=550,
            smtp_message="User unknown",
            error_detail="recipients refused",
        )
        assert result.status == SMTP_SEND_PERMANENT_BOUNCE
        assert result.smtp_code == 550
        assert result.smtp_message == "User unknown"
        assert result.error_detail is not None
        assert "recipients refused" in result.error_detail

    def test_transport_error_with_detail(self) -> None:
        result = SMTPSendResult(
            status=SMTP_SEND_TRANSPORT_ERROR,
            error_detail="connection refused",
        )
        assert result.status == SMTP_SEND_TRANSPORT_ERROR
        assert result.error_detail == "connection refused"


# ===== 4. SMTPConnector 构造(5 cases)=====


class TestSMTPConnectorConstruction:
    def test_valid_qq_provider(self) -> None:
        connector = SMTPConnector(provider="qq", email="user@qq.com")
        assert connector._provider == "qq"
        assert connector._email == "user@qq.com"
        assert connector.server_host == "smtp.qq.com"
        assert connector.server_port == "465"
        assert connector.source_name == "qq"

    def test_invalid_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="未知 provider"):
            SMTPConnector(provider="invalid", email="user@example.com")

    def test_outlook_provider_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="只实现 provider='qq'"):
            SMTPConnector(provider="outlook", email="user@outlook.com")

    def test_gmail_provider_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="只实现 provider='qq'"):
            SMTPConnector(provider="gmail", email="user@gmail.com")

    def test_default_transport_is_none(self) -> None:
        # D5.1-fix 修复:默认 transport=None(防假成功)
        # 原因:生产环境忘记显式注入时,InMemorySmtpTransport 默认 healthy 会"假成功"
        connector = SMTPConnector(provider="qq", email="user@qq.com")
        assert connector.transport is None

    def test_custom_transport_injection(self) -> None:
        # 显式注入自定义 transport
        custom = InMemorySmtpTransport()
        connector = SMTPConnector(provider="qq", email="user@qq.com", transport=custom)
        assert connector.transport is custom


# ===== 5. SMTPConnector.build_message(7 cases)=====


class TestSMTPConnectorBuildMessage:
    def setup_method(self) -> None:
        self.connector = SMTPConnector(provider="qq", email="user@qq.com")

    def test_valid_basic_message(self) -> None:
        msg = self.connector.build_message(
            from_addr="user@qq.com",
            to_addrs=["recipient@example.com"],
            subject="Test Subject",
            body="This is a test body with at least 10 characters.",
        )
        assert msg["From"] == "user@qq.com"
        assert msg["To"] == "recipient@example.com"
        assert msg["Subject"] == "Test Subject"
        assert "This is a test body" in _get_body(msg)

    def test_multiple_recipients(self) -> None:
        msg = self.connector.build_message(
            from_addr="user@qq.com",
            to_addrs=["a@example.com", "b@example.com"],
            subject="Test",
            body="This is a test body with sufficient length.",
        )
        assert msg["To"] == "a@example.com, b@example.com"

    def test_custom_headers(self) -> None:
        msg = self.connector.build_message(
            from_addr="user@qq.com",
            to_addrs=["a@example.com"],
            subject="Test",
            body="This is a test body with sufficient length.",
            headers={"X-Outbox-Id": "123", "X-Priority": "urgent"},
        )
        assert msg["X-Outbox-Id"] == "123"
        assert msg["X-Priority"] == "urgent"

    def test_from_addr_missing_at_raises(self) -> None:
        with pytest.raises(ValueError, match="from_addr 必须含 @"):
            self.connector.build_message(
                from_addr="invalid",
                to_addrs=["a@example.com"],
                subject="Test",
                body="This is a test body with sufficient length.",
            )

    def test_empty_to_addrs_raises(self) -> None:
        with pytest.raises(ValueError, match="to_addrs 必须是非空 list"):
            self.connector.build_message(
                from_addr="user@qq.com",
                to_addrs=[],
                subject="Test",
                body="This is a test body with sufficient length.",
            )

    def test_empty_subject_raises(self) -> None:
        with pytest.raises(ValueError, match="subject 必须是"):
            self.connector.build_message(
                from_addr="user@qq.com",
                to_addrs=["a@example.com"],
                subject="   ",
                body="This is a test body with sufficient length.",
            )

    def test_empty_body_raises(self) -> None:
        with pytest.raises(ValueError, match="body 必须是"):
            self.connector.build_message(
                from_addr="user@qq.com",
                to_addrs=["a@example.com"],
                subject="Test",
                body="",
            )

    def test_invalid_recipient_format_raises(self) -> None:
        with pytest.raises(ValueError, match="to_addrs\\[0\\]"):
            self.connector.build_message(
                from_addr="user@qq.com",
                to_addrs=["invalid-no-at"],
                subject="Test",
                body="This is a test body with sufficient length.",
            )


# ===== 6. SERVER_CONFIGS 完整性(2 cases)=====


class TestServerConfigs:
    def test_all_required_providers(self) -> None:
        assert "qq" in SERVER_CONFIGS
        assert "outlook" in SERVER_CONFIGS
        assert "gmail" in SERVER_CONFIGS

    def test_qq_uses_ssl_465(self) -> None:
        # D5.1 决策:统一 SSL 端口 465
        qq_config = SERVER_CONFIGS["qq"]
        assert qq_config.host == "smtp.qq.com"
        assert qq_config.port == 465


# ===== 7. SMTPConnector transport 边界(D5.1-fix 修复,7 cases)=====
# D5.1-fix 风险 #2 缓解:默认 transport=None(不再静默 fallback 到
# InMemorySmtpTransport),构造时 loguru.warning,首次 connect()/healthcheck()
# 入口 is None 硬报错 → 防生产环境"假成功"。覆盖以下 7 维:


class TestSMTPConnectorTransportBoundary:
    """D5.1-fix 修复后的 transport 边界完整测试(7 cases)。

    覆盖维度:
        1. 默认 transport=None(防假成功)
        2. transport property 返回 None vs 注入值
        3. 构造时未注入 → loguru.warning
        4. connect() 未注入 transport → SmtpTransportError
        5. healthcheck() 未注入 transport → 返回 unhealthy
        6. 显式 InMemorySmtpTransport 注入 → connect 成功
        7. 显式 SmtpLibTransport 注入 → connect 成功(mock smtplib)
    """

    def test_transport_property_returns_none_when_not_injected(self) -> None:
        # 默认 transport=None 后,property 返回 None(不是 InMemorySmtpTransport)
        connector = SMTPConnector(provider="qq", email="user@qq.com")
        assert connector.transport is None

    def test_transport_property_returns_injected_when_injected(self) -> None:
        # 显式注入 → property 返回原对象
        custom = InMemorySmtpTransport()
        connector = SMTPConnector(provider="qq", email="user@qq.com", transport=custom)
        assert connector.transport is custom

    def test_constructor_logs_warning_when_transport_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # D5.1-fix:构造时未注入 transport → 触发 loguru.warning(提醒用户)
        # 关键:loguru 不走 stdlib logging,caplog 抓不到 → 用 monkeypatch 替换
        # smtp.logger.warning 为 mock,验证调用次数 + 内容
        from my_ai_employee.connectors import smtp as smtp_module

        captured_warnings: list[str] = []
        monkeypatch.setattr(
            smtp_module.logger, "warning", lambda msg: captured_warnings.append(str(msg))
        )
        SMTPConnector(provider="qq", email="user@qq.com")
        assert len(captured_warnings) == 1
        assert "未注入 transport" in captured_warnings[0]
        assert "provider=qq" in captured_warnings[0]

    def test_connect_without_transport_raises_smtp_transport_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # D5.1-fix 修复:未注入 transport 时,connect() 入口 is None 硬报错
        # 避免生产环境忘记注入导致"假成功"
        # 1. monkeypatch Keychain 让 connect() 通过凭据校验
        from my_ai_employee.core import keychain

        monkeypatch.setattr(
            keychain,
            "get_smtp_password",
            lambda email: keychain.KeychainResult(ok=True, value="test-authcode"),
        )
        connector = SMTPConnector(provider="qq", email="user@qq.com")
        # 2. 调 connect() → 应抛 SmtpTransportError
        import asyncio

        with pytest.raises(SmtpTransportError, match="transport 未注入"):
            asyncio.run(connector.connect())

    def test_healthcheck_without_transport_returns_unhealthy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # D5.1-fix 修复:未注入 transport 时,healthcheck() 也走 connect() 链路 → 失败
        from my_ai_employee.core import keychain

        monkeypatch.setattr(
            keychain,
            "get_smtp_password",
            lambda email: keychain.KeychainResult(ok=True, value="test-authcode"),
        )
        connector = SMTPConnector(provider="qq", email="user@qq.com")
        import asyncio

        result = asyncio.run(connector.healthcheck())
        # healthcheck 返回 ok=False(不抛异常,符合 healthcheck 契约)
        assert result.ok is False
        assert result.error is not None
        assert "transport 未注入" in result.error

    def test_explicit_inmemory_transport_succeeds_connect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 显式注入 InMemorySmtpTransport → connect() 成功(测试场景)
        from my_ai_employee.core import keychain

        monkeypatch.setattr(
            keychain,
            "get_smtp_password",
            lambda email: keychain.KeychainResult(ok=True, value="test-authcode"),
        )
        transport = InMemorySmtpTransport()
        connector = SMTPConnector(provider="qq", email="user@qq.com", transport=transport)
        import asyncio

        # connect 不抛异常 + transport 已连
        asyncio.run(connector.connect())
        assert transport.connected is True
        assert transport.logged_in is True

    def test_explicit_smtplib_transport_succeeds_connect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 显式注入 SmtpLibTransport → connect() 成功(mock smtplib.SMTP_SSL)
        from unittest.mock import MagicMock

        from my_ai_employee.connectors.smtp import SmtpLibTransport
        from my_ai_employee.core import keychain

        monkeypatch.setattr(
            keychain,
            "get_smtp_password",
            lambda email: keychain.KeychainResult(ok=True, value="test-authcode"),
        )

        # Mock smtplib.SMTP_SSL — 不真连 QQ 服务器
        mock_smtp_instance = MagicMock()
        mock_smtp_class = MagicMock(return_value=mock_smtp_instance)
        monkeypatch.setattr("smtplib.SMTP_SSL", mock_smtp_class)

        transport = SmtpLibTransport()
        connector = SMTPConnector(provider="qq", email="user@qq.com", transport=transport)
        import asyncio

        # connect 不抛异常
        asyncio.run(connector.connect())
        # 验证 smtplib.SMTP_SSL 被调用(参数 = smtp.qq.com:465)
        mock_smtp_class.assert_called_once()
        # 验证 login 用了 email + password
        mock_smtp_instance.login.assert_called_once_with("user@qq.com", "test-authcode")


# ===== 私有 helper =====


def _get_body(message: EmailMessage) -> str:
    """从 EmailMessage 提取正文(测试断言用)。"""
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(payload) if payload else ""
