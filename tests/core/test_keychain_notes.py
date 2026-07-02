"""Day 10 / Phase 1.1 — Notes master key Keychain 接线测试.

本测试覆盖:
    - `core/keychain.set_notes_master_key` 严判白名单(非 str / 空 / 非 hex / 过短)
    - `core/keychain.get_notes_master_key` 沿 get_password 范本(返回 KeychainResult)
    - `core/keychain.delete_notes_master_key` 不存在算成功
    - `notes_encryption._hex_to_bytes` 内部 helper 严判 hex + 长度
    - `notes_encryption.load_notes_master_key` 工厂:env UNSET → None / Keychain OK → bytes /
      Keychain 失败 → None(沿撞坑 #65 降级,不抛异常)
    - 端到端:`load_notes_master_key() + build_notes_cipher()` 集成(env ON + 32 字节
      master_key → NotesCipherImpl.is_runtime_impl=True)

撞坑防御:
    - 撞坑 #1 隐私铁律:本测试全程 mock Keychain,**绝不读真 Keychain 明文**
    - 撞坑 #64 公共 API 一致性:`KEYCHAIN_SERVICE_NOTES` 服务名复用 notes_encryption 契约
    - 撞坑 #65 opt-in 4 阶段:env UNSET → Stub / Keychain 失败 → Stub / 不抛异常
    - 撞坑 #18 5 门严判替代:严判 hex 字符 + 长度下限(32 hex chars = 16 bytes)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from _pytest.monkeypatch import MonkeyPatch

from my_ai_employee.core.keychain import (
    KeychainResult,
    delete_notes_master_key,
    get_notes_master_key,
    set_notes_master_key,
)
from my_ai_employee.core.notes_encryption import (
    KEYCHAIN_SERVICE_NOTES,
    NotesCipherImpl,
    NotesCipherStub,
    _hex_to_bytes,
    build_notes_cipher,
    load_notes_master_key,
)

# ===== TestKeychainNotesMasterKeySet =====


class TestKeychainNotesMasterKeySet:
    """`set_notes_master_key` 严判白名单 + Keychain 接线."""

    def test_set_rejects_non_string(self) -> None:
        """非 str 类型 → ValueError(撞坑 #18 5 门严判替代)."""
        with pytest.raises(ValueError, match="master_key_hex 必须是 str"):
            set_notes_master_key(b"abc123")  # type: ignore[arg-type]

    def test_set_rejects_empty_string(self) -> None:
        """空字符串 → ValueError."""
        with pytest.raises(ValueError, match="必填且必须非空字符串"):
            set_notes_master_key("")

    def test_set_rejects_whitespace_only(self) -> None:
        """仅空白 → ValueError."""
        with pytest.raises(ValueError, match="必填且必须非空字符串"):
            set_notes_master_key("   \t\n  ")

    def test_set_rejects_non_hex_characters(self) -> None:
        """非 hex 字符 → ValueError."""
        with pytest.raises(ValueError, match=r"必须只含 \[0-9a-fA-F\] hex 字符"):
            set_notes_master_key("deadbeefXYZ123")

    def test_set_rejects_too_short(self) -> None:
        """长度 < 32 hex chars(16 bytes)→ ValueError."""
        with pytest.raises(ValueError, match="至少需 32 hex chars"):
            set_notes_master_key("deadbeef")  # 8 chars < 32

    def test_set_calls_security_add_generic_password(self) -> None:
        """合法 hex → 委托给底层 set_password,KeychainResult 透传."""
        # 32 hex chars = 16 bytes(下限,实际 Impl 期望 32 bytes 但下限由严判把关)
        master_key_hex = "a" * 32
        with patch("my_ai_employee.core.keychain.set_password") as mock_set:
            mock_set.return_value = KeychainResult(ok=True)
            result = set_notes_master_key(master_key_hex)
        assert result.ok is True
        # 验证 service / account 严判
        assert mock_set.call_count == 1
        call_args = mock_set.call_args
        assert call_args[0][0] == KEYCHAIN_SERVICE_NOTES  # service
        assert call_args[0][1] == "master"  # account
        assert call_args[0][2] == master_key_hex  # password(原值透传,不做二次处理)

    def test_set_uses_notes_encryption_service_constant(self) -> None:
        """撞坑 #64 公共 API 一致性 — service 常量复用 notes_encryption 契约."""
        assert KEYCHAIN_SERVICE_NOTES == "com.myaiemployee.notes"


# ===== TestKeychainNotesMasterKeyGet =====


class TestKeychainNotesMasterKeyGet:
    """`get_notes_master_key` Keychain 读取范本."""

    def test_get_returns_keychain_result(self) -> None:
        """底层 get_password 返回 KeychainResult,函数透传."""
        expected = KeychainResult(ok=True, value="a" * 64)
        with patch(
            "my_ai_employee.core.keychain.get_password",
            return_value=expected,
        ) as mock_get:
            result = get_notes_master_key()
        assert result.ok is True
        assert result.value == expected.value
        mock_get.assert_called_once_with(KEYCHAIN_SERVICE_NOTES, "master")

    def test_get_returns_not_found(self) -> None:
        """Keychain 不存在 → KeychainResult(ok=False, error='not found')."""
        expected = KeychainResult(ok=False, error="not found")
        with patch(
            "my_ai_employee.core.keychain.get_password",
            return_value=expected,
        ) as mock_get:
            result = get_notes_master_key()
        assert result.ok is False
        assert result.error == "not found"
        mock_get.assert_called_once_with(KEYCHAIN_SERVICE_NOTES, "master")


# ===== TestKeychainNotesMasterKeyDelete =====


class TestKeychainNotesMasterKeyDelete:
    """`delete_notes_master_key` Keychain 删除范本."""

    def test_delete_calls_security_delete(self) -> None:
        """合法删除 → 底层 delete_password 透传 KeychainResult."""
        expected = KeychainResult(ok=True)
        with patch(
            "my_ai_employee.core.keychain.delete_password",
            return_value=expected,
        ) as mock_delete:
            result = delete_notes_master_key()
        assert result.ok is True
        mock_delete.assert_called_once_with(KEYCHAIN_SERVICE_NOTES, "master")


# ===== TestHexToBytesHelper =====


class TestHexToBytesHelper:
    """`_hex_to_bytes` 内部 helper 严判 hex + 长度."""

    def test_valid_64_hex_chars(self) -> None:
        """64 hex chars (32 bytes) → 32 bytes."""
        result = _hex_to_bytes("a" * 64)
        assert result is not None
        assert len(result) == 32

    def test_valid_32_hex_chars(self) -> None:
        """32 hex chars (16 bytes) → 16 bytes(下限)."""
        result = _hex_to_bytes("a" * 32)
        assert result is not None
        assert len(result) == 16

    def test_uppercase_hex_accepted(self) -> None:
        """大写 hex 也接受."""
        result = _hex_to_bytes("DEADBEEF" * 4)
        assert result is not None
        assert len(result) == 16

    def test_non_string_returns_none(self) -> None:
        """非 str → None(沿撞坑 #65 降级范本)."""
        assert _hex_to_bytes(b"deadbeef") is None  # type: ignore[arg-type]
        assert _hex_to_bytes(None) is None  # type: ignore[arg-type]

    def test_empty_string_returns_none(self) -> None:
        """空字符串 → None."""
        assert _hex_to_bytes("") is None
        assert _hex_to_bytes("   ") is None

    def test_odd_length_returns_none(self) -> None:
        """奇数长度 → None."""
        assert _hex_to_bytes("abc") is None

    def test_non_hex_chars_return_none(self) -> None:
        """非 hex 字符 → None."""
        assert _hex_to_bytes("xyz123") is None

    def test_too_short_returns_none(self) -> None:
        """< 16 bytes → None(下限)."""
        assert _hex_to_bytes("aa") is None  # 1 byte < 16
        assert _hex_to_bytes("a" * 30) is None  # 15 bytes < 16


# ===== TestLoadNotesMasterKeyFactory =====


class TestLoadNotesMasterKeyFactory:
    """`load_notes_master_key` 工厂:env 开关 + Keychain + 严判全链路."""

    def test_env_unset_returns_none_without_keychain_call(self) -> None:
        """env UNSET 时短路返回 None,不发 Keychain 请求(撞坑 #65 opt-in 4 阶段)."""
        with patch.dict("os.environ", {}, clear=False):
            # env 未设 ENABLE_NOTES_ENCRYPTION
            import os

            os.environ.pop("ENABLE_NOTES_ENCRYPTION", None)
            with patch("my_ai_employee.core.keychain.get_notes_master_key") as mock_get:
                result = load_notes_master_key()
        assert result is None
        mock_get.assert_not_called()

    def test_env_enabled_but_keychain_missing_returns_none(self, monkeypatch: MonkeyPatch) -> None:
        """env ON + Keychain 'not found' → 返回 None(降级 Stub,撞坑 #65)."""
        monkeypatch.setenv("ENABLE_NOTES_ENCRYPTION", "1")
        with patch(
            "my_ai_employee.core.keychain.get_notes_master_key",
            return_value=KeychainResult(ok=False, error="not found"),
        ):
            result = load_notes_master_key()
        assert result is None

    def test_env_enabled_keychain_ok_valid_hex_returns_bytes(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """env ON + Keychain OK + 合法 hex → 返回 bytes(>= 16 bytes)."""
        monkeypatch.setenv("ENABLE_NOTES_ENCRYPTION", "1")
        master_key_hex = "b" * 64  # 32 bytes
        with patch(
            "my_ai_employee.core.keychain.get_notes_master_key",
            return_value=KeychainResult(ok=True, value=master_key_hex),
        ):
            result = load_notes_master_key()
        assert result is not None
        assert len(result) == 32
        assert result == bytes.fromhex(master_key_hex)

    def test_env_enabled_keychain_ok_short_hex_returns_none(self, monkeypatch: MonkeyPatch) -> None:
        """env ON + Keychain OK + 长度 < 16 bytes → 返回 None(撞坑 #18 严判)."""
        monkeypatch.setenv("ENABLE_NOTES_ENCRYPTION", "1")
        # 30 chars = 15 bytes < 16
        with patch(
            "my_ai_employee.core.keychain.get_notes_master_key",
            return_value=KeychainResult(ok=True, value="a" * 30),
        ):
            result = load_notes_master_key()
        assert result is None

    def test_env_enabled_keychain_ok_invalid_hex_returns_none(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        """env ON + Keychain OK + 非 hex → 返回 None."""
        monkeypatch.setenv("ENABLE_NOTES_ENCRYPTION", "1")
        with patch(
            "my_ai_employee.core.keychain.get_notes_master_key",
            return_value=KeychainResult(ok=True, value="XYZnothex" + "a" * 24),
        ):
            result = load_notes_master_key()
        assert result is None

    def test_keychain_call_raises_returns_none(self, monkeypatch: MonkeyPatch) -> None:
        """底层异常 → 返回 None(沿撞坑 #65 降级,不抛)."""
        monkeypatch.setenv("ENABLE_NOTES_ENCRYPTION", "1")
        with patch(
            "my_ai_employee.core.keychain.get_notes_master_key",
            side_effect=RuntimeError("keychain daemon unavailable"),
        ):
            result = load_notes_master_key()
        assert result is None


# ===== TestEndToEndIntegration =====


class TestEndToEndIntegration:
    """端到端:Keychain 命中 + build_notes_cipher → NotesCipherImpl."""

    def test_keychain_master_key_yields_impl_cipher(self, monkeypatch: MonkeyPatch) -> None:
        """env ON + Keychain OK + 32-byte master_key → build_notes_cipher 返回 Impl."""
        monkeypatch.setenv("ENABLE_NOTES_ENCRYPTION", "1")
        master_key_hex = "c" * 64  # 32 bytes
        with patch(
            "my_ai_employee.core.keychain.get_notes_master_key",
            return_value=KeychainResult(ok=True, value=master_key_hex),
        ):
            cipher = build_notes_cipher(load_notes_master_key())
        assert isinstance(cipher, NotesCipherImpl)
        assert cipher.is_runtime_impl is True
        assert cipher.name == "aes-xor-256"

    def test_env_unset_yields_stub_cipher_without_keychain_call(self) -> None:
        """env UNSET → build_notes_cipher 直接 Stub,不调 Keychain(降级短路)."""
        import os

        os.environ.pop("ENABLE_NOTES_ENCRYPTION", None)
        with patch("my_ai_employee.core.keychain.get_notes_master_key") as mock_get:
            cipher = build_notes_cipher(load_notes_master_key())
        assert isinstance(cipher, NotesCipherStub)
        assert cipher.is_runtime_impl is False
        mock_get.assert_not_called()

    def test_keychain_missing_yields_stub_cipher(self, monkeypatch: MonkeyPatch) -> None:
        """env ON + Keychain 缺失 → 降级 Stub(撞坑 #65)."""
        monkeypatch.setenv("ENABLE_NOTES_ENCRYPTION", "1")
        with patch(
            "my_ai_employee.core.keychain.get_notes_master_key",
            return_value=KeychainResult(ok=False, error="not found"),
        ):
            cipher = build_notes_cipher(load_notes_master_key())
        assert isinstance(cipher, NotesCipherStub)
