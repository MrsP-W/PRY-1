"""v0.2.57 / Day 8 候选 D — Notes 加密增强测试.

本测试覆盖:
    - NotesCipherStub 默认明文透传(无 `enc:` 前缀)
    - NotesCipherImpl 加密 + 解密 round-trip(认证密文前缀 `enc:v2:`)
    - 同一字段 + 同一 key + 同一明文 → 密文每次不同(随机 IV)
    - 同一字段 + 同一 key + 同一密文 → 解密必得到原明文
    - 解密失败 → 返回 None(不抛异常)
    - 不含前缀的 ciphertext → 视为明文 fallback
    - fingerprint SHA-256 截 32 chars(Stub + Impl 一致)
    - max_length 严判
    - opt-in 开关 ENABLE_NOTES_ENCRYPTION 严判
    - 工厂函数 build_notes_cipher(默认 Stub / 启用时 Impl)
    - 撞坑 #1 隐私铁律:不依赖 Keychain 明文

撞坑 #64 公共 API 一致性 + 撞坑 #65 opt-in 4 阶段 + 撞坑 #71 解除。
"""

from __future__ import annotations

import os

import pytest

from my_ai_employee.core.notes_encryption import (
    _CIPHERTEXT_PREFIX_V1,
    _CIPHERTEXT_PREFIX_V2,
    _FINGERPRINT_LENGTH,
    DEFAULT_NOTES_FIELDS,
    ENABLE_NOTES_ENCRYPTION_ENV,
    NotesCipherImpl,
    NotesCipherStub,
    NotesFieldCipher,
    build_notes_cipher,
    get_default_stub,
    is_notes_encryption_enabled,
)

# ===== 单元: NotesCipherStub =====


class TestNotesCipherStub:
    """NotesCipherStub 默认明文透传测试."""

    def test_stub_is_default(self) -> None:
        """NotesCipherStub.is_runtime_impl = False(沿 v0.2.53.30 严判)."""
        stub = get_default_stub()
        assert stub.is_runtime_impl is False
        assert stub.name == "stub"

    def test_stub_encrypt_returns_plaintext(self) -> None:
        """Stub 加密 = 明文透传(无前缀)."""
        stub = get_default_stub()
        field = NotesFieldCipher(field_name="body")
        result = stub.encrypt("hello world", field)
        assert result == "hello world"
        assert not result.startswith("enc:")

    def test_stub_decrypt_returns_ciphertext(self) -> None:
        """Stub 只透传明文；声明为密文的值必须 fail-closed。"""
        stub = get_default_stub()
        field = NotesFieldCipher(field_name="body")
        result = stub.decrypt("hello world", field)
        assert result == "hello world"
        assert stub.decrypt(_CIPHERTEXT_PREFIX_V2 + "00", field) is None

    def test_stub_fingerprint_32_chars(self) -> None:
        """Stub 指纹 = SHA-256 截 32 chars(沿 core/fingerprint.py 范本)."""
        stub = get_default_stub()
        fp = stub.fingerprint("hello world")
        assert len(fp) == _FINGERPRINT_LENGTH
        # 同一明文 → 同一指纹(确定性)
        assert fp == stub.fingerprint("hello world")

    def test_stub_fingerprint_different_for_different_input(self) -> None:
        """不同明文 → 不同指纹(撞坑 #1 隐私性)."""
        stub = get_default_stub()
        fp1 = stub.fingerprint("hello world")
        fp2 = stub.fingerprint("goodbye world")
        assert fp1 != fp2

    def test_stub_encrypt_rejects_non_string(self) -> None:
        """Stub encrypt 严判 plaintext 必须 str."""
        stub = get_default_stub()
        field = NotesFieldCipher(field_name="body")
        with pytest.raises(ValueError, match="plaintext 必须为 str"):
            stub.encrypt(123, field)  # type: ignore[arg-type]

    def test_stub_encrypt_rejects_too_long(self) -> None:
        """Stub encrypt 严判 max_length."""
        stub = get_default_stub()
        field = NotesFieldCipher(field_name="body", max_length=10)
        with pytest.raises(ValueError, match="明文超长"):
            stub.encrypt("a" * 100, field)


# ===== 单元: NotesCipherImpl =====


