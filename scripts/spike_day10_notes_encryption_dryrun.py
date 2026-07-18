#!/usr/bin/env python3
"""Day 10 Phase 3.5 — Notes 真加密生产链路 dry-run spike.

目的(用户 2026-07-02 路径 A Phase 3.5 授权):
    - 端到端验证:mock Keychain master key + 临时 SQLite DB + `ENABLE_NOTES_ENCRYPTION=1`
      → NoteStore insert Impl cipher → 库内认证 `enc:v2:` 前缀
      → /api/notes/pending 解密展示明文
      → 菜单栏 NoteConfirmServiceImpl.list_pending_confirm 解密返回明文
    - 不写 shell profile · 不写 `ENABLE_NOTES_ENCRYPTION=1` 到环境
    - 不动 `~/Library/Application Support/my-ai-employee/data.db`(生产主库)
    - 不启用 Notes 真加密生产 — 仅 spike 进程内 opt-in

沿用范本:
    - Phase 1.2 fallback 集成测试(`tests/db/test_notes_encryption_store.py`)
    - Phase 1.2 Dashboard 解密展示测试(`tests/dashboard/test_api.py`)
    - Phase 1.2 菜单栏解密列表测试(`tests/menu_bar/test_note_confirm_service.py`)

4 退出码契约(沿 `scripts/spike_d8_1000.py` D8 spike 范本):
    0 = 成功(spike 跑通 + 统计输出)
    1 = 准备失败(env / 路径错)
    2 = 业务失败(库内未发现 `enc:v2:` 前缀 或 UI 仍返回密文)
    3 = 技术失败(SQLAlchemy / 密钥长度不够 / cipher 初始化失败)

用法:
    uv run python scripts/spike_day10_notes_encryption_dryrun.py
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Day 10 Phase 3.5 Notes 真加密 dry-run spike (mock Keychain + 临时 DB)",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="保留临时 SQLite 文件(默认跑完删除,便于检查)",
    )
    return parser.parse_args()


def _mock_master_key_hex() -> str:
    """生成 32 字节随机 hex 字符串(>= 32 hex chars,严判 notes_encryption._DERIVED_KEY_LENGTH 32 字节下限).

    撞坑 #65 严判:必须 hex 字符 + 偶数长度 + >= 16 bytes。32 bytes 提供足量熵。
    """
    import secrets

    return secrets.token_hex(32)


def _patch_load_notes_master_key(monkeypatch_module: Any, hex_key: str) -> None:
    """monkeypatch `load_notes_master_key` 返回 bytes(从 hex 解码)。

    进程内 patch,不污染 macOS Keychain(spike 跑完 sys.exit 进程销毁)。
    """
    master_key = bytes.fromhex(hex_key)
    from my_ai_employee.core import notes_encryption

    def _fake_loader() -> bytes | None:
        return master_key

    monkeypatch_module.setattr(
        notes_encryption,
        "load_notes_master_key",
        _fake_loader,
    )


def _enable_in_process(monkeypatch_module: Any) -> None:
    """进程内设置 `ENABLE_NOTES_ENCRYPTION=1`(仅 spike 进程有效,不写 shell profile)."""
    monkeypatch_module.setenv("ENABLE_NOTES_ENCRYPTION", "1")


def _create_temp_db() -> tuple[str, Any]:
    """创建临时 SQLite file DB + engine + session_factory。

    Returns:
        (db_path, session_factory)
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    tmpdir = tempfile.mkdtemp(prefix="spike_day10_notes_")
    db_path = os.path.join(tmpdir, "notes.db")
    # 临时 DB 文件不加密(spike 仅验证加密逻辑,撞坑 #65 严判沿用)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    # alembic upgrade head 应用 schema(沿 [src/my_ai_employee/db/notes.py] 范本)
    from my_ai_employee.core.models import Base
    from my_ai_employee.db.notes import Note  # noqa: F401 — 必须 import 才注册到 Base.metadata

    # 直接 create_all(spike 不跑 alembic upgrade,沿 tests/db/test_notes_encryption_store.py:23-31 范本)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return db_path, session_factory


