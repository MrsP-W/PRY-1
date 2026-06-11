"""LLM Prompt 模板集合 — D4.6 起步, D4.7.4 扩展.

每个 prompt 是一个常量字符串,直接喂给 `router.route(TaskType.X, messages)`.

设计原则:
  - 中文为主 (项目主场景是国内邮件)
  - system 提示 + user 输入分离 (OpenAI 风格)
  - 严禁把可变对象 (如 dict / list) 暴露为 prompt 内部状态
  - 每个 prompt 配 "任务元数据" 段,便于 trace 关联(后续可加 fingerprint)
"""

from my_ai_employee.ai.prompts.classify import (
    SYSTEM_PROMPT as CLASSIFY_SYSTEM_PROMPT,
)
from my_ai_employee.ai.prompts.classify import (
    build_user_message as build_classify_user_message,
)
from my_ai_employee.ai.prompts.draft import (
    SYSTEM_PROMPT_DEFAULT,
    SYSTEM_PROMPT_FYI,
    SYSTEM_PROMPT_PERSONAL,
    SYSTEM_PROMPT_SPAM,
    SYSTEM_PROMPT_TODO,
    SYSTEM_PROMPT_URGENT,
)
from my_ai_employee.ai.prompts.draft import (
    build_system_prompt as build_draft_system_prompt,
)
from my_ai_employee.ai.prompts.draft import (
    build_user_message as build_draft_user_message,
)
from my_ai_employee.ai.prompts.review import (
    build_system_prompt as build_review_system_prompt,
)
from my_ai_employee.ai.prompts.review import (
    build_user_message as build_review_user_message,
)

__all__ = [
    # classify (D4.6)
    "CLASSIFY_SYSTEM_PROMPT",
    "build_classify_user_message",
    # draft (D4.7.2)
    "SYSTEM_PROMPT_DEFAULT",
    "SYSTEM_PROMPT_URGENT",
    "SYSTEM_PROMPT_TODO",
    "SYSTEM_PROMPT_FYI",
    "SYSTEM_PROMPT_SPAM",
    "SYSTEM_PROMPT_PERSONAL",
    "build_draft_system_prompt",
    "build_draft_user_message",
    # review (D4.7.4)
    "build_review_system_prompt",
    "build_review_user_message",
]
