"""Day 1.2 · setup_wizard.py 单测.

覆盖关键路径(撞坑 #1 凭据不入 chat/docs/commit + #18 override=False + #65 Notes opt-in):
    1. test_setup_wizard_help_exits_zero — --help 可用
    2. test_setup_wizard_check_only_exits_zero — --check-only 零副作用
    3. test_setup_wizard_check_only_no_email — --check-only 无邮箱走降级路径
    4. test_setup_wizard_tcc_only_exits_zero — --tcc-only 打印 TCC 引导
    5. test_setup_wizard_setup_status_dataclass — SetupStatus NamedTuple 字段对齐
    6. test_setup_wizard_init_db_skips_on_no_confirm — --init-db 用户拒绝时跳过
    7. test_setup_wizard_main_skips_writes_on_no_confirm — 全流程用户拒绝时只跑 check
    8. test_setup_wizard_load_env_called_once — 幂等 load_env 严判
    9. test_setup_wizard_no_shell_profile_writes — 严判:不写 ENABLE_*=1 到 shell
    10. test_setup_wizard_no_env_writes — 严判:不写凭据到 .env

跑法:
    pytest tests/scripts/test_setup_wizard.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETUP_WIZARD = PROJECT_ROOT / "scripts" / "setup_wizard.py"


def _run_setup_wizard(
    *args: str, stdin_input: str = "", env: dict | None = None
) -> subprocess.CompletedProcess:
    """辅助:跑 setup_wizard 子进程(避免污染当前进程 state)。"""
    return subprocess.run(
        [sys.executable, str(SETUP_WIZARD), *args],
        cwd=PROJECT_ROOT,
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **(env or {})},
        check=False,
    )


class TestSetupWizardCLI:
    """setup_wizard CLI 严格退出码测试(沿 test_import_alipay_cli.py 范本)。"""

    def test_setup_wizard_help_exits_zero(self) -> None:
        """--help 可用 · exit 0(沿 argparse 范本)。"""
        result = _run_setup_wizard("--help")
        assert result.returncode == 0
        assert "完全体首次配置向导" in result.stdout
        assert "--check-only" in result.stdout
        assert "--skip-notes" in result.stdout
        assert "--init-db" in result.stdout
        assert "--tcc-only" in result.stdout

    def test_setup_wizard_check_only_exits_zero(self) -> None:
        """--check-only 零副作用(用户输入有效邮箱 + 跳过写入)。"""
        result = _run_setup_wizard(
            "--check-only",
            stdin_input="123456789@qq.com\n",
        )
        # 即使 Keychain 没数据,check-only 也会成功(只是显示未配置)
        assert result.returncode == 0
        assert "步骤 1/6" in result.stdout
        assert "QQ IMAP 授权码" in result.stdout
        assert "QQ SMTP 授权码" in result.stdout
        assert "Notes master key" in result.stdout

    def test_setup_wizard_check_only_no_email_degrades(self) -> None:
        """--check-only 无邮箱走降级路径(仅检查 Notes master key)。"""
        result = _run_setup_wizard(
            "--check-only",
            stdin_input="\n",  # 空邮箱
        )
        assert result.returncode == 0
        assert "邮箱无效" in result.stdout
        assert "仅检查 Notes master key" in result.stdout
        # IMAP/SMTP 步骤被跳过,直接展示 Notes 检查
        assert "Notes master key(opt-in)" in result.stdout

    def test_setup_wizard_tcc_only_exits_zero(self) -> None:
        """--tcc-only 打印 TCC 引导(沿撞坑 #81 关键洞察)。"""
        result = _run_setup_wizard("--tcc-only")
        assert result.returncode == 0
        assert "macOS TCC 授权引导" in result.stdout
        assert "辅助功能" in result.stdout
        assert "自动化" in result.stdout
        assert "完全磁盘访问" in result.stdout
        # 撞坑 #81 关键洞察:Python.framework 3.12 而非 .venv/bin/python3
        assert "Python 3.12" in result.stdout

    def test_setup_wizard_init_db_skips_on_no_confirm(self) -> None:
        """--init-db 用户拒绝时跳过 alembic(沿 D5.6.5 4 重防误发范本)。"""
        result = _run_setup_wizard(
            "--init-db",
            stdin_input="no\n",  # 拒绝确认
        )
        assert result.returncode == 0
        assert "跳过" in result.stdout


class TestSetupWizardSafety:
    """setup_wizard 严判红线(撞坑 #1 + #18 + #65 + #71)。"""

    def test_setup_wizard_no_shell_profile_writes(self) -> None:
        """严判:setup_wizard 不会写 ~/.zshrc / ~/.bash_profile / shell profile。"""
        # 跑全流程(用户输入全部 yes / 测试邮箱 / 空凭据)
        result = _run_setup_wizard(
            "--skip-notes",
            stdin_input="123456789@qq.com\nyes\n123456789@qq.com\n\nno\nno\n",  # IMAP/SMTP 空凭据拒绝
        )
        # 即使用户填了邮箱,空凭据也会被严判拒写(无副作用)
        assert "授权码不能为空" in result.stdout or "跳过" in result.stdout

        # 验证 ~/.zshrc / ~/.bash_profile 没有新增 ENABLE_*=1
        for profile in [Path.home() / ".zshrc", Path.home() / ".bash_profile"]:
            if profile.exists():
                content = profile.read_text()
                # 不应包含 ENABLE_PATH_4_WRITE=1 / ENABLE_NOTES_ENCRYPTION=1
                assert "ENABLE_PATH_4_WRITE=1" not in content, (
                    f"{profile} 不应有 ENABLE_PATH_4_WRITE=1"
                )
                assert "ENABLE_NOTES_ENCRYPTION=1" not in content, (
                    f"{profile} 不应有 ENABLE_NOTES_ENCRYPTION=1"
                )

    def test_setup_wizard_no_env_writes(self) -> None:
        """严判:.env 不会被 setup_wizard 写入任何凭据(撞坑 #1 教训)。"""
        env_file = PROJECT_ROOT / ".env"
        env_before = env_file.read_text() if env_file.exists() else ""

        _run_setup_wizard(
            "--skip-notes",
            stdin_input="123456789@qq.com\nyes\n123456789@qq.com\n\nno\nno\n",
        )

        env_after = env_file.read_text() if env_file.exists() else ""
        # .env 内容不应被 setup_wizard 改动
        assert env_after == env_before, ".env 不应被 setup_wizard 修改"

    def test_setup_wizard_main_skips_writes_on_no_confirm(self) -> None:
        """全流程用户拒绝时只跑 check(不进入写入)。"""
        result = _run_setup_wizard(
            stdin_input="123456789@qq.com\nno\n",  # check 后拒绝继续
        )
        assert result.returncode == 0
        assert "跳过写入" in result.stdout
        # 不应进入 IMAP/SMTP/Notes/DB/TCC 步骤
        assert "步骤 2/6" not in result.stdout
        assert "步骤 6/6" not in result.stdout


class TestSetupWizardModule:
    """setup_wizard 模块内部单元测试。"""

    def test_setup_wizard_setup_status_dataclass(self) -> None:
        """SetupStatus NamedTuple 字段对齐(沿 v0.2.x 撞坑 #63 5 路径严判范本)。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from setup_wizard import SetupStatus  # noqa: E402

        # 4 字段严判: name / ok / detail / skipped
        s = SetupStatus(name="test", ok=True, detail="ok", skipped=False)
        assert s.name == "test"
        assert s.ok is True
        assert s.detail == "ok"
        assert s.skipped is False

        # skipped 默认值
        s2 = SetupStatus(name="test2", ok=True)
        assert s2.detail == ""
        assert s2.skipped is False

        # skipped=True 路径
        s3 = SetupStatus(name="test3", ok=True, detail="skipped", skipped=True)
        assert s3.skipped is True

    def test_setup_wizard_load_env_called_once(self) -> None:
        """幂等 load_env 严判(撞坑 #18 override=False 范本)。"""
        # 测试 core/config.py 的 _ENV_LOADED 标志
        from my_ai_employee.core import config  # noqa: E402

        # 重置状态(测试间隔离)
        config._ENV_LOADED = False
        first = config.load_env()
        second = config.load_env()
        # 第二次应该是幂等返 False(不重复 load_dotenv)
        assert first is True
        assert second is False


class TestSetupWizardEdgeCases:
    """setup_wizard 边界路径测试。"""

    def test_setup_wizard_invalid_argv(self) -> None:
        """无效 argv 走 argparse error(沿撞坑 #63 严判范本)。"""
        result = _run_setup_wizard("--invalid-flag")
        # argparse 错误退出码 = 2
        assert result.returncode == 2
        assert "unrecognized arguments" in result.stderr or "no such option" in result.stderr

    def test_setup_wizard_tcc_only_does_not_touch_keychain(self) -> None:
        """--tcc-only 严判零 Keychain 调用(进程内 main,非子进程)."""
        import importlib.util

        with (
            patch("my_ai_employee.core.keychain.get_imap_password") as mock_imap,
            patch("my_ai_employee.core.keychain.get_smtp_password_for_provider") as mock_smtp,
            patch("my_ai_employee.core.keychain.get_notes_master_key") as mock_notes,
        ):
            spec = importlib.util.spec_from_file_location("setup_wizard", SETUP_WIZARD)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            rc = module.main(["--tcc-only"])
            assert rc == 0
            mock_imap.assert_not_called()
            mock_smtp.assert_not_called()
            mock_notes.assert_not_called()
