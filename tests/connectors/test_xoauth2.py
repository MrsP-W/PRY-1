"""v0.2.2 #5 — XOAUTH2 helper 单元测试(12 cases).

承接 [[v0.2.2-p5-oauth-phase2-launch-2026-06-18]] §2.1 commit 4/5.
4 段测试覆盖(12 cases):
    1. build_xoauth2_auth_string(4 tests):SASL / JSON / email 严判 / token 严判
    2. parse_xoauth2_auth_string(2 tests):SASL 往返 / JSON 往返
    3. parse_xoauth2_failure_response(2 tests):成功 / is_retryable
    4. XOAUTH2Authenticator(4 tests):构造严判 / build_auth_string / 4 重防误发 / Provider 端到端

测试用 unittest.mock 注入 mock OAuth2Provider(零 msal/google-auth 依赖).
完全离线测试,无需真实 SMTP/OAuth 服务器(沿 D5.6.5 4 重防误发).

设计原则(沿 [[d4.7.3-v1.0.6-p2-3]] + [[d3.3.3-sqlcipher-integrityerror]] + commit 2/3 范本):
    - type() is bool 拒绝(bool 子类陷阱)
    - 公共 API 入口严判(email / token / provider / format)
    - 数据类 __post_init__ 双层防御(委托 XOAUTH2AuthString / XOAUTH2Failure)
    - except 范围窄化(OAuth2Error 透传)
    - 4 重防误发(env 门 + factory 注入 + 不真发 + email 严判)
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== 1. build_xoauth2_auth_string(4 tests)=====
# 沿 RFC 7628 §3.1 SASL XOAUTH2 初始客户端响应


def test_build_xoauth2_auth_string_sasl_default() -> Any:
    """1.1 build_xoauth2_auth_string 默认 SASL 格式(沿 RFC 7628 §3.1)。

    验证:
        - raw 是 base64 编码
        - 解码后含 user=<email> + auth=Bearer <token> + \\x01\\x01 结尾
        - format == "sasl"
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2_FORMAT_SASL,
        build_xoauth2_auth_string,
    )

    auth = build_xoauth2_auth_string(
        email="user@example.com",
        access_token="ya29.xx_access_token",
    )

    # base64 解码验证
    plain = base64.b64decode(auth.raw).decode("utf-8")
    assert plain.startswith("user=user@example.com\x01")
    assert "auth=Bearer ya29.xx_access_token" in plain
    assert plain.endswith("\x01\x01")
    assert auth.format == XOAUTH2_FORMAT_SASL
    assert auth.email == "user@example.com"
    assert auth.access_token == "ya29.xx_access_token"


def test_build_xoauth2_auth_string_json_format() -> Any:
    """1.2 build_xoauth2_auth_string JSON 格式(legacy 兼容)。

    验证:
        - raw 是 base64 编码
        - 解码后是合法 JSON dict 含 user + access_token + auth="Bearer"
        - format == "json"
    """
    import json

    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2_FORMAT_JSON,
        build_xoauth2_auth_string,
    )

    auth = build_xoauth2_auth_string(
        email="user@gmail.com",
        access_token="ya29.xx_access_token",
        format="json",
    )

    plain = base64.b64decode(auth.raw).decode("utf-8")
    obj = json.loads(plain)
    assert obj["user"] == "user@gmail.com"
    assert obj["access_token"] == "ya29.xx_access_token"
    assert obj["auth"] == "Bearer"
    assert auth.format == XOAUTH2_FORMAT_JSON


