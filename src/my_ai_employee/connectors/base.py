"""L1 适配器层 — 抽象基类（契约）。

所有 L1 适配器（IMAP/CalDAV/账单/Notes...）必须继承 `BaseConnector`，
实现 3 个抽象方法 + 1 个属性：

    - `source_name` 属性  → 标识（"qq" / "icloud" / "wechat" / ...）
    - `fetch(since)`      → 拉取自 `since` 以来的增量数据
    - `healthcheck()`     → 连通性 + 凭证有效性检查
    - `connect()`         → 建立连接（带失败重试）

设计原则（来自 [docs/architecture.md §1 L1]）：

    - **失败隔离**：单个适配器失败不传染（safe_fetch 包裹）
    - **熔断**：连续失败 3 次进入熔断，30 min 后再试
    - **统一接口**：所有适配器对 L3 暴露一致的 `fetch(since) -> list[dict]`

D2 收窄版（详见 [docs/week1-mvp.md §D2]）：只做 BaseConnector 抽象 + safe_fetch
实现，IMAP/CalDAV 各自实现 fetch/healthcheck/connect。
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger


# ===== 熔断配置 =====

# 连续失败阈值：达到此值后进入熔断
CIRCUIT_BREAKER_THRESHOLD = 3
# 熔断持续时间（秒）：30 min
CIRCUIT_BREAKER_COOLDOWN = 30 * 60


@dataclass
class HealthStatus:
    """适配器健康状态（healthcheck 返回值）。

    字段：
      - ok: 是否健康（True/False）
      - latency_ms: 本次检查耗时（毫秒）
      - error: 失败时的错误描述（None 表示无错）
      - circuit_open: 是否处于熔断状态
    """

    ok: bool
    latency_ms: float = 0.0
    error: str | None = None
    circuit_open: bool = False


@dataclass
class _CircuitBreakerState:
    """熔断器内部状态（每个适配器实例独立持有）。"""

    consecutive_failures: int = 0
    last_failure_at: float = 0.0  # time.time() 时间戳
    open_until: float = 0.0  # 熔断结束时间戳


class BaseConnector(ABC):
    """L1 适配器抽象基类。

    子类必须实现：
        - `source_name` (property)
        - `fetch(since)`
        - `healthcheck()`
        - `connect()`

    子类可直接使用：
        - `safe_fetch(since)` — 失败隔离 + 熔断
        - `_record_success()` / `_record_failure()` — 更新熔断计数
        - `_is_circuit_open()` — 熔断检查
        - `circuit_state` (property) — 读熔断状态

    设计：所有方法都是 `async`，方便后续接 APScheduler 异步任务调度。
    D2 收窄版里 IMAP 适配器内部用同步 imapclient 包，但顶层用 `asyncio.to_thread`
    包装避免阻塞事件循环。
    """

    def __init__(self) -> None:
        # 熔断状态：每个实例独立
        self._circuit = _CircuitBreakerState()

    # ===== 抽象契约（子类必须实现）=====

    @property
    @abstractmethod
    def source_name(self) -> str:
        """适配器唯一标识（如 "qq" / "icloud" / "wechat"）。"""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """建立连接。失败抛 `ConnectionError`。"""
        ...

    @abstractmethod
    async def fetch(self, since: datetime) -> list[dict[str, Any]]:
        """拉取 `since` 以来增量数据。

        返回：list of dict，每条 dict 至少含 `source` 字段（=source_name）
        """
        ...

    @abstractmethod
    async def healthcheck(self) -> HealthStatus:
        """健康检查：连通性 + 凭证有效性 + 服务端可达性。

        返回 `HealthStatus`，子类可附加字段（如账号、邮件未读数）。
        """
        ...

    # ===== 公共方法（失败隔离 + 熔断）=====

    async def safe_fetch(self, since: datetime) -> list[dict[str, Any]]:
        """带失败隔离的 fetch（应急版范本的应用）。

        行为：
            1. 熔断开启 → 立即返回空列表（不调用 fetch）
            2. fetch 抛任何异常 → 记录失败 + 计数 + 通知（如配置）
            3. 成功 → 重置失败计数
            4. 连续失败 ≥ 3 → 开启熔断（30 min）
        """
        if self._is_circuit_open():
            logger.warning(
                f"[{self.source_name}] 熔断中，跳过 fetch "
                f"(剩余 {(self._circuit.open_until - time.time()):.0f}s)"
            )
            return []

        try:
            result = await self.fetch(since)
        except Exception as e:
            self._record_failure(e)
            # 应急版范本：失败时通知用户（这里只 log）
            logger.error(f"[{self.source_name}] fetch failed: {e!r}")
            return []
        else:
            self._record_success()
            return result

    @property
    def circuit_state(self) -> dict[str, Any]:
        """读熔断状态（用于健康面板 / 调试）。"""
        return {
            "consecutive_failures": self._circuit.consecutive_failures,
            "last_failure_at": self._circuit.last_failure_at,
            "open_until": self._circuit.open_until,
            "is_open": self._is_circuit_open(),
        }

    # ===== 内部方法（子类可重写）=====

    def _is_circuit_open(self) -> bool:
        """是否处于熔断状态。"""
        if self._circuit.open_until == 0.0:
            return False
        if time.time() < self._circuit.open_until:
            return True
        # 熔断到期 → 自动重置
        self._reset_circuit()
        return False

    def _record_success(self) -> None:
        """fetch 成功 → 重置失败计数。"""
        if self._circuit.consecutive_failures > 0:
            logger.info(
                f"[{self.source_name}] fetch 成功，重置失败计数 "
                f"(was {self._circuit.consecutive_failures})"
            )
        self._circuit.consecutive_failures = 0
        self._circuit.open_until = 0.0

    def _record_failure(self, error: BaseException) -> None:
        """fetch 失败 → 计数 + 检查是否进入熔断。"""
        self._circuit.consecutive_failures += 1
        self._circuit.last_failure_at = time.time()

        if self._circuit.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            self._circuit.open_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
            logger.error(
                f"[{self.source_name}] 连续失败 "
                f"{self._circuit.consecutive_failures} 次，"
                f"进入熔断 {CIRCUIT_BREAKER_COOLDOWN}s: {error!r}"
            )
        else:
            logger.warning(
                f"[{self.source_name}] 失败 "
                f"{self._circuit.consecutive_failures}/{CIRCUIT_BREAKER_THRESHOLD}: {error!r}"
            )

    def _reset_circuit(self) -> None:
        """熔断到期 → 重置。"""
        logger.info(f"[{self.source_name}] 熔断到期，重置状态")
        self._circuit.consecutive_failures = 0
        self._circuit.open_until = 0.0


__all__ = [
    "BaseConnector",
    "HealthStatus",
    "CIRCUIT_BREAKER_THRESHOLD",
    "CIRCUIT_BREAKER_COOLDOWN",
]
