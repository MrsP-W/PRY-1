"""D3.1 — SQLCipher 数据库封装。

设计（[docs/week1-mvp.md §D3.1 数据层基础]）：

    - **加密**：SQLCipher（PRAGMA key，密码 = 32 字节随机串，存 Keychain）
    - **DB 路径**：`~/Library/Application Support/my-ai-employee/data.db`
        - macOS 标准路径（D1.1 锁定 macOS only）
    - **首次启动**：自动生成密码并写 Keychain（service=`my-ai-employee.db`，account=`data.db`）
    - **PRAGMA 矩阵**：key + foreign_keys=ON + journal_mode=WAL + busy_timeout=5000 + synchronous=NORMAL
        - WAL：多读单写不阻塞（D3.3 同步脚本并发读不发愁）
        - busy_timeout=5000ms：DB 锁等 5s
        - synchronous=NORMAL：WAL 模式下推荐（性能/安全平衡）
    - **复用 D2.3 keychain**：[`my_ai_employee.core.keychain.get_db_password`](core/keychain.py)
    - **schema 应用**：[`my_ai_employee.core.schema.sql`](core/schema.sql)（D3.1）
    - **ORM**：D3.2 引入 SQLAlchemy（不在本文件范围）

API（最小可用）：

    with Database.open() as db:
        db.init_schema()
        db.execute("INSERT INTO emails ...", (...))
        # with 块退出自动 commit；异常自动 rollback

失败模式（应急版范本）：

    - Keychain 不可用 → KeychainResult.ok=False → 抛 PermissionError
    - 密码错 → sqlcipher3 抛 DatabaseError（"file is not a database"）
    - DB 文件锁 → 抛 sqlite3.OperationalError（"database is locked"），等 busy_timeout 后重试
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, cast

import sqlcipher3
from loguru import logger

from my_ai_employee.core import keychain

# DB 文件默认位置（macOS — D1.1 决策锁定）
DEFAULT_DB_DIR: Path = Path.home() / "Library" / "Application Support" / "my-ai-employee"
DEFAULT_DB_PATH: Path = DEFAULT_DB_DIR / "data.db"

# schema.sql 路径（相对于本文件）
SCHEMA_PATH: Path = Path(__file__).parent / "schema.sql"


def _dict_factory(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    """行工厂：cursor.description → dict[列名, 值]。

    选这个而不是 sqlite3.Row 的原因：
    sqlcipher3 的 cursor 不是 sqlite3.Cursor 子类，标准 sqlite3.Row 工厂
    会在 fetchall/fetchone 时抛 "Row() argument 1 must be sqlite3.Cursor"。
    dict_factory 等价行为：row["col"] 可用 + 列名迭代友好。
    """
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class Database:
    """SQLCipher 加密数据库封装。

    设计原则：
        - **显式事务**：execute 不自动 commit，由调用方 / 上下文管理器管
        - **PRAGMA key 参数化**：避免密码含 `'` 引爆 SQL
        - **外键默认开**：PRAGMA foreign_keys = ON（SQLite 默认关，D3 联表查询需要）
        - **复用 D2.3 keychain**：密码管理不重复发明

    用法：

        # 1. 短期脚本
        db = Database.open()
        db.init_schema()
        db.execute("INSERT INTO emails ...", (...))
        db.commit()
        db.close()

        # 2. 上下文管理器（推荐）
        with Database.open() as db:
            db.init_schema()
            db.execute("INSERT INTO emails ...", (...))
            # 退出自动 commit；异常自动 rollback
    """

    def __init__(self, conn: sqlcipher3.Connection, db_path: Path) -> None:
        self._conn = conn
        self._db_path = db_path
        self._closed = False

    @classmethod
    def open(cls, db_path: Path | None = None) -> Database:
        """打开加密 DB。

        流程：
            1. 读/生成密码 from Keychain（D2.3 包装）
            2. 创建父目录（首次启动）
            3. sqlcipher3.connect
            4. PRAGMA 矩阵（executescript 一把梭）：
                - key = <password>（SQLCipher 加密）
                - foreign_keys = ON（联表查询需要）
                - journal_mode = WAL（多读单写不阻塞，D3.3 同步脚本并发读必要）
                - busy_timeout = 5000（DB 锁等 5s 再失败）
                - synchronous = NORMAL（WAL 模式下推荐）
            5. 主动 PRAGMA quick_check 触发 SQLCipher 懒校验

        Raises:
            PermissionError: Keychain 不可用
            sqlcipher3.DatabaseError: 密码错或 DB 文件损坏
            OSError: 父目录创建失败
        """
        path = db_path or DEFAULT_DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)

        # 1. 读/生成密码
        cred = keychain.get_db_password()
        if not cred.ok or not cred.value:
            # 首次启动：自动生成 32 字节随机串（64 hex chars）并写入 Keychain
            new_password = secrets.token_hex(32)
            set_result = keychain.set_db_password(new_password)
            if not set_result.ok:
                raise PermissionError(
                    f"DB 密码写入 Keychain 失败: {set_result.error}\n"
                    f"请手动执行：security add-generic-password "
                    f"-a data.db -s {keychain.SERVICE_DB} -w <your-32byte-password>"
                )
            logger.info(
                f"DB 密码首次自动生成并存入 Keychain "
                f"({len(new_password)} chars, service={keychain.SERVICE_DB})"
            )
            password = new_password
        else:
            password = cred.value

        # 2-3. 连接 + 加密 + 性能/并发 PRAGMA
        conn = sqlcipher3.connect(str(path), timeout=15)
        # PRAGMA 不支持参数化占位符 `?`（sqlite 解析器限制）
        # 用 executescript + 字符串拼接；密码单引号转义防御（hex 不会出现 `'`）
        safe_password = password.replace("'", "''")
        # 整个块都包 try/except：
        # - D3.1.1 加了 PRAGMA journal_mode=WAL，WAL 模式切换会写 WAL 文件到磁盘，
        #   触发第一次读 DB header 页（SQLCipher 懒校验）→ 错密码会立即抛
        # - 所以"密码错"的 DatabaseError 可能从 executescript 抛，也可能从 quick_check 抛
        try:
            conn.executescript(
                f"PRAGMA key = '{safe_password}'; "
                f"PRAGMA foreign_keys = ON; "
                f"PRAGMA journal_mode = WAL; "
                f"PRAGMA busy_timeout = 5000; "
                f"PRAGMA synchronous = NORMAL;"
            )
            # 行工厂：sqlcipher3 的 cursor 不是 sqlite3.Cursor 子类，
            # 标准 sqlite3.Row 工厂会爆 "Row() argument 1 must be sqlite3.Cursor"
            # 用 dict_factory 等价效果：fetchall 返回 list[dict[列名, 值]]，row["col"] 可用
            conn.row_factory = _dict_factory
            # 主动触发密码校验（SQLCipher 是懒校验的 — PRAGMA key 本身不读加密页，
            # 第一次读加密 B-tree 页才校验）。
            # 实测多种触发：
            #   - SELECT count(*) FROM sqlite_master → 不可靠（page 1 header 不加密）
            #   - PRAGMA cipher_version → 不可靠（编译时常量）
            #   - PRAGMA integrity_check → 可靠但耗内存（读全部页）
            #   - PRAGMA quick_check → ✅ 轻量 + 100% 触发（只读 1 个 root page）
            conn.execute("PRAGMA quick_check").fetchone()
        except sqlcipher3.DatabaseError as e:
            # 关闭连接再重抛，避免半开连接泄漏
            conn.close()
            raise sqlcipher3.DatabaseError(
                f"DB 打开失败：密码错误或文件损坏 ({e})"
            ) from e
        logger.info(f"DB 打开: path={path}")

        return cls(conn, path)

    def init_schema(self, schema_path: Path | None = None) -> None:
        """应用 schema.sql（幂等 — IF NOT EXISTS）。

        重复调用安全：D3.1 起 alembic 之前的过渡期用于初始化。
        D3.2 引入 alembic 后，本方法主要在测试 fixture 用。
        """
        path = schema_path or SCHEMA_PATH
        sql = path.read_text(encoding="utf-8")
        # executescript 会自动 commit（DDL 不能回滚）
        self._conn.executescript(sql)
        logger.info(f"schema 已应用: {path}")

    def execute(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> sqlcipher3.Cursor:
        """执行单条 SQL（不自动 commit）。"""
        return self._conn.execute(sql, params)

    def executemany(
        self, sql: str, params_list: list[tuple[Any, ...]]
    ) -> sqlcipher3.Cursor:
        """批量执行（不自动 commit，性能优于 N 次 execute）。"""
        return self._conn.executemany(sql, params_list)

    def fetch_all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        """跑 SELECT，返回所有行（每行 = dict[列名, 值]）。"""
        # cast: sqlcipher3 没类型标注，mypy 推断为 list[Any]
        return cast(list[dict[str, Any]], self._conn.execute(sql, params).fetchall())

    def fetch_one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        """跑 SELECT，返回第一行 dict（无则 None）。"""
        # cast: sqlcipher3 没类型标注，mypy 推断为 Any
        return cast(dict[str, Any] | None, self._conn.execute(sql, params).fetchone())

    def commit(self) -> None:
        """显式 commit。"""
        self._conn.commit()

    def rollback(self) -> None:
        """显式 rollback。"""
        self._conn.rollback()

    def close(self) -> None:
        """关闭连接（幂等）。"""
        if not self._closed:
            self._conn.close()
            self._closed = True
            logger.info(f"DB 关闭: path={self._db_path}")

    # ===== 上下文管理器 =====

    def __enter__(self) -> Database:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
                logger.warning(f"DB 事务回滚: exc={exc_type.__name__}: {exc_val}")
        finally:
            self.close()

    @property
    def db_path(self) -> Path:
        """DB 文件路径（测试断言用）。"""
        return self._db_path

    @property
    def connection(self) -> sqlcipher3.Connection:
        """受控访问底层 sqlcipher3 connection（供 D3.2 alembic env.py / 高级用法）。

        设计动机（D3.1.2）：alembic 迁移需要拿原始 connection 才能 `connection.run_sync(...)`
        跑 SQLAlchemy DDL，但直接用私有 `_conn` 是封装泄漏。`connection` property 是
        **受控入口**：仅暴露 conn 引用，**不**绕过 Database 的事务/上下文管理逻辑
        （调用方仍应走 `with Database.open() as db:` 拿到 db 后再访问 db.connection）。

        警告：
            - 直接 `db.connection.execute(...)` 不会自动 commit（绕过 Database 封装）
            - 关闭后访问抛 RuntimeError（避免使用半关连接）
            - 普通 CRUD 请用 `execute` / `fetch_all` / `fetch_one`

        Raises:
            RuntimeError: DB 已关闭（`close()` 后 / `__exit__` 后）

        用法：

            with Database.open() as db:
                db.init_schema()
                raw = db.connection  # alembic / 高级 SQLAlchemy 用法
                # 业务 SQL 仍走 db.execute(...)
        """
        if self._closed:
            raise RuntimeError(
                "DB 已关闭，无法访问 connection。"
                "请确保 Database 实例在 with 块内使用（context manager）。"
            )
        return self._conn


__all__ = [
    "Database",
    "DEFAULT_DB_PATH",
    "DEFAULT_DB_DIR",
    "SCHEMA_PATH",
]
