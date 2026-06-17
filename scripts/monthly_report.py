#!/usr/bin/env python3
"""D10.2 — 数字生活月报生成 CLI.

承接 docs/v0.1-launch-plan.md:166-191 D10 段 + docs/week2-mvp.md:241-256 D10 任务清单 +
v0.1-launch.md D10 启动决策(每月 1 号 09:00 由 @审计员 自动触发).

用法:
    uv run python scripts/monthly_report.py generate --month 2026-06
    uv run python scripts/monthly_report.py validate --template templates/finance_monthly.md

D10.2 设计决策(2026-06-15 锁定):
    - 沿 D6.6 import_wechat.py 4 退出码契约:0 成功 / 1 解析失败 / 2 业务失败 / 3 技术失败
    - 沿 D9.2 sync_imap.py subparsers 范本:generate + validate 2 子命令
    - alembic revision 校验:0007_transactions(与微信/支付宝同基线,transactions 表必在)
    - 模板路径:相对项目根 templates/finance_monthly.md(str.format 占位符替换)
    - 月份参数:--month YYYY-MM(默认上月 = today.replace(day=1) - 1 day)
    - 输出路径:reports/finance-monthly-YYYY-MM.md(自动 mkdir)

退出码(沿 D5.6.5 范本):
    0 = 成功(parsed > 0 且 failed == 0)
    1 = 解析失败(参数错 / 模板缺失 / alembic 不通过 / 数据库无 transactions 表)
    2 = 业务失败(transactions 0 行)
    3 = 技术失败(OperationalError 透传,DB 锁/连接错误)
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date as _date
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from my_ai_employee.core.alembic_helper import assert_min_revision  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.transactions import Transaction  # noqa: E402

# D10.2 锁定:月报所需最低 alembic revision(transactions 表必在)
_MIN_ALEMBIC_REVISION: str = "0007_transactions"

# 模板必含的占位符(防止模板被改坏不告警)
_REQUIRED_PLACEHOLDERS = (
    "{month}",
    "{generated_at}",
    "{total_income}",
    "{total_expense}",
    "{net_balance}",
    "{transaction_count}",
    "{category_breakdown}",
    "{anomaly_highlights}",
    "{income_mom}",
    "{expense_mom}",
)


def _parse_month(value: str) -> tuple[int, int]:
    """解析 'YYYY-MM' 字符串 → (year, month).

    Raises:
        ValueError: 格式错或日期非法
    """
    if not value or not isinstance(value, str):
        raise ValueError(f"month 必为非空字符串,实际 {type(value).__name__}")
    parts = value.split("-")
    if len(parts) != 2:
        raise ValueError(f"month 必为 'YYYY-MM' 格式,实际 {value!r}")
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError as e:
        raise ValueError(f"month 含非数字: {value!r}") from e
    if year < 1900 or year > 2200:
        raise ValueError(f"year 越界(1900-2200): {year}")
    if month < 1 or month > 12:
        raise ValueError(f"month 越界(1-12): {month}")
    # 用 date 校验(防 2026-02-30 之类)
    _date(year, month, 1)
    return (year, month)


def _month_bounds(year: int, month: int) -> tuple[_date, _date]:
    """返回 (first_day, last_day) 含首尾."""
    first = _date(year, month, 1)
    if month == 12:
        last = _date(year, 12, 31)
    else:
        from datetime import timedelta

        last = _date(year, month + 1, 1) - timedelta(days=1)
    return (first, last)


def _prev_month(year: int, month: int) -> tuple[int, int]:
    """返回上一月 (year, month)."""
    if month == 1:
        return (year - 1, 12)
    return (year, month - 1)


def _compute_stats(session: Session, year: int, month: int) -> dict[str, object]:
    """聚合当月 + 上月统计,返回填充模板所需的全部字段."""
    first, last = _month_bounds(year, month)
    prev_year, prev_month = _prev_month(year, month)
    prev_first, prev_last = _month_bounds(prev_year, prev_month)

    # 当月
    stmt = select(Transaction).where(
        Transaction.transaction_date >= first,
        Transaction.transaction_date <= last,
    )
    rows = list(session.execute(stmt).scalars())

    # 收入 = 金额 > 0;支出 = 金额 < 0(沿 S6.1 范本)
    total_income = sum((r.amount for r in rows if r.amount > 0), Decimal("0"))
    total_expense = sum((-r.amount for r in rows if r.amount < 0), Decimal("0"))
    net_balance = total_income - total_expense

    # 分类聚合(支出)
    expense_by_category: Counter[str] = Counter()
    for r in rows:
        if r.amount < 0:
            cat = r.category or "未分类"
            expense_by_category[cat] += -r.amount
    top5 = expense_by_category.most_common(5)
    if top5:
        lines = ["| 分类 | 金额 | 占比 |", "|------|------|------|"]
        for cat, amt in top5:
            pct = (amt / total_expense * 100) if total_expense > 0 else Decimal("0")
            lines.append(f"| {cat} | ¥{amt} | {pct:.1f}% |")
        category_breakdown = "\n".join(lines)
    else:
        category_breakdown = "_(当月无支出)_"

    # 异常高亮(v0.2 D8.3:接入 RuleBasedAnomalyDetector,替换原 >¥1000 简化版)
    # 异常告警为业务信号,非阻塞:Detector 抛 OperationalError → fallback "无异常"(沿 D4.7.3 v1.0.1)
    from sqlalchemy.orm import sessionmaker as _sessionmaker

    from my_ai_employee.core.anomaly_detector import RuleBasedAnomalyDetector
    from my_ai_employee.db.merchant_profile import MerchantProfileStore
    from my_ai_employee.db.transactions import TransactionStore

    _sf = _sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    _tx_store = TransactionStore(_sf)
    _profile_store = MerchantProfileStore(_sf, transaction_store=_tx_store)
    _detector = RuleBasedAnomalyDetector(
        transaction_store=_tx_store,
        merchant_profile_store=_profile_store,
    )

    anomaly_lines: list[str] = []
    try:
        for r in rows:
            results = _detector.detect_all(r)
            if results:
                kinds = ", ".join(sorted({res.kind for res in results}))
                anomaly_lines.append(
                    f"- {r.transaction_date} | {r.counterparty or '?'} | "
                    f"¥{r.amount} | 异常={kinds} | {r.category or '?'}"
                )
    except Exception as _e:  # noqa: BLE001 — Detector 异常不能让月报崩
        # 异常告警为业务信号,非阻塞(沿 D4.7.3 v1.0.1 范本:业务阻断 vs 技术失败分离)
        anomaly_lines = [f"_(异常检测暂不可用: {type(_e).__name__})_"]

    if anomaly_lines:
        anomaly_highlights = "\n".join(
            [
                "⚠️ **异常交易** (D8.3 智能检测 — 规则基础 + 商家画像增强)",
                "",
                "检测到以下异常:",
                "",
                *anomaly_lines[:10],
                "",
                "> 注:异常检测为业务信号,非阻塞;真异常 vs 业务异常分离(沿 D4.7.3 v1.0.1 范本)",
            ]
        )
    else:
        anomaly_highlights = "✅ 无异常"

    # 上月对比(同比环比 = month-over-month)
    prev_stmt = select(Transaction).where(
        Transaction.transaction_date >= prev_first,
        Transaction.transaction_date <= prev_last,
    )
    prev_rows = list(session.execute(prev_stmt).scalars())
    prev_income = sum((r.amount for r in prev_rows if r.amount > 0), Decimal("0"))
    prev_expense = sum((-r.amount for r in prev_rows if r.amount < 0), Decimal("0"))

    def _delta(curr: Decimal, prev: Decimal) -> str:
        if prev == 0:
            return "—"
        diff_pct = (curr - prev) / prev * 100
        sign = "+" if diff_pct >= 0 else ""
        return f"{sign}{diff_pct:.1f}%"

    return {
        "total_income": f"{total_income:.2f}",
        "total_expense": f"{total_expense:.2f}",
        "net_balance": f"{net_balance:.2f}",
        "transaction_count": len(rows),
        "category_breakdown": category_breakdown,
        "anomaly_highlights": anomaly_highlights,
        "income_mom": _delta(total_income, prev_income),
        "expense_mom": _delta(total_expense, prev_expense),
        "income_yoy": "—",  # v0.1 不做同比(留 v0.2)
        "expense_yoy": "—",
    }


def _open_session_factory(
    db_path: Path | None,
    *,
    no_encrypt: bool = False,
) -> tuple[sessionmaker[Session], object]:
    """打开 DB + 校验 alembic + 返回 sessionmaker(测试可 mock).

    Args:
        db_path: DB 路径(None → 默认 ~/Library/Application Support/my-ai-employee/data.db)
        no_encrypt: True → 走明文 sqlite(测试/开发用,生产必为 False)

    Returns:
        (sessionmaker, db_handle) — db_handle.close() 必调用于释放连接

    Raises:
        RuntimeError: alembic_version 缺失或 < _MIN_ALEMBIC_REVISION
        OperationalError: DB 锁或连接错误
    """
    if no_encrypt:
        # 测试/开发路径:明文 sqlite(避免 SQLCipher 加密)
        from sqlalchemy import create_engine

        if db_path is None:
            raise ValueError("no_encrypt 模式必显式 --db-path")
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        # 返回一个 fake db_handle(不需 close)
        class _FakeDb:
            def close(self) -> None:
                pass

        return (factory, _FakeDb())

    # 生产路径:SQLCipher 加密 DB
    db = Database.open(db_path=db_path)
    engine = make_sqlalchemy_engine(db)
    assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return (factory, db)


def cmd_generate(args: argparse.Namespace) -> int:
    """生成月报 CLI 子命令."""
    try:
        year, month = _parse_month(args.month)
    except ValueError as e:
        print(f"参数错误: {e}", file=sys.stderr)
        return 1

    template_path = Path(args.template)
    if not template_path.exists():
        print(f"模板不存在: {template_path}", file=sys.stderr)
        return 1
    if not template_path.is_file():
        print(f"template 不是文件: {template_path}", file=sys.stderr)
        return 1

    template_text = template_path.read_text(encoding="utf-8")
    for ph in _REQUIRED_PLACEHOLDERS:
        if ph not in template_text:
            print(f"模板缺占位符 {ph}: {template_path}", file=sys.stderr)
            return 1

    try:
        factory, db = _open_session_factory(args.db_path, no_encrypt=args.no_encrypt)
    except RuntimeError as e:
        print(f"Alembic version 校验失败: {e}", file=sys.stderr)
        print("请先跑: alembic upgrade head", file=sys.stderr)
        return 1
    except OperationalError as e:
        print(f"数据库技术失败(DB 锁或连接错误): {e}", file=sys.stderr)
        return 3
    try:
        try:
            with factory() as session:
                stats = _compute_stats(session, year, month)
        except OperationalError as e:
            print(f"数据库技术失败(DB 锁或连接错误): {e}", file=sys.stderr)
            return 3
    finally:
        db.close()

    # 业务失败:当月 0 笔
    if stats["transaction_count"] == 0:
        print(
            f"业务失败: {year}-{month:02d} 0 笔交易(可能未导入账单或月份错)",
            file=sys.stderr,
        )
        return 2

    # 渲染模板
    output_path = (
        Path(args.output)
        if args.output
        else (PROJECT_ROOT / "reports" / f"finance-monthly-{year}-{month:02d}.md")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = template_text.format(
        month=f"{year}-{month:02d}",
        generated_at=_date.today().isoformat(),
        **stats,
    )
    output_path.write_text(rendered, encoding="utf-8")

    print(
        f"monthly_report: generated={output_path} "
        f"transactions={stats['transaction_count']} "
        f"total_income=¥{stats['total_income']} "
        f"total_expense=¥{stats['total_expense']}"
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """校验模板必含占位符(D10.2 启动自检)."""
    template_path = Path(args.template)
    if not template_path.exists():
        print(f"模板不存在: {template_path}", file=sys.stderr)
        return 1
    if not template_path.is_file():
        print(f"template 不是文件: {template_path}", file=sys.stderr)
        return 1
    template_text = template_path.read_text(encoding="utf-8")
    missing = [ph for ph in _REQUIRED_PLACEHOLDERS if ph not in template_text]
    if missing:
        print(f"模板缺 {len(missing)} 个占位符: {missing}", file=sys.stderr)
        return 1
    print(f"✅ 模板校验通过: {template_path} ({len(_REQUIRED_PLACEHOLDERS)} 占位符全在)")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="D10.2 数字生活月报生成(沿 D5.6.5 4 退出码范本)")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # generate 子命令
    p_gen = subparsers.add_parser("generate", help="生成月报 Markdown")
    p_gen.add_argument("--month", required=True, help="月份 YYYY-MM(如 2026-06;默认上月)")
    p_gen.add_argument(
        "--template",
        type=Path,
        default=PROJECT_ROOT / "templates" / "finance_monthly.md",
        help="模板路径(默认 templates/finance_monthly.md)",
    )
    p_gen.add_argument(
        "--output",
        type=Path,
        default=None,
        help="输出路径(默认 reports/finance-monthly-YYYY-MM.md)",
    )
    p_gen.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径")
    p_gen.add_argument(
        "--no-encrypt",
        action="store_true",
        help="走明文 sqlite(测试/开发用,生产必为 False)",
    )
    p_gen.set_defaults(func=cmd_generate)

    # validate 子命令
    p_val = subparsers.add_parser("validate", help="校验模板必含占位符")
    p_val.add_argument(
        "--template",
        type=Path,
        default=PROJECT_ROOT / "templates" / "finance_monthly.md",
        help="模板路径(默认 templates/finance_monthly.md)",
    )
    p_val.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
