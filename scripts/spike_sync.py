"""D3.3 — 1 万封性能 spike（mock IMAP → SQLCipher DB）。

用法：

    uv run python scripts/spike_sync.py --n 10000

设计：
    - 不连真 IMAP — 用 faker 生成 1 万封 mock 邮件
    - 写入 tmp SQLCipher DB（避免污染 prod data）
    - time.perf_counter() 端到端计时
    - 验收指标：< 30s

退出码：
    0 = < 30s 通过
    1 = > 30s 失败
    2 = 致命错误
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.sync import IMAPSync  # noqa: E402

# ===== Mock Connector（不走真 IMAP）=====


class SpikeMockConnector:
    """Spike 专用 mock connector：safe_fetch 返回 faker 邮件。"""

    def __init__(self, n: int, source: str = "qq") -> None:
        self._n = n
        self.source_name = source
        self.close_called = False

    async def safe_fetch(self, since: datetime) -> list[dict]:
        # 一次性生成 n 封 mock 邮件（uid 1..n）
        return [
            {
                "uid": i + 1,
                "subject": f"Spike email #{i + 1}",
                "sender": f"user{i + 1}@example.com",
                "received_at": int(datetime.now(UTC).timestamp() * 1000) - i * 1000,
                "raw_size": 1024,
                "message_id": f"<spike-{i + 1}@example.com>",
                "recipients": ["user@qq.com"],
                "labels": ["inbox"],
            }
            for i in range(self._n)
        ]

    async def close(self) -> None:
        self.close_called = True


# ===== 主流程 =====


def _print(msg: str) -> None:
    print(msg)


def _print_err(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)


def run_spike(n: int) -> int:
    """跑 spike：init DB → 跑 sync → 打印结果 → 返回退出码。"""
    import asyncio

    # 1) 临时 DB（D3.1 schema.sql 初始化 — 复用 D3.2.3 测试 fixture 思路）
    tmp_dir = Path("/tmp") / f"spike_sync_{int(time.time())}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_db = tmp_dir / "spike.db"

    # 写 fake keychain（让 Database.open 走 fake 不报错）
    from my_ai_employee.core import keychain

    # 临时 monkeypatch keychain
    original_get = keychain.get_db_password
    original_set = keychain.set_db_password

    def fake_get() -> keychain.KeychainResult:
        return keychain.KeychainResult(ok=True, value="spike-test-password")

    def fake_set(p: str) -> keychain.KeychainResult:
        return keychain.KeychainResult(ok=True)

    keychain.get_db_password = fake_get
    keychain.set_db_password = fake_set

    try:
        # 2) 初始化 DB schema（用 D3.1 schema.sql — executescript 支持多语句）
        db = Database.open(db_path=tmp_db)
        schema_path = (
            PROJECT_ROOT / "src" / "my_ai_employee" / "core" / "schema.sql"
        )
        if schema_path.exists():
            with open(schema_path, encoding="utf-8") as f:
                db._conn.executescript(f.read())  # noqa: SLF001
        else:
            _print_err(f"找不到 schema.sql: {schema_path}")
            return 2
        db.close()

        # 3) 跑 sync（计时）
        db = Database.open(db_path=tmp_db)
        try:
            connector = SpikeMockConnector(n=n)
            sync = IMAPSync(db, connector, batch_size=100)

            _print(f"🚀 Spike 启动：{n} 封 mock 邮件 → {tmp_db}")
            t0 = time.perf_counter()
            result = asyncio.run(sync.run_once())
            elapsed = time.perf_counter() - t0
            sync.close()
        finally:
            db.close()

        # 4) 打印结果
        _print("\n📊 Spike 结果")
        _print(f"  mock 邮件数: {n}")
        _print(f"  拉取: {result.total_fetched}")
        _print(f"  入库: {result.inserted}")
        _print(f"  跳过: {result.skipped}")
        _print(f"  失败: {result.failed}")
        _print(f"  sync 端到端耗时: {result.duration_seconds:.2f}s")
        _print(f"  含 DB 打开/关闭: {elapsed:.2f}s")
        _print(f"  性能: {n / result.duration_seconds:.0f} 封/秒")

        # 5) 验收
        passed = result.duration_seconds < 30.0
        if passed:
            _print(
                f"\n✅ Spike 通过：{result.duration_seconds:.2f}s < 30s"
            )
            return 0
        else:
            _print_err(
                f"Spike 失败：{result.duration_seconds:.2f}s ≥ 30s"
            )
            return 1

    except Exception as e:
        _print_err(f"Spike 崩溃: {e!r}")
        logger.exception("spike 失败")
        return 2
    finally:
        # 还原 keychain
        keychain.get_db_password = original_get
        keychain.set_db_password = original_set
        # 清理 tmp DB
        import shutil

        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="D3.3 — 1 万封 spike")
    parser.add_argument(
        "--n", type=int, default=10_000, help="mock 邮件数（默认 10000）"
    )
    args = parser.parse_args()
    return run_spike(args.n)


if __name__ == "__main__":
    sys.exit(main())
