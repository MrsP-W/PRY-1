"""刷新 AI 每日情报的本地只读缓存。

此脚本只发起白名单 HTTPS GET，不读取账号/Keychain，不调用 LLM，也不发送任何
内容到外部。由独立的 one-shot LaunchAgent 每小时调用；本脚本本身不启停任何
业务服务。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from my_ai_employee.news import FileNewsStore, NewsService


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数。"""
    parser = argparse.ArgumentParser(description="刷新 AI 每日情报本地缓存（公开来源，只读）")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="覆盖缓存 JSON 路径（默认 Application Support/MyAIEmployee/news/latest.json）",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="运行结果输出格式",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行一次刷新；全部来源失败或已有并发刷新时返回非零。"""
    args = build_parser().parse_args(argv)
    service = NewsService(store=FileNewsStore(args.output) if args.output else None)
    result = service.refresh()
    payload = {
        "success": result.success,
        "wrote_snapshot": result.wrote_snapshot,
        "kept_previous_snapshot": result.kept_previous_snapshot,
        "degraded": result.degraded,
        "item_count": result.item_count,
        "sources": [status.to_dict() for status in result.source_statuses],
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif result.success and result.degraded:
        print(f"AI 每日情报刷新降级：本轮无合格条目，保留上一份 {result.item_count} 条缓存")
    elif result.success and result.item_count == 0:
        print("AI 每日情报已刷新：来源可用，但本轮无近 72 小时合格条目")
    elif result.success:
        print(f"AI 每日情报已刷新：{result.item_count} 条，写入本地缓存")
    elif result.degraded:
        print("AI 每日情报刷新失败：所有来源不可用，已保留上一份缓存并标记降级")
    elif result.source_statuses:
        print("AI 每日情报刷新失败：所有来源不可用，已保留上一份缓存")
    else:
        print("AI 每日情报刷新跳过：已有刷新进程在运行")
    return 0 if result.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
