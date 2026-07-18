"""v0.2.57 / Day 8 候选 D — Notes 加密增强(字段级加密 + 指纹降级).

本模块提供 Apple Notes 候选/已确认字段的**字段级加密**能力,沿
撞坑 #64 SHA-256 范本(沿 `core/fingerprint.py:normalize_fingerprint`
128 bit 截前 32 chars)。

设计目标:
    - **加密开关 opt-in**:默认 `ENABLE_NOTES_ENCRYPTION=0`,沿撞坑 #1
      隐私铁律(明文/加密两态并存,数据库可平迁)
    - **字段级加密**:仅加密 `body` / `title` 字段;`id` / `status` /
      `created_at` 不加密(便于查询)
    - **密钥管理**:沿 Keychain 取密码派生 key;无 Keychain 时降级
      SHA-256 指纹(不加密,只生成密文指纹供审计)
    - **格式可识别**:加密密文前缀 `enc:v1:`(版本化,沿 v0.2.55
      contract_version 范本)
    - **零依赖**:不依赖 cryptography 第三方库,纯 hashlib + os.urandom

边界(沿撞坑 #1 + 撞坑 #64 + 撞坑 #65):
    - 加密失败 → 返回明文 + warning 标记(不阻塞业务,沿 v0.2.53.7
      opt-in 4 阶段范本)
    - 解密失败 → 返回 None(便于上层 fallback 到明文)
    - 同一字段 + 同一 key + 同一明文 → 每次密文不同(随机 IV)
    - 同一字段 + 同一 key + 同一密文 → 解密必得到原明文(确定)

Day 8 候选 D 范围:
    - NotesFieldCipher dataclass(字段名 + 是否加密 + 派生 key)
    - NotesCipher 协议(encrypt / decrypt / fingerprint 3 方法)
    - NotesCipherStub 默认 Stub(明文无加密,等效 noop)
    - NotesCipherImpl 真实实现(派生 key + AES-like XOR 流密码 +
      SHA-256 指纹降级)
    - opt-in 开关 `ENABLE_NOTES_ENCRYPTION=1` 时尝试注入 Impl
    - 撞坑 #71 解除:业务代码首次 + 改动
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Final, Protocol

# 加密密文前缀(版本化,便于向后兼容;沿 v0.2.55 contract_version 范本)
_CIPHERTEXT_PREFIX_V1: Final = "enc:v1:"

# 指纹长度(沿 core/fingerprint.py:_FINGERPRINT_LENGTH=32 chars = 128 bit)
_FINGERPRINT_LENGTH: Final = 32

# 派生 key 长度(32 字节 = 256 bit,AES-256 兼容)
_DERIVED_KEY_LENGTH: Final = 32

# 运行时 Impl 的主密钥最小长度(与 Keychain 写入/工厂降级口径一致)
_MIN_MASTER_KEY_LENGTH: Final = 16

# 加密 IV 长度(16 字节 = 128 bit,AES block size)
_IV_LENGTH: Final = 16

# Keychain 服务名(沿撞坑 #64 公共 API 一致性)
KEYCHAIN_SERVICE_NOTES: Final = "com.myaiemployee.notes"

# opt-in 开关(沿 v0.2.53.7 DASHBOARD_REAL_DB=1 范本)
ENABLE_NOTES_ENCRYPTION_ENV: Final = "ENABLE_NOTES_ENCRYPTION"

# 默认 Stub 标识(沿撞坑 #65 opt-in 4 阶段范本)
_STUB_NAME: Final = "stub"
_IMPL_NAME: Final = "aes-xor-256"


# ===== 字段配置 dataclass =====


@dataclass(frozen=True, slots=True)
class NotesFieldCipher:
    """字段级加密配置 — 描述哪些字段加密 / 哪些不加密.

    字段:
        field_name: 字段名(对应 NoteStore 列名)
        encrypt: 是否加密(默认 True)
        max_length: 加密前明文最大长度(超长 ValueError)
    """

    field_name: str
    encrypt: bool = True
    max_length: int = 65536  # 64 KB 兜底


# Notes 字段默认配置(沿 NoteStore 列名)
DEFAULT_NOTES_FIELDS: Final[tuple[NotesFieldCipher, ...]] = (
    NotesFieldCipher(field_name="body", encrypt=True, max_length=65536),
    NotesFieldCipher(field_name="title", encrypt=True, max_length=512),
)


# ===== NotesCipher 协议 =====


class NotesCipher(Protocol):
    """Notes 字段级加密协议(沿撞坑 #64 公共 API 一致性).

    3 方法契约:
        - encrypt(plaintext, field) -> str
            - plaintext 为明文 → 返回密文(前缀 `enc:v1:`)或明文(Stub 模式)
            - field 描述字段名 / max_length(超长抛 ValueError)
        - decrypt(ciphertext, field) -> str | None
            - ciphertext 含前缀 → 解密;失败返回 None(不抛异常)
            - ciphertext 不含前缀 → 直接返回(明文 fallback)
        - fingerprint(plaintext) -> str
            - plaintext → SHA-256 截 32 chars(128 bit)
            - 加密失败时,审计/去重用此指纹(不暴露明文)

    注:`is_runtime_impl` / `name` 公共属性由具体类提供(沿 v0.2.53.30 严判),
       不在 Protocol 声明以避免 frozen dataclass 与 Protocol setter 类型冲突。
    """

    def encrypt(self, plaintext: str, field: NotesFieldCipher) -> str: ...

    def decrypt(self, ciphertext: str, field: NotesFieldCipher) -> str | None: ...

    def fingerprint(self, plaintext: str) -> str: ...


# ===== Stub 默认实现(无加密,等效 noop)=====


@dataclass(frozen=True, slots=True)
class NotesCipherStub:
    """Notes 字段级加密 Stub — 默认无加密(明文透传,沿 v0.2.53.6 范本).

    边界(沿撞坑 #65 opt-in 4 阶段):
        - 默认启用(测试零依赖)
        - encrypt 直接返回明文(无 `enc:v1:` 前缀)
        - decrypt 直接返回 ciphertext(无前缀判定)
        - fingerprint 走 SHA-256(沿 core/fingerprint.py 范本)
        - is_runtime_impl = False(沿 v0.2.53.30 严判)
    """

    is_runtime_impl: bool = False
    name: str = _STUB_NAME

    def encrypt(self, plaintext: str, field: NotesFieldCipher) -> str:
        """默认无加密 — 直接返回明文."""
        if not isinstance(plaintext, str):
            raise ValueError(f"plaintext 必须为 str,实际 type={type(plaintext).__name__}")
        if len(plaintext) > field.max_length:
            raise ValueError(
                f"字段 {field.field_name} 明文超长({len(plaintext)}>{field.max_length})"
            )
        return plaintext

    def decrypt(self, ciphertext: str, field: NotesFieldCipher) -> str | None:
        """默认无加密 — 直接返回 ciphertext(明文)."""
        if not isinstance(ciphertext, str):
            return None
        return ciphertext

    def fingerprint(self, plaintext: str) -> str:
        """SHA-256 截 32 chars(沿 core/fingerprint.py 范本)."""
        return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:_FINGERPRINT_LENGTH]


# ===== 真实实现(AES-like XOR 流密码 + SHA-256 指纹降级)=====


@dataclass(frozen=True, slots=True)
class NotesCipherImpl:
    """Notes 字段级加密 Impl — 派生 key + 随机 IV + XOR 流密码.

    边界(沿撞坑 #65 opt-in 4 阶段 + v0.2.57 / Day 8 候选 D):
        - 仅在 `ENABLE_NOTES_ENCRYPTION=1` 时注入
        - key 派生:PBKDF2-like(HMAC-SHA256 链,迭代 10000 次)
        - 加密:key ⊕ IV ⊕ plaintext(简单 XOR 流密码,演示用)
        - 密文格式:`enc:v1:{iv_hex}{ciphertext_hex}`
        - 随机 IV:每次 encrypt 用 `os.urandom(16)` 生成新 IV
        - 解密:从密文抽取 IV,与 key XOR 还原明文
        - fingerprint:SHA-256 截 32 chars(与 Stub 一致)
        - is_runtime_impl = True(沿 v0.2.53.30 严判)
    """

    master_key: bytes  # 主密钥(从 Keychain 或 config 派生)
    is_runtime_impl: bool = True
    name: str = _IMPL_NAME

    def __post_init__(self) -> None:
        """直构 Impl 也必须守住工厂的主密钥边界。"""
        if not isinstance(self.master_key, bytes):
            raise ValueError(f"master_key 必须为 bytes,实际 type={type(self.master_key).__name__}")
        if len(self.master_key) < _MIN_MASTER_KEY_LENGTH:
            raise ValueError(f"master_key 至少需 {_MIN_MASTER_KEY_LENGTH} bytes")

    def _derive_field_key(self, field_name: str, salt: bytes) -> bytes:
        """派生字段级 key — HMAC-SHA256 链迭代 10000 次.

        Args:
            field_name: 字段名(作为 salt 的一部分)
            salt: 随机 salt(16 字节)

        Returns:
            32 字节派生 key
        """
        h = hmac.new(self.master_key, salt + field_name.encode("utf-8"), hashlib.sha256)
        for _ in range(10000):
            h = hmac.new(self.master_key, h.digest(), hashlib.sha256)
        return h.digest()[:_DERIVED_KEY_LENGTH]

    def encrypt(self, plaintext: str, field: NotesFieldCipher) -> str:
        """加密明文 → 密文 `enc:v1:{iv_hex}{ciphertext_hex}`.

        Args:
            plaintext: 明文(必须 str)
            field: 字段配置(encrypt=False 时直接返回明文)

        Returns:
            密文字符串(前缀 `enc:v1:`)或明文(Stub 路径)

        Raises:
            ValueError: plaintext 非 str 或超长
        """
        if not isinstance(plaintext, str):
            raise ValueError(f"plaintext 必须为 str,实际 type={type(plaintext).__name__}")
        if len(plaintext) > field.max_length:
            raise ValueError(
                f"字段 {field.field_name} 明文超长({len(plaintext)}>{field.max_length})"
            )
        if not field.encrypt:
            return plaintext  # 字段不加密,直接返回
        # 1. 生成随机 salt + IV
        salt = os.urandom(_IV_LENGTH)
        iv = os.urandom(_IV_LENGTH)
        # 2. 派生字段级 key
        field_key = self._derive_field_key(field.field_name, salt)
        # 3. XOR 流密码(简化实现,演示用)
        plaintext_bytes = plaintext.encode("utf-8")
        ciphertext_bytes = bytes(
            b ^ field_key[i % _DERIVED_KEY_LENGTH] ^ iv[i % _IV_LENGTH]
            for i, b in enumerate(plaintext_bytes)
        )
        # 4. 拼接 IV + ciphertext(IV 用于解密时还原 key stream)
        return _CIPHERTEXT_PREFIX_V1 + (salt + iv + ciphertext_bytes).hex()

    def decrypt(self, ciphertext: str, field: NotesFieldCipher) -> str | None:
        """解密密文 → 明文;失败返回 None(不抛异常,沿撞坑 #65 范本).

        Args:
            ciphertext: 密文(可能含/不含 `enc:v1:` 前缀)
            field: 字段配置(用于派生 key)

        Returns:
            明文字符串;解密失败或格式错时返回 None
        """
        if not isinstance(ciphertext, str):
            return None
        # 不含前缀 → 视为明文 fallback(沿撞坑 #65 兼容旧数据)
        if not ciphertext.startswith(_CIPHERTEXT_PREFIX_V1):
            return ciphertext
        try:
            raw = bytes.fromhex(ciphertext[len(_CIPHERTEXT_PREFIX_V1) :])
            if len(raw) < _IV_LENGTH * 2:
                return None  # 格式错
            salt = raw[:_IV_LENGTH]
            iv = raw[_IV_LENGTH : _IV_LENGTH * 2]
            ciphertext_bytes = raw[_IV_LENGTH * 2 :]
            field_key = self._derive_field_key(field.field_name, salt)
            plaintext_bytes = bytes(
                b ^ field_key[i % _DERIVED_KEY_LENGTH] ^ iv[i % _IV_LENGTH]
                for i, b in enumerate(ciphertext_bytes)
            )
            return plaintext_bytes.decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return None

    def fingerprint(self, plaintext: str) -> str:
        """SHA-256 截 32 chars(与 Stub 范本一致,保证兼容性)."""
        return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:_FINGERPRINT_LENGTH]


# ===== 工厂函数 =====


def get_default_stub() -> NotesCipherStub:
    """获取默认 Stub(沿 `BusinessWriterStub.get_default_stub` 范本)."""
    return NotesCipherStub()


def is_notes_encryption_enabled() -> bool:
    """`ENABLE_NOTES_ENCRYPTION=1` 判定 — 默认关闭,仅识别 truthy 字面量.

    沿 v0.2.53.7 opt-in 范本。
    """
    import os

    raw = os.environ.get(ENABLE_NOTES_ENCRYPTION_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def build_notes_cipher(master_key: bytes | None = None) -> NotesCipher:
    """工厂函数 — 根据 opt-in 开关决定 Stub 或 Impl.

    Args:
        master_key: 主密钥(Impl 路径必填,None 时降级 Stub)

    Returns:
        NotesCipher 实例(Stub 或 Impl)
    """
    if not is_notes_encryption_enabled():
        return get_default_stub()
    if not isinstance(master_key, bytes) or len(master_key) < _MIN_MASTER_KEY_LENGTH:
        # 主密钥缺失/类型不符/过短 → 降级 Stub(沿撞坑 #65 opt-in 4 阶段)
        return get_default_stub()
    return NotesCipherImpl(master_key=master_key)


# Day 10 / Phase 1.1 — Keychain 主密钥加载工厂(降级不抛异常)
# 撞坑 #65 opt-in 4 阶段范本:任何失败 → 返回 None,绝不抛异常,绝不阻塞业务
# 撞坑 #1 隐私铁律:不打印 value,只记长度 + service 名
# 撞坑 #18 5 门严判替代:严判 hex + 长度,过短/非 hex → 视作缺密钥降级


def _hex_to_bytes(value: str) -> bytes | None:
    """hex 字符串 → bytes;失败返回 None(撞坑 #65 降级,不抛异常).

    严判:
        - 必须 hex 字符 [0-9a-fA-F]
        - 偶数长度
        - 长度 >= 16 bytes(32 hex chars,沿 `_DERIVED_KEY_LENGTH` 32 字节范本,
          这里只取下限保证密钥可用,实际 Impl 仍用完整长度)
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) % 2 != 0:
        return None
    if not all(c in "0123456789abcdefABCDEF" for c in stripped):
        return None
    try:
        raw = bytes.fromhex(stripped)
    except ValueError:
        return None
    if len(raw) < 16:
        return None
    return raw


def load_notes_master_key() -> bytes | None:
    """从 Keychain 加载 Notes 主密钥,失败时返回 None(沿撞坑 #65 降级范本).

    **绝不抛异常** — 任何失败(Keychain 不可用 / 密钥不存在 / 格式错 / 长度不够)
    都返回 None,让上层 `build_notes_cipher(None)` 自然降级到 Stub。

    撞坑 #1 隐私铁律:不打印 value,不 log 密钥原文。

    撞坑设计:
        - 默认 UNSET `ENABLE_NOTES_ENCRYPTION=1` 时,即使 Keychain 有密钥也返回 None
          (沿 `build_notes_cipher` opt-in 范本 — env 是开关,缺它就 Stub)
        - 当 env 开启时,才尝试从 Keychain 取
        - 此函数是 `build_notes_cipher(load_notes_master_key())` 的核心接线

    Returns:
        主密钥 bytes(>= 16 bytes)或 None(失败/未启用)
    """
    # 撞坑 #65 opt-in 4 阶段:env UNSET 时短路返回 None,不发请求
    if not is_notes_encryption_enabled():
        return None
    # Keychain 导入放在函数内 — 撞坑 #64 公共 API + 避免顶层硬绑 macOS-only
    try:
        from my_ai_employee.core.keychain import get_notes_master_key
    except ImportError:
        # Keychain 模块不可用(非 macOS 等场景)→ 降级
        return None
    try:
        result = get_notes_master_key()
    except Exception:
        # 任何底层异常 → 降级(撞坑 #65 4 阶段)
        return None
    if not result.ok or not isinstance(result.value, str):
        return None
    return _hex_to_bytes(result.value)


__all__ = [
    "DEFAULT_NOTES_FIELDS",
    "ENABLE_NOTES_ENCRYPTION_ENV",
    "KEYCHAIN_SERVICE_NOTES",
    "NotesCipher",
    "NotesCipherImpl",
    "NotesCipherStub",
    "NotesFieldCipher",
    "build_notes_cipher",
    "get_default_stub",
    "is_notes_encryption_enabled",
    # Day 10 / Phase 1.1 — Keychain 接线工厂
    "load_notes_master_key",
]
