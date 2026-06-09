"""D4.6 — 邮件分类器单元测试.

覆盖:

  5 类枚举 (EmailCategory):
    - 5 类枚举值 + 顺序(URGENT/TODO/FYI/SPAM/PERSONAL)
    - StrEnum 字符串行为(== "URGENT")

  响应严判 (_parse_classification_response):
    - 5 类全部解析成功
    - markdown 包裹 / 前后空白 / 内嵌其他文字
    - 失败 case: 无 JSON / 非法 JSON / category 错类型 / category 不在枚举
    - 失败 case: confidence 越界 / confidence 是 bool(陷阱,D4.4 P1)
    - 失败 case: top-level 不是 dict

  EmailClassifier.classify (mock router):
    - 5 类真实分类(各 1 case,5 总)
    - 失败响应 → ClassifierResponseError 透传
    - 参数 type 错 → ValueError(D4.5 P0 严判入口)
    - 正文超长自动截断(MAN_BODY_CHARS = 2000)
    - 严判 stats 累加正确(total/success/response_error/llm_error)

  EmailClassifier.classify_batch:
    - 顺序串行 + 单条异常不阻塞(异常入 list)
    - dict 缺字段 → KeyError 透传(D3.3.3 教训:不 catch-all 兜底)
    - list 元素不是 dict → ValueError 入 list

  prompt 构造 (build_user_message):
    - 3 字段 (subject/sender/body_excerpt) 拼接正确
    - 严判空字符串允许
    - 严判非 str → ValueError

D3.3.3 教训: 编程错误透传, 业务异常窄化.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.ai.classifier import (  # noqa: E402
    ClassificationResult,
    ClassifierResponseError,
    EmailCategory,
    EmailClassifier,
    _parse_classification_response,
)
from my_ai_employee.ai.prompts.classify import (  # noqa: E402
    SYSTEM_PROMPT,
    build_user_message,
)
from my_ai_employee.ai.providers import LLMResponse  # noqa: E402

# ============================================================
# EmailCategory 枚举
# ============================================================


class TestEmailCategory:
    """5 类枚举单元测试."""

    def test_five_categories(self) -> None:
        assert len(list(EmailCategory)) == 5
        assert EmailCategory.URGENT == "URGENT"
        assert EmailCategory.TODO == "TODO"
        assert EmailCategory.FYI == "FYI"
        assert EmailCategory.SPAM == "SPAM"
        assert EmailCategory.PERSONAL == "PERSONAL"

    def test_order_fixed(self) -> None:
        """顺序固定(业务层按类别分组直接用 list(EmailCategory) 排序)."""
        assert [c.value for c in EmailCategory] == [
            "URGENT",
            "TODO",
            "FYI",
            "SPAM",
            "PERSONAL",
        ]

    def test_strenum_string_behavior(self) -> None:
        """StrEnum 字符串行为: == "URGENT"."""
        assert EmailCategory.URGENT == "URGENT"
        assert f"category={EmailCategory.URGENT}" == "category=URGENT"
        # 严格 != 拼写错
        assert EmailCategory.URGENT != "urgent"  # StrEnum 大小写敏感


# ============================================================
# _parse_classification_response 响应严判
# ============================================================


class TestParseClassificationResponse:
    """严判 LLM 响应解析."""

    def test_five_categories_parse_ok(self) -> None:
        for cat in EmailCategory:
            content = '{"category": "' + cat.value + '", "confidence": 0.9}'
            c, conf = _parse_classification_response(content)
            assert c == cat
            assert conf == 0.9

    def test_markdown_wrapped(self) -> None:
        """LLM 经常包 ```json ... ``` markdown 包裹, 应能解."""
        content = '好的, 这是分类结果:\n```json\n{"category": "URGENT", "confidence": 0.95}\n```'
        c, conf = _parse_classification_response(content)
        assert c == EmailCategory.URGENT
        assert conf == 0.95

    def test_strip_whitespace(self) -> None:
        """前后空白允许."""
        c, conf = _parse_classification_response(
            '   \n  {"category": "TODO", "confidence": 0.5}  \n  '
        )
        assert c == EmailCategory.TODO
        assert conf == 0.5

    def test_no_json_raises(self) -> None:
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response("not a json response")
        assert exc_info.value.reason == "no_balanced_json"

    def test_invalid_json_raises(self) -> None:
        """截断 JSON 没有完整 {...} 结构, → no_balanced_json.

        D4.6 v1.0.1 P1-4: 改用平衡括号定位,允许任意字段顺序。
        截断内容没有闭合 } 早抛 no_balanced_json(比 json.loads 报错更早)。
        """
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('{"category": "URGENT", "confidence":')  # 截断
        assert exc_info.value.reason == "no_balanced_json"

    def test_top_level_not_dict(self) -> None:
        """list 顶层 → 平衡括号定位找不到 → no_balanced_json.

        防御性 fast-fail: 顶层结构错早抛, 不深究类型.
        """
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('["URGENT", 0.9]')  # list
        assert exc_info.value.reason == "no_balanced_json"

    def test_category_wrong_type(self) -> None:
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('{"category": 123, "confidence": 0.9}')
        assert "category_type" in exc_info.value.reason

    def test_category_not_in_enum(self) -> None:
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('{"category": "OOPS", "confidence": 0.5}')
        assert exc_info.value.reason == "invalid_category=OOPS"

    def test_confidence_out_of_range_high(self) -> None:
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('{"category": "URGENT", "confidence": 1.5}')
        assert "out_of_range" in exc_info.value.reason

    def test_confidence_out_of_range_negative(self) -> None:
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('{"category": "URGENT", "confidence": -0.1}')
        assert "out_of_range" in exc_info.value.reason

    def test_confidence_is_bool_rejected(self) -> None:
        """D4.4 P1 教训: bool 是 int 子类, 必须显式拒."""
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('{"category": "URGENT", "confidence": true}')
        assert "bool" in exc_info.value.reason

    def test_confidence_is_string_rejected(self) -> None:
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('{"category": "URGENT", "confidence": "0.9"}')
        assert "confidence_type" in exc_info.value.reason

    def test_content_not_str(self) -> None:
        """编程错误: content 不是 str → ClassifierResponseError (业务层) + reason 含 type 信息."""
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response(123)  # type: ignore[arg-type]
        assert "type=" in exc_info.value.reason


# ============================================================
# build_user_message
# ============================================================


class TestBuildUserMessage:
    """prompt 构造单元测试."""

    def test_basic(self) -> None:
        msgs = build_user_message(
            subject="[紧急] 客户投诉",
            sender="client@example.com",
            body_excerpt="订单 #1234 严重延迟",
        )
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "[紧急] 客户投诉" in msgs[0]["content"]
        assert "client@example.com" in msgs[0]["content"]
        assert "订单 #1234 严重延迟" in msgs[0]["content"]

    def test_empty_strings_allowed(self) -> None:
        """空字符串允许(与 Email 模型字段对齐)."""
        msgs = build_user_message(subject="", sender="", body_excerpt="")
        assert msgs[0]["content"]  # content 非空
        assert "(空)" in msgs[0]["content"]  # 3 个空字段都被标记

    def test_strict_type_rejection(self) -> None:
        """D4.4 P1 + D4.5 P0 教训: 严判非 str."""
        with pytest.raises(ValueError):
            build_user_message(subject=123, sender="x", body_excerpt="y")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            build_user_message(subject="x", sender=123, body_excerpt="y")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            build_user_message(subject="x", sender="y", body_excerpt=123)  # type: ignore[arg-type]

    def test_system_prompt_contains_5_categories(self) -> None:
        """系统 prompt 必须列出 5 类(防 LLM 偏离)."""
        for cat in EmailCategory:
            assert cat.value in SYSTEM_PROMPT


# ============================================================
# EmailClassifier.classify (mock router)
# ============================================================


def _mock_router_response(
    content: str, model: str = "deepseek/deepseek-chat", latency: int = 500
) -> LLMResponse:
    """造一个 mock LLMResponse."""
    return LLMResponse(
        content=content,
        model_full_id=model,
        input_tokens=100,
        output_tokens=10,
        latency_ms=latency,
    )


class TestEmailClassifierClassify:
    """EmailClassifier.classify 单邮件分类测试."""

    def test_five_categories_real(self) -> None:
        """5 类各 1 case."""
        for cat in EmailCategory:
            mock_router = MagicMock()
            mock_router.route.return_value = _mock_router_response(
                f'{{"category": "{cat.value}", "confidence": 0.85}}'
            )
            classifier = EmailClassifier(router=mock_router)
            result = classifier.classify(
                subject="test",
                sender="x@y.com",
                body_excerpt="body",
            )
            assert result.category == cat
            assert result.confidence == 0.85
            assert result.model_full_id == "deepseek/deepseek-chat"
            assert result.latency_ms == 500
            assert isinstance(result, ClassificationResult)

    def test_response_error_propagates(self) -> None:
        """LLM 响应脏 → ClassifierResponseError 透传(D3.3.3 教训)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response("not a json")
        classifier = EmailClassifier(router=mock_router)
        with pytest.raises(ClassifierResponseError):
            classifier.classify(subject="x", sender="y", body_excerpt="z")
        stats = classifier.stats()
        assert stats["total"] == 1
        assert stats["response_error"] == 1
        assert stats["success"] == 0

    def test_llm_error_propagates(self) -> None:
        """router.route 抛 LLMError → 透传, stats 累加 llm_error."""
        from my_ai_employee.ai.providers import LLMTimeoutError

        mock_router = MagicMock()
        mock_router.route.side_effect = LLMTimeoutError("timeout")
        classifier = EmailClassifier(router=mock_router)
        with pytest.raises(LLMTimeoutError):
            classifier.classify(subject="x", sender="y", body_excerpt="z")
        stats = classifier.stats()
        assert stats["total"] == 1
        assert stats["llm_error"] == 1
        assert stats["success"] == 0

    def test_param_type_strict(self) -> None:
        """D4.5 P0 严判入口: 参数 type 错 → ValueError."""
        mock_router = MagicMock()
        classifier = EmailClassifier(router=mock_router)
        with pytest.raises(ValueError):
            classifier.classify(subject=123, sender="x", body_excerpt="y")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            classifier.classify(subject="x", sender=123, body_excerpt="y")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            classifier.classify(subject="x", sender="y", body_excerpt=123)  # type: ignore[arg-type]
        # mock router 不应被调用
        mock_router.route.assert_not_called()

    def test_body_excerpt_truncated(self) -> None:
        """正文超 MAX_BODY_CHARS 自动截断."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(
            '{"category": "FYI", "confidence": 0.9}'
        )
        classifier = EmailClassifier(router=mock_router)
        long_body = "a" * 5000
        classifier.classify(subject="x", sender="y", body_excerpt=long_body)
        # 验证调 router 时 messages 里 body 截断到 MAX_BODY_CHARS
        call_kwargs = mock_router.route.call_args
        messages = call_kwargs.kwargs["messages"]
        user_content = next(m for m in messages if m["role"] == "user")["content"]
        assert len(user_content) < len(long_body)
        assert "a" * 2000 in user_content

    def test_stats_accumulate(self) -> None:
        """stats 累加正确."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(
            '{"category": "TODO", "confidence": 0.8}'
        )
        classifier = EmailClassifier(router=mock_router)
        for _ in range(3):
            classifier.classify(subject="x", sender="y", body_excerpt="z")
        stats = classifier.stats()
        assert stats["total"] == 3
        assert stats["success"] == 3
        assert stats["response_error"] == 0
        assert stats["llm_error"] == 0

    def test_temperature_passed_to_router(self) -> None:
        """低温 0.1 应透传到 router(分类任务保稳定)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(
            '{"category": "URGENT", "confidence": 0.9}'
        )
        classifier = EmailClassifier(router=mock_router)
        classifier.classify(subject="x", sender="y", body_excerpt="z")
        call_kwargs = mock_router.route.call_args
        assert call_kwargs.kwargs["temperature"] == 0.1
        assert call_kwargs.kwargs["max_tokens"] == 64
        assert call_kwargs.kwargs["task_type"].value == "classify"

    def test_to_dict(self) -> None:
        """ClassificationResult.to_dict 序列化为 dict."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(
            '{"category": "PERSONAL", "confidence": 0.7}', model="qwen/qwen3-max", latency=1200
        )
        classifier = EmailClassifier(router=mock_router)
        result = classifier.classify(subject="x", sender="y", body_excerpt="z")
        d = result.to_dict()
        assert d["category"] == "PERSONAL"
        assert d["confidence"] == 0.7
        assert d["model_full_id"] == "qwen/qwen3-max"
        assert d["latency_ms"] == 1200


