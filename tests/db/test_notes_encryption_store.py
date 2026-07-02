"""NoteStore 字段级加密读写链路测试(v0.2.57 / Day 8+ 候选 D 接入)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    from my_ai_employee.core.notes_encryption import _CIPHERTEXT_PREFIX_V1
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
        assert raw.title.startswith(_CIPHERTEXT_PREFIX_V1)
        assert raw.body.startswith(_CIPHERTEXT_PREFIX_V1)

    reloaded = store_encrypted.get_by_id(note.id)
    assert reloaded is not None
    assert reloaded.title == title
    assert reloaded.body == body


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
