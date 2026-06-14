"""D6.4 — TransactionStore:transactions 表读写封装(16 列 + 3 层去重模型 ORM).

承接 D6.1 微信 CSV 解析器(617526c)+ D6.2 fingerprint + 3 层去重(ad4e076)
+ D6.3 categorizer + merchants 500 + 状态机(85864df,5 状态 + ALLOWED_TRANSITIONS)
+ D6.4 0007 alembic migration(UNIQUE 复合 + 2 INDEX + 16 列 DDL)。

设计(沿 D4.8 OutboxStore 范本 + D3.2 8 雷区严判):
  - 16 列: id / source / external_transaction_id / transaction_date / amount
           / counterparty / category / payment_method / normalized_fingerprint
           / needs_confirm / candidate_match_id / status / imported_at_ms
           / confirmed_at_ms / raw_row_json / notes
  - insert(): L1 源内 UNIQUE 命中 → TransactionDuplicateError(业务阻断)
              严判 type/value/范围(Numeric 10,2 / BOOLEAN 走 Integer / DATE 走 Date)
  - get_by_id / list_by_source / find_candidates_by_fingerprint:3 类热路径查询
  - update_status(D6.4 新签名):必传 from_status + 调 assert_transition 严判
             状态漂移检测 + 白名单外转换(双层严判,沿 D5.2 范本)
  - 严判只放在 Adapter 层(契约层 TransactionStore 接受已校验参数,不再二次严判)

D3.2 8 雷区严判:
  - Numeric(10, 2) 非 Float(防精度漂移 13.14 == 13.140)
  - BOOLEAN 走 Integer + server_default="0"(SQLite 无 BOOLEAN 类型)
  - DATE 走 Date(非 DateTime,指纹算法只取日期)
  - AUTOINCREMENT(非 AUTO_INCREMENT)
  - 文件名 0007_transactions.py(下划线命名)
  - migration downgrade() 必须能干净回滚
  - render_as_batch=True 在 env.py 已配(SQLite ALTER TABLE 限制)
  - DESC 索引用 sa.text("imported_at_ms DESC")

D3.3.3 教训应用:
  - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突 → 业务阻断)
  - OperationalError / DataError / InterfaceError **不**捕获,透传给 Adapter 走技术失败入口
  - 拒绝 D3.3.2 反范本(SQLAlchemyError 基类过宽,会掩盖真实生产问题)
  - 双层 except `(IntegrityError, _sqlcipher_dbapi.IntegrityError)`:
    SQLCipher dialect 不包装 dbapi 异常,实际抛 sqlcipher3.dbapi2.IntegrityError

D7 兼容 5 扩展点(沿 plan §7):
  - source TEXT NOT NULL(str 通用,无硬编码 'wechat')
  - schema 必含 candidate_match_id + needs_confirm(D6 全 NULL/False,D7 触发跨源)
  - dedup.py ORM 替换(text() → select(Transaction))
  - fingerprint.py + dedup.py 函数签名不动
  - merchants.py dict[str, Category](D6.3 沿用)
"""

from __future__ import annotations

import json
import time
from datetime import date
from decimal import Decimal
from typing import Any

