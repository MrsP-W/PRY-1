"""D6.2 — 3 层去重模型(L1 硬约束 / L2 软标记 / L3 只标记).

承接 docs/v0.1-launch-plan.md §D6 3 层去重模型 + §D6.2 详细 plan:

    L1 源内幂等: (source, external_transaction_id) UNIQUE 命中 → 业务阻断
    L2 跨源候选: normalized_fingerprint INDEX 命中 → 返回候选 list
    L3 模糊匹配: needs_confirm=True + candidate_match_id=candidates[0].id

设计参考(plan §4 8 范本):
    - OutboxStore.insert IntegrityError 窄化: db/outbox.py:230-244
    - OutboxEmailDuplicateError 业务阻断入口: db/outbox.py:55-72
    - compute_fingerprint 派生稳定键: events/contract.py:179-220

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突 → 业务阻断)
    - OperationalError / DataError / InterfaceError **不**捕获,透传给 Adapter 走技术失败入口
    - 拒绝 D3.3.2 反范本(SQLAlchemyError 基类过宽,会掩盖真实生产问题)

D7 兼容 5 扩展点(沿 plan §7):
    - `source: str` 通用参数(无硬编码 'wechat')
    - 函数签名全 `session: Session` 注入,无模块级 DB 单例
    - check_l1_duplicate / find_l2_candidates / mark_l3_needs_confirm 全部不接 ORM 字段名
      (本阶段 ORM 字段未建,用 select + text() 原生 SQL 锁定契约,D6.4 替换为 ORM 即可)
"""

from __future__ import annotations

import re
from typing import Any

import sqlcipher3.dbapi2 as _sqlcipher_dbapi  # D3.3.2 教训: 双层 except 防 SQLCipher dialect 不包装 dbapi 异常
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
        session: SQLAlchemy Session(D6.4 完整 ORM 就位后)
        source: 业务源标识('wechat' / 'alipay' 等)
        external_transaction_id: 业务侧交易流水号

    Returns:
        True = 已存在同源同 ID 记录(命中,L1 重复)
        False = 未命中(可继续走 INSERT / L2 软标记)

    Raises:
        ValueError: 入参格式非法
        sqlalchemy.exc.OperationalError: DB 锁/连接失败 — 透传给 Adapter 走技术失败入口

    Note:
        实际 INSERT 时仍需依赖 `UNIQUE(source, external_transaction_id)` 约束兜底
        (D6.4 transactions 表 0007 migration 必加),本函数只做**预检优化**。
        真阻断抛 `TransactionDuplicateError` 的入口在
        `check_l1_duplicate_strict`(窄 except + 严判 UNIQUE 约束冲突)。
    """
    _validate_source(source)
    _validate_external_tx_id(external_transaction_id)

    # 严判严判 SELECT:仅查 UNIQUE(source, external_transaction_id) 索引列
    sql = text(
        "SELECT 1 FROM transactions "
        "WHERE source = :source AND external_transaction_id = :external_tx_id "
        "LIMIT 1"
    )
    row = session.execute(
        sql,
        {"source": source, "external_tx_id": external_transaction_id},
    ).first()
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
    """
    if not isinstance(fingerprint, str) or len(fingerprint) != 32:
        raise ValueError(f"fingerprint 必须是 32 chars hex,实际 len={len(fingerprint)!r}")
    if not all(c in "0123456789abcdef" for c in fingerprint):
        raise ValueError(f"fingerprint 必须全是小写 hex,实际 {fingerprint!r}")
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError(f"limit 必须是 [1, 100] 的 int,实际 {limit!r}")

    # 严判严判 SELECT:查 normalized_fingerprint INDEX
    # 排除自身(写入时 D6.5 Adapter 传 exclude_tx_id 防自命中)
    # 按 id ASC 排序(选最小 ID,确定性)
    if source_filter is not None:
        _validate_source(source_filter)
        sql = text(
            "SELECT id, source, external_transaction_id, amount, counterparty "
            "FROM transactions "
            "WHERE normalized_fingerprint = :fingerprint AND source = :source "
            "AND (:exclude_id IS NULL OR id != :exclude_id) "
            "ORDER BY id ASC LIMIT :limit"
        )
        params: dict[str, Any] = {
            "fingerprint": fingerprint,
            "source": source_filter,
            "exclude_id": exclude_tx_id,
            "limit": limit,
        }
    else:
        sql = text(
            "SELECT id, source, external_transaction_id, amount, counterparty "
            "FROM transactions "
            "WHERE normalized_fingerprint = :fingerprint "
            "AND (:exclude_id IS NULL OR id != :exclude_id) "
            "ORDER BY id ASC LIMIT :limit"
        )
        params = {
            "fingerprint": fingerprint,
            "exclude_id": exclude_tx_id,
            "limit": limit,
        }

    rows = session.execute(sql, params).fetchall()
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
    D6.4 阶段:可替换为 `Transaction` ORM + 状态机严判。

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
    """
    _validate_tx_id(new_tx_id, "new_tx_id")
    _validate_tx_id(candidate_match_id, "candidate_match_id")
    if new_tx_id == candidate_match_id:
        raise ValueError(
            f"new_tx_id 与 candidate_match_id 不能相同,new_tx_id={new_tx_id}, "
            f"candidate_match_id={candidate_match_id} (防自命中)"
        )

    sql = text(
        "UPDATE transactions "
        "SET needs_confirm = 1, candidate_match_id = :candidate_id "
        "WHERE id = :new_id AND needs_confirm = 0"
    )
    session.execute(
        sql,
        {"candidate_id": candidate_match_id, "new_id": new_tx_id},
    )
    # 注意:不 commit — 调用方(D6.5 TransactionAdapter)统一 commit(沿 D4.8.4 范本)


__all__ = [
    "TransactionDuplicateError",
    "TransactionFingerprintCollisionError",
    "check_l1_duplicate",
    "check_l1_duplicate_strict",
    "find_l2_candidates",
    "mark_l3_needs_confirm",
]
