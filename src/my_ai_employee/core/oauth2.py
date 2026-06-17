"""v0.2.1 #6 OAuth 2.0 抽象层 — Protocol + base + Token 数据类.

承接 [[v0.2.1-candidates-2026-06-17]] §6 OAuth 2.0 抽象层 + B 类决策延后声明
(独立 outlook/gmail,本轮 docs-only 评估不实施 provider).

业务背景:
    Gmail SMTP 自 2024 年起强制要求 OAuth 2.0 鉴权(outlook 可 App Password fallback)。
    为未来 outlook/gmail SMTP 解封(沿 [[v0.2.1-candidates-2026-06-17]] §5.3)准备 OAuth 基础。
    outlook SMTP 部分解封(4 commits)不依赖 OAuth,仍可独立推进。

本轮交付(Phase 1 docs-only 抽象):
    - OAuth2Provider Protocol(3 公开方法: get_auth_url / exchange_code / refresh_token)
    - OAuth2Token dataclass(access_token / refresh_token / expires_at_ms / scope / token_type)
    - OAuth2Config dataclass(client_id / client_secret / redirect_uri / scope)
    - OAuth2Error 异常基类(AuthorizationError / TokenExchangeError / TokenRefreshError)

Phase 2(后续 outlook/gmail 解封后实化):
    - MicrosoftOAuth2 实现(msal>=1.24,smtp.office365.com XOAUTH2)
    - GoogleOAuth2 实现(google-auth>=2.23,smtp.gmail.com XOAUTH2)
    - 测试 msal/google-auth 真实 OAuth flow(本地 mock)

D3.3.3 教训应用:
    - except 范围窄化: 拒绝捕获过宽 BaseException
    - 网络 / 鉴权错误透传(不静默吞)
    - OperationalError 风格异常传播

D4.7.3 教训应用:
    - type 严判在 hash 操作前(OAuth2Token scope 严判 list[str])
    - 公共 API 入口严判(URL / code / token 格式)
    - 数据类 __post_init__ 双层防御(frozen dataclass 校验)
    - expires_at_ms 严判 int(非 bool)>= 0
    - type() is bool 拒绝(bool 子类陷阱)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

# ===== 常量 =====

# Token 类型(沿 RFC 6749 §5.1 + RFC 6750)
TOKEN_TYPE_BEARER: str = "Bearer"

# 默认 scope 列表(沿 RFC 6749 §3.3 — space-delimited string)
DEFAULT_SCOPE_SEPARATOR: str = " "

# Token 过期提前刷新时间(60 秒,沿 OAuth 2.0 行业惯例)
DEFAULT_EXPIRY_BUFFER_SECONDS: int = 60


# ===== 异常基类 =====


class OAuth2Error(Exception):
    """OAuth 2.0 抽象层异常基类(所有 OAuth 错误继承此)。"""


class OAuth2AuthorizationError(OAuth2Error):
    """OAuth 2.0 授权失败(用户拒绝 / scope 不足 / 客户端未注册)。

    Attributes:
        error: OAuth 2.0 错误码(沿 RFC 6749 §4.1.2.1)
        error_description: 错误描述
    """

    def __init__(
        self,
        message: str,
        *,
        error: str = "",
        error_description: str = "",
    ) -> None:
        super().__init__(message)
        self.error = error
        self.error_description = error_description


class OAuth2TokenExchangeError(OAuth2Error):
    """OAuth 2.0 token 交换失败(code 无效 / client_secret 错 / 客户端类型错)。"""


class OAuth2TokenRefreshError(OAuth2Error):
    """OAuth 2.0 token 刷新失败(refresh_token 过期 / 客户端撤销)。"""


# ===== 数据类 =====


@dataclass(frozen=True)
class OAuth2Token:
    """OAuth 2.0 token 数据(沿 RFC 6749 §5.1 + RFC 6750)。

    字段:
        access_token: 访问 token(短期,通常 1 小时)
        refresh_token: 刷新 token(长期,通常 30-90 天)
        expires_at_ms: 过期 Unix 时间戳(毫秒)
        token_type: token 类型,默认 "Bearer"
        scope: 授权 scope 列表(沿 RFC 6749 §3.3)

    Raises:
        ValueError: 字段严判失败(类型 / 范围 / 空字符串)
    """

    access_token: str
    refresh_token: str | None
    expires_at_ms: int
    token_type: str = TOKEN_TYPE_BEARER
    scope: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """双层防御:严判字段类型 + 范围(沿 D4.7.3 v1.0.6 公共 API 自防御范本)。"""
        # 1. access_token 严判
        if not isinstance(self.access_token, str):
            raise ValueError(
                f"access_token 必须是 str, 实际 type={type(self.access_token).__name__}"
            )
        stripped_access = self.access_token.strip()
        if not stripped_access:
            raise ValueError("access_token 必填且必须非空字符串")
        if len(stripped_access) > 4096:
            raise ValueError(
                f"access_token 长度超过 4096 字符(防注入),实际 {len(stripped_access)} chars"
            )

        # 2. refresh_token 严判(None 允许,非 None 严判格式)
        if self.refresh_token is not None:
            if not isinstance(self.refresh_token, str):
                raise ValueError(
                    f"refresh_token 必须是 str 或 None, 实际 type={type(self.refresh_token).__name__}"
                )
            stripped_refresh = self.refresh_token.strip()
            if not stripped_refresh:
                raise ValueError("refresh_token 非空字符串必填,空字符串应传 None")

        # 3. expires_at_ms 严判(沿 D4.7.3 v1.0.4 P2-2 ms 字段严判)
        if (
            type(self.expires_at_ms) is bool
            or not isinstance(self.expires_at_ms, int)
            or self.expires_at_ms < 0
        ):
            raise ValueError(
                f"expires_at_ms 必须是正 int(非 bool),"
                f" 实际 type={type(self.expires_at_ms).__name__},"
                f" value={self.expires_at_ms!r}"
            )

        # 4. token_type 严判
        if not isinstance(self.token_type, str):
            raise ValueError(f"token_type 必须是 str, 实际 type={type(self.token_type).__name__}")
        stripped_type = self.token_type.strip()
        if not stripped_type:
            raise ValueError("token_type 必填且必须非空字符串")

        # 5. scope 严判(tuple[str, ...])
        if not isinstance(self.scope, tuple):
            raise ValueError(f"scope 必须是 tuple[str, ...], 实际 type={type(self.scope).__name__}")
        for idx, s in enumerate(self.scope):
            if not isinstance(s, str):
                raise ValueError(f"scope[{idx}] 必须是 str, 实际 type={type(s).__name__}")
            if not s.strip():
                raise ValueError(f"scope[{idx}] 仅含空白字符, 应传非空字符串")

    def is_expired(self, *, buffer_seconds: int = DEFAULT_EXPIRY_BUFFER_SECONDS) -> bool:
        """判断 token 是否过期(含 buffer 提前刷新时间)。

        Args:
            buffer_seconds: 提前刷新秒数(默认 60s)

        Returns:
            True = 已过期或即将过期 / False = 未过期
        """
        if (
            type(buffer_seconds) is bool
            or not isinstance(buffer_seconds, int)
            or buffer_seconds < 0
        ):
            raise ValueError(f"buffer_seconds 必须是正 int(非 bool), 实际 {buffer_seconds!r}")
        now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
        return now_ms >= (self.expires_at_ms - buffer_seconds * 1000)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(用于 Keychain JSON 存储)。

        Returns:
            dict 含所有字段(沿 RFC 6749 §5.1)
        """
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at_ms": self.expires_at_ms,
            "token_type": self.token_type,
            "scope": list(self.scope),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OAuth2Token:
        """从 dict 反序列化(从 Keychain 读 JSON 后构造)。

        Args:
            data: 序列化的 dict

        Returns:
            OAuth2Token 实例

        Raises:
            ValueError: data 字段缺失或类型错
        """
        if not isinstance(data, dict):
            raise ValueError(f"data 必须是 dict, 实际 type={type(data).__name__}")
        if "access_token" not in data or "expires_at_ms" not in data:
            raise ValueError(
                f"data 必含 access_token + expires_at_ms 字段, 实际 keys={list(data.keys())}"
            )
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at_ms=data["expires_at_ms"],
            token_type=data.get("token_type", TOKEN_TYPE_BEARER),
            scope=tuple(data.get("scope", ())),
        )


