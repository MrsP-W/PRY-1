"""D3.2 — alembic env.py（集成 SQLCipher 密码）。

设计（[docs/week1-mvp.md §D3.2 alembic 集成]）：

    - **不**用 alembic 默认的 sqlite+pysqlite URL 模式
    - 改用 `create_engine(..., creator=...)` — creator 返回 sqlcipher3.Connection
    - creator 走 [`make_sqlalchemy_creator`](../../sqlcipher_compat.py)（D3.2 适配层）
    - 这样 alembic 走的也是 SQLCipher 加密连接
    - metadata 来自 `my_ai_employee.core.models.Base.metadata`

关键点：
    - alembic offline 模式（`alembic upgrade head --sql`）不需要真连接，
      直接用 SQLAlchemy 字符串渲染，**不**走 creator
    - online 模式（`alembic upgrade head`）走 creator
    - target_metadata = Base.metadata（6 个 Model 都注册到这）

D3.2 决策（无 cursor patch）：
    - D3.1 dict_factory 已推到 Database 方法入口（execute / fetch_*），
      conn.row_factory 常态是 None — SA dialect 探针（get_isolation_level）天然满足
    - sqlcipher3 Cursor 不支持 context manager，但 SA 2.0 SQLite dialect 不调
      `with cursor()`（只在 Oracle dialect 用），所以**不需要** monkey-patch
    - 这俩决策让本文件保持极简：只调 `make_sqlalchemy_creator` 即可
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 让 alembic 能 import 项目源码
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 这就是 alembic 反射的元数据（6 个 Model）
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_creator  # noqa: E402

# alembic 配置（ini 文件）
config = context.config

# 配置 logging（从 alembic.ini 读）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 反射用 metadata
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """offline 模式：只生成 SQL，不连真实 DB（用于生成迁移脚本预览）。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 限制：ALTER TABLE 用 batch
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """online 模式：连真实 DB 跑迁移。"""
    # 走 sqlcipher_creator（每次 new engine 时调一次）
    from my_ai_employee.core.db import Database  # 延迟 import

    db = Database.open()
    creator = make_sqlalchemy_creator(db)

    # 用 ini 的 sqlalchemy.url（默认是 sqlite:///，但 creator 接管实际连接）
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = "sqlite:///"  # 占位，creator 接管
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # alembic 不需要连接池
        creator=creator,  # ← 关键：creator 走 SQLCipher
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite 限制
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
