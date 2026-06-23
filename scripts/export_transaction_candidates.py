#!/usr/bin/env python3
"""v0.2.29 — 导出 transactions 待确认候选供人工 review.

用途:
    W3 真账单导入后,把 needs_confirm=1 的跨源候选导出为 JSONL/CSV,
    供用户人工确认同日同金额同商户同方向的合理业务碰撞。

只读边界:
    - 不导入账单
    - 不修改 transactions
    - 不自动确认 / 合并 / 删除候选

用法:
    uv run python scripts/export_transaction_candidates.py --format jsonl
    uv run python scripts/export_transaction_candidates.py --format csv --output-path reports/candidates.csv

退出码:
    0 = 成功导出(包括 0 条候选)
    1 = 参数 / Alembic 校验失败
    3 = 数据库技术失败
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.core.alembic_helper import assert_min_revision  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.transactions import Transaction, TransactionStore  # noqa: E402

_MIN_ALEMBIC_REVISION = "0007_transactions"
_FIELDNAMES = [
    "tx_id",
    "source",
    "external_transaction_id",
    "transaction_date",
    "amount",
    "counterparty",
    "category",
    "payment_method",
    "status",
    "imported_at_ms",
    "normalized_fingerprint",
    "candidate_match_id",
    "candidate_missing",
    "candidate_source",
    "candidate_external_transaction_id",
    "candidate_transaction_date",
    "candidate_amount",
    "candidate_counterparty",
    "candidate_category",
    "candidate_payment_method",
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导出 transactions needs_confirm=1 候选")
    parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径,默认主库")
    parser.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        default="jsonl",
        help="输出格式,默认 jsonl",
    )
    parser.add_argument("--output-path", type=Path, default=None, help="输出文件,默认 stdout")
    parser.add_argument("--limit", type=int, default=1000, help="导出上限 [1,10000]")
    parser.add_argument("--source", type=str, default=None, help="可选限定 source")
    return parser


def _validate_cli_args(args: argparse.Namespace) -> None:
    """CLI 入参预检,失败时返回可读错误而非 DB 打开后的 traceback."""
    if type(args.limit) is bool or not isinstance(args.limit, int) or args.limit < 1:
        raise ValueError(f"--limit 必须是 >= 1 的 int,实际 {args.limit!r}")
    if args.limit > 10000:
        raise ValueError(f"--limit 必须 <= 10000,实际 {args.limit!r}")
    if args.source is not None:
        source = args.source.strip()
        if not source:
            raise ValueError("--source 必须是非空字符串")
        args.source = source


def _scalar(value: Any) -> Any:
    """把 DB 标量转成 JSON/CSV 稳定值."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def build_candidate_review_row(tx: Transaction, candidate: Transaction | None) -> dict[str, Any]:
    """构造单条人工 review 行,字段固定便于 CSV/JSONL 双输出."""
    row = {
        "tx_id": tx.id,
        "source": tx.source,
        "external_transaction_id": tx.external_transaction_id,
        "transaction_date": _scalar(tx.transaction_date),
        "amount": _scalar(tx.amount),
        "counterparty": tx.counterparty,
        "category": tx.category,
        "payment_method": tx.payment_method,
        "status": tx.status,
        "imported_at_ms": tx.imported_at_ms,
        "normalized_fingerprint": tx.normalized_fingerprint,
        "candidate_match_id": tx.candidate_match_id,
        "candidate_missing": candidate is None,
        "candidate_source": None,
        "candidate_external_transaction_id": None,
        "candidate_transaction_date": None,
        "candidate_amount": None,
        "candidate_counterparty": None,
        "candidate_category": None,
        "candidate_payment_method": None,
    }
    if candidate is not None:
        row.update(
            {
                "candidate_source": candidate.source,
                "candidate_external_transaction_id": candidate.external_transaction_id,
                "candidate_transaction_date": _scalar(candidate.transaction_date),
                "candidate_amount": _scalar(candidate.amount),
                "candidate_counterparty": candidate.counterparty,
                "candidate_category": candidate.category,
                "candidate_payment_method": candidate.payment_method,
            }
        )
    return row


def _write_rows(rows: list[dict[str, Any]], *, output_format: str, output_path: Path | None) -> None:
    if output_path is None:
        out = sys.stdout
        close_out = False
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out = output_path.open("w", encoding="utf-8", newline="")
        close_out = True

    try:
        if output_format == "jsonl":
            for row in rows:
                out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        else:
            writer = csv.DictWriter(out, fieldnames=_FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
    finally:
        if close_out:
            out.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        _validate_cli_args(args)
    except ValueError as e:
        print(f"参数错误: {e}", file=sys.stderr)
        return 1

    db = Database.open(db_path=args.db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        try:
            assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
        except RuntimeError as e:
            print(f"Alembic version 校验失败: {e}", file=sys.stderr)
            print("请先跑: alembic upgrade head", file=sys.stderr)
            return 1

        store = TransactionStore(sessionmaker(bind=engine))
        try:
            pending = store.list_by_needs_confirm(limit=args.limit, source_filter=args.source)
            rows = [
                build_candidate_review_row(
                    tx,
                    store.get_by_id(tx.candidate_match_id) if tx.candidate_match_id else None,
                )
                for tx in pending
            ]
        except OperationalError as e:
            print(f"数据库技术失败(DB 锁或连接错误): {e}", file=sys.stderr)
            return 3
    finally:
        db.close()

    _write_rows(rows, output_format=args.format, output_path=args.output_path)
    target = str(args.output_path) if args.output_path is not None else "stdout"
    print(
        f"transaction candidates export: exported={len(rows)} format={args.format} target={target}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
