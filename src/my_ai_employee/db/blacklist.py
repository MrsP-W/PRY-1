"""v0.2 B4.1 — RecipientBlacklist: 黑名单配置表 + Store(6 字段 + 6 公共方法).

承接 v0.1.0 post-tag 阶段 + 沿 D9.1 NoteStore 范本。
6 字段 schema(用户决策 2026-06-16 锁定"配置表 + 软删除"):

    1. id                INTEGER PK AUTOINCREMENT
    2. recipient_email   TEXT NOT NULL UNIQUE        # 收件人邮箱(L1 硬约束)
    3. reason            TEXT NOT NULL DEFAULT ''     # 拉黑原因(管理员备注,允许空)
    4. added_by          TEXT NOT NULL DEFAULT 'manual'  # 来源(manual / auto_spam / auto_bounce)
    5. added_at_ms       INTEGER NOT NULL             # 入库时间(Unix epoch ms)
    6. is_active         INTEGER NOT NULL DEFAULT 1   # 0/1 BOOLEAN 走 Integer(SQLite 无 BOOLEAN)

D3.2 8 雷区严判(全部应用):
    1. Numeric(10, 2) 非 Float — N/A(本表无金额字段)
    2. BOOLEAN 走 Integer + server_default="0/1"
    3. DATE 走 Date — N/A(本表用 ms INTEGER)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)
    5. 文件名 0010_recipient_blacklist.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配
    8. DESC 索引用 sa.text("added_at_ms DESC")

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突 → RecipientBlacklistDuplicateError)
    - OperationalError / DataError / InterfaceError **不**捕获,透传给 B4.2 Adapter

D4.7.3 教训应用:
    - P1-1 跨字段校验: added_by 必 3 选 1 枚举
    - P1-2 双向强一致: is_active INTEGER 0/1 DDL 严判,BOOLEAN 走 Integer 是 SQLite 唯一可行方案
    - P2-1 type 严判: is_active bool 入参严判 type() is bool(非 int 子类陷阱)
    - P2-2 异常范围窄化(D3.3.3): RecipientBlacklistStore.insert 拒绝 SQLAlchemyError 基类

v0.2 B4 决策应用:
    - is_active 软删除字段:deactivate() 走 is_active=0 而非物理删除(沿业务实践:
      误拉黑需要审计,UNIQUE 冲突时业务阻断 → 已存在 entry 必查到)
    - reason 字段允许空字符串(管理员没填备注时 'manual' 默认入库)
    - added_by 3 类白名单 'manual' / 'auto_spam' / 'auto_bounce'(预留自动拉黑扩展)

B4.1 范围边界(用户决策 2026-06-16):
    - 本轮不动 OutboxAdapter 集成(在 B4.2)
    - 本轮不动 SMTP 发送路径(在 B4.3)
    - 本轮不动 launchd 重启(6/23)
    - Store 层只暴露 is_blocked() hot-path 查询,B4.2 Adapter 直接调
"""

from __future__ import annotations

import time
from typing import Any

