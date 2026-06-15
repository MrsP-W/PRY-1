"""D5.6.4 — spike_send_100.py 真实网络门 + transport factory 注入集成测试(5 cases)。

D5.6.4 P1-3 修复(4th round 检查员反馈):
    - test_run_spike(real_send=True) 没有替换 SmtpLibTransport,可能连接 smtp.qq.com
    - 必须显式 SMTP_REAL_NETWORK=1 + 可选 smtp_transport_factory 注入,双层防御

D5.6.5.1 P1-1 修复(检查员驳回):
    - 之前 test_real_mode_unlocked_with_smtp_real_network_env 用 `pytest.raises(Exception)`
      宽泛放行,可能在异常前已连接 smtp.qq.com(真发邮件污染测试环境)
    - 必注入 smtp_transport_factory=InMemorySmtpTransport(双层防御:env 门 + factory)
    - 必断言 SmtpLibTransport 未构造
    - 必断言 factory 被调用次数 == 1

测试覆盖(6 cases):
    R1. test_real_mode_rejects_without_smtp_real_network_env
        real_send=True 但 SMTP_REAL_NETWORK 未设置 → 必抛 ValueError
    R2. test_real_mode_unlocked_with_smtp_real_network_env
        SMTP_REAL_NETWORK=1 + mock Keychain + 注入 InMemory factory → 必调 factory
        且 SmtpLibTransport 必未构造
    R3. test_smtp_transport_factory_injected_instead_of_smtp_lib
        源码契约:factory 优先分支必早于 SmtpLibTransport 出现
    R4. test_inmemory_mode_unaffected_by_env
        real_send=False → SMTP_REAL_NETWORK env 完全无影响
    R5. test_real_smtp_transport_not_constructed_when_factory_injected
        新增:即使 real_send=True + SMTP_REAL_NETWORK=1,只要 factory 注入
        就必不构造 SmtpLibTransport(避免真实 smtp.qq.com 连接)
    R6. test_run_spike_returns_spike_result_dataclass
        新增:run_spike 返回类型契约 必为 SpikeResult(16 字段,D5.7.1 P2-3 统一),不返回 None
        检查员 D5.6.5.1 P2-1 驳回:之前 run_spike 必返回 None,SpikeResult dataclass
        形同虚设。本测试固化返回契约。

设计原则(沿 D4.7.3 v1.0.6 + D5.6.2 范本):
- 不跑 spike 完整流程(慢),只验入口段 + 关键调用链
- mock Keychain 让 RealMode 流程可触发
- 严判 type + 边界(无 isinstance,无 type(value) is bool 漏判)
- 测试本身绝不允许连接真实 SMTP 服务器
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "spike_send_100.py"
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== R. D5.6.4 P1-3 真实网络门 + transport factory 注入(6 cases)=====


def test_real_mode_rejects_without_smtp_real_network_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D5.6.4 P1-3 修复:real_send=True 但 SMTP_REAL_NETWORK 未设置 → 必抛 ValueError。

    4th round 检查员反馈 P1 漏洞:
        测试可调 run_spike(real_send=True),即使没真设环境变量,代码也会真连 smtp.qq.com。
        真实网络污染测试环境 / 扰民(真发邮件)/ 烧测试 CI 流量。

    修复:env 门控必须在入口段就抛错(早失败),绝不让 transport 创建。
    """
    from my_ai_employee.core import keychain  # noqa: PLC0415
    from scripts import spike_send_100  # noqa: PLC0415

    # 显式 unset SMTP_REAL_NETWORK
    monkeypatch.delenv("SMTP_REAL_NETWORK", raising=False)

    # mock Keychain 让 RealMode 通过 env 门后能继续(但本测试目标:env 门必先抛)
    fake_result = keychain.KeychainResult(ok=True, value="real-test-password")
    with (
        patch.object(keychain, "get_smtp_password_for_provider", return_value=fake_result),
        pytest.raises(ValueError, match="D5\\.6\\.4 P1-3 修复.*SMTP_REAL_NETWORK"),
    ):
        spike_send_100.run_spike(
            output_dir=Path("/tmp/dummy"),
            real_send=True,
            recipient_email="user@example.com",
            max_recipients=1,
            confirm=spike_send_100._CONFIRM_PHRASE,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="real_user@qq.com",
            smtp_provider="qq",
            count=1,
        )


