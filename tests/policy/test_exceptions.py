"""D4.4 — 5 类 Policy 业务异常 + PolicyError 基类测试.

覆盖:
  - 5 子类均继承 PolicyError(不是 Exception 兜底)
  - 5 子类均继承 Exception(可 raise + except)
  - 5 子类彼此不同(isinstance 互不成立)
  - raise / catch 路径正常
  - 错误信息保留(D3.3.3 教训: 信息不能丢)
  - PolicyError 适合作为 5 子类"多 except" 的 catch-all
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.policy import (  # noqa: E402
    PolicyApprovalError,
    PolicyContractError,
    PolicyDecisionError,
    PolicyError,
    PolicyHeartbeatError,
    PolicyLaneError,
)


class TestExceptionHierarchy:
    """5 子类 + 基类层级校验."""

    def test_policy_error_is_exception(self) -> None:
        """PolicyError 继承 Exception(可正常 raise)."""
        assert issubclass(PolicyError, Exception)

    def test_all_5_subclasses_inherit_policy_error(self) -> None:
        """5 子类全部继承 PolicyError."""
        for cls in (
            PolicyContractError,
            PolicyDecisionError,
            PolicyApprovalError,
            PolicyHeartbeatError,
            PolicyLaneError,
        ):
            assert issubclass(cls, PolicyError), f"{cls.__name__} 必须继承 PolicyError"

    def test_subclasses_are_distinct(self) -> None:
        """5 子类彼此不同(每个类对应一类业务错误)."""
        classes = (
            PolicyContractError,
            PolicyDecisionError,
            PolicyApprovalError,
            PolicyHeartbeatError,
            PolicyLaneError,
        )
        for i, c1 in enumerate(classes):
            for j, c2 in enumerate(classes):
                if i == j:
                    continue
                assert not issubclass(c1, c2), f"{c1.__name__} 不应继承 {c2.__name__}"

    def test_subclasses_count_is_5(self) -> None:
        """PolicyError 直属子类正好 5 个(D4.4 范围锁定, 防意外扩展)."""
        direct_subclasses = PolicyError.__subclasses__()
        assert len(direct_subclasses) == 5
        names = {c.__name__ for c in direct_subclasses}
        assert names == {
            "PolicyContractError",
            "PolicyDecisionError",
            "PolicyApprovalError",
            "PolicyHeartbeatError",
            "PolicyLaneError",
        }


class TestRaiseAndCatch:
    """raise + except 路径."""

    def test_can_raise_and_catch_policy_error(self) -> None:
        """PolicyError 可 raise, 可 except."""
        with pytest.raises(PolicyError, match="基类测试"):
            raise PolicyError("基类测试")

    def test_can_catch_subclass_via_policy_error(self) -> None:
        """子类异常可用 PolicyError 兜底 catch(便于 caller 多 except 合并)."""
        with pytest.raises(PolicyError):
            raise PolicyContractError("TaskPacket 缺 objective")

    def test_subclass_specific_catch_works(self) -> None:
        """子类自身可独立 except(细粒度处理)."""
        with pytest.raises(PolicyLaneError):
            raise PolicyLaneError("FINISHED 是终态")

    def test_specific_catch_does_not_catch_sibling(self) -> None:
        """一个子类的 except 不接兄弟子类(避免误吞).

        验证: PolicyContractError 不会被 PolicyLaneError 接住,
        会作为 PolicyError 透传出去(兄弟子类互不 catch).
        """
        with pytest.raises(PolicyContractError, match="contract 错"):
            try:
                raise PolicyContractError("contract 错")
            except PolicyLaneError:
                pytest.fail("PolicyLaneError 不应接住 PolicyContractError")

    def test_error_message_preserved(self) -> None:
        """错误信息不丢(D3.3.3 教训)."""
        try:
            raise PolicyApprovalError("approval_token_id 缺失")
        except PolicyError as e:
            assert "approval_token_id 缺失" in str(e)


class TestImportPath:
    """5 子类均能从 my_ai_employee.policy 顶层导入(D4.4 公共 API 锁定)."""

    def test_all_importable_from_policy_top_level(self) -> None:
        from my_ai_employee import policy

        symbols = (
            "PolicyError",
            "PolicyContractError",
            "PolicyDecisionError",
            "PolicyApprovalError",
            "PolicyHeartbeatError",
            "PolicyLaneError",
        )
        for name in symbols:
            assert hasattr(policy, name), f"my_ai_employee.policy 缺 {name}"
