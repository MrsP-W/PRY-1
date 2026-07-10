"""SQLCipher SQLAlchemy creator 回归测试."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.pool import NullPool

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


# ===== 撞坑 #97 回归测试(2026-07-10):db_path 长生命周期必须用 NullPool =====


def test_engine_from_db_path_uses_nullpool(
    tmp_db_path: Path,
    fake_keychain: dict[tuple[str, str], str],
) -> None:
    """db_path 长生命周期 engine 必须配 NullPool(防 SQLCipher 跨线程 close)."""
    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()

    engine = make_sqlalchemy_engine(db_path=tmp_db_path)

    assert isinstance(engine.pool, NullPool), (
        f"撞坑 #97 修复:db_path 长生命周期 engine 必须用 NullPool,实测 {type(engine.pool).__name__}"
    )


def test_concurrent_threads_no_sqlcipher_cross_thread_close(
    tmp_db_path: Path,
    fake_keychain: dict[tuple[str, str], str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#97 修复回归:N 个 thread 并发查询,stderr 无 ProgrammingError.

    模拟 Dashboard 的 ThreadingHTTPServer 多请求场景:
    - 10 个 thread × 每 thread 5 次 checkout/query/close
    - 全部完成后,caplog 中不应出现 `check_same_thread` ProgrammingError
    """
    import logging

    with Database.open(db_path=tmp_db_path) as db:
        db.init_schema()

    engine = make_sqlalchemy_engine(db_path=tmp_db_path)

    errors: list[str] = []

    def worker(thread_id: int) -> None:
        try:
            for i in range(5):
                with engine.connect() as conn:
                    result = conn.execute(
                        text("SELECT :tid * 100 + :i"),
                        {"tid": thread_id, "i": i},
                    ).scalar_one()
                    assert isinstance(result, int)
        except Exception as exc:  # noqa: BLE001 — 收集线程内异常
            errors.append(f"thread {thread_id}: {exc!r}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(10)]
    # 把 SQLAlchemy / sqlcipher 日志捕获进 caplog
    with caplog.at_level(logging.WARNING, logger="sqlalchemy.pool"):
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    # 1. worker 内不应抛异常
    assert not errors, f"worker 异常:{errors}"

    # 2. caplog 应无 check_same_thread ProgrammingError
    bad = [r for r in caplog.records if "check_same_thread" in r.getMessage()]
    assert not bad, f"撞坑 #97 仍存在:stderr 出现跨线程 close 报错:{[r.getMessage() for r in bad]}"
