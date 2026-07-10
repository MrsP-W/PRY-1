"""D3.2 — SQLCipher 与 SQLAlchemy 的兼容性适配层。

解决问题（D3.2 启动时实测）：

**dict_factory 与 SA dialect 探针冲突**
   - D3.1 决策：`Database.open()` 设 `conn.row_factory = _dict_factory`，
     业务代码 `db.fetch_all()` 返回 `list[dict[str, Any]]`（row["col"] 可用）
   - D3.2 引入 SQLAlchemy 后：SA SQLite dialect 在 `first_connect` 钩子调
     `get_isolation_level` 期望 tuple-like row → 我们的 dict_factory 让 row
     变 dict → `row[0]` KeyError

**D3.2 决策**：把 row_factory 推到**方法入口**临时设（[`Database.execute`](db.py) /
[`fetch_all`](db.py) / [`fetch_one`](db.py) / [`executemany`](db.py) 内部），
conn.row_factory 常态是 None — SA 探针 OK，业务代码 dict 访问也 OK。

**本模块**只做一件事：让 SA engine 走 SQLCipher Database.open()（creator 模式）。

用法：

    from my_ai_employee.core.db import Database
    from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine

    db = Database.open()
    engine = make_sqlalchemy_engine(db)
    Base.metadata.create_all(engine)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import sqlcipher3.dbapi2 as _dbapi2
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from my_ai_employee.core.db import Database

__all__ = [
    "make_sqlalchemy_creator",
    "make_sqlalchemy_engine",
]


def make_sqlalchemy_creator(
    db: Database | None = None,
    *,
    db_path: Path | None = None,
) -> Callable[[], _dbapi2.Connection]:
    """返回 SA engine 的 creator 函数（D3.2 关键工具）。

    creator 干一件事：拿 `db.connection`（**受控入口** — D3.1.2 设计，
    不是私有 `_conn`）然后返回给 SQLAlchemy。

    **不需要**在 creator 内改 row_factory：D3.2 已把 row_factory 推到
    Database 方法入口（业务代码走 `db.fetch_*` 时临时设），
    `conn.row_factory` 常态是 None — SA 探针天然满足。

    Args:
        db: 已 open 的 Database 实例(短生命周期脚本/测试用)
        db_path: DB 路径(长生命周期进程用;每次连接独立 Database.open)

    Returns:
        接受 0 参数、返回 sqlcipher3 connection 的 callable
    """
    if (db is None) == (db_path is None):
        raise ValueError("make_sqlalchemy_creator 需要且只能传入 db 或 db_path")

    if db_path is not None:
        path = db_path

        def creator_from_path() -> _dbapi2.Connection:
            # 长生命周期服务不能持有已离开 context manager 的 db.connection。
            return Database.open(db_path=path).connection

        return creator_from_path

    def creator() -> _dbapi2.Connection:
        # D3.1.2 受控入口（不是私有 _conn）
        assert db is not None
        return db.connection

    return creator


def make_sqlalchemy_engine(
    db: Database | None = None,
    *,
    db_path: Path | None = None,
) -> Engine:
    """便捷函数：一步拿到走 SQLCipher 的 SA engine。

    等价于：
        engine = create_engine("sqlite:///", creator=make_sqlalchemy_creator(db))

    但更明确（明确走 SQLCipher，不让用户疑惑 sqlite:/// 含义）。

    **撞坑 #97 修复（2026-07-10）**：当传入 `db_path`（即长生命周期服务，如
    Dashboard / Menu Bar 长期 server）时，强制使用 `NullPool` —— **不** 用
    SA 默认的连接池（默认池会让 connection 在 thread A 创建、thread B 关闭，
    触发 `sqlcipher3.check_same_thread=True` 抛 `ProgrammingError`）。

    `NullPool` 每次 checkout 都让 creator 现建一条 sqlcipher3 connection,
    用完即关,close 一定在原 thread,**零跨线程 close 风险**。

    **不** 改用 `check_same_thread=False + StaticPool`：那会让多个 HTTP
    请求线程共享同一条 connection,SQLCipher 写入并发可能破坏 WAL/finalize
    顺序,把 close-time 异常升级为并发读写风险。

    `db` 短生命周期脚本保持默认 pool(同进程内不会跨线程)。

    Args:
        db: 已 open 的 Database 实例(短生命周期脚本/测试用)
        db_path: DB 路径(长生命周期进程用;每次连接独立 Database.open)

    Returns:
        SQLAlchemy Engine，creator 走 SQLCipher Database.open()
    """
    creator = make_sqlalchemy_creator(db, db_path=db_path)
    if db_path is not None:
        # 长生命周期 Dashboard / Menu Bar:每请求线程独立连接
        return create_engine("sqlite:///", creator=creator, poolclass=NullPool)
    # 短生命周期脚本:同进程无并发,默认 pool 即可
    return create_engine("sqlite:///", creator=creator)
