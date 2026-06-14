#!/usr/bin/env python3
"""D6.5 — 微信账单 CSV 一键导入入口.

用法:
    uv run python scripts/import_wechat.py --csv-path ~/Downloads/wechat.csv

默认写入项目主 SQLCipher DB。测试 / 演练可传 --db-path 到临时文件。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.core.transaction_adapter import TransactionAdapter  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入微信账单 CSV 到 transactions 表")
    parser.add_argument("--csv-path", required=True, type=Path, help="微信账单 CSV 文件路径")
    parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径,默认主库")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.csv_path.exists():
        print(f"CSV 文件不存在: {args.csv_path}", file=sys.stderr)
        return 2
    if not args.csv_path.is_file():
        print(f"csv-path 不是文件: {args.csv_path}", file=sys.stderr)
        return 2

    db = Database.open(db_path=args.db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        Base.metadata.create_all(engine)
        adapter = TransactionAdapter(sessionmaker(bind=engine))
        result = adapter.import_wechat_csv(args.csv_path)
    finally:
        db.close()

    print(
        "wechat import: "
        f"parsed={result.parsed} inserted={result.inserted} "
        f"categorized={result.categorized} duplicates={result.duplicates} "
        f"needs_confirm={result.needs_confirm} failed={result.failed}"
    )
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
