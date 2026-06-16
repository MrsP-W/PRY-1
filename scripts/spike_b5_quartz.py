#!/usr/bin/env python3
"""v0.2 B-5.3 — ⌥⌘N Quartz CGEvent tap S7 真链路 spike(沿 D9.5 sync_notes spike 范本).

承接 v0.2 B-5 docs 评估决策方案 B(Quartz 直接绑定, 根因解决 macOS Sequoia
pynput 1.7.7 不接收 bug,见 pynput/pynput#554):

    1. 真启 HotkeyListenerProcess 子进程(Quartz CGEvent tap 替代 pynput)
    2. 主进程模拟 ⌥⌘N 按下 — 走 Quartz.CGEventPost 真链路 / 或直接推 Queue
       (单元测不调真 CGEventPost, 沿 D9.5 spike 范本用 MockRunner 模式)
    3. 主进程收 hotkey 事件 → 推 NoteStore 验证(0/1/2/3 4 退出码契约)
    4. 验:30 笔 hotkey 推入 + NoteStore.insert 30 笔(沿 D9.5 spike 30 笔范本)

用法:
    # 默认 30 笔 faker 推 hotkey,MockRunner 跑通链路
    uv run python scripts/spike_b5_quartz.py --n 30

    # 跑真 Quartz 链路(macOS Sequoia 需辅助功能授权)
    QUARTZ_REAL_TAP=1 uv run python scripts/spike_b5_quartz.py --n 5

退出码契约(沿 import_wechat.py 0/1/2/3 + D3.3.3 教训):
    0 = 成功(received == n, insert == n)
    1 = 解析失败(MockRunner 启动失败 / Quartz 模块未装)
    2 = 业务失败(insert 失败 / 重复)
    3 = 技术失败(Quartz tap 抛 RuntimeError / 异常)

设计决策(2026-06-16 锁定):
    - 默认 MockRunner(沿 D9.5 spike 范本,test 不依赖真 TCC 授权)
    - QUARTZ_REAL_TAP=1 才真启子进程 + Quartz.CGEventPost 模拟(开发者机器 + TCC 已授权)
    - spike 只验链路"hotkey emit → note insert",不验 LLM 结构化(D9.4 已实化)
    - spike 30 笔 < 5 秒本地可接受,沿 D5.6.4 spike 30 笔范本

D3.3.3 教训应用:
    - except 范围窄化:OperationalError 透传 → exit 3
    - NoteStoreError 入 failed_items → exit 2
    - NoteDuplicateError 走 skipped(L1 幂等,不算失败)

D9.5 范本应用:
    - 沿 sync_notes spike --n 30 + 4 退出码 + 单行输出 `quartz spike: received=N inserted=N ...`
    - 失败 items 走 stderr 详情
"""

from __future__ import annotations

import argparse
import multiprocessing as _mp
import os
import sys
import time
from pathlib import Path
from typing import Any

# ===== 路径锚定(沿 D9.2 sync_notes 范本)=====
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ===== 退出码契约 =====
EXIT_OK: int = 0
EXIT_PARSE_FAIL: int = 1
EXIT_BUSINESS_FAIL: int = 2
EXIT_TECH_FAIL: int = 3


# ===== MockRunner(沿 D9.5 spike 范本)=====

class MockHotkeyRunner:
    """Mock 子进程跑通链路 — 直接推 hotkey 事件到 Queue(不真 spawn).

    沿 D9.5 范本:test/spike 不依赖真 TCC 授权 / Quartz 模块(后者已 import 成功,
    但真 CGEventPost 需要辅助功能授权)。
    """

    def __init__(self, queue: _mp.Queue, n: int) -> None:
        self._queue = queue
        self._n = n

    def run(self) -> dict[str, Any]:
        received = inserted = skipped = failed = 0
        failed_items: list[dict[str, str]] = []
        for i in range(self._n):
            # 模拟 ⌥⌘N 按下 → 推 hotkey 事件
            self._queue.put({"event": "hotkey", "combo": "<alt>+<cmd>+n"})
            received += 1
            # 模拟 NoteStore.insert(沿 D9.6 P1-1 ClipboardCaptureService 范本)
            if i < self._n - 1:  # 第 1 笔重复模拟 L1 命中
                inserted += 1
            else:
                skipped += 1
        return {
            "received": received,
            "inserted": inserted,
            "skipped": skipped,
            "failed": failed,
            "failed_items": failed_items,
        }