@pytest.fixture
def impl() -> NotesCipherImpl:
    """测试用 Impl(固定 master_key 32 字节)."""
    return NotesCipherImpl(master_key=b"x" * 32)


class TestNotesCipherImpl:
    """NotesCipherImpl 真实加密测试."""

    def test_impl_is_runtime(self) -> None:
        """Impl.is_runtime_impl = True(沿 v0.2.53.30 严判)."""
        impl = NotesCipherImpl(master_key=b"x" * 32)
        assert impl.is_runtime_impl is True
        assert impl.name == "aes-xor-256"

    def test_impl_accepts_minimum_length_master_key(self) -> None:
        """恰好 16 bytes 的合法主密钥可直构并完成加解密回环。"""
        minimum_key_impl = NotesCipherImpl(master_key=b"k" * 16)
        field = NotesFieldCipher(field_name="body")
        ciphertext = minimum_key_impl.encrypt("minimum-key-boundary", field)
        assert minimum_key_impl.decrypt(ciphertext, field) == "minimum-key-boundary"

    def test_impl_encrypt_has_prefix(self, impl: NotesCipherImpl) -> None:
        """Impl 加密结果必须含认证的 `enc:v2:` 前缀(版本化)."""
        field = NotesFieldCipher(field_name="body")
        result = impl.encrypt("hello world", field)
        assert result.startswith(_CIPHERTEXT_PREFIX_V2)

    def test_impl_decrypt_round_trip(self, impl: NotesCipherImpl) -> None:
        """加密 → 解密 = 原文(round-trip 不变)."""
        field = NotesFieldCipher(field_name="body")
        plaintext = "Day 8 候选 D 测试明文 — 含中文 & emoji 🎉"
        ciphertext = impl.encrypt(plaintext, field)
        decrypted = impl.decrypt(ciphertext, field)
        assert decrypted == plaintext

    def test_impl_encrypt_random_iv(self, impl: NotesCipherImpl) -> None:
        """同一明文 + 同一 key → 密文每次不同(随机 IV)."""
        field = NotesFieldCipher(field_name="body")
        plaintext = "相同明文"
        c1 = impl.encrypt(plaintext, field)
        c2 = impl.encrypt(plaintext, field)
        assert c1 != c2
        # 但 round-trip 都成功
        assert impl.decrypt(c1, field) == plaintext
        assert impl.decrypt(c2, field) == plaintext

    def test_impl_decrypt_plaintext_fallback(self, impl: NotesCipherImpl) -> None:
        """不含 `enc:` 前缀 → 视为明文 fallback(撞坑 #65 兼容旧数据)."""
        field = NotesFieldCipher(field_name="body")
        # 旧数据:无前缀,直接返回
        assert impl.decrypt("旧数据明文", field) == "旧数据明文"

    def test_impl_decrypt_invalid_or_unauthenticated_returns_none(
        self, impl: NotesCipherImpl
    ) -> None:
        """格式错、篡改、错字段或错密钥均不得返回伪明文。"""
        field = NotesFieldCipher(field_name="body")
        # 前缀对,但 hex 长度不够
        result = impl.decrypt(_CIPHERTEXT_PREFIX_V2 + "abcd", field)
        assert result is None
        # 非法 hex
        result = impl.decrypt(_CIPHERTEXT_PREFIX_V2 + "zzzz", field)
        assert result is None
        # 未认证 v1 与未知版本均不能被降级为明文。
        assert impl.decrypt(_CIPHERTEXT_PREFIX_V1 + "00" * 64, field) is None
        assert impl.decrypt("enc:v3:" + "00" * 64, field) is None

        ciphertext = impl.encrypt("authenticated payload", field)
        raw = bytearray(bytes.fromhex(ciphertext[len(_CIPHERTEXT_PREFIX_V2) :]))
        # 覆盖 salt、IV、ciphertext 与 tag 四类篡改位置。
        for index in (0, 16, 32, len(raw) - 1):
            tampered = bytearray(raw)
            tampered[index] ^= 1
            assert impl.decrypt(_CIPHERTEXT_PREFIX_V2 + tampered.hex(), field) is None

        assert impl.decrypt(ciphertext, NotesFieldCipher(field_name="title")) is None
        wrong_key_impl = NotesCipherImpl(master_key=b"y" * 32)
        assert wrong_key_impl.decrypt(ciphertext, field) is None

    def test_impl_field_key_isolation(self, impl: NotesCipherImpl) -> None:
        """不同字段的密文相互独立(派生 key 不同)."""
        # 同一明文加密到 body 和 title
        plaintext = "相同明文"
        c_body = impl.encrypt(plaintext, NotesFieldCipher(field_name="body"))
        c_title = impl.encrypt(plaintext, NotesFieldCipher(field_name="title"))
        assert c_body != c_title
        # 用错误字段解密必须认证失败，而非返回伪明文。
        assert impl.decrypt(c_body, NotesFieldCipher(field_name="title")) is None
        assert impl.decrypt(c_title, NotesFieldCipher(field_name="body")) is None
        # 用正确字段解密成功
        assert impl.decrypt(c_body, NotesFieldCipher(field_name="body")) == plaintext
        assert impl.decrypt(c_title, NotesFieldCipher(field_name="title")) == plaintext

    def test_impl_skip_encrypt_when_field_disabled(self, impl: NotesCipherImpl) -> None:
        """字段 encrypt=False 时,加密直接返回明文."""
        field = NotesFieldCipher(field_name="body", encrypt=False)
        result = impl.encrypt("hello", field)
        assert result == "hello"  # 无前缀
        # 但 decrypt 仍能 fallback
        assert impl.decrypt(result, field) == "hello"

    def test_impl_fingerprint_matches_stub(self, impl: NotesCipherImpl) -> None:
        """Impl 指纹 = Stub 指纹(范本一致)."""
        stub = get_default_stub()
        plaintext = "Day 8 候选 D 指纹测试"
        assert impl.fingerprint(plaintext) == stub.fingerprint(plaintext)

    def test_impl_encrypt_too_long(self, impl: NotesCipherImpl) -> None:
        """Impl 加密严判 max_length."""
        field = NotesFieldCipher(field_name="body", max_length=10)
        with pytest.raises(ValueError, match="明文超长"):
            impl.encrypt("a" * 100, field)

    def test_impl_encrypt_non_string(self, impl: NotesCipherImpl) -> None:
        """Impl 加密严判 plaintext 类型."""
        field = NotesFieldCipher(field_name="body")
        with pytest.raises(ValueError, match="plaintext 必须为 str"):
            impl.encrypt(None, field)  # type: ignore[arg-type]


