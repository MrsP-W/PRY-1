"""刷新 AI 每日情报的本地只读缓存。

此脚本只发起白名单 HTTPS GET，不读取账号/Keychain，不调用 LLM，也不发送任何
内容到外部。由独立的 one-shot LaunchAgent 每小时调用；本脚本本身不启停任何
业务服务。
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from my_ai_employee.news import FileNewsStore, NewsService
from my_ai_employee.news.models import RefreshResult


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
    store = FileNewsStore(args.output) if args.output else FileNewsStore()
    try:
        result = NewsService(store=store).refresh()
    except Exception:  # noqa: BLE001 — one-shot 必须留下可用回执而不泄露异常内容
        _append_runtime_error(store)
        return _emit_runtime_error(args.format)

    try:
        _append_result(store, result)
    except Exception:  # noqa: BLE001 — 回执不可写时不可伪报为一次成功运行
        _append_runtime_error(store)
        return _emit_runtime_error(args.format)

    payload = _result_payload(result)
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


def _append_result(store: FileNewsStore, result: RefreshResult) -> None:
    """将结果映射为固定、脱敏的 P3 运行回执。"""
    store.append_run(
        at=_timestamp(),
        outcome=_outcome(result),
        success=result.success,
        degraded=result.degraded,
        item_count=result.item_count,
        source_statuses=(
            {
                "source_id": status.source_id,
                "status": status.status,
                "item_count": status.item_count,
            }
            for status in result.source_statuses
        ),
    )


def _append_runtime_error(store: FileNewsStore) -> None:
    """尽力记录运行异常；写回执本身失败时仍维持稳定 CLI 返回码。"""
    try:
        store.append_run(
            at=_timestamp(),
            outcome="runtime_error",
            success=False,
            degraded=False,
            item_count=0,
            source_statuses=(),
        )
    except Exception:  # noqa: BLE001 — 无法再持久化时禁止将异常文本打到 stdout
        return


def _outcome(result: RefreshResult) -> str:
    """给 P3 汇总器提供互斥、稳定的本轮结论。"""
    if result.success and result.degraded:
        return "degraded"
    if result.success:
        return "success"
    if result.source_statuses or result.degraded or result.wrote_snapshot:
        return "all_sources_failed"
    return "overlap"


def _result_payload(result: RefreshResult) -> dict[str, Any]:
    """保持既有 CLI JSON 契约，不把 P3 内部 outcome 暴露给调用方。"""
    return {
        "success": result.success,
        "wrote_snapshot": result.wrote_snapshot,
        "kept_previous_snapshot": result.kept_previous_snapshot,
        "degraded": result.degraded,
        "item_count": result.item_count,
        "sources": [status.to_dict() for status in result.source_statuses],
    }


def _emit_runtime_error(output_format: str) -> int:
    """输出稳定的运行异常结果，绝不带出异常对象、URL 或新闻内容。"""
    payload = {
        "success": False,
        "wrote_snapshot": False,
        "kept_previous_snapshot": False,
        "degraded": False,
        "item_count": 0,
        "sources": [],
    }
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print("AI 每日情报刷新运行异常，未写入缓存")
    return 2


def _timestamp() -> str:
    """生成与现有快照一致的 UTC 时间格式。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