import sqlcipher3.dbapi2 as _sqlcipher_dbapi  # D3.3.2 教训: 双层 except 防 SQLCipher dialect 不包装 dbapi 异常
from sqlalchemy import (
    Date,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from my_ai_employee.core.models import Base
from my_ai_employee.core.transaction_category import TransactionCategory
from my_ai_employee.core.transactions import (
    _TRANSACTION_STATUS_CHOICES,
    ALLOWED_TRANSITIONS,
    TransactionIllegalTransitionError,
    TransactionStatus,
    assert_transition,
)

# ===== 自定义异常(D6.4 契约 — L1 UNIQUE 冲突 → 业务阻断入口)=====


class TransactionDuplicateError(Exception):
    """L1 源内 UNIQUE(source, external_transaction_id) 冲突 → 业务阻断入口(D6.4)。

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


# ===== ORM 模型(D6.4 16 列 + UNIQUE 复合 + 2 INDEX)=====


class Transaction(Base):
    """transactions 表 ORM(D6.4 — 16 列 DDL + 3 层去重模型)。

    字段注解(0007_transactions.py migration 同步):
        - id:                    INTEGER PK AUTOINCREMENT
        - source:                TEXT NOT NULL                  # D6='wechat', D7='alipay'
        - external_transaction_id: TEXT NOT NULL                # 业务侧交易流水号
        - transaction_date:      DATE NOT NULL                   # 交易日期(指纹算法只取日期)
        - amount:                NUMERIC(10, 2) NOT NULL         # 防精度漂移(非 Float)
        - counterparty:          TEXT NOT NULL                   # 商家名(归一化前)
        - category:              TEXT NULL                       # TransactionCategory 5 选 1
        - payment_method:        TEXT NULL                       # 支付方式(微信零钱/银行卡/...)
        - normalized_fingerprint: TEXT NOT NULL                  # SHA-256 前 32 chars(INDEX)
        - needs_confirm:         INTEGER NOT NULL DEFAULT 0      # BOOLEAN 走 Integer
        - candidate_match_id:    INTEGER NULL                    # L3 软标记,D6 全 NULL
        - status:                TEXT NOT NULL DEFAULT 'imported'  # TransactionStatus 5 选 1
        - imported_at_ms:        INTEGER NOT NULL                # Unix epoch ms
        - confirmed_at_ms:       INTEGER NULL                    # 用户确认时间戳
        - raw_row_json:          TEXT NOT NULL                   # 原始行 JSON(追溯)
        - notes:                 TEXT NULL                       # 用户备注

    约束:
        - UNIQUE(source, external_transaction_id) — L1 硬约束
    索引:
        - idx_transactions_fingerprint(normalized_fingerprint) — L2 软标记
        - idx_transactions_status_imported(status, imported_at_ms DESC) — 状态机热路径

    D3.2 8 雷区严判:
        - Numeric(10, 2) 非 Float(D3.2 教训)
        - BOOLEAN 走 Integer + server_default="0"(SQLite 无 BOOLEAN 类型)
        - DATE 走 Date(非 DateTime,指纹算法只取日期)
        - AUTOINCREMENT(非 AUTO_INCREMENT)
        - 下划线命名(idx_transactions_fingerprint)
        - DESC 索引用 sa.text("imported_at_ms DESC")(D3.2.3 修复)

    D7 兼容 schema 必含:
        - candidate_match_id + needs_confirm 2 列(D6 全 NULL/False,D7 触发跨源候选时写入)
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    external_transaction_id: Mapped[str] = mapped_column(Text, nullable=False)
    # DATE 类型(SQLAlchemy Date,D3.2 雷区:非 DateTime,指纹算法只取日期)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Numeric(10, 2) 防精度漂移(D3.2 雷区:非 Float)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    counterparty: Mapped[str] = mapped_column(Text, nullable=False)
    # category:StrEnum 5 选 1 严判,DDL 走 TEXT(SQLite 无 ENUM)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 32 chars hex(SHA-256 前 32 字符,沿 D6.2 fingerprint 派生)
    normalized_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    # BOOLEAN 走 Integer + server_default="0"(D3.2 雷区)
    needs_confirm: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # D7 兼容:D6 全 NULL,D7 触发跨源候选时写入
    candidate_match_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # status:TransactionStatus 5 选 1,DDL 走 TEXT,DEFAULT 'imported'
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="imported", server_default="imported"
    )
    imported_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_at_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # raw_row_json:JSON 字符串(保留原始行供追溯)
    raw_row_json: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 约束 + 索引
    __table_args__ = (
        # L1 硬约束: UNIQUE(source, external_transaction_id)
        UniqueConstraint("source", "external_transaction_id", name="uq_transactions_source_ext_id"),
        # L2 软标记: normalized_fingerprint INDEX(非 UNIQUE,跨源可能重复)
        Index("idx_transactions_fingerprint", "normalized_fingerprint"),
        # 状态机热路径: status + imported_at_ms DESC
        Index("idx_transactions_status_imported", "status", text("imported_at_ms DESC")),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} source={self.source!r} "
            f"ext_id={self.external_transaction_id!r} amount={self.amount} "
            f"status={self.status!r}>"
        )


# ===== TransactionStore =====


