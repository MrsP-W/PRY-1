"""统一配置加载 — `.env` 自动加载 + 环境变量便利访问。

设计原则（沿 [docs/architecture.md §5.1 数据保护] + keychain.py 铁律）：

    - **凭据绝不落 .env**：IMAP 授权码 / SMTP 授权码 / DB 密码 / Notes master key
      一律走 Keychain（见 `core/keychain.py`）。`.env` 只放**非机密配置**
      （IMAP_USER / LLM base url / provider API key 兜底 / 门控开关）。
    - **幂等加载**：`load_env()` 用模块级 flag 保证多次调用只真正 `load_dotenv()` 一次。
    - **只在显式入口调用**：main / setup_wizard / dashboard server / menu bar / 数据同步脚本
      在 `main()` 起始处调 `load_env()`，避免 import 期副作用污染 pytest。
    - **不覆盖已有 env**：默认 `override=False`，保证 `export FOO=bar` / CI 注入的变量
      优先于 `.env` 文件（撞坑 #18 门控优先级：显式 env > .env 文件）。

用法::

    from my_ai_employee.core.config import load_env
    load_env()  # main() 起始处调一次
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

# 模块级幂等 flag：保证 load_dotenv 只真正执行一次
_ENV_LOADED = False


def project_root() -> Path:
    """项目根目录（`config.py` 上溯 3 层：core → my_ai_employee → src → root）。"""
    return Path(__file__).resolve().parents[3]


def load_env(dotenv_path: Path | None = None, *, override: bool = False) -> bool:
    """幂等加载项目根 `.env`（若存在）。

    Args:
        dotenv_path: 显式指定 .env 路径（测试可注入）；默认项目根 `.env`。
        override: 是否覆盖已存在的环境变量（默认 False，显式 env 优先）。

    Returns:
        本次是否真正加载了文件（True = 加载成功；False = 已加载过 / 文件不存在 /
        python-dotenv 不可用）。
    """
    global _ENV_LOADED
    if _ENV_LOADED and dotenv_path is None:
        return False

    target = dotenv_path if dotenv_path is not None else project_root() / ".env"

    try:
        from dotenv import load_dotenv
    except ImportError:
        # python-dotenv 未装（应急降级）：不阻塞启动，依赖 shell export
        logger.warning("python-dotenv 未安装，跳过 .env 加载（依赖 shell export）")
        _ENV_LOADED = True
        return False

    if not target.exists():
        # 无 .env 文件是正常情况（凭据走 Keychain / CI 用 export）
        _ENV_LOADED = True
        return False

    loaded = load_dotenv(dotenv_path=target, override=override)
    _ENV_LOADED = True
    if loaded:
        logger.info(f".env 已加载: {target}（override={override}）")
    return loaded


def reset_for_test() -> None:
    """重置幂等 flag（仅测试用，允许重复 load_env）。"""
    global _ENV_LOADED
    _ENV_LOADED = False


__all__ = ["project_root", "load_env", "reset_for_test"]
