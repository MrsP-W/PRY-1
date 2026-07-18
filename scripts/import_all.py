#!/usr/bin/env python3
"""D7.6 — 统一账单导入调度器(遍历 connectors/ 自动发现 source).

承接 docs/v0.1-launch-plan.md §7 5 扩展点 #3:
    - D6 阶段未创建 import_all.py(预留)
    - D7.6 落地,统一调度 wechat + alipay (及未来 jd / bank 等)
    - 沿 D6.6 import_wechat 范本 + D6.6 4 重防误发 + WECHAT_REAL_IMPORT=1 env 门控

用法:
    # 默认 dry-run(只嗅探不导入,沿 D5.6.5 4 重防误发)
    uv run python scripts/import_all.py --csv-dir ~/Downloads/bills

    # 真实导入(需 env 门控 + 4 重防误发)
    export BILLS_REAL_IMPORT=1
    uv run python scripts/import_all.py --csv-dir ~/Downloads/bills --confirm "yes-i-understand"

退出码(沿 D6.6 范本):
    0 = 全部成功
    1 = 解析失败 / Alembic 不通过
    2 = 业务失败(有 failed_items)
    3 = 技术失败(OperationalError 透传)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import sqlcipher3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.exc import OperationalError, SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.connectors.alipay_csv import (  # noqa: E402
    UnsupportedCSVVersionError as AlipayUnsupportedVersionError,
)
from my_ai_employee.connectors.alipay_csv import (  # noqa: E402
    detect_version as detect_alipay_version,
)
from my_ai_employee.connectors.wechat_csv import (  # noqa: E402
    UnsupportedCSVVersionError as WechatUnsupportedVersionError,
)
from my_ai_employee.connectors.wechat_csv import (  # noqa: E402
    detect_version as detect_wechat_version,
)
from my_ai_employee.core.alembic_helper import (  # noqa: E402
    AlembicTechnicalError,
    assert_min_revision,
)
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.core.transaction_adapter import (  # noqa: E402
    TransactionAdapter,
    TransactionImportResult,
)
from scripts.import_real_gate import (  # noqa: E402
    REQUIRED_CONFIRM,
    validate_real_import_gate,
)

_MIN_ALEMBIC_REVISION: str = "0007_transactions"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="统一账单导入调度器(遍历 connectors/ 自动发现 source)"
    )
    parser.add_argument(
        "--csv-dir",
        required=True,
        type=Path,
        help="账单 CSV 所在目录(自动嗅探 wechat / alipay)",
    )
    parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径,默认主库")
    parser.add_argument(
        "--confirm",
        type=str,
        default="",
        help=f"真实导入确认(必须传 {REQUIRED_CONFIRM!r})",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="限制单次每个 CSV 的导入行数(真实导入必须为 1)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="限制总批次数(真实导入必须为 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="默认 dry-run:只嗅探不导入(防误触发)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_false",
        dest="dry_run",
        help="真实导入(需 BILLS_REAL_IMPORT=1 env + --confirm)",
    )
    return parser


def _sniff_source(csv_path: Path) -> str | None:
    """嗅探 CSV 来源(wechat / alipay / None)."""
    # 尝试微信嗅探
    try:
        detect_wechat_version(csv_path)
        return "wechat"
    except (WechatUnsupportedVersionError, FileNotFoundError, ValueError, OSError):
        pass
    # 尝试支付宝嗅探
    try:
        detect_alipay_version(csv_path)
        return "alipay"
    except (AlipayUnsupportedVersionError, FileNotFoundError, ValueError, OSError):
        return None


def _recognized_csv_files(csv_files: list[Path]) -> list[tuple[Path, str]]:
    """返回可导入的 CSV 与来源，供真实导入在开库前做总批次数门控。"""
    recognized: list[tuple[Path, str]] = []
    for csv_path in csv_files:
        source = _sniff_source(csv_path)
        if source is not None:
            recognized.append((csv_path, source))
    return recognized


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.csv_dir.exists():
        print(f"CSV 目录不存在: {args.csv_dir}", file=sys.stderr)
        return 1
    if not args.csv_dir.is_dir():
        print(f"csv-dir 不是目录: {args.csv_dir}", file=sys.stderr)
        return 1

    # 4 重防误发：真实导入必须复用单源入口的统一 fail-closed 契约。
    real_import = not args.dry_run
    if real_import:
        gate_error = validate_real_import_gate(
            env_name="BILLS_REAL_IMPORT",
            confirm=args.confirm,
            count=args.count,
            max_rows=args.max_rows,
        )
        if gate_error:
            print(gate_error, file=sys.stderr)
            return 1

    # 遍历 csv_dir 下所有 .csv 文件。dry-run 只允许到嗅探为止，不能打开
    # SQLCipher：Database.open() 可能创建目录、写入 Keychain/WAL。
    csv_files = sorted(args.csv_dir.glob("*.csv"))
    if not csv_files:
        print(f"未发现任何 .csv 文件: {args.csv_dir}", file=sys.stderr)
        return 1

    if not real_import:
        recognized_count = 0
        for csv_path in csv_files:
            source = _sniff_source(csv_path)
            if source is None:
                print(f"[SKIP] 无法识别来源: {csv_path}", file=sys.stderr)
                continue
            recognized_count += 1
            print(f"[{source}] {csv_path.name}")
            print("  [DRY-RUN] 跳过实际导入")
        if recognized_count == 0:
            print(f"未发现可识别的账单 CSV: {args.csv_dir}", file=sys.stderr)
            return 1
        print(f"\n汇总: files={recognized_count} parsed=0 inserted=0 failed=0")
        return 0

    # ``--count=1`` 必须限制整次真实写入，而非仅限制每个 CSV 的行数。
    # 先只读嗅探并拒绝多文件批次，保证失败路径绝不打开 SQLCipher 数据库。
    recognized_csv_files = _recognized_csv_files(csv_files)
    if len(csv_files) != args.count or len(recognized_csv_files) != args.count:
        print(
            "❌ BILLS_REAL_IMPORT=1 时 "
            f"--count={args.count} 要求目录恰好包含 {args.count} 个可识别 CSV(防误触发),"
            f"实际 CSV 文件 {len(csv_files)} 个、可识别 {len(recognized_csv_files)} 个",
            file=sys.stderr,
        )
        return 1

    # 仅真实导入通过全部门控后才允许触碰数据库。
    # 单源入口已将 Database.open() 的 Keychain/SQLCipher/目录错误映射为
    # exit 3；批量入口必须保持同一技术失败契约，且不得泄漏 traceback。
    try:
        db = Database.open(db_path=args.db_path)
    except (OSError, sqlcipher3.DatabaseError) as e:
        print(f"数据库技术失败(DB 打开、锁或连接错误): {e}", file=sys.stderr)
        return 3
    try:
        engine = make_sqlalchemy_engine(db)
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

        total_parsed = 0
        total_inserted = 0
        total_failed = 0
        results: list[tuple[Path, str, TransactionImportResult]] = []
        try:
            for csv_path, source in recognized_csv_files:
                print(f"[{source}] {csv_path.name}")
                if source == "wechat":
                    result = adapter.import_wechat_csv(csv_path, max_rows=args.max_rows)
                elif source == "alipay":
                    result = adapter.import_alipay_csv(csv_path, max_rows=args.max_rows)
                else:
                    continue
                results.append((csv_path, source, result))
                total_parsed += result.parsed
                total_inserted += result.inserted
                total_failed += result.failed
        except OperationalError as e:
            print(f"数据库技术失败(DB 锁或连接错误): {e}", file=sys.stderr)
            return 3
    except SQLAlchemyError as e:
        print(f"数据库技术失败(DB 打开、锁或连接错误): {e}", file=sys.stderr)
        return 3
    finally:
        db.close()

    print(
        f"\n汇总: files={len(results)} "
        f"parsed={total_parsed} inserted={total_inserted} failed={total_failed}"
    )
    if total_failed > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