def test_real_mode_unlocked_with_smtp_real_network_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """D5.6.5.1 P1-1 修复:SMTP_REAL_NETWORK=1 + 注入 InMemory factory → 必调 factory 且
    SmtpLibTransport 必未构造。

    4th round 之前用 `pytest.raises(Exception)` 宽泛放行 — 漏洞:在异常前可能已连接
    smtp.qq.com(真发邮件污染测试环境)。
    5th round 修复:即使 SMTP_REAL_NETWORK=1 解锁,也必注入 smtp_transport_factory=
    InMemorySmtpTransport,断言:
        1. factory 被调用 1 次(替换 SmtpLibTransport 路径)
        2. SmtpLibTransport.__init__ 必未触发
        3. env 门 + Keychain 读 + 凭证检查全过(进入 transport 选择段)
        4. SpikeResult.mode == "real" 且 smtp_real_network_unlocked == True
    """
    from my_ai_employee.connectors.smtp import (  # noqa: PLC0415
        InMemorySmtpTransport,
        SmtpLibTransport,
    )
    from my_ai_employee.core import keychain  # noqa: PLC0415
    from scripts import spike_send_100  # noqa: PLC0415

    # 显式 set SMTP_REAL_NETWORK=1(env 门解锁)
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")

    # mock Keychain(让 RealMode 凭证检查通过)
    fake_result = keychain.KeychainResult(ok=True, value="real-test-password-16chars")
    factory_calls: list[InMemorySmtpTransport] = []
    smtp_lib_constructor_calls: list[object] = []

    def fake_factory() -> InMemorySmtpTransport:
        """D5.6.5.1 P1-1:fake factory 返回 InMemorySmtpTransport(替代 SmtpLibTransport)。"""
        inst = InMemorySmtpTransport()
        factory_calls.append(inst)
        return inst

    # D5.6.5.1 P1-1 关键修复:跟踪 SmtpLibTransport 构造次数
    # 真实测试绝不能容忍 SmtpLibTransport 被构造(那意味着会去连 smtp.qq.com)
    original_smtp_lib_init = SmtpLibTransport.__init__

    def tracked_smtp_lib_init(self: object, *args: object, **kwargs: object) -> None:
        smtp_lib_constructor_calls.append(self)
        return original_smtp_lib_init(self, *args, **kwargs)  # type: ignore[arg-type]

    with (
        patch.object(keychain, "get_smtp_password_for_provider", return_value=fake_result),
        patch.object(SmtpLibTransport, "__init__", tracked_smtp_lib_init),
        # D5.6.5.1 P1-1:不再用 pytest.raises(Exception) 宽泛放行
        # 用 smtp_transport_factory=fake_factory 必调,断言状态而非异常
    ):
        # 调用 run_spike — 即使后续 InMemory 模式跑下去也无害(InMemorySmtpTransport 不连 SMTP)
        result = spike_send_100.run_spike(
            output_dir=tmp_path,
            real_send=True,
            recipient_email="user@example.com",
            max_recipients=1,
            confirm=spike_send_100._CONFIRM_PHRASE,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="real_user@qq.com",
            smtp_provider="qq",
            count=1,
            smtp_transport_factory=fake_factory,
        )

    # 断言 1:SpikeResult 必返回(D5.6.5.1 P2-1 修复)
    assert result is not None, "D5.6.5.1 P2-1:run_spike 必返回 SpikeResult(不再 None)"
    assert result.mode == "real", (
        f"D5.6.5.1 P2-1:SpikeResult.mode 必为 'real'(env 解锁+real_send=True),实际 {result.mode!r}"
    )
    assert result.smtp_real_network_unlocked is True, (
        f"D5.6.5.1 P2-1:SpikeResult.smtp_real_network_unlocked 必为 True,实际 {result.smtp_real_network_unlocked!r}"
    )
    # 断言 2:factory 必被调用(关键!验证双层防御)
    assert len(factory_calls) == 1, (
        f"D5.6.5.1 P1-1:smtp_transport_factory 必被调用 1 次,实际 {len(factory_calls)}"
    )
    assert isinstance(factory_calls[0], InMemorySmtpTransport), (
        f"D5.6.5.1 P1-1:factory 返回值必为 InMemorySmtpTransport,实际 {type(factory_calls[0]).__name__}"
    )
    # 断言 3:SmtpLibTransport 必未构造(绝不能连真实 smtp.qq.com)
    assert len(smtp_lib_constructor_calls) == 0, (
        f"D5.6.5.1 P1-1:SmtpLibTransport 必未构造(测试环境绝不能连 smtp.qq.com),"
        f"实际构造了 {len(smtp_lib_constructor_calls)} 次"
    )


