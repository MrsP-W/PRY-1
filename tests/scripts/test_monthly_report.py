"""D10.2 — monthly_report.py CLI 单元测试(12 cases).

承接 docs/v0.1-launch-plan.md:166-191 D10 段 + 沿 D6.6 import_wechat.py 4 退出码范本 +
D9.2 sync_imap.py subparsers 范本.

测试覆盖(12 cases):
    A. cmd_validate 4 cases
        A1. validate 通过(默认模板含 10 占位符)
        A2. validate 缺占位符模板 → exit 1
        A3. validate 模板不存在 → exit 1
        A4. validate 路径是目录 → exit 1
    B. cmd_generate 6 cases
        B1. generate 缺参数 --month → argparse exit 2
        B2. generate --month 格式错 → exit 1
        B3. generate --month 2026-13 → exit 1
        B4. generate 模板不存在 → exit 1
        B5. generate 数据库无 transactions 行 → exit 2(业务失败)
        B6. generate 数据库 alembic 校验失败 → exit 1
    C. _parse_month 边界 2 cases
        C1. 合法 '2026-06' → (2026, 6)
        C2. 非法 'abc' → ValueError
    D. _month_bounds 1 case
        D1. 2026-02 → (2026-02-01, 2026-02-29) 闰年不闰? 2026 非闰
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# 把 scripts/ 加到 sys.path,让"from scripts import monthly_report"能找到
sys.path.insert(0, str(PROJECT_ROOT))


def _make_pretend_alembic_db(db_path: Path, revision: str = "0007_transactions") -> None:
    """伪造 alembic_version 表(测 CLI alembic 校验).

    不创建 transactions 表 — 留给 Base.metadata.create_all 用真实 ORM schema 建。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))
        conn.commit()
    finally:
        conn.close()


# ===== A. cmd_validate =====

def test_a1_validate_default_template_passes(capsys, monkeypatch):
    """A1. validate 默认模板 → exit 0 + ✅ 校验通过."""
    from scripts import monthly_report

    rc = monthly_report.main(["validate"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "✅ 模板校验通过" in captured.out


def test_a2_validate_missing_placeholder_exits_1(tmp_path, capsys):
    """A2. 缺占位符模板 → exit 1."""
    from scripts import monthly_report

    bad_template = tmp_path / "bad.md"
    bad_template.write_text("# 缺占位符模板\n\n只有 month 占位符 {month}\n", encoding="utf-8")
    rc = monthly_report.main(["validate", "--template", str(bad_template)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "占位符" in captured.err or "缺" in captured.err


def test_a3_validate_template_not_exists_exits_1(capsys):
    """A3. 模板路径不存在 → exit 1."""
    from scripts import monthly_report

    rc = monthly_report.main(["validate", "--template", "/nonexistent/template.md"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "不存在" in captured.err


def test_a4_validate_path_is_dir_exits_1(tmp_path, capsys):
    """A4. 模板路径是目录 → exit 1."""
    from scripts import monthly_report

    rc = monthly_report.main(["validate", "--template", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "不是文件" in captured.err


# ===== B. cmd_generate =====

def test_b1_generate_missing_month_arg_exits_2(capsys):
    """B1. 缺 --month 参数 → argparse exit 2(usage error)."""
    from scripts import monthly_report

    with pytest.raises(SystemExit) as exc_info:
        monthly_report.main(["generate"])
    assert exc_info.value.code == 2


def test_b2_generate_invalid_month_format_exits_1(capsys):
    """B2. --month 格式错(不是 YYYY-MM)→ exit 1."""
    from scripts import monthly_report

    rc = monthly_report.main(["generate", "--month", "2026/06"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "YYYY-MM" in captured.err


def test_b3_generate_invalid_month_value_exits_1(capsys):
    """B3. --month 2026-13(月越界)→ exit 1."""
    from scripts import monthly_report

    rc = monthly_report.main(["generate", "--month", "2026-13"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "越界" in captured.err or "month" in captured.err


def test_b4_generate_template_not_exists_exits_1(capsys):
    """B4. 模板不存在 → exit 1."""
    from scripts import monthly_report

    rc = monthly_report.main(
        [
            "generate",
            "--month", "2026-06",
            "--template", "/nonexistent/template.md",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "不存在" in captured.err


def test_b5_generate_no_transactions_exits_2(tmp_path, capsys, monkeypatch):
    """B5. transactions 表 0 行 → exit 2(业务失败)."""
    from scripts import monthly_report
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / "v0.1.db"
    _make_pretend_alembic_db(db_path)  # alembic_version 验过 + transactions 表空

    # 用真实 ORM schema 创建表(create_all 走 Base.metadata)
    from my_ai_employee.core.models import Base
    import my_ai_employee.db.transactions  # noqa: F401  # 触发 Transaction 16 列注册

    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    fake_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    fake_db = type("DB", (), {"close": lambda self: None})()

    monkeypatch.setattr(
        monthly_report,
        "_open_session_factory",
        lambda db_path, no_encrypt=False: (fake_factory, fake_db),
    )

    rc = monthly_report.main(
        [
            "generate",
            "--month", "2026-06",
            "--db-path", str(db_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "0 笔交易" in captured.err or "业务失败" in captured.err


def test_b6_generate_alembic_too_old_exits_1(tmp_path, capsys, monkeypatch):
    """B6. alembic_version < '0007_transactions' → exit 1."""
    from scripts import monthly_report

    # 模拟 alembic 校验失败的场景
    def fake_open_raises(db_path, no_encrypt=False):
        raise RuntimeError(f"alembic_version '0006_old' < '0007_transactions'")

    monkeypatch.setattr(
        monthly_report, "_open_session_factory", fake_open_raises
    )

    rc = monthly_report.main(
        [
            "generate",
            "--month", "2026-06",
            "--db-path", str(tmp_path / "dummy.db"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "Alembic" in captured.err or "alembic" in captured.err


# ===== C. _parse_month 边界 =====

def test_c1_parse_month_valid():
    """C1. 合法 '2026-06' → (2026, 6)."""
    from scripts import monthly_report
    assert monthly_report._parse_month("2026-06") == (2026, 6)


def test_c2_parse_month_invalid_raises():
    """C2. 非法 'abc' → ValueError."""
    from scripts import monthly_report
    with pytest.raises(ValueError):
        monthly_report._parse_month("abc")


# ===== D. _month_bounds =====

def test_d1_month_bounds_non_leap():
    """D1. 2026-02(非闰年)→ (2026-02-01, 2026-02-28)."""
    from scripts import monthly_report
    first, last = monthly_report._month_bounds(2026, 2)
    assert first == date(2026, 2, 1)
    assert last == date(2026, 2, 28)


def test_d2_month_bounds_december_year_boundary():
    """D2. 12 月跨年边界(2026-12 → 2026-12-31)."""
    from scripts import monthly_report
    first, last = monthly_report._month_bounds(2026, 12)
    assert first == date(2026, 12, 1)
    assert last == date(2026, 12, 31)
