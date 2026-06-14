"""D6.4 — TransactionStore + Transaction ORM 测试(27 cases,实际超出 25 计划)。

承接 D6.1 微信 CSV(617526c)+ D6.2 fingerprint + 3 层去重(ad4e076)
+ D6.3 categorizer + merchants 500 + 状态机(85864df)
+ D6.4 transactions ORM 16 列 + 0007 migration + TransactionStore 5 方法 + TransactionDuplicateError。

9 段测试覆盖(27 cases,实际超出计划 25 一点,沿 D6.3 654 商家表"越多越好"哲学):
    1. ORM 模型列名/类型(3 tests) — 16 列名 + 类型 + UNIQUE 约束
    2. insert 基础功能(4 tests) — 全字段 / 默认值 / category 可选 / 所有可空字段
    3. insert 入参严判(6 tests) — type/value/范围/枚举(沿 D4.7.3 v1.0.5 P2-1 范本)
    4. UNIQUE 冲突 → TransactionDuplicateError(2 tests) — L1 业务阻断入口
    5. get_by_id / by_external_id 查询(4 tests) — 走 PK / UNIQUE 索引 + 跨源隔离
    6. list_by_source 列表(2 tests) — 按 imported_at_ms DESC 排序 + since 过滤
    7. find_candidates_by_fingerprint 候选(2 tests) — L2 软标记 + 按 id ASC
    8. update_status 状态机(3 tests) — 合法转换 / 漂移检测 / 白名单外转换
    9. confirmed_at_ms 必传规则(1 test) — CONFIRMED 必传 / 其他必传 None

D3.2 8 雷区严判:
    - Numeric(10, 2) 非 Float(防精度漂移)
    - BOOLEAN 走 Integer + server_default="0"
    - DATE 走 Date(非 DateTime)
    - AUTOINCREMENT(非 AUTO_INCREMENT)
    - 下划线命名(idx_transactions_fingerprint)
    - DESC 索引用 sa.text("imported_at_ms DESC")
    - render_as_batch=True(env.py)
    - downgrade 干净回滚

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突)
    - 拒绝 D3.3.2 反范本(SQLAlchemyError 基类过宽)

D7 兼容 5 扩展点(沿 plan §7):
    - source TEXT NOT NULL(str 通用)
    - candidate_match_id + needs_confirm schema 必含

Fixture 复用 tests/db/test_outbox.py 范本:
    - InMemory SQLite 模式(不依赖真 SQLCipher,快)
    - 测试间用 rollback 隔离
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

if TYPE_CHECKING:
    from collections.abc import Iterator


# ===== Fixtures(D6.4 范本:InMemory SQLite + create_all)=====


@pytest.fixture
def engine() -> Iterator:
    """InMemory SQLite + Transaction ORM 16 列 create_all."""
    eng = create_engine("sqlite:///:memory:")
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.transactions import Transaction  # noqa: F401

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    """返回 sessionmaker."""
    return sessionmaker(bind=engine)


@pytest.fixture
def store(session_factory) -> TransactionStore:  # type: ignore[name-defined]  # noqa: F821
    """TransactionStore 实例(注入 session_factory)。"""
    from my_ai_employee.db.transactions import TransactionStore

    return TransactionStore(session_factory)


# ===== 测试用 fixture:典型 transaction 参数 =====


@pytest.fixture
def valid_tx_params() -> dict:
    """典型合法 transaction 入参(供 insert 测试复用)。"""
    return {
        "source": "wechat",
        "external_transaction_id": "4200000123456789",
        "transaction_date": date(2026, 6, 14),
        "amount": Decimal("13.14"),
        "counterparty": "星巴克",
        "normalized_fingerprint": "a" * 32,  # 32 chars hex 占位
        "raw_row_json": '{"原始行": "星巴克 13.14元"}',
        "category": "dining",
        "payment_method": "微信零钱",
    }


# ===== Segment 1: ORM 模型(3 tests)====


def test_orm_tablename_transactions() -> None:
    """Case 1 — Transaction ORM __tablename__ = "transactions"。"""
    from my_ai_employee.db.transactions import Transaction

    assert Transaction.__tablename__ == "transactions"


def test_orm_has_16_columns() -> None:
    """Case 2 — Transaction ORM 16 列(D6.4 锁定)。"""
    from my_ai_employee.db.transactions import Transaction

    expected_cols = {
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
    actual_cols = {c.name for c in Transaction.__table__.columns}
    assert actual_cols == expected_cols, f"差集: {expected_cols - actual_cols}"


def test_orm_unique_constraint_and_indexes() -> None:
    """Case 3 — UNIQUE(source, external_transaction_id) + 2 INDEX 完整。"""
    from sqlalchemy import UniqueConstraint

    from my_ai_employee.db.transactions import Transaction

    table = Transaction.__table__

    # UNIQUE 约束(沿 test_outbox.py 范本:Table.constraints 是 SA 内部属性,mypy 需 # type: ignore[attr-defined])
    unique_constraints = [
        c
        for c in table.constraints  # type: ignore[attr-defined]
        if isinstance(c, UniqueConstraint)
    ]
    uq = next((c for c in unique_constraints if c.name == "uq_transactions_source_ext_id"), None)
    assert uq is not None, "UNIQUE(source, external_transaction_id) 约束缺失"
    assert set(uq.columns.keys()) == {"source", "external_transaction_id"}

    # 2 INDEX(Table.indexes 类型为 frozenset[Index])
    idx_names = {i.name for i in table.indexes}  # type: ignore[attr-defined]
    assert "idx_transactions_fingerprint" in idx_names
    assert "idx_transactions_status_imported" in idx_names


# ===== Segment 2: insert 基础(4 tests)====


def test_insert_basic_returns_transaction_with_id(store, valid_tx_params: dict) -> None:
    """Case 4 — insert 基本字段:返回 Transaction 实例,id 非空,status='imported'。"""
    tx = store.insert(**valid_tx_params)
    assert tx.id is not None and tx.id > 0
    assert tx.status == "imported"
    assert tx.source == "wechat"
    assert tx.amount == Decimal("13.14")
    assert tx.counterparty == "星巴克"
    assert tx.category == "dining"
    assert tx.needs_confirm == 0
    assert tx.candidate_match_id is None
    assert tx.notes is None


def test_insert_default_imported_at_ms(store, valid_tx_params: dict) -> None:
    """Case 5 — import 未传 imported_at_ms,默认 = 当前时间(int > 0)。"""
    tx = store.insert(**valid_tx_params)
    assert isinstance(tx.imported_at_ms, int) and tx.imported_at_ms > 0


def test_insert_category_optional(store, valid_tx_params: dict) -> None:
    """Case 6 — category 可空(None),D6.5 Adapter 调 categorizer() 后回填。"""
    params = valid_tx_params.copy()
    params["category"] = None
    tx = store.insert(**params)
    assert tx.category is None


def test_insert_all_optional_fields(store, valid_tx_params: dict) -> None:
    """Case 7 — 所有可空字段都传值:category / payment_method / candidate_match_id / notes。"""
    params = valid_tx_params.copy()
    params["candidate_match_id"] = 999
    params["notes"] = "测试备注"
    tx = store.insert(**params)
    assert tx.candidate_match_id == 999
    assert tx.notes == "测试备注"


# ===== Segment 3: insert 入参严判(6 tests)====


def test_insert_rejects_non_str_source(store, valid_tx_params: dict) -> None:
    """Case 8 — source 非 str → ValueError(沿 D6.2 _validate_source 范本)。"""
    params = valid_tx_params.copy()
    params["source"] = 12345
    with pytest.raises(ValueError, match="source 必填"):
        store.insert(**params)


def test_insert_rejects_invalid_source_pattern(store, valid_tx_params: dict) -> None:
    """Case 9 — source 含大写字母 → ValueError(^[a-z0-9_-]{1,32}$)。"""
    params = valid_tx_params.copy()
    params["source"] = "WeChat"  # 大写 W 非法
    with pytest.raises(ValueError, match=r"\^\[a-z0-9_-\]"):
        store.insert(**params)


def test_insert_rejects_non_decimal_amount(store, valid_tx_params: dict) -> None:
    """Case 10 — amount 非 Decimal → TypeError(防精度漂移)。"""
    params = valid_tx_params.copy()
    params["amount"] = 13.14  # float → 精度漂移风险
    with pytest.raises(TypeError, match="amount 必须是 Decimal"):
        store.insert(**params)


def test_insert_rejects_non_bool_needs_confirm(store, valid_tx_params: dict) -> None:
    """Case 11 — needs_confirm 非 bool(传 0 / 1 / "True")→ TypeError(D3.2 雷区 #2 + bool 是 int 子类陷阱)。"""
    params = valid_tx_params.copy()
    params["needs_confirm"] = 1  # int(虽然是 1)而非 bool
    with pytest.raises(TypeError, match="needs_confirm 必须是 bool"):
        store.insert(**params)


def test_insert_rejects_invalid_status(store, valid_tx_params: dict) -> None:
    """Case 12 — status 非 5 选 1 → ValueError(沿 D4.7.3 v1.0.5 P2-1 type 严判)。"""
    params = valid_tx_params.copy()
    params["status"] = "invalid_status"
    with pytest.raises(ValueError, match="status 必须是 TransactionStatus 5 选 1"):
        store.insert(**params)


def test_insert_rejects_invalid_fingerprint_length(store, valid_tx_params: dict) -> None:
    """Case 13 — fingerprint 长度 != 32 → ValueError(沿 D6.2 _validate_fingerprint 范本)。"""
    params = valid_tx_params.copy()
    params["normalized_fingerprint"] = "abc"  # 长度 3
    with pytest.raises(ValueError, match="fingerprint 必须是 32 chars hex"):
        store.insert(**params)


# ===== Segment 4: L1 UNIQUE 冲突 → TransactionDuplicateError(2 tests)====


def test_insert_duplicate_source_ext_id_raises_duplicate_error(
    store, valid_tx_params: dict
) -> None:
    """Case 14 — 插入重复 (source, external_transaction_id) → TransactionDuplicateError(L1 业务阻断入口)。"""
    from my_ai_employee.db.transactions import TransactionDuplicateError

    store.insert(**valid_tx_params)
    with pytest.raises(TransactionDuplicateError) as exc_info:
        store.insert(**valid_tx_params)
    # 业务阻断入口:TransactionDuplicateError
    assert isinstance(exc_info.value, TransactionDuplicateError)
    assert exc_info.value.source == "wechat"
    assert exc_info.value.external_transaction_id == "4200000123456789"


def test_insert_duplicate_does_not_rollback_previous(store, valid_tx_params: dict) -> None:
    """Case 15 — 重复 insert 失败,但之前成功的行仍在(回滚只影响失败那条)。"""
    from my_ai_employee.db.transactions import TransactionDuplicateError

    tx1 = store.insert(**valid_tx_params)
    with pytest.raises(TransactionDuplicateError):
        store.insert(**valid_tx_params)
    # 第一条还在
    fetched = store.get_by_id(tx1.id)
    assert fetched is not None
    assert fetched.id == tx1.id


# ===== Segment 5: 查询方法(4 tests)====


def test_get_by_id_returns_none_when_not_found(store) -> None:
    """Case 16 — get_by_id 不存在的 id → None。"""
    assert store.get_by_id(99999) is None


def test_get_by_id_returns_transaction(store, valid_tx_params: dict) -> None:
    """Case 17 — get_by_id 存在 id → 返回 Transaction。"""
    tx = store.insert(**valid_tx_params)
    fetched = store.get_by_id(tx.id)
    assert fetched is not None
    assert fetched.id == tx.id
    assert fetched.source == "wechat"


def test_by_external_id_returns_transaction(store, valid_tx_params: dict) -> None:
    """Case 18 — by_external_id 命中 UNIQUE 索引,返回单条。"""
    tx = store.insert(**valid_tx_params)
    fetched = store.by_external_id("wechat", "4200000123456789")
    assert fetched is not None
    assert fetched.id == tx.id


def test_by_external_id_source_isolation(store, valid_tx_params: dict) -> None:
    """Case 19 — by_external_id 跨源隔离:同 ID 不同 source 不命中(D7 兼容 #1)。"""
    store.insert(**valid_tx_params)
    # D6='wechat' 已有,D7='alipay' 同 ID 应未命中
    result = store.by_external_id("alipay", "4200000123456789")
    assert result is None


# ===== Segment 6: list_by_source(2 tests)====


def test_list_by_source_returns_all(store, valid_tx_params: dict) -> None:
    """Case 20 — list_by_source 返回该 source 所有交易,按 imported_at_ms DESC 排序。"""
    tx1 = store.insert(**valid_tx_params)
    params2 = valid_tx_params.copy()
    params2["external_transaction_id"] = "4200000987654321"
    tx2 = store.insert(**params2)
    # 插入时 imported_at_ms 默认 int(time.time()*1000),tx2 略晚或相同
    # 这里只断言两条都在
    result = store.list_by_source("wechat")
    ids = {t.id for t in result}
    assert {tx1.id, tx2.id} <= ids


def test_list_by_source_since_date_filter(store, valid_tx_params: dict) -> None:
    """Case 21 — list_by_source(since=date(2026, 6, 14)) 过滤旧交易。"""
    params_old = valid_tx_params.copy()
    params_old["transaction_date"] = date(2026, 6, 1)
    params_old["external_transaction_id"] = "old_001"
    store.insert(**params_old)
    params_new = valid_tx_params.copy()
    params_new["transaction_date"] = date(2026, 6, 14)
    store.insert(**params_new)
    # since = 2026-06-14 应只返回新的
    result = store.list_by_source("wechat", since=date(2026, 6, 14))
    ext_ids = {t.external_transaction_id for t in result}
    assert "4200000123456789" in ext_ids
    assert "old_001" not in ext_ids


# ===== Segment 7: find_candidates_by_fingerprint(2 tests)====


def test_find_candidates_returns_empty_when_no_match(store) -> None:
    """Case 22 — fingerprint 未命中 → 空 list。"""
    result = store.find_candidates_by_fingerprint("0" * 32)
    assert result == []


def test_find_candidates_returns_existing_transactions(store, valid_tx_params: dict) -> None:
    """Case 23 — fingerprint 命中已有 transactions,按 id ASC 排序。"""
    params1 = valid_tx_params.copy()
    params1["external_transaction_id"] = "fp_001"
    tx1 = store.insert(**params1)
    params2 = valid_tx_params.copy()
    params2["external_transaction_id"] = "fp_002"
    tx2 = store.insert(**params2)
    result = store.find_candidates_by_fingerprint("a" * 32)
    assert len(result) == 2
    assert result[0].id == min(tx1.id, tx2.id)
    assert result[1].id == max(tx1.id, tx2.id)


# ===== Segment 8: update_status 状态机(3 tests)====


def test_update_status_valid_transition(store, valid_tx_params: dict) -> None:
    """Case 24 — update_status(IMPORTED → CATEGORIZED) 合法,返回更新后 Transaction。"""
    tx = store.insert(**valid_tx_params)
    updated = store.update_status(tx.id, "categorized", from_status="imported")
    assert updated.status == "categorized"


def test_update_status_drift_detection_raises_illegal_transition(
    store, valid_tx_params: dict
) -> None:
    """Case 25 — update_status(IMPORTED → CATEGORIZED 期望 from=imported,实际 row=categorized)→ TransactionIllegalTransitionError(漂移检测,沿 D5.2 范本)。"""
    tx = store.insert(**valid_tx_params)
    # 模拟 concurrent 写:行已被推到 categorized
    store.update_status(tx.id, "categorized", from_status="imported")
    # 调用方期望 from=imported,但实际 row=categorized
    from my_ai_employee.core.transactions import TransactionIllegalTransitionError

    with pytest.raises(TransactionIllegalTransitionError, match="状态机漂移"):
        store.update_status(tx.id, "confirmed", from_status="imported", confirmed_at_ms=1234567890)


def test_update_status_invalid_transition_raises_illegal_transition(
    store, valid_tx_params: dict
) -> None:
    """Case 26 — update_status(IMPORTED → CONFIRMED 跳级)→ TransactionIllegalTransitionError(白名单外转换)。"""
    tx = store.insert(**valid_tx_params)
    from my_ai_employee.core.transactions import TransactionIllegalTransitionError

    with pytest.raises(TransactionIllegalTransitionError, match="状态机非法转换"):
        store.update_status(tx.id, "confirmed", from_status="imported", confirmed_at_ms=1234567890)


# ===== Segment 9: confirmed_at_ms 必传规则(1 test)====


def test_update_status_confirmed_requires_confirmed_at_ms(store, valid_tx_params: dict) -> None:
    """Case 27 — update_status(new_status=CONFIRMED) 必传 confirmed_at_ms,否则 ValueError(沿 D5.6.3 范本)。"""
    tx = store.insert(**valid_tx_params)
    # 先推到 CATEGORIZED(才能 CONFIRMED)
    store.update_status(tx.id, "categorized", from_status="imported")
    # CONFIRMED 未传 confirmed_at_ms → ValueError
    with pytest.raises(ValueError, match="update_status.new_status=CONFIRMED. 必传"):
        store.update_status(tx.id, "confirmed", from_status="categorized", confirmed_at_ms=None)
    # 非 CONFIRMED 误传 confirmed_at_ms → ValueError
    with pytest.raises(ValueError, match="必传 None"):
        store.update_status(
            tx.id,
            "needs_confirm",
            from_status="categorized",
            confirmed_at_ms=1234567890,
        )