def test_build_xoauth2_auth_string_rejects_invalid_email() -> Any:
    """1.3 build_xoauth2_auth_string email 严判失败(4 重防误发 #4)。

    验证:
        - email 非 str 拒绝
        - email 缺 @ 拒绝
        - email 仅空白拒绝
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2EmailValidationError,
        build_xoauth2_auth_string,
    )

    # 1.3.1 非 str
    with pytest.raises(XOAUTH2EmailValidationError, match="email 必须是 str"):
        build_xoauth2_auth_string(email=123, access_token="token")  # type: ignore[arg-type]

    # 1.3.2 缺 @
    with pytest.raises(XOAUTH2EmailValidationError, match="email 必须含 @"):
        build_xoauth2_auth_string(email="not-an-email", access_token="token")

    # 1.3.3 仅空白
    with pytest.raises(XOAUTH2EmailValidationError, match="email 必填且必须非空字符串"):
        build_xoauth2_auth_string(email="   ", access_token="token")


def test_build_xoauth2_auth_string_rejects_invalid_token() -> Any:
    """1.4 build_xoauth2_auth_string access_token 严判失败(沿 D4.7.3 公共 API 入口严判)。

    验证:
        - token 非 str 拒绝
        - token 仅空白拒绝
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2TokenValidationError,
        build_xoauth2_auth_string,
    )

    # 1.4.1 非 str
    with pytest.raises(XOAUTH2TokenValidationError, match="access_token 必须是 str"):
        build_xoauth2_auth_string(email="user@x.com", access_token=123)  # type: ignore[arg-type]

    # 1.4.2 仅空白
    with pytest.raises(XOAUTH2TokenValidationError, match="access_token 必填且必须非空字符串"):
        build_xoauth2_auth_string(email="user@x.com", access_token="   ")


# ===== 2. parse_xoauth2_auth_string(2 tests)=====


def test_parse_xoauth2_auth_string_sasl_round_trip() -> Any:
    """2.1 build → parse SASL 格式往返一致(沿 RFC 7628 §3.1)。

    验证:
        - build 生成的 raw 可被 parse 还原
        - parse 识别 SASL 格式
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2_FORMAT_SASL,
        build_xoauth2_auth_string,
        parse_xoauth2_auth_string,
    )

    auth = build_xoauth2_auth_string(
        email="user@outlook.com",
        access_token="EwA4B+xxx",
        format="sasl",
    )
    email, token, fmt = parse_xoauth2_auth_string(auth.raw)
    assert email == "user@outlook.com"
    assert token == "EwA4B+xxx"
    assert fmt == XOAUTH2_FORMAT_SASL


def test_parse_xoauth2_auth_string_json_round_trip() -> Any:
    """2.2 build → parse JSON 格式往返一致(legacy 兼容)。

    验证:
        - JSON 格式 raw 可被 parse 还原
        - parse 识别 JSON 格式
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2_FORMAT_JSON,
        build_xoauth2_auth_string,
        parse_xoauth2_auth_string,
    )

    auth = build_xoauth2_auth_string(
        email="user@gmail.com",
        access_token="ya29.xx",
        format="json",
    )
    email, token, fmt = parse_xoauth2_auth_string(auth.raw)
    assert email == "user@gmail.com"
    assert token == "ya29.xx"
    assert fmt == XOAUTH2_FORMAT_JSON


# ===== 3. parse_xoauth2_failure_response(2 tests)=====


def test_parse_xoauth2_failure_response_success() -> Any:
    """3.1 parse_xoauth2_failure_response 成功解析(沿 RFC 7628 §3.2)。

    验证:
        - 解码 + JSON 解析
        - status / schemes / scope 字段正确
    """
    from my_ai_employee.connectors.xoauth2 import parse_xoauth2_failure_response

    raw_json = b'{"status":"401","schemes":"bearer","scope":"https://mail.google.com/"}'
    server_response = base64.b64encode(raw_json).decode("ascii")

    failure = parse_xoauth2_failure_response(server_response)

    assert failure.status == "401"
    assert failure.schemes == ("bearer",)
    assert failure.scope == "https://mail.google.com/"
    assert failure.raw == server_response


def test_parse_xoauth2_failure_response_is_retryable() -> Any:
    """3.2 XOAUTH2Failure.is_retryable 判定(沿 RFC 7628 §3.2)。

    验证:
        - 401 (invalid credentials) → 不可重试
        - 4 (transient) → 可重试 1 次
    """
    from my_ai_employee.connectors.xoauth2 import parse_xoauth2_failure_response

    # 3.2.1 401 不可重试
    raw_401 = base64.b64encode(b'{"status":"401","schemes":"bearer"}').decode("ascii")
    failure_401 = parse_xoauth2_failure_response(raw_401)
    assert failure_401.is_retryable() is False

    # 3.2.2 4 可重试
    raw_4 = base64.b64encode(b'{"status":"4","schemes":"bearer"}').decode("ascii")
    failure_4 = parse_xoauth2_failure_response(raw_4)
    assert failure_4.is_retryable() is True


