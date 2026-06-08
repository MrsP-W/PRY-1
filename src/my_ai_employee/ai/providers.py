"""LLM Provider 抽象层 — D4.1.

参考 claw-code docs/local-openai-compatible-providers.md 架构原则:
  - OpenAI-compatible 统一协议: /v1/chat/completions + Bearer token
  - 命名: provider/model 格式
  - 环境变量: OPENAI_BASE_URL / OPENAI_API_KEY / OLLAMA_HOST
  - 适用: OpenAI / DeepSeek / Qwen (DashScope) / GLM / OpenRouter / Ollama / MiniMax / 腾讯混元

参考 claw-code src/openai_compat.rs 实现细节:
  - 不同模型对字段/参数的处理(已在 capability.py 抽象)
  - Reasoning 模型剥离 temperature(已在 router.py 处理)
  - GPT-5 用 max_completion_tokens 而非 max_tokens(本抽象层不暴露此差异,
    由 OpenAICompatibleProvider 在 D4.1.1 实现时处理)

D4.1.0 范围: 抽象基类 + 工厂函数 + 配置接口, **不调 HTTP**.
D4.1.1 实施: OpenAICompatibleProvider.chat() 实际 HTTP 调用.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .capability import Provider


@dataclass(frozen=True)
class LLMRequest:
    """统一的 LLM 请求(OpenAI-compatible schema).

    Attributes:
        model_full_id: provider/model 格式
        messages: OpenAI 风格 messages([{"role": "user", "content": "..."}])
        temperature: 0.0-1.0(推理模型会被 router 强制 1.0)
        max_tokens: 输出上限
    """

    model_full_id: str
    messages: list[dict]
    temperature: float = 0.3
    max_tokens: int = 1024


@dataclass(frozen=True)
class LLMResponse:
    """统一的 LLM 响应.

    Attributes:
        content: 文本输出
        model_full_id: 实际调用的 provider/model
        input_tokens: 输入 token 数(用于计费/审计)
        output_tokens: 输出 token 数
        latency_ms: 调用耗时(毫秒)
    """

    content: str
    model_full_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class LLMProvider(ABC):
    """LLM Provider 抽象基类(参考 claw-code openai_compat.rs)."""

    @abstractmethod
    def chat(self, request: LLMRequest) -> LLMResponse:
        """同步调用 LLM, 返回响应或抛异常(由 router 决定 fallback)."""
        ...

    @abstractmethod
    def healthcheck(self) -> bool:
        """健康检查(返回 True 表示可用).

        设计: 不实际发请求(节省 token), 仅检查配置完整性.
        真实健康检查在 router.route() 调用 chat() 时自然暴露.
        """
        ...

    @property
    @abstractmethod
    def provider_type(self) -> Provider:
        """返回 provider 类型."""
        ...

    @property
    @abstractmethod
    def base_url(self) -> str:
        """返回 API base URL(用于调试/healthcheck)."""
        ...


# === Provider base URL 配置表 ===
# 数据驱动: 后续加新 provider 只改此处
# v2 晨报钩子: 国内 base_url 优先

_BASE_URLS: dict[Provider, str] = {
    Provider.DEEPSEEK: "https://api.deepseek.com/v1",
    Provider.QWEN: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    Provider.GLM: "https://open.bigmodel.cn/api/paas/v4",
    Provider.MINIMAX: "https://api.minimaxi.com/v1",
    Provider.TENCENT: "https://api.hunyuan.tencent.com/v1",
    Provider.OPENAI: "https://api.openai.com/v1",
    Provider.ANTHROPIC: "https://api.anthropic.com/v1",
    Provider.OLLAMA: "",  # 由 OLLAMA_HOST 动态拼
    Provider.UNKNOWN: "",
}


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible 协议 provider(占位实现, D4.1.0 不调 HTTP).

    适用: OpenAI / DeepSeek / Qwen / GLM / OpenRouter / Ollama / MiniMax / 腾讯混元
    共同特征: 接受 /v1/chat/completions 端点 + Bearer token.

    D4.1.0 状态: 仅做架构定义, chat() 抛 NotImplementedError.
    D4.1.1 实施: 实现 chat() 调用 httpx + OpenAI SDK 风格.
    """

    def __init__(
        self,
        provider_type: Provider,
        base_url: str,
        api_key: str | None = None,
    ) -> None:
        self._provider_type = provider_type
        self._base_url = base_url.rstrip("/")
        # OPENAI_API_KEY fallback: 多数 OpenAI-compatible 服务都用这个名
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        # 占位: D4.1.1 会读各 provider 的环境变量
        # (DEEPSEEK_API_KEY / DASHSCOPE_API_KEY / MINIMAX_API_KEY / ...)

    @property
    def provider_type(self) -> Provider:
        return self._provider_type

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_key(self) -> str:
        return self._api_key

    def healthcheck(self) -> bool:
        """健康检查: 仅检查配置完整性, 不实际发请求.

        真实健康检查在 chat() 调用失败时由 router 触发熔断.
        """
        return bool(self._base_url)

    def chat(self, request: LLMRequest) -> LLMResponse:
        """调用 /v1/chat/completions.

        D4.1.0 占位: 抛 NotImplementedError.
        D4.1.1 实施: httpx + OpenAI SDK 风格.
        """
        raise NotImplementedError("D4.1.0 仅做架构定义, HTTP 调用在 D4.1.1 实施")


# === Provider Factory ===


def get_provider(full_id: str) -> LLMProvider:
    """按 full_id 获取 provider 实例.

    Args:
        full_id: provider/model 格式(如 "deepseek/deepseek-chat")

    Returns:
        LLMProvider 实例(目前只返回 OpenAICompatibleProvider 占位实现)

    Examples:
        >>> get_provider("deepseek/deepseek-chat").provider_type
        <Provider.DEEPSEEK: 'deepseek'>
        >>> get_provider("ollama/llama3.2").provider_type
        <Provider.OLLAMA: 'ollama'>
    """
    provider_str = full_id.split("/", 1)[0] if "/" in full_id else "openai"
    try:
        provider = Provider(provider_str)
    except ValueError:
        provider = Provider.UNKNOWN

    # Ollama 特殊: base_url 来自 OLLAMA_HOST 环境变量
    if provider == Provider.OLLAMA:
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        base_url = f"{host.rstrip('/')}/v1"
    else:
        base_url = _BASE_URLS.get(provider, "")

    return OpenAICompatibleProvider(
        provider_type=provider,
        base_url=base_url,
    )
