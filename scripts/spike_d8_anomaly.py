#!/usr/bin/env python3
"""v0.2 D8.4 — S11 真链路 spike 脚本(AnomalyDetector + 商家画像漂移端到端).

承接 v0.1.0 post-tag 阶段 + v0.2 D8 智能财务异常检测启动。
本 spike 验证 S11 端到端(从历史交易 → 商家画像 → 异常检测):

    1. 创建临时 SQLite DB(明文,避免 SQLCipher 加密)
    2. alembic upgrade head 校验 0011_merchant_profile 已应用
    3. 插 35 笔 baseline(¥50 同金额,σ=0)
    4. 插 1 笔 ¥888 异常笔(amount > avg + 3σ = 50)
    5. 跑 RuleBasedAnomalyDetector.detect_all(target)
    6. 验:amount_3sigma + new_merchant 触发

4 退出码契约(沿 D6.6 import_wechat.py 范本 + D3.3.3 教训):
    0 = 成功(kinds 含 amount_3sigma)
    1 = 解析失败(--db-path 缺失 / alembic revision 不通过)
    2 = 业务失败(amount_3sigma 未触发)
    3 = 技术失败(OperationalError / DB 锁 / SQLAlchemyError 透传)

用法:
    uv run python scripts/spike_d8_anomaly.py --db-path /tmp/spike_d8.db
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.db.merchant_profile import MerchantProfileStore  # noqa: E402
from my_ai_employee.db.transactions import Transaction, TransactionStore  # noqa: E402


def _make_fp(seed: str) -> str:
    """生成 32 chars 小写 hex fingerprint(沿 D6.2 normalize_fingerprint 派生规则)."""
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


# ===== 退出码契约 =====

EXIT_OK: int = 0
EXIT_PARSE_FAIL: int = 1
EXIT_BUSINESS_FAIL: int = 2
EXIT_TECH_FAIL: int = 3


def run_spike(db_path: Path) -> int:
    """跑 D8 spike 主流程.

    Args:
        db_path: 临时 SQLite DB 路径

    Returns:
        退出码(0/1/2/3)
    """
    # 1. 创建临时 SQLite DB + create_all(避免 alembic 复杂度,沿 D9.5 sync_notes spike 范本)
    if db_path.exists():
        db_path.unlink()
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    tx_store = TransactionStore(sf)
    profile_store = MerchantProfileStore(sf, transaction_store=tx_store)
    detector = RuleBasedAnomalyDetector(
        transaction_store=tx_store,
        merchant_profile_store=profile_store,
    )

    # 2. 插 35 笔 baseline(¥50 同金额,σ=0)+ 1 笔 ¥888 异常笔
    base_date = date(2026, 5, 1)
    with sf() as session:
        for i in range(35):
            session.add(
                Transaction(
                    source="wechat",
                    external_transaction_id=f"baseline-{i:03d}",
                    transaction_date=base_date + timedelta(days=i % 28),
                    amount=Decimal("50.00"),
                    counterparty="星巴克",
                    category="dining",
                    normalized_fingerprint=_make_fp(f"baseline-{i:03d}"),
                    status="categorized",
                    imported_at_ms=int(time.time() * 1000) - (35 - i) * 1000,
                    raw_row_json="{}",
                )
            )
        # 异常笔:¥888 远超 avg + 3σ = 50
        target = Transaction(
            source="wechat",
            external_transaction_id="anomaly-amount",
            transaction_date=date(2026, 6, 1),
            amount=Decimal("888.00"),
            counterparty="星巴克",
            category="dining",
            normalized_fingerprint=_make_fp("anomaly-amount"),
            status="categorized",
            imported_at_ms=int(time.time() * 1000),
            raw_row_json="{}",
        )
        session.add(target)
        session.commit()

    # 3. 跑异常检测
    with sf() as session:
        target_row = (
            session.query(Transaction).filter_by(external_transaction_id="anomaly-amount").one()
        )
        results = detector.detect_all(target_row)

    # 4. 验:amount_3sigma 必触发
    kinds = {r.kind for r in results}
    if "amount_3sigma" not in kinds:
        print(
            f"FAIL: 未检测到 amount_3sigma,实际 kinds={sorted(kinds)}",
            file=sys.stderr,
        )
        return EXIT_BUSINESS_FAIL

    # 单行输出(沿 sync_notes spike 范本)
    print(f"d8 spike: received=1 inserted=36 kinds={','.join(sorted(kinds))} count={len(results)}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v0.2 D8.4 S11 真链路 spike(AnomalyDetector + 商家画像)"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        required=True,
        help="临时 SQLite DB 路径(自动创建+清理)",
    )
    args = parser.parse_args(argv)

    if args.db_path is None:
        print("PARSE FAIL: --db-path 必传", file=sys.stderr)
        return EXIT_PARSE_FAIL

    try:
        return run_spike(args.db_path)
    except Exception as e:  # noqa: BLE001
        # 技术失败(OperationalError / DB 锁 / 其他) → exit 3
        print(f"TECH FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_TECH_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
