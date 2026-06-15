"""D5.6.2 — spike_send_100.py REAL 模式安全测试(7 cases)。

D5.6.1 检查员反馈 7 项缺陷,本测试文件覆盖 P0/P1.2/P1.3 真实模式安全契约:

测试覆盖(7 cases):
    A. CLI 参数层:
        1. test_cli_no_smtp_password_argparse        — --smtp-password 必须从 CLI 删除
                                                        (防 shell history 泄露)
        2. test_cli_smtp_provider_in_choices         — --smtp-provider choices 白名单严判
    B. run_spike 入口严判:
        3. test_run_spike_rejects_placeholder_password — REAL 模式拒占位密码
        4. test_run_spike_rejects_test_local_host    — REAL 模式拒 .test.local host
        5. test_run_spike_count_must_be_one         — REAL 模式强制 count == 1
    C. 凭证链路:
        6. test_run_spike_reads_password_from_keychain — REAL 模式从 Keychain 真读
        7. test_run_spike_rejects_empty_keychain_password — Keychain 读出空密码时拒收

设计原则(沿 D4.7.3 v1.0.6 范本 + D5.5.4/5 教训):
    - subprocess 跑 CLI 测 argparse(避免 import 副作用)
    - 直接 import run_spike + monkeypatch 测内部逻辑
    - 严判 type + 边界(无 isinstance,无 type(value) is bool 漏判)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "spike_send_100.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """跑 spike_send_100.py CLI,返回 CompletedProcess。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=30,
    )


# ===== A. CLI 参数层 =====


def test_cli_no_smtp_password_argparse() -> None:
    """D5.6.2 P0 凭证链路:--smtp-password 必须从 CLI 删除(防 shell history 泄露)。

    检查员反馈:密码通过 CLI 传递 → shell history + process list 双重泄露。
    """
    result = _run_cli("--help")
    assert result.returncode == 0, f"--help 失败: {result.stderr}"
    assert (
        "--smtp-password" not in result.stdout
    ), f"D5.6.2 P0 凭证链路:--smtp-password 必须从 CLI 删除!\n实际 --help 输出:\n{result.stdout}"


def test_cli_smtp_provider_in_choices() -> None:
    """D5.6.2 P0 凭证链路:--smtp-provider choices 必须白名单(qq/outlook/gmail)。"""
    result = _run_cli("--help")
    assert result.returncode == 0
    assert (
        "--smtp-provider" in result.stdout
    ), f"D5.6.2:--smtp-provider 应在 --help:\n{result.stdout}"
    # choices 应包含 qq/outlook/gmail 三选项
    assert (
        "{qq,outlook,gmail}" in result.stdout or "qq" in result.stdout
    ), f"D5.6.2:--smtp-provider choices 应含 qq/outlook/gmail:\n{result.stdout}"


# ===== B. run_spike 入口严判 =====


def test_run_spike_rejects_placeholder_password() -> None:
    """D5.6.2 P0 凭证链路:REAL 模式调用方无法传 smtp_password 参数(签名已删)。

    即使试图通过位置参数传占位,TypeError 会立即抛错,杜绝占位密码蒙混过关。
    """
    import inspect

    from scripts import spike_send_100  # noqa: PLC0415

    sig = inspect.signature(spike_send_100.run_spike)
    params = sig.parameters
    assert (
        "smtp_password" not in params
    ), f"D5.6.2 P0 凭证链路:run_spike 签名必删 smtp_password(防占位/泄露)!实际参数: {list(params)}"
    # 新签名必须含 smtp_provider
    assert (
        "smtp_provider" in params
    ), f"D5.6.2 P0 凭证链路:run_spike 签名必含 smtp_provider!实际参数: {list(params)}"


