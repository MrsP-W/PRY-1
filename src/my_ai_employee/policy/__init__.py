"""D4.4 — 任务策略板 (Task Policy Board).

参考: claw-code `g006-task-policy-board-verification-map.md`

D4.4 范围:
    - TaskPacket (8 必含字段契约 + JSON 双向 + 向后兼容)
    - PolicyEngine (6 决策可执行规则 + PolicyEvaluation + events 表落地)
    - LaneBoard (3 lanes + LaneEntry + LaneFreshness + status JSON)
    - Heartbeat (3 状态: healthy / stalled / transport_dead)
    - 5 类业务异常窄化 (D3.3.3 教训应用): PolicyContractError /
      PolicyDecisionError / PolicyApprovalError / PolicyHeartbeatError /
      PolicyLaneError + PolicyError 基类

D4.4 集成 (D4.x 互操作):
    - D4.3 events/store.py: 复用 EventStore.insert() 落地 PolicyDecisionEvent
      (event_type: policy.decision.made / policy.decision.degraded)
    - D4.1 router.py: 决策输入(capability / fallback 状态 → 6 决策 context)
    - D4.2 mcp/discovery.py: 决策输入(required/optional/degraded report → RetryAvailable)
    - heartbeat.py: 提取 last_heartbeat_ms 喂给 StaleCleanupRequired rule

D4.4 已知限制 (D4.4.1+ 复检 P 项):
    - 6 决策是"声明式评估", 实际执行(retry/rebase/merge) 留给 caller
    - LaneBoard 是 in-memory 状态, 不持久化(若需跨进程看 → D4.4.1 落 events 表)
    - ApprovalToken 没有独立存储(approval_token_id 只是个字符串)

D4.4 不含:
    - 真实 LLM/MCP/分类业务调用 — D4.5+ 才用 PolicyEngine.evaluate() 真实 emit
    - CLI 集成(status JSON 导出接口已留 to_status_json(), CLI 留 D4.5+)
    - 任务调度器(何时 evaluate → 留 D4.4.1+ 任务调度板)

D4.6 业务层复用(D4.5 范本扩展 — EmailClassifierAdapter):
    - 复用 SyncPolicyAdapter 4 依赖可注入范本
    - EmailClassifier.classify() → 喂 PolicyEngine.evaluate
    - lane_entry_id 命名 "classify:<source>:<run_id>"
    - 业务层调用方显式注入 event_store / engine

注: audit_log 表 (D3 sync 审计) 与 PolicyDecisionEvent (events 表) 职责正交, 互不替代.
"""

from __future__ import annotations

from my_ai_employee.policy.exceptions import (
    PolicyApprovalError,
    PolicyContractError,
    PolicyDecisionError,
    PolicyError,
    PolicyHeartbeatError,
    PolicyLaneError,
    SMTPSendIllegalTransitionError,
    SMTPSendRecipientsRefusedError,
    SMTPSendSenderRefusedError,
    SMTPSendTransportError,
)
from my_ai_employee.policy.heartbeat import Heartbeat, Liveness
from my_ai_employee.policy.integration import (
    ClassifyDecisionReport,
    ClassifyFailureDecisionReport,
    DraftBlockedDecisionReport,
    DraftDecisionReport,
    DraftFailureDecisionReport,
    EmailClassifierAdapter,
    EmailDrafterAdapter,
    EmailReviewerAdapter,
    ReviewBlockedDecisionReport,
    ReviewDecisionReport,
    ReviewFailureDecisionReport,
    SyncDecisionReport,
    SyncPolicyAdapter,
    build_classify_failure_packet,
    build_classify_packet,
    build_classify_policy_context,
    build_draft_blocked_packet,
    build_draft_failure_packet,
    build_draft_packet,
    build_draft_policy_context,
    build_imap_sync_packet,
    build_review_blocked_packet,
    build_review_failure_packet,
    build_review_packet,
    build_review_policy_context,
    build_sync_policy_context,
    compute_acceptance_results,
    compute_classification_acceptance,
    compute_draft_acceptance,
    compute_review_acceptance,
)
from my_ai_employee.policy.lane_board import (
    LaneBoard,
    LaneEntry,
    LaneFreshness,
    LaneStatus,
)

