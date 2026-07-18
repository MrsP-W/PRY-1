"""D6.6 P2 修复 — Alembic version 校验(防止漏迁移 + 走 alembic 而非 create_all).

承接 docs/v0.1-launch-plan.md §D6 + D6.4 0007_transactions migration:
    - CLI 在 import 前必须确认 alembic_version >= '0007_transactions'
    - 防止在旧 DB 上漏迁移(导致 transactions 表不存在)
    - 与 D3.2 8 雷区保持一致(Base.metadata.create_all 只兜底,不替代 alembic)
    - 给用户清晰的升级提示(必须先跑 alembic upgrade head)

设计原则(沿 D3.2 alembic env.py + D4.8 OutboxStore 严判范本):
    - get_alembic_revision 读 alembic_version.version_num
    - 表不存在 → 返回 None(调用方决定如何处理)
    - assert_min_revision 校验并抛清晰错误
    - 比较走字典序(假设 4 位数字命名规范 0001_xxx / 0007_xxx)
"""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


class AlembicTechnicalError(RuntimeError):
    """读取 Alembic 状态时发生的可恢复技术错误。"""


def get_alembic_revision(engine: Engine) -> str | None:
    """读 alembic_version 表的当前 revision.

    Args:
        engine: SQLAlchemy engine(已连真实 DB)

    Returns:
        revision 字符串(如 '0007_transactions')或 None(表不存在/未初始化)

    Raises:
        RuntimeError: 数据库不可达或 alembic_version 表结构异常
    """
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    except SQLAlchemyError as e:
        err_str = str(e).lower()
        # 仅明确的缺表错误才表示“尚未迁移”。SQLAlchemy 的 lock/连接错误会把
        # SELECT ... alembic_version 附在错误文本中，不能据此误判为缺表。
        if "no such table" in err_str and "alembic_version" in err_str:
            return None
        raise AlembicTechnicalError(f"读 alembic_version 失败: {e!r}") from e
    if row is None:
        return None
    return str(row[0])


def assert_min_revision(engine: Engine, min_revision: str) -> str:
    """检查 alembic_version >= min_revision(D6.6 CLI 入口段硬校验).

    Args:
        engine: SQLAlchemy engine
        min_revision: 最低允许的 revision(包含,如 '0007_transactions')

    Returns:
        当前 revision(校验通过时)

    Raises:
        RuntimeError: alembic_version 不存在 / revision 过旧
    """
    current = get_alembic_revision(engine)
    if current is None:
        raise RuntimeError(
            "alembic_version 表不存在 — DB 未初始化 alembic 迁移, 请先跑: alembic upgrade head"
        )
    if not _is_revision_at_least(current, min_revision):
        raise RuntimeError(
            f"alembic revision 过旧: 当前={current!r}, 需要>={min_revision!r}, "
            f"请先跑: alembic upgrade head"
        )
    return current


def _is_revision_at_least(current: str, minimum: str) -> bool:
    """比较两个 alembic revision 字符串(沿字典序,假设 4 位数字命名规范).

    沿 D3.2 8 雷区:revision 命名 `0001_xxx` / `0007_xxx` 等 4 位数字 + 下划线。
    提取数字前缀(0-padded),字典序比较等价于整数比较。
    """
    head = current.split("_", 1)[0]
    try:
        return int(head) >= int(minimum.split("_", 1)[0])
    except ValueError:
        return False


__all__ = [
    "AlembicTechnicalError",
    "get_alembic_revision",
    "assert_min_revision",
]
