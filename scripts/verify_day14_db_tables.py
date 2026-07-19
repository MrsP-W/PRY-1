"""Day 1.4 只读验收 — transactions / notes / outbox 三表 schema · 索引 · 行数.

不写库 · 不跑迁移 · 只读 SELECT / PRAGMA。
沿 D5.6.5 4 重防误发范本:默认只检查,任何写操作均不在本脚本内。

用法:
    uv run python scripts/verify_day14_db_tables.py
    make setup-verify-db

退出码:
    0 — 三表存在且 schema/索引契约满足(行数可为 0)
    1 — schema 或索引漂移
    2 — DB 不可打开 / 表缺失 / Keychain 不可用
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from my_ai_employee.core.config import load_env  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402

# 三表契约(列名集合,沿 ORM __tablename__ + migration 范本)
TABLE_CONTRACTS: dict[str, dict[str, Any]] = {
    "transactions": {
        "required_columns": frozenset(
            {
                "id",
                "source",
                "external_transaction_id",
                "transaction_date",
                "amount",
                "counterparty",
                "category",
                "payment_method",
                "normalized_fingerprint",
                "needs_confirm",
                "candidate_match_id",
                "status",
                "imported_at_ms",
                "confirmed_at_ms",
                "raw_row_json",
                "notes",
            }
        ),
        "required_indexes": frozenset(
            {
                "idx_transactions_fingerprint",
                "idx_transactions_status_imported",
            }
        ),
        "required_unique": (("source", "external_transaction_id"),),
    },
    "notes": {
        "required_columns": frozenset(
            {
                "id",
                "apple_note_id",
                "folder",
                "title",
                "body",
                "attachments_json",
                "is_private",
                "tags",
                "synced_at_ms",
                "updated_at_ms",
                "sync_status",
                "normalized_fingerprint",
                "needs_confirm",
                "candidate_match_id",
                "note_source",
            }
        ),
        "required_indexes": frozenset(
            {
                "idx_notes_folder_synced",
                "idx_notes_updated",
                "idx_notes_sync_status",
                "idx_notes_fingerprint",
                "idx_notes_needs_confirm",
                "idx_notes_source_updated",
            }
        ),
        "required_unique": (("apple_note_id",),),
    },
    "outbox": {
        "required_columns": frozenset(
            {
                "id",
                "email_id",
                "subject",
                "body",
                "tone",
                "reviewer_decision_event_id",
                "drafter_decision_event_id",
                "status",
                "created_at",
                "recipient_email",
                "priority",
                "last_approved_at_ms",
                "sla_due_at_ms",
            }
        ),
        "required_indexes": frozenset(
            {
                "idx_outbox_status_created_at",
                "idx_outbox_priority_created_at",
                "idx_outbox_sla_due_at",
            }
        ),
        "required_unique": (("email_id",),),
    },
}


@dataclass(frozen=True, slots=True)
class TableReport:
    """单表只读验收报告."""

    name: str
    row_count: int
    columns: frozenset[str]
    indexes: frozenset[str]
    missing_columns: frozenset[str]
    missing_indexes: frozenset[str]
    missing_unique: tuple[tuple[str, ...], ...]

    @property
    def ok(self) -> bool:
        return not self.missing_columns and not self.missing_indexes and not self.missing_unique


def _unique_column_sets(db: Database, table: str) -> set[tuple[str, ...]]:
    """PRAGMA index_list(unique=1) → 各唯一索引覆盖列元组."""
    found: set[tuple[str, ...]] = set()
    for idx in db.execute(f"PRAGMA index_list({table})").fetchall():
        if not idx["unique"]:
            continue
        cols = db.execute(f"PRAGMA index_info('{idx['name']}')").fetchall()
        found.add(tuple(str(c["name"]) for c in cols))
    return found


def _table_columns(db: Database, table: str) -> frozenset[str]:
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    return frozenset(str(row["name"]) for row in rows)


def _table_indexes(db: Database, table: str) -> frozenset[str]:
    rows = db.execute(f"PRAGMA index_list({table})").fetchall()
    return frozenset(str(row["name"]) for row in rows)


def _table_exists(db: Database, table: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def inspect_table(db: Database, table: str) -> TableReport | str:
    """检查单表;表缺失时返回错误文案."""
    if not _table_exists(db, table):
        return f"表缺失: {table}(请先 make alembic-upgrade-head)"
    contract = TABLE_CONTRACTS[table]
    columns = _table_columns(db, table)
    indexes = _table_indexes(db, table)
    row = db.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    count = int(row["c"]) if row else 0
    missing_cols = frozenset(contract["required_columns"]) - columns
    missing_idx = frozenset(contract["required_indexes"]) - indexes
    uniques = _unique_column_sets(db, table)
    missing_unique = tuple(u for u in contract.get("required_unique", ()) if u not in uniques)
    return TableReport(
        name=table,
        row_count=count,
        columns=columns,
        indexes=indexes,
        missing_columns=missing_cols,
        missing_indexes=missing_idx,
        missing_unique=missing_unique,
    )


def verify_all_tables(*, db_path: Path | None = None) -> tuple[list[TableReport], list[str]]:
    """打开 DB 只读验收三表;返回 (报告列表, 硬错误列表)."""
    errors: list[str] = []
    reports: list[TableReport] = []
    try:
        db = Database.open(db_path) if db_path else Database.open()
    except (PermissionError, OSError) as exc:
        return [], [f"DB 不可打开: {exc}"]
    try:
        for table in TABLE_CONTRACTS:
            result = inspect_table(db, table)
            if isinstance(result, str):
                errors.append(result)
                continue
            reports.append(result)
    finally:
        db.close()
    return reports, errors


def print_report(reports: list[TableReport], *, verbose: bool = False) -> None:
    """打印人类可读报告."""
    print("Day 1.4 只读验收 — transactions / notes / outbox")
    print("=" * 60)
    for rep in reports:
        status = "OK" if rep.ok else "DRIFT"
        print(f"\n[{status}] {rep.name}")
        print(f"  行数: {rep.row_count}")
        if rep.missing_columns:
            print(f"  缺列: {sorted(rep.missing_columns)}")
        if rep.missing_indexes:
            print(f"  缺索引: {sorted(rep.missing_indexes)}")
        if rep.missing_unique:
            print(f"  缺唯一约束: {list(rep.missing_unique)}")
        if verbose and rep.ok:
            print(f"  列数: {len(rep.columns)} · 索引数: {len(rep.indexes)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Day 1.4 三表只读验收(不写库)")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="打印额外列/索引计数",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="机器可读 JSON 一行输出",
    )
    args = parser.parse_args(argv)
    load_env()

    reports, errors = verify_all_tables()
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 2

    drift = [r for r in reports if not r.ok]
    if args.json:
        import json

        payload = {
            "ok": not drift,
            "tables": [
                {
                    "name": r.name,
                    "row_count": r.row_count,
                    "missing_columns": sorted(r.missing_columns),
                    "missing_indexes": sorted(r.missing_indexes),
                    "missing_unique": [list(u) for u in r.missing_unique],
                }
                for r in reports
            ],
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print_report(reports, verbose=args.verbose)

    if drift:
        return 1
    print("\n✅ 三表 schema/索引契约满足(只读验收,未写入)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
