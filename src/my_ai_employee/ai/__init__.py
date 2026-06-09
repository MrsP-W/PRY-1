"""L3 智能层。

4 个核心服务：
  - classifier          邮件 5 类分类（Claude Haiku）
  - drafter             邮件草稿生成（Claude Sonnet）
  - finance_analyzer    财务异常检测 + 月度报告（Claude Sonnet）
  - note_structurer     剪贴板/Notes 结构化（Claude Haiku）

当前 LLM：minimax M3（通过 Claude Code SDK）
Fallback：规则引擎（关键词/正则）— 不做本地 Ollama

D4（classifier + drafter）+ D8（finance_analyzer + note_structurer）实施。

Prompts 子包(D4.6 + D4.7.2):
  - ai.prompts.classify: D4.6 分类器 SYSTEM prompt + build_user_message
  - ai.prompts.draft:    D4.7.2 草稿 5+1 类 SYSTEM prompt + build_system_prompt 分发
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
from my_ai_employee.ai.drafter import (
    DraftBlockedResult,
    DrafterError,
    DrafterResponseError,
    DraftResult,
    DraftSpamReplyIntent,
    DraftTone,
    EmailDrafter,
    SpamBlockedError,
    has_markdown_fence,
    parse_draft_response,
    validate_draft_body,
    validate_draft_subject,
    validate_draft_tone,
)
from my_ai_employee.ai.fallback import (
    FALLBACK_CHAINS,
    CircuitBreaker,
    FallbackChainConfig,
    get_chain,
)
from my_ai_employee.ai.prompts import (
    CLASSIFY_SYSTEM_PROMPT,
    SYSTEM_PROMPT_DEFAULT,
    SYSTEM_PROMPT_FYI,
    SYSTEM_PROMPT_PERSONAL,
    SYSTEM_PROMPT_SPAM,
    SYSTEM_PROMPT_TODO,
    SYSTEM_PROMPT_URGENT,
    build_classify_user_message,
    build_draft_system_prompt,
    build_draft_user_message,
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
    # drafter (D4.7)
    "DrafterError",
    "DrafterResponseError",
    "DraftBlockedResult",
    "DraftResult",
    "DraftSpamReplyIntent",
    "DraftTone",
    "EmailDrafter",
    "SpamBlockedError",
    "has_markdown_fence",
    "parse_draft_response",
    "validate_draft_body",
    "validate_draft_subject",
    "validate_draft_tone",
    # prompts (D4.6 classify + D4.7.2 draft)
    "CLASSIFY_SYSTEM_PROMPT",
    "build_classify_user_message",
    "SYSTEM_PROMPT_DEFAULT",
    "SYSTEM_PROMPT_URGENT",
    "SYSTEM_PROMPT_TODO",
    "SYSTEM_PROMPT_FYI",
    "SYSTEM_PROMPT_SPAM",
    "SYSTEM_PROMPT_PERSONAL",
    "build_draft_system_prompt",
    "build_draft_user_message",
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
