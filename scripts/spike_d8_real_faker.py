#!/usr/bin/env python3
"""v0.2 D8 周验证 — 半真实账单样本误报率 spike(2026-06-17 扩到 100 笔).

承接 commit 9 docs 收口后的本周验证任务(2026-06-17 用户指令 #2):
"本周验证:D8 异常检测再跑一轮真实/半真实账单样本,观察误报率"
+ "继续扩大账单样本,观察 cold_start signal 是否噪音过多"

样本来源(W3 扩样本 — 沿 D8.5.4 修复后验证):
    - tests/fixtures/wechat_faker/{2022, 2023, 2024, 2025, 2026}_sample.csv (50 笔)
    - tests/fixtures/alipay_faker/{2022, 2023, 2024, 2025, 2026}_sample.csv (50 笔)
    - 共 100 笔半真实账单,覆盖 24 个月 + 2 个 source + ~20 个商家

W3 验证重点(用户指令 #2):
    1. 真异常误报率仍 0%(D8.5.1-3 修复后)
    2. cold_start 业务信号在更大样本下合理(不噪音)
    3. 已知异常能 catch(¥999 amount_3sigma + 4/5 hour frequency 5 笔)

设计样本验证用例:
    - 1 笔 ¥999 异常大额(wechat_2024-05-21 + alipay_2024-05-21) → amount_3sigma
    - 5 笔同 source 1 小时内(wechat_2026-04-05 + alipay_2026-04-05) → frequency_5tx_per_hour
    - ~50% 商家有画像(≥5 笔)+ ~50% 商家冷启动(<5 笔) → new_merchant 信号分布

验证维度:
    1. 6 类异常触发率(amount_3sigma / frequency_5tx_per_hour / duplicate_charge
       / new_merchant / amount_drift / category_drift)
    2. 性能基线(平均 ms / 笔,沿 D5.6.5 真实 1 封范本)
    3. 真异常误报率(已知正常样本被标异常 = 0%)
    4. cold_start 信号占比(业务信号,不算异常)

4 退出码契约(沿 D5.6.5 + D8.4 spike 范本):
    0 = 成功(spike 跑通 + 统计输出)
    1 = 解析失败(CSV 缺失 / 列名错)
    2 = 业务失败(loaded == 0)
    3 = 技术失败(OperationalError / DB 锁)

用法:
    uv run python scripts/spike_d8_real_faker.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.db.merchant_profile import MerchantProfileStore  # noqa: E402
from my_ai_employee.db.transactions import Transaction, TransactionStore  # noqa: E402

# ===== 退出码契约 =====

EXIT_OK: int = 0
EXIT_PARSE_FAIL: int = 1
EXIT_BUSINESS_FAIL: int = 2
EXIT_TECH_FAIL: int = 3


# ===== CSV 列名映射(微信 vs 支付宝,支持多年份不同列名) =====

# 微信可能列名(按实际 faker 样本)
WECHAT_TIME_COLS = ("交易时间", "日期", "消费时间")
WECHAT_AMOUNT_COL = "金额"
WECHAT_COUNTERPARTY_COL = "交易对方"
WECHAT_EXT_ID_COLS = ("交易号", "交易单号", "订单号")

# 支付宝可能列名
ALIPAY_TIME_COLS = ("付款时间", "创建时间", "消费时间")
ALIPAY_AMOUNT_COL = "金额"
ALIPAY_COUNTERPARTY_COL = "交易对方"
ALIPAY_EXT_ID_COLS = ("交易号", "交易单号", "订单号")


def _resolve_cols(
    headers: list[str],
    time_cols: tuple[str, ...],
    ext_id_cols: tuple[str, ...],
) -> dict[str, str]:
    """从 CSV 表头解析出实际列名映射.

    Args:
        headers: csv.DictReader.fieldnames
        time_cols: 候选时间列名(按优先级)
        ext_id_cols: 候选 ext_id 列名(按优先级)

    Returns:
        {"time": <列名>, "amount": <列名>, "counterparty": <列名>, "ext_id": <列名>}

    Raises:
        KeyError: 必填列缺失
    """
    time_col = next((c for c in time_cols if c in headers), None)
    if time_col is None:
        raise KeyError(f"时间列缺失,候选: {time_cols}")
    ext_id_col = next((c for c in ext_id_cols if c in headers), None)
    if ext_id_col is None:
        raise KeyError(f"ext_id 列缺失,候选: {ext_id_cols}")
    if WECHAT_AMOUNT_COL not in headers:
        raise KeyError(f"金额列缺失: {WECHAT_AMOUNT_COL}")
    if WECHAT_COUNTERPARTY_COL not in headers:
        raise KeyError(f"商家列缺失: {WECHAT_COUNTERPARTY_COL}")
    return {
        "time": time_col,
        "amount": WECHAT_AMOUNT_COL,
        "counterparty": WECHAT_COUNTERPARTY_COL,
        "ext_id": ext_id_col,
    }


def _make_fp(seed: str) -> str:
    """生成 32 chars 小写 hex fingerprint(沿 D6.2 范本)."""
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


def _parse_csv_row(row: dict[str, str], cols: dict[str, str]) -> Transaction:
    """解析 CSV 一行 → Transaction(支持微信/支付宝两种列名).

    Args:
        row: csv.DictReader 的一行
        cols: 列名映射

    Returns:
        Transaction(未入库)

    Raises:
        ValueError: 金额无法解析 / 商家名为空
        KeyError: 必填列缺失
    """
    time_str = row[cols["time"]].strip()
    amount_str = row[cols["amount"]].strip()
    counterparty = row[cols["counterparty"]].strip()
    ext_id = row[cols["ext_id"]].strip()
    source = row.get("source", "unknown")

    # 时间解析(支持 "2024-05-12 14:30:00" 格式,部分 CSV 是 "2026-04-01 09:00:00")
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        tx_date = dt.date()
        imported_at_ms = int(dt.timestamp() * 1000)
    except ValueError as e:
        raise ValueError(f"时间格式错: {time_str!r}") from e

    # 金额解析(支持负数 / "12.00" / "-15.00")
    try:
        amount = Decimal(amount_str)
    except InvalidOperation as e:
        raise ValueError(f"金额格式错: {amount_str!r}") from e

    if not counterparty:
        raise ValueError(f"商家名空: ext_id={ext_id}")

    return Transaction(
        source=source,
        external_transaction_id=ext_id,
        transaction_date=tx_date,
        amount=amount,
        counterparty=counterparty,
        category=None,  # 不预设分类,让 spike 反映真实场景(可空)
        normalized_fingerprint=_make_fp(f"{cols['time']}-{ext_id}"),
        status="categorized",
        imported_at_ms=imported_at_ms,
        raw_row_json="{}",
    )


def _load_csv(
    path: Path,
    time_cols: tuple[str, ...],
    ext_id_cols: tuple[str, ...],
    source: str,
) -> list[Transaction]:
    """加载 1 个 CSV → list[Transaction].

    Args:
        path: CSV 文件路径
        time_cols: 候选时间列名
        ext_id_cols: 候选 ext_id 列名
        source: 数据源(wechat / alipay)

    Returns:
        Transaction 列表
    """
    txs: list[Transaction] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = _resolve_cols(list(reader.fieldnames or []), time_cols, ext_id_cols)
        for row in reader:
            row["source"] = source
            tx = _parse_csv_row(row, cols)
            txs.append(tx)
    return txs


def run_spike(fixtures_root: Path) -> int:
    """跑 D8 半真实账单 spike 主流程.

    Args:
        fixtures_root: tests/fixtures 根目录

    Returns:
        退出码(0/1/2/3)
    """
    # 1. 加载 10 个 CSV × 10 行 = 100 笔(W3 扩样本,沿 D8.5.4 修复后验证)
    wechat_csvs = [
        fixtures_root / "wechat_faker" / f"wechat_{year}_sample.csv" for year in (2022, 2023, 2024, 2025, 2026)
    ]
    alipay_csvs = [
        fixtures_root / "alipay_faker" / f"alipay_{year}_sample.csv" for year in (2022, 2023, 2024, 2025, 2026)
    ]

    for p in wechat_csvs + alipay_csvs:
        if not p.exists():
            print(f"PARSE FAIL: CSV 缺失: {p}", file=sys.stderr)
            return EXIT_PARSE_FAIL

    txs: list[Transaction] = []
    for path in wechat_csvs:
        txs.extend(_load_csv(path, WECHAT_TIME_COLS, WECHAT_EXT_ID_COLS, source="wechat"))
    for path in alipay_csvs:
        txs.extend(_load_csv(path, ALIPAY_TIME_COLS, ALIPAY_EXT_ID_COLS, source="alipay"))

    if not txs:
        print(f"BUSINESS FAIL: 加载 0 笔,实际 {len(txs)}", file=sys.stderr)
        return EXIT_BUSINESS_FAIL

    # 2. 临时 SQLite DB + create_all
    db_path = Path("/tmp/spike_d8_real_faker.db")
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

    # 3. 入库 100 笔(按 imported_at_ms 升序,模拟真实时序)
    txs_sorted = sorted(txs, key=lambda t: t.imported_at_ms)
    with sf() as session:
        for tx in txs_sorted:
            session.add(tx)
        session.commit()

    # 4. 跑异常检测(逐笔 + 统计 6 类触发率 + 平均延迟)
    kind_counts: dict[str, int] = {
        "amount_3sigma": 0,
        "frequency_5tx_per_hour": 0,
        "duplicate_charge": 0,
        "new_merchant": 0,
        "amount_drift": 0,
        "category_drift": 0,
    }
    total_anomalies = 0
    total_latency_ms: float = 0.0
    tx_count_with_results = 0

    with sf() as session:
        for tx_id in [tx.id for tx in txs_sorted]:
            tx_row = session.get(Transaction, tx_id)
            if tx_row is None:
                continue
            start = time.perf_counter()
            results = detector.detect_all(tx_row)
            latency_ms: float = (time.perf_counter() - start) * 1000
            total_latency_ms += latency_ms
            tx_count_with_results += 1
            if results:
                total_anomalies += 1
                for r in results:
                    kind_counts[r.kind] = kind_counts.get(r.kind, 0) + 1

    # 5. 输出统计
    avg_latency_ms: float = (
        total_latency_ms / tx_count_with_results if tx_count_with_results else 0.0
    )
    kinds_summary = ",".join(f"{k}={v}" for k, v in kind_counts.items() if v > 0)
    if not kinds_summary:
        kinds_summary = "(none)"

    # 单行输出(沿 D5.6.5 + D8.4 spike 范本)
    print(
        f"d8 real-faker spike: loaded={len(txs_sorted)} "
        f"detected={total_anomalies} "
        f"avg_latency_ms={avg_latency_ms:.2f} "
        f"kinds={kinds_summary}"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v0.2 D8 周验证 — 半真实账单样本误报率 spike")
    parser.add_argument(
        "--fixtures-root",
        type=Path,
        default=PROJECT_ROOT / "tests" / "fixtures",
        help="tests/fixtures 根目录(默认 项目/tests/fixtures)",
    )
    args = parser.parse_args(argv)

    if not args.fixtures_root.exists():
        print(f"PARSE FAIL: fixtures-root 不存在: {args.fixtures_root}", file=sys.stderr)
        return EXIT_PARSE_FAIL

    try:
        return run_spike(args.fixtures_root)
    except Exception as e:  # noqa: BLE001
        print(f"TECH FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_TECH_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
