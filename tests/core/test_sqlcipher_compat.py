"""SQLCipher SQLAlchemy creator 回归测试."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from my_ai_employee.core import keychain
from my_ai_employee.core.db import Database
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_creator, make_sqlalchemy_engine


@pytest.fixture
def fake_keychain(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    """in-memory Keychain,避免污染真实 macOS Keychain."""
    store: dict[tuple[str, str], str] = {}

    def fake_get() -> keychain.KeychainResult:
        key = (keychain.SERVICE_DB, "data.db")
        if key in store:
            return keychain.KeychainResult(ok=True, value=store[key])
        return keychain.KeychainResult(ok=False, error="not found")

    def fake_set(password: str) -> keychain.KeychainResult:
        store[(keychain.SERVICE_DB, "data.db")] = password
        return keychain.KeychainResult(ok=True)

    monkeypatch.setattr(keychain, "get_db_password", fake_get)
    monkeypatch.setattr(keychain, "set_db_password", fake_set)
    return store


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "sqlcipher_compat.db"


def test_creator_requires_exactly_one_source(tmp_db_path: Path) -> None:
    with pytest.raises(ValueError, match="只能传入 db 或 db_path"):
        make_sqlalchemy_creator()

    db = object()
    with pytest.raises(ValueError, match="只能传入 db 或 db_path"):
        make_sqlalchemy_creator(db=db, db_path=tmp_db_path)  # type: ignore[arg-type]


def test_engine_from_db_path_survives_closed_initial_database(
    tmp_db_path: Path,
    fake_keychain: dict[tuple[str, str], str],
) -> None:
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()

    engine = make_sqlalchemy_engine(db_path=tmp_db_path)

    with engine.connect() as conn:
        row_count = conn.execute(text("SELECT count(*) FROM sqlite_master")).scalar_one()

    assert isinstance(row_count, int)


def test_engine_from_closed_database_still_fails_fast(
    tmp_db_path: Path,
    fake_keychain: dict[tuple[str, str], str],
) -> None:
    db = Database.open(db_path=tmp_db_path)
    engine = make_sqlalchemy_engine(db)
    db.close()

    with pytest.raises(RuntimeError, match="DB 已关闭"), engine.connect():
        pass
