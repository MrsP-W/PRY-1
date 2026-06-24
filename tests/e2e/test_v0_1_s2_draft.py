"""S2 — 1-click 草稿生成 → drafter < 10s(Week 1 路径).

承接 docs/v0.1-launch-plan.md:217 S2 唯一编号表行。

D6.0 范围(2026-06-14 启动):
    - 5 封分类后的 faker 邮件
    - EmailDrafter.draft 生成 DraftResult(Mock LLM router,无真实 LLM)
    - 断言:草稿生成 < 10s + body_length 10-8000 + tone 在 3 类中 + DraftResult 字段齐

跑法:
    pytest tests/e2e/test_v0_1_s2_draft.py -v
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _make_router_mock() -> Any:
    """Mock LLM router,返回固定 DraftResult JSON."""
    from my_ai_employee.ai.providers import LLMResponse

    class _MockRouter:
        def route(self, *, task_type: Any, messages: Any, temperature: Any, max_tokens: Any) -> Any:
            return LLMResponse(
                content=(
                    '{"subject": "Re: 客户投诉处理", '
                    '"body": "尊敬的客户您好,针对您反馈的问题我们正在处理中,'
                    '请耐心等待,感谢您的理解与支持。", '
                    '"tone": "FORMAL"}'
                ),
                model_full_id="mock-drafter-e2e",
                input_tokens=100,
                output_tokens=80,
                latency_ms=20,
            )

    return _MockRouter()


@pytest.mark.e2e
def test_s2_draft_single_email() -> Any:
    """S2.1 — 单邮件 drafter 草稿生成 < 10s,body_length 10-8000,tone 在 3 类中."""
    from my_ai_employee.ai.drafter import DraftResult, DraftTone, EmailDrafter

    drafter = EmailDrafter(router=_make_router_mock())  # type: ignore[arg-type]

    start = time.time()
    result = drafter.draft(
        subject="服务器故障",
        sender="customer@example.com",
        body_excerpt="我们这边服务器挂了,影响业务,请尽快处理。",
    )
    elapsed = time.time() - start

    # 业务契约
    assert isinstance(result, DraftResult)
    assert elapsed < 10.0, f"drafter 草稿生成应 < 10s,实际 {elapsed:.2f}s"
    assert 10 <= len(result.body) <= 8000, f"body_length 应在 10-8000,实际 {len(result.body)}"
    assert result.tone in DraftTone
    assert result.model_full_id == "mock-drafter-e2e"
    assert result.spam_reply_authorized is False  # 默认未授权


@pytest.mark.e2e
def test_s2_draft_batch_5_emails() -> Any:
    """S2.2 — 5 封 drafter 顺序生成,全部成功 < 30s."""
    from my_ai_employee.ai.drafter import DraftResult, EmailDrafter

    drafter = EmailDrafter(router=_make_router_mock())  # type: ignore[arg-type]
    emails = [
        {"subject": f"邮件 #{i}", "sender": f"u{i}@x.com", "body_excerpt": f"内容 {i}"}
        for i in range(5)
    ]

    start = time.time()
    results = drafter.draft_batch(emails)  # type: ignore[arg-type]
    elapsed = time.time() - start

    assert len(results) == 5
    assert all(isinstance(r, DraftResult) for r in results)
    assert elapsed < 30.0, f"5 封 drafter 应 < 30s,实际 {elapsed:.2f}s"


@pytest.mark.e2e
def test_s2_draft_spam_blocked_by_default() -> Any:
    """S2.3 — SPAM 邮件默认被业务硬阻断(SpamBlockedError)."""
    from my_ai_employee.ai.classifier import EmailCategory
    from my_ai_employee.ai.drafter import EmailDrafter, SpamBlockedError

    drafter = EmailDrafter(router=_make_router_mock())  # type: ignore[arg-type]

    with pytest.raises(SpamBlockedError):
        drafter.draft(
            subject="打折促销",
            sender="spam@x.com",
            body_excerpt="点击链接赢大奖",
            email_category=EmailCategory.SPAM,
            allow_spam_reply=False,  # 默认 False → 阻断
        )
