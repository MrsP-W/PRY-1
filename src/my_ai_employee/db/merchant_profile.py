"""v0.2 D8.1 — merchant_profile 表 ORM + Store(8 字段 + 3 公共方法).

承接 v0.1.0 post-tag 阶段 + v0.2 D8 智能财务异常检测启动。
8 字段 schema(沿 D3.2 8 雷区严判 + D6.4 Transaction ORM 同构):

    1. id                    INTEGER PK AUTOINCREMENT
    2. counterparty          TEXT NOT NULL UNIQUE           # 商家名(L1 硬约束)
    3. avg_amount            NUMERIC(10, 2) NOT NULL         # 历史平均消费(Decimal 2 位精度)
    4. amount_std            NUMERIC(10, 2) NOT NULL         # 历史金额 σ(Decimal 2 位精度)
    5. category_distribution TEXT NOT NULL                   # JSON: {category: count}
    6. tx_count              INTEGER NOT NULL                # 历史笔数
    7. last_seen_ms          INTEGER NOT NULL                # 最后一次出现时间戳
    8. updated_at_ms         INTEGER NOT NULL                # 画像更新时间戳

D3.2 8 雷区严判(全部应用):
    1. Numeric(10, 2) 非 Float — avg_amount / amount_std 走 Numeric
    2. BOOLEAN 走 Integer + server_default="0/1" — N/A(本表无 BOOLEAN)
    3. DATE 走 Date — N/A(本表用 ms INTEGER)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)
    5. 文件名 0011_merchant_profile.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配
    8. DESC 索引用 sa.text("last_seen_ms DESC")(D3.2.3 修复)

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突)
    - OperationalError / DataError / InterfaceError **不**捕获,透传给 D8.2 Detector
    - 双层 except (IntegrityError, _sqlcipher_dbapi.IntegrityError): 沿 B4.1 范本

D4.7.3 教训应用:
    - type 严判在 hash 操作前
    - 公共 API 入口严判 + 数据类 __post_init__ 双层防御
    - ms 字段严判 type() is bool,拒 int 子类陷阱

D8 业务规则(v0.2 启动规划):
    - MIN_HISTORY_FOR_PROFILE = 5(冷启动阈值,< 5 笔返回 None 不入库)
    - upsert 范本兼容已有数据,不动旧表
    - 商家画像由 D8.2 AnomalyDetector 调 compute_profile() 计算
    - get_profile() hot-path 查询,异常检测热路径

设计权衡:
    - 不新建 merchant_profile 集成到 TransactionStore(避免 Store 类膨胀)
    - 独立 MerchantProfileStore + 注入 TransactionStore(避免循环 import)
    - D8.2 AnomalyDetector 注入 TransactionStore + MerchantProfileStore 两个依赖
"""

from __future__ import annotations