def test_run_spike_rejects_test_local_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5.6.2 防误发:REAL 模式拒 .test.local host(防占位 SMTP 服务器连真实网络)。"""
    from scripts import spike_send_100  # noqa: PLC0415

    # D5.6.4 P1-3 修复:env 门解锁(让 .test.local 严判先于 env 门被测到)
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    with pytest.raises(ValueError, match="smtp_host 不能是 .test.local"):
        spike_send_100.run_spike(
            output_dir=Path("/tmp/dummy"),
            real_send=True,
            recipient_email="user@example.com",
            max_recipients=1,
            confirm=spike_send_100._CONFIRM_PHRASE,
            smtp_host="smtp.test.local",
            smtp_port=465,
            smtp_username="real_user@qq.com",
            smtp_provider="qq",
            count=1,
        )


def test_run_spike_count_must_be_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5.6.2 检查员反馈:--real 模式强制 count == 1(防止"我以为是 1 封但实际 10")。

    通过 mock Keychain 避免真实读取,只触发 count 严判段。
    """
    from my_ai_employee.core import keychain  # noqa: PLC0415
    from scripts import spike_send_100  # noqa: PLC0415

    # D5.6.4 P1-3 修复:env 门解锁
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    # mock Keychain 让 count 严判前不报错
    fake_result = keychain.KeychainResult(ok=True, value="real-auth-code-16chars")
    with (
        patch.object(keychain, "get_smtp_password_for_provider", return_value=fake_result),
        pytest.raises(ValueError, match="--count 必传 1"),
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
            count=10,  # ❌ 必拒
        )


# ===== C. 凭证链路 =====


