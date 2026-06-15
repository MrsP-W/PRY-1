#!/usr/bin/env python3
"""D9.2 — Apple Notes 同步 CLI(子命令 sync / spike + 4 退出码契约).

承接 docs/v0.1-launch-plan.md §D9 + 沿 scripts/import_wechat.py 范本:

用法:
    # 正常同步(真 AppleScript 调 Notes.app,需显式 env 解锁)
    NOTES_REAL_NETWORK=1 uv run python scripts/sync_notes.py sync --max-rows 1

    # spike 模式(默认 30 笔 faker,Mock runner 跑通链路)
    uv run python scripts/sync_notes.py spike --n 30

退出码契约(沿 import_wechat.py 0/1/2/3):
    0 = 成功(parsed > 0 且 failed == 0;空 Notes 库也走 0)
    1 = 解析/alembic 失败(Alembic 不通过 / AppleScript 启动失败)
    2 = 业务失败(result.failed > 0)
    3 = 技术失败(OperationalError 透传,DB 锁/连接错误)

设计决策(2026-06-15 锁定):
    - 融合 sync_imap.py 的 subparsers(sync + spike 子命令)
    - 融合 import_wechat.py 的 4 退出码 + alembic 校验 + 单行输出
    - L1 幂等走 NoteStore.find_by_apple_id 预检(同事务内抛 NoteDuplicateError 兜底)
    - HTML 清洗走 adapters/apple_notes/html_cleaner.py(标准库 HTMLParser,无新依赖)
    - 失败隔离 per-note(单条失败不影响其他)
    - macOS TCC 风险:osascript 首次调需用户在 系统设置→隐私与安全性→自动化 授权

D3.3.3 教训应用:
    - except 范围窄化:只接 NotesConnectorError(AppleScript 失败)+ NoteStoreError(业务层)
    - OperationalError / DataError / InterfaceError 不捕获,透传 → exit 3
    - NoteDuplicateError 不算失败(已同步过,归 skipped)

D6.6 P2 修复应用:
    - 启动校验 alembic_version >= '0008_notes'(防漏迁移)
    - failed_items 走 stderr 详情(每项 apple_id + error_class + msg)

D9.6.3 P2-1 修复(2026-06-15 晨间精细代码审查):
    - per-note `except Exception` 拆分:`except OperationalError: raise` + `except (ValueError, TypeError)`
    - sync 模式(L145)与 spike 模式(L224)同构
    - 业务失败 vs 技术失败语义对齐:OperationalError 必走 exit 3(技术失败)
    - (ValueError, TypeError) 是 NoteStore 严判失败,走 failed_items + exit 2(业务失败)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.adapters.apple_notes.html_cleaner import clean_notes_html  # noqa: E402
from my_ai_employee.connectors.apple_notes import (  # noqa: E402
    NotesConnector,
    NotesConnectorError,
)
from my_ai_employee.core.alembic_helper import assert_min_revision  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.notes import NoteDuplicateError, NoteStore  # noqa: E402

# D9.2 决策:Apple Notes 同步所需最低 alembic revision(0008_notes)
_MIN_ALEMBIC_REVISION: str = "0008_notes"

# Spike B-1 预热新增:真实 AppleScript 同步默认 deny,沿 SMTP_REAL_NETWORK=1 范本。
_NOTES_REAL_NETWORK_ENV: str = "NOTES_REAL_NETWORK"
_NOTES_REAL_NETWORK_VALUE: str = "1"


# ===== 工具函数 =====


def _print(msg: str) -> None:
    """stdout 输出(单行结果)。"""
    print(msg)


def _print_err(msg: str) -> None:
    """stderr 输出(失败详情,前缀 ❌)。"""
    print(f"❌ {msg}", file=sys.stderr)


# ===== 子命令 sync =====


def cmd_sync(args: argparse.Namespace) -> int:
    """正常同步模式(真 AppleScript 调 Notes.app)。

    流程:
        1. Database.open() + make_sqlalchemy_engine + assert_min_revision(0008_notes)
        2. NotesConnector(osascript_runner=real).list_all_notes()
        3. per-note: get_note_body() → clean_notes_html() → NoteStore.insert()
        4. 失败隔离(per-note try/except,失败归 failed_items)
        5. 单行输出 + failed_items stderr

    Returns:
        退出码(0/1/2/3)
    """
    if os.environ.get(_NOTES_REAL_NETWORK_ENV) != _NOTES_REAL_NETWORK_VALUE:
        _print_err(
            f"真实 Apple Notes 同步需显式设置环境变量 "
            f"{_NOTES_REAL_NETWORK_ENV}={_NOTES_REAL_NETWORK_VALUE},"
            f"实际 env[{_NOTES_REAL_NETWORK_ENV}]="
            f"{os.environ.get(_NOTES_REAL_NETWORK_ENV)!r}。"
        )
        _print_err(
            f"示例:{_NOTES_REAL_NETWORK_ENV}={_NOTES_REAL_NETWORK_VALUE} "
            f"uv run python scripts/sync_notes.py sync --max-rows 1"
        )
        return 1

    db = Database.open(db_path=args.db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        try:
            assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
        except RuntimeError as e:
            _print_err(f"Alembic version 校验失败: {e}")
            _print_err("请先跑: alembic upgrade head")
            return 1

        store = NoteStore(sessionmaker(bind=engine))
        connector = NotesConnector(osascript_runner=NotesConnector._default_osascript_runner)

        parsed = inserted = skipped = failed = 0
        failed_items: list[dict[str, str]] = []

        for metadata in connector.list_all_notes():
            if args.max_rows is not None and parsed >= args.max_rows:
                break
            parsed += 1
            apple_note_id = metadata["apple_note_id"]
            try:
                # L1 幂等预检(同事务内 UNIQUE 兜底)
                if store.find_by_apple_id(apple_note_id) is not None:
                    skipped += 1
                    continue
                # 按需取 body + HTML 清洗
                raw_html = connector.get_note_body(apple_note_id)
                body, attachments = clean_notes_html(raw_html)
                # 构造 attachments_json(不含二进制,沿 D9.1 决策)
                attachments_json = json.dumps(attachments) if attachments else None
                store.insert(
                    apple_note_id=apple_note_id,
                    folder=metadata["folder"],
                    title=metadata["title"],
                    body=body,
                    updated_at_ms=metadata["modified_at_ms"],
                    is_private=metadata["is_private"],
                    attachments_json=attachments_json,
                )
                inserted += 1
            except NoteDuplicateError:
                # 并发场景兜底(预检后另一进程已插入)
                skipped += 1
            except OperationalError:
                # D9.6.3 P2-1:per-note OperationalError 必透传(D3.3.3 教训),
                # 让外层 try 收 → 整批记 exit 3(技术失败),不计入 failed_items
                raise
            except NotesConnectorError as e:
                failed += 1
                failed_items.append(
                    {
                        "apple_id": apple_note_id,
                        "error_class": type(e).__name__,
                        "msg": str(e),
                    }
                )
            except (ValueError, TypeError) as e:
                # 严判外的兜底(沿 D3.3.3 教训:范围窄化,OperationalError/InterfaceError/DataError 不在)
                failed += 1
                failed_items.append(
                    {
                        "apple_id": apple_note_id,
                        "error_class": type(e).__name__,
                        "msg": str(e),
                    }
                )
    except OperationalError as e:
        # D3.3.3 教训:OperationalError 必透传(DB 锁 / 连接错误)
        _print_err(f"数据库技术失败(DB 锁或连接错误): {e}")
        return 3
    except NotesConnectorError as e:
        # 整批失败(AppleScript 启动失败 / 解析层错误)
        _print_err(f"AppleScript 失败: {e}")
        return 1
    finally:
        db.close()

    _print(f"notes sync: parsed={parsed} inserted={inserted} skipped={skipped} failed={failed}")
    if failed_items:
        for item in failed_items:
            _print_err(
                f"failed_item: apple_id={item['apple_id']!r} "
                f"error_class={item['error_class']!r} msg={item['msg']!r}"
            )

    if failed > 0:
        return 2
    return 0


# ===== 子命令 spike =====


def cmd_spike(args: argparse.Namespace) -> int:
    """Spike 模式(默认 30 笔 faker 笔记,Mock runner 跑通链路,验证不真调 AppleScript).

    流程:
        1. Database.open() + alembic 校验
        2. 生成 N 笔 faker 笔记(apple_note_id = x-coredata://test/spike-NNNN)
        3. NoteStore.insert(不走 NotesConnector,直接 RawNote → insert)
        4. 单行输出 spike 模式标记

    Returns:
        退出码(0/1/2/3)
    """
    db = Database.open(db_path=args.db_path)
    try:
        engine = make_sqlalchemy_engine(db)
        try:
            assert_min_revision(engine, _MIN_ALEMBIC_REVISION)
        except RuntimeError as e:
            _print_err(f"Alembic version 校验失败: {e}")
            _print_err("请先跑: alembic upgrade head")
            return 1

        store = NoteStore(sessionmaker(bind=engine))

        parsed = inserted = skipped = failed = 0
        for i in range(args.n):
            parsed += 1
            apple_note_id = f"x-coredata://test/spike-{i:04d}"
            try:
                if store.find_by_apple_id(apple_note_id) is not None:
                    skipped += 1
                    continue
                store.insert(
                    apple_note_id=apple_note_id,
                    folder="spike-folder",
                    title=f"Spike Note {i:04d}",
                    body=f"Spike body content {i} — 测试笔记,不含真实数据。",
                    updated_at_ms=int(time.time() * 1000) - i * 1000,
                    is_private=False,
                )
                inserted += 1
            except NoteDuplicateError:
                skipped += 1
            except OperationalError:
                # D9.6.3 P2-1:spike 模式 per-note OperationalError 必透传,
                # 与 sync 模式同构(D3.3.3 教训 + D9.6.3 P2-1 修复)
                raise
            except (ValueError, TypeError) as e:
                # 严判外的兜底(OperationalError 已在前面透传,这里只接业务严判失败)
                failed += 1
                _print_err(f"spike failed: apple_id={apple_note_id!r} err={e!r}")
    except OperationalError as e:
        _print_err(f"数据库技术失败(DB 锁或连接错误): {e}")
        return 3
    finally:
        db.close()

    _print(
        f"notes spike: parsed={parsed} inserted={inserted} "
        f"skipped={skipped} failed={failed} n={args.n}"
    )
    if failed > 0:
        return 2
    return 0


# ===== argparse =====


def _build_parser() -> argparse.ArgumentParser:
    """构造 argparse(子命令 sync + spike)。"""
    parser = argparse.ArgumentParser(description="D9.2 — Apple Notes 同步 CLI(子命令 sync / spike)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # sync 子命令
    sync_p = sub.add_parser("sync", help="正常同步(真 AppleScript 调 Notes.app)")
    sync_p.add_argument(
        "--max-rows",
        type=_positive_int,
        default=None,
        help="最多处理 N 条 Notes(真实 spike 推荐 1,默认不限)",
    )
    sync_p.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径,默认主库")
    sync_p.set_defaults(func=cmd_sync)

    # spike 子命令
    spike_p = sub.add_parser("spike", help="性能 spike(faker 笔记入库,Mock runner 跑通链路)")
    spike_p.add_argument(
        "--n", type=int, default=30, help="faker 笔记数(默认 30,沿 D5.6.4 spike 范本)"
    )
    spike_p.add_argument("--db-path", type=Path, default=None, help="可选 DB 路径,默认主库")
    spike_p.set_defaults(func=cmd_spike)

    return parser


def _positive_int(value: str) -> int:
    """argparse type:正整数。"""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


def main(argv: list[str] | None = None) -> int:
    """CLI 入口(沿 sync_imap.py:main 范本,int() 收窄 mypy Any)。"""
    args = _build_parser().parse_args(argv)
    # D3.3.2 修复:args.func 是 argparse set_defaults 注入的 callable,
    # mypy 推断为 Any — main() 声明返回 int,包裹 int() 强制收窄
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
