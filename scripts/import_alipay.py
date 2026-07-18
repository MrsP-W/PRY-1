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
    3 = 技术失败(DB 打开、锁或连接错误)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sqlcipher3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))  # 让直接运行脚本时可 import scripts.* 包

from sqlalchemy.exc import OperationalError, SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.connectors.alipay_csv import (  # noqa: E402
    UnsupportedCSVVersionError,
    detect_version,
)
from my_ai_employee.core.alembic_helper import (  # noqa: E402
    AlembicTechnicalError,
    assert_min_revision,
)
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.core.transaction_adapter import TransactionAdapter  # noqa: E402
from scripts.import_real_gate import validate_real_import_gate  # noqa: E402

# D6.6 锁定:支付宝账单所需最低 alembic revision(0007_transactions,沿 D6 沿用)
_MIN_ALEMBIC_REVISION: str = "0007_transactions"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入支付宝账单 CSV 到 transactions 表")
    parser.add_argument("--csv-path", required=True, type=Path, help="支付宝账单 CSV 文件路径")
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
    parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径,默认主库")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    gate_err = validate_real_import_gate(
        env_name="ALIPAY_REAL_IMPORT",
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

    # D7.5 沿用 D6.6:先做只读 pre-flight 嗅探，失败时绝不打开 SQLCipher。
    # Database.open() 可能创建目录、写入 Keychain/WAL；无效 CSV 不应触发这些副作用。
    try:
        version = detect_version(args.csv_path)
    except UnsupportedCSVVersionError as e:
        print(f"无法嗅探支付宝账单 CSV 版本: {e}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f"CSV 读取失败: {e}", file=sys.stderr)
        return 1

    try:
        db = Database.open(db_path=args.db_path)
    except (OSError, sqlcipher3.DatabaseError) as e:
        # Database.open() 可能因 Keychain、目录或 SQLCipher 校验失败而中断；
        # CLI 必须保持技术失败 exit 3 契约，不能泄漏 traceback。
        print(f"数据库技术失败(DB 打开、锁或连接错误): {e}", file=sys.stderr)
        return 3
    try:
        engine = make_sqlalchemy_engine(db)
        # D6.6 P2 修复:CLI 启动校验 alembic_version >= '0007_transactions'
        try:
            assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
        except AlembicTechnicalError as e:
            print(f"数据库技术失败(DB 打开、锁或连接错误): {e}", file=sys.stderr)
            return 3
        except RuntimeError as e:
            print(f"Alembic version 校验失败: {e}", file=sys.stderr)
            print("请先跑: alembic upgrade head", file=sys.stderr)
            return 1

        Base.metadata.create_all(engine)
        adapter = TransactionAdapter(sessionmaker(bind=engine))

        try:
            # v0.2.1 #2 真账单 spike 4 重防误发:--max-rows 透传 adapter
            # CLI 默认 max_rows=None = 全量;ALIPAY_REAL_IMPORT=1 + --max-rows 1 限 1 行
            result = adapter.import_alipay_csv(args.csv_path, max_rows=args.max_rows)
        except OperationalError as e:
            print(f"数据库技术失败(DB 锁或连接错误): {e}", file=sys.stderr)
            return 3
    except SQLAlchemyError as e:
        print(f"数据库技术失败(DB 打开、锁或连接错误): {e}", file=sys.stderr)
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
