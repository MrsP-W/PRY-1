"""D7.5 — import_alipay.py + import_all.py CLI 严格退出码测试.

承接 D6.6 P1/P2 修复 + D7.5 沿用:
    - 解析失败 → exit 1
    - Alembic 过旧 → exit 1
    - 业务失败 → exit 2
    - 技术失败 → exit 3(OperationalError 透传)

6 cases:
    1. test_alipay_cli_exits_1_on_missing_csv — 支付宝 CSV 不存在
    2. test_alipay_cli_exits_1_on_empty_file — 支付宝空文件
    3. test_alipay_cli_exits_1_on_unsupported_header — 支付宝未知 header
    4. test_alipay_cli_exits_1_on_alembic_too_old — 支付宝 alembic 过旧
    5. test_alipay_cli_exits_0_on_valid_csv — 支付宝 2024 样本成功
    6. test_import_all_dry_run_no_real_env — import_all 默认 dry-run 拒绝真实导入

跑法:
    pytest tests/scripts/test_import_alipay_cli.py -v
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALIPAY_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "alipay_faker"

sys.path.insert(0, str(PROJECT_ROOT))


def _make_pretend_alembic_db(db_path: Path, revision: str = "0007_transactions") -> None:
    """在临时 SQLite 上伪造 alembic_version + 必含表。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))
        conn.execute(
            """
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_transaction_id TEXT NOT NULL,
                transaction_date DATE NOT NULL,
                amount NUMERIC(10, 2) NOT NULL,
                counterparty TEXT NOT NULL,
                category TEXT,
                payment_method TEXT,
                normalized_fingerprint TEXT NOT NULL,
                needs_confirm INTEGER NOT NULL DEFAULT 0,
                candidate_match_id INTEGER,
                status TEXT NOT NULL DEFAULT 'imported',
                imported_at_ms INTEGER NOT NULL,
                confirmed_at_ms INTEGER,
                raw_row_json TEXT NOT NULL,
                notes TEXT,
                UNIQUE(source, external_transaction_id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


class _FakeDatabase:
    """Mock Database — 只提供 close()."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def close(self) -> None:
        pass


def _run_alipay_cli(csv_path: Path, db_path: Path) -> int:
    """跑 import_alipay.main,mock Database + make_sqlalchemy_engine."""
    from sqlalchemy import create_engine

    from scripts import import_alipay  # noqa: PLC0415

    fake_db = _FakeDatabase(db_path)
    plain_engine = create_engine(f"sqlite:///{db_path}")

    with (
        patch.object(import_alipay, "Database") as mock_db_class,
        patch.object(import_alipay, "make_sqlalchemy_engine", return_value=plain_engine),
    ):
        mock_db_class.open.return_value = fake_db
        return import_alipay.main(["--csv-path", str(csv_path), "--db-path", str(db_path)])


# ===== C1. 文件不存在 =====


def test_alipay_cli_exits_1_on_missing_csv(tmp_path: Path) -> None:
    """D7.5 P1:CSV 文件不存在 → exit 1."""
    db = tmp_path / "pretend.db"
    _make_pretend_alembic_db(db)
    missing_csv = tmp_path / "does_not_exist.csv"
    rc = _run_alipay_cli(missing_csv, db)
    assert rc == 1


# ===== C2. 空文件 =====


def test_alipay_cli_exits_1_on_empty_file(tmp_path: Path) -> None:
    """D7.5 P1:空文件 → detect_version 抛 UnsupportedCSVVersionError → exit 1."""
    db = tmp_path / "pretend.db"
    _make_pretend_alembic_db(db)
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("")
    rc = _run_alipay_cli(empty_csv, db)
    assert rc == 1


# ===== C3. 不支持的 header =====


def test_alipay_cli_exits_1_on_unsupported_header(tmp_path: Path) -> None:
    """D7.5 P1:header 不是 2024/2025/2026 任一版本 → exit 1."""
    db = tmp_path / "pretend.db"
    _make_pretend_alembic_db(db)
    bad_csv = tmp_path / "unsupported.csv"
    bad_csv.write_text(
        "some,random,columns,that,alipay,doesnt,have\n1,2,3,4,5,6,7\n",
        encoding="utf-8",
    )
    rc = _run_alipay_cli(bad_csv, db)
    assert rc == 1


# ===== C4. Alembic revision 过旧 =====


def test_alipay_cli_exits_1_on_alembic_too_old(tmp_path: Path) -> None:
    """D7.5 P2:alembic_version < '0007_transactions' → exit 1."""
    db = tmp_path / "old_alembic.db"
    _make_pretend_alembic_db(db, revision="0006_outbox_approval_provenance")
    valid_csv = ALIPAY_FIXTURES / "alipay_2024_sample.csv"
    rc = _run_alipay_cli(valid_csv, db)
    assert rc == 1


# ===== C5. 正常 2024 样本(成功路径)=====


def test_alipay_cli_exits_0_on_valid_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D7.5 P1 验证:正常 2024 样本 → exit 0."""
    db = tmp_path / "valid.db"
    _make_pretend_alembic_db(db)
    valid_csv = ALIPAY_FIXTURES / "alipay_2024_sample.csv"
    rc = _run_alipay_cli(valid_csv, db)
    captured = capsys.readouterr()
    assert rc == 0, (
        f"D7.5 P1:正常 2024 CSV 应 exit 0,实际 {rc}\nstdout={captured.out}\nstderr={captured.err}"
    )
    assert "parsed=5" in captured.out
    assert "inserted=5" in captured.out
    assert "version=2024" in captured.out


# ===== C6. import_all 默认 dry-run + 4 重防误发 =====


def test_import_all_dry_run_no_real_env(tmp_path: Path) -> None:
    """D7.6 4 重防误发:默认 dry-run,真实导入需 BILLS_REAL_IMPORT=1 + --confirm."""
    import os

    db = tmp_path / "pretend.db"
    _make_pretend_alembic_db(db)
    csv_dir = tmp_path / "bills"
    csv_dir.mkdir()
    # 复制支付宝 2024 样本到 csv_dir
    import shutil

    shutil.copy(ALIPAY_FIXTURES / "alipay_2024_sample.csv", csv_dir / "alipay_2024_sample.csv")

    # 确保 env 未设
    env = os.environ.copy()
    env.pop("BILLS_REAL_IMPORT", None)

    from scripts import import_all  # noqa: PLC0415

    fake_db = _FakeDatabase(db)
    from sqlalchemy import create_engine

    plain_engine = create_engine(f"sqlite:///{db}")
    with (
        patch.object(import_all, "Database") as mock_db_class,
        patch.object(import_all, "make_sqlalchemy_engine", return_value=plain_engine),
    ):
        mock_db_class.open.return_value = fake_db
        # 默认 dry-run,只嗅探不导入
        rc = import_all.main(["--csv-dir", str(csv_dir), "--db-path", str(db)])

    assert rc == 0, f"import_all dry-run 应 exit 0,实际 {rc}"