import json
import time
from collections import Counter
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlcipher3.dbapi2 as _sqlcipher_dbapi  # D3.3.2 教训: 双层 except 防 SQLCipher dialect 不包装
from sqlalchemy import (
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

if TYPE_CHECKING:
    from my_ai_employee.db.transactions import TransactionStore

# ===== 自定义异常(D8.1 契约 — L1 UNIQUE 冲突 → 业务阻断入口)=====


class MerchantProfileDuplicateError(Exception):
    """L1 UNIQUE(counterparty) 冲突 → 业务阻断入口(v0.2 D8.1).

    Attributes:
        counterparty: 重复的商家名
        original_error: SQLAlchemy IntegrityError / SQLCipher dbapi2.IntegrityError
    """

    def __init__(
        self,
        message: str,
        *,
        counterparty: str,
        original_error: Any = None,
    ) -> None:
        super().__init__(message)
        self.counterparty = counterparty
        self.original_error = original_error


# ===== MerchantProfile ORM(8 字段)=====


class MerchantProfile(Base):
    """商家画像主表(mirror 0011 alembic migration)。

    字段注解:
        - id:                    INTEGER PK AUTOINCREMENT
        - counterparty:          TEXT NOT NULL UNIQUE           # 商家名(L1 硬约束)
        - avg_amount:            NUMERIC(10, 2) NOT NULL         # 历史平均消费
        - amount_std:            NUMERIC(10, 2) NOT NULL         # 历史金额 σ
        - category_distribution: TEXT NOT NULL                   # JSON: {category: count}
        - tx_count:              INTEGER NOT NULL                # 历史笔数
        - last_seen_ms:          INTEGER NOT NULL                # 最后一次出现时间戳
        - updated_at_ms:         INTEGER NOT NULL                # 画像更新时间戳

    约束:
        - UNIQUE(counterparty) — L1 硬约束(防同一商家重复画像)

    索引:
        - idx_merchant_profile_last_seen(last_seen_ms DESC) — 最近活跃商家热路径
    """

    __tablename__ = "merchant_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    counterparty: Mapped[str] = mapped_column(Text, nullable=False)
    # Numeric(10, 2) 防精度漂移(D3.2 雷区)
    avg_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount_std: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    category_distribution: Mapped[str] = mapped_column(Text, nullable=False)
    tx_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_seen_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # 约束 + 索引(D3.2 雷区 #8: DESC 索引用 sa.text 包裹)
    __table_args__ = (
        UniqueConstraint("counterparty", name="uq_merchant_profile_counterparty"),
        Index("idx_merchant_profile_last_seen", text("last_seen_ms DESC")),
    )

    def __repr__(self) -> str:
        return (
            f"<MerchantProfile id={self.id} counterparty={self.counterparty!r} "
            f"avg_amount={self.avg_amount} amount_std={self.amount_std} "
            f"tx_count={self.tx_count}>"
        )


# ===== MerchantProfileStore(沿 D9.1 NoteStore 范本 + B4.1 blacklist 范本)=====


class MerchantProfileStore:
    """商家画像读写封装(8 字段 + L1 UNIQUE 业务阻断).

    设计(沿 NoteStore 范本 + D3.2 8 雷区严判):
        - upsert_profile(): 计算新画像后 L1 UNIQUE 命中 → upsert 兼容
                            (insert + IntegrityError fallback update,沿 D6.4 范本)
        - get_profile(): hot-path 查询(异常检测热路径)
        - compute_profile(): 从历史交易算商家画像(冷启动 < 5 笔 → 返回 None)
        - 严判只放在 Store 层(契约层接受已校验参数)

    业务规则(D8.1):
        - MIN_HISTORY_FOR_PROFILE = 5(冷启动阈值,< 5 笔返回 None)
        - counterparty 必填非空白 + ≤ 128 字符(沿 transactions 同款)
        - avg_amount / amount_std 严判 >= 0(σ >= 0 数学约束)
        - tx_count 严判 >= 0
        - ms 字段严判 type() is bool,拒 int 子类陷阱

    D3.3.3 教训应用:
        - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突 → MerchantProfileDuplicateError)
        - OperationalError / DataError / InterfaceError **不**捕获,透传给 D8.2 Detector
    """

    MIN_HISTORY_FOR_PROFILE: int = 5  # 冷启动阈值(< 5 笔不画像)

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        transaction_store: TransactionStore,
    ) -> None:
        """初始化。

        Args:
            session_factory: SQLAlchemy sessionmaker(Session 范本)
            transaction_store: TransactionStore 实例(注入依赖,避免循环 import)

        Raises:
            TypeError: session_factory 非 sessionmaker 或 transaction_store 缺失
        """
        if session_factory is None or not callable(session_factory):
            raise TypeError(
                f"session_factory 必须是 sessionmaker(callable),"
                f"实际 type={type(session_factory).__name__}"
            )
        if transaction_store is None:
            raise TypeError("transaction_store 必传非 None(注入依赖)")
        self._sf = session_factory
        self._tx_store = transaction_store

    # ===== 严判 helper(沿 B4.1 blacklist 范本)=====

    @staticmethod
    def _validate_counterparty(counterparty: str) -> str:
        """严判 counterparty(必填非空白 + ≤ 128 字符).

        Raises:
            TypeError: 非 str
            ValueError: 空字符串 / 纯空白 / 超长
        """
        if not isinstance(counterparty, str):
            raise TypeError(
                f"counterparty 必须是 str,实际 type={type(counterparty).__name__},"
                f" value={counterparty!r}"
            )
        stripped = counterparty.strip()
        if not stripped:
            raise ValueError("counterparty 必非空(经 strip())")
        if len(stripped) > 128:
            raise ValueError(f"counterparty 长度超 128(实际 {len(stripped)})")
        return stripped

    @staticmethod
    def _validate_amount(amount: Decimal, field_name: str) -> Decimal:
        """严判金额字段(Decimal 2 位精度,>= 0).

        Raises:
            TypeError: 非 Decimal
            ValueError: < 0 / 超过 2 位小数
        """
        if not isinstance(amount, Decimal):
            raise TypeError(
                f"{field_name} 必须是 Decimal,实际 type={type(amount).__name__}, value={amount!r}"
            )
        if amount < 0:
            raise ValueError(f"{field_name} 必须 >= 0(实际 {amount})")
        # 2 位小数精度(D3.2 Numeric(10, 2) 锁)
        exponent: int = amount.as_tuple().exponent  # type: ignore[assignment]
        if exponent < -2:
            raise ValueError(f"{field_name} 小数位超 2(实际 {amount})")
        return amount

    @staticmethod
    def _validate_tx_count(tx_count: int) -> int:
        """严判 tx_count(int 拒 bool,>= 0).

        D4.7.3 v1.0.4 P2-2 范本: type() is bool 检查在 isinstance 之前.
        """
        if type(tx_count) is bool or not isinstance(tx_count, int) or tx_count < 0:
            raise ValueError(
                f"tx_count 必须是原生 int(非 bool) >= 0, "
                f"实际 type={type(tx_count).__name__}, value={tx_count!r}"
            )
        return tx_count

    @staticmethod
    def _validate_ms(ms: int, field_name: str) -> int:
        """严判 ms 字段(int 拒 bool,>= 0).

        D4.7.3 v1.0.4 P2-2 范本: type() is bool 检查在 isinstance 之前.
        """
        if type(ms) is bool or not isinstance(ms, int) or ms < 0:
            raise ValueError(
                f"{field_name} 必须是原生 int(非 bool) >= 0, "
                f"实际 type={type(ms).__name__}, value={ms!r}"
            )
        return ms

    @staticmethod
    def _validate_category_distribution(dist_json: str) -> str:
        """严判 category_distribution(JSON 字符串,≤ 2000 字符).

        Raises:
            TypeError: 非 str
            ValueError: JSON 解析失败 / 超长 / 非 dict
        """
        if not isinstance(dist_json, str):
            raise TypeError(
                f"category_distribution 必须是 str,实际 type={type(dist_json).__name__}"
            )
        if len(dist_json) > 2000:
            raise ValueError(f"category_distribution 长度超 2000(实际 {len(dist_json)})")
        try:
            parsed = json.loads(dist_json)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"category_distribution 必须是合法 JSON 字符串,实际 {dist_json!r}"
            ) from e
        if not isinstance(parsed, dict):
            raise ValueError(
                f"category_distribution JSON 解析后必须是 dict,实际 type={type(parsed).__name__}"
            )
        return dist_json

    # ===== 公开 API =====

    def compute_profile(self, counterparty: str) -> dict[str, Any] | None:
        """从历史交易算商家画像(冷启动 < 5 笔 → 返回 None).

        沿 TransactionStore.list_by_counterparty 同款日期过滤;
        冷启动不画像直接返回 None,D8.2 Detector 走 new_merchant 标记路径。

        Args:
            counterparty: 商家名(归一化前)

        Returns:
            画像 dict {counterparty, avg_amount, amount_std, category_distribution,
            tx_count, last_seen_ms} 或 None(冷启动)

        Raises:
            TypeError: counterparty 非 str
            ValueError: counterparty 空字符串
        """
        counterparty_stripped = self._validate_counterparty(counterparty)
        # 多取 50 笔(冷启动阈值 5 + 余量)
        history = self._tx_store.list_by_counterparty(
            counterparty_stripped, limit=self.MIN_HISTORY_FOR_PROFILE + 50
        )
        if len(history) < self.MIN_HISTORY_FOR_PROFILE:
            return None
        # 计算 avg_amount / amount_std(Decimal 精度,沿 D8.2 范本)
        amounts = [h.amount for h in history if h.amount > 0]
        if not amounts:
            return None
        avg = sum(amounts, Decimal("0")) / Decimal(len(amounts))
        # σ = sqrt(Σ(amount - avg)^2 / n) — 标准差公式
        std = (sum((a - avg) ** 2 for a in amounts) / Decimal(len(amounts))) ** Decimal("0.5")
        # 类别分布(沿 D8 docs 评估决策 #3 硬编码)
        category_dist = dict(Counter(h.category or "未分类" for h in history))
        last_seen = max(h.imported_at_ms for h in history)
        return {
            "counterparty": counterparty_stripped,
            "avg_amount": avg,
            "amount_std": std,
            "category_distribution": json.dumps(category_dist, ensure_ascii=True),
            "tx_count": len(history),
            "last_seen_ms": last_seen,
        }

    def upsert_profile(self, profile: dict[str, Any]) -> None:
        """upsert 商家画像(insert + IntegrityError fallback update,沿 B4.1 范本).

        沿 D8.1 决策:商家画像 schema 变化破坏旧数据风险 🟢 低,alembic 0011 新建表
        不动旧表;upsert 范本兼容已有数据。

        Args:
            profile: 画像 dict(必含 6 字段: counterparty / avg_amount / amount_std
                     / category_distribution / tx_count / last_seen_ms)
                     注: updated_at_ms 自动取当前时间

        Raises:
            TypeError: profile 非 dict
            KeyError: profile 缺必填字段
            ValueError: 字段严判失败
            MerchantProfileDuplicateError: 业务阻断(理论上 upsert 不应触发,留兜底)
            sqlalchemy.exc.OperationalError / DataError / InterfaceError: 技术失败
        """
        if not isinstance(profile, dict):
            raise TypeError(f"profile 必须是 dict,实际 type={type(profile).__name__}")
        # 字段严判
        counterparty = self._validate_counterparty(profile["counterparty"])
        avg_amount = self._validate_amount(profile["avg_amount"], "avg_amount")
        amount_std = self._validate_amount(profile["amount_std"], "amount_std")
        category_distribution = self._validate_category_distribution(
            profile["category_distribution"]
        )
        tx_count = self._validate_tx_count(profile["tx_count"])
        last_seen_ms = self._validate_ms(profile["last_seen_ms"], "last_seen_ms")
        now_ms = int(time.time() * 1000)
        updated_at_ms = self._validate_ms(now_ms, "updated_at_ms")

        # upsert 范本: 先查再决定 insert / update(避免 IntegrityError 路径)
        # 沿 D6.4 范本 + B4.1 blacklist 范本
        with self._sf() as session:
            existing = session.execute(
                select(MerchantProfile).where(MerchantProfile.counterparty == counterparty)
            ).scalar_one_or_none()
            if existing is None:
                try:
                    session.add(
                        MerchantProfile(
                            counterparty=counterparty,
                            avg_amount=avg_amount,
                            amount_std=amount_std,
                            category_distribution=category_distribution,
                            tx_count=tx_count,
                            last_seen_ms=last_seen_ms,
                            updated_at_ms=updated_at_ms,
                        )
                    )
                    session.commit()
                except IntegrityError as e:
                    raise MerchantProfileDuplicateError(
                        f"UNIQUE(counterparty={counterparty!r}) 冲突",
                        counterparty=counterparty,
                        original_error=e,
                    ) from e
                except _sqlcipher_dbapi.IntegrityError as e:
                    raise MerchantProfileDuplicateError(
                        f"UNIQUE(counterparty={counterparty!r}) 冲突",
                        counterparty=counterparty,
                        original_error=e,
                    ) from e
            else:
                # update 已有画像
                existing.avg_amount = avg_amount
                existing.amount_std = amount_std
                existing.category_distribution = category_distribution
                existing.tx_count = tx_count
                existing.last_seen_ms = last_seen_ms
                existing.updated_at_ms = updated_at_ms
                session.commit()

    def get_profile(self, counterparty: str) -> MerchantProfile | None:
        """按 counterparty 查询(L1 业务阻断入口的反向查询 + D8.2 hot-path).

        Args:
            counterparty: 商家名

        Returns:
            MerchantProfile 或 None(未画像)

        Raises:
            TypeError: counterparty 非 str
            ValueError: counterparty 空字符串
        """
        counterparty_stripped = self._validate_counterparty(counterparty)
        with self._sf() as session:
            stmt = select(MerchantProfile).where(
                MerchantProfile.counterparty == counterparty_stripped
            )
            return session.execute(stmt).scalar_one_or_none()


__all__ = [
    "MerchantProfile",
    "MerchantProfileStore",
    "MerchantProfileDuplicateError",
]