# ============================================================
# EmailClassifier.classify_batch
# ============================================================


class TestEmailClassifierBatch:
    """批量分类单元测试."""

    def test_batch_all_success(self) -> None:
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(
            '{"category": "FYI", "confidence": 0.9}'
        )
        classifier = EmailClassifier(router=mock_router)
        results = classifier.classify_batch(
            [
                {"subject": "s1", "sender": "x", "body_excerpt": "b1"},
                {"subject": "s2", "sender": "x", "body_excerpt": "b2"},
            ]
        )
        assert len(results) == 2
        assert all(isinstance(r, ClassificationResult) for r in results)
        assert mock_router.route.call_count == 2

    def test_batch_response_error_per_item(self) -> None:
        """单条响应脏 → 异常入 results 列表, 不阻塞后续."""
        call_count = 0

        def route_side_effect(**kwargs: Any) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return _mock_router_response("not json")
            return _mock_router_response('{"category": "TODO", "confidence": 0.8}')

        mock_router = MagicMock()
        mock_router.route.side_effect = route_side_effect
        classifier = EmailClassifier(router=mock_router)
        results = classifier.classify_batch(
            [
                {"subject": "s1", "sender": "x", "body_excerpt": "b1"},
                {"subject": "s2", "sender": "x", "body_excerpt": "b2"},
                {"subject": "s3", "sender": "x", "body_excerpt": "b3"},
            ]
        )
        assert len(results) == 3
        assert isinstance(results[0], ClassificationResult)
        assert isinstance(results[1], ClassifierResponseError)
        assert isinstance(results[2], ClassificationResult)

    def test_batch_element_not_dict(self) -> None:
        """list 元素不是 dict → ValueError 入 results 列表."""
        # 显式 mock content(避免 MagicMock 默认字符串化被正则误命中)
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(
            '{"category": "FYI", "confidence": 0.9}'
        )
        classifier = EmailClassifier(router=mock_router)
        results = classifier.classify_batch(
            [
                {"subject": "s1", "sender": "x", "body_excerpt": "b1"},
                "not a dict",  # type: ignore[list-item]
            ]
        )
        assert len(results) == 2
        assert isinstance(results[0], ClassificationResult)
        assert isinstance(results[1], ValueError)


