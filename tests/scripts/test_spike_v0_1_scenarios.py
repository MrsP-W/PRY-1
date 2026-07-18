"""v0.1 场景入口的 S5 真实 SMTP fail-closed 门控回归。"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from scripts import spike_v0_1_scenarios as scenarios


def _main(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["spike_v0_1_scenarios.py", *args])
    return scenarios.main()


def _must_not_run(_: str) -> int:
    """拒绝路径不得回退到 subprocess 场景执行。"""
    raise AssertionError("S5 entry gate should reject before running a scenario")


def test_real_requires_enable_s5(monkeypatch: pytest.MonkeyPatch) -> None:
    """--real 不能被静默忽略，避免误以为已进入真实模式。"""
    monkeypatch.setattr(scenarios, "_run_scenario", _must_not_run)

    assert _main(monkeypatch, "--real") == 1


def test_s5_requires_explicit_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """S5 不能因遗漏 --real 而运行一个看似成功的 skip 场景。"""
    monkeypatch.setattr(scenarios, "_run_scenario", _must_not_run)

    assert _main(monkeypatch, "--enable-s5") == 1


def test_s5_real_requires_network_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """无显式网络环境变量时，在调用场景前拒绝。"""
    monkeypatch.delenv("SMTP_REAL_NETWORK", raising=False)
    monkeypatch.setattr(scenarios, "_run_scenario", _must_not_run)

    assert (
        _main(
            monkeypatch,
            "--enable-s5",
            "--real",
            "--confirm",
            scenarios._S5_CONFIRM_PHRASE,
        )
        == 1
    )


@pytest.mark.parametrize("confirm", ["", "wrong-confirmation"])
def test_s5_real_requires_exact_confirmation(monkeypatch: pytest.MonkeyPatch, confirm: str) -> None:
    """确认短语缺失或错误时，不得启动 S5。"""
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    monkeypatch.setattr(scenarios, "_run_scenario", _must_not_run)
    args = ["--enable-s5", "--real"]
    if confirm:
        args.extend(["--confirm", confirm])

    assert _main(monkeypatch, *args) == 1


def test_s5_real_runs_only_after_all_entry_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """全门通过才调用 S5；混用或任何子场景非零均 fail-closed。"""
    calls: list[str] = []

    def run_scenario(scenario: str, **_: object) -> int:
        calls.append(scenario)
        return 0 if len(calls) == 1 else 1

    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    monkeypatch.setattr(scenarios, "_run_scenario", run_scenario)

    assert (
        _main(
            monkeypatch,
            "--enable-s5",
            "--real",
            "--confirm",
            scenarios._S5_CONFIRM_PHRASE,
        )
        == 0
    )
    assert calls == ["s5_real_smtp"]

    assert (
        _main(
            monkeypatch,
            "--enable-s5",
            "--real",
            "--confirm",
            scenarios._S5_CONFIRM_PHRASE,
        )
        == 1
    )
    assert calls == ["s5_real_smtp", "s5_real_smtp"]

    # 真实 SMTP 不得和其他批量场景混跑，拒绝必须发生在任何子场景前。
    monkeypatch.setattr(scenarios, "_run_scenario", _must_not_run)
    for other_scenario_args in (
        ("--enable-s1-s4",),
        ("--enable-s6-s9",),
        ("--enable-s1-s4", "--enable-s6-s9"),
    ):
        assert (
            _main(
                monkeypatch,
                "--enable-s5",
                "--real",
                "--confirm",
                scenarios._S5_CONFIRM_PHRASE,
                *other_scenario_args,
            )
            == 1
        )

    # pytest rc=2 表示中断，绝不能被场景入口伪装成成功跳过。
    interrupted_calls: list[str] = []

    def interrupted(scenario: str) -> int:
        interrupted_calls.append(scenario)
        return 2

    monkeypatch.setattr(scenarios, "_run_scenario", interrupted)

    assert _main(monkeypatch, "--enable-s1-s4") == 1
    assert interrupted_calls == ["s1_imap_classify", "s2_draft", "s3_outbox", "s4_approve"]


def test_s5_cli_injects_child_only_confirmation_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """S5 的 CLI 确认只传给单次子 pytest，不污染父进程或 direct pytest。"""
    calls: list[dict[str, str] | None] = []

    def run_scenario(scenario: str, *, extra_env: dict[str, str] | None = None) -> int:
        assert scenario == "s5_real_smtp"
        calls.append(extra_env)
        return 0

    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    monkeypatch.delenv(scenarios._S5_CLI_CONFIRM_ENV, raising=False)
    monkeypatch.setattr(scenarios, "_run_scenario", run_scenario)

    assert (
        _main(
            monkeypatch,
            "--enable-s5",
            "--real",
            "--confirm",
            scenarios._S5_CONFIRM_PHRASE,
        )
        == 0
    )
    assert calls and calls[0] is not None
    assert calls[0] == {scenarios._S5_CLI_CONFIRM_ENV: scenarios._S5_CLI_CONFIRM_VALUE}
    assert scenarios._S5_CLI_CONFIRM_ENV not in os.environ


def test_run_scenario_merges_child_env_without_mutating_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """子进程覆写只作用于其 pytest 调用，父环境保持原样。"""
    captured_envs: list[dict[str, str]] = []

    class _RunResult:
        returncode = 0

    def fake_run(command: list[str], *, cwd: object, env: dict[str, str]) -> _RunResult:
        assert command[:3] == ["uv", "run", "pytest"]
        assert cwd == scenarios.ROOT
        captured_envs.append(env)
        return _RunResult()

    monkeypatch.setenv("PRESERVED_PARENT_ENV", "present")
    monkeypatch.delenv(scenarios._S5_CLI_CONFIRM_ENV, raising=False)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert (
        scenarios._run_scenario(
            "s5_real_smtp",
            extra_env={scenarios._S5_CLI_CONFIRM_ENV: scenarios._S5_CLI_CONFIRM_VALUE},
        )
        == 0
    )
    assert captured_envs == [
        {
            **os.environ,
            scenarios._S5_CLI_CONFIRM_ENV: scenarios._S5_CLI_CONFIRM_VALUE,
        }
    ]
    assert scenarios._S5_CLI_CONFIRM_ENV not in os.environ
