"""D9.1 — NoteStore:notes 表读写封装(10 字段 + Note ORM).

承接 D9(Apple Notes 同步 + ⌥⌘N 剪贴板结构化)+ 沿 D6.4 TransactionStore 范本。
10 字段 schema(用户决策 2026-06-15 锁定"完整版"):

    1. id                INTEGER PK AUTOINCREMENT
    2. apple_note_id     TEXT NOT NULL UNIQUE       # Apple ID 硬约束(L1 幂等)
    3. folder            TEXT NOT NULL               # 默认 "Notes"
    4. title             TEXT NOT NULL               # 空字符串兜底
    5. body              TEXT NOT NULL               # HTML 转纯文本
    6. attachments_json  TEXT NULL                   # JSON list,不含二进制
    7. is_private        INTEGER NOT NULL DEFAULT 0  # 0/1 BOOLEAN 走 Integer
    8. tags              TEXT NULL                   # note_structurer 输出
    9. synced_at_ms      INTEGER NOT NULL            # Unix epoch ms
    10. updated_at_ms    INTEGER NOT NULL            # Apple 修改时间

D3.2 8 雷区严判(全部应用):
    1. NUMERIC(10, 2) 非 Float — N/A(本表无金额字段)
    2. BOOLEAN 走 Integer + server_default="0"
    3. DATE 走 Date — N/A(本表用 ms INTEGER)
    4. AUTOINCREMENT(非 AUTO_INCREMENT)
    5. 文件名 0008_notes.py(下划线命名)
    6. migration downgrade() 必须能干净回滚
    7. render_as_batch=True 在 env.py 已配
    8. DESC 索引用 sa.text("synced_at_ms DESC")

D3.3.3 教训应用:
    - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突 → 业务阻断)
    - OperationalError / DataError / InterfaceError **不**捕获

D4.7.3 教训应用:
    - 工厂层 + 数据类 `__post_init__` 是双入口必须双层防御
    - 跨字段关系必须双向覆盖防漏方向
    - 异常类型必须统一, type 严判必须在 hash 操作前
    - 严判时不要遗漏 Adapter 入口段和数据类 `__post_init__` 三层都要严判

D9 决策应用:
    - is_private=1 跳过 LLM 标 pending(沿 D4.7.2 v1.0.6 SPAM 阻断范本)
    - tags 字段供 note_structurer 写(逗号分隔)
    - 附件只存元数据(不含二进制)
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

# ===== 自定义异常(D9.1 契约 — L1 UNIQUE 冲突 → 业务阻断入口)=====


class NoteDuplicateError(Exception):
    """L1 UNIQUE(apple_note_id) 冲突 → 业务阻断入口(D9.1)。

    Adapter 层(NoteStructurerAdapter)接住此异常,转写
    record_note_business_blocked_and_emit,走业务阻断入口。

    Attributes:
        apple_note_id: 重复的 Apple ID
        original_error: SQLAlchemy IntegrityError / SQLCipher dbapi2.IntegrityError
    """

    def __init__(
        self,
        message: str,
        *,
        apple_note_id: str,
        original_error: Any = None,
    ) -> None:
        super().__init__(message)
        self.apple_note_id = apple_note_id
        self.original_error = original_error


# ===== Note ORM(10 字段)=====


class Note(Base):
    """Apple Notes 主表(mirror 0008 alembic migration)。

    字段注解:
        - id:                INTEGER PK AUTOINCREMENT
        - apple_note_id:     TEXT NOT NULL UNIQUE
        - folder:            TEXT NOT NULL
        - title:             TEXT NOT NULL
        - body:              TEXT NOT NULL
        - attachments_json:  TEXT NULL
        - is_private:        INTEGER NOT NULL DEFAULT 0
        - tags:              TEXT NULL
        - synced_at_ms:      INTEGER NOT NULL
        - updated_at_ms:     INTEGER NOT NULL

    约束:
        - UNIQUE(apple_note_id)
    索引:
        - idx_notes_folder_synced(folder, synced_at_ms DESC)
        - idx_notes_updated(updated_at_ms DESC)
    """

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    apple_note_id: Mapped[str] = mapped_column(Text, nullable=False)
    folder: Mapped[str] = mapped_column(
        Text, nullable=False, default="Notes", server_default="Notes"
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    attachments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_private: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # 约束 + 索引(D3.2 雷区 #8: DESC 索引用 sa.text 包裹)
    __table_args__ = (
        UniqueConstraint("apple_note_id", name="uq_notes_apple_note_id"),
        Index("idx_notes_folder_synced", "folder", text("synced_at_ms DESC")),
        Index("idx_notes_updated", text("updated_at_ms DESC")),
    )

    def __repr__(self) -> str:
        return (
            f"<Note id={self.id} apple_note_id={self.apple_note_id!r} "
            f"folder={self.folder!r} title={self.title!r}>"
        )


# ===== NoteStore(沿 D6.4 TransactionStore 范本)=====


class NoteStore:
    """Apple Notes 读写封装(10 字段 + L1 UNIQUE 业务阻断).

    设计(沿 TransactionStore 范本 + D3.2 8 雷区严判):
        - insert(): L1 UNIQUE 命中 → NoteDuplicateError(业务阻断)
                    严判 type/value/范围(BOOLEAN 走 Integer / attachments_json None 或 str)
        - get_by_id / list_all / find_by_apple_id: 3 类热路径查询
        - 严判只放在 Store 层(契约层接受已校验参数,不再二次严判)

    业务规则(D9.1):
        - is_private 走 Integer(0/1),严判 type() is bool(非 int)
        - attachments_json 必须是 None 或 str(空字符串兜底)
        - tags 必须是 None 或 str(逗号分隔,严判非空时 strip 后非空)
        - synced_at_ms / updated_at_ms 必传 int(非 bool)>= 0

    D3.3.3 教训应用:
        - except 范围窄化: 只接 IntegrityError(UNIQUE 冲突 → NoteDuplicateError)
        - OperationalError / DataError / InterfaceError **不**捕获,透传给 Adapter
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
    def _validate_apple_note_id(apple_note_id: str) -> str:
        """严判 apple_note_id 非空字符串(1-128 字符,strip 后非空).

        Raises:
            TypeError: 非 str
            ValueError: 空字符串 / 过长
        """
        if not isinstance(apple_note_id, str):
            raise TypeError(
                f"apple_note_id 必须是 str,实际 type={type(apple_note_id).__name__},"
                f" value={apple_note_id!r}"
            )
        stripped = apple_note_id.strip()
        if not stripped:
            raise ValueError("apple_note_id 必非空(经 strip())")
        if len(stripped) > 128:
            raise ValueError(f"apple_note_id 长度超 128(实际 {len(stripped)})")
        return stripped

    @staticmethod
    def _validate_folder(folder: str) -> str:
        """严判 folder 非空字符串(1-64 字符)."""
        if not isinstance(folder, str):
            raise TypeError(
                f"folder 必须是 str,实际 type={type(folder).__name__}, value={folder!r}"
            )
        stripped = folder.strip()
        if not stripped:
            raise ValueError("folder 必非空(经 strip())")
        if len(stripped) > 64:
            raise ValueError(f"folder 长度超 64(实际 {len(stripped)})")
        return stripped

    @staticmethod
    def _validate_title(title: str) -> str:
        """严判 title 非 str(允许空字符串)."""
        if not isinstance(title, str):
            raise TypeError(f"title 必须是 str,实际 type={type(title).__name__}, value={title!r}")
        return title

    @staticmethod
    def _validate_body(body: str) -> str:
        """严判 body 非 str(允许空字符串)."""
        if not isinstance(body, str):
            raise TypeError(f"body 必须是 str,实际 type={type(body).__name__}, value={body!r}")
        return body

    @staticmethod
    def _validate_attachments_json(attachments_json: str | None) -> str | None:
        """严判 attachments_json 必须是 None 或 str(JSON 字符串).

        Raises:
            TypeError: 非 None 也非 str
        """
        if attachments_json is None:
            return None
        if not isinstance(attachments_json, str):
            raise TypeError(
                f"attachments_json 必须是 str 或 None,"
                f"实际 type={type(attachments_json).__name__}, value={attachments_json!r}"
            )
        return attachments_json

    @staticmethod
    def _validate_tags(tags: str | None) -> str | None:
        """严判 tags 必须是 None 或 str(非空时 strip 后非空).

        Raises:
            TypeError: 非 None 也非 str
            ValueError: 仅含空白字符
        """
        if tags is None:
            return None
        if not isinstance(tags, str):
            raise TypeError(
                f"tags 必须是 str 或 None,实际 type={type(tags).__name__}, value={tags!r}"
            )
        if not tags.strip():
            raise ValueError("tags 仅含空白字符(应传 None 或非空字符串)")
        return tags

    @staticmethod
    def _validate_ms(value: int, field_name: str) -> int:
        """严判 epoch ms:int(非 bool)>= 0.

        Raises:
            TypeError: 非 int(bool 子类陷阱)
            ValueError: < 0
        """
        if type(value) is bool or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"{field_name} 必须是原生 int(非 bool)>= 0,"
                f"实际 type={type(value).__name__}, value={value!r}"
            )
        return value

    @staticmethod
    def _validate_is_private(is_private: bool) -> int:
        """严判 is_private bool(非 int 子类),转 Integer(0/1)."""
        if type(is_private) is not bool:
            raise TypeError(
                f"is_private 必须是 bool(非 int 子类),"
                f"实际 type={type(is_private).__name__}, value={is_private!r}"
            )
        return 1 if is_private else 0

    # ===== 公开 API =====

    def insert(
        self,
        apple_note_id: str,
        folder: str,
        title: str,
        body: str,
        updated_at_ms: int,
        *,
        attachments_json: str | None = None,
        is_private: bool = False,
        tags: str | None = None,
        synced_at_ms: int | None = None,
    ) -> Note:
        """插入一条 note(D9.1 入库入口 — L1 UNIQUE 业务阻断).

        Args:
            apple_note_id: Apple ID(L1 硬约束)
            folder: 文件夹名(默认 "Notes")
            title: 笔记标题(允许空字符串)
            body: 笔记正文(HTML 转纯文本)
            updated_at_ms: Apple Notes 最后修改 Unix epoch ms
            attachments_json: 附件元数据 JSON 字符串(不含二进制,可空)
            is_private: 是否私密(默认 False,沿 D4.7.2 v1.0.6 私密阻断范本)
            tags: 标签(逗号分隔,note_structurer 输出,可空)
            synced_at_ms: 同步时间戳(默认 = 当前时间)

        Returns:
            新插入的 Note(已 refresh,id/synced_at_ms 都可读)

        Raises:
            NoteDuplicateError: UNIQUE(apple_note_id) 冲突(L1 业务阻断入口)
            ValueError: 业务层严判失败(类型 / 范围 / 枚举值)
            sqlalchemy.exc.OperationalError / DataError / InterfaceError: 技术失败
        """
        # 1. 业务层严判(沿 D4.7.3 v1.0.5/v1.0.6 范本: type 严判在 hash 前)
        apple_note_id = self._validate_apple_note_id(apple_note_id)
        folder = self._validate_folder(folder)
        title = self._validate_title(title)
        body = self._validate_body(body)
        attachments_json = self._validate_attachments_json(attachments_json)
        tags = self._validate_tags(tags)
        is_private_int = self._validate_is_private(is_private)
        updated_at_ms = self._validate_ms(updated_at_ms, "updated_at_ms")
        if synced_at_ms is None:
            synced_at_ms = int(time.time() * 1000)
        else:
            synced_at_ms = self._validate_ms(synced_at_ms, "synced_at_ms")

        # 2. 落库(D3.3.3 教训: except 范围窄化,只接 IntegrityError)
        try:
            with self._sf() as session:
                note = Note(
                    apple_note_id=apple_note_id,
                    folder=folder,
                    title=title,
                    body=body,
                    attachments_json=attachments_json,
                    is_private=is_private_int,
                    tags=tags,
                    synced_at_ms=synced_at_ms,
                    updated_at_ms=updated_at_ms,
                )
                session.add(note)
                session.commit()
                session.refresh(note)
                return note
        except IntegrityError as e:
            # 业务阻断入口(UNIQUE 冲突)
            raise NoteDuplicateError(
                f"UNIQUE(apple_note_id={apple_note_id!r}) 冲突(已同步过)",
                apple_note_id=apple_note_id,
                original_error=e,
            ) from e
        except _sqlcipher_dbapi.IntegrityError as e:
            # SQLCipher dialect 不包装 dbapi 异常(D3.3.2 教训)
            raise NoteDuplicateError(
                f"UNIQUE(apple_note_id={apple_note_id!r}) 冲突(已同步过)",
                apple_note_id=apple_note_id,
                original_error=e,
            ) from e

    def get_by_id(self, note_id: int) -> Note | None:
        """按主键 id 查询.

        Args:
            note_id: note 主键

        Returns:
            Note 或 None(未找到)
        """
        if type(note_id) is bool or not isinstance(note_id, int) or note_id < 1:
            raise ValueError(
                f"note_id 必须是正 int(非 bool),"
                f"实际 type={type(note_id).__name__}, value={note_id!r}"
            )
        with self._sf() as session:
            return session.get(Note, note_id)

    def find_by_apple_id(self, apple_note_id: str) -> Note | None:
        """按 apple_note_id 查询(L1 幂等检查).

        Args:
            apple_note_id: Apple ID

        Returns:
            Note 或 None(未找到)
        """
        apple_note_id = self._validate_apple_note_id(apple_note_id)
        with self._sf() as session:
            stmt = select(Note).where(Note.apple_note_id == apple_note_id)
            return session.execute(stmt).scalar_one_or_none()

    def list_all(self, limit: int = 1000) -> list[Note]:
        """列出所有 notes(按 synced_at_ms DESC 倒序).

        Args:
            limit: 最多返回条数(默认 1000,严判正 int)

        Returns:
            list[Note]: 按 synced_at_ms 倒序
        """
        if type(limit) is bool or not isinstance(limit, int) or limit < 1:
            raise ValueError(
                f"limit 必须是正 int(非 bool),实际 type={type(limit).__name__}, value={limit!r}"
            )
        with self._sf() as session:
            stmt = select(Note).order_by(text("synced_at_ms DESC")).limit(limit)
            return list(session.execute(stmt).scalars().all())

    def list_by_folder(self, folder: str, limit: int = 1000) -> list[Note]:
        """按 folder 查询.

        Args:
            folder: 文件夹名
            limit: 最多返回条数

        Returns:
            list[Note]: 按 synced_at_ms 倒序
        """
        folder = self._validate_folder(folder)
        if type(limit) is bool or not isinstance(limit, int) or limit < 1:
            raise ValueError(
                f"limit 必须是正 int(非 bool),实际 type={type(limit).__name__}, value={limit!r}"
            )
        with self._sf() as session:
            stmt = (
                select(Note)
                .where(Note.folder == folder)
                .order_by(text("synced_at_ms DESC"))
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())


# ===== 模块导出 =====


__all__ = [
    "Note",
    "NoteStore",
    "NoteDuplicateError",
]
