"""NoteStore 字段级加密读写链路测试(v0.2.57 / Day 8+ 候选 D 接入)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    from collections.abc import Iterator

    from my_ai_employee.db.notes import NoteStore


@pytest.fixture
def engine() -> Iterator[Any]:
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.notes import Note  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    return sessionmaker[Any](bind=engine)


@pytest.fixture
def store(session_factory: Any) -> NoteStore:
    from my_ai_employee.db.notes import NoteStore

    return NoteStore(session_factory)


@pytest.fixture
def store_encrypted(session_factory: Any) -> NoteStore:
    from my_ai_employee.core.notes_encryption import NotesCipherImpl
    from my_ai_employee.db.notes import NoteStore

    return NoteStore(session_factory, cipher=NotesCipherImpl(master_key=b"x" * 32))


def test_default_store_encrypts_when_env_and_keychain_ok(
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认 NoteStore:env=1 + Keychain OK 时应加密落库(不经手动注入 cipher)."""
    from my_ai_employee.core.keychain import KeychainResult
    from my_ai_employee.core.notes_encryption import _CIPHERTEXT_PREFIX_V3
    from my_ai_employee.db.notes import Note, NoteStore

    monkeypatch.setenv("ENABLE_NOTES_ENCRYPTION", "1")
    master_key_hex = "d" * 64
    with patch(
        "my_ai_employee.core.keychain.get_notes_master_key",
        return_value=KeychainResult(ok=True, value=master_key_hex),
    ):
        default_store = NoteStore(session_factory)
        note = default_store.insert(
            apple_note_id="x-coredata://ICNote/DEFAULT-ENC1",
            folder="Notes",
            title="默认加密标题",
            body="默认加密正文",
            updated_at_ms=1700000002000,
        )
    assert note.title == "默认加密标题"
    assert note.body == "默认加密正文"

    with session_factory() as session:
        raw = session.get(Note, note.id)
        assert raw is not None
        assert raw.title.startswith(_CIPHERTEXT_PREFIX_V3)
        assert raw.body.startswith(_CIPHERTEXT_PREFIX_V3)


def test_insert_stub_cipher_stores_plaintext_at_rest(
    store: NoteStore, session_factory: Any
) -> None:
    """默认 Stub:落库与读出均为明文."""
    from my_ai_employee.db.notes import Note

    note = store.insert(
        apple_note_id="x-coredata://ICNote/PLAIN1",
        folder="Notes",
        title="明文标题",
        body="明文正文",
        updated_at_ms=1700000000000,
    )
    assert note.title == "明文标题"
    assert note.body == "明文正文"

    with session_factory() as session:
        raw = session.get(Note, note.id)
        assert raw is not None
        assert raw.title == "明文标题"
        assert raw.body == "明文正文"


def test_insert_impl_cipher_encrypts_at_rest_and_decrypts_on_read(
    store_encrypted: NoteStore,
    session_factory: Any,
) -> None:
    """Impl:指纹用明文计算,库内 title/body 加密,读出解密."""
    from my_ai_employee.core.fingerprint import normalize_note_fingerprint
    from my_ai_employee.core.notes_encryption import _CIPHERTEXT_PREFIX_V3
    from my_ai_employee.db.notes import Note

    title = "加密标题"
    body = "加密正文"
    updated_at_ms = 1700000000000
    note = store_encrypted.insert(
        apple_note_id="x-coredata://ICNote/ENC1",
        folder="Notes",
        title=title,
        body=body,
        updated_at_ms=updated_at_ms,
    )
    assert note.title == title
    assert note.body == body

    expected_fp = normalize_note_fingerprint(
        title=title,
        folder="Notes",
        updated_at_ms=updated_at_ms,
    )
    assert note.normalized_fingerprint == expected_fp

    with session_factory() as session:
        raw = session.get(Note, note.id)
        assert raw is not None
        assert raw.title.startswith(_CIPHERTEXT_PREFIX_V3)
        assert raw.body.startswith(_CIPHERTEXT_PREFIX_V3)

    reloaded = store_encrypted.get_by_id(note.id)
    assert reloaded is not None
    assert reloaded.title == title
    assert reloaded.body == body

    with session_factory() as session:
        raw = session.get(Note, note.id)
        assert raw is not None
        # 认证失败不能把原始密文回传到 UI/业务层。
        raw.title = raw.title[:-2] + ("00" if raw.title[-2:] != "00" else "01")
        session.commit()

    tampered = store_encrypted.get_by_id(note.id)
    assert tampered is not None
    assert tampered.title == "[加密内容不可用]"
    assert tampered.body == body


