"""国际新闻 LLM 翻译的输入最小化与响应严判回归。"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from my_ai_employee.ai.capability import TaskType
from my_ai_employee.ai.providers import LLMResponse
from my_ai_employee.news.models import NewsItem
from my_ai_employee.news.translation import (
    NewsTranslationError,
    RouterNewsTranslator,
    parse_translation_response,
)


def _item(
    item_id: str = "global-1",
    *,
    title: str = "Enterprise AI agents expand",
    summary: str = "Companies are deploying more AI agents.",
    quote: str | None = 'CEO said: "Ship it."',
    region: str = "global",
) -> NewsItem:
    return NewsItem(
        item_id=item_id,
        title=title,
        summary=summary,
        url=f"https://example.com/{item_id}",
        source="Example",
        source_id="example",
        region=region,
        origin="official",
        kind="leader_statement" if quote else "event",
        published_at="2026-07-30T00:00:00Z",
        topics=("agent",),
        relevance="high",
        speaker="CEO" if quote else None,
        quote=quote,
        verbatim=quote is not None,
    )


class _FakeRouter:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []

    def route(
        self,
        task_type: TaskType,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        trace_id: str | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "task_type": task_type,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "trace_id": trace_id,
            }
        )
        return LLMResponse(
            content=self.content,
            model_full_id="minimax/MiniMax-M3",
            input_tokens=100,
            output_tokens=50,
            latency_ms=10,
        )


def _response(
    items: Sequence[NewsItem],
    *,
    title_zh: str = "企业扩大部署人工智能智能体",
    summary_zh: str = "越来越多的企业正在部署人工智能智能体。",
) -> str:
    return json.dumps(
        {
            "translations": [
                {
                    "id": f"n{index}",
                    "title_zh": title_zh,
                    "summary_zh": summary_zh if item.summary else "",
                }
                for index, item in enumerate(items)
            ]
        },
        ensure_ascii=False,
    )


def test_router_translator_sends_only_public_title_and_summary() -> None:
    quote = "We will deploy safe agents worldwide."
    item = _item(
        summary=f'The CEO said: "{quote}" during the briefing.',
        quote=quote,
    )
    router = _FakeRouter(_response([item]))

    translated = RouterNewsTranslator(router).translate([item])

    assert translated[item.item_id].title_zh == "企业扩大部署人工智能智能体"
    call = router.calls[0]
    assert call["task_type"] is TaskType.SUMMARIZE
    prompt = json.loads(call["messages"][1]["content"])  # type: ignore[index]
    assert prompt == {
        "items": [
            {
                "id": "n0",
                "title": item.title,
                "summary": ('The CEO said: "[官方英文原文摘录已单列]" during the briefing.'),
            }
        ]
    }
    serialized_prompt = json.dumps(prompt, ensure_ascii=False)
    assert item.item_id not in serialized_prompt
    assert item.item_id not in router.content
    assert item.quote is not None
    assert item.quote not in serialized_prompt
    assert item.url not in serialized_prompt


def test_parser_accepts_one_complete_leading_think_block() -> None:
    item = _item()
    content = f"<think>internal reasoning</think>\n{_response([item])}"

    translated = parse_translation_response(content, [item])

    assert translated[item.item_id].summary_zh == "越来越多的企业正在部署人工智能智能体。"


@pytest.mark.parametrize(
    "content",
    (
        'explanation\n{"translations":[]}',
        '```json\n{"translations":[]}\n```',
        "<think>unfinished",
        '<think>ok</think>\n{"translations":[]} trailing',
    ),
)
def test_parser_rejects_wrappers_or_incomplete_think(content: str) -> None:
    with pytest.raises(NewsTranslationError):
        parse_translation_response(content, [_item()])


@pytest.mark.parametrize(
    ("payload", "reason"),
    (
        (
            {
                "translations": [
                    {
                        "id": "unexpected",
                        "title_zh": "中文标题",
                        "summary_zh": "中文摘要",
                    }
                ]
            },
            "translation_id",
        ),
        (
            {
                "translations": [
                    {
                        "id": "n0",
                        "title_zh": "English only",
                        "summary_zh": "中文摘要",
                    }
                ]
            },
            "title_zh_cjk",
        ),
        (
            {
                "translations": [
                    {
                        "id": "n0",
                        "title_zh": "中文标题",
                        "summary_zh": "中文摘要",
                        "quote_zh": "禁止字段",
                    }
                ]
            },
            "translation_shape",
        ),
    ),
)
def test_parser_rejects_invalid_ids_non_chinese_or_extra_fields(
    payload: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(NewsTranslationError, match=reason):
        parse_translation_response(json.dumps(payload, ensure_ascii=False), [_item()])


def test_parser_requires_exact_id_set_and_empty_summary_stays_empty() -> None:
    first = _item("global-1")
    second = _item("global-2")
    with pytest.raises(NewsTranslationError, match="translation_id_set"):
        parse_translation_response(_response([first]), [first, second])

    empty_summary = _item(summary="")
    invalid = _response([empty_summary], summary_zh="模型新增摘要")
    payload = json.loads(invalid)
    payload["translations"][0]["summary_zh"] = "模型新增摘要"
    with pytest.raises(NewsTranslationError, match="summary_zh_unexpected"):
        parse_translation_response(json.dumps(payload, ensure_ascii=False), [empty_summary])


def test_translator_rejects_non_global_items_before_router_call() -> None:
    router = _FakeRouter('{"translations":[]}')

    with pytest.raises(ValueError, match="region=global"):
        RouterNewsTranslator(router).translate([_item(region="cn")])

    assert router.calls == []
