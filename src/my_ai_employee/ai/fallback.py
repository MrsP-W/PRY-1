"""LLM Fallback Chain — D4.1.

参考 claw-code src/router/fallback.py 架构原则:
  - 主选 → 备选 → 兜底链
  - 失败隔离: 单 provider 失败不阻塞链上其他
  - 失败计数: 连续 N 次失败触发熔断, 冷却期后恢复

参考 D3.3.3 教训("异常范围要窄化到真要处理的类型"):
  - 本模块只定义"业务上等同于需要 fallback 的错误"(HTTP 4xx/5xx/超时)
  - 不 catch-all 兜底 — 编程错误(参数错/类型错)应直接抛

v2 晨报钩子(国内模型优先):
  - 4 任务类型 → 4 fallback 链, 全部国内优先
  - 国外 provider(Anthropic/OpenAI)仅作 final fallback
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .capability import TaskType


@dataclass(frozen=True)
class FallbackChainConfig:
    """Fallback 链配置(数据驱动, 可由配置文件覆盖).

    Attributes:
        primary: 主选 full_id (provider/model)
        secondary: 备选 full_id
        tertiary: 兜底 full_id
        max_retries: 单 provider 重试次数(0 表示不重试, 直接走链上下一档)
        timeout_seconds: 单次调用超时
        circuit_breaker_threshold: 连续失败 N 次触发熔断
        circuit_breaker_cooldown_seconds: 熔断冷却时间
    """

    primary: str
    secondary: str
    tertiary: str
    max_retries: int = 0
    timeout_seconds: float = 30.0
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown_seconds: float = 1800.0  # 30 分钟


# === Fallback 链配置表 ===
# v2 晨报钩子: 4 任务类型 → 4 异构链
# 设计原则: primary 走"性价比最优", secondary 走"能力次优", tertiary 走"兜底"

FALLBACK_CHAINS: dict[TaskType, FallbackChainConfig] = {
    # 邮件分类: 短文本 + 高频 + 准确率敏感
    # primary = DeepSeek 性价比(0.5 元/百万 token), secondary = Qwen 多模态备用, tertiary = M3 兜底
    TaskType.CLASSIFY: FallbackChainConfig(
        primary="deepseek/deepseek-chat",
        secondary="qwen/qwen3-max",
        tertiary="minimax/MiniMax-M3",
    ),
    # 草稿生成: 中长文本 + 中文质量敏感
    # primary = M3 中文质量优, secondary = DeepSeek 性价比, tertiary = Qwen 1M context
    TaskType.DRAFT: FallbackChainConfig(
        primary="minimax/MiniMax-M3",
        secondary="deepseek/deepseek-chat",
        tertiary="qwen/qwen3-max",
    ),
    # 财务异常检测: 推理深度敏感
    # primary = DeepSeek-R1 推理模型, secondary = M3 中文推理, tertiary = GLM 备选
    TaskType.ANALYZE: FallbackChainConfig(
        primary="deepseek/deepseek-reasoner",
        secondary="minimax/MiniMax-M3",
        tertiary="glm/glm-4-plus",
    ),
    # 笔记结构化: 中等长度 + 可能多模态
    # primary = Qwen 多模态 + 1M context, secondary = 腾讯混元, tertiary = DeepSeek 兜底
    TaskType.STRUCTURE: FallbackChainConfig(
        primary="qwen/qwen3-max",
        secondary="tencent/hunyuan-pro",
        tertiary="deepseek/deepseek-chat",
    ),
    # 摘要: 通用任务
    # primary = DeepSeek 性价比, secondary = M3 中文, tertiary = Claude 兜底
    TaskType.SUMMARIZE: FallbackChainConfig(
        primary="deepseek/deepseek-chat",
        secondary="minimax/MiniMax-M3",
        tertiary="anthropic/claude-sonnet-4-6",
    ),
}


@dataclass
class CircuitBreaker:
    """熔断器(单 provider 隔离, 避免雪崩).

    States:
      - CLOSED: 正常, 请求直通
      - OPEN: 熔断, 请求直接跳过
      - HALF_OPEN: 冷却期过, 下一个请求试水(本实现简化: 冷却期过后直接 CLOSED)

    Attributes:
        failure_count: 连续失败次数
        opened_at: 熔断开始时间(time.time())
        cooldown_seconds: 冷却时间
    """

    failure_count: int = 0
    opened_at: float | None = None
    cooldown_seconds: float = 1800.0

    def record_success(self) -> None:
        """成功: 重置计数."""
        self.failure_count = 0
        self.opened_at = None

    def record_failure(self) -> None:
        """失败: 累加, 达阈值则熔断."""
        self.failure_count += 1
        if self.failure_count >= 3:  # 默认阈值
            self.opened_at = time.time()

    def is_open(self) -> bool:
        """是否熔断中.

        冷却期过: 自动重置 → CLOSED.
        """
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at > self.cooldown_seconds:
            self.failure_count = 0
            self.opened_at = None
            return False
        return True


def get_chain(task_type: TaskType) -> FallbackChainConfig:
    """获取任务类型对应的 fallback 链.

    Args:
        task_type: 任务类型

    Returns:
        FallbackChainConfig 实例

    Raises:
        KeyError: 任务类型未配置(应由 FALLBACK_CHAINS 覆盖所有 TaskType)
    """
    return FALLBACK_CHAINS[task_type]