# D4.8 业务层接入(草稿入库,6/11 晚间启动)
# 独立模块 outbox_adapter.py(避免 integration.py 4125 行膨胀)
# 字段含义常量 OUTBOX_BLOCK_REASON_VALUES 留在 outbox_adapter.py(非导出)
from my_ai_employee.policy.outbox_adapter import (
    EmailOutboxAdapter,
    OutboxBlockedDecisionReport,
    OutboxDecisionReport,
    OutboxFailureDecisionReport,
    build_outbox_blocked_packet,
    build_outbox_failure_packet,
    build_outbox_packet,
    build_outbox_policy_context,
    compute_outbox_acceptance,
)
from my_ai_employee.policy.policy_engine import (
    PolicyDecision,
    PolicyDecisionKind,
    PolicyEngine,
    PolicyEvaluation,
    get_engine,
)
from my_ai_employee.policy.send_adapter import (
    EmailSendAdapter,
    SendBlockedDecisionReport,
    SendDecisionReport,
    SendFailureDecisionReport,
    build_send_blocked_packet,
    build_send_failure_packet,
    build_send_packet,
    build_send_policy_context,
    compute_send_acceptance,
)
from my_ai_employee.policy.task_packet import (
    PermissionProfile,
    RecoveryPolicy,
    TaskPacket,
    TaskPacketBuilder,
    assert_packet_contract,
)

__all__ = [
    # 异常
    "PolicyError",
    "PolicyContractError",
    "PolicyDecisionError",
    "PolicyApprovalError",
    "PolicyHeartbeatError",
    "PolicyLaneError",
    # TaskPacket
    "TaskPacket",
    "TaskPacketBuilder",
    "RecoveryPolicy",
    "PermissionProfile",
    "assert_packet_contract",
    # PolicyEngine
    "PolicyDecision",
    "PolicyDecisionKind",
    "PolicyEvaluation",
    "PolicyEngine",
    "get_engine",
    # LaneBoard
    "LaneBoard",
    "LaneEntry",
    "LaneStatus",
    "LaneFreshness",
    # Heartbeat
    "Heartbeat",
    "Liveness",
    # D4.5 业务层接入
    "SyncPolicyAdapter",
    "SyncDecisionReport",
    "build_imap_sync_packet",
    "build_sync_policy_context",
    "compute_acceptance_results",
    # D4.6 业务层接入(邮件分类)
    "EmailClassifierAdapter",
    "ClassifyDecisionReport",
    "ClassifyFailureDecisionReport",
    "build_classify_packet",
    "build_classify_failure_packet",
    "build_classify_policy_context",
    "compute_classification_acceptance",
    # D4.7.3 业务层接入(邮件草稿, 6/10 起始)
    "EmailDrafterAdapter",
    "DraftDecisionReport",
    "DraftBlockedDecisionReport",
    "build_draft_packet",
    "build_draft_blocked_packet",
    "build_draft_policy_context",
    "compute_draft_acceptance",
    # D4.7.3 v1.0.2 P1-1 新增: 技术失败独立 packet + 独立 report
    "build_draft_failure_packet",
    "DraftFailureDecisionReport",
    # D4.7.4 业务层接入(邮件审阅, 6/11 启动)
    # 沿用 D4.7.3 三入口架构(成功 / 业务阻断 / 技术失败), 4 类阻断白名单
    "EmailReviewerAdapter",
    "ReviewDecisionReport",
    "ReviewBlockedDecisionReport",
    "ReviewFailureDecisionReport",
    "build_review_packet",
    "build_review_blocked_packet",
    "build_review_failure_packet",
    "build_review_policy_context",
    "compute_review_acceptance",
    # D4.8 业务层接入(草稿入库, 6/11 晚间启动)
    # 沿用 D4.7.4 三入口架构, 5 依赖可注入(新增 outbox_store)
    # PermissionProfile = READ_WRITE(D4.8 首次引入, 写库需要)
    "EmailOutboxAdapter",
    "OutboxDecisionReport",
    "OutboxBlockedDecisionReport",
    "OutboxFailureDecisionReport",
    "build_outbox_packet",
    "build_outbox_blocked_packet",
    "build_outbox_failure_packet",
    "build_outbox_policy_context",
    "compute_outbox_acceptance",
    # D5.3 业务层接入(SMTP 真实发送, 6/12 启动)
    # 沿用 D4.7.3 三入口架构(成功 / 业务阻断 / 技术失败)
    # 4 类 SMTP 异常(异常窄化 D3.3.3 范本)
    "SMTPSendRecipientsRefusedError",
    "SMTPSendSenderRefusedError",
    "SMTPSendTransportError",
    "SMTPSendIllegalTransitionError",
    "EmailSendAdapter",
    "SendDecisionReport",
    "SendBlockedDecisionReport",
    "SendFailureDecisionReport",
    "build_send_packet",
    "build_send_blocked_packet",
    "build_send_failure_packet",
    "build_send_policy_context",
    "compute_send_acceptance",
]