# ===== 4. XOAUTH2Authenticator(4 tests)=====


def test_xoauth2_authenticator_constructor_validates_provider() -> Any:
    """4.1 XOAUTH2Authenticator.__init__ provider / format 严判(沿 D4.7.3 公共 API 入口严判)。

    验证:
        - provider 非 str / 不在白名单拒绝
        - format 非 str / 不在白名单拒绝
        - 双注入 oauth2_provider + oauth2_provider_factory 拒绝
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2Authenticator,
        XOAUTH2AuthStringError,
        XOAUTH2ProviderError,
    )
    from my_ai_employee.core.oauth2 import OAuth2Provider

    # 4.1.1 provider 不在白名单
    with pytest.raises(XOAUTH2ProviderError, match="provider 必须是"):
        XOAUTH2Authenticator(provider="yahoo")

    # 4.1.2 format 不在白名单
    with pytest.raises(XOAUTH2AuthStringError, match="format 必须是"):
        XOAUTH2Authenticator(provider="microsoft", format="custom")

    # 4.1.3 双注入拒绝
    mock_provider = MagicMock(spec=OAuth2Provider)
    mock_factory = MagicMock(return_value=mock_provider)
    with pytest.raises(XOAUTH2ProviderError, match="不能同时传入"):
        XOAUTH2Authenticator(
            provider="microsoft",
            oauth2_provider=mock_provider,
            oauth2_provider_factory=mock_factory,
        )


def test_xoauth2_authenticator_build_auth_string() -> Any:
    """4.2 XOAUTH2Authenticator.build_auth_string 端到端 + 构造 format 透传。

    验证:
        - 实例构造时 format 透传到 build_auth_string
        - 单次调用 format 覆盖构造 format
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2_FORMAT_JSON,
        XOAUTH2_FORMAT_SASL,
        XOAUTH2Authenticator,
    )

    auth = XOAUTH2Authenticator(provider="microsoft")
    assert auth.format == XOAUTH2_FORMAT_SASL

    auth_default = auth.build_auth_string(email="u@x.com", access_token="t1")
    assert auth_default.format == XOAUTH2_FORMAT_SASL

    auth_json = auth.build_auth_string(
        email="u@x.com", access_token="t2", format=XOAUTH2_FORMAT_JSON
    )
    assert auth_json.format == XOAUTH2_FORMAT_JSON


