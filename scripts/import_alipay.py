#!/usr/bin/env python3
"""D7.5 — 支付宝账单 CSV 一键导入入口(沿 D6.5 import_wechat 范本).

用法:
    uv run python scripts/import_alipay.py --csv-path ~/Downloads/alipay.csv

D7.5 沿用 D6.6 P1/P2 修复契约(0 schema 变更,纯 CLI 复用):
    - P1 解析失败静默成功:pre-flight detect_version 嗅探,失败 → exit 1
    - P2 CLI 不走 Alembic:启动校验 alembic_version >= '0007_transactions',失败 → exit 1
    - P2 原子性:沿 TransactionStore.insert_and_advance_status(单事务)
    - P2 多候选信息:result.candidate_count + candidate_ids + failed_items

退出码(沿 D5.6.5 + D6.6 范本):
    0 = 成功(parsed > 0 且 failed == 0)
    1 = 解析失败(文件不存在 / 嗅探失败 / 解析 0 行 / Alembic 不通过)
    2 = 业务失败(result.failed > 0)
    3 = 技术失败(OperationalError 透传,DB 锁/连接错误)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.connectors.alipay_csv import (  # noqa: E402
    UnsupportedCSVVersionError,
    detect_version,
)
from my_ai_employee.core.alembic_helper import assert_min_revision  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.core.transaction_adapter import TransactionAdapter  # noqa: E402

# D6.6 锁定:支付宝账单所需最低 alembic revision(0007_transactions,沿 D6 沿用)
_MIN_ALEMBIC_REVISION: str = "0007_transactions"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入支付宝账单 CSV 到 transactions 表")
    parser.add_argument("--csv-path", required=True, type=Path, help="支付宝账单 CSV 文件路径")
    parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径,默认主库")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.csv_path.exists():
        print(f"CSV 文件不存在: {args.csv_path}", file=sys.stderr)
        return 1
    if not args.csv_path.is_file():
        print(f"csv-path 不是文件: {args.csv_path}", file=sys.stderr)
        return 1

    db = Database.open(db_path=args.db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        # D6.6 P2 修复:CLI 启动校验 alembic_version >= '0007_transactions'
        try:
            assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
        except RuntimeError as e:
            print(f"Alembic version 校验失败: {e}", file=sys.stderr)
            print("请先跑: alembic upgrade head", file=sys.stderr)
            return 1

        # D6.6 P1 修复:pre-flight detect_version 嗅探(防 silent success)
        try:
            version = detect_version(args.csv_path)
        except UnsupportedCSVVersionError as e:
            print(f"无法嗅探支付宝账单 CSV 版本: {e}", file=sys.stderr)
            return 1
        except (FileNotFoundError, ValueError, OSError) as e:
            print(f"CSV 读取失败: {e}", file=sys.stderr)
            return 1

        Base.metadata.create_all(engine)
        adapter = TransactionAdapter(sessionmaker(bind=engine))

        try:
            result = adapter.import_alipay_csv(args.csv_path)
        except OperationalError as e:
            print(f"数据库技术失败(DB 锁或连接错误): {e}", file=sys.stderr)
            return 3
    finally:
        db.close()

    print(
        "alipay import: "
        f"parsed={result.parsed} inserted={result.inserted} "
        f"categorized={result.categorized} duplicates={result.duplicates} "
        f"needs_confirm={result.needs_confirm} failed={result.failed} "
        f"candidate_count={result.candidate_count} "
        f"version={version}"
    )
    if result.failed_items:
        for item in result.failed_items:
            print(
                f"  failed_item: ext_id={item.external_transaction_id!r} "
                f"error_type={item.error_type!r} error={item.error_message!r}",
                file=sys.stderr,
            )

    if result.parsed == 0:
        print(
            f"解析失败: 0 行解析成功(version={version}),"
            f"请检查文件格式(字段缺失 / 编码 / 版本不匹配)",
            file=sys.stderr,
        )
        return 1
    if result.failed > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