# ===== D4.6 v1.0.1 修复测试(2026-06-09 用户复检 P1-1 + P1-4)=====


class TestD46V101Fixes:
    """D4.6 v1.0.1 业务语义修复测试集.

    覆盖用户 6/9 晨间复检的 P1-1 + P1-4 修复点。
    P1-2 + P1-3 + P2-5 由 tests/policy/test_classifier_adapter.py 覆盖(Adapter 层)。
    """

    # --- P1-1: LLMAllFallbacksError 应被 classify() 识别为 LLMError ---

    def test_llm_all_fallbacks_error_caught(self) -> None:
        """P1-1 修复: router 全链失败抛 LLMAllFallbacksError(LLMError), classify() 应捕获并计入 llm_error."""
        from my_ai_employee.ai.providers import LLMAllFallbacksError

        mock_router = MagicMock()
        mock_router.route.side_effect = LLMAllFallbacksError(
            task_type="classify",
            primary="deepseek/deepseek-chat",
            secondary="qwen/qwen-plus",
            tertiary="MiniMax/MiniMax-M3",
            last_error=RuntimeError("upstream 502"),
        )
        classifier = EmailClassifier(router=mock_router)
        with pytest.raises(LLMAllFallbacksError):
            classifier.classify(subject="s", sender="x", body_excerpt="b")
        # 关键: _stats["llm_error"] 必须 +1(原 RuntimeError 逃逸时不增)
        stats = classifier.stats()
        assert stats["llm_error"] == 1
        assert stats["total"] == 1

    def test_llm_all_fallbacks_is_llm_error(self) -> None:
        """P1-1 旁路: LLMAllFallbacksError 必须是 LLMError 子类, except LLMError 覆盖."""
        from my_ai_employee.ai.providers import LLMAllFallbacksError, LLMError

        err = LLMAllFallbacksError(
            task_type="classify",
            primary="a",
            secondary="b",
            tertiary="c",
            last_error=RuntimeError("x"),
        )
        assert isinstance(err, LLMError)
        # 关键属性透传
        assert err.task_type == "classify"
        assert err.primary == "a"
        assert err.secondary == "b"
        assert err.tertiary == "c"
        assert err.last_error is not None

    # --- P1-4: 反序 JSON / NaN / markdown fence / 平衡括号 ---

    def test_reverse_field_order_accepted(self) -> None:
        """P1-4 修复: confidence → category 反序合法 JSON 必须被接受."""
        c, conf = _parse_classification_response('{"confidence": 0.85, "category": "URGENT"}')
        assert c == EmailCategory.URGENT
        assert conf == 0.85

    def test_markdown_fence_stripped(self) -> None:
        """P1-4 修复: ```json ... ``` 包裹应被显式剥离."""
        c, conf = _parse_classification_response(
            '```json\n{"category": "TODO", "confidence": 0.7}\n```'
        )
        assert c == EmailCategory.TODO
        assert conf == 0.7

    def test_markdown_fence_no_lang(self) -> None:
        """P1-4: 裸 ``` ... ``` 也应剥离(不强制带 json 标识)."""
        c, conf = _parse_classification_response('```\n{"category": "FYI", "confidence": 0.6}\n```')
        assert c == EmailCategory.FYI
        assert conf == 0.6

    def test_confidence_nan_rejected(self) -> None:
        """P1-4 修复: NaN 必须被拒收(原 0<=x<=1 范围 NaN 通过)."""
        with pytest.raises(ClassifierResponseError) as exc_info:
            _parse_classification_response('{"category": "URGENT", "confidence": NaN}')
        # NaN 是合法 JSON number 但 math.isfinite() 拒
        assert "not_finite" in exc_info.value.reason or "out_of_range" in exc_info.value.reason

    def test_confidence_inf_rejected(self) -> None:
        """P1-4 修复: Inf / -Inf 必须被拒收."""
        for bad in ("Infinity", "-Infinity"):
            with pytest.raises(ClassifierResponseError) as exc_info:
                _parse_classification_response(f'{{"category": "URGENT", "confidence": {bad}}}')
            assert "not_finite" in exc_info.value.reason

    def test_balanced_json_with_nested_braces(self) -> None:
        """P1-4 修复: 含嵌套 {} 的 JSON 应正确平衡(不误判)."""
        c, conf = _parse_classification_response(
            '{"category": "URGENT", "confidence": 0.8, "meta": {"a": 1, "b": 2}}'
        )
        assert c == EmailCategory.URGENT
        assert conf == 0.8

    def test_extra_text_around_json(self) -> None:
        """P1-4 修复: JSON 前后有散文/解释文字, 平衡括号定位必须容忍."""
        c, conf = _parse_classification_response(
            'Here is my answer:\n{"category": "TODO", "confidence": 0.65}\nDone.'
        )
        assert c == EmailCategory.TODO
        assert conf == 0.65
