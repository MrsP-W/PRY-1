"""v0.2.2 #5 — GoogleOAuth2 单元测试(11 cases).

承接 [[v0.2.2-p5-oauth-phase2-launch-2026-06-18]] §2.2 commit 3/5.
4 段测试覆盖(11 cases):
    1. URL 构造(5 tests):基本 URL / access_type=offline / prompt=consent / 默认 state / 严判
    2. exchange_code(2 tests):成功 / 异常收窄
    3. refresh_token(2 tests):成功 / 异常收窄
    4. 严判(1 test) + Protocol 合规(1 test)

测试用 unittest.mock patch google_auth_oauthlib.Flow(google_auth_client_factory 注入).
完全离线测试,无需真实 google_auth_oauthlib 依赖(6/19 commit 3 暂不引入 dep,6/22 commit 5 加).

设计原则(沿 [[d4.7.3-v1.0.6-p2-3]] + [[d3.3.3-sqlcipher-integrityerror]] + commit 2 范本):
    - type() is bool 拒绝(bool 子类陷阱)
    - 公共 API 入口严判(config / state / code / refresh_token_value)
    - 数据类 __post_init__ 双层防御(委托 OAuth2Token)
    - except 范围窄化(仅捕 google_auth/网络异常,OAuth2Error 透传)
    - Google 特色字段(access_type=offline / prompt=consent / include_granted_scopes)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== 1. URL 构造(5 tests)=====


def test_get_auth_url_basic_construction():
    """1.1 GoogleOAuth2.get_auth_url 基本 URL 构造(9 字段全含)."""
    from my_ai_employee.core.oauth2 import OAuth2Config
    from my_ai_employee.core.oauth2_google import (
        GOOGLE_AUTHORIZE_URL,
        GoogleOAuth2,
    )

    config = OAuth2Config(
        client_id="my-google-app-id",
        client_secret="my-google-app-secret",
        redirect_uri="https://my-app.com/oauth/callback",
        scope=("https://mail.google.com/",),
    )
    provider = GoogleOAuth2()
    url = provider.get_auth_url(config, state="test-state-123")

    assert url.startswith(f"{GOOGLE_AUTHORIZE_URL}?")
    # 9 必含字段(URL-encoded)
    assert "client_id=my-google-app-id" in url
    assert "response_type=code" in url
    assert "state=test-state-123" in url
    # Google 特色 3 字段
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "include_granted_scopes=true" in url
    # scope URL 编码
    assert "scope=" in url


def test_get_auth_url_google_specific_params():
    """1.2 Google OAuth 必含 access_type=offline / prompt=consent / include_granted_scopes(沿 Google 文档)."""
    from my_ai_employee.core.oauth2 import OAuth2Config
    from my_ai_employee.core.oauth2_google import GoogleOAuth2

    config = OAuth2Config(
        client_id="x",
        redirect_uri="https://x.com/cb",
        scope=("https://mail.google.com/",),
    )
    provider = GoogleOAuth2()
    url = provider.get_auth_url(config, state="state-xyz")

    # 3 个 Google 特有字段必须存在(否则 refresh_token 不会颁发)
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "include_granted_scopes=true" in url


def test_get_auth_url_state_none_generates_state():
    """1.3 get_auth_url state=None 时自动 generate_state(防 CSRF,沿 RFC 6749 §10.12)."""
    from my_ai_employee.core.oauth2 import OAuth2Config
    from my_ai_employee.core.oauth2_google import GoogleOAuth2

    config = OAuth2Config(
        client_id="x",
        redirect_uri="https://x.com/cb",
        scope=("https://mail.google.com/",),
    )
    provider = GoogleOAuth2()
    url = provider.get_auth_url(config)
    # state 必含
    assert "state=" in url
    # state 长度 >= 32(generate_state 默认)
    state_value = [kv for kv in url.split("&") if kv.startswith("state=")][0]
    state_raw = state_value.split("=", 1)[1]
    assert len(state_raw) >= 32


def test_get_auth_url_rejects_invalid_config():
    """1.4 get_auth_url config 非 OAuth2Config 拒绝(沿 D4.7.3 公共 API 入口严判)."""
    from my_ai_employee.core.oauth2_google import GoogleOAuth2

    provider = GoogleOAuth2()
    with pytest.raises(ValueError, match="config 必须是 OAuth2Config"):
        provider.get_auth_url("not a config")  # type: ignore[arg-type]


def test_get_auth_url_rejects_invalid_state():
    """1.5 get_auth_url state 非 str / 空字符串拒绝(沿 D4.7.3 公共 API 入口严判)."""
    from my_ai_employee.core.oauth2 import OAuth2Config
    from my_ai_employee.core.oauth2_google import GoogleOAuth2

    config = OAuth2Config(client_id="x", redirect_uri="https://x.com/cb", scope=())
    provider = GoogleOAuth2()
    with pytest.raises(ValueError, match="state 必须是 str 或 None"):
        provider.get_auth_url(config, state=123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="state 必填且必须非空字符串"):
        provider.get_auth_url(config, state="   ")


# ===== 2. exchange_code(2 tests)=====


def _build_mock_google_auth_factory(return_value: Any) -> MagicMock:
    """构造 mock google_auth_client_factory(测试 helper).

    Args:
        return_value: google_auth_oauthlib.Flow.fetch_token 方法的返回值

    Returns:
        MagicMock factory 函数
    """
    mock_client = MagicMock()
    mock_client.fetch_token.return_value = return_value
    mock_factory = MagicMock(return_value=mock_client)
    return mock_factory


def test_exchange_code_success_returns_oauth2_token():
    """2.1 exchange_code 成功返回 OAuth2Token(模拟 google_auth_oauthlib 返回值)."""
    from my_ai_employee.core.oauth2 import OAuth2Config
    from my_ai_employee.core.oauth2_google import GoogleOAuth2

    future_ms = int(time.time() * 1000) + 3600 * 1000
    mock_factory = _build_mock_google_auth_factory(
        {
            "access_token": "ya29.xx_access_token",
            "refresh_token": "1//xx_refresh_token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "https://mail.google.com/",
        }
    )

    config = OAuth2Config(
        client_id="my-google-app-id",
        client_secret="my-google-app-secret",
        redirect_uri="https://my-app.com/oauth/callback",
        scope=("https://mail.google.com/",),
    )
    provider = GoogleOAuth2(google_auth_client_factory=mock_factory)
    token = provider.exchange_code(config, "auth-code-123")

    assert token.access_token == "ya29.xx_access_token"
    assert token.refresh_token == "1//xx_refresh_token"
    # expires_at_ms 必在 1 小时后
    assert token.expires_at_ms > future_ms - 60_000
    assert "https://mail.google.com/" in token.scope
    assert token.token_type == "Bearer"

    # 验证 google_auth_client_factory 被调一次,client.fetch_token 被调一次
    mock_factory.assert_called_once()
    mock_factory.return_value.fetch_token.assert_called_once()
    call_kwargs = mock_factory.return_value.fetch_token.call_args.kwargs
    assert call_kwargs["code"] == "auth-code-123"
    assert call_kwargs["client_id"] == "my-google-app-id"


def test_exchange_code_google_auth_exception_narrows_to_token_exchange_error():
    """2.2 exchange_code google_auth 抛异常(网络错等)收窄为 OAuth2TokenExchangeError(沿 D3.3.3 范本)."""
    from my_ai_employee.core.oauth2 import OAuth2Config
    from my_ai_employee.core.oauth2_google import (
        GoogleOAuth2,
        OAuth2TokenExchangeError,
    )

    mock_client = MagicMock()
    mock_client.fetch_token.side_effect = ConnectionError("网络中断")
    mock_factory = MagicMock(return_value=mock_client)

    config = OAuth2Config(client_id="x", redirect_uri="https://x.com/cb", scope=())
    provider = GoogleOAuth2(google_auth_client_factory=mock_factory)
    with pytest.raises(
        OAuth2TokenExchangeError, match="google_auth_oauthlib.Flow.fetch_token 失败"
    ):
        provider.exchange_code(config, "any-code")


# ===== 3. refresh_token(2 tests)=====


def _build_mock_google_auth_factory_refresh(return_value: Any) -> MagicMock:
    """构造 mock google_auth_client_factory(refresh_token 测试用)."""
    mock_client = MagicMock()
    mock_client.fetch_token.return_value = return_value
    mock_factory = MagicMock(return_value=mock_client)
    return mock_factory


def test_refresh_token_success_returns_new_oauth2_token():
    """3.1 refresh_token 成功返回新 OAuth2Token(google refresh 通常不返回新 refresh_token)."""
    from my_ai_employee.core.oauth2 import OAuth2Config
    from my_ai_employee.core.oauth2_google import GoogleOAuth2

    mock_factory = _build_mock_google_auth_factory_refresh(
        {
            "access_token": "ya29.xx_new_access_token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "https://mail.google.com/",
        }
    )

    config = OAuth2Config(
        client_id="x",
        client_secret="y",
        redirect_uri="https://x.com/cb",
        scope=("https://mail.google.com/",),
    )
    provider = GoogleOAuth2(google_auth_client_factory=mock_factory)
    token = provider.refresh_token(config, "old-refresh-token")

    assert token.access_token == "ya29.xx_new_access_token"
    # Google refresh 通常不返回新 refresh_token(沿 Google 文档)
    assert token.refresh_token is None
    assert token.token_type == "Bearer"
    assert token.expires_at_ms > int(time.time() * 1000) + 3000 * 1000  # ~1 hour

    # 验证 fetch_token(refresh_token=...) 被调一次
    mock_factory.return_value.fetch_token.assert_called_once()
    call_kwargs = mock_factory.return_value.fetch_token.call_args.kwargs
    assert call_kwargs["refresh_token"] == "old-refresh-token"
    assert call_kwargs["client_id"] == "x"


def test_refresh_token_google_auth_exception_narrows_to_token_refresh_error():
    """3.2 refresh_token google_auth 抛异常(网络错等)收窄为 OAuth2TokenRefreshError(沿 D3.3.3 范本)."""
    from my_ai_employee.core.oauth2 import OAuth2Config
    from my_ai_employee.core.oauth2_google import (
        GoogleOAuth2,
        OAuth2TokenRefreshError,
    )

    mock_client = MagicMock()
    mock_client.fetch_token.side_effect = TimeoutError("请求超时")
    mock_factory = MagicMock(return_value=mock_client)

    config = OAuth2Config(
        client_id="x",
        client_secret="y",
        redirect_uri="https://x.com/cb",
        scope=(),
    )
    provider = GoogleOAuth2(google_auth_client_factory=mock_factory)
    with pytest.raises(OAuth2TokenRefreshError, match="google_auth_oauthlib.Flow.fetch_token 失败"):
        provider.refresh_token(config, "any-refresh-token")


# ===== 4. 严判(1 test) + Protocol 合规(1 test)=====


def test_default_scopes_validation():
    """4.1 default_scopes 严判(沿 D4.7.3 数据类契约严判)."""
    from my_ai_employee.core.oauth2_google import GoogleOAuth2

    # 4.1.1 非 tuple 拒绝
    with pytest.raises(ValueError, match="default_scopes 必须是 tuple"):
        GoogleOAuth2(default_scopes=[])  # type: ignore[arg-type]

    # 4.1.2 含非 str 元素拒绝
    with pytest.raises(ValueError, match="default_scopes.*必须是 str"):
        GoogleOAuth2(default_scopes=("a", 123))  # type: ignore[arg-type]

    # 4.1.3 仅空白字符串拒绝
    with pytest.raises(ValueError, match="default_scopes.*仅含空白字符"):
        GoogleOAuth2(default_scopes=("valid", "   "))


def test_google_oauth2_satisfies_oauth2provider_protocol():
    """4.2 GoogleOAuth2 满足 OAuth2Provider Protocol(沿 v0.2.1 #6 范本).

    验证 GoogleOAuth2 实例可被 `isinstance(provider, OAuth2Provider)` 识别,
    因 Protocol 用 `@runtime_checkable`.
    """
    from my_ai_employee.core.oauth2 import OAuth2Provider
    from my_ai_employee.core.oauth2_google import GoogleOAuth2

    provider = GoogleOAuth2()
    assert isinstance(provider, OAuth2Provider)