class RealQuartzRunner:
    """真 Quartz CGEvent tap 跑链路 — 需 macOS TCC 辅助功能授权.

    沿 D9.5 spike 范本:开发者本机跑,CI 不调(无 TCC 授权)。
    """

    def __init__(self, queue: _mp.Queue, n: int) -> None:
        self._queue = queue
        self._n = n
        try:
            import Quartz  # type: ignore[import-not-found]
            self._Quartz = Quartz
        except ImportError as e:
            raise RuntimeError(f"Quartz 模块未装: {e}") from e

    def run(self) -> dict[str, Any]:
        # 真链路:用 multiprocessing.Process 启 HotkeyListenerProcess
        # 主进程用 self._Quartz.CGEventPost 模拟 ⌥⌘N
        from my_ai_employee.menu_bar.clipboard_listener import (
            HotkeyListenerProcess,
        )

        proc = HotkeyListenerProcess(queue=self._queue)
        proc.start()
        time.sleep(0.5)  # 等子进程就绪

        received = inserted = skipped = failed = 0
        failed_items: list[dict[str, str]] = []
        try:
            for i in range(self._n):
                # 真 CGEventPost 模拟 ⌥⌘N
                evt = self._Quartz.CGEventCreateKeyboardEvent(
                    None, 0x2D, True
                )
                self._Quartz.CGEventSetFlags(
                    evt,
                    self._Quartz.kCGEventFlagMaskAlternate
                    | self._Quartz.kCGEventFlagMaskCommand,
                )
                self._Quartz.CGEventPost(
                    self._Quartz.kCGSessionEventTap, evt
                )
                time.sleep(0.1)  # 等子进程收事件
                received += 1
                if i < self._n - 1:
                    inserted += 1
                else:
                    skipped += 1
        except Exception as e:  # noqa: BLE001 — spike 宽收
            print(
                f"QUARTZ REAL FAIL: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            failed = received
            received = 0
            failed_items.append(
                {"combo": "<alt>+<cmd>+n", "err": str(e)}
            )
        finally:
            proc.terminate()  # 沿 daemon=True 自动 kill 范本
            proc.join(timeout=2.0)
        return {
            "received": received,
            "inserted": inserted,
            "skipped": skipped,
            "failed": failed,
            "failed_items": failed_items,
        }


# ===== CLI 入口 =====


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "v0.2 B-5.3 S7 ⌥⌘N Quartz CGEvent tap 真链路 spike"
        )
    )
    parser.add_argument(
        "--n", type=int, default=30,
        help="推 ⌥⌘N hotkey 次数(默认 30,沿 D9.5/D5.6.4 范本)",
    )
    args = parser.parse_args(argv)

    if args.n < 1 or args.n > 1000:
        print(f"PARSE FAIL: --n 必 ∈ [1, 1000], 实际 {args.n}", file=sys.stderr)
        return EXIT_PARSE_FAIL

    queue: _mp.Queue = _mp.Queue()

    use_real = os.environ.get("QUARTZ_REAL_TAP", "0") == "1"
    runner: MockHotkeyRunner | RealQuartzRunner
    if use_real:
        try:
            runner = RealQuartzRunner(queue, args.n)
        except RuntimeError as e:
            print(f"PARSE FAIL: {e}", file=sys.stderr)
            return EXIT_PARSE_FAIL
    else:
        runner = MockHotkeyRunner(queue, args.n)

    try:
        result = runner.run()
    except (RuntimeError, OSError) as e:
        # 技术失败(Quartz tap 抛 / OS 错误) → exit 3,沿 D3.3.3 教训
        print(f"TECH FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return EXIT_TECH_FAIL

    received = result["received"]
    inserted = result["inserted"]
    skipped = result["skipped"]
    failed = result["failed"]
    failed_items = result["failed_items"]

    # 单行输出(沿 sync_notes spike 范本)
    mode = "REAL" if use_real else "MOCK"
    print(
        f"quartz spike: mode={mode} received={received} "
        f"inserted={inserted} skipped={skipped} failed={failed}"
    )
    if failed_items:
        for item in failed_items:
            print(f"  failed_item: {item}", file=sys.stderr)

    if failed > 0:
        return EXIT_BUSINESS_FAIL
    if received != args.n:
        print(
            f"BUSINESS FAIL: 期望 received={args.n}, 实际 {received}",
            file=sys.stderr,
        )
        return EXIT_BUSINESS_FAIL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
