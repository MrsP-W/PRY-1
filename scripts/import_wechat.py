#!/usr/bin/env python3
"""D6.5 + D6.6 — 微信账单 CSV 一键导入入口.

用法:
    uv run python scripts/import_wechat.py --csv-path ~/Downloads/wechat.csv

D6.6 P1 修复(检查员驳回 4 缺陷 — 1 P1 + 3 P2):
    - P1 解析失败静默成功:pre-flight detect_version 嗅探,失败 → exit 1
    - P2 CLI 不走 Alembic:启动校验 alembic_version >= '0007_transactions',失败 → exit 1
    - P2 原子性:沿 TransactionStore.insert_and_advance_status(单事务)
    - P2 多候选信息:result.candidate_count + candidate_ids + failed_items

退出码(沿 D5.6.5 范本):
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
sys.path.insert(0, str(PROJECT_ROOT))  # 让直接运行脚本时可 import scripts.* 包

from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.connectors.wechat_csv import (  # noqa: E402
    UnsupportedCSVVersionError,
    detect_version,
)
from my_ai_employee.core.alembic_helper import assert_min_revision  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.core.transaction_adapter import TransactionAdapter  # noqa: E402
from scripts.import_real_gate import validate_real_import_gate  # noqa: E402

# D6.6 锁定:微信账单所需最低 alembic revision(0007_transactions)
_MIN_ALEMBIC_REVISION: str = "0007_transactions"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入微信账单 CSV 到 transactions 表")
    parser.add_argument("--csv-path", required=True, type=Path, help="微信账单 CSV 文件路径")
    parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径,默认主库")
    # v0.2.1 #2 真账单 spike 4 重防误发参数(沿 D6.6 范本)
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="限制单次导入行数(默认 None = 全量;spike 时通常 1)",
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default="",
        help="确认文本(沿 D6.6 4 重防误发:必传 'yes-i-understand-this-imports-real-bill')",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="限制总批次数(默认 1;spike 时锁定 1 防止误触发)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    gate_err = validate_real_import_gate(
        env_name="WECHAT_REAL_IMPORT",
        confirm=args.confirm,
        count=args.count,
        max_rows=args.max_rows,
    )
    if gate_err:
        print(gate_err, file=sys.stderr)
        return 1

    if not args.csv_path.exists():
        print(f"CSV 文件不存在: {args.csv_path}", file=sys.stderr)
        return 1
    if not args.csv_path.is_file():
        print(f"csv-path 不是文件: {args.csv_path}", file=sys.stderr)
        return 1

    # D6.6 P1 修复:先做只读 pre-flight 嗅探，失败时绝不打开 SQLCipher。
    # Database.open() 可能创建目录、写入 Keychain/WAL；无效 CSV 不应触发这些副作用。
    try:
        version = detect_version(args.csv_path)
    except UnsupportedCSVVersionError as e:
        print(f"无法嗅探微信账单 CSV 版本: {e}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f"CSV 读取失败: {e}", file=sys.stderr)
        return 1

    db = Database.open(db_path=args.db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        # D6.6 P2 修复:CLI 启动校验 alembic_version >= '0007_transactions'
        # 防止在旧 DB 上漏迁移(导致 transactions 表不存在)
        try:
            assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
        except RuntimeError as e:
            print(f"Alembic version 校验失败: {e}", file=sys.stderr)
            print("请先跑: alembic upgrade head", file=sys.stderr)
            return 1

        # create_all 仍保留(D6.4 兼容 — 走 alembic 后,这里是 no-op)
        Base.metadata.create_all(engine)
        adapter = TransactionAdapter(sessionmaker(bind=engine))

        try:
            # v0.2.1 #2 真账单 spike 4 重防误发:--max-rows 透传 adapter
            # CLI 默认 max_rows=None = 全量;WECHAT_REAL_IMPORT=1 + --max-rows 1 限 1 行
            result = adapter.import_wechat_csv(args.csv_path, max_rows=args.max_rows)
        except OperationalError as e:
            # D3.3.3 教训:OperationalError 必透传(DB 锁 / 连接错误)
            print(f"数据库技术失败(DB 锁或连接错误): {e}", file=sys.stderr)
            return 3
    finally:
        db.close()

    print(
        "wechat import: "
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

    # D6.6 P1 修复:严格退出码
    if result.parsed == 0:
        # pre-flight 嗅探成功 + 但 0 解析 = 解析失败静默成功
        # (如 2026 parser 抛 NotImplementedError,2024/2025 内容全空等)
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