import sqlcipher3.dbapi2 as _sqlcipher_dbapi  # D3.3.2 教训: 双层 except 防 SQLCipher dialect 不包装 dbapi 异常
from sqlalchemy import (
    Index,
    Integer,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from my_ai_employee.core.models import Base

# ===== 自定义异常(B4.1 契约 — L1 UNIQUE 冲突 → 业务阻断入口)=====


class RecipientBlacklistDuplicateError(Exception):
    """L1 UNIQUE(recipient_email) 冲突 → 业务阻断入口(v0.2 B4.1).

    Adapter 层(OutboxAdapter B4.2)接住此异常,转写
    record_outbox_business_blocked_and_emit,走业务阻断入口(reason="blacklisted_recipient"
    白名单已预留,见 policy/outbox_adapter.py:56-61)。

    Attributes:
        recipient_email: 重复的邮箱
        original_error: SQLAlchemy IntegrityError / SQLCipher dbapi2.IntegrityError
    """

    def __init__(
        self,
        message: str,
        *,
        recipient_email: str,
        original_error: Any = None,
    ) -> None:
        super().__init__(message)
        self.recipient_email = recipient_email
        self.original_error = original_error


# ===== 严判常量(B4.1 契约 — added_by 3 类白名单)=====

_ADDED_BY_CHOICES: frozenset[str] = frozenset({"manual", "auto_spam", "auto_bounce"})

_EMAIL_MAX_LEN = 254  # RFC 5321 邮箱总长度上限(含 local + @ + domain)

# ===== RecipientBlacklist ORM(6 字段)=====


class RecipientBlacklist(Base):
    """收件人黑名单主表(mirror 0010 alembic migration)。

    字段注解:
        - id:              INTEGER PK AUTOINCREMENT
        - recipient_email: TEXT NOT NULL UNIQUE
        - reason:          TEXT NOT NULL DEFAULT ''
        - added_by:        TEXT NOT NULL DEFAULT 'manual'
        - added_at_ms:     INTEGER NOT NULL
        - is_active:       INTEGER NOT NULL DEFAULT 1

    约束:
        - UNIQUE(recipient_email)

    索引:
        - idx_recipient_blacklist_active(added_at_ms DESC) — 拉黑时间倒序
    """

    __tablename__ = "recipient_blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipient_email: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    added_by: Mapped[str] = mapped_column(
        Text, nullable=False, default="manual", server_default="manual"
    )
    added_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # 约束 + 索引(D3.2 雷区 #8: DESC 索引用 sa.text 包裹)
    __table_args__ = (
        UniqueConstraint("recipient_email", name="uq_recipient_blacklist_email"),
        Index("idx_recipient_blacklist_active", text("added_at_ms DESC")),
    )

    def __repr__(self) -> str:
        return (
            f"<RecipientBlacklist id={self.id} recipient_email={self.recipient_email!r} "
            f"added_by={self.added_by!r} is_active={self.is_active}>"
        )


# ===== RecipientBlacklistStore(沿 D9.1 NoteStore 范本)=====


