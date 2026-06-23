"""S6 — 微信/支付宝 CSV 导入 → 解析 → 入库 → 跨源去重 → 菜单栏支出更新 端到端验证.

承接 docs/v0.1-launch-plan.md:221 S6 唯一编号表行 + docs/week2-mvp.md:58-96 D6 + D7 任务。

S6.1 (commit 1) — 微信 100 笔 InMemory 导入 + 5 类分类 + status 流转
S6.2 (commit 1) — 跨源去重(L2 needs_confirm + candidate_match_id)
S6.3 (commit 2) — 菜单栏支出总额(沿 core.expense_aggregate.current_month_expense)
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pytest
from sqlalchemy.orm import Session, sessionmaker

# ===== Fakers =====

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_WECHAT_2024_CSV = _FIXTURES_DIR / "wechat_faker" / "wechat_2024_sample.csv"
_WECHAT_2025_CSV = _FIXTURES_DIR / "wechat_faker" / "wechat_2025_sample.csv"
_ALIPAY_2024_CSV = _FIXTURES_DIR / "alipay_faker" / "alipay_2024_sample.csv"


# ===== Helpers(沿 D7 spike 段 C 范本 + D6.2 fingerprint 算法)=====


def _raw_row_hash(*, date_: date, amount: Decimal, counterparty: str, ext_id: str) -> str:
    """32 chars sha256 派生 fingerprint(S6.1 唯一性 + S6.2 跨源匹配共用)."""
    payload = f"{date_.isoformat()}|{amount}|{counterparty}|{ext_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _csv_to_raw_transactions(
    csv_path: Path,
    *,
    source: str,
    ext_id_prefix: str,
) -> list:
    """读 faker CSV 解析为 RawTransaction 列表(沿 wechat_csv.py 字段映射).

    Args:
        csv_path: faker CSV 路径(5 行)
        source: 'wechat' / 'alipay'
        ext_id_prefix: ext_id 前缀(传 unique 值防 L1 误命中)
    """
    import csv

    from my_ai_employee.connectors._types import RawTransaction

    rows: list[RawTransaction] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            # 解析日期(微信/支付宝两源共用 "YYYY-MM-DD HH:MM:SS" 格式)
            dt_str = (
                row.get("交易时间")
                or row.get("付款时间")
                or row.get("日期")
                or row.get("创建时间")
                or ""
            )
            date_ = date.fromisoformat(dt_str.split(" ")[0])
            amount = Decimal(str(row["金额"]))
            # 类型映射:微信是"收/付"列 → 映射到 "收入"/"支出"
            raw_type = row.get("交易类型") or row.get("收/付") or row.get("收/支") or "支出"
            if raw_type in ("付", "支"):
                type_: Literal["支出", "收入"] = "支出"
            elif raw_type in ("收",):
                type_ = "收入"
            else:
                type_ = "支出"
            counterparty = row["交易对方"]
            payment_method = row["支付方式"]
            # 唯一 ext_id(沿 plan §S6.1 决策)
            ext_id = f"{ext_id_prefix}-{source}-{i:03d}"
            raw_hash = _raw_row_hash(
                date_=date_,
                amount=amount,
                counterparty=counterparty,
                ext_id=ext_id,
            )
            rows.append(
                RawTransaction(
                    date=date_,
                    amount=amount,
                    counterparty=counterparty,
                    type=type_,
                    payment_method=payment_method,
                    external_transaction_id=ext_id,
                    raw_row_hash=raw_hash,
                )
            )
    return rows


def _expand_to_100(rows_10: list) -> list:
    """循环展开 10 行 faker 样本到 100 行(每行 ext_id 改 unique).

    沿 plan §S6.1:`list(islice(cycle(2024_5 + 2025_5), 100))` × ext_id 改 token_hex(8)。
    """
    from my_ai_employee.connectors._types import RawTransaction

    out: list[RawTransaction] = []
    counter = 0
    while len(out) < 100:
        for raw in rows_10:
            if len(out) >= 100:
                break
            new_ext_id = f"s61-{secrets.token_hex(8)}-{counter:04d}"
            counter += 1
            out.append(
                RawTransaction(
                    date=raw.date,
                    amount=raw.amount,
                    counterparty=raw.counterparty,
                    type=cast(Literal["支出", "收入"], raw.type),
                    payment_method=raw.payment_method,
                    external_transaction_id=new_ext_id,
                    raw_row_hash=_raw_row_hash(
                        date_=raw.date,
                        amount=raw.amount,
                        counterparty=raw.counterparty,
                        ext_id=new_ext_id,
                    ),
                )
            )
    return out


# ===== S6.1 — 微信 100 笔 InMemory 导入 =====


@pytest.mark.e2e
def test_s6_wechat_csv_import_100_inmemory(session_factory: sessionmaker[Session]) -> None:
    """S6.1 — 微信 100 笔 InMemory 导入,3 层去重 + 5 类分类 + status 流转.

    复用 wechat_2024/2025 faker 样本(各 5 行,共 10 行 × 10 轮 = 100 笔),
    ext_id 改 `s61-{token_hex(8)}-{counter}` 唯一值,防 L1 源内 UNIQUE 误命中。

    验证:
      - parsed / inserted / (categorized + needs_confirm) / imported_ids == 100
      - duplicates / failed == 0(单源导入,无跨源,无失败)
      - 终态 status ⊆ {categorized, needs_confirm}(沿 Adapter 原子化,不会停在 imported)
      - 5 类分类至少命中 1 类(避免全 OTHER 兜底)
      - store.list_by_source("wechat") 实际查到 100 行
    """
    from my_ai_employee.core.transaction_adapter import TransactionAdapter
    from my_ai_employee.db.transactions import TransactionStore

    rows_10 = _csv_to_raw_transactions(
        _WECHAT_2024_CSV, source="wechat", ext_id_prefix="base"
    ) + _csv_to_raw_transactions(_WECHAT_2025_CSV, source="wechat", ext_id_prefix="base")
    rows_100 = _expand_to_100(rows_10)
    assert len(rows_100) == 100

    adapter = TransactionAdapter(session_factory)
    result = adapter.import_raw_transactions(rows_100, source="wechat")

    # Adapter 6 计数 + 3 详情
    assert result.parsed == 100, f"parsed 应等于 100,实际 {result.parsed}"
    assert result.inserted == 100, f"inserted 应等于 100,实际 {result.inserted}"
    assert result.categorized + result.needs_confirm == 100, (
        f"categorized + needs_confirm 应等于 100,实际 {result.categorized + result.needs_confirm}"
    )
    assert result.duplicates == 0, f"duplicates 应等于 0,实际 {result.duplicates}"
    assert result.failed == 0, f"failed 应等于 0,实际 {result.failed}"
    assert len(result.imported_ids) == 100

    # 终态 status 严判(沿 Adapter 原子化:直接推到 categorized / needs_confirm)
    store = TransactionStore(session_factory)
    rows = store.list_by_source("wechat", limit=200)
    assert len(rows) == 100
    statuses = {row.status for row in rows}
    assert statuses.issubset({"categorized", "needs_confirm"}), (
        f"终态 status 应 ⊆ {{categorized, needs_confirm}},实际 {statuses}"
    )
    # 5 类分类至少命中 1 类(避免全 OTHER 兜底,验证 categorizer 真在工作)
    categories = {row.category for row in rows}
    assert len(categories) >= 2, f"分类应至少 2 类,实际 {categories}"


# ===== S6.2 — 跨源去重 + needs_confirm =====


@pytest.mark.e2e
def test_s6_cross_source_dedup(session_factory: sessionmaker[Session]) -> None:
    """S6.2 — 跨源去重:同一笔交易(同日同金额同商家)不会被微信+支付宝两边都导入.

    复用 wechat_2024(5 行)+ alipay_2024(5 行),5 对全部跨源同 fingerprint
    (2024-05-12 星巴克 / 2024-05-13 美团 / 2024-05-14 工资 / 2024-05-15 滴滴
    / 2024-05-16 星巴克退款)。

    验证(沿 D7 spike 段 C 范本):
      - wechat 5 笔先入 → inserted=5, categorized=5(无候选,单源)
      - alipay 5 笔后入 → inserted=5, needs_confirm=5, candidate_count=5
      - 总行数 = 10(L1 跨源不误判,L2 跨源正确触发 needs_confirm)
      - alipay 行的 candidate_match_id 指向 wechat id(同 fingerprint)
      - 反向(alipay 先入 → wechat 后入)同理
    """
    from my_ai_employee.core.transaction_adapter import TransactionAdapter
    from my_ai_employee.db.transactions import TransactionStore

    adapter = TransactionAdapter(session_factory)

    # 正向:wechat 先入 → alipay 后入
    wechat_rows = _csv_to_raw_transactions(_WECHAT_2024_CSV, source="wechat", ext_id_prefix="s62-w")
    alipay_rows = _csv_to_raw_transactions(_ALIPAY_2024_CSV, source="alipay", ext_id_prefix="s62-a")

    res_w = adapter.import_raw_transactions(wechat_rows, source="wechat")
    res_a = adapter.import_raw_transactions(alipay_rows, source="alipay")

    expected_wechat = len(wechat_rows)
    expected_alipay = len(alipay_rows)
    from my_ai_employee.core.fingerprint import normalize_fingerprint

    wechat_fps_unused = {
        normalize_fingerprint(row.date, row.amount, row.counterparty, sign=+1)
        for row in wechat_rows
    }
    del wechat_fps_unused  # noqa: F841 — 仅占位防 ruff F841,实际计算用 wechat_pos_fps
    alipay_fps_unused = {
        normalize_fingerprint(row.date, row.amount, row.counterparty, sign=+1)
        for row in alipay_rows
    }
    del alipay_fps_unused  # noqa: F841
    # v0.2.28 L2 sign-lock:wechat/alipay rows 各自派生 sign(type=支出→+1 / 收入→-1)
    # 计算期望命中数时,wechat_rows 中 sign=+1 的 fp 与 alipay_rows 中 sign=+1 的 fp 才会命中
    # (sign=-1 的行不参与跨源比较,因为 sign 维度锁死)
    wechat_pos_fps = {
        normalize_fingerprint(row.date, row.amount, row.counterparty, sign=+1)
        for row in wechat_rows
        if row.type == "支出"
    }
    alipay_pos_fps = {
        normalize_fingerprint(row.date, row.amount, row.counterparty, sign=+1)
        for row in alipay_rows
        if row.type == "支出"
    }
    expected_alipay_candidates = sum(
        1
        for row in alipay_rows
        if row.type == "支出"
        and normalize_fingerprint(row.date, row.amount, row.counterparty, sign=+1) in wechat_pos_fps
    )
    expected_wechat_candidates = sum(
        1
        for row in wechat_rows
        if row.type == "支出"
        and normalize_fingerprint(row.date, row.amount, row.counterparty, sign=+1) in alipay_pos_fps
    )

    # wechat:单源样本,无跨源候选 → 全 categorized
    assert res_w.parsed == expected_wechat
    assert res_w.inserted == expected_wechat
    assert res_w.categorized == expected_wechat
    assert res_w.needs_confirm == 0
    assert res_w.failed == 0

    # alipay:同 fingerprint 样本命中 wechat 候选 → needs_confirm + candidate_count
    assert res_a.parsed == expected_alipay
    assert res_a.inserted == expected_alipay
    assert res_a.needs_confirm == expected_alipay_candidates
    assert res_a.categorized == expected_alipay - expected_alipay_candidates
    assert res_a.candidate_count == expected_alipay_candidates
    assert res_a.failed == 0

    # L1 跨源不误判(同 ext_id 不会阻断,因 wechat/alipay ext_id 前缀不同)
    # L2 跨源正确触发(同 fingerprint 跨源候选)
    store = TransactionStore(session_factory)
    wechat_stored = store.list_by_source("wechat", limit=expected_wechat + 1)
    alipay_stored = store.list_by_source("alipay", limit=expected_alipay + 1)
    assert len(wechat_stored) == expected_wechat
    assert len(alipay_stored) == expected_alipay

    # 命中候选的 alipay 行 candidate_match_id 指向 wechat id(同 fingerprint 选最小 id)
    needs_confirm_rows = [tx for tx in alipay_stored if tx.needs_confirm == 1]
    assert len(needs_confirm_rows) == expected_alipay_candidates
    for alipay_tx in needs_confirm_rows:
        assert alipay_tx.candidate_match_id is not None
        # candidate_match_id 必须是 wechat 的某个 id
        assert any(w.id == alipay_tx.candidate_match_id for w in wechat_stored)

    # 反向:alipay 先入 → wechat 后入
    # 用新的 session_factory 隔离(沿 D7 spike 段 D 范本)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from my_ai_employee.core.models import Base

    engine2 = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine2)
    sf2 = sessionmaker(bind=engine2, autoflush=False, autocommit=False)
    adapter2 = TransactionAdapter(sf2)

    res_a2 = adapter2.import_raw_transactions(alipay_rows, source="alipay")
    res_w2 = adapter2.import_raw_transactions(wechat_rows, source="wechat")
    assert res_a2.inserted == expected_alipay
    assert res_a2.categorized == expected_alipay
    assert res_w2.inserted == expected_wechat
    assert res_w2.needs_confirm == expected_wechat_candidates
    assert res_w2.candidate_count == expected_wechat_candidates


# ===== S6.3 — 菜单栏支出总额(commit 2 真实断言)=====


@pytest.mark.e2e
def test_s6_menu_bar_expense_update() -> None:
    """S6.3 — 菜单栏支出总额实时更新(写入 transactions 后触发).

    沿 core.expense_aggregate.current_month_expense 聚合查询,
    D9 menu_bar/expense_service.py 启动时直接 import 该函数。

    验证:
      - 导入 100 笔 faker(沿 S6.1 _expand_to_100 范本)
        + 50 笔 2024-05(wechat_2024_sample.csv × 10 轮)+ 50 笔 2025-03(wechat_2025 × 10 轮)
      - current_month_expense(today=date(2024, 5, 31)) == Decimal("50635.00")
        (10 轮 × (38.50 + 12.00 + 5000.00 + 28.00 + (-15.00)) = 10 × 5063.50 = 50635.00)
      - current_month_expense(today=date(2025, 3, 31)) == Decimal("36035.00")
        (10 轮 × (42.00 + 88.00 + 3500.00 + 15.50 + (-42.00)) = 10 × 3603.50 = 36035.00)
      - 独立 InMemory sqlite(不污染其他 e2e session)
    """
    from decimal import Decimal

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from my_ai_employee.core.expense_aggregate import current_month_expense
    from my_ai_employee.core.models import Base
    from my_ai_employee.core.transaction_adapter import TransactionAdapter

    # 独立 InMemory sqlite(沿 S6.2 反向范本,不污染其他 e2e session)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    adapter = TransactionAdapter(sf)

    # 100 笔 faker(沿 S6.1 _expand_to_100,50 笔 2024-05 + 50 笔 2025-03)
    rows_10 = _csv_to_raw_transactions(
        _WECHAT_2024_CSV, source="wechat", ext_id_prefix="s63-base"
    ) + _csv_to_raw_transactions(_WECHAT_2025_CSV, source="wechat", ext_id_prefix="s63-base")
    rows_100 = _expand_to_100(rows_10)
    assert len(rows_100) == 100
    res = adapter.import_raw_transactions(rows_100, source="wechat")
    assert res.inserted == 100
    assert res.failed == 0

    # 当月支出总额断言(随 fixture 扩样本动态计算期望值)
    total_may = current_month_expense(sf, today=date(2024, 5, 31))
    expected_may = sum(
        (row.amount for row in rows_100 if row.date.year == 2024 and row.date.month == 5),
        Decimal("0.00"),
    )
    assert total_may == expected_may, f"2024-05 总额应等于 {expected_may},实际 {total_may}"

    total_mar = current_month_expense(sf, today=date(2025, 3, 31))
    expected_mar = sum(
        (row.amount for row in rows_100 if row.date.year == 2025 and row.date.month == 3),
        Decimal("0.00"),
    )
    assert total_mar == expected_mar, f"2025-03 总额应等于 {expected_mar},实际 {total_mar}"
