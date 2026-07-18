"""S5 direct pytest 的 fail-closed collection gate 回归。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.e2e import conftest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _FakeItem:
    """最小 pytest item 替身，只记录 collection hook 添加的 marker。"""

    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.markers: list[Any] = []

    def add_marker(self, marker: Any) -> None:
        self.markers.append(marker)


@pytest.mark.parametrize(
    ("network_enabled", "child_marker", "should_skip"),
    [
        (True, None, False),
        (False, conftest._S5_CLI_CONFIRM_VALUE, True),
        (True, conftest._S5_CLI_CONFIRM_VALUE, False),
        (True, "unexpected", False),
    ],
)
def test_s5_collection_skips_only_without_network(
    monkeypatch: pytest.MonkeyPatch,
    network_enabled: bool,
    child_marker: str | None,
    should_skip: bool,
) -> None:
    """仅无网络 env 可跳过；已开网络但未确认必须进入 fail-closed 测试体。"""
    if network_enabled:
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    else:
        monkeypatch.delenv("SMTP_REAL_NETWORK", raising=False)
    if child_marker is None:
        monkeypatch.delenv(conftest._S5_CLI_CONFIRM_ENV, raising=False)
    else:
        monkeypatch.setenv(conftest._S5_CLI_CONFIRM_ENV, child_marker)

    item = _FakeItem("tests/e2e/test_v0_1_s5_real_smtp.py::test_s5_real_smtp_1_email_sent")
    conftest.pytest_collection_modifyitems(None, [item])

    assert bool(item.markers) is should_skip


def test_network_enabled_without_cli_marker_fails_closed() -> None:
    """direct pytest 不能把缺确认误报为成功的 skip。"""
    env = os.environ.copy()
    env["SMTP_REAL_NETWORK"] = "1"
    env.pop(conftest._S5_CLI_CONFIRM_ENV, None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-cov",
            "tests/e2e/test_v0_1_s5_real_smtp.py",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "已确认的 CLI" in result.stdout + result.stderr


def test_collection_gate_leaves_non_s5_items_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """S5 的加严门不影响其他 e2e 场景。"""
    monkeypatch.delenv("SMTP_REAL_NETWORK", raising=False)
    monkeypatch.delenv(conftest._S5_CLI_CONFIRM_ENV, raising=False)
    item = _FakeItem("tests/e2e/test_v0_1_s4_approve.py::test_s4_approve")

    conftest.pytest_collection_modifyitems(None, [item])

    assert item.markers == []


def test_fake_keychain_hooks_are_restored_after_fixture_scope() -> None:
    """e2e fake Keychain 的动态 hook 不得泄漏到后续测试。"""
    from my_ai_employee.core import keychain

    missing = object()
    keychain_module: Any = keychain
    original_get = getattr(keychain_module, "get", missing)
    original_set = getattr(keychain_module, "set", missing)

    with pytest.MonkeyPatch.context() as scoped_monkeypatch:
        conftest._install_fake_keychain(scoped_monkeypatch)

        assert callable(keychain_module.get)
        assert callable(keychain_module.set)

    assert getattr(keychain_module, "get", missing) is original_get
    assert getattr(keychain_module, "set", missing) is original_set
