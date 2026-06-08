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
)
from my_ai_employee.policy.heartbeat import Heartbeat, Liveness
from my_ai_employee.policy.integration import (
    SyncDecisionReport,
    SyncPolicyAdapter,
    build_imap_sync_packet,
    build_sync_policy_context,
    compute_acceptance_results,
)
from my_ai_employee.policy.lane_board import (
    LaneBoard,
    LaneEntry,
    LaneFreshness,
    LaneStatus,
)
from my_ai_employee.policy.policy_engine import (
    PolicyDecision,
    PolicyDecisionKind,
    PolicyEngine,
    PolicyEvaluation,
    get_engine,
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
]
