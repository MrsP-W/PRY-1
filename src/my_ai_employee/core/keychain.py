"""macOS Keychain 凭证包装。

设计原则（[docs/architecture.md §5.1 数据保护]）：

    - 凭证（IMAP 密码 / DB 密码 / API Key）**只存 Keychain**，不落盘 .env
    - 应用名固定 `my-ai-employee`（用于在 Keychain Access.app 检索）
    - 服务名 = 用途（`db` / `imap-qq` / `imap-outlook` ...）
    - 账号 = 标识（QQ 邮箱地址 / 数据库名）

Keychain 命令（macOS）：

    security add-generic-password   # 写入
    security find-generic-password  # 读取（-w 只输出密码）
    security delete-generic-password  # 删除

跨平台：D2 阶段只支持 macOS（菜单栏项目），其他平台 `is_available()` 返回 False，
调用方需降级（应急版范本：弹窗让用户手动输入）。
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Final

from loguru import logger

# Keychain 中的 service 名（统一前缀）
SERVICE_PREFIX: Final[str] = "my-ai-employee"
SERVICE_DB: Final[str] = f"{SERVICE_PREFIX}.db"
SERVICE_IMAP_QQ: Final[str] = f"{SERVICE_PREFIX}.imap.qq"
SERVICE_IMAP_OUTLOOK: Final[str] = f"{SERVICE_PREFIX}.imap.outlook"
SERVICE_IMAP_GMAIL: Final[str] = f"{SERVICE_PREFIX}.imap.gmail"


@dataclass
class KeychainResult:
    """Keychain 操作结果。"""

    ok: bool
    value: str | None = None
    error: str | None = None


def is_available() -> bool:
    """检查当前平台是否支持 Keychain（仅 macOS）。"""
    return sys.platform == "darwin" and _security_command_exists()


def _security_command_exists() -> bool:
    """`security` 命令是否可用。"""
    try:
        subprocess.run(
            ["security", "help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def set_password(service: str, account: str, password: str) -> KeychainResult:
    """写入 Keychain（覆盖式）。失败时返回 `ok=False`。

    Args:
        service: 服务名（如 `my-ai-employee.db`）
        account: 账号（如 QQ 邮箱地址）
        password: 要存的密码

    Returns:
        KeychainResult(ok=True) 成功 / KeychainResult(ok=False, error=...) 失败
    """
    if not is_available():
        return KeychainResult(ok=False, error="当前平台不支持 Keychain（非 macOS）")

    # 原位更新（`security add-generic-password -U` 本身能覆盖已有项）
    # — 不再"先删后增"，避免 delete 成功但 add 失败导致旧凭证丢失
    try:
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-a", account,
                "-s", service,
                "-w", password,
                "-U",  # 关键：-U 表示"如果已存在则更新"
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return KeychainResult(ok=False, error=f"security add-generic-password 失败: {e.stderr.strip()}")
    except subprocess.TimeoutExpired:
        return KeychainResult(ok=False, error="security add-generic-password 超时（10s）")
    except Exception as e:  # 兜底：FileNotFoundError 等
        return KeychainResult(ok=False, error=f"未知错误: {e!r}")

    logger.info(f"Keychain 写入: service={service} account={account} ({len(password)} chars)")
    return KeychainResult(ok=True)


def get_password(service: str, account: str) -> KeychainResult:
    """从 Keychain 读密码。

    Returns:
        KeychainResult(ok=True, value=...) 找到
        KeychainResult(ok=False, error="not found") 不存在
        KeychainResult(ok=False, error=...) 其他错误
    """
    if not is_available():
        return KeychainResult(ok=False, error="当前平台不支持 Keychain（非 macOS）")

    try:
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a", account,
                "-s", service,
                "-w",  # 只输出密码
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        password = proc.stdout.strip()
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        # "SecKeychainSearchCopyNext: The specified item could not be found..."
        if "could not be found" in stderr.lower() or e.returncode == 44:
            return KeychainResult(ok=False, error="not found")
        return KeychainResult(ok=False, error=f"security find-generic-password 失败: {stderr}")
    except subprocess.TimeoutExpired:
        return KeychainResult(ok=False, error="security find-generic-password 超时（10s）")
    except Exception as e:
        return KeychainResult(ok=False, error=f"未知错误: {e!r}")

    return KeychainResult(ok=True, value=password)


def delete_password(service: str, account: str) -> KeychainResult:
    """从 Keychain 删除（不存在也不算错）。"""
    if not is_available():
        return KeychainResult(ok=False, error="当前平台不支持 Keychain（非 macOS）")

    try:
        subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-a", account,
                "-s", service,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip()
        if "could not be found" in stderr.lower() or e.returncode == 44:
            return KeychainResult(ok=True)  # 不存在 → 视为成功
        return KeychainResult(ok=False, error=f"security delete-generic-password 失败: {stderr}")
    except subprocess.TimeoutExpired:
        return KeychainResult(ok=False, error="security delete-generic-password 超时（10s）")
    except Exception as e:
        return KeychainResult(ok=False, error=f"未知错误: {e!r}")

    return KeychainResult(ok=True)


# ===== 高层封装（业务便利）=====


def set_db_password(password: str) -> KeychainResult:
    """存数据库密码（Keychain service=my-ai-employee.db, account=data.db）。"""
    return set_password(SERVICE_DB, "data.db", password)


def get_db_password() -> KeychainResult:
    """读数据库密码。"""
    return get_password(SERVICE_DB, "data.db")


def set_imap_password(email: str, auth_code: str) -> KeychainResult:
    """存 IMAP 授权码（service=my-ai-employee.imap.qq, account=email）。"""
    return set_password(SERVICE_IMAP_QQ, email, auth_code)


def get_imap_password(email: str) -> KeychainResult:
    """读 IMAP 授权码。"""
    return get_password(SERVICE_IMAP_QQ, email)


__all__ = [
    "KeychainResult",
    "is_available",
    "set_password",
    "get_password",
    "delete_password",
    "set_db_password",
    "get_db_password",
    "set_imap_password",
    "get_imap_password",
    "SERVICE_PREFIX",
    "SERVICE_DB",
    "SERVICE_IMAP_QQ",
    "SERVICE_IMAP_OUTLOOK",
    "SERVICE_IMAP_GMAIL",
]