def test_list_all_returns_decrypted_titles(store_encrypted: NoteStore) -> None:
    """列表查询路径同样解密 title/body."""
    store_encrypted.insert(
        apple_note_id="x-coredata://ICNote/ENC2",
        folder="Notes",
        title="待确认",
        body="正文",
        updated_at_ms=1700000001000,
    )
    notes = store_encrypted.list_all(limit=10)
    assert len(notes) >= 1
    assert notes[0].title == "待确认"
    assert notes[0].body == "正文"


def test_l3_fuzzy_match_decrypts_encrypted_titles(store_encrypted: NoteStore) -> None:
    """真实密文 title 在 L3 ±1 天候选查询中须先解密再归一化。"""
    from datetime import UTC, datetime

    base_ms = int(datetime(2026, 6, 14, 10, tzinfo=UTC).timestamp() * 1000)
    existing = store_encrypted.insert(
        apple_note_id="x-coredata://ICNote/ENC-L3-001",
        folder="Notes",
        title="星巴克*",
        body="旧笔记",
        updated_at_ms=base_ms,
    )

    candidate = store_encrypted.insert(
        apple_note_id="x-coredata://ICNote/ENC-L3-002",
        folder="Notes",
        title="星巴克",
        body="新笔记",
        updated_at_ms=int(datetime(2026, 6, 15, 10, tzinfo=UTC).timestamp() * 1000),
    )

    assert candidate.needs_confirm == 1
    assert candidate.candidate_match_id == existing.id


def test_l3_fuzzy_match_skips_tampered_encrypted_title(
    store_encrypted: NoteStore,
    session_factory: Any,
) -> None:
    """认证失败的加密 title 不得参与 L3 候选，保持 fail-closed。"""
    from datetime import UTC, datetime

    from my_ai_employee.db.notes import Note

    base_ms = int(datetime(2026, 6, 14, 10, tzinfo=UTC).timestamp() * 1000)
    existing = store_encrypted.insert(
        apple_note_id="x-coredata://ICNote/ENC-L3-TAMPER-001",
        folder="Notes",
        title="篡改候选",
        body="旧笔记",
        updated_at_ms=base_ms,
    )
    with session_factory() as session:
        raw = session.get(Note, existing.id)
        assert raw is not None
        raw.title = raw.title[:-2] + ("00" if raw.title[-2:] != "00" else "01")
        tampered_title = raw.title
        session.commit()

    candidate = store_encrypted.insert(
        apple_note_id="x-coredata://ICNote/ENC-L3-TAMPER-002",
        folder="Notes",
        title=tampered_title,
        body="新笔记",
        updated_at_ms=int(datetime(2026, 6, 15, 10, tzinfo=UTC).timestamp() * 1000),
    )

    assert candidate.needs_confirm == 0
    assert candidate.candidate_match_id is None


# ============================================================
# Day 10 Phase 1.2 — 旧明文 fallback 集成测试(撞坑 #65 兼容旧数据)
# 沿 [src/my_ai_employee/core/notes_encryption.py:240-244] Impl.decrypt 注释
# "明文 fallback(沿撞坑 #65 兼容旧数据)"回归保护
# ============================================================


