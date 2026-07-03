"""Day 1.4 verify_day14_db_tables.py 单测 — 只读契约,无真实 DB 写入."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config as AlembicConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_day14_db_tables.py"


def _load_verify_module():
    spec = importlib.util.spec_from_file_location("verify_day14_db_tables", VERIFY_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_day14_db_tables"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def verify_mod():
    return _load_verify_module()


@pytest.fixture
def fake_keychain(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    from my_ai_employee.core import keychain

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
def migrated_db_path(tmp_path: Path, fake_keychain: dict[tuple[str, str], str]) -> Path:
    """alembic head 后的临时 SQLCipher DB(含 transactions/notes/outbox)."""
    from alembic import command

    db_path = tmp_path / "day14_verify.db"
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    import my_ai_employee.core.db as db_module

    original_open = db_module.Database.open

    def patched_open(db_path_arg: Any = None) -> Any:
        return original_open(db_path=db_path)

    db_module.Database.open = staticmethod(patched_open)  # type: ignore[method-assign]
    try:
        command.upgrade(cfg, "head")
    finally:
        db_module.Database.open = staticmethod(original_open)  # type: ignore[method-assign]
    return db_path


def test_verify_all_tables_ok_after_alembic_head(verify_mod, migrated_db_path: Path) -> None:
    reports, errors = verify_mod.verify_all_tables(db_path=migrated_db_path)
    assert errors == []
    assert len(reports) == 3
    assert all(r.ok for r in reports)
    names = {r.name for r in reports}
    assert names == {"transactions", "notes", "outbox"}


def test_verify_missing_table_returns_error(tmp_path: Path, verify_mod, fake_keychain) -> None:
    from my_ai_employee.core.db import Database

    db_path = tmp_path / "empty.db"
    # 仅初始化空加密库(无 migration)
    db = Database.open(db_path)
    db.close()
    db = Database.open(db_path)
    try:
        result = verify_mod.inspect_table(db, "transactions")
    finally:
        db.close()
    assert isinstance(result, str)
    assert "表缺失" in result
