"""D4.3.2 修复迁移 — 替换 events 表 UNIQUE 约束为全局唯一.

Revision ID: 0003_fix_events_fingerprint_unique
Revises: 0002_events
Create Date: 2026-06-08

背景 (D4.3.1 复检发现的 P1):
    - 旧 0002_events 定义 `UNIQUE(event, source, subject_id, fingerprint)` 4 字段联合约束
    - SQLite UNIQUE 允许多个 NULL(subject_id=NULL 时被视作不同值)
    - 同 fingerprint + subject_id=NULL 重复插入 → 破坏 dedupe, on_conflict='raise' 抛错风险
    - D4.3.1 修复直接改了 0002_events 的 UniqueConstraint, 但 alembic 不会重新执行同一 revision
    - **已迁移到 0002_events revision 的旧库仍保留旧 4 字段 UNIQUE, 漏洞未修**

本迁移目标:
    - 重建 events 表, 把 UNIQUE(event, source, subject_id, fingerprint) 替换为
      `UNIQUE(fingerprint)` 全局唯一
    - 对所有已迁移库幂等:
        1) 旧库 (跑了旧 0002, 4 字段 UNIQUE) → 数据迁移 + 升级到 UNIQUE(fingerprint)
        2) 新库 (跑了 D4.3.1 改后 0002, 已 UNIQUE(fingerprint)) → 数据 1:1 复制, 等价 no-op
    - 处理已存在重复行: 用 `INSERT OR IGNORE` 保留每个 fingerprint 的最早一行
      (旧库可能因为 P1 漏洞已写入 subject_id=NULL 重复 fingerprint, UNIQUE 冲突会爆)

设计:
    - SQLite 不支持直接 DROP/ADD UNIQUE 约束 → 用"建新表→拷数据→删旧表→改名"模式
    - 不用 alembic batch_alter_table: 显式 raw SQL 避免 ORM 推断出错, 行为可预测
    - 数据迁移 INSERT OR IGNORE 防御已有重复行(即使 dedupe 默认模式 + NULL 漏洞组合)
    - 重建全部 6 索引 (created_at DESC / event / status / source / subject_id / fingerprint)

参考:
    - D3.2.3 教训: SQLite ALTER TABLE 限制, 走 raw SQL
    - D3.3.3 教训: 窄 except (本迁移不涉及 SQLAlchemy 异常)
    - D4.3.1 复检: 旧 4 字段 UNIQUE 在 subject_id=NULL 时被 SQLite 视为不同行
    - 契约保证: UNIQUE(fingerprint) 由 compute_fingerprint 入参含 source 保证 fallback 跨源安全
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_fix_events_fingerprint_unique"
down_revision: str | Sequence[str] | None = "0002_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """替换 events 表 UNIQUE 约束为 UNIQUE(fingerprint) 全局唯一.

    对所有 DB 状态幂等:
        - 旧库 (4 字段 UNIQUE) → 重建 + 升级到 UNIQUE(fingerprint)
        - 新库 (D4.3.1 改后已 UNIQUE(fingerprint)) → 1:1 复制, 等价 no-op
        - 已有重复 fingerprint 行 → INSERT OR IGNORE 保留最早一行

    副作用: 重建表会让 SQLAlchemy 重新读 schema, alembic_version 保持 0003
    """
    # 1) 建临时表(目标 schema — UNIQUE(fingerprint))
    op.execute("""
        CREATE TABLE events_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event           TEXT    NOT NULL,
            status          TEXT    NOT NULL,
            source          TEXT    NOT NULL DEFAULT '',
            subject_id      TEXT,
            fingerprint     TEXT    NOT NULL DEFAULT '',
            event_metadata  TEXT    NOT NULL DEFAULT '{}',
            created_at      INTEGER NOT NULL,
            UNIQUE(fingerprint)
        )
        """)
    # 2) 拷数据: INSERT OR IGNORE 防御旧库已存在的重复行(subject_id=NULL + 同 fingerprint)
    #    UNIQUE(fingerprint) 冲突时保留最早插入的(id 最小), 后续重复行被忽略
    op.execute("""
        INSERT OR IGNORE INTO events_new
            (id, event, status, source, subject_id, fingerprint, event_metadata, created_at)
        SELECT id, event, status, source, subject_id, fingerprint, event_metadata, created_at
        FROM events
        """)
    # 3) 删旧表
    op.execute("DROP TABLE events")
    # 4) 改名
    op.execute("ALTER TABLE events_new RENAME TO events")
    # 5) 重建全部 6 索引 (与 0002_events 一致)
    op.execute("CREATE INDEX idx_events_created_at ON events(created_at DESC)")
    op.execute("CREATE INDEX idx_events_event ON events(event)")
    op.execute("CREATE INDEX idx_events_status ON events(status)")
    op.execute("CREATE INDEX idx_events_source ON events(source)")
    op.execute("CREATE INDEX idx_events_subject_id ON events(subject_id)")
    op.execute("CREATE INDEX idx_events_fingerprint ON events(fingerprint)")


def downgrade() -> None:
    """回滚: 把 UNIQUE(fingerprint) 换回 4 字段 UNIQUE(event, source, subject_id, fingerprint).

    注意: 如果升级时已用 INSERT OR IGNORE 合并过重复行, 这次 downgrade 不会恢复
    被合并的数据(有损). 这是用户主动选择回滚的代价.
    """
    # 1) 建临时表(回滚目标 schema)
    op.execute("""
        CREATE TABLE events_old (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event           TEXT    NOT NULL,
            status          TEXT    NOT NULL,
            source          TEXT    NOT NULL DEFAULT '',
            subject_id      TEXT,
            fingerprint     TEXT    NOT NULL DEFAULT '',
            event_metadata  TEXT    NOT NULL DEFAULT '{}',
            created_at      INTEGER NOT NULL,
            UNIQUE(event, source, subject_id, fingerprint)
        )
        """)
    # 2) 拷数据(不回填已被合并的重复行)
    op.execute("""
        INSERT INTO events_old
            (id, event, status, source, subject_id, fingerprint, event_metadata, created_at)
        SELECT id, event, status, source, subject_id, fingerprint, event_metadata, created_at
        FROM events
        """)
    # 3) 删旧表 + 改名
    op.execute("DROP TABLE events")
    op.execute("ALTER TABLE events_old RENAME TO events")
    # 4) 重建 6 索引
    op.execute("CREATE INDEX idx_events_created_at ON events(created_at DESC)")
    op.execute("CREATE INDEX idx_events_event ON events(event)")
    op.execute("CREATE INDEX idx_events_status ON events(status)")
    op.execute("CREATE INDEX idx_events_source ON events(source)")
    op.execute("CREATE INDEX idx_events_subject_id ON events(subject_id)")
    op.execute("CREATE INDEX idx_events_fingerprint ON events(fingerprint)")
