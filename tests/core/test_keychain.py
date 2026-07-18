"""Keychain 平台适配层的无真实凭证测试。"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import Mock

import pytest

import my_ai_employee.core.keychain as keychain


def _completed(*, stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["security"], returncode, stdout=stdout)


def test_is_available_requires_macos_and_security_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(keychain, "_security_command_exists", lambda: True)
    assert keychain.is_available() is True

    monkeypatch.setattr(sys, "platform", "linux")
    assert keychain.is_available() is False


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (_completed(returncode=1), True),
        (FileNotFoundError(), False),
        (subprocess.TimeoutExpired(["security"], 5), False),
    ],
)
def test_security_command_detection_handles_platform_outcomes(
    monkeypatch: pytest.MonkeyPatch, outcome: object, expected: bool
) -> None:
    run = Mock(side_effect=outcome if isinstance(outcome, BaseException) else None)
    if not isinstance(outcome, BaseException):
        run.return_value = outcome
    monkeypatch.setattr(subprocess, "run", run)

    assert keychain._security_command_exists() is expected


def test_set_password_uses_atomic_security_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keychain, "is_available", lambda: True)
    run = Mock(return_value=_completed())
    monkeypatch.setattr(subprocess, "run", run)

    result = keychain.set_password("service", "user@example.com", "secret")

    assert result == keychain.KeychainResult(ok=True)
    assert run.call_args.args[0] == [
        "security",
        "add-generic-password",
        "-a",
        "user@example.com",
        "-s",
        "service",
        "-w",
        "secret",
        "-U",
    ]
    assert run.call_args.kwargs["check"] is True


@pytest.mark.parametrize(
    "operation, expected_error",
    [
        (subprocess.CalledProcessError(1, ["security"], stderr="denied"), "失败: denied"),
        (subprocess.TimeoutExpired(["security"], 10), "超时（10s）"),
        (OSError("unavailable"), "未知错误"),
    ],
)
def test_set_password_reports_security_errors(
    monkeypatch: pytest.MonkeyPatch, operation: BaseException, expected_error: str
) -> None:
    monkeypatch.setattr(keychain, "is_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=operation))

    result = keychain.set_password("service", "account", "secret")

    assert result.ok is False
    assert result.error is not None and expected_error in result.error


def test_generic_password_operations_short_circuit_off_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(keychain, "is_available", lambda: False)

    for result in (
        keychain.set_password("service", "account", "secret"),
        keychain.get_password("service", "account"),
        keychain.delete_password("service", "account"),
    ):
        assert result.ok is False
        assert result.error == "当前平台不支持 Keychain（非 macOS）"


def test_get_password_returns_stripped_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keychain, "is_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", Mock(return_value=_completed(stdout=" secret\n")))

    assert keychain.get_password("service", "account") == keychain.KeychainResult(
        ok=True, value="secret"
    )


@pytest.mark.parametrize(
    "operation, expected",
    [
        (subprocess.CalledProcessError(44, ["security"], stderr="not here"), "not found"),
        (
            subprocess.CalledProcessError(1, ["security"], stderr="access denied"),
            "失败: access denied",
        ),
        (subprocess.TimeoutExpired(["security"], 10), "超时（10s）"),
        (OSError("unavailable"), "未知错误"),
    ],
)
def test_get_password_classifies_errors(
    monkeypatch: pytest.MonkeyPatch, operation: BaseException, expected: str
) -> None:
    monkeypatch.setattr(keychain, "is_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=operation))

    result = keychain.get_password("service", "account")

    assert result.ok is False
    assert result.error is not None and expected in result.error


@pytest.mark.parametrize(
    "operation, expected_ok, expected_error",
    [
        (_completed(), True, None),
        (subprocess.CalledProcessError(44, ["security"], stderr="not found"), True, None),
        (
            subprocess.CalledProcessError(1, ["security"], stderr="access denied"),
            False,
            "失败: access denied",
        ),
        (subprocess.TimeoutExpired(["security"], 10), False, "超时（10s）"),
        (OSError("unavailable"), False, "未知错误"),
    ],
)
def test_delete_password_is_idempotent_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
    operation: object,
    expected_ok: bool,
    expected_error: str | None,
) -> None:
    monkeypatch.setattr(keychain, "is_available", lambda: True)
    run = Mock(side_effect=operation if isinstance(operation, BaseException) else None)
    if not isinstance(operation, BaseException):
        run.return_value = operation
    monkeypatch.setattr(subprocess, "run", run)

    result = keychain.delete_password("service", "account")

    assert result.ok is expected_ok
    if expected_error is None:
        assert result.error is None
    else:
        assert result.error is not None and expected_error in result.error


def test_legacy_convenience_functions_use_fixed_service_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_password = Mock(return_value=keychain.KeychainResult(ok=True))
    get_password = Mock(return_value=keychain.KeychainResult(ok=True, value="secret"))
    monkeypatch.setattr(keychain, "set_password", set_password)
    monkeypatch.setattr(keychain, "get_password", get_password)

    keychain.set_db_password("db-secret")
    keychain.get_db_password()
    keychain.set_imap_password("mail@example.com", "imap-secret")
    keychain.get_imap_password("mail@example.com")
    keychain.set_smtp_password("mail@example.com", "smtp-secret")
    keychain.get_smtp_password("mail@example.com")

    assert set_password.call_args_list == [
        ((keychain.SERVICE_DB, "data.db", "db-secret"),),
        ((keychain.SERVICE_IMAP_QQ, "mail@example.com", "imap-secret"),),
        ((keychain.SERVICE_SMTP_QQ, "mail@example.com", "smtp-secret"),),
    ]
    assert get_password.call_args_list == [
        ((keychain.SERVICE_DB, "data.db"),),
        ((keychain.SERVICE_IMAP_QQ, "mail@example.com"),),
        ((keychain.SERVICE_SMTP_QQ, "mail@example.com"),),
    ]


@pytest.mark.parametrize(
    "provider, service",
    [
        ("qq", keychain.SERVICE_SMTP_QQ),
        ("outlook", keychain.SERVICE_SMTP_OUTLOOK),
        ("gmail", keychain.SERVICE_SMTP_GMAIL),
    ],
)
def test_smtp_provider_helpers_route_to_the_provider_service(
    monkeypatch: pytest.MonkeyPatch, provider: str, service: str
) -> None:
    get_password = Mock(return_value=keychain.KeychainResult(ok=True, value="secret"))
    set_password = Mock(return_value=keychain.KeychainResult(ok=True))
    delete_password = Mock(return_value=keychain.KeychainResult(ok=True))
    monkeypatch.setattr(keychain, "get_password", get_password)
    monkeypatch.setattr(keychain, "set_password", set_password)
    monkeypatch.setattr(keychain, "delete_password", delete_password)

    keychain.get_smtp_password_for_provider(provider, "mail@example.com")
    keychain.set_smtp_password_for_provider(provider, "mail@example.com", "secret")
    keychain.delete_smtp_password_for_provider(provider, "mail@example.com")

    get_password.assert_called_once_with(service, "mail@example.com")
    set_password.assert_called_once_with(service, "mail@example.com", "secret")
    delete_password.assert_called_once_with(service, "mail@example.com")


def test_smtp_provider_helpers_reject_unknown_provider() -> None:
    with pytest.raises(ValueError, match="smtp_provider"):
        keychain.get_smtp_password_for_provider("unknown", "mail@example.com")


@pytest.mark.parametrize(
    "provider, service",
    [
        ("microsoft", keychain.SERVICE_OAUTH_MICROSOFT),
        ("google", keychain.SERVICE_OAUTH_GOOGLE),
    ],
)
def test_oauth_helpers_validate_and_route_tokens(
    monkeypatch: pytest.MonkeyPatch, provider: str, service: str
) -> None:
    set_password = Mock(return_value=keychain.KeychainResult(ok=True))
    get_password = Mock(return_value=keychain.KeychainResult(ok=True, value="{}"))
    delete_password = Mock(return_value=keychain.KeychainResult(ok=True))
    monkeypatch.setattr(keychain, "set_password", set_password)
    monkeypatch.setattr(keychain, "get_password", get_password)
    monkeypatch.setattr(keychain, "delete_password", delete_password)

    keychain.set_oauth_token(provider, "mail@example.com", "{}")
    keychain.get_oauth_token(provider, "mail@example.com")
    keychain.delete_oauth_token(provider, "mail@example.com")

    set_password.assert_called_once_with(service, "mail@example.com", "{}")
    get_password.assert_called_once_with(service, "mail@example.com")
    delete_password.assert_called_once_with(service, "mail@example.com")


@pytest.mark.parametrize("token", [None, "", "   "])
def test_set_oauth_token_rejects_blank_or_non_string_token(token: object) -> None:
    with pytest.raises(ValueError, match="token_json"):
        keychain.set_oauth_token("microsoft", "mail@example.com", token)  # type: ignore[arg-type]


def test_oauth_helpers_reject_unknown_provider() -> None:
    with pytest.raises(ValueError, match="oauth_provider"):
        keychain.get_oauth_token("unknown", "mail@example.com")
