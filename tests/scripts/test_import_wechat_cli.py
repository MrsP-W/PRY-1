"""D6.6 P1/P2 修复 — import_wechat.py CLI 严格退出码测试(6 cases).

D6.5 收口后,检查员驳回 4 缺陷:
    - P1:解析失败(safe_parse 返回空列表)→ CLI 静默成功(exit 0)
        修复:pre-flight detect_version + parsed=0 检查 → exit 1
    - P2:CLI 走 Base.metadata.create_all() 不走 Alembic
        修复:启动校验 alembic_version >= '0007_transactions'

测试覆盖(6 cases):
    C1. test_cli_exits_1_on_missing_csv
        --csv-path 指向不存在文件 → exit 1
    C2. test_cli_exits_1_on_empty_file
        空文件(0 字节)→ detect_version 抛 UnsupportedCSVVersionError → exit 1
    C3. test_cli_exits_1_on_unsupported_header
        header 不是 2024/2025/2026 任一版本 → exit 1
    C4. test_cli_exits_1_on_corrupt_csv
        header 看起来对但 0 数据行 → exit 1(parsed=0)
    C5. test_cli_exits_1_on_alembic_revision_too_old
        alembic_version < '0007_transactions' → exit 1
    C6. test_cli_exits_0_on_valid_csv
        正常 2024 样本 → exit 0

设计原则:
    - 直接 import main()(不 subprocess,避免 SQLCipher 加密 DB 问题)
    - mock Database.open 走 plain sqlite(测试环境,沿 D6.4 范本)
    - tmp_path 临时文件(避免污染 fixtures)
    - 临时 SQLite 初始化成满足 alembic_version 校验的"伪 alembic DB"
    - 用 capfd 捕获 stdout/stderr 验退出消息
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WECHAT_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "wechat_faker"

# 把 scripts/ 加到 sys.path,让"from scripts import import_wechat"能找到
sys.path.insert(0, str(PROJECT_ROOT))


def _make_pretend_alembic_db(db_path: Path, revision: str = "0007_transactions") -> None:
    """在临时 SQLite 上伪造 alembic_version + 必含表(用于通过 alembic 校验)。

    D6.6 P2 修复测试:alembic_helper.assert_min_revision 必须能读到 '0007_transactions'。
    真实 SQLCipher + 真实 alembic upgrade head 走 tests/db/test_transactions_migration.py,
    本测试只验 CLI 行为(alembic 校验 + pre-flight 嗅探 + 退出码),不验真实迁移。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))
        conn.execute("""
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
            """)
        conn.commit()
    finally:
        conn.close()


