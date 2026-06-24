"""v0.2.1 #6 — OAuth 2.0 抽象层 + Keychain 集成测试(14 cases).

承接 [[v0.2.1-candidates-2026-06-17]] §6 OAuth 2.0 抽象层 + B 类决策延后声明
(独立 outlook/gmail,本轮 docs-only 抽象).

3 段测试覆盖(14 cases):
    1. OAuth2Token 数据类严判(5 tests):基本构造 / 空字符串拒绝 / bool 拒绝 / scope 类型严判 / is_expired
    2. OAuth2Config 数据类严判(4 tests):URL 格式 / redirect_uri 拒绝 / scope 类型 / endpoint URL
    3. generate_state 工具函数(2 tests):长度边界 / 唯一性
    4. Keychain 集成(3 tests):set/get/delete OAuth token + provider 严判 + JSON 序列化往返

设计原则(沿 D4.7.3 v1.0.6 + D3.3.3):
    - type() is bool 拒绝(bool 子类陷阱)
    - 公共 API 入口严判(URL / token / scope 格式)
    - 数据类 __post_init__ 双层防御
    - Keychain JSON 序列化 / 反序列化往返
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    pass


# ===== 1. OAuth2Token 数据类严判(5 tests)=====


def test_oauth2_token_basic_construction() -> Any:
    """1.1 OAuth2Token 基本构造(正常字段全过)。"""
    from my_ai_employee.core.oauth2 import OAuth2Token

    token = OAuth2Token(
        access_token="ya29.a0AfH6SMBxx",
        refresh_token="1//0gXXxx",
        expires_at_ms=1700000000000,
        scope=("https://www.googleapis.com/auth/gmail.send",),
    )
    assert token.access_token == "ya29.a0AfH6SMBxx"
    assert token.refresh_token == "1//0gXXxx"
    assert token.expires_at_ms == 1700000000000
    assert token.token_type == "Bearer"
    assert token.scope == ("https://www.googleapis.com/auth/gmail.send",)


def test_oauth2_token_rejects_empty_access_token() -> Any:
    """1.2 access_token 空字符串拒绝(双层防御严判)。"""
    from my_ai_employee.core.oauth2 import OAuth2Token

    with pytest.raises(ValueError, match="access_token 必填且必须非空字符串"):
        OAuth2Token(access_token="   ", refresh_token=None, expires_at_ms=1700000000000)


def test_oauth2_token_rejects_bool_expires() -> Any:
    """1.3 expires_at_ms=bool 拒绝(沿 D4.7.3 v1.0.4 P2-2 type() is bool 严判)。"""
    from my_ai_employee.core.oauth2 import OAuth2Token

    with pytest.raises(ValueError, match="expires_at_ms 必须是正 int"):
        OAuth2Token(access_token="ya29", refresh_token=None, expires_at_ms=True)  # type: ignore[arg-type]


def test_oauth2_token_rejects_non_string_scope() -> Any:
    """1.4 scope tuple 含非 str 元素拒绝(沿 D4.7.3 严判)。"""
    from my_ai_employee.core.oauth2 import OAuth2Token

    with pytest.raises(ValueError, match="scope.*必须是 str"):
        OAuth2Token(
            access_token="ya29",
            refresh_token=None,
            expires_at_ms=1700000000000,
            scope=("valid_scope", 123),  # type: ignore[arg-type]
        )


def test_oauth2_token_is_expired() -> Any:
    """1.5 is_expired 含 buffer 提前刷新(沿 RFC 6749 §6 行业惯例 60s buffer)。"""
    from my_ai_employee.core.oauth2 import OAuth2Token

    # 过去时间 → 已过期
    past_token = OAuth2Token(access_token="ya29", refresh_token=None, expires_at_ms=1000000000000)
    assert past_token.is_expired() is True

    # 未来时间(1 小时后)→ 未过期
    future_ms = int(time.time() * 1000) + 3600 * 1000
    future_token = OAuth2Token(access_token="ya29", refresh_token=None, expires_at_ms=future_ms)
    assert future_token.is_expired() is False


# ===== 2. OAuth2Config 数据类严判(4 tests)=====


def test_oauth2_config_basic_construction() -> Any:
    """2.1 OAuth2Config 基本构造(URL 严判全过)。"""
    from my_ai_employee.core.oauth2 import OAuth2Config

    config = OAuth2Config(
        client_id="my-app-id",
        client_secret="my-app-secret",
        redirect_uri="https://my-app.com/oauth/callback",
        scope=("https://www.googleapis.com/auth/gmail.send",),
        authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
    )
    assert config.client_id == "my-app-id"
    assert config.scope_string() == "https://www.googleapis.com/auth/gmail.send"


def test_oauth2_config_rejects_invalid_redirect_uri() -> Any:
    """2.2 redirect_uri 非 http/https 拒绝(沿 RFC 6749 §3.1.2)。"""
    from my_ai_employee.core.oauth2 import OAuth2Config

    with pytest.raises(ValueError, match="redirect_uri 必须以"):
        OAuth2Config(client_id="x", redirect_uri="ftp://invalid.com/cb")


def test_oauth2_config_rejects_non_tuple_scope() -> Any:
    """2.3 scope 非 tuple 拒绝(沿 D4.7.3 严判)。"""
    from my_ai_employee.core.oauth2 import OAuth2Config

    with pytest.raises(ValueError, match="scope 必须是 tuple"):
        OAuth2Config(
            client_id="x",
            redirect_uri="https://example.com/cb",
            scope="invalid_string",  # type: ignore[arg-type]
        )


def test_oauth2_config_scope_string_joins_with_space() -> Any:
    """2.4 scope_string 空格分隔(沿 RFC 6749 §3.3)。"""
    from my_ai_employee.core.oauth2 import OAuth2Config

    config = OAuth2Config(
        client_id="x",
        redirect_uri="https://example.com/cb",
        scope=("read", "write", "admin"),
    )
    assert config.scope_string() == "read write admin"


# ===== 3. generate_state 工具函数(2 tests)=====


def test_generate_state_length_default() -> Any:
    """3.1 generate_state 默认长度 32(防 CSRF,沿 RFC 6749 §10.12)。"""
    from my_ai_employee.core.oauth2 import generate_state

    state = generate_state()
    assert len(state) >= 32  # token_urlsafe 可能 > 32 bytes
    # 严判只含 URL-safe 字符
    assert all(
        c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in state
    )


def test_generate_state_length_validation() -> Any:
    """3.2 generate_state 长度严判 [16, 256](沿 D4.7.3 v1.0.5 P2-1 type() is bool 拒绝)。"""
    from my_ai_employee.core.oauth2 import generate_state

    with pytest.raises(ValueError, match="length 必须是"):
        generate_state(length=8)
    with pytest.raises(ValueError, match="length 必须是"):
        generate_state(length=512)
    with pytest.raises(ValueError, match="length 必须是"):
        generate_state(length=True)  # type: ignore[arg-type]


# ===== 4. Keychain 集成(3 tests)=====


def test_oauth2_token_serialization_roundtrip() -> Any:
    """4.1 OAuth2Token.to_dict / from_dict 序列化往返(用于 Keychain JSON 存储)。"""
    from my_ai_employee.core.oauth2 import OAuth2Token

    original = OAuth2Token(
        access_token="ya29.test_token",
        refresh_token="1//refresh_test",
        expires_at_ms=1700000000000,
        scope=("https://www.googleapis.com/auth/gmail.send",),
    )
    data = original.to_dict()
    json_str = json.dumps(data)
    restored = OAuth2Token.from_dict(json.loads(json_str))
    assert restored.access_token == original.access_token
    assert restored.refresh_token == original.refresh_token
    assert restored.expires_at_ms == original.expires_at_ms
    assert restored.scope == original.scope


def test_keychain_set_oauth_token_validates_provider(monkeypatch: Any) -> Any:
    """4.2 set_oauth_token provider 白名单严判(沿 D4.7.3 严判)。"""
    from my_ai_employee.core import keychain

    monkeypatch.setattr(
        keychain, "set_password", lambda *args, **kwargs: keychain.KeychainResult(ok=True)
    )

    with pytest.raises(ValueError, match="oauth_provider 必传"):
        keychain.set_oauth_token("invalid_provider", "user@example.com", "{}")
    with pytest.raises(ValueError, match="token_json 必须是 str"):
        keychain.set_oauth_token("microsoft", "user@example.com", 123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="token_json 必填"):
        keychain.set_oauth_token("microsoft", "user@example.com", "   ")


def test_keychain_get_oauth_token_validates_provider(monkeypatch: Any) -> Any:
    """4.3 get_oauth_token provider 白名单严判(沿 D4.7.3 严判)。"""
    from my_ai_employee.core import keychain

    monkeypatch.setattr(
        keychain,
        "get_password",
        lambda *args, **kwargs: keychain.KeychainResult(ok=True, value="{}"),
    )

    with pytest.raises(ValueError, match="oauth_provider 必传"):
        keychain.get_oauth_token("invalid", "user@example.com")
