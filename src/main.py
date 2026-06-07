"""我的AI员工 — 主入口。

D1 脚手架阶段：仅打印 Hello + 显示项目信息。
Week 1 D5 接入菜单栏后改用 rumps 启动。

设计：rich 可用时用 rich（彩色面板）；不可用时降级到原生 print。
这保证 `make hello` 在 poetry install 前后都能用（应急版范本）。

使用：
    poetry run python src/main.py            # 默认
    poetry run python src/main.py --interactive  # 交互模式（占位）
    poetry run python src/main.py --version     # 版本信息
    poetry run python src/main.py --info        # 项目信息
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from src import __version__

# ===== 降级导入 rich =====
try:
    from rich.console import Console
    from rich.panel import Panel

    RICH_AVAILABLE = True
    _console = Console()
except ImportError:
    RICH_AVAILABLE = False
    _console = None  # type: ignore[assignment]


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
            # 简单去除 rich 标签
            line = line.replace("[bold green]", "").replace("[/bold green]", "")
            line = line.replace("[cyan]", "").replace("[/cyan]", "")
            line = line.replace("[dim]", "").replace("[/dim]", "")
            line = line.replace("[yellow]", "").replace("[/yellow]", "")
            line = line.replace("[green]", "").replace("[/green]", "")
            line = line.replace("[bold]", "").replace("[/bold]", "")
            print(f"│ {line.ljust(width - 2)} │")
        print("└" + "─" * (width) + "┘")
        print()


def print_hello() -> None:
    """打印 Hello 信息（make hello 用）。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = "🤖 我的AI员工"

    if RICH_AVAILABLE:
        body = (
            f"[bold green]Hello, 我的AI员工！[/bold green]\n\n"
            f"  版本:      [cyan]{__version__}[/cyan]\n"
            f"  当前时间:  [cyan]{now}[/cyan]\n"
            f"  Python:    [cyan]{sys.version.split()[0]}[/cyan]\n"
            f"  平台:      [cyan]{sys.platform}[/cyan]\n\n"
            f"[dim]📖 文档：README.md / docs/architecture.md[/dim]\n"
            f"[dim]🛠️  命令：poetry run make help[/dim]"
        )
    else:
        body = (
            "Hello, 我的AI员工！\n"
            "\n"
            f"  版本:      {__version__}\n"
            f"  当前时间:  {now}\n"
            f"  Python:    {sys.version.split()[0]}\n"
            f"  平台:      {sys.platform}\n"
            "\n"
            "📖 文档：README.md / docs/architecture.md\n"
            "🛠️  命令：poetry run make help\n"
            "⚠️  rich 未安装（应急版降级输出）"
        )

    _print_panel(title, body)


def print_info() -> None:
    """打印项目信息。"""
    project_root = Path(__file__).resolve().parent.parent
    data_dir = Path.home() / "Library" / "Application Support" / "我的AI员工"

    if RICH_AVAILABLE:
        info = (
            f"  [bold]项目根目录[/bold]:  {project_root}\n"
            f"  [bold]数据目录[/bold]:    {data_dir}\n"
            f"  [bold]源码入口[/bold]:    src/main.py\n"
            f"  [bold]文档入口[/bold]:    README.md\n"
            f"  [bold]当前阶段[/bold]:    [yellow]D1 脚手架（已通过）[/yellow]\n"
            f"  [bold]下一棒[/bold]:      [green]D2 IMAP 适配器[/green]"
        )
    else:
        info = (
            f"  项目根目录:  {project_root}\n"
            f"  数据目录:    {data_dir}\n"
            f"  源码入口:    src/main.py\n"
            f"  文档入口:    README.md\n"
            f"  当前阶段:    D1 脚手架（已通过）\n"
            f"  下一棒:      D2 IMAP 适配器"
        )

    _print_panel("📋 项目信息", info)


def run_interactive() -> None:
    """交互模式（占位）。"""
    msg = (
        "⏳ 交互模式尚未实现（Week 1 D5 接入菜单栏后可用）\n"
        "当前可用的命令：hello / info / version"
    )
    print(msg)


def main() -> int:
    """主入口。"""
    parser = argparse.ArgumentParser(
        prog="my-ai-employee",
        description="我的AI员工 — 全天候个人 AI 数字员工",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python src/main.py                  # Hello 信息
  python src/main.py --info           # 项目详情
  python src/main.py --version        # 版本号
  python src/main.py --interactive    # 交互模式（占位）
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

    args = parser.parse_args()

    if args.info:
        print_info()
    elif args.interactive:
        run_interactive()
    else:
        print_hello()

    return 0


if __name__ == "__main__":
    sys.exit(main())
