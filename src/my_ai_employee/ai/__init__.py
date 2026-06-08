"""L3 智能层。

4 个核心服务：
  - classifier          邮件 5 类分类（Claude Haiku）
  - drafter             邮件草稿生成（Claude Sonnet）
  - finance_analyzer    财务异常检测 + 月度报告（Claude Sonnet）
  - note_structurer     剪贴板/Notes 结构化（Claude Haiku）

当前 LLM：minimax M3（通过 Claude Code SDK）
Fallback：规则引擎（关键词/正则）— 不做本地 Ollama

D4（classifier + drafter）+ D8（finance_analyzer + note_structurer）实施。
"""

from my_ai_employee.ai.capability import (
    CAPABILITY_REGISTRY,
    ModelCapability,
    Provider,
    TaskType,
    get_capability,
    list_models,
)
from my_ai_employee.ai.classifier import (
    ClassificationResult,
    ClassifierError,
    ClassifierResponseError,
    EmailCategory,
    EmailClassifier,
)
from my_ai_employee.ai.fallback import (
    FALLBACK_CHAINS,
    CircuitBreaker,
    FallbackChainConfig,
    get_chain,
)
from my_ai_employee.ai.providers import (
    LLMAPIError,
    LLMConnectionError,
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    OpenAICompatibleProvider,
    get_provider,
)
from my_ai_employee.ai.router import LLMRouter, RouterStats, get_router

__all__ = [
    # capability
    "CAPABILITY_REGISTRY",
    "ModelCapability",
    "Provider",
    "TaskType",
    "get_capability",
    "list_models",
    # classifier (D4.6)
    "ClassificationResult",
    "ClassifierError",
    "ClassifierResponseError",
    "EmailCategory",
    "EmailClassifier",
    # fallback
    "FALLBACK_CHAINS",
    "CircuitBreaker",
    "FallbackChainConfig",
    "get_chain",
    # providers
    "LLMAPIError",
    "LLMConnectionError",
    "LLMError",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMTimeoutError",
    "OpenAICompatibleProvider",
    "get_provider",
    # router
    "LLMRouter",
    "RouterStats",
    "get_router",
]
