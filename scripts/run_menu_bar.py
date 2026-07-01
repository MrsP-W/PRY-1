"""菜单栏常驻入口 — NotesMenuBarApp 最小启动脚本(Day 1 / 7 天计划交付物).

设计要点:
    - 不依赖不存在的 `python -m menu_bar.app` 入口(Day 2 前置)
    - 所有服务用 None 默认值(Stub 默认单例),不连真实 DB / 不读真实剪贴板
    - badge 轮询 30s 默认(可被 env `MYAIEMP_BADGE_POLL_SECONDS` 覆盖,test 用 0.1s 加快)
    - sys.path 注入 src/,允许 `uv run python scripts/run_menu_bar.py` 直接启动

启动方式(沿 D9.3 + D10 范本):
    前台调试:uv run python scripts/run_menu_bar.py
    后台常驻(Week 1 方案 A):nohup uv run python scripts/run_menu_bar.py > data/menu_bar.log 2>&1 &
    集成 Day 7 一键包:bash ops/start-digital-employee.sh

撞坑关联:
    - 撞坑 #71 决议 B:本棒新写为基础设施文件,撞坑 #71 docs-only 边界外
    - 撞坑 #59 红线维持:本脚本不读取真实凭据,无 Keychain 写入,无真实发送
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.menu_bar.app import NotesMenuBarApp  # noqa: E402


def _badge_poll_seconds() -> float:
    """从 env 读取轮询间隔(秒),默认 30.0(沿 D9.3 + v0.2.2 启动候选 #6 范本)."""
    raw = os.environ.get("MYAIEMP_BADGE_POLL_SECONDS")
    if raw is None:
        return 30.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"MYAIEMP_BADGE_POLL_SECONDS 必须是 float,实际 {raw!r}") from exc
    if value < 0 or value > 3600:
        raise ValueError(f"MYAIEMP_BADGE_POLL_SECONDS 必须在 [0, 3600] 内,实际 {value}")
    return value


def main() -> int:
    """启动菜单栏 App 阻塞运行(返回 0 = 正常退出)."""
    NotesMenuBarApp(badge_poll_interval_seconds=_badge_poll_seconds()).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