def _seed_plaintext_note(
    session_factory: Any,
    *,
    apple_note_id: str,
    title: str,
    body: str,
    synced_at_ms: int = 1_700_000_000_000,
) -> int:
    """直接 SQLAlchemy session.add 写入明文 note(模拟旧版 NoteStore 未加密路径)。"""
    from my_ai_employee.db.notes import Note

    with session_factory() as session:
        note = Note(
            apple_note_id=apple_note_id,
            folder="Notes",
            title=title,
            body=body,
            is_private=0,  # 直接 SQLAlchemy 写入,不经过 _validate_is_private 守卫
            tags=None,
            synced_at_ms=synced_at_ms,
            updated_at_ms=synced_at_ms,
            sync_status="NEW",
            needs_confirm=1,
            candidate_match_id=None,
        )
        session.add(note)
        session.commit()
        return int(note.id)


def _seed_encrypted_note(
    store: Any,
    *,
    apple_note_id: str,
    title: str,
    body: str,
    synced_at_ms: int = 1_700_000_000_001,
) -> int:
    """NoteStore.insert 走 Impl cipher(库内落认证 `enc:v2:` 前缀)."""
    result = store.insert(
        apple_note_id=apple_note_id,
        folder="Notes",
        title=title,
        body=body,
        is_private=False,
        tags=None,
        synced_at_ms=synced_at_ms,
        updated_at_ms=synced_at_ms,
    )
    return int(result.id)