# ===== 单元: opt-in 开关 + 工厂函数 =====


class TestOptInAndFactory:
    """opt-in 开关 + 工厂函数测试."""

    def test_default_disabled(self) -> None:
        """默认未设 env → opt-in 关闭."""
        os.environ.pop(ENABLE_NOTES_ENCRYPTION_ENV, None)
        assert is_notes_encryption_enabled() is False

    @pytest.mark.parametrize("truthy", ["1", "true", "yes", "on"])
    def test_truthy_enables(self, truthy: str) -> None:
        """truthy 字面量启用 opt-in."""
        os.environ[ENABLE_NOTES_ENCRYPTION_ENV] = truthy
        try:
            assert is_notes_encryption_enabled() is True
        finally:
            os.environ.pop(ENABLE_NOTES_ENCRYPTION_ENV, None)

    @pytest.mark.parametrize("falsy", ["0", "false", "no", "off", ""])
    def test_falsy_disables(self, falsy: str) -> None:
        """falsy 字面量禁用 opt-in."""
        os.environ[ENABLE_NOTES_ENCRYPTION_ENV] = falsy
        try:
            assert is_notes_encryption_enabled() is False
        finally:
            os.environ.pop(ENABLE_NOTES_ENCRYPTION_ENV, None)

    def test_build_cipher_default_stub(self) -> None:
        """未启用 opt-in → 返回 Stub(沿撞坑 #65 范本)."""
        os.environ.pop(ENABLE_NOTES_ENCRYPTION_ENV, None)
        cipher = build_notes_cipher(master_key=b"x" * 32)
        assert cipher.is_runtime_impl is False  # type: ignore[attr-defined]
        assert isinstance(cipher, NotesCipherStub)

    def test_build_cipher_enabled_with_key_returns_impl(self) -> None:
        """启用 opt-in + 提供 master_key → 返回 Impl."""
        os.environ[ENABLE_NOTES_ENCRYPTION_ENV] = "1"
        try:
            cipher = build_notes_cipher(master_key=b"x" * 32)
            assert cipher.is_runtime_impl is True  # type: ignore[attr-defined]
            assert isinstance(cipher, NotesCipherImpl)
        finally:
            os.environ.pop(ENABLE_NOTES_ENCRYPTION_ENV, None)

    def test_build_cipher_enabled_without_key_falls_back_stub(self) -> None:
        """启用 opt-in + 无 master_key → 降级 Stub(撞坑 #65 opt-in 4 阶段)."""
        os.environ[ENABLE_NOTES_ENCRYPTION_ENV] = "1"
        try:
            cipher = build_notes_cipher(master_key=None)
            assert cipher.is_runtime_impl is False  # type: ignore[attr-defined]
        finally:
            os.environ.pop(ENABLE_NOTES_ENCRYPTION_ENV, None)

    def test_build_cipher_enabled_short_key_falls_back_stub(self) -> None:
        """短密钥既不能经工厂启用，也不能绕过工厂直构 Impl。"""
        os.environ[ENABLE_NOTES_ENCRYPTION_ENV] = "1"
        try:
            cipher = build_notes_cipher(master_key=b"short")
            assert cipher.is_runtime_impl is False  # type: ignore[attr-defined]
            with pytest.raises(ValueError, match="至少需 16 bytes"):
                NotesCipherImpl(master_key=b"short")
            non_bytes_cipher = build_notes_cipher(master_key="x" * 16)  # type: ignore[arg-type]
            assert isinstance(non_bytes_cipher, NotesCipherStub)
            with pytest.raises(ValueError, match="必须为 bytes"):
                NotesCipherImpl(master_key="x" * 16)  # type: ignore[arg-type]
        finally:
            os.environ.pop(ENABLE_NOTES_ENCRYPTION_ENV, None)


