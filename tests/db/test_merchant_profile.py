"""v0.2 D8.1 — MerchantProfile ORM + Store 测试(8 cases).

承接 D6.4 TransactionStore(16 列 + 5 公共方法)+ B4.1 RecipientBlacklistStore 范本。
本测试覆盖 8 cases:

    1. ORM 模型列名/类型(2 tests) — __tablename__ + 8 字段名 + UNIQUE 约束
    2. 严判 helper(2 tests) — _validate_counterparty / _validate_amount 边界
    3. compute_profile 冷启动/正常(2 tests) — < 5 笔 → None / >= 5 笔 → dict[Any, Any]
    4. upsert_profile insert / update(2 tests) — 新增 + 覆盖

D3.2 8 雷区严判(全部应用):
    - Numeric(10, 2) 非 Float
    - BOOLEAN 走 Integer + server_default="0/1" — N/A
    - DATE 走 Date — N/A
    - AUTOINCREMENT
    - 下划线命名
    - DESC 索引用 sa.text
    - render_as_batch=True(env.py)
    - downgrade 干净回滚

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError
    - 拒绝 D3.3.2 反范本

D4.7.3 教训应用:
    - type 严判在 hash 操作前
    - 公共 API 入口严判 + 数据类 __post_init__ 双层防御
    - ms 字段严判 type() is bool

Fixture 复用 tests/db/test_transactions.py 范本:
    - InMemory SQLite 模式(不依赖真 SQLCipher,快)
    - 测试间用 rollback 隔离
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== Fixtures(D8.1 范本:InMemory SQLite + create_all)=====


@pytest.fixture
def engine() -> Iterator[Any]:
    """InMemory SQLite + MerchantProfile ORM 8 列 + Transaction ORM 16 列 create_all."""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.merchant_profile import MerchantProfile  # noqa: F401
    from my_ai_employee.db.transactions import Transaction  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Any) -> Any:
    """返回 sessionmaker[Any]."""
    return sessionmaker[Any](bind=engine)


@pytest.fixture
def store(session_factory: Any) -> Any:
    """MerchantProfileStore 实例(注入 session_factory + TransactionStore)。"""
    from my_ai_employee.db.merchant_profile import MerchantProfileStore
    from my_ai_employee.db.transactions import TransactionStore

    tx_store = TransactionStore(session_factory)
    return MerchantProfileStore(session_factory, transaction_store=tx_store)


@pytest.fixture
def tx_store(session_factory: Any) -> Any:
    """TransactionStore 实例(供 setup helper 复用)。"""
    from my_ai_employee.db.transactions import TransactionStore

    return TransactionStore(session_factory)


# ===== Setup helper:批量插入历史交易 =====


def _seed_history(
    tx_store: Any, counterparty: str, n: int, base_amount: Decimal = Decimal("50.00")
) -> None:
    """插入 n 笔同一商家的历史交易(供 compute_profile 测试用)。"""
    from my_ai_employee.db.transactions import Transaction

    with tx_store._session_factory() as session:
        for i in range(n):
            session.add(
                Transaction(
                    source="wechat",
                    external_transaction_id=f"{counterparty}-{i:03d}",
                    transaction_date=date(2026, 5, 1 + i % 28),
                    amount=base_amount,
                    counterparty=counterparty,
                    category="dining",
                    normalized_fingerprint=f"{counterparty}-fp-{i:03d}".ljust(32, "0")[:32],
                    status="categorized",
                    imported_at_ms=1_700_000_000_000 + i * 1000,
                    raw_row_json="{}",
                )
            )
        session.commit()


# ===== Segment 1: ORM 模型(2 tests)=====


def test_orm_tablename_merchant_profile() -> None:
    """Case 1 — MerchantProfile ORM __tablename__ = "merchant_profile"。"""
    from my_ai_employee.db.merchant_profile import MerchantProfile

    assert MerchantProfile.__tablename__ == "merchant_profile"


def test_orm_has_8_columns_with_unique_constraint() -> None:
    """Case 2 — MerchantProfile ORM 8 字段 + UNIQUE(counterparty) 约束。"""
    from my_ai_employee.db.merchant_profile import MerchantProfile

    columns = {c.name for c in MerchantProfile.__table__.columns}
    assert columns == {
        "id",
        "counterparty",
        "avg_amount",
        "amount_std",
        "category_distribution",
        "tx_count",
        "last_seen_ms",
        "updated_at_ms",
    }
    # UNIQUE 约束(用 isinstance 检查 UniqueConstraint)
    from sqlalchemy import Table, UniqueConstraint

    table: Table = MerchantProfile.__table__  # type: ignore[assignment]
    unique_constraints = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert any("counterparty" in [col.name for col in c.columns] for c in unique_constraints)
    # 索引(idx_merchant_profile_last_seen) 必含
    assert any(idx.name == "idx_merchant_profile_last_seen" for idx in table.indexes)


# ===== Segment 2: 严判 helper(2 tests)=====


def test_validate_counterparty_rejects_empty_and_non_string() -> None:
    """Case 3 — _validate_counterparty 拒空字符串 + 非 str。"""
    from my_ai_employee.db.merchant_profile import MerchantProfileStore

    # 空字符串 → ValueError
    with pytest.raises(ValueError, match="counterparty 必非空"):
        MerchantProfileStore._validate_counterparty("")
    with pytest.raises(ValueError, match="counterparty 必非空"):
        MerchantProfileStore._validate_counterparty("   \n\t")

    # 非 str → TypeError
    with pytest.raises(TypeError, match="counterparty 必须是 str"):
        MerchantProfileStore._validate_counterparty(123)  # type: ignore[arg-type]

    # 超长(> 128)→ ValueError
    with pytest.raises(ValueError, match="counterparty 长度超 128"):
        MerchantProfileStore._validate_counterparty("a" * 129)

    # 合法字符串(strip 后非空)
    assert MerchantProfileStore._validate_counterparty("  星巴克  ") == "星巴克"


def test_validate_amount_rejects_negative_and_non_decimal() -> None:
    """Case 4 — _validate_amount 拒 < 0 / 非 Decimal / 超 2 位小数。"""
    from my_ai_employee.db.merchant_profile import MerchantProfileStore

    # < 0 → ValueError
    with pytest.raises(ValueError, match="avg_amount 必须 >= 0"):
        MerchantProfileStore._validate_amount(Decimal("-1.00"), "avg_amount")

    # 非 Decimal → TypeError
    with pytest.raises(TypeError, match="avg_amount 必须是 Decimal"):
        MerchantProfileStore._validate_amount(13.14, "avg_amount")  # type: ignore[arg-type]

    # 超 2 位小数 → ValueError
    with pytest.raises(ValueError, match="小数位超 2"):
        MerchantProfileStore._validate_amount(Decimal("13.141"), "avg_amount")

    # 合法 Decimal(>= 0 + ≤ 2 位小数)
    assert MerchantProfileStore._validate_amount(Decimal("0.00"), "avg_amount") == Decimal("0.00")
    assert MerchantProfileStore._validate_amount(Decimal("13.14"), "avg_amount") == Decimal("13.14")


# ===== Segment 3: compute_profile 冷启动/正常(2 tests)=====


def test_compute_profile_returns_none_when_history_below_threshold(
    store: Any, tx_store: Any
) -> None:
    """Case 5 — compute_profile < 5 笔历史 → None(冷启动 fallback,沿 D8.1 决策 MIN_HISTORY_FOR_PROFILE=5)."""
    # 插 4 笔(< 5 阈值)
    _seed_history(tx_store, "新商家", n=4)
    result = store.compute_profile("新商家")
    assert result is None


def test_compute_profile_returns_dict_with_correct_stats(store: Any, tx_store: Any) -> None:
    """Case 6 — compute_profile >= 5 笔 → dict[Any, Any] 含 avg_amount + amount_std + tx_count."""
    # 插 10 笔 ¥50.00(同金额 σ=0)
    _seed_history(tx_store, "星巴克", n=10, base_amount=Decimal("50.00"))

    result = store.compute_profile("星巴克")
    assert result is not None
    assert result["counterparty"] == "星巴克"
    assert result["avg_amount"] == Decimal("50.00")
    # σ = sqrt(Σ(amount - 50)^2 / 10) = 0(同金额)
    assert result["amount_std"] == Decimal("0.00")
    assert result["tx_count"] == 10
    # category_distribution 必是合法 JSON
    import json

    dist = json.loads(result["category_distribution"])
    assert dist == {"dining": 10}


# ===== Segment 4: upsert_profile insert / update(2 tests)=====


def test_upsert_profile_inserts_new_profile(store: Any) -> None:
    """Case 7 — upsert_profile 新增画像(MerchantProfile 行入库 + 字段严判生效)."""
    import time

    now_ms = int(time.time() * 1000)
    profile = {
        "counterparty": "瑞幸咖啡",
        "avg_amount": Decimal("25.50"),
        "amount_std": Decimal("2.30"),
        "category_distribution": '{"dining": 12}',
        "tx_count": 12,
        "last_seen_ms": now_ms - 86400 * 1000,
    }
    store.upsert_profile(profile)

    # 查回画像(沿 get_profile)
    fetched = store.get_profile("瑞幸咖啡")
    assert fetched is not None
    assert fetched.counterparty == "瑞幸咖啡"
    assert fetched.avg_amount == Decimal("25.50")
    assert fetched.amount_std == Decimal("2.30")
    assert fetched.tx_count == 12
    assert fetched.updated_at_ms >= now_ms - 1000  # 误差 1s 内


def test_upsert_profile_updates_existing_profile(store: Any) -> None:
    """Case 8 — upsert_profile 覆盖已有画像(tx_count 累加 + 字段全更新)."""
    import time

    now_ms = int(time.time() * 1000)
    # 第 1 次 upsert
    profile_v1 = {
        "counterparty": "麦当劳",
        "avg_amount": Decimal("30.00"),
        "amount_std": Decimal("5.00"),
        "category_distribution": '{"dining": 10}',
        "tx_count": 10,
        "last_seen_ms": now_ms - 86400 * 1000,
    }
    store.upsert_profile(profile_v1)
    fetched_v1 = store.get_profile("麦当劳")
    assert fetched_v1 is not None
    assert fetched_v1.tx_count == 10

    # 第 2 次 upsert(累加 + 更新)
    profile_v2 = {
        "counterparty": "麦当劳",
        "avg_amount": Decimal("32.00"),
        "amount_std": Decimal("4.50"),
        "category_distribution": '{"dining": 20}',
        "tx_count": 20,
        "last_seen_ms": now_ms,
    }
    store.upsert_profile(profile_v2)

    fetched_v2 = store.get_profile("麦当劳")
    assert fetched_v2 is not None
    assert fetched_v2.tx_count == 20  # 覆盖 10 → 20
    assert fetched_v2.avg_amount == Decimal("32.00")  # 覆盖 30 → 32
    assert fetched_v2.amount_std == Decimal("4.50")
    assert fetched_v2.last_seen_ms == now_ms
    assert fetched_v2.updated_at_ms >= fetched_v1.updated_at_ms  # 后续 upsert 时间戳更新


# ===== Segment 5: list_by_counterparty 严判(2 cases,补到 transactions 测试文件)=====
# 实际位置:tests/db/test_transactions.py 内补 2 个 case(沿 plan §commit 5)
# 这里只放 1 个 case 触发 list_by_counterparty 真实链路(确保 ORM 改动生效)
# 其余 1 个 case 在 test_transactions.py 末尾追加


def test_list_by_counterparty_integration_with_profile(store: Any, tx_store: Any) -> None:
    """Case 9(integration) — TransactionStore.list_by_counterparty + MerchantProfileStore 联动.

    集成验证:历史交易 → 商家画像 — 模拟 D8.2 Detector 调用场景.
    """
    # 插 6 笔同商家(> 5 阈值)
    _seed_history(tx_store, "喜茶", n=6, base_amount=Decimal("35.00"))

    # 1. list_by_counterparty 直接查
    history = tx_store.list_by_counterparty("喜茶", limit=10)
    assert len(history) == 6
    assert all(h.counterparty == "喜茶" for h in history)

    # 2. compute_profile 联动 → 写入画像
    profile = store.compute_profile("喜茶")
    assert profile is not None
    assert profile["tx_count"] == 6
    assert profile["avg_amount"] == Decimal("35.00")

    # 3. upsert 画像
    store.upsert_profile(profile)
    fetched = store.get_profile("喜茶")
    assert fetched is not None
    assert fetched.tx_count == 6
    assert fetched.avg_amount == Decimal("35.00")
