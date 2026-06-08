"""D4.4 — TaskPacket (g006 §"Typed task packet schema" 8 必含字段契约).

参考 g006-task-policy-board-verification-map.md:
  TaskPacket 8 必含字段:
    1. objective          — str (目标描述)
    2. scope              — list[str] (范围: 模块/文件/子系统)
    3. resources          — list[str] (资源依赖: MCP server / DB 表 / 文件)
    4. acceptance_criteria — list[str] (验收标准: pass/fail 标准)
    5. model              — str (model full_id, capability registry 键)
    6. provider           — str (provider name, e.g. 'minimax' / 'openai_compat')
    7. permission_profile — str (权限配置: 'read_only' / 'read_write' / 'admin')
    8. recovery_policy    — str (恢复策略: 'none' / 'retry_on_transient' / 'manual')

设计:
  - 8 字段 dataclass + field(default=...) 支持旧 JSON 缺字段(serde(default) 模式, g006 强调)
  - TaskPacketBuilder 链式构造
  - to_dict / from_dict JSON 双向(向后兼容, 缺字段 → defaults, 旧字段忽略)
  - assert_packet_contract() 8 字段不变量校验

D3.3.3 教训应用:
  - 编程错误透传: ValueError/TypeError 不包装
  - 业务错误窄化: PolicyContractError 包裹 8 字段校验失败
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Any

from my_ai_employee.policy.exceptions import PolicyContractError

# ===== 枚举 (typed values, 业务友好) =====


class RecoveryPolicy(enum.StrEnum):
    """恢复策略 (g006 §"recovery_policy" 字段).

    NONE:               — 不重试不升级
    RETRY_ON_TRANSIENT: — 仅当 last_error_recoverable=True 时重试
    MANUAL:             — 任何错误需人工审批,不自动重试
    """

    NONE = "none"
    RETRY_ON_TRANSIENT = "retry_on_transient"
    MANUAL = "manual"


class PermissionProfile(enum.StrEnum):
    """权限配置 (g006 §"permission_profile" 字段).

    READ_ONLY:   — 只读(查 DB / 读文件 / 调 LLM)
    READ_WRITE:  — 读写(写文件 / 调 draft API / 发邮件)
    ADMIN:       — 高级(改用户配置 / 调系统管理 API)
    """

    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    ADMIN = "admin"


# ===== 8 必含字段 dataclass =====


@dataclass
class TaskPacket:
    """TaskPacket — g006 8 必含字段 (backwards compat via defaults).

    所有 8 字段都有 default, 支持:
      1. 旧 JSON 缺字段 → TaskPacket.from_dict(old_json) 仍能成功
      2. 构造时只填部分字段, 后续 update
      3. Builder 模式链式填

    注: 默认 objective="" 视为"未填", assert_packet_contract 会拒绝.
    """

    # 8 必含字段
    objective: str = ""
    scope: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    permission_profile: str = PermissionProfile.READ_ONLY.value
    recovery_policy: str = RecoveryPolicy.NONE.value

    # ===== JSON 双向 =====

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(便于 JSON 化)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskPacket:
        """从 dict 反序列化(向后兼容: 缺字段 → defaults, 旧字段忽略).

        Args:
            data: dict(可能含部分 8 字段 + 旧字段 + extra 业务字段)

        Returns:
            TaskPacket 实例

        Raises:
            PolicyContractError: data 不是 dict
        """
        if not isinstance(data, dict):
            raise PolicyContractError(f"data 必须是 dict, 实际 {type(data).__name__}")
        # 只取 8 字段(其他字段忽略, extra 业务字段不引入)
        return cls(
            objective=data.get("objective", ""),
            scope=list(data.get("scope", []) or []),
            resources=list(data.get("resources", []) or []),
            acceptance_criteria=list(data.get("acceptance_criteria", []) or []),
            model=data.get("model", ""),
            provider=data.get("provider", ""),
            permission_profile=data.get("permission_profile", PermissionProfile.READ_ONLY.value),
            recovery_policy=data.get("recovery_policy", RecoveryPolicy.NONE.value),
        )


# ===== 8 字段不变量校验 =====


def assert_packet_contract(packet: TaskPacket) -> None:
    """校验 TaskPacket 满足 g006 8 必含字段不变量.

    校验规则:
      - objective 必填非空(str)
      - scope 必填非空 list(≥1 项)
      - resources 必填 list(可空, 表示无外部依赖)
      - acceptance_criteria 必填非空 list(≥1 项, 没有 AC = 没有 pass 标准)
      - model 必填非空(str)
      - provider 必填非空(str)
      - permission_profile 必填(str, 合法枚举值)
      - recovery_policy 必填(str, 合法枚举值)

    Raises:
        PolicyContractError: 任一字段不满足
        ValueError: 编程错误(传 None / 错类型, 透传)
    """
    if not isinstance(packet, TaskPacket):
        raise PolicyContractError(f"packet 必须是 TaskPacket, 实际 {type(packet).__name__}")
    if not isinstance(packet.objective, str):
        raise PolicyContractError(f"objective 必须是 str, 实际 {type(packet.objective).__name__}")
    if not packet.objective:
        raise PolicyContractError("objective 必填非空")
    if not isinstance(packet.scope, list):
        raise PolicyContractError(f"scope 必须是 list, 实际 {type(packet.scope).__name__}")
    if not packet.scope:
        raise PolicyContractError("scope 必填非空(至少 1 项)")
    if not isinstance(packet.resources, list):
        raise PolicyContractError(f"resources 必须是 list, 实际 {type(packet.resources).__name__}")
    if not isinstance(packet.acceptance_criteria, list):
        raise PolicyContractError(
            f"acceptance_criteria 必须是 list, 实际 {type(packet.acceptance_criteria).__name__}"
        )
    if not packet.acceptance_criteria:
        raise PolicyContractError("acceptance_criteria 必填非空(至少 1 项, 否则没有 pass 标准)")
    if not isinstance(packet.model, str):
        raise PolicyContractError(f"model 必须是 str, 实际 {type(packet.model).__name__}")
    if not packet.model:
        raise PolicyContractError("model 必填非空")
    if not isinstance(packet.provider, str):
        raise PolicyContractError(f"provider 必须是 str, 实际 {type(packet.provider).__name__}")
    if not packet.provider:
        raise PolicyContractError("provider 必填非空")
    if not isinstance(packet.permission_profile, str):
        raise PolicyContractError(
            f"permission_profile 必须是 str, 实际 {type(packet.permission_profile).__name__}"
        )
    valid_perms = {p.value for p in PermissionProfile}
    if packet.permission_profile not in valid_perms:
        raise PolicyContractError(
            f"permission_profile 非法: {packet.permission_profile!r} 不在 {valid_perms}"
        )
    if not isinstance(packet.recovery_policy, str):
        raise PolicyContractError(
            f"recovery_policy 必须是 str, 实际 {type(packet.recovery_policy).__name__}"
        )
    valid_recovery = {p.value for p in RecoveryPolicy}
    if packet.recovery_policy not in valid_recovery:
        raise PolicyContractError(
            f"recovery_policy 非法: {packet.recovery_policy!r} 不在 {valid_recovery}"
        )


# ===== Builder 模式 =====


class TaskPacketBuilder:
    """TaskPacket 链式构造器(D4.4 业务代码用, 避免一次传 8 个参数).

    Usage:
        packet = (
            TaskPacketBuilder()
            .with_objective("D4.5 邮件分类")
            .with_scope(["email/classifier.py"])
            .with_resources(["mcp:imap"])
            .with_acceptance_criteria(["precision ≥ 0.85"])
            .with_model("minimax/M3")
            .with_provider("minimax")
            .with_permission_profile(PermissionProfile.READ_WRITE)
            .with_recovery_policy(RecoveryPolicy.RETRY_ON_TRANSIENT)
            .build()
        )
    """

    def __init__(self) -> None:
        self._packet = TaskPacket()

    def with_objective(self, objective: str) -> TaskPacketBuilder:
        self._packet.objective = objective
        return self

    def with_scope(self, scope: list[str]) -> TaskPacketBuilder:
        self._packet.scope = list(scope)
        return self

    def with_resources(self, resources: list[str]) -> TaskPacketBuilder:
        self._packet.resources = list(resources)
        return self

    def with_acceptance_criteria(self, criteria: list[str]) -> TaskPacketBuilder:
        self._packet.acceptance_criteria = list(criteria)
        return self

    def with_model(self, model: str) -> TaskPacketBuilder:
        self._packet.model = model
        return self

    def with_provider(self, provider: str) -> TaskPacketBuilder:
        self._packet.provider = provider
        return self

    def with_permission_profile(self, profile: PermissionProfile | str) -> TaskPacketBuilder:
        if isinstance(profile, PermissionProfile):
            self._packet.permission_profile = profile.value
        else:
            self._packet.permission_profile = profile
        return self

    def with_recovery_policy(self, policy: RecoveryPolicy | str) -> TaskPacketBuilder:
        if isinstance(policy, RecoveryPolicy):
            self._packet.recovery_policy = policy.value
        else:
            self._packet.recovery_policy = policy
        return self

    def build(self) -> TaskPacket:
        """构造 TaskPacket(不调 assert_packet_contract — caller 决定何时校验)."""
        return self._packet


# ===== 模块导出 =====


__all__ = [
    "TaskPacket",
    "TaskPacketBuilder",
    "RecoveryPolicy",
    "PermissionProfile",
    "assert_packet_contract",
]