class _FakeDatabase:
    """Mock Database — 只提供 close(),engine 由 make_sqlalchemy_engine mock 提供。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    def close(self) -> None:
        pass


def _run_cli_with_mock_db(
    csv_path: Path,
    db_path: Path,
    *,
    max_rows: int | None = None,
) -> int:
    """跑 import_wechat.main,Database.open + make_sqlalchemy_engine 都用 mock(走 plain sqlite)。

    Args:
        csv_path: 微信账单 CSV 路径
        db_path: 临时 sqlite 路径
        max_rows: 透传 CLI --max-rows(默认 None = 全量)

    Returns:
        退出码(0/1/2/3)
    """
    from sqlalchemy import create_engine

    from scripts import import_wechat  # noqa: PLC0415

    fake_db = _FakeDatabase(db_path)
    plain_engine = create_engine(f"sqlite:///{db_path}")

    args = ["--csv-path", str(csv_path), "--db-path", str(db_path)]
    if max_rows is not None:
        args += ["--max-rows", str(max_rows)]

    with (
        patch.object(import_wechat, "Database") as mock_db_class,
        patch.object(import_wechat, "make_sqlalchemy_engine", return_value=plain_engine),
    ):
        mock_db_class.open.return_value = fake_db
        return import_wechat.main(args)


# ===== C1. 文件不存在 =====


def test_cli_exits_1_on_missing_csv(tmp_path: Path) -> None:
    """D6.6 P1:CSV 文件不存在 → exit 1(防脚本误传)。"""
    db = tmp_path / "pretend.db"
    _make_pretend_alembic_db(db)
    missing_csv = tmp_path / "does_not_exist.csv"
    rc = _run_cli_with_mock_db(missing_csv, db)
    assert rc == 1, f"D6.6 P1:missing CSV 应 exit 1,实际 {rc}"


# ===== C2. 空文件 =====


def test_cli_exits_1_on_empty_file(tmp_path: Path) -> None:
    """D6.6 P1:空文件(0 字节)→ detect_version 抛 UnsupportedCSVVersionError → exit 1。"""
    db = tmp_path / "pretend.db"
    _make_pretend_alembic_db(db)
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("")  # 0 字节
    rc = _run_cli_with_mock_db(empty_csv, db)
    assert rc == 1, f"D6.6 P1:空文件应 exit 1,实际 {rc}"


# ===== C3. 不支持的 header =====


def test_cli_exits_1_on_unsupported_header(tmp_path: Path) -> None:
    """D6.6 P1:header 不是 2024/2025/2026 任一版本 → exit 1。"""
    db = tmp_path / "pretend.db"
    _make_pretend_alembic_db(db)
    bad_csv = tmp_path / "unsupported.csv"
    bad_csv.write_text(
        "some,random,columns,that,wechat,doesnt,have\n1,2,3,4,5,6,7\n",
        encoding="utf-8",
    )
    rc = _run_cli_with_mock_db(bad_csv, db)
    assert rc == 1, f"D6.6 P1:unsupported header 应 exit 1,实际 {rc}"


# ===== C4. 坏 CSV(header 对但数据全坏)=====


def test_cli_exits_1_on_corrupt_csv(tmp_path: Path) -> None:
    """D6.6 P1:header 看起来对但数据行全坏(必填字段缺失)→ exit 1(parsed=0)。"""
    db = tmp_path / "pretend.db"
    _make_pretend_alembic_db(db)
    # 2024 header,但完全空行(no data rows)
    corrupt_csv = tmp_path / "corrupt.csv"
    corrupt_csv.write_text(
        "交易时间,交易类型,收/付,金额,支付方式,交易对方,交易号\n",
        encoding="utf-8",
    )
    rc = _run_cli_with_mock_db(corrupt_csv, db)
    assert rc == 1, f"D6.6 P1:corrupt CSV(header 对但 0 数据)应 exit 1,实际 {rc}"


# ===== C5. Alembic revision 过旧 =====


def test_cli_exits_1_on_alembic_revision_too_old(tmp_path: Path) -> None:
    """D6.6 P2:alembic_version < '0007_transactions' → exit 1(防漏迁移)。"""
    db = tmp_path / "old_alembic.db"
    _make_pretend_alembic_db(db, revision="0006_outbox_approval_provenance")
    valid_csv = WECHAT_FIXTURES / "wechat_2024_sample.csv"
    rc = _run_cli_with_mock_db(valid_csv, db)
    assert rc == 1, f"D6.6 P2:alembic revision 过旧应 exit 1,实际 {rc}"


# ===== C6. 正常 2024 样本(成功路径)=====


def test_cli_exits_0_on_valid_csv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D6.6 P1 验证:正常 2024 样本 → exit 0(确保修复不破坏正向路径)。"""
    db = tmp_path / "valid.db"
    _make_pretend_alembic_db(db)
    valid_csv = WECHAT_FIXTURES / "wechat_2024_sample.csv"
    rc = _run_cli_with_mock_db(valid_csv, db)
    captured = capsys.readouterr()
    assert rc == 0, (
        f"D6.6 P1:正常 2024 CSV 应 exit 0,实际 {rc}\nstdout={captured.out}\nstderr={captured.err}"
    )
    # 输出含 parsed/inserted 当前 fixture 行数
    from my_ai_employee.connectors.wechat_csv import WeChatCSVConnector

    expected = len(WeChatCSVConnector().safe_parse(valid_csv))
    assert f"parsed={expected}" in captured.out, f"输出缺 parsed={expected}:{captured.out}"
    assert f"inserted={expected}" in captured.out, f"输出缺 inserted={expected}:{captured.out}"
    assert "version=2024" in captured.out, f"输出缺 version=2024:{captured.out}"


# ===== C7. --max-rows 1 真账单 spike 4 重防误发(2026-06-23 检查员 P0 修复)=====


def test_cli_max_rows_1_limits_to_1_row(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """v0.2.1 #2 真账单 spike 4 重防误发:--max-rows 1 严格只导入 1 行。

    修复历史(检查员 6/22 检查报告 P0):
        CLI 接收 --max-rows 但没有透传 adapter,真账单 spike 时仍全量导入。
        本测试断言:--max-rows 1 → parsed=1 inserted=1(fixture 实际行数 >= 1)。
    """
    db = tmp_path / "maxrows.db"
    _make_pretend_alembic_db(db)
    valid_csv = WECHAT_FIXTURES / "wechat_2024_sample.csv"
    rc = _run_cli_with_mock_db(valid_csv, db, max_rows=1)
    captured = capsys.readouterr()
    assert rc == 0, (
        f"--max-rows 1 应 exit 0(限制成功),实际 {rc}\nstdout={captured.out}\nstderr={captured.err}"
    )
    assert "parsed=1" in captured.out, f"--max-rows 1 应 parsed=1,实际输出:{captured.out}"
    assert "inserted=1" in captured.out, f"--max-rows 1 应 inserted=1,实际输出:{captured.out}"
