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

D4.1.0: 抽象基类 + 工厂函数 + 配置接口(chat() 抛 NotImplementedError).
D4.1.1: 实施 OpenAICompatibleProvider.chat() — httpx + OpenAI 协议响应解析.

D3.3.3 教训("异常范围要窄化到真要处理的类型"):
  - chat() 抛 4 类业务异常(LLMTimeoutError / LLMConnectionError /
    LLMAPIError / LLMResponseError), 编程错误(参数错)透传
  - router 决定 fallback: 业务异常 → fallback, 编程异常 → 直接抛
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from .capability import Provider

# === 4 类业务异常（窄化定义，参考 D3.3.3 教训）===


class LLMError(Exception):
    """LLM 业务异常基类."""


class LLMTimeoutError(LLMError):
    """请求超时(httpx.TimeoutException 映射)."""


class LLMConnectionError(LLMError):
    """网络连接失败(httpx.ConnectError / RequestError)."""


class LLMAPIError(LLMError):
    """API 返回 4xx/5xx(httpx.HTTPStatusError 映射).

    Attributes:
        status_code: HTTP 状态码
        body: 响应体(截断到 500 字符, 防止巨型响应爆日志)
    """

    def __init__(self, message: str, status_code: int, body: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body[:500]


class LLMResponseError(LLMError):
    """响应解析失败(响应体非 JSON / 缺字段 / 字段类型错)."""


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


# === 各 provider 专用 API Key 环境变量名（v2 钩子驱动）===
# 加新 provider 只需在此表加一行

_API_KEY_ENV: dict[Provider, str] = {
    Provider.DEEPSEEK: "DEEPSEEK_API_KEY",
    Provider.QWEN: "DASHSCOPE_API_KEY",
    Provider.GLM: "GLM_API_KEY",
    Provider.MINIMAX: "MINIMAX_API_KEY",
    Provider.TENCENT: "TENCENT_API_KEY",
    Provider.OPENAI: "OPENAI_API_KEY",
    Provider.ANTHROPIC: "ANTHROPIC_API_KEY",
    # OLLAMA 无 Key
}


def _resolve_api_key(provider: Provider, override: str | None) -> str:
    """按 provider 解析 API Key.

    优先级: override > 专用 Key(DEEPSEEK_API_KEY 等) > OPENAI_API_KEY 兜底
    """
    if override:
        return override
    env_name = _API_KEY_ENV.get(provider, "OPENAI_API_KEY")
    return os.environ.get(env_name, "") or os.environ.get("OPENAI_API_KEY", "")


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible 协议 provider.

    适用: OpenAI / DeepSeek / Qwen / GLM / OpenRouter / Ollama / MiniMax / 腾讯混元
    共同特征: 接受 /v1/chat/completions 端点 + Bearer token.

    D4.1.1 实施: httpx 调用 + 响应解析, 抛 4 类窄化业务异常.
    """

    # 默认 HTTP 超时（秒）
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        provider_type: Provider,
        base_url: str,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._provider_type = provider_type
        self._base_url = base_url.rstrip("/")
        self._api_key = _resolve_api_key(provider_type, api_key)
        self._timeout = timeout

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
        return bool(self._base_url) and bool(self._api_key)

    def chat(self, request: LLMRequest) -> LLMResponse:
        """调用 /v1/chat/completions.

        流程:
          1. 构造 OpenAI 风格请求体
          2. httpx.post 同步调用
          3. 解析响应 → LLMResponse

        异常(窄化, 参考 D3.3.3 教训):
          - httpx.TimeoutException → LLMTimeoutError
          - httpx.ConnectError / RequestError → LLMConnectionError
          - HTTP 4xx/5xx → LLMAPIError(status_code + body)
          - 响应解析失败(非 JSON / 缺字段)→ LLMResponseError
          - 编程错误(TypeError / KeyError 在 model_id 等)→ 透传, 不包装
        """
        # 1. 构造请求体(从 full_id 拆 model_id)
        if "/" not in request.model_full_id:
            raise ValueError(
                f"model_full_id 格式错误: {request.model_full_id!r} (需 provider/model)"
            )
        model_id = request.model_full_id.split("/", 1)[1]
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": model_id,
            "messages": list(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        # 2. 同步调用 httpx（每次新建短连接，避免连接泄漏）
        # D3.3.3 教训: 异常范围要窄化 — 分层 except
        start = time.monotonic()
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(
                f"LLM 调用超时 ({self._timeout}s) | provider={self._provider_type.value} | "
                f"model={request.model_full_id}"
            ) from e
        except httpx.ConnectError as e:
            raise LLMConnectionError(
                f"LLM 连接失败 | provider={self._provider_type.value} | "
                f"base_url={self._base_url} | err={e}"
            ) from e
        except httpx.RequestError as e:
            # 其他网络错误(读取失败/写入失败/连接重置)
            raise LLMConnectionError(
                f"LLM 网络错误 | provider={self._provider_type.value} | err={e}"
            ) from e

        latency_ms = int((time.monotonic() - start) * 1000)

        # 3. 检查 HTTP 状态码
        if response.status_code >= 400:
            raise LLMAPIError(
                f"LLM API 错误 {response.status_code} | provider={self._provider_type.value}",
                status_code=response.status_code,
                body=response.text,
            )

        # 4. 解析响应(OpenAI 风格: choices[0].message.content + usage)
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError, ValueError) as e:
            # 响应结构异常(非 OpenAI 风格 / 缺字段)
            raise LLMResponseError(
                f"LLM 响应解析失败 | provider={self._provider_type.value} | "
                f"err={e} | body={response.text[:200]}"
            ) from e

        return LLMResponse(
            content=content,
            model_full_id=request.model_full_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )


# === Provider Factory ===


def get_provider(full_id: str) -> LLMProvider:
    """按 full_id 获取 provider 实例.

    Args:
        full_id: provider/model 格式(如 "deepseek/deepseek-chat")

    Returns:
        LLMProvider 实例(目前只返回 OpenAICompatibleProvider)

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
