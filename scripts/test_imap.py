#!/usr/bin/env python3
"""D2.4 — IMAP 适配器测试入口（CLI）。

用法：

    # 1. 把 QQ 授权码写进 Keychain（一次性）
    python scripts/test_imap.py --set-password your@qq.com
    # 然后粘贴 16 位授权码（不回显）

    # 2. 健康检查（不取邮件，只验证连得通）
    python scripts/test_imap.py --check --email your@qq.com --provider qq

    # 3. 拉取最近 7 天的邮件（INBOX）
    python scripts/test_imap.py --fetch-latest --email your@qq.com \\
        --provider qq --days 7 --limit 5

    # 4. 删 Keychain 里的授权码
    python scripts/test_imap.py --delete-password --email your@qq.com

设计（[docs/week1-mvp.md §D2.4]）：

    - 用 `argparse` + `getpass`（密码不回显）
    - 输出走 rich（如可用）或降级到原生 print（应急版范本）
    - 退出码：0 成功 / 1 失败（CI 友好）

风险（[docs/week1-mvp.md §D2 风险]）：

    - 用户必须先在 QQ 邮箱网页版生成授权码
    - mitm 风险：imapclient 默认 verify=True（macOS 证书链）
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# 允许脚本被直接 `python scripts/test_imap.py` 跑（无需安装包）
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from my_ai_employee.connectors.imap import IMAPConnector  # noqa: E402
from my_ai_employee.core import keychain  # noqa: E402

# ===== 输出辅助（应急版范本）=====


def _print(msg: str) -> None:
    """统一输出：rich 可用时用 rich，否则原生 print。"""
    try:
        from rich.console import Console

        Console().print(msg)
    except ImportError:
        print(msg)


def _print_err(msg: str) -> None:
    """错误输出（统一到 stderr）。"""
    try:
        from rich.console import Console

        Console(stderr=True).print(f"[bold red]{msg}[/bold red]")
    except ImportError:
        print(f"❌ {msg}", file=sys.stderr)


# ===== 子命令实现 =====


async def cmd_check(email: str, provider: str) -> int:
    """健康检查（不取邮件）。"""
    connector = IMAPConnector(provider=provider, email=email)
    _print(f"🔍 正在检查 IMAP 连通性: {provider} / {email}")
    status = await connector.healthcheck()
    if status.ok:
        _print(
            f"✅ 健康检查通过: latency={status.latency_ms:.1f}ms circuit_open={status.circuit_open}"
        )
        return 0
    _print_err(f"健康检查失败: error={status.error} latency={status.latency_ms:.1f}ms")
    return 1


async def cmd_fetch_latest(email: str, provider: str, days: int, limit: int) -> int:
    """拉取最近 N 天的邮件。"""
    since = datetime.now(UTC) - timedelta(days=days)
    connector = IMAPConnector(provider=provider, email=email)
    _print(f"📬 拉取邮件: provider={provider} email={email} since={since.isoformat()}")
    try:
        emails = await connector.safe_fetch(since)
    except Exception as e:
        _print_err(f"fetch 抛异常（safe_fetch 应已隔离，请报告 bug）: {e!r}")
        return 1
    finally:
        await connector.close()

    if not emails:
        _print("📭 没有新邮件")
        return 0

    # 按时间倒序
    emails.sort(
        key=lambda em: em.get("received_at") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    for i, em in enumerate(emails[:limit], 1):
        _print(
            f"  [{i}] {em.get('received_at', '?')}  "
            f"{em.get('sender', '?')}  {em.get('subject', '?')[:60]}"
        )
    _print(f"\n✅ 共 {len(emails)} 封（显示前 {min(limit, len(emails))} 封）")
    return 0


def cmd_set_password(email: str, provider: str) -> int:
    """交互式写入 Keychain（不回显密码）。"""
    if provider != "qq":
        _print_err(f"--set-password 当前只支持 qq（{provider} 走 OAuth 流程，D2.5 spike）")
        return 1
    if not keychain.is_available():
        _print_err("当前平台不支持 Keychain（仅 macOS）")
        return 1
    code = getpass.getpass(f"请粘贴 {email} 的 QQ 授权码（不回显）: ").strip()
    if not code:
        _print_err("授权码为空，取消写入")
        return 1
    result = keychain.set_imap_password(email, code)
    if not result.ok:
        _print_err(f"写入 Keychain 失败: {result.error}")
        return 1
    _print(f"✅ 已写入 Keychain: service=my-ai-employee.imap.qq account={email}")
    return 0


def cmd_delete_password(email: str, provider: str) -> int:
    """删除 Keychain 凭证。"""
    if not keychain.is_available():
        _print_err("当前平台不支持 Keychain")
        return 1
    if provider == "qq":
        result = keychain.delete_password(keychain.SERVICE_IMAP_QQ, email)
    else:
        _print_err("--delete-password 当前只支持 qq")
        return 1
    if not result.ok:
        _print_err(f"删除失败: {result.error}")
        return 1
    _print(f"✅ Keychain 凭证已删除: {email}")
    return 0


# ===== argparse =====


def build_parser() -> argparse.ArgumentParser:
    """CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="test_imap",
        description="我的AI员工 — IMAP 适配器测试入口（D2.4）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  # 写授权码（交互式）
  python scripts/test_imap.py --set-password your@qq.com

  # 健康检查
  python scripts/test_imap.py --check --email your@qq.com

  # 拉取最近 7 天最近 10 封
  python scripts/test_imap.py --fetch-latest --email your@qq.com \\
      --days 7 --limit 10

D2 仅实现 QQ 邮箱（授权码模式）。Outlook/Gmail 需 OAuth 2.0，
推后到 D2.5 spike；如需，请联系维护者确认启动窗口。
""",
    )
    parser.add_argument(
        "--email",
        help="邮箱地址（如 your@qq.com）",
    )
    parser.add_argument(
        "--provider",
        choices=["qq"],  # D2 阶段只允许 qq；Outlook/Gmail 推后 D2.5
        default="qq",
        help="邮箱服务商（D2 仅 qq，Outlook/Gmail 推后 D2.5）",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="拉取最近几天的邮件（默认 7）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="最多显示几封（默认 10）",
    )
    # 操作模式（互斥）
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="只做健康检查（不取邮件）",
    )
    mode.add_argument(
        "--fetch-latest",
        action="store_true",
        help="拉取最近 N 天邮件",
    )
    mode.add_argument(
        "--set-password",
        action="store_true",
        help="交互式把授权码写进 Keychain",
    )
    mode.add_argument(
        "--delete-password",
        action="store_true",
        help="从 Keychain 删除授权码",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。argv 可注入便于单测。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.set_password:
            if not args.email:
                parser.error("--set-password 必须带 --email")
            return cmd_set_password(args.email, args.provider)
        if args.delete_password:
            if not args.email:
                parser.error("--delete-password 必须带 --email")
            return cmd_delete_password(args.email, args.provider)
        # 后续命令需要 email
        if not args.email:
            parser.error("--email 是必需的")

        if args.check:
            return asyncio.run(cmd_check(args.email, args.provider))
        if args.fetch_latest:
            return asyncio.run(cmd_fetch_latest(args.email, args.provider, args.days, args.limit))
    except KeyboardInterrupt:
        _print_err("用户中断（Ctrl-C）")
        return 130
    return 0  # pragma: no cover（argparse 互斥组保证走上面任一分支）


if __name__ == "__main__":
    sys.exit(main())