class TransactionStore:
    """transactions 表读写封装(D6.4 业务层契约 — D6.5 Adapter 依赖此 Store)。

    Usage:
        store = TransactionStore(session_factory)
        # 入库(L1 严判:同源同 ID UNIQUE 冲突 → 业务阻断)
        tx = store.insert(
            source="wechat",
            external_transaction_id="4200000123456789",
            transaction_date=date(2026, 6, 14),
            amount=Decimal("13.14"),
            counterparty="星巴克",
            category="dining",
            payment_method="微信零钱",
            normalized_fingerprint="abc123...",
            raw_row_json='{"原始行": "..."}',
        )
        assert tx.id is not None
        assert tx.status == "imported"
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # ===== insert =====

    def insert(
        self,
        source: str,
        external_transaction_id: str,
        transaction_date: date,
        amount: Decimal,
        counterparty: str,
        normalized_fingerprint: str,
        raw_row_json: str,
        *,
        category: str | None = None,
        payment_method: str | None = None,
        needs_confirm: bool = False,
        candidate_match_id: int | None = None,
        status: str = "imported",
        imported_at_ms: int | None = None,
        confirmed_at_ms: int | None = None,
        notes: str | None = None,
    ) -> Transaction:
        """插入一条 transaction(D6.4 入库入口 — L1 UNIQUE 业务阻断)。

        Args:
            source: 业务源标识('wechat' / 'alipay' 等,D6.4 严判 ^[a-z0-9_-]{1,32}$)
            external_transaction_id: 业务侧交易流水号(1-128 字符,严判)
            transaction_date: 交易日期(必传 date,非 datetime)
            amount: 交易金额(Decimal 严判 2 位小数,防精度漂移)
            counterparty: 商家名(非空,strip() 后严判)
            normalized_fingerprint: 32 chars SHA-256 hex(L2 软标记用)
            raw_row_json: 原始行 JSON 字符串(必传,保留供追溯)
            category: TransactionCategory 5 选 1(None 表示待分类,D6.5 Adapter 调 categorizer())
            payment_method: 支付方式(可空)
            needs_confirm: L3 软标记(默认 False,D7 触发跨源时设 True)
            candidate_match_id: L3 候选 ID(D6 全 None)
            status: TransactionStatus 5 选 1(默认 'imported',D6.4 不允许传其他值)
            imported_at_ms: Unix epoch ms(默认 = 当前时间)
            confirmed_at_ms: 用户确认时间戳(可空)
            notes: 备注(可空)

        Returns:
            新插入的 Transaction(已 refresh,id/status/imported_at_ms 都可读)

        Raises:
            TransactionDuplicateError: UNIQUE(source, external_transaction_id) 冲突
                (L1 业务阻断入口)
            ValueError: 业务层严判失败(类型 / 范围 / 枚举值)
            sqlalchemy.exc.OperationalError / DataError / InterfaceError: 技术失败
                (透传给 Adapter 走 record_transaction_failure_and_emit)

        D3.3.3 教训应用:
            - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突)
            - OperationalError / DataError / InterfaceError **不**捕获
            - 拒绝 D3.3.2 反范本(SQLAlchemyError 基类过宽,会掩盖真实生产问题)
            - 双层 except `(IntegrityError, _sqlcipher_dbapi.IntegrityError)`:
              SQLCipher dialect 不包装 dbapi 异常
        """
        # 1. 业务层严判(沿 D4.7.3 v1.0.5/v1.0.6 范本: type 严判在 hash 前)
        source = self._validate_source(source)
        external_transaction_id = self._validate_external_tx_id(external_transaction_id)
        counterparty = self._validate_counterparty(counterparty)
        normalized_fingerprint = self._validate_fingerprint(normalized_fingerprint)
        raw_row_json = self._validate_raw_row_json(raw_row_json)
        if category is not None:
            category = self._validate_category(category)
        if payment_method is not None:
            payment_method = self._validate_payment_method(payment_method)
        status = self._normalize_status(status)
        # needs_confirm: BOOLEAN 走 Integer(0/1),严判 type() is bool(非 int)
        if type(needs_confirm) is not bool:
            raise TypeError(
                f"needs_confirm 必须是 bool(非 int),实际 type={type(needs_confirm).__name__}, "
                f"value={needs_confirm!r}"
            )
        needs_confirm_int = 1 if needs_confirm else 0
        if candidate_match_id is not None and (
            type(candidate_match_id) is bool
            or not isinstance(candidate_match_id, int)
            or candidate_match_id < 1
        ):
            raise ValueError(
                f"candidate_match_id 必须是正 int(非 bool),"
                f"实际 type={type(candidate_match_id).__name__}, value={candidate_match_id!r}"
            )
        if amount is None or not isinstance(amount, Decimal):
            raise TypeError(
                f"amount 必须是 Decimal,实际 type={type(amount).__name__}, value={amount!r}"
            )
        if isinstance(transaction_date, str) or not hasattr(transaction_date, "isoformat"):
            raise TypeError(
                f"transaction_date 必须是 date(非 str/datetime),"
                f"实际 type={type(transaction_date).__name__}, value={transaction_date!r}"
            )
        # 严判 imported_at_ms 必传 int(非 bool)>= 0
        if imported_at_ms is None:
            imported_at_ms = int(time.time() * 1000)
        else:
            if (
                type(imported_at_ms) is bool
                or not isinstance(imported_at_ms, int)
                or imported_at_ms < 0
            ):
                raise ValueError(
                    f"imported_at_ms 必须是原生 int(非 bool)>= 0,"
                    f"实际 type={type(imported_at_ms).__name__}, value={imported_at_ms!r}"
                )
        if confirmed_at_ms is not None and (
            type(confirmed_at_ms) is bool
            or not isinstance(confirmed_at_ms, int)
            or confirmed_at_ms < 0
        ):
            raise ValueError(
                f"confirmed_at_ms 必须是原生 int(非 bool)>= 0(允许 None),"
                f"实际 type={type(confirmed_at_ms).__name__}, value={confirmed_at_ms!r}"
            )

        # 2. 插入(D3.3.3 教训: 窄 except, 只接 IntegrityError)
        with self._session_factory() as session:
            try:
                row = Transaction(
                    source=source,
                    external_transaction_id=external_transaction_id,
                    transaction_date=transaction_date,
                    amount=amount,
                    counterparty=counterparty,
                    category=category,
                    payment_method=payment_method,
                    normalized_fingerprint=normalized_fingerprint,
                    needs_confirm=needs_confirm_int,
                    candidate_match_id=candidate_match_id,
                    status=status,
                    imported_at_ms=imported_at_ms,
                    confirmed_at_ms=confirmed_at_ms,
                    raw_row_json=raw_row_json,
                    notes=notes,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                return row
            except (IntegrityError, _sqlcipher_dbapi.IntegrityError) as err:
                session.rollback()
                # 业务阻断: UNIQUE(source, external_transaction_id) 冲突 → 业务阻断入口
                # D3.3.2 教训: SQLCipher dialect 实际抛 sqlcipher3.dbapi2.IntegrityError(原始 err),
                #              sqlalchemy.exc.IntegrityError 反而是包装层(可能无 .orig)
                # D3.3.3 教训: 范围窄化, 拒 SQLAlchemyError 基类(会掩盖 OperationalError 等)
                err_str = str(getattr(err, "orig", err))
                if (
                    "UNIQUE constraint failed: transactions.source" in err_str
                    or "UNIQUE constraint failed: transactions.source, transactions.external_transaction_id"
                    in err_str
                ):
                    raise TransactionDuplicateError(
                        source=source,
                        external_transaction_id=external_transaction_id,
                        original_error=err,
                    ) from err
                # 其他 IntegrityError(FK 约束 / CHECK 约束) 走技术失败
                raise

    # ===== 查询方法(热路径) =====

    def get_by_id(self, tx_id: int) -> Transaction | None:
        """按 transactions.id 查单条(走 PK 索引,O(1))。

        Args:
            tx_id: Transaction.id

        Returns:
            Transaction 或 None
        """
        if type(tx_id) is bool or not isinstance(tx_id, int) or tx_id < 1:
            raise ValueError(
                f"tx_id 必须是正 int(非 bool),实际 type={type(tx_id).__name__}, value={tx_id!r}"
            )
        with self._session_factory() as session:
            return session.get(Transaction, tx_id)

    def by_external_id(self, source: str, external_transaction_id: str) -> Transaction | None:
        """按 (source, external_transaction_id) 查单条(走 UNIQUE 索引,O(1))。

        用于 L1 预检(沿 D6.2 check_l1_duplicate 范本)。
        """
        source = self._validate_source(source)
        external_transaction_id = self._validate_external_tx_id(external_transaction_id)
        with self._session_factory() as session:
            stmt = select(Transaction).where(
                Transaction.source == source,
                Transaction.external_transaction_id == external_transaction_id,
            )
            return session.execute(stmt).scalar_one_or_none()

    def list_by_source(
        self,
        source: str,
        since: date | None = None,
        limit: int = 100,
    ) -> list[Transaction]:
        """按 source 查多条(可选 since 日期过滤,按 imported_at_ms DESC 排序)。

        Args:
            source: 业务源标识('wechat' / 'alipay' 等)
            since: 起始日期(含),None 表示不限
            limit: 返回上限,默认 100

        Returns:
            按 imported_at_ms DESC 排序的 Transaction 列表
        """
        source = self._validate_source(source)
        if since is not None and (isinstance(since, str) or not hasattr(since, "isoformat")):
            raise TypeError(
                f"since 必须是 date(非 str),实际 type={type(since).__name__}, value={since!r}"
            )
        if type(limit) is bool or not isinstance(limit, int) or limit < 1 or limit > 10000:
            raise ValueError(
                f"limit 必须是 [1, 10000] 的 int(非 bool),"
                f"实际 type={type(limit).__name__}, value={limit!r}"
            )
        with self._session_factory() as session:
            stmt = select(Transaction).where(Transaction.source == source)
            if since is not None:
                stmt = stmt.where(Transaction.transaction_date >= since)
            stmt = stmt.order_by(Transaction.imported_at_ms.desc()).limit(limit)
            return list(session.execute(stmt).scalars().all())

    def find_candidates_by_fingerprint(
        self,
        fingerprint: str,
        *,
        exclude_tx_id: int | None = None,
        source_filter: str | None = None,
        limit: int = 5,
    ) -> list[Transaction]:
        """L2 跨源 normalized_fingerprint 候选查询(软标记,无 UNIQUE)。

        Args:
            fingerprint: 32 chars SHA-256 hex(由 normalize_fingerprint 派生)
            exclude_tx_id: 排除的 transactions.id(写入时排除自身,防自命中)
            source_filter: 限定 source(默认查所有 source 跨源候选;可指定 'wechat' 单源)
            limit: 最多返回候选数(默认 5,防止超多候选淹没调用方)

        Returns:
            候选 Transaction 列表(>= 0)
            按 id ASC 排序(选最小 ID 作为 candidate_match_id)
        """
        fingerprint = self._validate_fingerprint(fingerprint)
        if exclude_tx_id is not None and (
            type(exclude_tx_id) is bool or not isinstance(exclude_tx_id, int) or exclude_tx_id < 1
        ):
            raise ValueError(
                f"exclude_tx_id 必须是正 int(非 bool)(允许 None),"
                f"实际 type={type(exclude_tx_id).__name__}, value={exclude_tx_id!r}"
            )
        if source_filter is not None:
            source_filter = self._validate_source(source_filter)
        if type(limit) is bool or not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError(
                f"limit 必须是 [1, 100] 的 int(非 bool),"
                f"实际 type={type(limit).__name__}, value={limit!r}"
            )
        with self._session_factory() as session:
            stmt = select(Transaction).where(Transaction.normalized_fingerprint == fingerprint)
            if source_filter is not None:
                stmt = stmt.where(Transaction.source == source_filter)
            if exclude_tx_id is not None:
                stmt = stmt.where(Transaction.id != exclude_tx_id)
            stmt = stmt.order_by(Transaction.id.asc()).limit(limit)
            return list(session.execute(stmt).scalars().all())

    # ===== 状态机更新(D6.3 状态机 + D6.4 落库)=====

    def update_status(
        self,
        tx_id: int,
        new_status: str | TransactionStatus,
        *,
        from_status: str | TransactionStatus,
        confirmed_at_ms: int | None = None,
    ) -> Transaction:
        """更新 transactions.status(D6.4 状态机更新入口 — 5 状态 × 白名单严判)。

        Args:
            tx_id: Transaction.id
            new_status: 目标 status(TransactionStatus 5 选 1)
            from_status: 调用方预期的当前 status(必传关键字,严判一致性)
                         防 concurrent 写导致状态机漂移(行已被其他调用方推到其他状态)
            confirmed_at_ms: 用户确认时间戳(Unix epoch ms)
                写入规则:
                - new_status == CONFIRMED:必传 int(非 None),表示"此时刻被显式确认过"
                - new_status != CONFIRMED:必传 None,row.confirmed_at_ms 保留原值(不动)

        Returns:
            更新后的 Transaction(已 refresh)

        Raises:
            TransactionIllegalTransitionError: 状态漂移(from_status != row.status)
                                               或 白名单外转换
            ValueError: new_status / from_status 非法枚举值 / tx_id 不存在
                       或 confirmed_at_ms 必传规则违反(CONFIRMED 未传 / 非 CONFIRMED 误传)
            TypeError: 类型非法

        状态机白名单(ALLOWED_TRANSITIONS,沿 D6.3):
            IMPORTED      → {CATEGORIZED, NEEDS_CONFIRM, ARCHIVED}
            CATEGORIZED   → {NEEDS_CONFIRM, CONFIRMED, ARCHIVED}
            NEEDS_CONFIRM → {CONFIRMED, ARCHIVED}
            CONFIRMED     → {ARCHIVED}
            ARCHIVED      → {}    (终态)
        """
        # 1. 严判 tx_id
        if type(tx_id) is bool or not isinstance(tx_id, int) or tx_id < 1:
            raise ValueError(
                f"tx_id 必须是正 int(非 bool),实际 type={type(tx_id).__name__}, value={tx_id!r}"
            )
        new_status_value = self._normalize_status(new_status)
        from_status_value = self._normalize_status(from_status)
        # 2. 严判 confirmed_at_ms 必传规则(在 row 存在前做,失败更快)
        if new_status_value == TransactionStatus.CONFIRMED.value:
            if confirmed_at_ms is None:
                raise ValueError(
                    f"D6.4 状态机:update_status(new_status=CONFIRMED) 必传 "
                    f"confirmed_at_ms(Unix epoch ms),实际 {confirmed_at_ms!r}"
                )
            if (
                type(confirmed_at_ms) is bool
                or not isinstance(confirmed_at_ms, int)
                or confirmed_at_ms < 0
            ):
                raise ValueError(
                    f"D6.4 状态机:confirmed_at_ms 必须是原生 int(非 bool)>= 0,"
                    f"实际 type={type(confirmed_at_ms).__name__}, value={confirmed_at_ms!r}"
                )
        else:
            if confirmed_at_ms is not None:
                raise ValueError(
                    f"D6.4 状态机:update_status(new_status={new_status_value!r}) "
                    f"时 confirmed_at_ms 必传 None(保留原确认时间戳),"
                    f"实际 {confirmed_at_ms!r}"
                )

        with self._session_factory() as session:
            row = session.get(Transaction, tx_id)
            if row is None:
                raise ValueError(f"tx_id={tx_id} 不存在,无法 update_status 为 {new_status_value!r}")
            # 3. 状态漂移检测(concurrent write 防护,沿 D5.2 范本)
            if row.status != from_status_value:
                raise TransactionIllegalTransitionError(
                    tx_id=tx_id,
                    from_status=from_status_value,
                    to_status=new_status_value,
                    actual_status=row.status,
                )
            # 4. 白名单外转换严判(调 D6.3 assert_transition 公共 API)
            try:
                assert_transition(from_status_value, new_status_value)
            except TransactionIllegalTransitionError:
                # 重新抛,带 tx_id 上下文
                from_enum = TransactionStatus(from_status_value)
                allowed = ALLOWED_TRANSITIONS[from_enum]
                raise TransactionIllegalTransitionError(
                    tx_id=tx_id,
                    from_status=from_status_value,
                    to_status=new_status_value,
                    allowed=allowed,
                ) from None
            row.status = new_status_value
            # 5. 写入确认时间戳:仅在 CONFIRMED 时写入
            if new_status_value == TransactionStatus.CONFIRMED.value:
                assert confirmed_at_ms is not None  # noqa: S101
                row.confirmed_at_ms = confirmed_at_ms
            session.commit()
            session.refresh(row)
            return row

    # ===== 私有 helper(沿 D4.7.3 v1.0.5 P2-1 范本: type 严判在 hash 前)====-

    @staticmethod
    def _validate_source(source: Any) -> str:
        """严判 source(防非 str / 非法字符,沿 D6.2 _validate_source 范本)。"""
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"source 必填且必须非空字符串,实际 {source!r}")
        import re

        if not re.match(r"^[a-z0-9_-]{1,32}$", source):
            raise ValueError(
                f"source 必须匹配 ^[a-z0-9_-]{{1,32}}$,实际 {source!r}"
                f"(D6='wechat' / D7='alipay' 之类小写 snake_case)"
            )
        return source

    @staticmethod
    def _validate_external_tx_id(external_transaction_id: Any) -> str:
        """严判 external_transaction_id(1-128 字符,strip() 后非空,沿 D6.2 范本)。"""
        if not isinstance(external_transaction_id, str) or not external_transaction_id.strip():
            raise ValueError(
                f"external_transaction_id 必填且必须非空字符串,实际 {external_transaction_id!r}"
            )
        s = external_transaction_id.strip()
        if not (1 <= len(s) <= 128):
            raise ValueError(
                f"external_transaction_id 长度必须在 [1, 128],实际 len={len(s)}, value={s!r}"
            )
        return s

    @staticmethod
    def _validate_counterparty(counterparty: Any) -> str:
        """严判 counterparty(非空 strip() 后非空)。"""
        if not isinstance(counterparty, str) or not counterparty.strip():
            raise ValueError(f"counterparty 必填且必须非空字符串,实际 {counterparty!r}")
        return counterparty.strip()

    @staticmethod
    def _validate_fingerprint(fingerprint: Any) -> str:
        """严判 fingerprint(32 chars 小写 hex,沿 D6.2 范本)。"""
        if not isinstance(fingerprint, str) or len(fingerprint) != 32:
            raise ValueError(
                f"fingerprint 必须是 32 chars hex,实际 len={len(fingerprint) if isinstance(fingerprint, str) else 'N/A'}"
            )
        if not all(c in "0123456789abcdef" for c in fingerprint):
            raise ValueError(f"fingerprint 必须全是小写 hex,实际 {fingerprint!r}")
        return fingerprint

    @staticmethod
    def _validate_raw_row_json(raw_row_json: Any) -> str:
        """严判 raw_row_json(必传非空字符串,且为合法 JSON)。"""
        if not isinstance(raw_row_json, str) or not raw_row_json.strip():
            raise ValueError(f"raw_row_json 必填且必须非空字符串,实际 {raw_row_json!r}")
        try:
            json.loads(raw_row_json)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(
                f"raw_row_json 必须是合法 JSON 字符串,实际 {raw_row_json!r} (err={e})"
            ) from e
        return raw_row_json

    @staticmethod
    def _validate_category(category: Any) -> str:
        """严判 category(TransactionCategory 5 选 1 的 value)。"""
        if not isinstance(category, str):
            raise TypeError(
                f"category 必须是 str(TransactionCategory 5 选 1 的 value),"
                f"实际 type={type(category).__name__}, value={category!r}"
            )
        valid_values = {c.value for c in TransactionCategory}
        if category not in valid_values:
            raise ValueError(
                f"category 必须是 TransactionCategory 5 选 1 {valid_values!r},实际 {category!r}"
            )
        return category

    @staticmethod
    def _validate_payment_method(payment_method: Any) -> str:
        """严判 payment_method(非空 strip() 后非空)。"""
        if not isinstance(payment_method, str) or not payment_method.strip():
            raise ValueError(f"payment_method 必填且必须非空字符串,实际 {payment_method!r}")
        return payment_method.strip()

    @staticmethod
    def _normalize_status(value: Any) -> str:
        """严判 status 字符串(防 list/dict/set 触发 TypeError,沿 D4.7.3 v1.0.5 P2-1 范本)。"""
        if type(value) is not str:
            raise TypeError(
                f"status 必须是 str 或 TransactionStatus 枚举,实际 {type(value).__name__}={value!r}"
            )
        if value not in _TRANSACTION_STATUS_CHOICES:
            raise ValueError(
                f"status 必须是 TransactionStatus 5 选 1 {_TRANSACTION_STATUS_CHOICES!r},"
                f"实际 {value!r}"
            )
        return value


__all__ = [
    "Transaction",
    "TransactionStore",
    "TransactionDuplicateError",
]
