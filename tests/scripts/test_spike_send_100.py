"""D5.6.3 — spike_send_100.py REAL 模式 --count 1-10 + --multi-confirm 契约(10 cases).

沿 docs/v0.2.56-d5.6.3-relax-design.md §6 + docs/v0.2.56-audit-review-2026-06-30.md。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from my_ai_employee.connectors.smtp import InMemorySmtpTransport, SmtpLibTransport
from my_ai_employee.core import keychain
from scripts import spike_send_100


def _unlock_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")


def _real_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "output_dir": Path("/tmp/dummy"),
        "real_send": True,
        "recipient_email": "user@example.com",
        "max_recipients": 1,
        "confirm": spike_send_100._CONFIRM_PHRASE,
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "smtp_username": "real_user@qq.com",
        "smtp_provider": "qq",
        "count": 1,
        "multi_confirm": "",
    }
    base.update(overrides)
    return base


def _mock_keychain_and_factory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[list[InMemorySmtpTransport], list[object]]:
    fake_result = keychain.KeychainResult(ok=True, value="real-auth-code-16chars")
    monkeypatch.setattr(
        keychain,
        "get_smtp_password_for_provider",
        lambda _p, _e: fake_result,
    )
    factory_calls: list[InMemorySmtpTransport] = []
    smtp_lib_calls: list[object] = []

    def fake_factory() -> InMemorySmtpTransport:
        inst = InMemorySmtpTransport()
        factory_calls.append(inst)
        return inst

    original_init = SmtpLibTransport.__init__

    def tracked_init(self: object, *args: object, **kwargs: object) -> None:
        smtp_lib_calls.append(self)
        return original_init(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(SmtpLibTransport, "__init__", tracked_init)
    return factory_calls, smtp_lib_calls, fake_factory, tmp_path


def test_real_mode_count_1_no_multi_confirm_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """count=1 + 无 multi_confirm → 通过(向后兼容)."""
    _unlock_real_network(monkeypatch)
    factory_calls, smtp_lib_calls, fake_factory, out_dir = _mock_keychain_and_factory(
        monkeypatch, tmp_path
    )
    result = spike_send_100.run_spike(
        **_real_kwargs(output_dir=out_dir, smtp_transport_factory=fake_factory),
    )
    assert result is not None
    assert len(factory_calls) == 1
    assert len(smtp_lib_calls) == 0


def test_real_mode_count_5_no_multi_confirm_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """count=5 + 无 multi_confirm → ValueError."""
    _unlock_real_network(monkeypatch)
    with pytest.raises(ValueError, match="--count > 1 时必传"):
        spike_send_100.run_spike(**_real_kwargs(count=5))


def test_real_mode_count_5_with_multi_confirm_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """count=5 + multi_confirm 正确 → 通过."""
    _unlock_real_network(monkeypatch)
    factory_calls, smtp_lib_calls, fake_factory, out_dir = _mock_keychain_and_factory(
        monkeypatch, tmp_path
    )
    result = spike_send_100.run_spike(
        **_real_kwargs(
            output_dir=out_dir,
            count=5,
            multi_confirm=spike_send_100._MULTI_CONFIRM_PHRASE,
            smtp_transport_factory=fake_factory,
        ),
    )
    assert result is not None
    assert result.total == 5
    assert len(factory_calls) == 1
    assert len(smtp_lib_calls) == 0


def test_real_mode_count_10_with_multi_confirm_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """count=10 + multi_confirm → 上界通过."""
    _unlock_real_network(monkeypatch)
    _factory_calls, smtp_lib_calls, fake_factory, out_dir = _mock_keychain_and_factory(
        monkeypatch, tmp_path
    )
    result = spike_send_100.run_spike(
        **_real_kwargs(
            output_dir=out_dir,
            count=10,
            multi_confirm=spike_send_100._MULTI_CONFIRM_PHRASE,
            smtp_transport_factory=fake_factory,
        ),
    )
    assert result.total == 10
    assert len(smtp_lib_calls) == 0


def test_real_mode_count_11_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """count=11 → 超 _REAL_MODE_MAX_COUNT."""
    _unlock_real_network(monkeypatch)
    with pytest.raises(ValueError, match="--count 必传 1-10"):
        spike_send_100.run_spike(
            **_real_kwargs(
                count=11,
                multi_confirm=spike_send_100._MULTI_CONFIRM_PHRASE,
            ),
        )


def test_real_mode_count_0_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """count=0 → 下界拒绝."""
    _unlock_real_network(monkeypatch)
    with pytest.raises(ValueError, match="--count 必传 1-10"):
        spike_send_100.run_spike(**_real_kwargs(count=0))


def test_real_mode_count_negative_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """count=-1 → 下界负数拒绝."""
    _unlock_real_network(monkeypatch)
    with pytest.raises(ValueError, match="--count 必传 1-10"):
        spike_send_100.run_spike(**_real_kwargs(count=-1))


def test_real_mode_multi_confirm_invalid_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """count=5 + multi_confirm 错值 → ValueError."""
    _unlock_real_network(monkeypatch)
    with pytest.raises(ValueError, match="--count > 1 时必传"):
        spike_send_100.run_spike(**_real_kwargs(count=5, multi_confirm="wrong"))


def test_inmemory_mode_count_unaffected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """InMemory 模式 count 规则不变(沿 _INMEMORY_MAX_COUNT)."""
    result = spike_send_100.run_spike(
        output_dir=tmp_path,
        real_send=False,
        count=50,
    )
    assert result.total == 50

    with pytest.raises(ValueError, match=f"<= {spike_send_100._INMEMORY_MAX_COUNT}"):
        spike_send_100.run_spike(
            output_dir=tmp_path,
            real_send=False,
            count=spike_send_100._INMEMORY_MAX_COUNT + 1,
        )


def test_real_mode_existing_gates_still_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """5 重防误发门控都不动(--confirm / --max-recipients / env 门)."""
    _unlock_real_network(monkeypatch)
    with pytest.raises(ValueError, match="--confirm 必传"):
        spike_send_100.run_spike(**_real_kwargs(confirm="wrong"))

    with pytest.raises(ValueError, match="--max-recipients 必传 1"):
        spike_send_100.run_spike(**_real_kwargs(max_recipients=2))

    monkeypatch.delenv("SMTP_REAL_NETWORK", raising=False)
    with pytest.raises(ValueError, match="SMTP_REAL_NETWORK"):
        spike_send_100.run_spike(**_real_kwargs())
