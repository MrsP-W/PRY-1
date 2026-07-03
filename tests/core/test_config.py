"""tests/core/test_config.py — `.env` 统一加载模块单测。

覆盖：
    - load_env 幂等（第二次调用返回 False，不重复加载）
    - 无 .env 文件时安全返回 False
    - 显式 dotenv_path 真正加载 + 不覆盖已有 env（override=False）
    - override=True 覆盖已有 env
    - project_root 指向仓库根（含 pyproject.toml）
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest

from my_ai_employee.core import config


@pytest.fixture(autouse=True)
def _reset_flag() -> Generator[None, None, None]:
    """每个用例前后重置幂等 flag，避免相互污染。"""
    config.reset_for_test()
    yield
    config.reset_for_test()


def test_project_root_has_pyproject() -> None:
    root = config.project_root()
    assert (root / "pyproject.toml").exists()


def test_load_env_missing_file_returns_false(tmp_path: Path) -> None:
    missing = tmp_path / ".env"
    assert config.load_env(dotenv_path=missing) is False


def test_load_env_reads_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MYAIEMP_TEST_KEY=from_dotenv\n", encoding="utf-8")
    monkeypatch.delenv("MYAIEMP_TEST_KEY", raising=False)

    loaded = config.load_env(dotenv_path=env_file)

    assert loaded is True
    assert os.environ.get("MYAIEMP_TEST_KEY") == "from_dotenv"


def test_load_env_does_not_override_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MYAIEMP_TEST_KEY=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("MYAIEMP_TEST_KEY", "from_shell")

    config.load_env(dotenv_path=env_file)

    # override=False → shell 值优先
    assert os.environ.get("MYAIEMP_TEST_KEY") == "from_shell"


def test_load_env_override_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MYAIEMP_TEST_KEY=from_dotenv\n", encoding="utf-8")
    monkeypatch.setenv("MYAIEMP_TEST_KEY", "from_shell")

    config.load_env(dotenv_path=env_file, override=True)

    assert os.environ.get("MYAIEMP_TEST_KEY") == "from_dotenv"


def test_load_env_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    # 第一次（无显式路径，走默认根 .env；可能存在也可能不存在）
    config.load_env()
    # 第二次默认路径 → 幂等直接返回 False
    assert config.load_env() is False
