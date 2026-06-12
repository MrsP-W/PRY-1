"""D5.2 迁移 — outbox 状态机扩值(SENDING + FAILED) + 显式白名单。

Revision ID: 0005_outbox_sending_state
Revises: 0004_outbox_table
Create Date: 2026-06-12

承接 D4.8 v1.0.1(commit `2e48179`,outbox 表 11 字段 + UNIQUE + 2 索引 + 2 FK)
+ D5.1 SMTP transport + Keychain(commit `cce567a`)
+ D5.1-fix transport 边界 + CLI provider 严判(commit `18284fa`)
+ D5 启动方向纠正(commit `b0943ff`,CalDAV/菜单栏/launchd 顺延 D6+)

**本迁移设计**:无 DDL 改动,只做业务层契约升级。
  - DDL 层面:outbox 表结构与索引全部沿用 0004,SQLite TEXT 列存枚举字面量,
    业务层 StrEnum 扩值不需要 schema 改动
  - 业务层:OutboxStatus 从 4 状态扩为 6 状态(加 SENDING + FAILED)
  - 业务层:新增 ALLOWED_TRANSITIONS 显式状态机白名单
  - 业务层:新增 OutboxIllegalTransitionError 异常类
  - 业务层:update_status(*, from_status) 必传 from_status + 白名单严判

状态机白名单(6 状态,3 路径):
    PENDING_SEND → {SENDING, APPROVED, FAILED, CANCELLED}
    APPROVED     → {SENDING, FAILED, CANCELLED}
    SENDING      → {SENT, FAILED}
    SENT         → {}    (终态)
    FAILED       → {PENDING_SEND, CANCELLED}  # 重试回 PENDING_SEND
    CANCELLED    → {}    (终态)

D5.2 vs D5 启动计划文档偏差(重要!):
    - D5 启动计划文档: PENDING_SEND → {SENDING, FAILED, CANCELLED}(3 个目标)
    - D5.2 实际白名单: PENDING_SEND → {SENDING, APPROVED, FAILED, CANCELLED}(4 个目标)
    - 偏差原因: D4.8 v1.0.1 锁定时已有 test_update_status_pending_to_approved
      契约测试(D4.8 L498-509),D5.2 必须保留 APPROVED 作为 PENDING_SEND 合法目标
      以维护 D4.8 已有契约(代码向后兼容)
    - 决策: 沿 D4.8 已有契约,在白名单中保留 APPROVED;D5 业务调度器可走
      快路径(PENDING_SEND → SENDING)或显式批准路径(PENDING_SEND → APPROVED → SENDING)
    - 报告: 在 D5.2 业务调度器报告 / 跨项目 memory 同步标注此决策偏差

3 路径业务语义:
    - 自动路径(快): PENDING_SEND → SENDING → SENT(D5 业务调度器直接消费 PENDING_SEND)
    - 显式批准路径: PENDING_SEND → APPROVED → SENDING → SENT(用户审阅通过后调度)
    - 重试路径:     PENDING_SEND → SENDING → FAILED → PENDING_SEND(指数退避后重试)
    - 取消路径:     任意状态 → CANCELLED(用户主动取消)

D3.2/D3.3 沿用约定:
    - render_as_batch=True 在 env.py 已配,本迁移无 DDL,空 upgrade/downgrade
    - D5.2 实际 DDL 改动量: 0(纯业务层 StrEnum + 状态机白名单)

教训应用(沿 D4.7.3 v1.0.6 25 教训):
    - P1-1 跨字段校验: update_status(*, from_status) 调用方必传 from_status,Store 层
      严判 from_status == row.status(防 concurrent 写导致状态机漂移)
    - P1-2 双向强一致: 状态机白名单 6 状态 × 各自目标集完整(无遗漏,无冗余)
    - P2-1 type 严判: _normalize_status 严判 type() is str + in frozenset
    - P2-2 异常范围窄化(D3.3.3): OutboxIllegalTransitionError 不接基类,
      由调用方(后续 D5.3 EmailSendAdapter)按业务语义区分业务阻断 vs 技术失败
    - 固化哲学: 代码 + 测试 + 文档 1:1 对齐(本迁移 + db/outbox.py 改 + 新 tests
      同步 commit,避免"代码改 / 文档延后")
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0005_outbox_sending_state"
down_revision: str | Sequence[str] | None = "0004_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== 无 DDL 改动 =====
    # 本迁移为"业务层契约升级" — outbox 表结构与索引全部沿用 0004_outbox_table migration,
    # SQLite TEXT 列存枚举字面量,业务层 StrEnum 扩值(SENDING + FAILED)不需要 schema 改动。
    #
    # 业务层实际改动在以下文件(本迁移 commit 一并入库):
    #   - src/my_ai_employee/core/outbox.py: OutboxStatus 4→6 状态 + ALLOWED_TRANSITIONS
    #   - src/my_ai_employee/db/outbox.py: OutboxIllegalTransitionError + update_status 严判
    #   - tests/db/test_outbox_status_transitions.py: +18 cases 状态机白名单严判测试
    #
    # alembic 规范:无 DDL 时 upgrade()/downgrade() 用 pass(明确表示"已审查,无 schema 改动")
    pass


def downgrade() -> None:
    # ===== 倒序无 DDL 改动 =====
    # down_revision = 0004_outbox_table 业务层 4 状态版本
    # 业务层 OutboxStatus 与 ALLOWED_TRANSITIONS 仍由 db/outbox.py 持有,
    # 实际"回滚"等于代码 git revert(alembic 不持有 StrEnum 状态)
    pass
