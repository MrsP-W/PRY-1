"""L3 智能层。

5 个核心服务：
  - classifier          邮件 5 类分类（Claude Haiku）
  - drafter             邮件草稿生成（Claude Sonnet）
  - reviewer            邮件草稿审阅（LLM + 本地规则）
  - finance_analyzer    财务异常检测 + 月度报告（Claude Sonnet）
  - note_structurer     剪贴板/Notes 结构化（Claude Haiku, D9.4 实施）

当前 LLM：minimax M3（通过 Claude Code SDK）
Fallback：规则引擎（关键词/正则）— 不做本地 Ollama

D4（classifier + drafter + reviewer）+ D8（finance_analyzer 延后 v0.2）+ D9.4（note_structurer）实施。
（2026-06-15 修正：D8 智能财务延后 v0.2, note_structurer 实际归 D9.4 实施,
docs/v0.1-launch-plan.md:111-143 D9 段锁定契约）

Prompts 子包(D4.6 + D4.7.2 + D4.7.4 + D9.4):
  - ai.prompts.classify:        D4.6 分类器 SYSTEM prompt + build_user_message
  - ai.prompts.draft:           D4.7.2 草稿 5+1 类 SYSTEM prompt + build_system_prompt 分发
  - ai.prompts.review:          D4.7.4 审阅 5+1 类 SYSTEM prompt + 三字段裸 JSON 契约
  - ai.prompts.note_structurer: D9.4 笔记结构化 6 类 SYSTEM prompt + 抗注入 user 消息
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
from my_ai_employee.ai.note_structurer import (  # noqa: E402
    FailureDecisionReport,
    NoteNotFoundError,
    NoteStructurerService,
    PrivateSkipDecisionReport,
    StructuredNote,
)
from my_ai_employee.ai.prompts import (
    CLASSIFY_SYSTEM_PROMPT,
    NOTE_STRUCTURER_SYSTEM_PROMPT_DEFAULT,
    NOTE_STRUCTURER_SYSTEM_PROMPT_FYI,
    NOTE_STRUCTURER_SYSTEM_PROMPT_PERSONAL,
    NOTE_STRUCTURER_SYSTEM_PROMPT_SPAM,
    NOTE_STRUCTURER_SYSTEM_PROMPT_TODO,
    NOTE_STRUCTURER_SYSTEM_PROMPT_URGENT,
    SYSTEM_PROMPT_DEFAULT,
    SYSTEM_PROMPT_FYI,
    SYSTEM_PROMPT_PERSONAL,
    SYSTEM_PROMPT_SPAM,
    SYSTEM_PROMPT_TODO,
    SYSTEM_PROMPT_URGENT,
    build_classify_user_message,
    build_draft_system_prompt,
    build_draft_user_message,
    build_note_structurer_system_prompt,
    build_note_structurer_user_message,
    build_review_system_prompt,
    build_review_user_message,
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
from my_ai_employee.ai.reviewer import (
    EmailReviewer,
    ReviewBlockedResult,
    ReviewBlockReason,
    ReviewerError,
    ReviewerResponseError,
    ReviewFailureResult,
    ReviewResult,
    parse_review_response,
)
from my_ai_employee.ai.reviewer import (
    has_markdown_fence as has_review_markdown_fence,
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
    # reviewer (D4.7.4)
    "EmailReviewer",
    "ReviewBlockedResult",
    "ReviewBlockReason",
    "ReviewerError",
    "ReviewerResponseError",
    "ReviewFailureResult",
    "ReviewResult",
    "has_review_markdown_fence",
    "parse_review_response",
    # prompts (D4.6 classify + D4.7.2 draft + D4.7.4 review)
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
    "build_note_structurer_system_prompt",
    "build_note_structurer_user_message",
    "build_review_system_prompt",
    "build_review_user_message",
    "NOTE_STRUCTURER_SYSTEM_PROMPT_DEFAULT",
    "NOTE_STRUCTURER_SYSTEM_PROMPT_URGENT",
    "NOTE_STRUCTURER_SYSTEM_PROMPT_TODO",
    "NOTE_STRUCTURER_SYSTEM_PROMPT_FYI",
    "NOTE_STRUCTURER_SYSTEM_PROMPT_SPAM",
    "NOTE_STRUCTURER_SYSTEM_PROMPT_PERSONAL",
    # fallback
    "FALLBACK_CHAINS",
    "CircuitBreaker",
    "FallbackChainConfig",
    "get_chain",
    # note_structurer (D9.4 — 5 公共符号, 简化 4 依赖为 3 依赖, 不接 PolicyEngine)
    "FailureDecisionReport",
    "NoteNotFoundError",
    "NoteStructurerService",
    "PrivateSkipDecisionReport",
    "StructuredNote",
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
