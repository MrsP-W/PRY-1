"""受控 Agent Runtime — AgentRun 最小闭环（非角色 Markdown）。"""

from my_ai_employee.runtime.models import (
    ALLOWED_AGENT_RUN_TRANSITIONS,
    AgentRunRecord,
    AgentRunStatus,
)
from my_ai_employee.runtime.store import (
    AgentRunIllegalTransitionError,
    AgentRunNotFoundError,
    AgentRunStore,
)
from my_ai_employee.runtime.workflows.email_to_draft import (
    EmailToDraftInput,
    EmailToDraftResult,
    make_classify_fn,
    make_draft_fn,
    run_email_to_draft,
    stub_classify_fn,
    stub_draft_fn,
)

__all__ = [
    "ALLOWED_AGENT_RUN_TRANSITIONS",
    "AgentRunIllegalTransitionError",
    "AgentRunNotFoundError",
    "AgentRunRecord",
    "AgentRunStatus",
    "AgentRunStore",
    "EmailToDraftInput",
    "EmailToDraftResult",
    "make_classify_fn",
    "make_draft_fn",
    "run_email_to_draft",
    "stub_classify_fn",
    "stub_draft_fn",
]
