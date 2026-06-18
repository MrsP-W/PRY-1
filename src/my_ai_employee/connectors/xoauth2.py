"""v0.2.2 #5 — XOAUTH2 SMTP 鉴权 helper(RFC 7628 + 4 重防误发).

承接 [[v0.2.2-p5-oauth-phase2-launch-2026-06-18]] §2.1 commit 4/5.
实现 XOAUTH2 SASL 鉴权字符串生成与解析(沿 RFC 7628),
不实际调用 smtplib(只生成 auth_string,真实 SMTP 鉴权调用留给上层 Adapter 复用).

业务背景:
    Gmail SMTP 自 2024 年起强制要求 OAuth 2.0 鉴权(无 App Password fallback).
    Outlook SMTP 推荐 OAuth 2.0(可 App Password fallback,但推荐 OAuth).
    XOAUTH2 是 OAuth 2.0 在 SMTP 协议层的鉴权机制(沿 RFC 7628).

设计要点(沿 [[v0.2.2-p5-oauth-phase2-launch-2026-06-18]] §5.3 + commit 2/3 范本):
    - XOAUTH2 顶层模块(不嵌入 connectors/smtp.py · 避免破坏 14+ import 链)
    - 复用 [[v0.2.1-oauth-abstract-layer-launch-2026-06-17]] `OAuth2Provider` Protocol
      (commit 2/3 实现的 MicrosoftOAuth2 / GoogleOAuth2 直接 inject)
    - [[d4.7.3-v1.0.6-p2-3]] 公共 API 入口严判(type / strip / 范围)
    - [[d3.3.3-sqlcipher-integrityerror]] except 范围窄化
    - [[d5.6.5-real-send]] 4 重防误发范本(env 门 + factory 注入 + 不真发 + email 校验)
    - 失败响应解析(沿 RFC 7628 §3 `{"status":"401","schemes":"bearer","scope":"..."}`)

XOAUTH2 鉴权字符串格式(RFC 7628 §3.1 — SASL XOAUTH2 initial client response):

    auth_string = base64("user=" + email + "\\x01" +
                         "auth=Bearer " + access_token + "\\x01" +
                         "\\x01")

    SMTP 鉴权命令:
        AUTH XOAUTH2 <base64-encoded-auth_string>
        AUTH XOAUTH2 <base64-encoded-auth_string> (重试一次,首次失败后)

    服务器失败响应(RFC 7628 §3.2):
        334 <base64-encoded-json>  // 失败时服务器返回 JSON 描述
        {
            "status": "401",
            "schemes": "bearer",
            "scope": "https://mail.google.com/"
        }

JSON 格式(legacy 兼容 — 部分老服务器):
    auth_string = base64('{"user":"email","access_token":"token","auth":"Bearer"}')

OAuth 端点(沿 v0.2.1 candidates §6):
    - Microsoft: smtp.office365.com:587 (STARTTLS) / 465 (SSL) · XOAUTH2
    - Google:    smtp.gmail.com:465 (SSL) · XOAUTH2

沿用范本:[[v0.2.1-oauth-abstract-layer-launch-2026-06-17]] / [[d4.7.3-v1.0.6-p2-3]] /
[[d3.3.3-sqlcipher-integrityerror]] / [[d5.6.5-real-send]] / [[b-class-deferral-2026-06-09]] /
[[v0.2.2-p5-oauth-microsoft-2026-06-18]] commit 2 / [[v0.2.2-p5-oauth-google-2026-06-18]] commit 3
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from my_ai_employee.core.oauth2 import (
    OAuth2Config,
    OAuth2Error,
    OAuth2Provider,
    OAuth2Token,
)

# ===== 常量(沿 RFC 7628 + v0.2.1 candidates §6)=====

#: XOAUTH2 SASL mechanism 名称(沿 RFC 7628 §3)
XOAUTH2_MECHANISM: Final[str] = "XOAUTH2"

#: 老格式 XOAUTH(部分老服务器沿用,非 SASL)
XOAUTH_FALLBACK_MECHANISM: Final[str] = "XOAUTH"

#: XOAUTH2 auth_string 格式(SASL 沿 RFC 7628 / JSON 沿 Google legacy)
XOAUTH2_FORMAT_SASL: Final[str] = "sasl"
XOAUTH2_FORMAT_JSON: Final[str] = "json"
XOAUTH2_FORMATS: Final[frozenset[str]] = frozenset({XOAUTH2_FORMAT_SASL, XOAUTH2_FORMAT_JSON})

#: 支持的 XOAUTH2 OAuth 2.0 provider(沿 [[b-class-deferral-2026-06-09]])
XOAUTH2_PROVIDERS: Final[frozenset[str]] = frozenset({"microsoft", "google"})

#: 真实 SMTP 网络门控(沿 [[d5.6.5-real-send]] 4 重防误发 #1)
#: - 不设置环境变量:真实网络关闭(默认)
#: - XOAUTH2_REAL_NETWORK=1:真实网络开启(显式 opt-in)
XOAUTH2_REAL_NETWORK_ENV: Final[str] = "XOAUTH2_REAL_NETWORK"
XOAUTH2_REAL_NETWORK_VALUE: Final[str] = "1"

#: SASL XOAUTH2 分隔符(沿 RFC 7628 §3.1 — 0x01 单元分隔符)
XOAUTH2_SASL_DELIMITER: Final[str] = "\x01"

#: SASL XOAUTH2 字符串拼接模板(沿 RFC 7628 §3.1)
XOAUTH2_SASL_TEMPLATE: Final[str] = "user={email}{delim}auth=Bearer {token}{delim}{delim}"

#: JSON XOAUTH2 模板(沿 Google 文档 — 老格式)
XOAUTH2_JSON_TEMPLATE: Final[str] = '{{"user":"{email}","access_token":"{token}","auth":"Bearer"}}'

#: RFC 7628 §3.2 失败状态码(常见)
XOAUTH2_STATUS_AUTH_FAILURE: Final[str] = "401"
XOAUTH2_STATUS_TEMPORARY_FAILURE: Final[str] = "4"

#: Provider 服务器配置(沿 v0.2.1 candidates §6)
#: - Microsoft: STARTTLS 587 (官方推荐) / SSL 465 (D5 范本统一 SSL)
#: - Google: SSL 465 (官方文档)
XOAUTH2_SERVERS: Final[dict[str, dict[str, Any]]] = {
    "microsoft": {
        "host": "smtp.office365.com",
        "port": 587,
        "use_ssl": False,
        "use_starttls": True,
        "mechanism": XOAUTH2_MECHANISM,
    },
    "google": {
        "host": "smtp.gmail.com",
        "port": 465,
        "use_ssl": True,
        "use_starttls": False,
        "mechanism": XOAUTH2_MECHANISM,
    },
}


# ===== 自定义异常(沿 d3.3.3 范本 — 异常细分,OperationalError 风格传播)=====


class XOAUTH2Error(Exception):
    """XOAUTH2 helper 通用异常基类(所有 XOAUTH2 错误继承此)。"""


class XOAUTH2AuthStringError(XOAUTH2Error):
    """XOAUTH2 鉴权字符串生成/解析失败(参数错 / base64 解码失败 / 格式错)。"""


class XOAUTH2EmailValidationError(XOAUTH2Error):
    """XOAUTH2 email 严判失败(非 str / 缺 @ / 纯空白)。"""


class XOAUTH2TokenValidationError(XOAUTH2Error):
    """XOAUTH2 access_token 严判失败(非 str / 纯空白 / 长度异常)。"""


class XOAUTH2ProviderError(XOAUTH2Error):
    """XOAUTH2 OAuth 2.0 provider 调用失败(exchange_code / refresh_token 异常)。

    内层透传 OAuth2Error 不静默吞(沿 [[d3.3.3-sqlcipher-integrityerror]] 范本)。
    """


class XOAUTH2RealNetworkDisabledError(XOAUTH2Error):
    """真实 SMTP 网络未开启(沿 [[d5.6.5-real-send]] 4 重防误发 #1)。

    测试环境必须显式设置 XOAUTH2_REAL_NETWORK=1 才能走真实网络。
    """


class XOAUTH2FailureResponseError(XOAUTH2Error):
    """SMTP XOAUTH2 失败响应解析失败(沿 RFC 7628 §3.2)。"""


# ===== 数据类(沿 D4.7.3 v1.0.6 双层防御)=====


@dataclass(frozen=True)
class XOAUTH2AuthString:
    """XOAUTH2 鉴权字符串数据(沿 RFC 7628 §3.1)。

    字段:
        raw: base64 编码后的鉴权字符串(可直接传给 `AUTH XOAUTH2 <raw>`)
        plain: 原始未编码字符串(测试断言用)
        format: 格式("sasl" / "json")
        email: 用户邮箱(透传,业务层用)
        access_token: access_token(透传,业务层用)

    Raises:
        ValueError: 字段严判失败
    """

    raw: str
    plain: str
    format: str
    email: str
    access_token: str

    def __post_init__(self) -> None:
        """双层防御:严判字段(沿 D4.7.3 v1.0.6 公共 API 自防御范本)。"""
        if not isinstance(self.raw, str) or not self.raw.strip():
            raise ValueError(f"raw 必填且必须非空字符串, 实际 type={type(self.raw).__name__}")
        if not isinstance(self.plain, str) or not self.plain.strip():
            raise ValueError(f"plain 必填且必须非空字符串, 实际 type={type(self.plain).__name__}")
        if self.format not in XOAUTH2_FORMATS:
            raise ValueError(f"format 必须是 {XOAUTH2_FORMATS} 之一, 实际 {self.format!r}")
        if not isinstance(self.email, str) or "@" not in self.email:
            raise ValueError(f"email 必填且必须含 @, 实际 {self.email!r}")
        if not isinstance(self.access_token, str) or not self.access_token.strip():
            raise ValueError(
                f"access_token 必填且必须非空字符串, 实际 type={type(self.access_token).__name__}"
            )


@dataclass(frozen=True)
class XOAUTH2Failure:
    """XOAUTH2 服务器失败响应(沿 RFC 7628 §3.2)。

    字段:
        status: 状态码字符串("401" / "4" 等)
        schemes: 服务器支持的鉴权 scheme 列表(如 ["bearer"])
        scope: 鉴权失败的 scope 字符串
        raw: 原始 JSON 字符串(测试断言用)
    """

    status: str
    schemes: tuple[str, ...]
    scope: str
    raw: str

    def __post_init__(self) -> None:
        """双层防御:严判字段。"""
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError(f"status 必填且必须非空字符串, 实际 type={type(self.status).__name__}")
        if not isinstance(self.schemes, tuple):
            raise ValueError(
                f"schemes 必须是 tuple[str, ...], 实际 type={type(self.schemes).__name__}"
            )
        for idx, s in enumerate(self.schemes):
            if not isinstance(s, str):
                raise ValueError(f"schemes[{idx}] 必须是 str, 实际 type={type(s).__name__}")
        if not isinstance(self.scope, str):
            raise ValueError(f"scope 必须是 str, 实际 type={type(self.scope).__name__}")
        if not isinstance(self.raw, str):
            raise ValueError(f"raw 必须是 str, 实际 type={type(self.raw).__name__}")

    def is_retryable(self) -> bool:
        """是否可重试(RFC 7628 §3.2 — 401 不可重试,4xx 瞬态可重试 1 次)。

        沿 RFC 7628 §3.2:
        - 401 (invalid credentials): 不可重试
        - 4 (transient): 可重试 1 次
        - 其他: 不可重试

        Returns:
            True = 可重试 / False = 不可重试
        """
        return self.status == XOAUTH2_STATUS_TEMPORARY_FAILURE


# ===== 严判 helper(沿 d4.7.3 v1.0.6 公共 API 入口严判)=====


def _validate_email(email: Any) -> str:
    """严判 email(沿 D4.7.3 公共 API 入口严判)。

    Args:
        email: 用户邮箱地址

    Returns:
        strip 后的 email 字符串

    Raises:
        XOAUTH2EmailValidationError: email 非 str / 缺 @ / 仅含空白
    """
    if not isinstance(email, str):
        raise XOAUTH2EmailValidationError(f"email 必须是 str, 实际 type={type(email).__name__}")
    stripped = email.strip()
    if not stripped:
        raise XOAUTH2EmailValidationError("email 必填且必须非空字符串(沿 RFC 5321 邮件地址格式)")
    if "@" not in stripped:
        raise XOAUTH2EmailValidationError(f"email 必须含 @, 实际 {stripped!r}")
    if len(stripped) > 320:
        # RFC 5321 邮件地址最大长度 320
        raise XOAUTH2EmailValidationError(
            f"email 长度超过 320 字符(RFC 5321 上限), 实际 {len(stripped)} chars"
        )
    return stripped


def _validate_access_token(access_token: Any) -> str:
    """严判 access_token(沿 D4.7.3 公共 API 入口严判)。

    Args:
        access_token: OAuth 2.0 access_token

    Returns:
        strip 后的 access_token 字符串

    Raises:
        XOAUTH2TokenValidationError: token 非 str / 仅含空白 / 长度异常
    """
    if not isinstance(access_token, str):
        raise XOAUTH2TokenValidationError(
            f"access_token 必须是 str, 实际 type={type(access_token).__name__}"
        )
    stripped = access_token.strip()
    if not stripped:
        raise XOAUTH2TokenValidationError("access_token 必填且必须非空字符串")
    if len(stripped) > 4096:
        # OAuth 2.0 access_token 实际长度通常 32-2048,4096 留 buffer
        raise XOAUTH2TokenValidationError(
            f"access_token 长度超过 4096 字符(防注入), 实际 {len(stripped)} chars"
        )
    return stripped


def _validate_format(format_value: Any) -> str:
    """严鉴权字符串格式。

    Args:
        format_value: 格式字符串("sasl" / "json")

    Returns:
        严判后的格式字符串

    Raises:
        XOAUTH2AuthStringError: format_value 不在 XOAUTH2_FORMATS 白名单
    """
    if not isinstance(format_value, str):
        raise XOAUTH2AuthStringError(f"format 必须是 str, 实际 type={type(format_value).__name__}")
    if format_value not in XOAUTH2_FORMATS:
        raise XOAUTH2AuthStringError(
            f"format 必须是 {sorted(XOAUTH2_FORMATS)} 之一, 实际 {format_value!r}"
        )
    return format_value


def _validate_provider(provider: Any) -> str:
    """严判 provider(沿 D4.7.3 公共 API 入口严判)。

    Args:
        provider: provider 字符串("microsoft" / "google")

    Returns:
        严判后的 provider 字符串

    Raises:
        XOAUTH2ProviderError: provider 不在 XOAUTH2_PROVIDERS 白名单
    """
    if not isinstance(provider, str):
        raise XOAUTH2ProviderError(f"provider 必须是 str, 实际 type={type(provider).__name__}")
    if provider not in XOAUTH2_PROVIDERS:
        raise XOAUTH2ProviderError(
            f"provider 必须是 {sorted(XOAUTH2_PROVIDERS)} 之一, 实际 {provider!r}"
        )
    return provider


def _is_real_network_enabled() -> bool:
    """检测真实 SMTP 网络是否开启(沿 [[d5.6.5-real-send]] 4 重防误发 #1)。

    Returns:
        True = 真实网络开启 / False = 真实网络关闭(默认)
    """
    return os.environ.get(XOAUTH2_REAL_NETWORK_ENV) == XOAUTH2_REAL_NETWORK_VALUE


# ===== 鉴权字符串生成 / 解析(沿 RFC 7628 §3)=====


def build_xoauth2_auth_string(
    email: str,
    access_token: str,
    *,
    format: str = XOAUTH2_FORMAT_SASL,  # noqa: A002 — 沿 RFC 7628 术语 "format"
) -> XOAUTH2AuthString:
    """生成 XOAUTH2 鉴权字符串(沿 RFC 7628 §3.1 SASL 初始客户端响应)。

    Args:
        email: 用户邮箱地址(必含 @)
        access_token: OAuth 2.0 access_token
        format: 鉴权字符串格式("sasl" 默认 / "json" legacy)

    Returns:
        XOAUTH2AuthString(raw / plain / format / email / access_token)

    Raises:
        XOAUTH2EmailValidationError: email 严判失败
        XOAUTH2TokenValidationError: access_token 严判失败
        XOAUTH2AuthStringError: format 严判失败

    Examples:
        SASL(RFC 7628 默认):
            >>> auth = build_xoauth2_auth_string(
            ...     email="user@example.com",
            ...     access_token="ya29.xx",
            ... )
            >>> auth.format
            'sasl'
            >>> base64.b64decode(auth.raw).decode()
            'user=user@example.com\\x01auth=Bearer ya29.xx\\x01\\x01'
        JSON(legacy):
            >>> auth = build_xoauth2_auth_string(
            ...     email="user@example.com",
            ...     access_token="ya29.xx",
            ...     format="json",
            ... )
            >>> base64.b64decode(auth.raw).decode()
            '{"user":"user@example.com","access_token":"ya29.xx","auth":"Bearer"}'
    """
    validated_email = _validate_email(email)
    validated_token = _validate_access_token(access_token)
    validated_format = _validate_format(format)

    if validated_format == XOAUTH2_FORMAT_SASL:
        # SASL XOAUTH2(沿 RFC 7628 §3.1)
        plain = XOAUTH2_SASL_TEMPLATE.format(
            email=validated_email,
            token=validated_token,
            delim=XOAUTH2_SASL_DELIMITER,
        )
    else:
        # JSON XOAUTH2(legacy 兼容)
        plain = XOAUTH2_JSON_TEMPLATE.format(
            email=validated_email,
            token=validated_token,
        )

    # base64 编码(SMTP 协议要求)
    raw = base64.b64encode(plain.encode("utf-8")).decode("ascii")

    return XOAUTH2AuthString(
        raw=raw,
        plain=plain,
        format=validated_format,
        email=validated_email,
        access_token=validated_token,
    )


def parse_xoauth2_auth_string(raw: str) -> tuple[str, str, str]:
    """解析 XOAUTH2 鉴权字符串(沿 RFC 7628 §3.1 单元分隔符 0x01 拆分)。

    Args:
        raw: base64 编码后的 XOAUTH2 鉴权字符串

    Returns:
        (email, access_token, format) 三元组

    Raises:
        XOAUTH2AuthStringError: 解析失败(base64 / 格式错)

    Examples:
        >>> raw = base64.b64encode(
        ...     b"user=user@example.com\\x01auth=Bearer ya29.xx\\x01\\x01"
        ... ).decode()
        >>> parse_xoauth2_auth_string(raw)
        ('user@example.com', 'ya29.xx', 'sasl')
    """
    if not isinstance(raw, str) or not raw.strip():
        raise XOAUTH2AuthStringError(f"raw 必填且必须非空字符串, 实际 type={type(raw).__name__}")
    try:
        plain_bytes = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as e:
        raise XOAUTH2AuthStringError(f"XOAUTH2 raw 不是有效 base64: {e!r}") from e

    plain = plain_bytes.decode("utf-8", errors="replace")

    # JSON 格式优先检测(以 '{' 开头)
    if plain.startswith("{"):
        try:
            obj = json.loads(plain)
        except json.JSONDecodeError as e:
            raise XOAUTH2AuthStringError(f"XOAUTH2 JSON 格式解析失败: {e!r}") from e
        if not isinstance(obj, dict):
            raise XOAUTH2AuthStringError(
                f"XOAUTH2 JSON 必须是 dict, 实际 type={type(obj).__name__}"
            )
        email = obj.get("user", "")
        token = obj.get("access_token", "")
        if not email or not token:
            raise XOAUTH2AuthStringError(
                f"XOAUTH2 JSON 必含 user + access_token 字段, 实际 keys={list(obj.keys())}"
            )
        return (str(email), str(token), XOAUTH2_FORMAT_JSON)

    # SASL 格式(沿 RFC 7628 §3.1 单元分隔符 0x01)
    parts = plain.split(XOAUTH2_SASL_DELIMITER)
    # SASL 模板: user=email \x01 auth=Bearer token \x01 \x01
    # 拆分结果应至少 3 段(最后一段空字符串因 \x01\x01)
    if len(parts) < 3:
        raise XOAUTH2AuthStringError(f"XOAUTH2 SASL 格式错(应至少 3 段), 实际 {len(parts)} 段")

    user_part = parts[0]
    auth_part = parts[1]

    if not user_part.startswith("user="):
        raise XOAUTH2AuthStringError(f"XOAUTH2 SASL 第一段必须以 'user=' 开头, 实际 {user_part!r}")
    email = user_part[5:]  # 去除 "user=" 前缀

    if not auth_part.startswith("auth=Bearer "):
        raise XOAUTH2AuthStringError(
            f"XOAUTH2 SASL 第二段必须以 'auth=Bearer ' 开头, 实际 {auth_part!r}"
        )
    access_token = auth_part[len("auth=Bearer ") :]

    if not email or not access_token:
        raise XOAUTH2AuthStringError(
            f"XOAUTH2 SASL email 或 access_token 为空: email={email!r} token={access_token!r}"
        )
    return (email, access_token, XOAUTH2_FORMAT_SASL)


def parse_xoauth2_failure_response(server_response: str) -> XOAUTH2Failure:
    """解析 SMTP XOAUTH2 服务器失败响应(沿 RFC 7628 §3.2)。

    Args:
        server_response: 服务器返回的 base64 编码 JSON 字符串

    Returns:
        XOAUTH2Failure(status / schemes / scope / raw)

    Raises:
        XOAUTH2FailureResponseError: 解析失败(base64 / JSON / 字段缺失)

    Examples:
        >>> import base64
        >>> raw = base64.b64encode(
        ...     b'{"status":"401","schemes":"bearer","scope":"https://mail.google.com/"}'
        ... ).decode()
        >>> failure = parse_xoauth2_failure_response(raw)
        >>> failure.status
        '401'
        >>> failure.is_retryable()
        False
    """
    if not isinstance(server_response, str) or not server_response.strip():
        raise XOAUTH2FailureResponseError(
            f"server_response 必填且必须非空字符串, 实际 type={type(server_response).__name__}"
        )
    try:
        plain_bytes = base64.b64decode(server_response, validate=True)
    except (ValueError, TypeError) as e:
        raise XOAUTH2FailureResponseError(f"XOAUTH2 failure response 不是有效 base64: {e!r}") from e

    plain = plain_bytes.decode("utf-8", errors="replace")
    try:
        obj = json.loads(plain)
    except json.JSONDecodeError as e:
        raise XOAUTH2FailureResponseError(f"XOAUTH2 failure response 不是有效 JSON: {e!r}") from e

    if not isinstance(obj, dict):
        raise XOAUTH2FailureResponseError(
            f"XOAUTH2 failure response 必须是 dict, 实际 type={type(obj).__name__}"
        )

    status = str(obj.get("status", ""))
    if not status:
        raise XOAUTH2FailureResponseError(
            f"XOAUTH2 failure response 必含 status 字段, 实际 keys={list(obj.keys())}"
        )

    schemes_raw = obj.get("schemes", [])
    if isinstance(schemes_raw, str):
        schemes_tuple: tuple[str, ...] = tuple(schemes_raw.split())
    elif isinstance(schemes_raw, (list, tuple)):
        schemes_tuple = tuple(s for s in schemes_raw if isinstance(s, str))
    else:
        schemes_tuple = ()

    scope = str(obj.get("scope", ""))

    return XOAUTH2Failure(
        status=status,
        schemes=schemes_tuple,
        scope=scope,
        raw=server_response,
    )


# ===== XOAUTH2Authenticator — 4 重防误发范本(沿 d5.6.5-real-send)=====


class XOAUTH2Authenticator:
    """XOAUTH2 鉴权字符串生成器(沿 [[d5.6.5-real-send]] 4 重防误发)。

    4 重防误发(沿 D5.6.5 / D5.6.5.1 范本):
        1. **env 门**:`XOAUTH2_REAL_NETWORK=1` 显式开启(默认关闭)
        2. **factory 注入**:`oauth2_provider_factory` 测试 mock,生产传 None
        3. **不真发邮件**:helper 只生成 auth_string,不调 smtplib
        4. **email 严判**:必含 @,strip 后非空,RFC 5321 长度上限 320

    业务背景:为未来 outlook/gmail SMTP OAuth 解封准备(沿
    [[v0.2.1-candidates-2026-06-17]] §5.3).
    B 类决策延后:outlook/gmail SMTP provider 单独门控启动.

    复用要点:
        - [[v0.2.1-oauth-abstract-layer-launch-2026-06-17]] `OAuth2Provider` Protocol
        - [[v0.2.2-p5-oauth-microsoft-2026-06-18]] commit 2 `MicrosoftOAuth2`
        - [[v0.2.2-p5-oauth-google-2026-06-18]] commit 3 `GoogleOAuth2`

    用法(生产):
        auth = XOAUTH2Authenticator(provider="microsoft", oauth2_provider=MicrosoftOAuth2())
        token = auth.oauth2_provider.exchange_code(config, code)
        auth_string = auth.build_auth_string(email="user@outlook.com", access_token=token.access_token)
        # 真实 SMTP 鉴权调用 smtplib(由上层 Adapter 处理,本 helper 不做)

    用法(测试):
        mock_provider = MagicMock(spec=OAuth2Provider)
        mock_provider.exchange_code.return_value = OAuth2Token(
            access_token="ya29.xx", refresh_token=None, expires_at_ms=...
        )
        auth = XOAUTH2Authenticator(provider="google", oauth2_provider=mock_provider)
        auth_string = auth.build_auth_string(email="user@gmail.com", access_token="ya29.xx")
    """

    def __init__(
        self,
        *,
        provider: str,
        oauth2_provider: OAuth2Provider | None = None,
        oauth2_provider_factory: Callable[..., OAuth2Provider] | None = None,
        format: str = XOAUTH2_FORMAT_SASL,  # noqa: A002 — 沿 RFC 7628 术语
    ) -> None:
        """XOAUTH2Authenticator 构造.

        Args:
            provider: provider 字符串("microsoft" / "google")
            oauth2_provider: OAuth2Provider 实例(直接注入,生产用)
            oauth2_provider_factory: OAuth2Provider 工厂函数(测试用,延迟构造)
            format: 鉴权字符串格式("sasl" 默认 / "json" legacy)

        Raises:
            XOAUTH2ProviderError: provider 不在白名单
            XOAUTH2AuthStringError: format 不在白名单
        """
        self._provider = _validate_provider(provider)
        self._format = _validate_format(format)
        # 4 重防误发 #2:factory 注入 — 仅一个,oauth2_provider 优先
        self._oauth2_provider = oauth2_provider
        self._oauth2_provider_factory = oauth2_provider_factory
        if oauth2_provider is not None and oauth2_provider_factory is not None:
            # 双注入是配置错误,严判防误用(沿 D4.7.3 公共 API 入口严判)
            raise XOAUTH2ProviderError("oauth2_provider 与 oauth2_provider_factory 不能同时传入")

    @property
    def provider(self) -> str:
        """provider 字符串(只读)。"""
        return self._provider

    @property
    def format(self) -> str:
        """鉴权字符串格式(只读)。"""
        return self._format

    @property
    def server_config(self) -> dict[str, Any]:
        """provider 服务器配置(只读,沿 XOAUTH2_SERVERS)。"""
        return XOAUTH2_SERVERS[self._provider]

    @property
    def oauth2_provider(self) -> OAuth2Provider | None:
        """OAuth2Provider 实例(只读,可能为 None 需 factory 延迟构造)。"""
        return self._oauth2_provider

    def get_oauth2_provider(self) -> OAuth2Provider:
        """获取 OAuth2Provider 实例(4 重防误发 #2:factory 延迟构造)。

        Returns:
            OAuth2Provider 实例

        Raises:
            XOAUTH2ProviderError: 未注入 oauth2_provider 且未注入 factory
        """
        if self._oauth2_provider is not None:
            return self._oauth2_provider
        if self._oauth2_provider_factory is not None:
            # 沿 D4.7.3 v1.0.3 is None 范本:is None 不用 or 保留 falsey 替身
            provider = self._oauth2_provider_factory()
            if not isinstance(provider, OAuth2Provider):
                raise XOAUTH2ProviderError(
                    f"oauth2_provider_factory 必返回 OAuth2Provider 实例, "
                    f"实际 type={type(provider).__name__}"
                )
            return provider
        raise XOAUTH2ProviderError(
            "未注入 oauth2_provider 或 oauth2_provider_factory,"
            f"无法获取 provider={self._provider!r} 的 OAuth2Provider"
        )

    def build_auth_string(
        self,
        email: str,
        access_token: str,
        *,
        format: str | None = None,  # noqa: A002 — 沿 RFC 7628 术语
    ) -> XOAUTH2AuthString:
        """生成 XOAUTH2 鉴权字符串(沿 RFC 7628 §3.1)。

        4 重防误发 #3:helper 只生成 auth_string,不调 smtplib,真实网络关闭也允许生成。

        Args:
            email: 用户邮箱地址
            access_token: OAuth 2.0 access_token
            format: 可选覆盖构造时 format

        Returns:
            XOAUTH2AuthString 数据类

        Raises:
            XOAUTH2EmailValidationError: email 严判失败
            XOAUTH2TokenValidationError: access_token 严判失败
            XOAUTH2AuthStringError: format 严判失败
        """
        actual_format = format if format is not None else self._format
        return build_xoauth2_auth_string(
            email=email,
            access_token=access_token,
            format=actual_format,
        )

    def assert_real_network_enabled(self) -> None:
        """断言真实 SMTP 网络已开启(4 重防误发 #1:env 门)。

        生产环境必须显式设置 `XOAUTH2_REAL_NETWORK=1` 才能走真实 SMTP。
        测试环境默认关闭,避免误连真实 outlook/gmail 服务器。

        Raises:
            XOAUTH2RealNetworkDisabledError: 真实网络未开启(测试环境默认)

        Examples:
            # 测试:helper.build_auth_string() 允许(不调 smtplib)
            # 真实 SMTP 鉴权调用:必须先 assert_real_network_enabled()
        """
        if not _is_real_network_enabled():
            raise XOAUTH2RealNetworkDisabledError(
                f"真实 SMTP 网络未开启,需设置 {XOAUTH2_REAL_NETWORK_ENV}={XOAUTH2_REAL_NETWORK_VALUE}"
            )

    def build_auth_string_via_oauth2_provider(
        self,
        config: OAuth2Config,
        code: str,
        user_email: str,
    ) -> XOAUTH2AuthString:
        """通过 OAuth2Provider 兑换 code → access_token → 鉴权字符串(端到端)。

        复用 [[v0.2.2-p5-oauth-microsoft-2026-06-18]] commit 2 / commit 3
        的 MicrosoftOAuth2 / GoogleOAuth2.

        Args:
            config: OAuth2Config 客户端配置
            code: 用户授权后回调的授权码(一次性,通常 30s 过期)
            user_email: 用户邮箱地址(OAuth 2.0 token 不含 user email,需外部传入)

        Returns:
            XOAUTH2AuthString(已含 access_token)

        Raises:
            ValueError: config 严判失败(委托给 OAuth2Config)
            OAuth2TokenExchangeError: code 无效(沿 RFC 6749 §4.1.3)
            XOAUTH2AuthStringError: 鉴权字符串生成失败
            XOAUTH2EmailValidationError: user_email 严判失败
            XOAUTH2TokenValidationError: access_token 严判失败

        Note:
            本方法调用 OAuth2Provider.exchange_code() 涉及真实 OAuth 2.0 token
            端点请求,仅供生产 spike 使用。单元测试需 mock OAuth2Provider。
        """
        if not isinstance(config, OAuth2Config):
            raise ValueError(f"config 必须是 OAuth2Config 实例, 实际 type={type(config).__name__}")
        # user_email 必须先严判(沿 4 重防误发 #4 — email 校验)
        validated_email = _validate_email(user_email)
        provider = self.get_oauth2_provider()
        # 沿 [[d3.3.3-sqlcipher-integrityerror]] except 范围窄化
        try:
            token: OAuth2Token = provider.exchange_code(config, code)
        except OAuth2Error:
            # 已是 OAuth2 异常,直接透传(不静默吞)
            raise
        except Exception as e:
            raise XOAUTH2ProviderError(
                f"XOAUTH2Authenticator: OAuth2Provider.exchange_code 失败: {e!r}"
            ) from e

        return self.build_auth_string(
            email=validated_email,
            access_token=token.access_token,
        )

    def build_auth_string_via_refresh(
        self,
        config: OAuth2Config,
        refresh_token_value: str,
        user_email: str,
    ) -> XOAUTH2AuthString:
        """通过 OAuth2Provider 刷新 access_token → 鉴权字符串(后台刷新用)。

        复用 commit 2/3 `refresh_token` 方法。

        Args:
            config: OAuth2Config 客户端配置
            refresh_token_value: 旧 refresh_token
            user_email: 用户邮箱地址(OAuth 2.0 token 不含 user email,需外部传入)

        Returns:
            XOAUTH2AuthString(已含新 access_token)

        Raises:
            ValueError: config 严判失败
            OAuth2TokenRefreshError: refresh_token 过期(沿 RFC 6749 §6)
            XOAUTH2AuthStringError: 鉴权字符串生成失败
            XOAUTH2EmailValidationError: user_email 严判失败
            XOAUTH2TokenValidationError: access_token 严判失败
        """
        if not isinstance(config, OAuth2Config):
            raise ValueError(f"config 必须是 OAuth2Config 实例, 实际 type={type(config).__name__}")
        validated_email = _validate_email(user_email)
        provider = self.get_oauth2_provider()
        # 沿 [[d3.3.3-sqlcipher-integrityerror]] except 范围窄化
        try:
            token: OAuth2Token = provider.refresh_token(config, refresh_token_value)
        except OAuth2Error:
            # 已是 OAuth2 异常,直接透传
            raise
        except Exception as e:
            raise XOAUTH2ProviderError(
                f"XOAUTH2Authenticator: OAuth2Provider.refresh_token 失败: {e!r}"
            ) from e

        return self.build_auth_string(
            email=validated_email,
            access_token=token.access_token,
        )


__all__ = [
    # 常量
    "XOAUTH2_MECHANISM",
    "XOAUTH_FALLBACK_MECHANISM",
    "XOAUTH2_FORMAT_SASL",
    "XOAUTH2_FORMAT_JSON",
    "XOAUTH2_FORMATS",
    "XOAUTH2_PROVIDERS",
    "XOAUTH2_REAL_NETWORK_ENV",
    "XOAUTH2_REAL_NETWORK_VALUE",
    "XOAUTH2_SASL_DELIMITER",
    "XOAUTH2_SASL_TEMPLATE",
    "XOAUTH2_JSON_TEMPLATE",
    "XOAUTH2_STATUS_AUTH_FAILURE",
    "XOAUTH2_STATUS_TEMPORARY_FAILURE",
    "XOAUTH2_SERVERS",
    # 异常
    "XOAUTH2Error",
    "XOAUTH2AuthStringError",
    "XOAUTH2EmailValidationError",
    "XOAUTH2TokenValidationError",
    "XOAUTH2ProviderError",
    "XOAUTH2RealNetworkDisabledError",
    "XOAUTH2FailureResponseError",
    # 数据类
    "XOAUTH2AuthString",
    "XOAUTH2Failure",
    # 公开 API
    "build_xoauth2_auth_string",
    "parse_xoauth2_auth_string",
    "parse_xoauth2_failure_response",
    "XOAUTH2Authenticator",
    # 私有 helper 不导出(仅模块内使用)
]
