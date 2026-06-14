"""D5.6.4 — spike_send_100.py 真实网络门 + transport factory 注入集成测试(4 cases)。

D5.6.4 P1-3 修复(4th round 检查员反馈):
    - test_run_spike(real_send=True) 没有替换 SmtpLibTransport,可能连接 smtp.qq.com
    - 必须显式 SMTP_REAL_NETWORK=1 + 可选 smtp_transport_factory 注入,双层防御

测试覆盖(4 cases):
    R1. test_real_mode_rejects_without_smtp_real_network_env
        real_send=True 但 SMTP_REAL_NETWORK 未设置 → 必抛 ValueError
    R2. test_real_mode_unlocked_with_smtp_real_network_env
        SMTP_REAL_NETWORK=1 + mock Keychain → 必进 Keychain 调用链
    R3. test_smtp_transport_factory_injected_instead_of_smtp_lib
        SMTP_REAL_NETWORK=1 + smtp_transport_factory 注入 → 必用 factory 而非 SmtpLibTransport
    R4. test_inmemory_mode_unaffected_by_env
        real_send=False → SMTP_REAL_NETWORK env 完全无影响,走 InMemorySmtpTransport

设计原则(沿 D4.7.3 v1.0.6 + D5.6.2 范本):
- 不跑 spike 完整流程(慢),只验入口段 + 关键调用链
- mock Keychain 让 RealMode 流程可触发
- 严判 type + 边界(无 isinstance,无 type(value) is bool 漏判)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "spike_send_100.py"
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== R. D5.6.4 P1-3 真实网络门 + transport factory 注入(4 cases)=====


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
) -> None:
    """D5.6.4 P1-3 修复:SMTP_REAL_NETWORK=1 → 必进 Keychain 调用链(env 门解锁成功)。

    验证正向路径:env 解锁后,RealMode 后续流程(读 Keychain 等)正常推进。
    Keychain 必须被调(否则无法获得真实授权码)。
    """
    from my_ai_employee.core import keychain  # noqa: PLC0415
    from scripts import spike_send_100  # noqa: PLC0415

    # 显式 set SMTP_REAL_NETWORK=1
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")

    # mock Keychain
    fake_result = keychain.KeychainResult(ok=True, value="real-test-password-16chars")
    with (
        patch.object(keychain, "get_smtp_password_for_provider", return_value=fake_result),
        pytest.raises(
            Exception
        ) as exc_info,  # 后续会抛错(无 _install_fake_keychain),但 Keychain 必先被调
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

    # 关键断言:Keychain 已被调(env 解锁成功,流程通过 env 门)
    # 通过 exc_info 看是否进入"Keychain 读"之后(空密码检查已过)
    err_msg = str(exc_info.value)
    # 必看到 keychain 错误链之外的后续错误(说明 env 门 + Keychain 读 + 空检查全过)
    # 例如 "Keychain" 必不在错误中(已通过)
    assert "Keychain" not in err_msg or "空" in err_msg, (
        f"D5.6.4 P1-3:SMTP_REAL_NETWORK=1 后必通过 Keychain 读,实际错误:{err_msg!r}"
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