@dataclass(frozen=True)
class OAuth2Config:
    """OAuth 2.0 客户端配置(沿 RFC 6749 §2.2 + §2.3.1)。

    字段:
        client_id: 客户端 ID(由 OAuth 提供商颁发)
        client_secret: 客户端密钥(Confidential Client 必填,Public Client 传 "")
        redirect_uri: 授权回调 URI(沿 RFC 6749 §3.1.2)
        scope: 授权 scope 列表(空格分隔字符串或 list)
        authorization_endpoint: 授权端点(可选,默认由 provider 提供)
        token_endpoint: token 端点(可选,默认由 provider 提供)

    Raises:
        ValueError: 字段严判失败
    """

    client_id: str
    redirect_uri: str
    client_secret: str = ""
    scope: tuple[str, ...] = field(default_factory=tuple)
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None

    def __post_init__(self) -> None:
        """双层防御:严判字段格式(URL / 非空 / scope 类型)。"""
        # 1. client_id 严判
        if not isinstance(self.client_id, str):
            raise ValueError(f"client_id 必须是 str, 实际 type={type(self.client_id).__name__}")
        if not self.client_id.strip():
            raise ValueError("client_id 必填且必须非空字符串")

        # 2. redirect_uri 严判(URL 格式)
        if not isinstance(self.redirect_uri, str):
            raise ValueError(
                f"redirect_uri 必须是 str, 实际 type={type(self.redirect_uri).__name__}"
            )
        if not self.redirect_uri.startswith(("http://", "https://", "urn:ietf:wg:oauth:2.0:oob")):
            raise ValueError(
                f"redirect_uri 必须以 http:// / https:// / urn:ietf:wg:oauth:2.0:oob 开头,"
                f" 实际 {self.redirect_uri!r}"
            )

        # 3. client_secret 严判(空字符串允许,但非 str 拒绝)
        if not isinstance(self.client_secret, str):
            raise ValueError(
                f"client_secret 必须是 str, 实际 type={type(self.client_secret).__name__}"
            )

        # 4. scope 严判(tuple[str, ...])
        if not isinstance(self.scope, tuple):
            raise ValueError(f"scope 必须是 tuple[str, ...], 实际 type={type(self.scope).__name__}")
        for idx, s in enumerate(self.scope):
            if not isinstance(s, str):
                raise ValueError(f"scope[{idx}] 必须是 str, 实际 type={type(s).__name__}")

        # 5. endpoint 严判(URL 格式或 None)
        for endpoint_name, endpoint_value in [
            ("authorization_endpoint", self.authorization_endpoint),
            ("token_endpoint", self.token_endpoint),
        ]:
            if endpoint_value is None:
                continue
            if not isinstance(endpoint_value, str):
                raise ValueError(
                    f"{endpoint_name} 必须是 str 或 None, 实际 type={type(endpoint_value).__name__}"
                )
            if not endpoint_value.startswith(("http://", "https://")):
                raise ValueError(
                    f"{endpoint_name} 必须以 http:// / https:// 开头, 实际 {endpoint_value!r}"
                )

    def scope_string(self) -> str:
        """scope 列表转 RFC 6749 §3.3 空格分隔字符串。"""
        return DEFAULT_SCOPE_SEPARATOR.join(self.scope)


