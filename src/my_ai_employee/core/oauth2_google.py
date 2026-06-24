"""v0.2.2 #5 — Google OAuth 2.0 provider(google-auth 接入).

承接 [[v0.2.2-p5-oauth-phase2-launch-2026-06-18]] §2.2 commit 3/5.
实现 Google OAuth 2.0 provider(沿 [[v0.2.1-oauth-abstract-layer-launch-2026-06-17]]
`OAuth2Provider` Protocol Phase 1).
标识平台:Google Identity OAuth 2.0(支持 gmail SMTP XOAUTH2 鉴权).

业务背景:
    为未来 gmail SMTP OAuth 解封准备(沿 [[v0.2.1-candidates-2026-06-17]] §5.3).
    B 类决策延后:outlook/gmail SMTP provider 单独门控启动.
    Gmail SMTP 自 2024 年起强制要求 OAuth 2.0 鉴权(无 App Password fallback).

设计要点(沿 [[v0.2.2-p5-oauth-phase2-launch-2026-06-18]] 范本 + commit 2 范本):
    - 实现 OAuth2Provider Protocol 3 方法(get_auth_url / exchange_code / refresh_token)
    - `google_auth_oauthlib.Flow` 真实调用(6/22 commit 5 加 dep)
    - 6/19 commit 3 暂不引入 dep,测试用 `google_auth_client_factory` 注入 mock
    - 公共 API 入口严判(沿 [[d4.7.3-v1.0.6-p2-3]])
    - 数据类辅助(`_google_auth_result_to_token` 沿 Phase 1 `OAuth2Token.from_dict`)
    - [[d3.3.3-sqlcipher-integrityerror]] except 范围窄化(不捕 BaseException)
    - Google 强制 PKCE:`code_challenge_method='S256'`(生产必须 HTTPS redirect_uri)

OAuth 端点(沿 Google Identity OAuth 2.0 文档):
    - authorize: `https://accounts.google.com/o/oauth2/v2/auth`
    - token: `https://oauth2.googleapis.com/token`
    - revoke: `https://oauth2.googleapis.com/revoke`

默认 scope(沿 Gmail API 鉴权最小集 — SMTP 发送必需):
    - `https://mail.google.com/`(gmail 全权访问,含 SMTP 发送 + IMAP 读取)
    - `https://www.googleapis.com/auth/userinfo.email`(用户邮箱元数据,可选但推荐)

沿用范本:[[v0.2.1-oauth-abstract-layer-launch-2026-06-17]] / [[d4.7.3-v1.0.6-p2-3]] /
[[d3.3.3-sqlcipher-integrityerror]] / [[b-class-deferral-2026-06-09]] /
[[v0.2.2-p5-oauth-microsoft-2026-06-18]] commit 2
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from my_ai_employee.core.oauth2 import (
    DEFAULT_SCOPE_SEPARATOR,
    OAuth2Config,
    OAuth2Error,
    OAuth2Provider,
    OAuth2Token,
    OAuth2TokenExchangeError,
    OAuth2TokenRefreshError,
    generate_state,
)

if TYPE_CHECKING:
    # google_auth_oauthlib.Flow 真实类型,仅类型检查
    # commit 3 暂不引入 dep,运行时函数内 import
    import google_auth_oauthlib  # type: ignore[import-untyped,unused-ignore]  # noqa: F401

# ===== Google OAuth 2.0 端点常量(沿 Google Identity OAuth 2.0 文档)=====

#: Google Identity OAuth 2.0 authorize endpoint
#: (沿 https://developers.google.com/identity/protocols/oauth2/web-server)
GOOGLE_AUTHORIZE_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"

#: Google OAuth 2.0 token endpoint
GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"

#: Google OAuth 2.0 revoke endpoint(token 撤销用)
GOOGLE_REVOKE_URL: str = "https://oauth2.googleapis.com/revoke"

#: Google 默认 scope 集(沿 gmail SMTP XOAUTH2 鉴权最小集)
GOOGLE_DEFAULT_SCOPES: tuple[str, ...] = (
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/userinfo.email",
)

#: Google token endpoint 默认 expires_in(3600s = 1 小时,沿 Google 文档)
GOOGLE_DEFAULT_EXPIRES_IN_SECONDS: int = 3600

#: google_auth_oauthlib.Flow 默认 code_challenge_method(Google 强制 PKCE)
GOOGLE_DEFAULT_CODE_CHALLENGE_METHOD: str = "S256"

#: Google access_type(offline = 必返 refresh_token)
GOOGLE_ACCESS_TYPE_OFFLINE: str = "offline"

#: Google prompt(consent = 强制显示同意页,确保 refresh_token 颁发)
GOOGLE_PROMPT_CONSENT: str = "consent"

#: Google response_type(Authorization Code Grant)
GOOGLE_RESPONSE_TYPE_CODE: str = "code"

#: Google include_granted_scopes(沿 Google 文档)
GOOGLE_INCLUDE_GRANTED_SCOPES: str = "true"


def _validate_oauth2_config(config: Any) -> OAuth2Config:
    """严判 OAuth2Config(沿 [[d4.7.3-v1.0.6-p2-3]] 公共 API 入口严判).

    Args:
        config: 待严判对象

    Returns:
        OAuth2Config(原对象,不复制)

    Raises:
        ValueError: config 非 OAuth2Config
    """
    if not isinstance(config, OAuth2Config):
        raise ValueError(f"config 必须是 OAuth2Config 实例, 实际 type={type(config).__name__}")
    return config


def _validate_state(state: Any) -> str:
    """严判 state 参数(沿 D4.7.3 公共 API 入口严判).

    Args:
        state: state 字符串(防 CSRF,沿 RFC 6749 §10.12)

    Returns:
        strip 后的 state 字符串

    Raises:
        ValueError: state 非 str 或仅含空白
    """
    if not isinstance(state, str):
        raise ValueError(f"state 必须是 str 或 None, 实际 type={type(state).__name__}")
    stripped = state.strip()
    if not stripped:
        raise ValueError("state 必填且必须非空字符串(防 CSRF)")
    return stripped


def _validate_default_scopes(default_scopes: Any) -> tuple[str, ...]:
    """严判 default_scopes(沿 D4.7.3 数据类契约严判).

    Args:
        default_scopes: tuple[str, ...]

    Returns:
        tuple[str, ...] 严判后的 scope

    Raises:
        ValueError: default_scopes 非 tuple 或含非 str / 仅空白
    """
    if not isinstance(default_scopes, tuple):
        raise ValueError(
            f"default_scopes 必须是 tuple[str, ...], 实际 type={type(default_scopes).__name__}"
        )
    for idx, s in enumerate(default_scopes):
        if not isinstance(s, str):
            raise ValueError(f"default_scopes[{idx}] 必须是 str, 实际 type={type(s).__name__}")
        if not s.strip():
            raise ValueError(f"default_scopes[{idx}] 仅含空白字符, 应传非空字符串")
    return default_scopes


def _validate_code(code: Any) -> str:
    """严判 authorization code(沿 D4.7.3 公共 API 入口严判).

    Args:
        code: 用户授权后回调的授权码(一次性,通常 30s 过期)

    Returns:
        strip 后的 code 字符串

    Raises:
        ValueError: code 非 str 或仅含空白
    """
    if not isinstance(code, str):
        raise ValueError(f"code 必须是 str, 实际 type={type(code).__name__}")
    stripped = code.strip()
    if not stripped:
        raise ValueError("code 必填且必须非空字符串")
    return stripped


def _validate_refresh_token_value(refresh_token_value: Any) -> str:
    """严判 refresh_token 字符串(沿 D4.7.3 公共 API 入口严判).

    Args:
        refresh_token_value: 旧 refresh_token

    Returns:
        strip 后的 refresh_token 字符串

    Raises:
        ValueError: refresh_token_value 非 str 或仅含空白
    """
    if not isinstance(refresh_token_value, str):
        raise ValueError(
            f"refresh_token_value 必须是 str, 实际 type={type(refresh_token_value).__name__}"
        )
    stripped = refresh_token_value.strip()
    if not stripped:
        raise ValueError("refresh_token_value 必填且必须非空字符串")
    return stripped


def _google_auth_result_to_token(result: Any) -> OAuth2Token:
    """google_auth_oauthlib 返回 dict → OAuth2Token(沿 RFC 6749 §5.1 + Phase 1 OAuth2Token 数据类).

    Args:
        result: google_auth 调用返回值,含 access_token / refresh_token / expires_in / scope / token_type

    Returns:
        OAuth2Token(含 5 字段,带 `__post_init__` 双层防御严判)

    Raises:
        ValueError: result 字段缺失或类型错
        OAuth2TokenExchangeError: result 含 "error" 字段(沿 RFC 6749 §5.2)
    """
    if not isinstance(result, dict):
        raise ValueError(f"google_auth 返回值必须是 dict, 实际 type={type(result).__name__}")

    # 1. 错误响应(沿 RFC 6749 §5.2)
    if "error" in result:
        error = result.get("error", "")
        error_description = result.get("error_description", "")
        # OAuth2TokenExchangeError 是 OAuth2Error(Exception) 简单子类,无 error/description 属性
        # 错误信息全部通过 message 传递
        raise OAuth2TokenExchangeError(f"Google token 端点返回错误: {error_description or error}")

    # 2. access_token 必填
    access_token_raw = result.get("access_token", "")
    if not isinstance(access_token_raw, str) or not access_token_raw.strip():
        raise ValueError(f"google_auth 返回值必含非空 access_token, 实际 {access_token_raw!r}")

    # 3. refresh_token 可选(Google refresh 通常不返回新 refresh_token,除非 access_type=offline + prompt=consent)
    refresh_token_raw = result.get("refresh_token")

    # 4. expires_in 严判,默认 3600
    expires_in_raw = result.get("expires_in", GOOGLE_DEFAULT_EXPIRES_IN_SECONDS)
    if type(expires_in_raw) is bool or not isinstance(expires_in_raw, int) or expires_in_raw < 0:
        expires_in = GOOGLE_DEFAULT_EXPIRES_IN_SECONDS
    else:
        expires_in = expires_in_raw
    expires_at_ms = int(time.time() * 1000) + expires_in * 1000

    # 5. token_type 严判(Google 默认 "Bearer",RFC 6750)
    token_type_raw = result.get("token_type", "Bearer")
    if not isinstance(token_type_raw, str) or not token_type_raw.strip():
        token_type_raw = "Bearer"

    # 6. scope 严判(Google 返回空格分隔字符串)
    scope_raw = result.get("scope", [])
    if isinstance(scope_raw, str):
        scope_tuple: tuple[str, ...] = tuple(scope_raw.split(DEFAULT_SCOPE_SEPARATOR))
    elif isinstance(scope_raw, (list, tuple)):
        scope_tuple = tuple(s for s in scope_raw if isinstance(s, str))
    else:
        scope_tuple = ()

    # 7. 委托给 OAuth2Token(双层防御严判 + scope tuple 严判已下沉)
    return OAuth2Token(
        access_token=access_token_raw.strip(),
        refresh_token=refresh_token_raw if refresh_token_raw else None,
        expires_at_ms=expires_at_ms,
        token_type=token_type_raw.strip(),
        scope=scope_tuple,
    )


class GoogleOAuth2(OAuth2Provider):
    """Google OAuth 2.0 provider(沿 `OAuth2Provider` Protocol).

    Google Identity OAuth 2.0 + gmail SMTP / IMAP OAuth 鉴权.

    业务背景:为未来 gmail SMTP OAuth 解封准备(沿
    [[v0.2.1-candidates-2026-06-17]] §5.3).

    测试用 `google_auth_client_factory` 注入 mock,生产用真实 `google_auth_oauthlib.Flow`.

    显式继承 `OAuth2Provider` Protocol(沿 [[d4.7.3-v1.0.6-p2-3]]):
        - mypy 能识别类型契约(无需 type: ignore)
        - ruff 不报 unused import
        - IDE 跳转更友好
    """

    def __init__(
        self,
        *,
        google_auth_client_factory: Callable[..., Any] | None = None,
        default_scopes: tuple[str, ...] = GOOGLE_DEFAULT_SCOPES,
    ) -> None:
        """GoogleOAuth2 构造.

        Args:
            google_auth_client_factory: `google_auth_oauthlib.Flow` 工厂函数
                (测试用 mock 注入,生产传 None 即可,运行时内部 import google_auth_oauthlib)
            default_scopes: 默认 scope 列表(https://mail.google.com/ + userinfo.email)

        Raises:
            ValueError: default_scopes 非 tuple 或含非 str / 仅空白
        """
        self._google_auth_client_factory = google_auth_client_factory
        self._default_scopes = _validate_default_scopes(default_scopes)

    def get_auth_url(
        self,
        config: OAuth2Config,
        *,
        state: str | None = None,
    ) -> str:
        """生成 Google 授权 URL(用户浏览器跳转入口).

        沿 RFC 6749 §4.1.1 + Google Identity OAuth 2.0 文档必含:
            - client_id
            - response_type=code(Authorization Code Grant)
            - redirect_uri
            - scope(空格分隔)
            - state(防 CSRF 攻击;若 None 则自动 `generate_state()`)
            - access_type=offline(必返 refresh_token)
            - prompt=consent(强制同意页,确保 refresh_token 颁发)
            - include_granted_scopes=true(沿 Google 文档)

        Args:
            config: OAuth2Config 客户端配置
            state: 可选 state 参数(防 CSRF 攻击,推荐生成随机串)

        Returns:
            完整授权 URL(用户浏览器跳转)

        Raises:
            ValueError: config / state 严判失败
        """
        validated_config = _validate_oauth2_config(config)
        # state 必含,None 时自动 generate_state()
        if state is None:
            final_state: str = generate_state()
        else:
            final_state = _validate_state(state)

        # scope 优先用 config.scope,空时回落 default_scopes
        scope_str = validated_config.scope_string()
        if not scope_str:
            scope_str = DEFAULT_SCOPE_SEPARATOR.join(self._default_scopes)

        # 构造 URL(沿 Google Identity OAuth 2.0 文档必含 9 字段)
        params = {
            "client_id": validated_config.client_id,
            "response_type": GOOGLE_RESPONSE_TYPE_CODE,
            "redirect_uri": validated_config.redirect_uri,
            "scope": scope_str,
            "state": final_state,
            "access_type": GOOGLE_ACCESS_TYPE_OFFLINE,
            "prompt": GOOGLE_PROMPT_CONSENT,
            "include_granted_scopes": GOOGLE_INCLUDE_GRANTED_SCOPES,
        }
        query = urlencode(params)
        return f"{GOOGLE_AUTHORIZE_URL}?{query}"

    def exchange_code(
        self,
        config: OAuth2Config,
        code: str,
    ) -> OAuth2Token:
        """授权码 → access_token + refresh_token(后端回调处理).

        沿 RFC 6749 §4.1.3 + Google Identity OAuth 2.0 文档:
            - `google_auth_oauthlib.Flow.fetch_token(code=...)` POST /token 端点
            - 沿 google-auth-oauthlib 库 Flow.fetch_token(authorization_response 或 code 字符串)

        Args:
            config: OAuth2Config 客户端配置
            code: 用户授权后回调的授权码(一次性,通常 30s 过期)

        Returns:
            OAuth2Token(含 access_token / refresh_token / expires_at_ms)

        Raises:
            ValueError: config / code 严判失败
            OAuth2TokenExchangeError: code 无效 / 客户端错 / 网络错 / token 端点返回 error
        """
        validated_config = _validate_oauth2_config(config)
        validated_code = _validate_code(code)

        client = self._build_google_auth_client(validated_config)
        # 沿 [[d3.3.3-sqlcipher-integrityerror]] except 范围窄化:仅捕 google_auth/网络异常
        try:
            result: dict[str, Any] = client.fetch_token(
                token_url=GOOGLE_TOKEN_URL,
                code=validated_code,
                client_id=validated_config.client_id,
                client_secret=validated_config.client_secret,
            )
        except OAuth2Error:
            # 已是 OAuth2 异常,直接透传(不静默吞,沿 D3.3.3 范本)
            raise
        except Exception as e:
            raise OAuth2TokenExchangeError(
                f"GoogleOAuth2.exchange_code: google_auth_oauthlib.Flow.fetch_token 失败: {e!r}"
            ) from e

        # _google_auth_result_to_token 内部已含 RFC 6749 §5.2 error 字段严判
        return _google_auth_result_to_token(result)

    def refresh_token(
        self,
        config: OAuth2Config,
        refresh_token_value: str,
    ) -> OAuth2Token:
        """refresh_token → 新 access_token(后台定时刷新).

        沿 RFC 6749 §6 + Google Identity OAuth 2.0 文档:
            - `google_auth_oauthlib.Flow.fetch_token(token_url=..., refresh_token=...)`

        Args:
            config: OAuth2Config 客户端配置
            refresh_token_value: 旧 refresh_token

        Returns:
            新 OAuth2Token(access_token 必刷新,refresh_token 可能轮换)

        Raises:
            ValueError: config / refresh_token_value 严判失败
            OAuth2TokenRefreshError: refresh_token 过期 / 客户端撤销 / token 端点返回 error
        """
        validated_config = _validate_oauth2_config(config)
        validated_refresh = _validate_refresh_token_value(refresh_token_value)

        client = self._build_google_auth_client(validated_config)
        # 沿 [[d3.3.3-sqlcipher-integrityerror]] except 范围窄化
        try:
            result: dict[str, Any] = client.fetch_token(
                token_url=GOOGLE_TOKEN_URL,
                refresh_token=validated_refresh,
                client_id=validated_config.client_id,
                client_secret=validated_config.client_secret,
            )
        except OAuth2Error:
            # 已是 OAuth2 异常,直接透传
            raise
        except Exception as e:
            raise OAuth2TokenRefreshError(
                f"GoogleOAuth2.refresh_token: google_auth_oauthlib.Flow.fetch_token 失败: {e!r}"
            ) from e

        # _google_auth_result_to_token 抛 OAuth2TokenExchangeError
        # 此处需转译为 OAuth2TokenRefreshError(语义对应)
        try:
            return _google_auth_result_to_token(result)
        except OAuth2TokenExchangeError as e:
            # OAuth2TokenRefreshError 是 OAuth2Error(Exception) 简单子类,无 error 属性
            # 错误信息全部通过 message 传递
            raise OAuth2TokenRefreshError(f"Google token 端点返回错误(refresh): {e!s}") from e

    def _build_google_auth_client(self, config: OAuth2Config) -> Any:
        """构造 google_auth_oauthlib.Flow(沿 google-auth-oauthlib 库 2.23+ 文档).

        测试时用 `google_auth_client_factory` 注入 mock,生产用真实 `import google_auth_oauthlib`.

        Args:
            config: OAuth2Config 客户端配置

        Returns:
            `google_auth_oauthlib.Flow` 实例(或测试 mock)

        Raises:
            ImportError: 未注入 factory 且 google_auth_oauthlib 未安装(6/22 commit 5 加 dep)
        """
        if self._google_auth_client_factory is not None:
            return self._google_auth_client_factory(
                client_config={
                    "web": {
                        "client_id": config.client_id,
                        "client_secret": config.client_secret,
                        "auth_uri": GOOGLE_AUTHORIZE_URL,
                        "token_uri": GOOGLE_TOKEN_URL,
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [config.redirect_uri],
                    }
                },
                scopes=list(self._default_scopes),
            )

        # 函数内 import:6/19 commit 3 测试不依赖 google_auth_oauthlib,6/22 commit 5 加 dep
        import google_auth_oauthlib

        return google_auth_oauthlib.flow.Flow.from_client_config(
            client_config={
                "web": {
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "auth_uri": GOOGLE_AUTHORIZE_URL,
                    "token_uri": GOOGLE_TOKEN_URL,
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": [config.redirect_uri],
                }
            },
            scopes=list(self._default_scopes),
        )


__all__ = [
    "GOOGLE_AUTHORIZE_URL",
    "GOOGLE_TOKEN_URL",
    "GOOGLE_REVOKE_URL",
    "GOOGLE_DEFAULT_SCOPES",
    "GOOGLE_DEFAULT_EXPIRES_IN_SECONDS",
    "GOOGLE_DEFAULT_CODE_CHALLENGE_METHOD",
    "GOOGLE_ACCESS_TYPE_OFFLINE",
    "GOOGLE_PROMPT_CONSENT",
    "GOOGLE_RESPONSE_TYPE_CODE",
    "GOOGLE_INCLUDE_GRANTED_SCOPES",
    "GoogleOAuth2",
    "OAuth2TokenExchangeError",
    "OAuth2TokenRefreshError",
    # 严判 helper 暂不导出(私有 API,仅 GoogleOAuth2 内部使用)
]
