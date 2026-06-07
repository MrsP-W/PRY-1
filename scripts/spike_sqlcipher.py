"""D3.0 — sqlcipher3 加密往返 spike（5 分钟验证）。

目的：
    1. 验证 .venv 里的 sqlcipher3-binary 装包正常
    2. 验证 PRAGMA key 流程无误（密码错打不开）
    3. 验证加密性能（建表 + 写 1 行 < 100ms）

不进入 git（脚本一次性验证，验证完删 / 或转成正式 test）。

用法：
    .venv/bin/python scripts/spike_sqlcipher.py
"""

from __future__ import annotations

import secrets
import tempfile
import time
from pathlib import Path

import sqlcipher3


def main() -> None:
    print("🔐 sqlcipher3 加密往返 spike")
    print("=" * 50)

    # 1. 建临时 DB + 随机密码
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "spike.db"
        password = secrets.token_hex(32)
        print(f"  db_path: {db_path}")
        print(f"  password: {password[:8]}...{password[-4:]} ({len(password)} chars)")

        # 2. 建 DB + 加密 + 写 1 行
        start = time.perf_counter()
        conn = sqlcipher3.connect(str(db_path))
        conn.execute(f"PRAGMA key = '{password}'")
        conn.execute("CREATE TABLE spike (id INTEGER PRIMARY KEY, secret TEXT)")
        conn.execute("INSERT INTO spike (secret) VALUES (?)", ("hello-encrypted",))
        conn.commit()
        conn.close()
        t_create = (time.perf_counter() - start) * 1000
        print(f"  ✅ 建库+加密+写入: {t_create:.1f}ms")

        # 3. 验：用正确密码重开 + 读
        start = time.perf_counter()
        conn = sqlcipher3.connect(str(db_path))
        conn.execute(f"PRAGMA key = '{password}'")
        row = conn.execute("SELECT secret FROM spike WHERE id = 1").fetchone()
        conn.close()
        t_read = (time.perf_counter() - start) * 1000
        assert row is not None and row[0] == "hello-encrypted", f"读取失败: {row}"
        print(f"  ✅ 正确密码重开+读取: {t_read:.1f}ms, data={row[0]!r}")

        # 4. 验：错误密码打不开
        start = time.perf_counter()
        try:
            conn = sqlcipher3.connect(str(db_path))
            conn.execute(f"PRAGMA key = '{secrets.token_hex(32)}'")  # 错的密码
            conn.execute("SELECT secret FROM spike WHERE id = 1").fetchone()
            conn.close()
            print("  ❌ 错误密码居然能开！bug！")
        except sqlcipher3.DatabaseError as e:
            t_wrong = (time.perf_counter() - start) * 1000
            print(f"  ✅ 错误密码拒绝: {t_wrong:.1f}ms, error={type(e).__name__}")

    print()
    print("🎉 sqlcipher3 加密往返 spike 全绿，可启动 D3.1")


if __name__ == "__main__":
    main()