# ===== Protocol 抽象层 =====


@runtime_checkable
class OAuth2Provider(Protocol):
    """OAuth 2.0 provider 抽象层 Protocol(沿 RFC 6749 §4 + §5 + §6)。

    3 公开方法:
        - get_auth_url: 生成授权 URL(用户浏览器跳转)
        - exchange_code: 授权码 → access_token(后端回调)
        - refresh_token: refresh_token → 新 access_token(后台定时)

    Phase 2 后续 outlook/gmail 解封后实化 MicrosoftOAuth2 + GoogleOAuth2(本轮 docs-only 抽象)。
    """

    def get_auth_url(
        self,
        config: OAuth2Config,
        *,
        state: str | None = None,
    ) -> str:
        """生成 OAuth 2.0 授权 URL(用户浏览器跳转入口)。

        沿 RFC 6749 §4.1.1 必含:
            - response_type=code(Authorization Code Grant)
            - client_id, redirect_uri, scope, state(防 CSRF)

        Args:
            config: OAuth2Config 客户端配置
            state: 可选 state 参数(防 CSRF 攻击,推荐生成随机串)

        Returns:
            完整授权 URL(用户浏览器跳转)

        Raises:
            OAuth2AuthorizationError: 授权 URL 构造失败
        """
        ...

    def exchange_code(
        self,
        config: OAuth2Config,
        code: str,
    ) -> OAuth2Token:
        """授权码 → access_token + refresh_token(后端回调处理)。

        沿 RFC 6749 §4.1.3 POST /token 端点:
            - grant_type=authorization_code
            - code, redirect_uri, client_id, client_secret

        Args:
            config: OAuth2Config 客户端配置
            code: 用户授权后回调的授权码(一次性,通常 30s 过期)

        Returns:
            OAuth2Token(含 access_token / refresh_token / expires_at_ms)

        Raises:
            OAuth2TokenExchangeError: code 无效 / 客户端错 / 网络错
        """
        ...

    def refresh_token(
        self,
        config: OAuth2Config,
        refresh_token_value: str,
    ) -> OAuth2Token:
        """refresh_token → 新 access_token(后台定时刷新)。

        沿 RFC 6749 §6 POST /token 端点:
            - grant_type=refresh_token
            - refresh_token, client_id, client_secret

        Args:
            config: OAuth2Config 客户端配置
            refresh_token_value: 旧 refresh_token

        Returns:
            新 OAuth2Token(通常 access_token 刷新 + refresh_token 可能轮换)

        Raises:
            OAuth2TokenRefreshError: refresh_token 过期 / 客户端撤销 / 网络错
        """
        ...


# ===== 公共工具函数 =====


def generate_state(length: int = 32) -> str:
    """生成 OAuth 2.0 state 参数(防 CSRF 攻击,沿 RFC 6749 §10.12)。

    Args:
        length: 随机串长度(默认 32 字符)

    Returns:
        URL-safe 随机串(只含 [A-Za-z0-9_-])

    Raises:
        ValueError: length 越界
    """
    if type(length) is bool or not isinstance(length, int) or length < 16 or length > 256:
        raise ValueError(f"length 必须是 [16, 256] 的 int(非 bool), 实际 {length!r}")
    import secrets

    return secrets.token_urlsafe(length)


__all__ = [
    "OAuth2Error",
    "OAuth2AuthorizationError",
    "OAuth2TokenExchangeError",
    "OAuth2TokenRefreshError",
    "OAuth2Token",
    "OAuth2Config",
    "OAuth2Provider",
    "generate_state",
    "TOKEN_TYPE_BEARER",
    "DEFAULT_SCOPE_SEPARATOR",
    "DEFAULT_EXPIRY_BUFFER_SECONDS",
]