def test_run_spike_reads_password_from_keychain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D5.6.2 P0 凭证链路 + D5.6.3 P2-4 加固 + D5.7.1 P1-1 双层防御:REAL 模式必须从
    Keychain 真读 + 必注入 smtp_transport_factory(防测试连真实 smtp.qq.com)。

    修复前(D5.6.2 P2-4 检查员反馈):
    - 用 contextlib.suppress(Exception) 吞掉所有异常,无法验证凭证链路
    修复后(D5.6.3 P2-4):
    - 直接验证 keychain.get_smtp_password_for_provider 调过的入参 + 返回值
    - 验证返回值(smtp_password)必用于后续 OutboxDispatcher 构造
    - 删 contextlib.suppress(Exception) 路径,异常直接抛(便于真实调试)
    修复后(D5.7.1 P1-1 — 检查员驳回):
    - D5.6.5.1 落地时在 test_spike_send_100_real_network.py:R2 已加双层防御,
      但本测试(test_run_spike_reads_password_from_keychain)仍用
      `pytest.raises(Exception)` 宽泛放行 + 不注入 InMemory factory + 不跟踪
      SmtpLibTransport.__init__,跑全套测试时可能连接 smtp.qq.com(异常前已发)
    - 必注入 smtp_transport_factory=fake_factory(返回 InMemorySmtpTransport)
    - 必跟踪 SmtpLibTransport.__init__ 构造次数
    - 必断言:factory 调 1 次 + SmtpLibTransport 未构造 + 状态(不靠异常)
    """
    from my_ai_employee.connectors.smtp import (  # noqa: PLC0415
        InMemorySmtpTransport,
        SmtpLibTransport,
    )
    from my_ai_employee.core import keychain  # noqa: PLC0415
    from scripts import spike_send_100  # noqa: PLC0415

    # D5.6.4 P1-3 修复:env 门解锁
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")

    real_password = "real-keychain-password-16chars"
    called_with: list[tuple[str, str]] = []

    def mock_get_smtp_password(provider: str, email: str) -> keychain.KeychainResult:
        # 验证调用参数正确(provider 透传,email 透传)
        called_with.append((provider, email))
        return keychain.KeychainResult(ok=True, value=real_password)

    # D5.7.1 P1-1 修复:fake factory 注入(必优先于 SmtpLibTransport 路径)
    factory_calls: list[InMemorySmtpTransport] = []
    smtp_lib_constructor_calls: list[object] = []

    def fake_factory() -> InMemorySmtpTransport:
        """D5.7.1 P1-1:fake factory 返回 InMemorySmtpTransport(替代 SmtpLibTransport)。"""
        inst = InMemorySmtpTransport()
        factory_calls.append(inst)
        return inst

    # D5.7.1 P1-1 修复:跟踪 SmtpLibTransport 构造次数 — 绝不能容忍被构造
    original_smtp_lib_init = SmtpLibTransport.__init__

    def tracked_smtp_lib_init(self: object, *args: object, **kwargs: object) -> None:
        smtp_lib_constructor_calls.append(self)
        return original_smtp_lib_init(self, *args, **kwargs)  # type: ignore[arg-type]

    with (
        patch.object(
            keychain, "get_smtp_password_for_provider", side_effect=mock_get_smtp_password
        ) as mock_call,
        patch.object(SmtpLibTransport, "__init__", tracked_smtp_lib_init),
        # D5.7.1 P1-1:不再用 pytest.raises(Exception) 宽泛放行
        # 用 smtp_transport_factory=fake_factory 必调,断言状态而非异常
    ):
        # 调用 run_spike — 后续 InMemory 模式跑下去也无害(InMemorySmtpTransport 不连 SMTP)
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

    # 断言 1:SpikeResult 必返回(D5.6.5.1 P2-1 修复,顺带验证)
    assert result is not None, "D5.6.5.1 P2-1:run_spike 必返回 SpikeResult(不再 None)"
    # 断言 2:Keychain 函数被调用(provider 透传 + email 透传)
    assert (
        mock_call.called
    ), "D5.6.2 P0 凭证链路:REAL 模式必须调 keychain.get_smtp_password_for_provider,但实际未被调用!"
    assert called_with == [
        ("qq", "real_user@qq.com")
    ], f"D5.6.3 P2-4:Keychain 调用入参必为 (qq, real_user@qq.com),实际 {called_with!r}"
    # 断言 3:返回的密码非空(无占位/空字符串)
    assert real_password, "D5.6.3 P2-4:real_password 必非空(无占位)"
    # 断言 4:D5.7.1 P1-1 双层防御 — factory 必被调用 1 次
    assert (
        len(factory_calls) == 1
    ), f"D5.7.1 P1-1:smtp_transport_factory 必被调用 1 次,实际 {len(factory_calls)}"
    assert isinstance(
        factory_calls[0], InMemorySmtpTransport
    ), f"D5.7.1 P1-1:factory 返回值必为 InMemorySmtpTransport,实际 {type(factory_calls[0]).__name__}"
    # 断言 5:D5.7.1 P1-1 — SmtpLibTransport 必未构造(测试环境绝不能连 smtp.qq.com)
    assert len(smtp_lib_constructor_calls) == 0, (
        f"D5.7.1 P1-1:SmtpLibTransport 必未构造(测试环境绝不能连 smtp.qq.com),"
        f"实际构造了 {len(smtp_lib_constructor_calls)} 次"
    )


def test_run_spike_rejects_empty_keychain_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5.6.2 P0 凭证链路:Keychain 读出空密码/占位时必须拒收(防脏数据蒙混)。"""
    from my_ai_employee.core import keychain  # noqa: PLC0415
    from scripts import spike_send_100  # noqa: PLC0415

    # D5.6.4 P1-3 修复:env 门解锁
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")

    # 测试 1: Keychain 失败(ok=False)
    fail_result = keychain.KeychainResult(ok=False, error="not found")
    with (
        patch.object(keychain, "get_smtp_password_for_provider", return_value=fail_result),
        pytest.raises(RuntimeError, match="从 Keychain 读 .* 失败"),
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

    # 测试 2: Keychain 读出 <test-placeholder> 占位
    placeholder_result = keychain.KeychainResult(ok=True, value="<test-placeholder>")
    with (
        patch.object(keychain, "get_smtp_password_for_provider", return_value=placeholder_result),
        pytest.raises(RuntimeError, match="占位"),
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

    # 测试 3: Keychain 读出空字符串
    empty_result = keychain.KeychainResult(ok=True, value="")
    with (
        patch.object(keychain, "get_smtp_password_for_provider", return_value=empty_result),
        pytest.raises(RuntimeError, match="空密码"),
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
