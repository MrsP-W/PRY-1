"""LLM Router — D4.1 主入口.

5 步决策法落地:
  1. 接收请求 (task_type + messages)
  2. 查 fallback 链(按 task_type)
  3. 遍历: primary → secondary → tertiary
  4. 跳过熔断的 provider + reasoning 模型强制 temperature=1.0
  5. 返回首个成功响应(失败则继续链上, 全失败抛 LLMAllFallbacksError)

参考 claw-code:
  - docs/local-openai-compatible-providers.md: OpenAI-compatible 路由
  - docs/MODEL_COMPATIBILITY.md: capability registry
  - src/router/fallback.py: fallback 链模式

参考 D3.3.3 教训("异常范围要窄化"):
  - router 捕获 Exception(全失败兜底), 但每个 provider 调 chat() 自身
    不应 catch-all 兜底(让真错误透传出来, 由 router 决定 fallback)

D4.6 v1.0.1 修复(D4.6 复检 P1-1):
  - 全链失败从 RuntimeError 改为 LLMAllFallbacksError(LLMError 子类)
  - 业务方 except LLMError 即可覆盖(不再逃逸)
  - 错误消息保留 primary/secondary/tertiary + last_error 完整上下文

D4.1.0 范围: 决策逻辑 + 统计 + 单例, **不调 HTTP** (provider.chat 占位).
D4.1.1 实施: OpenAICompatibleProvider.chat() 实际 HTTP + 单元测试集成.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from loguru import logger

from .capability import (
    TaskType,
    get_capability,
)
from .fallback import (
    CircuitBreaker,
    get_chain,
)
from .providers import (
    LLMAllFallbacksError,
    LLMError,
    LLMRequest,
    LLMResponse,
    get_provider,
)


@dataclass
class RouterStats:
    """路由统计(可观测性, 参考 claw-code 的 truthful status 原则).

    Attributes:
        primary_attempts: 主选调用次数
        primary_successes: 主选成功次数
        fallback_attempts: 备选/兜底调用次数
        fallback_successes: 备选/兜底成功次数
        failures: 全链失败次数
        total_latency_ms: 累计耗时(毫秒)
    """

    primary_attempts: int = 0
    primary_successes: int = 0
    fallback_attempts: int = 0
    fallback_successes: int = 0
    failures: int = 0
    total_latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(便于 JSON 化)."""
        return {
            "primary_attempts": self.primary_attempts,
            "primary_successes": self.primary_successes,
            "fallback_attempts": self.fallback_attempts,
            "fallback_successes": self.fallback_successes,
            "failures": self.failures,
            "total_latency_ms": self.total_latency_ms,
            "primary_success_rate": (
                self.primary_successes / self.primary_attempts if self.primary_attempts > 0 else 0.0
            ),
        }


class LLMRouter:
    """LLM 路由器(D4.1 主类, 单例).

    关键不变量:
      - 主选优先, 备选/兜底只在主选失败时启用
      - 熔断的 provider 跳过(避免雪崩)
      - Reasoning 模型强制 temperature=1.0(参考 claw-code MODEL_COMPATIBILITY.md)
      - 全链失败抛 RuntimeError(让上层 catch 处理)
    """

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._stats = RouterStats()

    def _breaker(self, full_id: str) -> CircuitBreaker:
        """获取/创建单 provider 的熔断器(惰性创建)."""
        if full_id not in self._breakers:
            self._breakers[full_id] = CircuitBreaker()
        return self._breakers[full_id]

    def route(
        self,
        task_type: TaskType,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """主入口: 按 task_type 路由 + fallback 链.

        Args:
            task_type: 任务类型(决定 fallback 链)
            messages: OpenAI 风格 messages
            temperature: 用户指定温度(0.0-1.0, reasoning 模型会被强制 1.0)
            max_tokens: 输出上限

        Returns:
            LLMResponse(首个成功的响应)

        Raises:
            RuntimeError: 全链失败
        """
        chain = get_chain(task_type)
        start = time.time()
        last_error: Exception | None = None

        for tier_name, full_id in (
            ("primary", chain.primary),
            ("secondary", chain.secondary),
            ("tertiary", chain.tertiary),
        ):
            # 1. 熔断检查
            breaker = self._breaker(full_id)
            if breaker.is_open():
                logger.warning(
                    f"[router] {full_id} 熔断中, 跳过 {tier_name} | task_type={task_type.value}"
                )
                continue

            # 2. capability registry 检查
            cap = get_capability(full_id)
            if cap is None:
                logger.warning(f"[router] {full_id} 不在 capability registry, 跳过 {tier_name}")
                continue

            # 3. Reasoning 模型强制 temperature=1.0
            if cap.is_reasoning and temperature != 1.0:
                logger.info(
                    f"[router] {full_id} 是推理模型, 强制 temperature=1.0 (用户传 {temperature})"
                )
                actual_temp = 1.0
            else:
                actual_temp = temperature

            # 4. 调用 provider
            try:
                if tier_name == "primary":
                    self._stats.primary_attempts += 1
                else:
                    self._stats.fallback_attempts += 1

                provider = get_provider(full_id)
                request = LLMRequest(
                    model_full_id=full_id,
                    messages=messages,
                    temperature=actual_temp,
                    max_tokens=max_tokens,
                )
                response = provider.chat(request)

                # 5. 成功: 记录 + 返回
                breaker.record_success()
                if tier_name == "primary":
                    self._stats.primary_successes += 1
                else:
                    self._stats.fallback_successes += 1
                self._stats.total_latency_ms += int((time.time() - start) * 1000)
                logger.info(
                    f"[router] {tier_name}={full_id} 成功 | "
                    f"latency={response.latency_ms}ms | "
                    f"task_type={task_type.value}"
                )
                return response
            except LLMError as e:
                # 业务错误(超时/连接/HTTP 4xx/5xx/响应解析)→ 熔断 + 走链上下一档
                # 编程错误(ValueError/TypeError) 不 catch — 直接透传,
                # 让调用方知道是"代码 bug"而非"网络问题"(D3.3.3 教训).
                breaker.record_failure()
                last_error = e
                logger.warning(
                    f"[router] {tier_name}={full_id} 失败: {e!r} | task_type={task_type.value}"
                )
                continue

        # 全链失败(D4.6 v1.0.1 P1-1 修复:RuntimeError → LLMAllFallbacksError)
        # 业务方 except LLMError 即可覆盖,不再逃逸到分类器/Adapter 外
        self._stats.failures += 1
        self._stats.total_latency_ms += int((time.time() - start) * 1000)
        raise LLMAllFallbacksError(
            task_type=task_type.value,
            primary=chain.primary,
            secondary=chain.secondary,
            tertiary=chain.tertiary,
            last_error=last_error,
        )

    def stats(self) -> dict[str, Any]:
        """路由统计(可观测性, 对外暴露)."""
        return self._stats.to_dict()

    def reset_breakers(self) -> None:
        """重置所有熔断器(测试/运维用)."""
        for breaker in self._breakers.values():
            breaker.record_success()
        logger.info(f"[router] 重置 {len(self._breakers)} 个熔断器")


# === Singleton ===
_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    """获取单例路由器(进程级).

    测试时可显式调用 reset_breakers() 或 new router 实例隔离状态.
    """
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