class RecipientBlacklistStore:
    """收件人黑名单读写封装(6 字段 + L1 UNIQUE 业务阻断).

    设计(沿 NoteStore 范本 + D3.2 8 雷区严判):
        - insert(): L1 UNIQUE 命中 → RecipientBlacklistDuplicateError(业务阻断)
                   严判 type/value/范围/枚举(BOOLEAN 走 Integer / added_by 3 选 1)
        - get_by_id / find_by_email / is_blocked / list_all: 4 类热路径查询
        - deactivate(): 软删除(is_active=0,审计可追溯)
        - 严判只放在 Store 层(契约层接受已校验参数,不再二次严判)

    业务规则(B4.1):
        - is_active 走 Integer(0/1),严判 type() is bool(非 int)
        - added_by 必 3 选 1 枚举: 'manual' / 'auto_spam' / 'auto_bounce'
        - recipient_email 必填非空白 + 含 '@' + ≤ 254 字符
        - reason 允许空字符串(管理员未填备注)
        - added_at_ms 必传 int(非 bool)>= 0

    D3.3.3 教训应用:
        - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突 → RecipientBlacklistDuplicateError)
        - OperationalError / DataError / InterfaceError **不**捕获,透传给 B4.2 Adapter
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """初始化。

        Args:
            session_factory: SQLAlchemy sessionmaker(Session 范本)
        """
        if session_factory is None or not callable(session_factory):
            raise TypeError(
                f"session_factory 必须是 sessionmaker(callable),"
                f"实际 type={type(session_factory).__name__}"
            )
        self._sf = session_factory

    # ===== 严判 helper(双层防御:工厂层 + 数据类 `__post_init__`)=====

    @staticmethod
    def _validate_recipient_email(recipient_email: str) -> str:
        """严判 recipient_email(必填 + 含 @ + ≤ 254 字符).

        Raises:
            TypeError: 非 str
            ValueError: 空字符串 / 纯空白 / 不含 '@' / 超长
        """
        if not isinstance(recipient_email, str):
            raise TypeError(
                f"recipient_email 必须是 str,实际 type={type(recipient_email).__name__},"
                f" value={recipient_email!r}"
            )
        stripped = recipient_email.strip()
        if not stripped:
            raise ValueError("recipient_email 必非空(经 strip())")
        if "@" not in stripped:
            raise ValueError(f"recipient_email 必须含 '@' 字符,实际 {stripped!r}")
        if len(stripped) > _EMAIL_MAX_LEN:
            raise ValueError(f"recipient_email 长度超 {_EMAIL_MAX_LEN}(实际 {len(stripped)})")
        return stripped

    @staticmethod
    def _validate_reason(reason: str) -> str:
        """严判 reason(允许空字符串,≤ 500 字符).

        Raises:
            TypeError: 非 str
            ValueError: 超长(500 字符上限,留审计余地)
        """
        if not isinstance(reason, str):
            raise TypeError(
                f"reason 必须是 str,实际 type={type(reason).__name__}, value={reason!r}"
            )
        if len(reason) > 500:
            raise ValueError(f"reason 长度超 500(实际 {len(reason)})")
        return reason

    @staticmethod
    def _validate_added_by(added_by: str) -> str:
        """严判 added_by(3 选 1 枚举,D4.7.3 v1.0.5 P2-1 范本: type 严判在 hash 前).

        Raises:
            TypeError: 非 str
            ValueError: 不在 3 类白名单
        """
        if not isinstance(added_by, str):
            raise TypeError(
                f"added_by 必须是 str,实际 type={type(added_by).__name__}, value={added_by!r}"
            )
        if added_by not in _ADDED_BY_CHOICES:
            raise ValueError(
                f"added_by 必须是 3 选 1 枚举 {_ADDED_BY_CHOICES!r}, 实际 {added_by!r}"
            )
        return added_by

    @staticmethod
    def _validate_ms(ms: int, field_name: str) -> int:
        """严判 ms 字段(int 拒 bool,>= 0).

        D4.7.3 v1.0.4 P2-2 范本: type() is bool 检查在 isinstance 之前,
        拒 bool 子类(isinstance(True, int)==True 陷阱).
        """
        if type(ms) is bool or not isinstance(ms, int) or ms < 0:
            raise ValueError(
                f"{field_name} 必须是原生 int(非 bool) >= 0, "
                f"实际 type={type(ms).__name__}, value={ms!r}"
            )
        return ms

    @staticmethod
    def _validate_is_active(is_active: Any) -> int:
        """严判 is_active(bool 拒 int, 沿 D4.7.3 v1.0.5 P2-1 范本).

        拒绝:
            - None / 非 bool 类型(int 子类是常见陷阱)
        """
        if type(is_active) is not bool:
            raise TypeError(
                f"is_active 必须是 bool(非 int 子类),"
                f"实际 type={type(is_active).__name__}, value={is_active!r}"
            )
        return 1 if is_active else 0

    # ===== 公开 API =====

    def insert(
        self,
        recipient_email: str,
        *,
        reason: str = "",
        added_by: str = "manual",
        added_at_ms: int | None = None,
        is_active: bool = True,
    ) -> RecipientBlacklist:
        """插入一条黑名单条目(v0.2 B4.1 入库入口 — L1 UNIQUE 业务阻断).

        Args:
            recipient_email: 收件人邮箱(L1 硬约束,必填含 '@')
            reason: 拉黑原因(允许空字符串,≤ 500 字符)
            added_by: 来源(3 选 1 枚举: 'manual' / 'auto_spam' / 'auto_bounce',默认 'manual')
            added_at_ms: 入库时间戳(默认 = 当前时间)
            is_active: 是否启用(默认 True,deactivate() 走 is_active=0 软删除)

        Returns:
            新插入的 RecipientBlacklist(已 refresh,id/added_at_ms 都可读)

        Raises:
            RecipientBlacklistDuplicateError: UNIQUE(recipient_email) 冲突(L1 业务阻断入口)
            ValueError: 业务层严判失败(类型 / 范围 / 枚举值)
            sqlalchemy.exc.OperationalError / DataError / InterfaceError: 技术失败
        """
        # 1. 业务层严判(沿 D4.7.3 v1.0.5/v1.0.6 范本: type 严判在 hash 前)
        recipient_email = self._validate_recipient_email(recipient_email)
        reason = self._validate_reason(reason)
        added_by = self._validate_added_by(added_by)
        is_active_int = self._validate_is_active(is_active)
        if added_at_ms is None:
            added_at_ms = int(time.time() * 1000)
        else:
            added_at_ms = self._validate_ms(added_at_ms, "added_at_ms")

        # 2. 落库(D3.3.3 教训: except 范围窄化,只接 IntegrityError)
        try:
            with self._sf() as session:
                entry = RecipientBlacklist(
                    recipient_email=recipient_email,
                    reason=reason,
                    added_by=added_by,
                    added_at_ms=added_at_ms,
                    is_active=is_active_int,
                )
                session.add(entry)
                session.commit()
                session.refresh(entry)
                return entry
        except IntegrityError as e:
            # 业务阻断入口(UNIQUE 冲突)
            raise RecipientBlacklistDuplicateError(
                f"UNIQUE(recipient_email={recipient_email!r}) 冲突(已在黑名单)",
                recipient_email=recipient_email,
                original_error=e,
            ) from e
        except _sqlcipher_dbapi.IntegrityError as e:
            # SQLCipher dialect 不包装 dbapi 异常(D3.3.2 教训)
            raise RecipientBlacklistDuplicateError(
                f"UNIQUE(recipient_email={recipient_email!r}) 冲突(已在黑名单)",
                recipient_email=recipient_email,
                original_error=e,
            ) from e

    def get_by_id(self, bl_id: int) -> RecipientBlacklist | None:
        """按主键 id 查询.

        Args:
            bl_id: 黑名单主键

        Returns:
            RecipientBlacklist 或 None(未找到)
        """
        if type(bl_id) is bool or not isinstance(bl_id, int) or bl_id < 1:
            raise ValueError(
                f"bl_id 必须是原生 int(非 bool) >= 1, "
                f"实际 type={type(bl_id).__name__}, value={bl_id!r}"
            )
        with self._sf() as session:
            return session.get(RecipientBlacklist, bl_id)

    def find_by_email(self, recipient_email: str) -> RecipientBlacklist | None:
        """按 recipient_email 查询(L1 业务阻断入口的反向查询).

        Args:
            recipient_email: 收件人邮箱

        Returns:
            RecipientBlacklist 或 None(未找到)
        """
        recipient_email = self._validate_recipient_email(recipient_email)
        with self._sf() as session:
            stmt = select(RecipientBlacklist).where(
                RecipientBlacklist.recipient_email == recipient_email
            )
            return session.execute(stmt).scalar_one_or_none()

    def is_blocked(self, recipient_email: str) -> bool:
        """hot-path 查询: 邮箱是否在黑名单(B4.2 Adapter 调用).

        Args:
            recipient_email: 收件人邮箱

        Returns:
            True = 邮箱在黑名单(is_active=1 状态)
            False = 邮箱不在黑名单(或已软删除 is_active=0)
        """
        # 不走严判(避免 hot-path 性能损失,B4.2 Adapter 入口已严判)
        if not isinstance(recipient_email, str) or not recipient_email.strip():
            return False
        if "@" not in recipient_email:
            return False
        with self._sf() as session:
            stmt = select(RecipientBlacklist.is_active).where(
                RecipientBlacklist.recipient_email == recipient_email.strip()
            )
            result = session.execute(stmt).scalar_one_or_none()
            return result == 1

    def list_all(self, *, only_active: bool = True) -> list[RecipientBlacklist]:
        """列出全部黑名单条目(管理员查询用,B4.1 不做 admin CLI 但保留 API).

        Args:
            only_active: True = 仅返回 is_active=1(默认), False = 返回全部

        Returns:
            RecipientBlacklist 列表(按 added_at_ms DESC 倒序)
        """
        if not isinstance(only_active, bool):
            raise TypeError(f"only_active 必须是 bool, 实际 type={type(only_active).__name__}")
        with self._sf() as session:
            stmt = select(RecipientBlacklist)
            if only_active:
                stmt = stmt.where(RecipientBlacklist.is_active == 1)
            stmt = stmt.order_by(text("added_at_ms DESC"))
            return list(session.execute(stmt).scalars())

    def deactivate(self, bl_id: int) -> None:
        """软删除黑名单条目(is_active=0,审计可追溯).

        Args:
            bl_id: 黑名单主键

        Raises:
            ValueError: bl_id 严判失败 / 条目不存在
            sqlalchemy.exc.OperationalError / DataError / InterfaceError: 技术失败
        """
        if type(bl_id) is bool or not isinstance(bl_id, int) or bl_id < 1:
            raise ValueError(
                f"bl_id 必须是原生 int(非 bool) >= 1, "
                f"实际 type={type(bl_id).__name__}, value={bl_id!r}"
            )
        with self._sf() as session:
            entry = session.get(RecipientBlacklist, bl_id)
            if entry is None:
                raise ValueError(f"bl_id={bl_id} 不存在")
            if entry.is_active == 0:
                return  # 已软删除,幂等
            entry.is_active = 0
            session.commit()
