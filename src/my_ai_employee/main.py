"""我的AI员工 — 主入口。

D1.1 脚手架阶段：仅打印 Hello + 显示项目信息。
Week 1 D5 接入菜单栏后改用 rumps 启动。

设计：rich 可用时用 rich（彩色面板）；不可用时降级到原生 print。
这保证 `make hello` 在依赖装好前后都能用（应急版范本）。

D1.1 改进：所有用户可见的字符串拼装拆成纯函数（render_*_body），
方便单元测试覆盖（覆盖率从 0% → ~80%）。

使用：
    python -m my_ai_employee.main            # 默认
    python -m my_ai_employee.main --interactive  # 交互模式（占位）
    python -m my_ai_employee.main --version     # 版本信息
    python -m my_ai_employee.main --info        # 项目信息
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from my_ai_employee import __version__

# ===== 降级导入 rich =====
try:
    from rich.console import Console
    from rich.panel import Panel

    RICH_AVAILABLE = True
    _console = Console()
except ImportError:
    RICH_AVAILABLE = False
    _console = None  # type: ignore[assignment]


# ===== 纯函数（可单测）=====


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 解析器（拆出来便于单测）。"""
    parser = argparse.ArgumentParser(
        prog="my-ai-employee",
        description="我的AI员工 — 全天候个人 AI 数字员工",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m my_ai_employee.main            # Hello 信息
  python -m my_ai_employee.main --info     # 项目详情
  python -m my_ai_employee.main --version  # 版本号
  python -m my_ai_employee.main --interactive  # 交互模式（占位）
        """,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="显示项目详细信息",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="启动交互模式（占位）",
    )
    return parser


def _strip_rich_tags(line: str) -> str:
    """降级模式：去除 rich 标签得到纯文本（拆出来便于单测）。"""
    for tag in [
        "[bold green]", "[/bold green]",
        "[cyan]", "[/cyan]",
        "[dim]", "[/dim]",
        "[yellow]", "[/yellow]",
        "[green]", "[/green]",
        "[bold]", "[/bold]",
    ]:
        line = line.replace(tag, "")
    return line


def render_hello_body(
    *,
    version: str = __version__,
    now: str | None = None,
    py_ver: str | None = None,
    platform: str | None = None,
    use_rich: bool = RICH_AVAILABLE,
) -> str:
    """渲染 Hello 面板 body（纯函数 — 可单测）。

    Args:
        version: 版本字符串
        now: 当前时间字符串（测试时可固定）
        py_ver: Python 版本字符串
        platform: 平台字符串
        use_rich: 是否使用 rich 标签（默认从全局 RICH_AVAILABLE 读）
    """
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    py_ver = py_ver or sys.version.split()[0]
    platform = platform or sys.platform

    if use_rich:
        return (
            f"[bold green]Hello, 我的AI员工！[/bold green]\n\n"
            f"  版本:      [cyan]{version}[/cyan]\n"
            f"  当前时间:  [cyan]{now}[/cyan]\n"
            f"  Python:    [cyan]{py_ver}[/cyan]\n"
            f"  平台:      [cyan]{platform}[/cyan]\n\n"
            f"[dim]📖 文档：README.md / docs/architecture.md[/dim]\n"
            f"[dim]🛠️  命令：make help[/dim]"
        )
    return (
        "Hello, 我的AI员工！\n"
        "\n"
        f"  版本:      {version}\n"
        f"  当前时间:  {now}\n"
        f"  Python:    {py_ver}\n"
        f"  平台:      {platform}\n"
        "\n"
        "📖 文档：README.md / docs/architecture.md\n"
        "🛠️  命令：make help\n"
        "⚠️  rich 未安装（应急版降级输出）"
    )


def render_info_body(
    *,
    project_root: Path | None = None,
    data_dir: Path | None = None,
    source_entry: str = "src/my_ai_employee/main.py",
    doc_entry: str = "README.md",
    current_stage: str = "D1.1 脚手架重构（PEP 621 + uv）",
    next_stage: str = "D2 IMAP 适配器",
    use_rich: bool = RICH_AVAILABLE,
) -> str:
    """渲染项目信息面板 body（纯函数 — 可单测）。"""
    project_root = project_root or Path(__file__).resolve().parent.parent.parent
    data_dir = data_dir or Path.home() / "Library" / "Application Support" / "我的AI员工"

    if use_rich:
        return (
            f"  [bold]项目根目录[/bold]:  {project_root}\n"
            f"  [bold]数据目录[/bold]:    {data_dir}\n"
            f"  [bold]源码入口[/bold]:    {source_entry}\n"
            f"  [bold]文档入口[/bold]:    {doc_entry}\n"
            f"  [bold]当前阶段[/bold]:    [yellow]{current_stage}[/yellow]\n"
            f"  [bold]下一棒[/bold]:      [green]{next_stage}[/green]"
        )
    return (
        f"  项目根目录:  {project_root}\n"
        f"  数据目录:    {data_dir}\n"
        f"  源码入口:    {source_entry}\n"
        f"  文档入口:    {doc_entry}\n"
        f"  当前阶段:    {current_stage}\n"
        f"  下一棒:      {next_stage}"
    )


# ===== 副作用函数（打印）=====


def _print_panel(title: str, body: str) -> None:
    """打印面板（rich 可用时用彩色，否则用纯文本）。"""
    if RICH_AVAILABLE:
        _console.print(  # type: ignore[union-attr]
            Panel(body, title=title, border_style="blue", padding=(1, 2))
        )
    else:
        # 降级版（应急版范本 Level 3）
        width = 60
        print()
        print(f"┌─ {title} " + "─" * (width - len(title) - 4) + "┐")
        for line in body.split("\n"):
            print(f"│ {_strip_rich_tags(line).ljust(width - 2)} │")
        print("└" + "─" * (width) + "┘")
        print()


def print_hello() -> None:
    """打印 Hello 信息（make hello 用）。"""
    _print_panel("🤖 我的AI员工", render_hello_body())


def print_info() -> None:
    """打印项目信息。"""
    _print_panel("📋 项目信息", render_info_body())


def run_interactive() -> None:
    """交互模式（占位）。"""
    msg = (
        "⏳ 交互模式尚未实现（Week 1 D5 接入菜单栏后可用）\n"
        "当前可用的命令：hello / info / version"
    )
    print(msg)


def main(argv: list[str] | None = None) -> int:
    """主入口。argv 可注入便于单测；不传时用 sys.argv[1:]。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.info:
        print_info()
    elif args.interactive:
        run_interactive()
    else:
        print_hello()

    return 0


if __name__ == "__main__":
    sys.exit(main())