def _seed_plaintext_note(
    session_factory: Any,
    *,
    apple_note_id: str,
    title: str,
    body: str,
    synced_at_ms: int = 1_700_000_000_000,
) -> int:
    """直接 SQLAlchemy session.add 写入明文 note(模拟旧版 NoteStore 未加密路径).

    Returns:
        int: 新插入 note 的主键 id.
    """
    from my_ai_employee.db.notes import Note

    with session_factory() as session:
        note = Note(
            apple_note_id=apple_note_id,
            folder="Notes",
            title=title,
            body=body,
            is_private=0,
            tags=None,
            synced_at_ms=synced_at_ms,
            updated_at_ms=synced_at_ms,
            sync_status="NEW",
            needs_confirm=1,
            candidate_match_id=None,
        )
        session.add(note)
        session.commit()
        return int(note.id)


_V2_LEGACY_TITLE_CIPHERTEXT = (
    "enc:v2:000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
    "c50139450d502f52ba123b087082f2383dd9738c6c6200a247b691381e45b9e02045b5f8a779d7867d52ae6098bf25"
)


def test_impl_cipher_reads_v2_legacy_ciphertext_from_store(
    session_factory: Any,
) -> None:
    """升级后 NoteStore 仍须从实际库行解密认证通过的 v2 title。"""
    from my_ai_employee.core.notes_encryption import NotesCipherImpl
    from my_ai_employee.db.notes import Note, NoteStore

    with session_factory() as session:
        legacy = Note(
            apple_note_id="x-coredata://ICNote/LEGACY-V2-CIPHER",
            folder="Notes",
            title=_V2_LEGACY_TITLE_CIPHERTEXT,
            body="legacy v2 plaintext body",
            is_private=0,
            tags=None,
            synced_at_ms=1_700_000_000_003,
            updated_at_ms=1_700_000_000_003,
            sync_status="NEW",
            needs_confirm=1,
            candidate_match_id=None,
        )
        session.add(legacy)
        session.commit()
        legacy_id = int(legacy.id)

    impl_store = NoteStore(session_factory, cipher=NotesCipherImpl(master_key=b"x" * 32))
    loaded = impl_store.get_by_id(legacy_id)
    assert loaded is not None
    assert loaded.title == "legacy v2 title"
    assert loaded.body == "legacy v2 plaintext body"

    pending = impl_store.list_by_needs_confirm(limit=10)
    assert any(note.id == legacy_id and note.title == "legacy v2 title" for note in pending)


def test_stub_cipher_reads_legacy_plaintext_fallback(
    session_factory: Any,
) -> None:
    """撞坑 #65:库内历史明文(无 enc: 前缀)经 Stub cipher 读出应透传原值.

    场景:历史 NoteStore 写入时未启用加密,库内 title/body 仍是明文。
    新 store 实例(默认 Stub cipher)读取时不应误把明文当密文处理。
    """
    from my_ai_employee.db.notes import NoteStore

    note_id = _seed_plaintext_note(
        session_factory,
        apple_note_id="x-coredata://ICNote/LEGACY-STUB",
        title="旧明文标题",
        body="旧明文正文",
    )

    # 默认构造 → Stub cipher
    legacy_store = NoteStore(session_factory)
    loaded = legacy_store.get_by_id(note_id)
    assert loaded is not None
    assert loaded.title == "旧明文标题"
    assert loaded.body == "旧明文正文"

    # 列表路径同样回退
    listed = legacy_store.list_by_needs_confirm(limit=10)
    assert any(n.id == note_id and n.title == "旧明文标题" for n in listed)


def test_impl_cipher_reads_legacy_plaintext_fallback(
    session_factory: Any,
) -> None:
    """撞坑 #65:Impl cipher 读库内明文(无 enc: 前缀)应透传原值.

    关键回归:NotesCipherImpl.decrypt 显式 `startswith("enc:")` 判定
    缺前缀时 return ciphertext(notes_encryption.py:242-244)。此契约被破坏
    则历史数据(明文落库)会被新 store 读坏。
    """
    from my_ai_employee.core.notes_encryption import NotesCipherImpl
    from my_ai_employee.db.notes import NoteStore

    note_id = _seed_plaintext_note(
        session_factory,
        apple_note_id="x-coredata://ICNote/LEGACY-IMPL",
        title="Impl 读旧明文",
        body="Impl 应透传",
    )

    impl_store = NoteStore(session_factory, cipher=NotesCipherImpl(master_key=b"x" * 32))
    loaded = impl_store.get_by_id(note_id)
    assert loaded is not None
    assert loaded.title == "Impl 读旧明文"
    assert loaded.body == "Impl 应透传"

    # 列表 + 待确认查询路径同样回退
    pending = impl_store.list_by_needs_confirm(limit=10)
    matched = [n for n in pending if n.id == note_id]
    assert len(matched) == 1
    assert matched[0].title == "Impl 读旧明文"
    assert matched[0].body == "Impl 应透传"