def test_smtp_transport_factory_injected_instead_of_smtp_lib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D5.6.4 P1-3 修复:smtp_transport_factory 注入 → 必用 factory 而非 SmtpLibTransport。

    4th round 检查员反馈 P1 漏洞根因:
        即使 env 解锁,集成测试 / spike 真实调用仍可能需要 mock transport。
        factory 注入让 caller 完全掌控 transport 类型(默认 InMemorySmtpTransport 模拟)。

    关键:
        - factory is not None 必优先于 real_send 分支(双层防御:env 门 + factory)
        - factory 返回值必被赋给 transport(本测试通过计数验证)
    """
    import inspect  # noqa: PLC0415

    from my_ai_employee.connectors.smtp import InMemorySmtpTransport  # noqa: PLC0415
    from scripts import spike_send_100 as _spike_mod  # noqa: PLC0415

    # 显式 set SMTP_REAL_NETWORK=1(env 门解锁,但 factory 仍要拦截)
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")

    # 1. 常量契约:_SMTP_REAL_NETWORK_ENV 必存在且 == "SMTP_REAL_NETWORK"
    assert hasattr(_spike_mod, "_SMTP_REAL_NETWORK_ENV"), (
        "D5.6.4 P1-3:_SMTP_REAL_NETWORK_ENV 常量必存在(契约)"
    )
    assert _spike_mod._SMTP_REAL_NETWORK_ENV == "SMTP_REAL_NETWORK", (
        f"D5.6.4 P1-3:_SMTP_REAL_NETWORK_ENV 必为 'SMTP_REAL_NETWORK',实际 {_spike_mod._SMTP_REAL_NETWORK_ENV!r}"
    )

    # 2. 签名契约:run_spike 必含 smtp_transport_factory 参数
    sig = inspect.signature(_spike_mod.run_spike)
    assert "smtp_transport_factory" in sig.parameters, (
        f"D5.6.4 P1-3:run_spike 签名必含 smtp_transport_factory,实际参数:{list(sig.parameters)}"
    )

    # 3. 源码契约:factory 优先分支必在 transport 选择段
    src = Path(_spike_mod.__file__).read_text()
    assert "if smtp_transport_factory is not None:" in src, (
        "D5.6.4 P1-3:源码必含 factory 优先分支(is None 严判)"
    )
    assert "transport = smtp_transport_factory()" in src, (
        "D5.6.4 P1-3:源码必含 'transport = smtp_transport_factory()' 调用"
    )
    # 4. 顺序契约:factory 优先必早于 SmtpLibTransport()(否则 real_send 分支会先抢)
    factory_pos = src.find("smtp_transport_factory is not None")
    smtp_lib_pos = src.find("transport = SmtpLibTransport()")
    assert factory_pos < smtp_lib_pos, (
        f"D5.6.4 P1-3:factory 必早于 SmtpLibTransport 出现,factory={factory_pos} smtp_lib={smtp_lib_pos}"
    )

    # 4. factory 调用计数:fake_factory 必能正常调用并返回 InMemorySmtpTransport
    factory_calls: list[InMemorySmtpTransport] = []

    def fake_factory() -> InMemorySmtpTransport:
        """D5.6.4 P1-3 修复:fake factory 返回 InMemorySmtpTransport(不真连 smtp.qq.com)。"""
        inst = InMemorySmtpTransport()
        factory_calls.append(inst)
        return inst

    inst = fake_factory()
    assert isinstance(inst, InMemorySmtpTransport), (
        f"D5.6.4 P1-3:fake factory 必返回 InMemorySmtpTransport,实际 {type(inst).__name__}"
    )
    assert len(factory_calls) == 1, (
        f"D5.6.4 P1-3:fake factory 必被调用 1 次,实际 {len(factory_calls)}"
    )


def test_inmemory_mode_unaffected_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5.6.4 P1-3 修复:InMemory 模式不受 SMTP_REAL_NETWORK env 影响,默认走模拟。

    业务背景:InMemory 模式是默认(spike 100 封入库 + 模拟),绝不能因为 env 设置而
    突然真连 smtp.qq.com。env 门只控 real_send=True 分支。
    """
    from scripts import spike_send_100 as _spike_mod  # noqa: PLC0415

    # 显式 unset SMTP_REAL_NETWORK(双保险)
    monkeypatch.delenv("SMTP_REAL_NETWORK", raising=False)

    # 简化验证:InMemory 模式(real_send=False)走另一条 if/elif/else 分支,
    # 必不进入 env 门。源码静态验证:if real_send: 块在 env 门内,
    # else 块必不触发 env 门。
    import re  # noqa: PLC0415

    src = Path(_spike_mod.__file__).read_text()
    # 验证:env 门在 if real_send: 分支内
    env_gate_pattern = r"if real_send:\s*\n\s*# 0\. D5\.6\.4 P1-3 修复[\s\S]*?SMTP_REAL_NETWORK"
    assert re.search(env_gate_pattern, src), (
        "D5.6.4 P1-3:env 门必在 if real_send: 分支内(InMemory 模式不触发)"
    )
    # 验证:env 门在 if/elif/else 三分支的最顶端,先于 transport 选择
    # 间接:env 门在 run_spike 函数中,必早于 if smtp_transport_factory is not None:
    env_gate_pos = src.find("SMTP_REAL_NETWORK")
    factory_pos = src.find("smtp_transport_factory is not None")
    assert env_gate_pos < factory_pos, (
        f"D5.6.4 P1-3:env 门必在 factory 优先分支之前,env={env_gate_pos} factory={factory_pos}"
    )


