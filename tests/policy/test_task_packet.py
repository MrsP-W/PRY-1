"""D4.4 — TaskPacket 8 必含字段契约 + JSON 双向 + 向后兼容 + Builder 测试.

覆盖:
  - 8 必含字段默认值(全 field(default=...), 构造空 TaskPacket 成功)
  - TaskPacketBuilder 链式构造 + 接受 enum 或 str
  - to_dict / from_dict JSON 双向(8 字段全 roundtrip)
  - from_dict 向后兼容: 缺字段 → defaults
  - from_dict 容忍旧字段(忽略未知 key)
  - from_dict 拒绝非 dict 输入 → PolicyContractError
  - assert_packet_contract: 8 字段不变量校验
  - 编程错误透传: ValueError/TypeError 不包装
  - 业务错误窄化: PolicyContractError(继承 PolicyError)
  - 枚举值校验: permission_profile / recovery_policy 非法值被拒
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.policy import (  # noqa: E402
    PermissionProfile,
    PolicyContractError,
    PolicyError,
    RecoveryPolicy,
    TaskPacket,
    TaskPacketBuilder,
    assert_packet_contract,
)

# ===== TaskPacket 默认值 =====


class TestDefaults:
    """8 必含字段全 default, 空 TaskPacket 构造成功."""

    def test_empty_packet_constructs(self) -> None:
        """空 TaskPacket() 成功(全部走 defaults)."""
        p = TaskPacket()
        assert p.objective == ""
        assert p.scope == []
        assert p.resources == []
        assert p.acceptance_criteria == []
        assert p.model == ""
        assert p.provider == ""
        assert p.permission_profile == PermissionProfile.READ_ONLY.value
        assert p.recovery_policy == RecoveryPolicy.NONE.value

    def test_empty_packet_fails_contract(self) -> None:
        """空 packet 不通过 assert_packet_contract(objective 必填非空)."""
        with pytest.raises(PolicyContractError, match="objective 必填非空"):
            assert_packet_contract(TaskPacket())


# ===== TaskPacketBuilder =====


class TestBuilder:
    """链式构造 + 接受 enum 或 str."""

    def test_builder_minimal_valid(self) -> None:
        """Builder 只填 3 个必填字段(objective/scope/AC), 仍构造成功."""
        p = (
            TaskPacketBuilder()
            .with_objective("test")
            .with_scope(["x/"])
            .with_acceptance_criteria(["pass"])
            .build()
        )
        assert p.objective == "test"
        assert p.scope == ["x/"]
        assert p.acceptance_criteria == ["pass"]
        # 其他字段走 defaults
        assert p.resources == []
        assert p.model == ""
        assert p.provider == ""

    def test_builder_with_enum_values(self) -> None:
        """Builder 接受 PermissionProfile/RecoveryPolicy enum."""
        p = (
            TaskPacketBuilder()
            .with_objective("test")
            .with_scope(["x/"])
            .with_acceptance_criteria(["pass"])
            .with_permission_profile(PermissionProfile.ADMIN)
            .with_recovery_policy(RecoveryPolicy.MANUAL)
            .build()
        )
        assert p.permission_profile == "admin"
        assert p.recovery_policy == "manual"

    def test_builder_with_str_values(self) -> None:
        """Builder 接受 str 值(与 enum 等价)."""
        p = (
            TaskPacketBuilder()
            .with_objective("test")
            .with_scope(["x/"])
            .with_acceptance_criteria(["pass"])
            .with_permission_profile("read_write")
            .with_recovery_policy("retry_on_transient")
            .build()
        )
        assert p.permission_profile == "read_write"
        assert p.recovery_policy == "retry_on_transient"

    def test_builder_returns_self_for_chaining(self) -> None:
        """Builder 每个 with_* 返回 self(链式)."""
        b = TaskPacketBuilder()
        assert b.with_objective("x") is b
        assert b.with_scope(["y"]) is b

    def test_builder_does_not_validate(self) -> None:
        """Builder.build() 不调 assert_packet_contract — 由 caller 决定何时校验."""
        # 不填任何字段, build() 仍成功
        p = TaskPacketBuilder().build()
        assert isinstance(p, TaskPacket)


# ===== JSON 双向 =====


class TestJsonRoundtrip:
    """to_dict / from_dict 双向."""

    def test_to_dict_returns_8_fields(self) -> None:
        """to_dict 返回 8 字段全 key."""
        p = TaskPacket(
            objective="x",
            scope=["a/"],
            resources=["b"],
            acceptance_criteria=["c"],
            model="m",
            provider="p",
            permission_profile="read_write",
            recovery_policy="retry_on_transient",
        )
        d = p.to_dict()
        assert d["objective"] == "x"
        assert d["scope"] == ["a/"]
        assert d["resources"] == ["b"]
        assert d["acceptance_criteria"] == ["c"]
        assert d["model"] == "m"
        assert d["provider"] == "p"
        assert d["permission_profile"] == "read_write"
        assert d["recovery_policy"] == "retry_on_transient"

    def test_from_dict_roundtrip(self) -> None:
        """to_dict → from_dict → to_dict 应等价."""
        p1 = TaskPacket(
            objective="D4.4",
            scope=["policy/"],
            resources=["mcp:imap"],
            acceptance_criteria=["pytest passed"],
            model="minimax/M3",
            provider="minimax",
            permission_profile="read_write",
            recovery_policy="retry_on_transient",
        )
        p2 = TaskPacket.from_dict(p1.to_dict())
        assert p1.to_dict() == p2.to_dict()


# ===== 向后兼容 =====


class TestBackwardsCompat:
    """from_dict 容忍缺字段 + 旧字段."""

    def test_from_dict_missing_fields_uses_defaults(self) -> None:
        """缺字段 → defaults(关键 backwards compat)."""
        p = TaskPacket.from_dict({})
        assert p.objective == ""
        assert p.scope == []
        assert p.resources == []
        assert p.acceptance_criteria == []
        assert p.model == ""
        assert p.provider == ""
        assert p.permission_profile == PermissionProfile.READ_ONLY.value
        assert p.recovery_policy == RecoveryPolicy.NONE.value

    def test_from_dict_partial_dict(self) -> None:
        """只填部分字段也 OK."""
        p = TaskPacket.from_dict(
            {"objective": "x", "scope": ["a/"], "acceptance_criteria": ["pass"]}
        )
        assert p.objective == "x"
        assert p.scope == ["a/"]
        assert p.acceptance_criteria == ["pass"]
        assert p.model == ""

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """from_dict 忽略未知 key(旧字段 / 业务 extra 字段不引入)."""
        data = {
            "objective": "x",
            "scope": ["a/"],
            "acceptance_criteria": ["pass"],
            "unknown_old_field": "should_be_ignored",
            "another_legacy": 12345,
        }
        p = TaskPacket.from_dict(data)
        d = p.to_dict()
        assert "unknown_old_field" not in d
        assert "another_legacy" not in d

    def test_from_dict_normalizes_none_list_to_empty(self) -> None:
        """None 的 list 字段 → [] (data.get("scope", []) or [] 模式)."""
        p = TaskPacket.from_dict(
            {
                "objective": "x",
                "scope": None,
                "resources": None,
                "acceptance_criteria": None,
            }
        )
        assert p.scope == []
        assert p.resources == []
        assert p.acceptance_criteria == []

    def test_from_dict_rejects_non_dict(self) -> None:
        """非 dict 输入 → PolicyContractError."""
        with pytest.raises(PolicyContractError, match="data 必须是 dict"):
            TaskPacket.from_dict("not a dict")  # type: ignore[arg-type]


# ===== assert_packet_contract 8 字段不变量 =====


class TestContract:
    """8 必含字段不变量校验."""

    @pytest.fixture
    def valid_packet(self) -> TaskPacket:
        return TaskPacket(
            objective="test",
            scope=["x/"],
            resources=["y"],
            acceptance_criteria=["z"],
            model="m",
            provider="p",
        )

    def test_valid_packet_passes(self, valid_packet: TaskPacket) -> None:
        """全字段填合法值 → 通过."""
        assert_packet_contract(valid_packet)

    def test_empty_objective_fails(self, valid_packet: TaskPacket) -> None:
        """objective="" → 失败."""
        valid_packet.objective = ""
        with pytest.raises(PolicyContractError, match="objective 必填非空"):
            assert_packet_contract(valid_packet)

    def test_empty_scope_fails(self, valid_packet: TaskPacket) -> None:
        """scope=[] → 失败."""
        valid_packet.scope = []
        with pytest.raises(PolicyContractError, match="scope 必填非空"):
            assert_packet_contract(valid_packet)

    def test_empty_acceptance_criteria_fails(self, valid_packet: TaskPacket) -> None:
        """AC=[] → 失败(没标准 = 没 pass 路径)."""
        valid_packet.acceptance_criteria = []
        with pytest.raises(PolicyContractError, match="acceptance_criteria 必填非空"):
            assert_packet_contract(valid_packet)

    def test_empty_resources_allowed(self, valid_packet: TaskPacket) -> None:
        """resources=[] 允许(无外部依赖)."""
        valid_packet.resources = []
        assert_packet_contract(valid_packet)

    def test_empty_model_fails(self, valid_packet: TaskPacket) -> None:
        """model="" → 失败."""
        valid_packet.model = ""
        with pytest.raises(PolicyContractError, match="model 必填非空"):
            assert_packet_contract(valid_packet)

    def test_empty_provider_fails(self, valid_packet: TaskPacket) -> None:
        """provider="" → 失败."""
        valid_packet.provider = ""
        with pytest.raises(PolicyContractError, match="provider 必填非空"):
            assert_packet_contract(valid_packet)

    def test_invalid_permission_profile_fails(self, valid_packet: TaskPacket) -> None:
        """permission_profile 不在枚举 → 失败."""
        valid_packet.permission_profile = "super_admin"
        with pytest.raises(PolicyContractError, match="permission_profile 非法"):
            assert_packet_contract(valid_packet)

    def test_invalid_recovery_policy_fails(self, valid_packet: TaskPacket) -> None:
        """recovery_policy 不在枚举 → 失败."""
        valid_packet.recovery_policy = "auto_retry_forever"
        with pytest.raises(PolicyContractError, match="recovery_policy 非法"):
            assert_packet_contract(valid_packet)

    def test_all_3_permission_profiles_accepted(self, valid_packet: TaskPacket) -> None:
        """3 个合法 permission_profile 都通过."""
        for prof in PermissionProfile:
            valid_packet.permission_profile = prof.value
            assert_packet_contract(valid_packet)

    def test_all_3_recovery_policies_accepted(self, valid_packet: TaskPacket) -> None:
        """3 个合法 recovery_policy 都通过."""
        for rp in RecoveryPolicy:
            valid_packet.recovery_policy = rp.value
            assert_packet_contract(valid_packet)

    def test_non_taskpacket_input_fails(self) -> None:
        """非 TaskPacket 输入 → PolicyContractError."""
        with pytest.raises(PolicyContractError, match="packet 必须是 TaskPacket"):
            assert_packet_contract({"objective": "x"})  # type: ignore[arg-type]

    def test_contract_error_is_policy_error(self, valid_packet: TaskPacket) -> None:
        """PolicyContractError 继承 PolicyError(可被基类 catch)."""
        valid_packet.objective = ""
        with pytest.raises(PolicyError):
            assert_packet_contract(valid_packet)


# ===== 编程错误透传 =====


class TestProgrammingErrorsPropagate:
    """ValueError/TypeError (编程错误) 不被 PolicyContractError 包装."""

    def test_wrong_type_objective_propagates(self) -> None:
        """objective 不是 str → 编程错误(透传)."""
        p = TaskPacket(
            objective="x",
            scope=["y/"],
            acceptance_criteria=["z"],
        )
        p.objective = 123  # type: ignore[assignment]
        with pytest.raises(PolicyContractError, match="objective 必须是 str"):
            assert_packet_contract(p)

    def test_scope_not_list_fails(self) -> None:
        """scope 不是 list → PolicyContractError(业务错误, 非编程错误)."""
        p = TaskPacket(
            objective="x",
            scope="not a list",  # type: ignore[arg-type]
            acceptance_criteria=["z"],
        )
        with pytest.raises(PolicyContractError, match="scope 必须是 list"):
            assert_packet_contract(p)