def test_l3_fuzzy_match_keeps_legacy_plaintext_title_compatibility(
    session_factory: Any,
) -> None:
    """Impl cipher 的 L3 查询仍须匹配直接落库的旧明文 title。"""
    from datetime import UTC, datetime

    from my_ai_employee.core.notes_encryption import NotesCipherImpl
    from my_ai_employee.db.notes import NoteStore

    base_ms = int(datetime(2026, 6, 14, 10, tzinfo=UTC).timestamp() * 1000)
    legacy_id = _seed_plaintext_note(
        session_factory,
        apple_note_id="x-coredata://ICNote/LEGACY-L3-001",
        title="旧明文候选",
        body="旧笔记",
        synced_at_ms=base_ms,
    )
    impl_store = NoteStore(session_factory, cipher=NotesCipherImpl(master_key=b"x" * 32))

    candidate = impl_store.insert(
        apple_note_id="x-coredata://ICNote/LEGACY-L3-002",
        folder="Notes",
        title="旧明文候选",
        body="新笔记",
        updated_at_ms=int(datetime(2026, 6, 15, 10, tzinfo=UTC).timestamp() * 1000),
    )

    assert candidate.needs_confirm == 1
    assert candidate.candidate_match_id == legacy_id


def test_impl_cipher_mixed_plaintext_and_encrypted(
    session_factory: Any,
) -> None:
    """渐进迁移:全密文 + 全明文混合列表,Impl cipher 字段独立处理.

    场景:Day 9+ 期间某些 Note 走 NoteStore.insert(Impl 加密),
    另一些历史 Note 未走加密(直接落库明文)。一次 list_by_needs_confirm
    混合返回,字段独立解密 / 透传(沿撞坑 #65 兼容)。
    """
    from my_ai_employee.core.notes_encryption import NotesCipherImpl
    from my_ai_employee.db.notes import NoteStore

    # 1) 通过 NoteStore.insert 写一条全密文
    impl_store = NoteStore(session_factory, cipher=NotesCipherImpl(master_key=b"y" * 32))
    inserted = impl_store.insert(
        apple_note_id="x-coredata://ICNote/MIXED-NEW",
        folder="Notes",
        title="新加密标题",
        body="新加密正文",
        updated_at_ms=1_700_000_001_000,
    )

    # 2) 直接 SQLAlchemy 写一条全明文(模拟历史未加密数据)
    legacy_id = _seed_plaintext_note(
        session_factory,
        apple_note_id="x-coredata://ICNote/MIXED-LEGACY",
        title="旧明文标题",
        body="旧明文正文",
        synced_at_ms=1_700_000_002_000,
    )

    # 3) 一次 list_all 验证 2 条全部出现 + 字段独立
    # (list_by_needs_confirm 只返回 needs_confirm=1,而 NoteStore.insert 自动
    #  决定 needs_confirm — 新插入无重复指纹时为 0,改用 list_all 覆盖全场景)
    pending = impl_store.list_all(limit=10)
    by_id = {n.id: n for n in pending}

    # 全密文:应正确解密
    assert by_id[inserted.id].title == "新加密标题"
    assert by_id[inserted.id].body == "新加密正文"

    # 全明文:应透传(Impl.decrypt 遇无前缀 return ciphertext,撞坑 #65)
    legacy = by_id[legacy_id]
    assert legacy.title == "旧明文标题"
    assert legacy.body == "旧明文正文"