def test_xoauth2_authenticator_four_layers_defense() -> Any:
    """4.3 XOAUTH2Authenticator 4 重防误发(沿 D5.6.5 / D5.6.5.1 范本)。

    4 重防误发:
        1. **env 门**:assert_real_network_enabled() 未设置 env 时拒绝
        2. **factory 注入**:未注入 oauth2_provider + 未注入 factory 时 get_oauth2_provider() 拒绝
        3. **不真发邮件**:build_auth_string() 不调 smtplib,真实网络关闭也能生成
        4. **email 严判**:build_auth_string 拒绝非 str / 缺 @ email
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2Authenticator,
        XOAUTH2EmailValidationError,
        XOAUTH2ProviderError,
        XOAUTH2RealNetworkDisabledError,
    )

    # 4.3.1 真实网络未开启 → 拒绝(monkeypatch 临时清空 env)
    auth = XOAUTH2Authenticator(provider="google")
    import os

    saved_env = os.environ.pop("XOAUTH2_REAL_NETWORK", None)
    try:
        with pytest.raises(XOAUTH2RealNetworkDisabledError, match="真实 SMTP 网络未开启"):
            auth.assert_real_network_enabled()
    finally:
        if saved_env is not None:
            os.environ["XOAUTH2_REAL_NETWORK"] = saved_env

    # 4.3.2 未注入 oauth2_provider + 未注入 factory → 拒绝
    auth_no_inject = XOAUTH2Authenticator(provider="microsoft")
    with pytest.raises(XOAUTH2ProviderError, match="未注入 oauth2_provider"):
        auth_no_inject.get_oauth2_provider()

    # 4.3.3 不真发邮件 — build_auth_string 不依赖 env
    auth3 = XOAUTH2Authenticator(provider="google")
    auth_string = auth3.build_auth_string(email="u@gmail.com", access_token="t3")
    assert auth_string.email == "u@gmail.com"

    # 4.3.4 email 严判
    with pytest.raises(XOAUTH2EmailValidationError, match="email 必须含 @"):
        auth3.build_auth_string(email="bad", access_token="t3")


def test_xoauth2_authenticator_end_to_end_via_oauth2_provider() -> Any:
    """4.4 XOAUTH2Authenticator.build_auth_string_via_oauth2_provider 端到端。

    验证:
        - exchange_code 成功 → 鉴权字符串生成
        - refresh_token 成功 → 鉴权字符串生成
        - OAuth2Provider 异常透传为 XOAUTH2ProviderError
    """
    from my_ai_employee.connectors.xoauth2 import (
        XOAUTH2Authenticator,
        XOAUTH2ProviderError,
    )
    from my_ai_employee.core.oauth2 import (
        OAuth2Config,
        OAuth2Provider,
        OAuth2Token,
        OAuth2TokenExchangeError,
    )

    # 4.4.1 成功路径 — exchange_code
    expires_at_ms = 9999999999999  # 未来时间
    mock_token = OAuth2Token(
        access_token="ya29.xx_access",
        refresh_token="1//xx_refresh",
        expires_at_ms=expires_at_ms,
    )
    mock_provider = MagicMock(spec=OAuth2Provider)
    mock_provider.exchange_code.return_value = mock_token
    auth = XOAUTH2Authenticator(provider="google", oauth2_provider=mock_provider)
    config = OAuth2Config(
        client_id="my-google-id",
        client_secret="my-google-secret",
        redirect_uri="https://x.com/cb",
        scope=("https://mail.google.com/",),
    )
    auth_string = auth.build_auth_string_via_oauth2_provider(
        config=config, code="auth-code-123", user_email="user@gmail.com"
    )
    assert auth_string.access_token == "ya29.xx_access"
    assert auth_string.email == "user@gmail.com"
    assert "user=user@gmail.com" in base64.b64decode(auth_string.raw).decode("utf-8")
    mock_provider.exchange_code.assert_called_once_with(config, "auth-code-123")

    # 4.4.2 成功路径 — refresh_token
    mock_provider2 = MagicMock(spec=OAuth2Provider)
    mock_provider2.refresh_token.return_value = OAuth2Token(
        access_token="ya29.xx_new",
        refresh_token=None,  # Google refresh 通常不返新 refresh_token
        expires_at_ms=expires_at_ms,
    )
    auth2 = XOAUTH2Authenticator(provider="google", oauth2_provider=mock_provider2)
    auth_string2 = auth2.build_auth_string_via_refresh(
        config=config, refresh_token_value="1//old_refresh", user_email="user@gmail.com"
    )
    assert auth_string2.access_token == "ya29.xx_new"

    # 4.4.3 OAuth2Provider 异常 → 透传
    mock_provider3 = MagicMock(spec=OAuth2Provider)
    mock_provider3.exchange_code.side_effect = ConnectionError("OAuth 端点超时")
    auth3 = XOAUTH2Authenticator(provider="google", oauth2_provider=mock_provider3)
    with pytest.raises(XOAUTH2ProviderError, match="OAuth2Provider.exchange_code 失败"):
        auth3.build_auth_string_via_oauth2_provider(
            config=config, code="bad-code", user_email="user@gmail.com"
        )

    # 4.4.4 OAuth2TokenExchangeError 透传(不静默吞)
    mock_provider4 = MagicMock(spec=OAuth2Provider)
    mock_provider4.exchange_code.side_effect = OAuth2TokenExchangeError("invalid code")
    auth4 = XOAUTH2Authenticator(provider="google", oauth2_provider=mock_provider4)
    with pytest.raises(OAuth2TokenExchangeError, match="invalid code"):
        auth4.build_auth_string_via_oauth2_provider(
            config=config, code="bad-code", user_email="user@gmail.com"
        )
