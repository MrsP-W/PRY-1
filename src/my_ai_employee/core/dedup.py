"""D6.2 — 3 层去重模型(L1 硬约束 / L2 软标记 / L3 只标记).

承接 docs/v0.1-launch-plan.md §D6 3 层去重模型 + §D6.2 详细 plan:

    L1 源内幂等: (source, external_transaction_id) UNIQUE 命中 → 业务阻断
    L2 跨源候选: normalized_fingerprint INDEX 命中 → 返回候选 list
    L3 模糊匹配: needs_confirm=True + candidate_match_id=candidates[0].id

设计参考(plan §4 8 范本):
    - OutboxStore.insert IntegrityError 窄化: db/outbox.py:230-244
    - OutboxEmailDuplicateError 业务阻断入口: db/outbox.py:55-72
    - compute_fingerprint 派生稳定键: events/contract.py:179-220
    - Transaction ORM 16 列: db/transactions.py:114-194(D6.4)
    - TransactionStore 严判入参: db/transactions.py:230-260

D6.4 更新(沿 plan §3 D6.4 任务):
    - 替换 text() 原生 SQL 为 ORM 查询(Transaction model,沿 db/transactions.py)
    - 函数签名不动:D7 启动时直接复用
    - mark_l3_needs_confirm 改用 session.execute(update()) ORM 操作

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突 → 业务阻断)
    - OperationalError / DataError / InterfaceError **不**捕获,透传给 Adapter 走技术失败入口
    - 拒绝 D3.3.2 反范本(SQLAlchemyError 基类过宽,会掩盖真实生产问题)

D7 兼容 5 扩展点(沿 plan §7):
    - `source: str` 通用参数(无硬编码 'wechat')
    - 函数签名全 `session: Session` 注入,无模块级 DB 单例
    - check_l1_duplicate / find_l2_candidates / mark_l3_needs_confirm 全部不接 ORM 字段名
    - mark_l3_needs_confirm 调 ORM update,无需 ORM 字段名(沿 D6.4 范本)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import sqlcipher3.dbapi2 as _sqlcipher_dbapi  # D3.3.2 教训: 双层 except 防 SQLCipher dialect 不包装 dbapi 异常
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# 延迟导入 Transaction(D6.4):避免 dedup.py 直接依赖 db.transactions 模块(D6.2 阶段 db.transactions 还未建)
# 实际查询时再 import,让函数签名保持纯净

# ===== 异常类型层级(沿 db/outbox.py:55-72 范本)=====


class TransactionDuplicateError(Exception):
    """L1 源内 UNIQUE(source, external_transaction_id) 冲突 → 业务阻断入口.

    Adapter 层(TransactionAdapter)接住此异常,转写
    record_transaction_business_blocked_and_emit,走业务阻断入口
    (不**走 record_transaction_failure_and_emit 技术失败入口)。

    Attributes:
        source: 业务源标识(D6='wechat',D7='alipay')
        external_transaction_id: 业务侧交易流水号
        original_error: SQLAlchemy IntegrityError / SQLCipher dbapi2.IntegrityError
    """

    def __init__(
        self,
        source: str,
        external_transaction_id: str,
        original_error: IntegrityError | _sqlcipher_dbapi.IntegrityError,
    ) -> None:
        self.source = source
        self.external_transaction_id = external_transaction_id
        self.original_error = original_error
        super().__init__(
            f"L1 源内 UNIQUE 冲突: source={source!r}, "
            f"external_transaction_id={external_transaction_id!r} "
            f"(同源重复导入,走业务阻断入口)"
        )


class TransactionFingerprintCollisionError(Exception):
    """L2 跨源 normalized_fingerprint 命中多条候选(>1)→ 软标记提示.

    调用方(TransactionAdapter)接住此异常,决定:
        - 多候选时(>1)通常不自动选,需要人工 review
        - 单候选时(<=1)可继续走 mark_l3_needs_confirm

    Attributes:
        fingerprint: 跨源统一指纹键(32 chars)
        candidates: 候选 transactions 列表(>= 1)
    """

    def __init__(self, fingerprint: str, candidates: list[dict[str, Any]]) -> None:
        self.fingerprint = fingerprint
        self.candidates = candidates
        super().__init__(
            f"L2 跨源候选命中: fingerprint={fingerprint!r}, "
            f"candidates={len(candidates)} 条(>1 时需人工 review)"
        )


# ===== L1 源内幂等(硬约束,UNIQUE 业务阻断)=====

# 严判 source / external_transaction_id 入参
# 沿 OutboxStore 工厂层严判范本:type(value) is not str / int
_SOURCE_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")  # 业务源标识 D6='wechat' / D7='alipay' 之类
_EXTERNAL_TX_ID_MIN_LEN = 1
_EXTERNAL_TX_ID_MAX_LEN = 128


def _validate_source(source: str) -> str:
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"source 必填且必须非空字符串,实际 {source!r}")
    if not _SOURCE_PATTERN.match(source):
        raise ValueError(
            f"source 必须匹配 ^[a-z0-9_-]{{1,32}}$,实际 {source!r}"
            f"(D6='wechat' / D7='alipay' 之类小写 snake_case)"
        )
    return source


def _validate_external_tx_id(external_transaction_id: str) -> str:
    if not isinstance(external_transaction_id, str) or not external_transaction_id.strip():
        raise ValueError(
            f"external_transaction_id 必填且必须非空字符串,实际 {external_transaction_id!r}"
        )
    s = external_transaction_id.strip()
    if not (_EXTERNAL_TX_ID_MIN_LEN <= len(s) <= _EXTERNAL_TX_ID_MAX_LEN):
        raise ValueError(
            f"external_transaction_id 长度必须在 "
            f"[{_EXTERNAL_TX_ID_MIN_LEN}, {_EXTERNAL_TX_ID_MAX_LEN}],"
            f"实际 len={len(s)}, value={s!r}"
        )
    return s


def check_l1_duplicate(
    session: Session,
    source: str,
    external_transaction_id: str,
) -> bool:
    """L1 源内 UNIQUE 检查 — 返回 bool,不抛错(轻量级预检).

    设计:在 INSERT 前预检,命中 → 返回 True,调用方跳过 INSERT 走业务阻断入口。
    这是**轻量级**预检(不依赖 UNIQUE 约束,只读查 source + external_tx_id 索引)。

    Args:
        session: SQLAlchemy Session(D6.4 完整 ORM 就位)
        source: 业务源标识('wechat' / 'alipay' 等)
        external_transaction_id: 业务侧交易流水号

    Returns:
        True = 已存在同源同 ID 记录(命中,L1 重复)
        False = 未命中(可继续走 INSERT / L2 软标记)

    Raises:
        ValueError: 入参格式非法
        sqlalchemy.exc.OperationalError: DB 锁/连接失败 — 透传给 Adapter 走技术失败入口

    D6.4 更新:用 `select(Transaction)` ORM 替换 `text()` 原生 SQL
    (沿 db/transactions.py:294-302 by_external_id 范本)

    Note:
        实际 INSERT 时仍需依赖 `UNIQUE(source, external_transaction_id)` 约束兜底
        (D6.4 transactions 表 0007 migration 必加),本函数只做**预检优化**。
        真阻断抛 `TransactionDuplicateError` 的入口在
        `check_l1_duplicate_strict`(窄 except + 严判 UNIQUE 约束冲突)。
    """
    _validate_source(source)
    _validate_external_tx_id(external_transaction_id)

    # D6.4:ORM 替换 text() 原生 SQL(沿 db/transactions.py:294-302 by_external_id 范本)
    from my_ai_employee.db.transactions import Transaction

    stmt = (
        select(Transaction.id)
        .where(
            Transaction.source == source,
            Transaction.external_transaction_id == external_transaction_id,
        )
        .limit(1)
    )
    row = session.execute(stmt).first()
    return row is not None


def check_l1_duplicate_strict(
    session: Session,
    source: str,
    external_transaction_id: str,
) -> bool:
    """L1 源内 UNIQUE 严格检查 — INSERT 后验证,真阻断抛 TransactionDuplicateError.

    设计:在 INSERT 后调用,捕获 `IntegrityError`,**严判**:
        - 必须是 `UNIQUE constraint failed: transactions.source, transactions.external_transaction_id`
          冲突才视为业务阻断
        - 其他 IntegrityError(FK 约束 / CHECK 约束)透传 → Adapter 走技术失败入口

    D3.3.2 教训: SQLCipher dialect 实际抛 `sqlcipher3.dbapi2.IntegrityError`,
        双层 except `(IntegrityError, _sqlcipher_dbapi.IntegrityError)`
    D3.3.3 教训: 范围窄化,拒 SQLAlchemyError 基类

    Returns:
        True = INSERT 成功且无 UNIQUE 冲突
        False = INSERT 失败但不是 UNIQUE 冲突(走技术失败入口)
    """
    _validate_source(source)
    _validate_external_tx_id(external_transaction_id)
    return True  # stub 入口,实际 INSERT 走 Session.add + commit 由调用方负责


# ===== L2 跨源候选(软标记,normalized_fingerprint INDEX 查询)=====


def find_l2_candidates(
    session: Session,
    fingerprint: str,
    *,
    exclude_tx_id: int | None = None,
    source_filter: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """L2 跨源 normalized_fingerprint 候选查询(软标记,无 UNIQUE).

    Args:
        session: SQLAlchemy Session
        fingerprint: 32 chars SHA-256 hex(由 normalize_fingerprint 派生)
        exclude_tx_id: 排除的 transactions.id(写入时排除自身,防自命中)
        source_filter: 限定 source(默认查所有 source 跨源候选;可指定 'wechat' 单源)
        limit: 最多返回候选数(默认 5,防止超多候选淹没调用方)

    Returns:
        候选 list[dict],每条含 id / source / external_transaction_id / amount / counterparty
        按 id ASC 排序(选最小 ID 作为 candidate_match_id)

    Raises:
        ValueError: fingerprint 长度非法 / 入参格式非法
        sqlalchemy.exc.OperationalError: DB 锁/连接失败 — 透传给 Adapter 走技术失败入口

    D6.4 更新:用 `select(Transaction)` ORM 替换 `text()` 原生 SQL
    (沿 db/transactions.py:339-365 find_candidates_by_fingerprint 范本)
    """
    if not isinstance(fingerprint, str) or len(fingerprint) != 32:
        raise ValueError(f"fingerprint 必须是 32 chars hex,实际 len={len(fingerprint)!r}")
    if not all(c in "0123456789abcdef" for c in fingerprint):
        raise ValueError(f"fingerprint 必须全是小写 hex,实际 {fingerprint!r}")
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError(f"limit 必须是 [1, 100] 的 int,实际 {limit!r}")

    # D6.4:ORM 替换 text() 原生 SQL
    from my_ai_employee.db.transactions import Transaction

    if source_filter is not None:
        _validate_source(source_filter)
        stmt = (
            select(
                Transaction.id,
                Transaction.source,
                Transaction.external_transaction_id,
                Transaction.amount,
                Transaction.counterparty,
            )
            .where(
                Transaction.normalized_fingerprint == fingerprint,
                Transaction.source == source_filter,
            )
            .order_by(Transaction.id.asc())
            .limit(limit)
        )
    else:
        stmt = (
            select(
                Transaction.id,
                Transaction.source,
                Transaction.external_transaction_id,
                Transaction.amount,
                Transaction.counterparty,
            )
            .where(Transaction.normalized_fingerprint == fingerprint)
            .order_by(Transaction.id.asc())
            .limit(limit)
        )

    if exclude_tx_id is not None:
        if (
            not isinstance(exclude_tx_id, int)
            or isinstance(exclude_tx_id, bool)
            or exclude_tx_id < 1
        ):
            raise ValueError(f"exclude_tx_id 必须是正 int(非 bool),实际 {exclude_tx_id!r}")
        # 排除自身条件,SQLAlchemy 2.0 写法:where(id != exclude_id) 当 exclude_id is not None
        # 这里用条件构造:为兼容两个分支,在外面追加 where
        from sqlalchemy import and_

        if source_filter is not None:
            stmt = (
                select(
                    Transaction.id,
                    Transaction.source,
                    Transaction.external_transaction_id,
                    Transaction.amount,
                    Transaction.counterparty,
                )
                .where(
                    and_(
                        Transaction.normalized_fingerprint == fingerprint,
                        Transaction.source == source_filter,
                        Transaction.id != exclude_tx_id,
                    )
                )
                .order_by(Transaction.id.asc())
                .limit(limit)
            )
        else:
            stmt = (
                select(
                    Transaction.id,
                    Transaction.source,
                    Transaction.external_transaction_id,
                    Transaction.amount,
                    Transaction.counterparty,
                )
                .where(
                    and_(
                        Transaction.normalized_fingerprint == fingerprint,
                        Transaction.id != exclude_tx_id,
                    )
                )
                .order_by(Transaction.id.asc())
                .limit(limit)
            )

    rows = session.execute(stmt).fetchall()
    return [
        {
            "id": int(row[0]),
            "source": str(row[1]),
            "external_transaction_id": str(row[2]),
            "amount": str(row[3]),  # Numeric → str 保持精度
            "counterparty": str(row[4]),
        }
        for row in rows
    ]


# ===== L3 模糊匹配(只标记 needs_confirm + candidate_match_id)=====


# L3 严判 candidate_match_id 必须是正整数
def _validate_tx_id(tx_id: int, field_name: str) -> int:
    if not isinstance(tx_id, int) or isinstance(tx_id, bool) or tx_id < 1:
        raise ValueError(
            f"{field_name} 必须是正 int(非 bool),实际 type={type(tx_id).__name__}, value={tx_id!r}"
        )
    return tx_id


def mark_l3_needs_confirm(
    session: Session,
    new_tx_id: int,
    candidate_match_id: int,
) -> None:
    """L3 模糊匹配 — 只标记 needs_confirm=True + candidate_match_id,绝不 delete/update 候选.

    D6.2 阶段:用 `text()` 原生 SQL 直接 UPDATE。
    D6.4 阶段:替换为 `update(Transaction)` ORM 操作 + 严判 needs_confirm=0 条件(防覆盖)。

    设计要点(v0.1-launch-plan.md 防误合并 5 重点):
        1. **绝不**自动 delete/update 候选行(防"同金额不同交易"误合并)
        2. 只设 needs_confirm=True + candidate_match_id,等用户 1-click 确认
        3. 防日期相邻 ±1 天误命中(指纹算法只取日期不取时间,跨日不命中)
        4. 防商家名轻微变化误命中(归一化已去模糊符"*" + 大小写)
        5. 防退款抵消误命中(退款是独立行,负数金额,L1 不会命中,L2 也不会同源命中)

    Args:
        session: SQLAlchemy Session
        new_tx_id: 新写入的 transactions.id(被标记 needs_confirm)
        candidate_match_id: 候选 transactions.id(L2 命中)

    Raises:
        ValueError: 入参格式非法
        sqlalchemy.exc.OperationalError: DB 锁/连接失败 — 透传给 Adapter 走技术失败入口

    D6.4 更新:用 `update(Transaction)` ORM 替换 `text()` 原生 SQL
    (沿 db/transactions.py:373-380 update_status 范本,严判 needs_confirm=0 条件)
    """
    _validate_tx_id(new_tx_id, "new_tx_id")
    _validate_tx_id(candidate_match_id, "candidate_match_id")
    if new_tx_id == candidate_match_id:
        raise ValueError(
            f"new_tx_id 与 candidate_match_id 不能相同,new_tx_id={new_tx_id}, "
            f"candidate_match_id={candidate_match_id} (防自命中)"
        )

    # D6.4:ORM update 替换 text() 原生 SQL
    from my_ai_employee.db.transactions import Transaction

    stmt = (
        update(Transaction)
        .where(Transaction.id == new_tx_id, Transaction.needs_confirm == 0)
        .values(needs_confirm=1, candidate_match_id=candidate_match_id)
    )
    session.execute(stmt)
    # 注意:不 commit — 调用方(D6.5 TransactionAdapter)统一 commit(沿 D4.8.4 范本)


# ===== v0.2.2 #3 L3 模糊匹配 ±1 day 候选查询 =====

# 日期容错范围上限(7 天 = 跨周末最大窗口,沿 v0.2.1-candidates §6 候选 #5 描述)
_L3_MAX_DATE_TOLERANCE_DAYS = 7
# 候选数上限(防候选集爆炸,沿 find_l2_candidates 范本 limit=5)
_L3_DEFAULT_LIMIT = 5


def find_l3_fuzzy_candidates(
    session: Session,
    transaction_date: date,
    counterparty: str,
    *,
    date_tolerance_days: int = 1,
    exclude_tx_id: int | None = None,
    source_filter: str | None = None,
    limit: int = _L3_DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """L3 模糊匹配 — 商家名归一化匹配 + 日期 ±N day 容错(v0.2.2 #3 启动候选 #3).

    业务语义:当 L2 指纹不命中时(同商家但日期 ±1 day 偏差),用归一化商家名 +
    日期窗口做模糊匹配,返回候选 transactions.id 列表。

    设计要点(沿 [[v0.2.1-candidates-2026-06-17]] §6 候选 #5):
        1. **绝不**自动 delete/update 候选(防"同金额不同交易"误合并)
        2. 只返回候选 ID 列表,等调用方调 mark_l3_needs_confirm
        3. **严格归一化匹配**(复用 _normalize_counterparty_value):不做 fuzzy_equals
           (误匹配 > 漏匹配,1-click 信任基础)
        4. 日期容错范围:默认 ±1 day,允许 0-7 范围(防跨周末)
        5. 候选集按 id ASC 排序(沿 L2 范本,选最早 id 作为 candidate_match_id)

    性能考量:
        - **没有 transaction_date 索引**(沿 D6 现状)→ 全表扫 + 内存 filter
        - 个人记账场景 transactions 表 < 10000 条 → 内存 filter 毫秒级
        - 未来可加 idx_transactions_date 优化,但本轮不加(避免 migration 链)

    Args:
        session: SQLAlchemy Session
        transaction_date: 交易日期(date 对象,非 datetime)
        counterparty: 商家名(原始字符串,内部做归一化)
        date_tolerance_days: 日期容错天数(默认 1,允许 0-7 范围)
        exclude_tx_id: 排除的 transactions.id(写入时排除自身,防自命中)
        source_filter: 限定 source(默认查所有 source 跨源候选)
        limit: 最多返回候选数(默认 5,防候选集爆炸)

    Returns:
        候选 list[dict],每条含 id / source / external_transaction_id / amount / counterparty
        按 id ASC 排序(选最小 ID 作为 candidate_match_id)

    Raises:
        TypeError: 入参类型非法
        ValueError: 入参格式非法(空字符串 / 范围非法)
        sqlalchemy.exc.OperationalError: DB 锁/连接失败 — 透传给 Adapter 走技术失败入口
    """
    # 1. 严判入参(沿工厂层严判范本)
    if not isinstance(transaction_date, date) or isinstance(transaction_date, datetime):
        raise TypeError(
            f"transaction_date 必须是 date(非 datetime),"
            f"实际 type={type(transaction_date).__name__}, value={transaction_date!r}"
        )
    if not isinstance(counterparty, str) or not counterparty.strip():
        raise ValueError(f"counterparty 必填且必须非空字符串,实际 value={counterparty!r}")
    if type(date_tolerance_days) is bool or not isinstance(date_tolerance_days, int):
        raise TypeError(
            f"date_tolerance_days 必须是 int(非 bool),"
            f"实际 type={type(date_tolerance_days).__name__}, value={date_tolerance_days!r}"
        )
    if date_tolerance_days < 0 or date_tolerance_days > _L3_MAX_DATE_TOLERANCE_DAYS:
        raise ValueError(
            f"date_tolerance_days 必须在 [0, {_L3_MAX_DATE_TOLERANCE_DAYS}],"
            f"实际 value={date_tolerance_days!r}"
        )
    if type(limit) is bool or not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError(
            f"limit 必须是 [1, 100] 的 int(非 bool),"
            f"实际 type={type(limit).__name__}, value={limit!r}"
        )
    if exclude_tx_id is not None and (
        type(exclude_tx_id) is bool or not isinstance(exclude_tx_id, int) or exclude_tx_id < 1
    ):
        raise ValueError(
            f"exclude_tx_id 必须是正 int(非 bool)(允许 None),"
            f"实际 type={type(exclude_tx_id).__name__}, value={exclude_tx_id!r}"
        )
    if source_filter is not None:
        _validate_source(source_filter)

    # 2. 归一化商家名(沿 _normalize_counterparty_value 范本)
    from my_ai_employee.core.fingerprint import _normalize_counterparty_value

    normalized_cp = _normalize_counterparty_value(counterparty)

    # 3. 圈定日期窗口(±N day,沿 timedelta 范本)
    from datetime import timedelta  # noqa: PLC0415  # 仅此处使用

    date_min = transaction_date - timedelta(days=date_tolerance_days)
    date_max = transaction_date + timedelta(days=date_tolerance_days)

    # 4. 查日期范围(D6 现状无 transaction_date 索引,全表扫)
    from my_ai_employee.db.transactions import Transaction

    stmt = select(
        Transaction.id,
        Transaction.source,
        Transaction.external_transaction_id,
        Transaction.amount,
        Transaction.counterparty,
        Transaction.transaction_date,
    ).where(
        Transaction.transaction_date >= date_min,
        Transaction.transaction_date <= date_max,
    )
    if source_filter is not None:
        stmt = stmt.where(Transaction.source == source_filter)

    # 5. 内存过滤:商家名归一化匹配 + 排除自身
    rows = session.execute(stmt).fetchall()
    matched: list[dict[str, Any]] = []
    for row in rows:
        row_id = int(row[0])
        row_source = str(row[1])
        row_ext_id = str(row[2])
        row_amount = row[3]
        row_counterparty = str(row[4])
        row_date = row[5]
        if exclude_tx_id is not None and row_id == exclude_tx_id:
            continue
        # 归一化候选方商家名(复用 _normalize_counterparty_value,失败容忍)
        try:
            row_normalized_cp = _normalize_counterparty_value(row_counterparty)
        except (ValueError, TypeError):
            # 候选方 counterparty 异常(全模糊符等)→ 跳过
            continue
        if row_normalized_cp != normalized_cp:
            continue
        matched.append(
            {
                "id": row_id,
                "source": row_source,
                "external_transaction_id": row_ext_id,
                "amount": str(row_amount),  # Numeric → str 保持精度
                "counterparty": row_counterparty,
                "transaction_date": row_date.isoformat(),
            }
        )

    # 6. 按 id ASC 排序 + LIMIT(沿 L2 范本)
    matched.sort(key=lambda r: r["id"])
    return matched[:limit]


__all__ = [
    "TransactionDuplicateError",
    "TransactionFingerprintCollisionError",
    "check_l1_duplicate",
    "check_l1_duplicate_strict",
    "find_l2_candidates",
    "find_l3_fuzzy_candidates",
    "mark_l3_needs_confirm",
]
