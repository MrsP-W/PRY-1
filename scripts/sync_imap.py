"""D3.3 — IMAP 同步 CLI（QQ / Outlook / Gmail）。

用法：

    # 正常同步
    uv run python scripts/sync_imap.py --provider qq --email user@qq.com

    # spike 模式（生成 1 万封 mock 入库到 tmp DB，验证性能 < 30s）
    uv run python scripts/sync_imap.py --spike 10000

退出码：
    0 = 成功（即便有 failed 计数，只要进程完成就是 0 — D3.3 失败隔离设计）
    1 = 参数错
    2 = 致命错误（DB 打开失败 / Keychain 缺失）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 让 scripts/ 能 import src/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.connectors.imap import IMAPConnector  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sync import IMAPSync, SyncResult  # noqa: E402


def _print(msg: str) -> None:
    """stdout 输出（与 stderr 日志分离）。"""
    print(msg)


def _print_err(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)


def cmd_sync(args: argparse.Namespace) -> int:
    """正常同步模式（真 IMAPConnector）。"""
    db = Database.open()
    try:
        connector = IMAPConnector(provider=args.provider, email=args.email)
        sync = IMAPSync(db, connector, batch_size=args.batch_size)
        result = asyncio.run(sync.run_once())
        sync.close()
        _print_sync_result(result)
        return 0
    except Exception as e:
        _print_err(f"同步失败: {e!r}")
        return 2
    finally:
        db.close()


def cmd_spike(args: argparse.Namespace) -> int:
    """Spike 模式（1 万封 faker mock 入库到 tmp DB）。"""
    from my_ai_employee.core.sync import IMAPSync  # noqa: F401
    from scripts.spike_sync import run_spike  # noqa: E402

    return run_spike(args.n)


def _print_sync_result(r: SyncResult) -> None:
    _print("\n📬 同步结果")
    _print(f"  拉取: {r.total_fetched} 封")
    _print(f"  入库: {r.inserted} 封")
    _print(f"  跳过: {r.skipped} 封（UNIQUE 冲突）")
    _print(f"  失败: {r.failed} 封")
    _print(f"  新 last_uid: {r.new_last_uid}")
    _print(f"  耗时: {r.duration_seconds:.2f}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="D3.3 — IMAP 邮件同步入库 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # sync 子命令
    sync_p = sub.add_parser("sync", help="正常同步（真 IMAP）")
    sync_p.add_argument("--provider", required=True, choices=["qq", "outlook", "gmail"])
    sync_p.add_argument("--email", required=True, help="邮箱地址")
    sync_p.add_argument("--batch-size", type=int, default=100, help="每批 commit 大小")
    sync_p.set_defaults(func=cmd_sync)

    # spike 子命令
    spike_p = sub.add_parser("spike", help="性能 spike（mock 入库 tmp DB）")
    spike_p.add_argument("--n", type=int, default=10_000, help="mock 邮件数（默认 1 万）")
    spike_p.set_defaults(func=cmd_spike)

    args = parser.parse_args()
    # ⚠️ D3.3.2 修复：args.func 是 argparse set_defaults 注入的 callable，
    # mypy 推断为 Any — main() 声明返回 int，包裹 int() 强制收窄
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
