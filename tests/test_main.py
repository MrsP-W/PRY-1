"""D1.1 测试：覆盖可单测的纯函数，subprocess 只留 2 个 CLI 冒烟。

D1 旧版：6 个测试全用 subprocess，覆盖率 0%
D1.1 新版：**18 个测试**（实测覆盖率 61.9%）
  - 9 个直接 import 测纯函数（build_parser × 3、_strip_rich_tags × 2、render_*_body × 4）
  - 5 个参数化测试（_strip_rich_tags 边界情况）
  - 2 个 subprocess 冒烟（hello + --version 真实跑）
  - 2 个 my_ai_employee 包元数据

D2+ 实际业务测试会在 tests/connectors/、tests/core/、tests/ai/ 下扩展。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 定位项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ===== 纯函数单测（覆盖率核心）=====


def test_build_parser_default() -> None:
    """默认参数：info=False, interactive=False。"""
    from my_ai_employee.main import build_parser

    parser = build_parser()
    args = parser.parse_args([])
    assert args.info is False
    assert args.interactive is False


def test_build_parser_info_flag() -> None:
    """--info 标志被识别。"""
    from my_ai_employee.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["--info"])
    assert args.info is True
    assert args.interactive is False


def test_build_parser_interactive_flag() -> None:
    """--interactive 标志被识别。"""
    from my_ai_employee.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["--interactive"])
    assert args.interactive is True
    assert args.info is False


def test_strip_rich_tags_removes_all() -> None:
    """降级模式：去除所有 rich 标签。"""
    from my_ai_employee.main import _strip_rich_tags

    raw = "[bold green]Hello[/bold green] [cyan]v1.0[/cyan]"
    assert _strip_rich_tags(raw) == "Hello v1.0"


def test_strip_rich_tags_no_op_on_plain() -> None:
    """降级模式：纯文本无影响。"""
    from my_ai_employee.main import _strip_rich_tags

    assert _strip_rich_tags("hello world") == "hello world"


def test_render_hello_body_rich_mode() -> None:
    """Hello body rich 模式：含 rich 标签。"""
    from my_ai_employee.main import render_hello_body

    body = render_hello_body(
        version="1.2.3",
        now="2026-06-07 16:00:00",
        py_ver="3.12.13",
        platform="darwin",
        use_rich=True,
    )
    assert "[bold green]Hello, 我的AI员工！[/bold green]" in body
    assert "[cyan]1.2.3[/cyan]" in body
    assert "[cyan]2026-06-07 16:00:00[/cyan]" in body
    assert "[cyan]3.12.13[/cyan]" in body
    assert "[cyan]darwin[/cyan]" in body


def test_render_hello_body_plain_mode() -> None:
    """Hello body 降级模式：无 rich 标签，含应急版提示。"""
    from my_ai_employee.main import render_hello_body

    body = render_hello_body(
        version="1.2.3",
        now="2026-06-07 16:00:00",
        py_ver="3.12.13",
        platform="darwin",
        use_rich=False,
    )
    assert "[bold" not in body
    assert "[cyan" not in body
    assert "Hello, 我的AI员工！" in body
    assert "1.2.3" in body
    assert "应急版" in body  # 降级提示


def test_render_info_body_rich_mode() -> None:
    """Info body rich 模式：含 stage 高亮。"""
    from my_ai_employee.main import render_info_body

    body = render_info_body(
        project_root=Path("/tmp/test"),
        data_dir=Path("/tmp/data"),
        current_stage="D1.1 脚手架重构",
        next_stage="D2 IMAP",
        use_rich=True,
    )
    assert "[bold]项目根目录[/bold]" in body
    assert "/tmp/test" in body
    assert "[yellow]D1.1 脚手架重构[/yellow]" in body
    assert "[green]D2 IMAP[/green]" in body


def test_render_info_body_plain_mode() -> None:
    """Info body 降级模式：无 rich 标签。"""
    from my_ai_employee.main import render_info_body

    body = render_info_body(
        project_root=Path("/tmp/test"),
        data_dir=Path("/tmp/data"),
        current_stage="D1.1",
        next_stage="D2",
        use_rich=False,
    )
    assert "[bold" not in body
    assert "[yellow" not in body
    assert "[green" not in body
    assert "D1.1" in body
    assert "D2" in body


# ===== Subprocess 冒烟（CLI 真实跑通）=====


def _run_main(*args: str) -> subprocess.CompletedProcess[str]:
    """用 python -m my_ai_employee.main 跑子进程。"""
    return subprocess.run(
        [sys.executable, "-m", "my_ai_employee.main", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_cli_hello_smoke() -> None:
    """CLI 冒烟 1：默认调用能跑通 + 包含项目名。"""
    result = _run_main()
    assert result.returncode == 0, f"非零退出码：{result.returncode}\n{result.stderr}"
    assert "我的AI员工" in result.stdout
    assert "Hello" in result.stdout


def test_cli_version_smoke() -> None:
    """CLI 冒烟 2：--version 输出正确版本号。"""
    result = _run_main("--version")
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


# ===== 包元数据单测 =====


def test_package_version() -> None:
    """验证 my_ai_employee 包版本。"""
    from my_ai_employee import __version__

    assert __version__ == "0.1.0"


def test_package_author() -> None:
    """验证 my_ai_employee 包作者。"""
    from my_ai_employee import __author__

    assert __author__ == "Mr-PRY"


# ===== 参数化：Hello body 的标签剥离（边界情况）=====


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("[bold]x[/bold]", "x"),
        ("[cyan]v1[/cyan] [green]ok[/green]", "v1 ok"),
        ("plain", "plain"),
        ("", ""),
        ("[bold green]Hello[/bold green] [dim]note[/dim]", "Hello note"),
    ],
)
def test_strip_rich_tags_parametrized(raw: str, expected: str) -> None:
    """降级标签剥离：参数化 5 个边界情况。"""
    from my_ai_employee.main import _strip_rich_tags

    assert _strip_rich_tags(raw) == expected