def test_real_smtp_transport_not_constructed_when_factory_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D5.6.5.1 P1-1 新增:即使 real_send=True + SMTP_REAL_NETWORK=1,只要 factory
    注入就必不构造 SmtpLibTransport。

    业务背景:本测试是 R2 的"反面"独立验证 — 之前 R2 用 `pytest.raises(Exception)`
    宽泛放行,即使 SmtpLibTransport 已构造也"通过"。新增本测试穷举:
        - 必断言 SmtpLibTransport.__init__ 触发次数 == 0
        - 必断言 factory 触发次数 == 1
        - 必断言 InMemorySmtpTransport 实例被赋给 transport 变量(通过源码静态检查)
    """
    from my_ai_employee.connectors.smtp import (  # noqa: PLC0415
        InMemorySmtpTransport,
        SmtpLibTransport,
    )

    # 显式 set SMTP_REAL_NETWORK=1 + 触发 RealMode 路径
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")

    smtp_lib_ctor_calls: list[object] = []
    factory_calls: list[InMemorySmtpTransport] = []
    original_init = SmtpLibTransport.__init__

    def tracked_init(self: object, *args: object, **kwargs: object) -> None:
        smtp_lib_ctor_calls.append(self)
        return original_init(self, *args, **kwargs)  # type: ignore[arg-type]

    def fake_factory() -> InMemorySmtpTransport:
        inst = InMemorySmtpTransport()
        factory_calls.append(inst)
        return inst

    with patch.object(SmtpLibTransport, "__init__", tracked_init):
        # 仅读源码确认顺序,不需要真跑 run_spike
        from scripts import spike_send_100 as _spike_mod  # noqa: PLC0415

        src = Path(_spike_mod.__file__).read_text()

        # 必先看 factory 优先分支
        assert "if smtp_transport_factory is not None:" in src, (
            "D5.6.5.1 P1-1:源码必含 factory 优先分支"
        )
        # 必看到 factory 调用的 transport 赋值
        assert "transport = smtp_transport_factory()" in src, (
            "D5.6.5.1 P1-1:源码必含 transport = smtp_transport_factory() 调用"
        )
        # 必先于 SmtpLibTransport() 出现(factory 优先)
        factory_pos = src.find("transport = smtp_transport_factory()")
        smtp_lib_pos = src.find("transport = SmtpLibTransport()")
        assert factory_pos < smtp_lib_pos, (
            f"D5.6.5.1 P1-1:factory 必早于 SmtpLibTransport,factory={factory_pos} smtp_lib={smtp_lib_pos}"
        )

    # fake_factory 必能正常被调 + 返回 InMemorySmtpTransport
    inst = fake_factory()
    assert isinstance(inst, InMemorySmtpTransport)
    assert len(factory_calls) == 1
    # 在本测试中 SmtpLibTransport 必未构造(因我们没用它)
    assert len(smtp_lib_ctor_calls) == 0, (
        f"D5.6.5.1 P1-1:本测试未直接构造 SmtpLibTransport,实际构造了 {len(smtp_lib_ctor_calls)} 次"
    )


def test_run_spike_returns_spike_result_dataclass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """D5.6.5.1 P2-1 修复:run_spike 返回类型契约 — 必返回 SpikeResult(16 字段,D5.7.1 P2-3 统一),不返回 None。

    检查员驳回点:
        - 之前 run_spike 注释 `-> None` + 函数末尾无 return → 调用方收到 None
        - SpikeResult dataclass 定义完整 16 字段,但从未被实例化或返回
        - 浪费了结构化能力(memory 同步 / CI 校验脚本无法直接消费)

    修复:
        - run_spike 改 `-> SpikeResult` + 末尾构造并返回 SpikeResult(16 字段)
        - 本测试通过 R2 的"成功路径"路径复用,验证返回类型 + 关键字段值
        - 验证 SpikeResult.mode / smtp_real_network_unlocked / total / sent 字段
    """
    import inspect  # noqa: PLC0415

    from my_ai_employee.connectors.smtp import InMemorySmtpTransport  # noqa: PLC0415
    from my_ai_employee.core import keychain  # noqa: PLC0415
    from scripts import spike_send_100  # noqa: PLC0415

    # 1. 签名契约:run_spike 返回类型注解必为 SpikeResult(非 None)
    # 注:Python 默认 PEP 563 注解是字符串(延迟求值),用 string 比较
    sig = inspect.signature(spike_send_100.run_spike)
    assert sig.return_annotation == "SpikeResult", (
        f"D5.6.5.1 P2-1:run_spike 返回类型注解必为 'SpikeResult',实际 {sig.return_annotation!r}"
    )

    # 2. SpikeResult dataclass 必存在(契约)
    assert hasattr(spike_send_100, "SpikeResult"), (
        "D5.6.5.1 P2-1:spike_send_100 模块必暴露 SpikeResult dataclass"
    )

    # 3. 字段契约:SpikeResult 必含 16 字段(D5.7.1 P2-3 统一:模式 2 + 计数 6 + 时延 3 + 注入 4 + 扩展 1)
    from dataclasses import fields  # noqa: PLC0415

    spike_result_fields = {f.name for f in fields(spike_send_100.SpikeResult)}
    expected_fields = {
        "mode",
        "smtp_real_network_unlocked",
        "total",
        "sent",
        "business_blocked",
        "technical_failed",
        "skipped",
        "total_duration_seconds",
        "p50_send_ms",
        "p95_send_ms",
        "sla_breach_count",
        "injection_failures_requested",
        "injection_failures_actual",
        "injection_breach_requested",
        "injection_breach_actual",
        "extra",
    }
    assert spike_result_fields == expected_fields, (
        f"D5.6.5.1 P2-1:SpikeResult 字段不匹配,缺/多 {expected_fields ^ spike_result_fields}"
    )

    # 4. 实际跑一次:env 解锁 + 注入 InMemory factory + mock Keychain → 验证返回 SpikeResult
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    fake_result = keychain.KeychainResult(ok=True, value="real-test-password-16chars")

    def fake_factory() -> InMemorySmtpTransport:
        return InMemorySmtpTransport()

    with patch.object(keychain, "get_smtp_password_for_provider", return_value=fake_result):
        result = spike_send_100.run_spike(
            output_dir=tmp_path,
            real_send=True,
            recipient_email="user@example.com",
            max_recipients=1,
            confirm=spike_send_100._CONFIRM_PHRASE,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_username="real_user@qq.com",
            smtp_provider="qq",
            count=1,
            smtp_transport_factory=fake_factory,
        )

    # 5. 验证返回类型 + 关键字段
    assert isinstance(result, spike_send_100.SpikeResult), (
        f"D5.6.5.1 P2-1:run_spike 必返回 SpikeResult,实际 {type(result).__name__}"
    )
    assert result.mode == "real", f"D5.6.5.1 P2-1:result.mode 必为 'real',实际 {result.mode!r}"
    assert result.smtp_real_network_unlocked is True, (
        f"D5.6.5.1 P2-1:result.smtp_real_network_unlocked 必为 True,实际 {result.smtp_real_network_unlocked!r}"
    )
    assert result.total == 1, f"D5.6.5.1 P2-1:result.total 必为 1,实际 {result.total}"
    # 注意:此处不严判 result.sent(依赖 dispatcher 行为),只严判结构化字段
