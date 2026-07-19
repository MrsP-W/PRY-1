#!/usr/bin/env python3
"""本地导入与输出 Codex 对话摘要笔记。

输入 JSONL 每行格式：
    {"thread_id":"...","title":"...","summary":"...","ended_at_ms":1784400000000}

安全边界：
    - 默认 ``import`` 仅校验与预览，不写数据库；必须显式传 ``--apply`` 才落库。
    - 不读取 Codex 桌面端、浏览器历史或任何远程会话；调用方必须提供已总结的 JSONL。
    - ``show`` 仅查询本地数据库记录，按本机自然日输出每次对话的总结。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.exc import IntegrityError, OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.core.alembic_helper import assert_min_revision  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.notes import NoteStore  # noqa: E402
from my_ai_employee.notes.codex_conversations import (  # noqa: E402
    CodexConversationNotesService,
    load_conversation_summaries_jsonl,
)

_MIN_ALEMBIC_REVISION = "0017_codex_conversation_notes"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地 Codex 对话摘要笔记导入与按日输出")
    sub = parser.add_subparsers(dest="command", required=True)

    import_parser = sub.add_parser("import", help="校验或显式导入已总结的 JSONL 对话")
    import_parser.add_argument("--input", required=True, type=Path, help="UTF-8 JSONL 输入文件")
    import_parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径，默认主库")
    import_parser.add_argument(
        "--apply",
        action="store_true",
        help="显式写入本地数据库；未传时只校验 JSONL，不写入",
    )
    import_parser.set_defaults(func=cmd_import)

    show_parser = sub.add_parser("show", help="输出某日的 Codex 对话总结 Markdown")
    show_parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="本机自然日，格式 YYYY-MM-DD（默认今天）",
    )
    show_parser.add_argument("--limit", type=int, default=100, help="最多输出条数 [1,1000]")
    show_parser.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径，默认主库")
    show_parser.set_defaults(func=cmd_show)
    return parser


def _open_service(db_path: Path | None) -> tuple[Database, CodexConversationNotesService]:
    db = Database.open(db_path=db_path)
    engine = make_sqlalchemy_engine(db)
    assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
    store = NoteStore(sessionmaker(bind=engine))
    return db, CodexConversationNotesService(store)


def cmd_import(args: argparse.Namespace) -> int:
    """校验 JSONL；仅在 ``--apply`` 时写入本地 Notes。"""
    try:
        records = load_conversation_summaries_jsonl(args.input)
    except ValueError as exc:
        print(f"❌ Codex 对话 JSONL 校验失败: {exc}", file=sys.stderr)
        return 1

    if not args.apply:
        print(
            f"codex conversations import: parsed={len(records)} apply=false "
            "（仅校验，未写入；如需导入请追加 --apply）"
        )
        return 0

    db: Database | None = None
    try:
        db, service = _open_service(args.db_path)
        result = service.import_summaries(records)
    except ValueError as exc:
        print(f"❌ Codex 对话导入拒绝: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"❌ Alembic version 校验失败: {exc}", file=sys.stderr)
        return 1
    except (IntegrityError, OperationalError) as exc:
        print(f"❌ 数据库技术失败(DB 锁或连接错误): {exc}", file=sys.stderr)
        return 3
    finally:
        if db is not None:
            db.close()

    print(
        "codex conversations import: "
        f"parsed={len(records)} created={result.created} updated={result.updated}"
    )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """查询并输出某日的每次 Codex 对话总结。"""
    if type(args.limit) is bool or not isinstance(args.limit, int) or not 1 <= args.limit <= 1000:
        print("❌ --limit 必须是 [1,1000] 的整数", file=sys.stderr)
        return 1
    try:
        requested_day = NoteStore._validate_daily_note_date(args.date)
    except (TypeError, ValueError) as exc:
        print(f"❌ 参数或笔记内容无效: {exc}", file=sys.stderr)
        return 1

    db: Database | None = None
    try:
        db, service = _open_service(args.db_path)
        markdown = service.render_daily_markdown(requested_day, limit=args.limit)
    except (TypeError, ValueError) as exc:
        print(f"❌ 参数或笔记内容无效: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"❌ Alembic version 校验失败: {exc}", file=sys.stderr)
        return 1
    except OperationalError as exc:
        print(f"❌ 数据库技术失败(DB 锁或连接错误): {exc}", file=sys.stderr)
        return 3
    finally:
        if db is not None:
            db.close()

    print(markdown, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
