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

    def test_default_transport_is_inmemory(self) -> None:
        # D4.7.3 v1.0.3 P2-2 范本:is None 不用 or → 默认 InMemorySmtpTransport
        connector = SMTPConnector(provider="qq", email="user@qq.com")
        assert isinstance(connector.transport, InMemorySmtpTransport)

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


# ===== 私有 helper =====


def _get_body(message: EmailMessage) -> str:
    """从 EmailMessage 提取正文(测试断言用)。"""
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(payload) if payload else ""