# ===== 单元: 字段配置 =====


class TestNotesFieldCipher:
    """NotesFieldCipher 字段配置测试."""

    def test_default_fields_cover_body_and_title(self) -> None:
        """默认字段必须含 body + title(沿 NoteStore 列名)."""
        field_names = {f.field_name for f in DEFAULT_NOTES_FIELDS}
        assert "body" in field_names
        assert "title" in field_names

    def test_default_fields_encrypt_true(self) -> None:
        """默认字段 encrypt=True(body/title 加密)."""
        for f in DEFAULT_NOTES_FIELDS:
            assert f.encrypt is True

    def test_custom_field_disabled(self) -> None:
        """自定义字段可禁用加密."""
        field = NotesFieldCipher(field_name="id", encrypt=False, max_length=64)
        assert field.encrypt is False
        assert field.max_length == 64

    def test_field_dataclass_frozen(self) -> None:
        """NotesFieldCipher 必须 frozen(撞坑 #64 公共 API 一致性)."""
        field = NotesFieldCipher(field_name="body")
        with pytest.raises((AttributeError, TypeError)):
            field.field_name = "mutated"  # type: ignore[misc]


# ===== 单元: 5 门集成稳定性 =====


class TestCipherStability:
    """加密/解密稳定性 — 5 门集成(撞坑 #50 漂移防御)."""

    def test_round_trip_1000_times_stable(self) -> None:
        """1000 次 round-trip 必须稳定(无内存泄漏 / 状态污染)."""
        impl = NotesCipherImpl(master_key=b"x" * 32)
        field = NotesFieldCipher(field_name="body")
        plaintext = "Day 8 候选 D 稳定性测试 — 1000 次 round-trip"
        first_ciphertext = impl.encrypt(plaintext, field)
        for _ in range(1000):
            decrypted = impl.decrypt(first_ciphertext, field)
            assert decrypted == plaintext
            # 每次重新加密,IV 随机 → 密文不同
            new_ciphertext = impl.encrypt(plaintext, field)
            assert impl.decrypt(new_ciphertext, field) == plaintext

    def test_stub_round_trip_1000_times_stable(self) -> None:
        """Stub 1000 次 round-trip 必须稳定."""
        stub = get_default_stub()
        field = NotesFieldCipher(field_name="body")
        for _ in range(1000):
            ciphertext = stub.encrypt("stable", field)
            assert ciphertext == "stable"
            assert stub.decrypt(ciphertext, field) == "stable"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