def _run_spike(args: argparse.Namespace) -> int:
    """spike 主流程。

    Returns:
        退出码(0/1/2/3)
    """
    # ---- 0. 准备:进程内 opt-in + mock Keychain ----
    from _pytest.monkeypatch import MonkeyPatch  # 复用 pytest 内置 helper

    mp = MonkeyPatch()
    try:
        _enable_in_process(mp)
        hex_key = _mock_master_key_hex()
        _patch_load_notes_master_key(mp, hex_key)

        # ---- 1. 验证 opt-in 链路 ----
        from my_ai_employee.core.notes_encryption import (
            NotesCipherImpl,
            build_notes_cipher,
            is_notes_encryption_enabled,
            load_notes_master_key,
        )

        assert is_notes_encryption_enabled() is True, "ENABLE_NOTES_ENCRYPTION 未生效"
        loaded_key = load_notes_master_key()
        if loaded_key is None or len(loaded_key) < 16:
            print(f"[FAIL] load_notes_master_key 返回 None 或过短: {loaded_key!r}", file=sys.stderr)
            return 1
        cipher = build_notes_cipher(loaded_key)
        if not isinstance(cipher, NotesCipherImpl):
            print(
                f"[FAIL] build_notes_cipher 返回 Stub 而非 Impl: {type(cipher).__name__}",
                file=sys.stderr,
            )
            return 1
        print(f"[OK] opt-in 链路就绪: cipher={type(cipher).__name__}, key_len={len(loaded_key)}")

        # ---- 2. 创建临时 SQLite DB ----
        db_path, session_factory = _create_temp_db()
        print(f"[OK] 临时 DB: {db_path}")

        try:
            # ---- 3. seed 2 条 note:1 条明文(模拟历史)+ 1 条新加密(走 NoteStore.insert) ----
            from my_ai_employee.db.notes import NoteStore

            # 默认构造 NoteStore → build_notes_cipher(load_notes_master_key()) → Impl(Phase 1.1 P1)
            store = NoteStore(session_factory)

            legacy_id = _seed_plaintext_note(
                session_factory,
                apple_note_id="x-coredata://ICNote/LEGACY-DRYRUN",
                title="历史明文标题",
                body="历史明文正文,无 enc: 前缀",
            )

            encrypted_id = _seed_encrypted_note(
                store,
                apple_note_id="x-coredata://ICNote/ENCRYPTED-DRYRUN",
                title="新加密标题",
                body="新加密正文,应自动落 enc:v2: 前缀",
            )

            # ---- 4. 库内直查:验证 legacy 是明文,encrypted 是 enc:v2: 前缀 ----
            from sqlalchemy import select

            from my_ai_employee.db.notes import Note

            with session_factory() as session:
                legacy_row = session.execute(select(Note).where(Note.id == legacy_id)).scalar_one()
                encrypted_row = session.execute(
                    select(Note).where(Note.id == encrypted_id)
                ).scalar_one()

            if legacy_row.title.startswith("enc:v2:") or legacy_row.body.startswith("enc:v2:"):
                print(
                    f"[FAIL] legacy note 不应该有 enc:v2: 前缀: title={legacy_row.title[:20]!r}",
                    file=sys.stderr,
                )
                return 2
            if not encrypted_row.title.startswith("enc:v2:") or not encrypted_row.body.startswith(
                "enc:v2:"
            ):
                print(
                    f"[FAIL] 新加密 note 应该有 enc:v2: 前缀: title={encrypted_row.title[:20]!r}",
                    file=sys.stderr,
                )
                return 2
            print("[OK] 库内前缀严判: legacy=plaintext, encrypted=enc:v2: 前缀")

            # ---- 5. NoteStore.list_all + get_by_id 验证解密(沿 Phase 1.2 test_impl_cipher_mixed_plaintext_and_encrypted 范本)----
            # 注意:NoteStore.insert 新 note 无指纹冲突 → needs_confirm=0,
            # list_by_needs_confirm 仅返回 needs_confirm=1,故验证改用 list_all + get_by_id
            all_notes = store.list_all(limit=10)
            all_by_id = {n.id: n for n in all_notes}
            if legacy_id not in all_by_id:
                print(f"[FAIL] legacy_id={legacy_id} 不在 list_all 列表中", file=sys.stderr)
                return 2
            if encrypted_id not in all_by_id:
                print(f"[FAIL] encrypted_id={encrypted_id} 不在 list_all 列表中", file=sys.stderr)
                return 2
            legacy_loaded = all_by_id[legacy_id]
            encrypted_loaded = all_by_id[encrypted_id]
            if (
                legacy_loaded.title != "历史明文标题"
                or legacy_loaded.body != "历史明文正文,无 enc: 前缀"
            ):
                print(f"[FAIL] legacy 解密错: title={legacy_loaded.title!r}", file=sys.stderr)
                return 2
            if (
                encrypted_loaded.title != "新加密标题"
                or encrypted_loaded.body != "新加密正文,应自动落 enc:v2: 前缀"
            ):
                print(f"[FAIL] encrypted 解密错: title={encrypted_loaded.title!r}", file=sys.stderr)
                return 2

            # get_by_id 单独验证 encrypted note 解密(更严格)
            encrypted_by_id = store.get_by_id(encrypted_id)
            if encrypted_by_id is None or encrypted_by_id.title != "新加密标题":
                print(
                    f"[FAIL] get_by_id(encrypted) 解密错: {encrypted_by_id!r}",
                    file=sys.stderr,
                )
                return 2
            # 严判无 enc:v2: 前缀泄露
            if legacy_loaded.title.startswith("enc:v2:") or encrypted_loaded.title.startswith(
                "enc:v2:"
            ):
                print(
                    f"[FAIL] 解密后仍含 enc:v2: 前缀: legacy={legacy_loaded.title[:20]!r}, "
                    f"encrypted={encrypted_loaded.title[:20]!r}",
                    file=sys.stderr,
                )
                return 2
            print(
                "[OK] list_all + get_by_id 解密: 2 条全部明文返回 "
                "(legacy 明文 + encrypted 解密,无 enc:v2: 前缀泄露)"
            )

            # ---- 6. 菜单栏 NoteConfirmServiceImpl.list_pending_confirm 验证(仅 legacy,因为 encrypted 无 needs_confirm=1)----
            from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

            svc = NoteConfirmServiceImpl(note_store=store)
            confirm_items = svc.list_pending_confirm(limit=10)
            confirm_titles = {item.get("title") for item in confirm_items if isinstance(item, dict)}
            if "历史明文标题" not in confirm_titles:
                print(
                    f"[FAIL] 菜单栏 list_pending_confirm 未包含历史明文标题: {confirm_titles}",
                    file=sys.stderr,
                )
                return 2
            # encrypted 不在 list_pending_confirm 因 needs_confirm=0,但其解密路径在步骤 5 已验证
            # 严判无 enc:v2: 前缀泄露
            for item in confirm_items:
                title = item.get("title", "") if isinstance(item, dict) else ""
                if title.startswith("enc:v2:"):
                    print(f"[FAIL] 菜单栏泄露密文: title={title[:20]!r}", file=sys.stderr)
                    return 2
            print(
                f"[OK] 菜单栏 NoteConfirmServiceImpl 解密: {len(confirm_items)} 条明文 "
                f"(legacy 明文为主,encrypted 不在 pending 因 needs_confirm=0)"
            )

            # ---- 7. Dashboard /api/notes/pending payload 验证(沿 Phase 1.2 test_api 范本 · 仅 legacy)----
            from my_ai_employee.dashboard.context import DashboardContext
            from my_ai_employee.dashboard.responses import build_notes_pending_payload

            # 最小 DashboardContext(仅 note_confirm_service 必须)
            class _StubExpense:
                def get_anomaly_count(self) -> int:
                    return 0

                def get_recent_anomalies(self, limit: int = 10) -> list[dict[str, Any]]:
                    return []

            ctx = DashboardContext(
                note_confirm_service=svc,
                expense_service=_StubExpense(),
                keychain_probe=lambda _s: True,
            )
            payload = build_notes_pending_payload(ctx, limit=10)
            payload_items = payload.get("items", [])
            payload_titles = {item.get("title") for item in payload_items if isinstance(item, dict)}
            if "历史明文标题" not in payload_titles:
                print(
                    f"[FAIL] Dashboard payload 未包含历史明文标题: {payload_titles}",
                    file=sys.stderr,
                )
                return 2
            # 严判字段白名单 + 无密文泄露
            expected_keys = {
                "apple_note_id",
                "title",
                "folder",
                "synced_at_ms",
                "candidate_match_id",
                "needs_confirm",
            }
            for item in payload_items:
                if not isinstance(item, dict):
                    continue
                title = item.get("title", "")
                if title.startswith("enc:v2:"):
                    print(
                        f"[FAIL] Dashboard payload 泄露密文: title={title[:20]!r}", file=sys.stderr
                    )
                    return 2
                keys = set(item.keys())
                if keys != expected_keys:
                    extra = keys - expected_keys
                    missing = expected_keys - keys
                    if extra or missing:
                        print(
                            f"[FAIL] Dashboard payload 字段不匹配: extra={extra}, missing={missing}",
                            file=sys.stderr,
                        )
                        return 2
            print(
                f"[OK] Dashboard payload: {len(payload_items)} 条明文,字段白名单严判通过 "
                f"(legacy 为主,encrypted 解密路径在步骤 5 已验证)"
            )

            # ---- 8. 收官统计 ----
            print()
            print("=" * 60)
            print("Day 10 Phase 3.5 Notes 真加密 dry-run spike — 全绿")
            print("=" * 60)
            print("  opt-in: ENABLE_NOTES_ENCRYPTION=1 (进程内)")
            print(f"  master key: {len(loaded_key)} bytes (mock,run-end 自动销毁)")
            print("  cipher: NotesCipherImpl (Phase 1.1 P1 默认)")
            print(f"  DB: 临时 SQLite file (跑完{'保留' if args.keep_db else '删除'})")
            print("  notes: 2 (1 legacy plaintext + 1 new authenticated enc:v2:)")
            print("  NoteStore.list_all + get_by_id 解密: 2 条明文")
            print(
                "  NoteConfirmServiceImpl.list_pending_confirm: 1 条明文 (legacy 为主,encrypted needs_confirm=0)"
            )
            print("  Dashboard /api/notes/pending payload: 1 条明文 + 6 字段白名单")
            print("  生产主库未触碰 ~/Library/Application Support/my-ai-employee/data.db")
            print("  shell profile 未写 ENABLE_NOTES_ENCRYPTION=1")
            print()
            return 0
        finally:
            # ---- 9. 清理临时 DB(默认删除, --keep-db 保留)----
            if not args.keep_db:
                tmpdir = Path(db_path).parent
                shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        mp.undo()


def main() -> int:
    args = _parse_args()
    return _run_spike(args)


if __name__ == "__main__":
    sys.exit(main())
