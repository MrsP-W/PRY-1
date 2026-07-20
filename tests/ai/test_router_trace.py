"""Router trace_id 透传回归。"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from my_ai_employee.ai.capability import TaskType
from my_ai_employee.ai.providers import LLMRequest, LLMResponse
from my_ai_employee.ai.router import LLMRouter


def test_router_last_trace_includes_trace_id(monkeypatch: Any) -> None:
    router = LLMRouter()

    class _Prov:
        def healthcheck(self) -> bool:
            return True

        def chat(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                content="ok",
                model_full_id=request.model_full_id,
                input_tokens=1,
                output_tokens=2,
                latency_ms=3,
            )

    monkeypatch.setattr(
        "my_ai_employee.ai.router.get_chain",
        lambda _t: MagicMock(primary="stub:model", secondary="stub:b", tertiary="stub:c"),
    )
    monkeypatch.setattr(
        "my_ai_employee.ai.router.get_capability",
        lambda _fid: MagicMock(is_reasoning=False),
    )
    monkeypatch.setattr("my_ai_employee.ai.router.get_provider", lambda _fid: _Prov())

    resp = router.route(
        TaskType.CLASSIFY,
        [{"role": "user", "content": "hi"}],
        trace_id="trace-abc",
    )
    assert resp.content == "ok"
    trace = router.last_trace()
    assert trace["trace_id"] == "trace-abc"
    assert trace["ok"] is True
    assert trace["attempts"][0]["input_tokens"] == 1
    # stats() 契约不变
    stats = router.stats()
    assert "primary_attempts" in stats
    assert "trace_id" not in stats
