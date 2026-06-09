"""D4.7 — 邮件草稿生成器单元测试.

覆盖:

  DraftTone 枚举(契约 3):
    - 3 类枚举值 + 顺序(FORMAL/FRIENDLY/CONCISE)
    - StrEnum 字符串行为

  严判 helper (_validate_draft_subject / _validate_draft_body / _validate_draft_tone):
    - 边界值(契约 1 长度上下界)
    - 非法类型(bool 子类陷阱 / None / list / int)
    - 严判入口(契约 1 公共 API 自防御)

  解析 (_parse_draft_response):
    - 合法响应(subject + body + tone 3 字段)
    - 任意字段顺序(D4.6 范本复用)
    - 拒 markdown-wrapped JSON(契约 2 核心)
    - 拒非法 tone(契约 3 核心)
    - 拒长度越界(契约 1)
    - 失败 case: 无 JSON / 非法 JSON / 顶层非 dict

  has_markdown_fence(契约 2 公共 API):
    - 3 种 fence 形式
    - 裸 JSON / 非 str 输入

  validate_draft 公共 API(契约 1):
    - 合法草稿 → True
    - 4 类非法 → False(不抛错)

  EmailDrafter.draft (mock router):
    - 合法草稿返回 DraftResult
    - 响应脏 → DrafterResponseError 透传
    - 参数 type 错 → ValueError 严判
    - 正文超长自动截断
    - email_category None 允许
    - tone 字符串合法/非法

  EmailDrafter.draft_batch:
    - 顺序串行 + 单条异常不阻塞
    - dict 缺字段 → KeyError 透传(D4.6 范本)
    - list 元素不是 dict → ValueError 入 list

  DraftResult data class:
    - to_dict 序列化
    - frozen 不可变
    - 字段集合

  4 项契约锁定测试(D4.7.1 起始固定):
    - 契约 1: 草稿无 confidence 字段
    - 契约 2: 拒 markdown-wrapped JSON
    - 契约 3: tone 枚举锁定 3 类
    - 契约 4: 范围限定(ast 验证不 import db/events/policy/sqlalchemy)

D3.3.3 教训: 编程错误透传, 业务异常窄化.
D4.7 4 项契约(2026-06-09 用户审批锁定): 严判入口下沉到公共 API, 严判下沉到 helper.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.ai.drafter import (  # noqa: E402
    DrafterError,
    DrafterResponseError,
    DraftResult,
    DraftTone,
    EmailDrafter,
    _parse_draft_response,
    has_markdown_fence,
    parse_draft_response,
    validate_draft_body,
    validate_draft_subject,
    validate_draft_tone,
)
from my_ai_employee.ai.providers import LLMResponse  # noqa: E402

# 修复未使用导入警告
_ = (DrafterError,)

# ============================================================
# Mock helpers
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


def _valid_draft_json(
    *,
    subject: str = "Re: 项目进度",
    body: str = "感谢您的来信, 项目进展顺利, 我们将在 6 月底前完成。",
    tone: str = "FORMAL",
) -> str:
    """造一个合法的草稿 JSON 响应."""
    return f'{{"subject": "{subject}", "body": "{body}", "tone": "{tone}"}}'


# ============================================================
# Section 0: DraftTone 枚举(契约 3 锁定 3 类)
# ============================================================


class TestDraftToneEnum:
    """3 类 tone 枚举(契约 3 锁定)."""

    def test_three_tones(self) -> None:
        assert len(list(DraftTone)) == 3
        assert DraftTone.FORMAL == "FORMAL"
        assert DraftTone.FRIENDLY == "FRIENDLY"
        assert DraftTone.CONCISE == "CONCISE"

    def test_order_fixed(self) -> None:
        """顺序固定(业务层按语气分组直接用 list(DraftTone) 排序)."""
        assert [t.value for t in DraftTone] == ["FORMAL", "FRIENDLY", "CONCISE"]

    def test_strenum_string_behavior(self) -> None:
        """StrEnum 字符串行为(== "FORMAL")."""
        assert DraftTone.FORMAL == "FORMAL"
        assert f"语气: {DraftTone.FORMAL.value}" == "语气: FORMAL"


# ============================================================
# Section 1: 严判 _validate_draft_* helper(契约 1 公共 API)
# ============================================================


class TestValidateDraftSubject:
    """subject 严判 helper(契约 1: 1-200 字符)."""

    def test_accepts_normal(self) -> None:
        validate_draft_subject("Re: 项目进度")

    def test_accepts_min_length(self) -> None:
        """边界 1 字符."""
        validate_draft_subject("A")

    def test_accepts_max_length(self) -> None:
        """边界 200 字符."""
        validate_draft_subject("A" * 200)

    def test_rejects_empty(self) -> None:
        """契约 1: subject 非空(0 字符拒收)."""
        with pytest.raises(ValueError, match="subject 太短"):
            validate_draft_subject("")

    def test_rejects_too_long(self) -> None:
        """契约 1: subject 长度 > 200 拒收."""
        with pytest.raises(ValueError, match="subject 太长"):
            validate_draft_subject("A" * 201)

    def test_rejects_non_str(self) -> None:
        """D4.4 P1 教训: type 错 → ValueError 透传."""
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(["A"])  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        """D4.4 P1 教训: 拒 bool 子类陷阱(isinstance(True, int) == True)."""
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(True)  # type: ignore[arg-type]


class TestValidateDraftBody:
    """body 严判 helper(契约 1: 10-8000 字符)."""

    def test_accepts_normal(self) -> None:
        validate_draft_body("感谢您的来信, 项目进展顺利。")

    def test_accepts_min_length(self) -> None:
        """边界 10 字符."""
        validate_draft_body("A" * 10)

    def test_accepts_max_length(self) -> None:
        """边界 8000 字符."""
        validate_draft_body("A" * 8000)

    def test_rejects_too_short(self) -> None:
        """契约 1: body < 10 字符拒收."""
        with pytest.raises(ValueError, match="body 太短"):
            validate_draft_body("A" * 9)

    def test_rejects_too_long(self) -> None:
        """契约 1: body > 8000 字符拒收."""
        with pytest.raises(ValueError, match="body 太长"):
            validate_draft_body("A" * 8001)

    def test_rejects_empty(self) -> None:
        """契约 1: body 0 字符拒收."""
        with pytest.raises(ValueError, match="body 太短"):
            validate_draft_body("")

    def test_rejects_non_str(self) -> None:
        """D4.4 P1 教训: type 错 → ValueError 透传."""
        with pytest.raises(ValueError, match="body 必须是 str"):
            validate_draft_body(123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="body 必须是 str"):
            validate_draft_body(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="body 必须是 str"):
            validate_draft_body(["x"] * 10)  # type: ignore[arg-type]


class TestValidateDraftTone:
    """tone 严判 helper(契约 3 锁定 3 类)."""

    def test_accepts_enum(self) -> None:
        validate_draft_tone(DraftTone.FORMAL)
        validate_draft_tone(DraftTone.FRIENDLY)
        validate_draft_tone(DraftTone.CONCISE)

    def test_accepts_valid_string(self) -> None:
        """契约 3: 字符串必须 ∈ {FORMAL, FRIENDLY, CONCISE}."""
        validate_draft_tone("FORMAL")
        validate_draft_tone("FRIENDLY")
        validate_draft_tone("CONCISE")

    def test_rejects_invalid_string(self) -> None:
        """契约 3: 非法枚举值 → ValueError(拒 APOLOGETIC / INSPIRATIONAL)."""
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone("APOLOGETIC")
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone("INSPIRATIONAL")
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone("formal")  # 大小写敏感
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone("")

    def test_rejects_non_str_non_enum(self) -> None:
        """type 错 → ValueError 透传."""
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone(123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone(["FORMAL"])  # type: ignore[arg-type]


# ============================================================
# Section 2: 解析 _parse_draft_response(契约 2 + 契约 3 核心)
# ============================================================


class TestParseDraftResponse:
    """_parse_draft_response 严判解析主函数(契约 1 + 2 + 3)."""

    def test_accepts_valid_response(self) -> None:
        """合法 3 字段."""
        result = _parse_draft_response(_valid_draft_json())
        subject, body, tone = result
        assert subject == "Re: 项目进度"
        assert tone == DraftTone.FORMAL

    def test_accepts_arbitrary_field_order(self) -> None:
        """D4.6 范本: 不强制字段顺序."""
        content = (
            '{"tone": "FRIENDLY", "body": "感谢您的支持与配合, 我们会尽快处理。", "subject": "Hi"}'
        )
        subject, body, tone = _parse_draft_response(content)
        assert tone == DraftTone.FRIENDLY
        assert subject == "Hi"

    def test_accepts_all_three_tones(self) -> None:
        """契约 3: 3 类 tone 全部解析成功."""
        for tone in DraftTone:
            content = _valid_draft_json(tone=tone.value)
            _, _, parsed_tone = _parse_draft_response(content)
            assert parsed_tone == tone

    def test_rejects_non_str_content(self) -> None:
        """type 错 → DrafterResponseError(业务异常)."""
        with pytest.raises(DrafterResponseError, match="LLM content 必须是 str"):
            _parse_draft_response(123)  # type: ignore[arg-type]
        with pytest.raises(DrafterResponseError, match="LLM content 必须是 str"):
            _parse_draft_response(None)  # type: ignore[arg-type]

    def test_rejects_markdown_fenced_json(self) -> None:
        """**契约 2 核心**: 拒 ```json ... ``` 包裹的 JSON(D4.7 决择: 不剥离)."""
        fenced = '```json\n{"subject": "Re: 项目", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}\n```'
        with pytest.raises(DrafterResponseError, match="markdown fence") as exc_info:
            _parse_draft_response(fenced)
        assert exc_info.value.reason == "markdown_fenced"

    def test_rejects_markdown_fenced_no_language(self) -> None:
        """**契约 2**: 拒 ``` ... ```(无语言标识) 包裹."""
        fenced = '```\n{"subject": "Re: 项目", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}\n```'
        with pytest.raises(DrafterResponseError, match="markdown fence"):
            _parse_draft_response(fenced)

    def test_rejects_no_balanced_json(self) -> None:
        """无平衡 JSON 块 → DrafterResponseError."""
        with pytest.raises(DrafterResponseError, match="未找到平衡的 JSON 块"):
            _parse_draft_response("not a json at all")

    def test_rejects_non_dict_json(self) -> None:
        """JSON 顶层非 object → DrafterResponseError(实际是 'no_balanced_json')."""
        # 注: `{...}` 在 JSON 中永远 parse 成 dict, 故 "顶层必须是 object" 分支不可达.
        # 实际拒绝路径: 数组 `[1,2,3]` 不含 `{`, 平衡括号扫描失败 → no_balanced_json.
        with pytest.raises(DrafterResponseError, match="未找到平衡的 JSON 块"):
            _parse_draft_response("[1, 2, 3]")

    def test_rejects_invalid_tone(self) -> None:
        """**契约 3 核心**: 非法 tone → DrafterResponseError."""
        content = (
            '{"subject": "Re: x", "body": "感谢您的来信, 项目进展顺利。", "tone": "APOLOGETIC"}'
        )
        with pytest.raises(DrafterResponseError, match="tone 值不在 3 类枚举中") as exc_info:
            _parse_draft_response(content)
        assert "invalid_tone=APOLOGETIC" in exc_info.value.reason

    def test_rejects_short_body(self) -> None:
        """**契约 1 核心**: body < 10 字符 → DrafterResponseError."""
        content = '{"subject": "Re: x", "body": "短", "tone": "FORMAL"}'
        with pytest.raises(DrafterResponseError, match="body 业务验收未通过") as exc_info:
            _parse_draft_response(content)
        assert "body_invalid_len" in exc_info.value.reason

    def test_rejects_long_subject(self) -> None:
        """**契约 1 核心**: subject > 200 字符 → DrafterResponseError."""
        content = (
            '{"subject": "'
            + "A" * 201
            + '", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}'
        )
        with pytest.raises(DrafterResponseError, match="subject 业务验收未通过"):
            _parse_draft_response(content)

    def test_rejects_non_str_subject(self) -> None:
        """type 错 → DrafterResponseError."""
        content = '{"subject": 123, "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}'
        with pytest.raises(DrafterResponseError, match="subject 字段必须是 str"):
            _parse_draft_response(content)


# ============================================================
# Section 3: has_markdown_fence(契约 2 公共 API)
# ============================================================


class TestHasMarkdownFence:
    """has_markdown_fence 公共 API(契约 2)."""

    def test_detects_json_fence(self) -> None:
        assert has_markdown_fence('```json\n{"x": 1}\n```') is True

    def test_detects_uppercase_json_fence(self) -> None:
        assert has_markdown_fence('```JSON\n{"x": 1}\n```') is True

    def test_detects_no_language_fence(self) -> None:
        assert has_markdown_fence('```\n{"x": 1}\n```') is True

    def test_returns_false_for_raw_json(self) -> None:
        """裸 JSON 不含 fence → False."""
        assert has_markdown_fence('{"x": 1}') is False

    def test_returns_false_for_non_str(self) -> None:
        """非 str 输入(留到 _parse_draft_response 上层抛 type 错)."""
        assert has_markdown_fence(123) is False  # type: ignore[arg-type]
        assert has_markdown_fence(None) is False  # type: ignore[arg-type]

    def test_returns_false_for_fence_in_body(self) -> None:
        """fence 在 body 字段内也是 fence(整体检测, 不区分位置)."""
        content = (
            '{"subject": "x", "body": "请看 ```python\\nprint(1)\\n``` 这段代码", "tone": "FORMAL"}'
        )
        # 契约 2 拒收, 含 fence → True
        assert has_markdown_fence(content) is True


# ============================================================
# Section 4: validate_draft 公共 API(契约 1 业务验收)
# ============================================================


class TestValidateDraftPublicAPI:
    """EmailDrafter.validate_draft 公共 API(契约 1)."""

    def test_accepts_valid_draft(self) -> None:
        drafter = EmailDrafter(router=MagicMock())
        assert (
            drafter.validate_draft(
                subject="Re: 项目",
                body="感谢您的来信, 项目进展顺利。",
                tone=DraftTone.FORMAL,
            )
            is True
        )

    def test_accepts_valid_draft_str_tone(self) -> None:
        """tone 字符串合法."""
        drafter = EmailDrafter(router=MagicMock())
        assert (
            drafter.validate_draft(
                subject="Re: 项目",
                body="感谢您的来信, 项目进展顺利。",
                tone="FRIENDLY",
            )
            is True
        )

    def test_rejects_empty_subject(self) -> None:
        """契约 1: 空 subject → False(不抛错, 由调用方决定)."""
        drafter = EmailDrafter(router=MagicMock())
        assert (
            drafter.validate_draft(
                subject="",
                body="感谢您的来信, 项目进展顺利。",
                tone=DraftTone.FORMAL,
            )
            is False
        )

    def test_rejects_short_body(self) -> None:
        """契约 1: body < 10 → False."""
        drafter = EmailDrafter(router=MagicMock())
        assert (
            drafter.validate_draft(
                subject="Re: x",
                body="短",
                tone=DraftTone.FORMAL,
            )
            is False
        )

    def test_rejects_long_body(self) -> None:
        """契约 1: body > 8000 → False."""
        drafter = EmailDrafter(router=MagicMock())
        assert (
            drafter.validate_draft(
                subject="Re: x",
                body="A" * 8001,
                tone=DraftTone.FORMAL,
            )
            is False
        )

    def test_rejects_invalid_tone(self) -> None:
        """契约 3: 非法 tone → False(联动契约 3)."""
        drafter = EmailDrafter(router=MagicMock())
        assert (
            drafter.validate_draft(
                subject="Re: x",
                body="感谢您的来信, 项目进展顺利。",
                tone="APOLOGETIC",
            )
            is False
        )


# ============================================================
# Section 5: EmailDrafter.draft (mock router)
# ============================================================


class TestEmailDrafterDraft:
    """EmailDrafter.draft 单邮件草稿生成测试."""

    def test_returns_valid_result(self) -> None:
        """合法草稿返回 DraftResult."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft(subject="test", sender="x@y.com", body_excerpt="body")
        assert isinstance(result, DraftResult)
        assert result.tone == DraftTone.FORMAL
        assert result.subject == "Re: 项目进度"
        assert result.model_full_id == "deepseek/deepseek-chat"
        assert result.latency_ms == 500

    def test_response_error_propagates(self) -> None:
        """LLM 响应脏 → DrafterResponseError 透传(D3.3.3 教训)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response("not a json")
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(DrafterResponseError):
            drafter.draft(subject="x", sender="y", body_excerpt="z")
        stats = drafter.stats()
        assert stats["total"] == 1
        assert stats["response_error"] == 1
        assert stats["success"] == 0

    def test_llm_error_propagates(self) -> None:
        """router.route 抛 LLMError → 透传, stats 累加 llm_error."""
        from my_ai_employee.ai.providers import LLMTimeoutError

        mock_router = MagicMock()
        mock_router.route.side_effect = LLMTimeoutError("timeout")
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(LLMTimeoutError):
            drafter.draft(subject="x", sender="y", body_excerpt="z")
        stats = drafter.stats()
        assert stats["llm_error"] == 1

    def test_param_type_strict(self) -> None:
        """D4.5 P0 严判入口: 参数 type 错 → ValueError."""
        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(ValueError):
            drafter.draft(subject=123, sender="x", body_excerpt="y")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            drafter.draft(subject="x", sender=123, body_excerpt="y")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            drafter.draft(subject="x", sender="y", body_excerpt=123)  # type: ignore[arg-type]
        mock_router.route.assert_not_called()

    def test_body_excerpt_truncated(self) -> None:
        """正文超 MAX_BODY_CHARS 自动截断."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        long_body = "a" * 5000
        drafter.draft(subject="x", sender="y", body_excerpt=long_body)
        call_kwargs = mock_router.route.call_args
        messages = call_kwargs.kwargs["messages"]
        user_content = next(m for m in messages if m["role"] == "user")["content"]
        assert "a" * 2000 in user_content
        assert "a" * 2001 not in user_content

    def test_email_category_none_allowed(self) -> None:
        """email_category None 允许(D4.7 范围限定: drafter 是独立服务, 不强制来自 D4.6)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category=None,
        )
        assert result is not None

    def test_tone_string_valid(self) -> None:
        """tone 字符串合法 → 接受."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json(tone="FRIENDLY"))
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft(subject="x", sender="y", body_excerpt="z", tone="FRIENDLY")
        assert result.tone == DraftTone.FRIENDLY

    def test_tone_string_invalid_raises(self) -> None:
        """tone 字符串非法 → ValueError 严判入口."""
        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(ValueError, match="tone 字符串必须"):
            drafter.draft(subject="x", sender="y", body_excerpt="z", tone="apologetic")

    def test_validation_error_recorded_but_not_raised(self) -> None:
        """业务验收未通过(契约 1)记录 stats 但不抛错(由 D4.7.3 Adapter 决定)."""
        mock_router = MagicMock()
        # LLM 返回 body 长度合法但 == 0 字符(契约 1 拒收)
        bad_content = '{"subject": "Re: x", "body": "", "tone": "FORMAL"}'
        mock_router.route.return_value = _mock_router_response(bad_content)
        drafter = EmailDrafter(router=mock_router)
        # body=0 字符 _parse_draft_response 会抛 DrafterResponseError(body_invalid_len)
        with pytest.raises(DrafterResponseError):
            drafter.draft(subject="x", sender="y", body_excerpt="z")
        # 注意: 业务验收(契约 1)在 _parse_draft_response 严判时已经抛错, 不走到
        # EmailDrafter.draft 的 validate_draft 二次校验。这是正确的:
        # 严判入口下沉到 _parse_draft_response, 不重复校验(D4.6 v1.0.2-second 范本).

    def test_temperature_passed_to_router(self) -> None:
        """中温 0.7 应透传到 router(草稿任务保创意)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        drafter.draft(subject="x", sender="y", body_excerpt="z")
        call_kwargs = mock_router.route.call_args
        assert call_kwargs.kwargs["temperature"] == 0.7

    def test_task_type_is_draft(self) -> None:
        """D4.7 router 应调 TaskType.DRAFT(TaskType.DRAFT 已在 capability.py 定义)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        drafter.draft(subject="x", sender="y", body_excerpt="z")
        call_kwargs = mock_router.route.call_args
        from my_ai_employee.ai.capability import TaskType

        assert call_kwargs.kwargs["task_type"] == TaskType.DRAFT


# ============================================================
# Section 6: EmailDrafter.draft_batch
# ============================================================


class TestEmailDrafterBatch:
    """EmailDrafter.draft_batch 批量草稿测试."""

    def test_batch_returns_results(self) -> None:
        """批量返回结果."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = [
            {"subject": "s1", "sender": "x1", "body_excerpt": "b1"},
            {"subject": "s2", "sender": "x2", "body_excerpt": "b2"},
        ]
        results = drafter.draft_batch(emails)
        assert len(results) == 2
        assert all(isinstance(r, DraftResult) for r in results)

    def test_batch_handles_non_dict(self) -> None:
        """list 元素不是 dict → ValueError 入 list(D3.3.3 教训)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = [
            {"subject": "s", "sender": "x", "body_excerpt": "b"},
            "not a dict",  # type: ignore[list-item]
        ]
        results = drafter.draft_batch(emails)
        assert len(results) == 2
        assert isinstance(results[0], DraftResult)
        assert isinstance(results[1], ValueError)

    def test_batch_handles_missing_keys(self) -> None:
        """dict 缺字段 → KeyError 透传(D4.6 v1.0.2 P2-4 范本)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = [
            {"subject": "s"},  # 缺 sender + body_excerpt
            {"subject": "s", "sender": "x", "body_excerpt": "b"},
        ]
        results = drafter.draft_batch(emails)
        assert len(results) == 2
        assert isinstance(results[0], KeyError)
        assert isinstance(results[1], DraftResult)

    def test_batch_handles_partial_failures(self) -> None:
        """批量内部分失败: 1 成功 + 1 响应脏."""
        mock_router = MagicMock()
        # 第一次成功, 第二次响应脏
        mock_router.route.side_effect = [
            _mock_router_response(_valid_draft_json()),
            _mock_router_response("not a json"),
        ]
        drafter = EmailDrafter(router=mock_router)
        emails = [
            {"subject": "s1", "sender": "x1", "body_excerpt": "b1"},
            {"subject": "s2", "sender": "x2", "body_excerpt": "b2"},
        ]
        results = drafter.draft_batch(emails)
        assert len(results) == 2
        assert isinstance(results[0], DraftResult)
        assert isinstance(results[1], DrafterResponseError)


# ============================================================
# Section 7: DraftResult data class
# ============================================================


class TestDraftResult:
    """DraftResult 数据类测试."""

    def test_to_dict(self) -> None:
        result = DraftResult(
            subject="Re: 项目",
            body="感谢您的来信, 项目进展顺利。",
            tone=DraftTone.FORMAL,
            model_full_id="deepseek/deepseek-chat",
            latency_ms=500,
            raw_content='{"subject": "Re: 项目", "body": "...", "tone": "FORMAL"}',
        )
        d = result.to_dict()
        assert d["subject"] == "Re: 项目"
        assert d["tone"] == "FORMAL"
        assert d["model_full_id"] == "deepseek/deepseek-chat"
        assert d["latency_ms"] == 500

    def test_is_frozen(self) -> None:
        """frozen 不可变."""
        from dataclasses import FrozenInstanceError

        result = DraftResult(
            subject="s",
            body="b" * 20,
            tone=DraftTone.FORMAL,
            model_full_id="m",
            latency_ms=0,
            raw_content="r",
        )
        with pytest.raises(FrozenInstanceError):
            result.subject = "new"  # type: ignore[misc]

    def test_fields(self) -> None:
        """字段集合固定."""
        from dataclasses import fields

        field_names = {f.name for f in fields(DraftResult)}
        assert field_names == {
            "subject",
            "body",
            "tone",
            "model_full_id",
            "latency_ms",
            "raw_content",
        }


# ============================================================
# Section 8: 4 项契约锁定测试(D4.7.1 起始固定)
# ============================================================


class TestContract1NoConfidenceField:
    """**契约 1 锁定**: 草稿无 confidence 字段, 业务验收用明确长度/必填/tone 枚举判定."""

    def test_draft_result_no_confidence_field(self) -> None:
        """DraftResult 不含 confidence 字段."""
        from dataclasses import fields

        field_names = {f.name for f in fields(DraftResult)}
        assert "confidence" not in field_names, (
            "**契约 1 违反**: DraftResult 不应有 confidence 字段! "
            "草稿业务验收用 subject 必填 + body 长度 + tone 枚举判定, 不用 LLM 自报 confidence."
        )

    def test_validate_draft_does_not_use_confidence(self) -> None:
        """validate_draft 公共 API 不读 confidence 字段(只用 3 个明确条件)."""
        drafter = EmailDrafter(router=MagicMock())
        # 不传 confidence, 草稿验证正常工作
        assert (
            drafter.validate_draft(
                subject="Re: x",
                body="感谢您的来信, 项目进展顺利。",
                tone=DraftTone.FORMAL,
            )
            is True
        )

    def test_parse_draft_response_ignores_extra_confidence_field(self) -> None:
        """_parse_draft_response 不报错当 LLM 多输出 confidence 字段(宽松)."""
        content = (
            '{"subject": "Re: x", "body": "感谢您的来信, 项目进展顺利。", '
            '"tone": "FORMAL", "confidence": 0.9}'
        )
        # 不应抛错, 额外字段被忽略(只严判 3 个必含字段)
        subject, body, tone = _parse_draft_response(content)
        assert tone == DraftTone.FORMAL


class TestContract2RejectsMarkdownFenced:
    """**契约 2 锁定**: 拒 markdown-wrapped JSON(不剥离 fence)."""

    def test_drafter_response_error_for_markdown_fence(self) -> None:
        """_parse_draft_response 对 ```json ... ``` 抛 DrafterResponseError, reason=markdown_fenced."""
        fenced = (
            '```json\n{"subject": "Re: 项目", '
            '"body": "感谢您的来信, 项目进展顺利。", '
            '"tone": "FORMAL"}\n```'
        )
        with pytest.raises(DrafterResponseError) as exc_info:
            parse_draft_response(fenced)
        assert exc_info.value.reason == "markdown_fenced"

    def test_drafter_rejects_markdown_fence_via_draft(self) -> None:
        """EmailDrafter.draft 透传契约 2 错误."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(
            '```json\n{"subject": "Re: 项目", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}\n```'
        )
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(DrafterResponseError, match="markdown fence"):
            drafter.draft(subject="x", sender="y", body_excerpt="z")

    def test_drafter_accepts_raw_json(self) -> None:
        """裸 JSON(无 fence)正常通过."""
        result = parse_draft_response(_valid_draft_json())
        assert result[2] == DraftTone.FORMAL


class TestContract3ToneEnumLocked:
    """**契约 3 锁定**: tone 枚举固定 FORMAL / FRIENDLY / CONCISE 3 类."""

    def test_draft_tone_exactly_3_values(self) -> None:
        """DraftTone 恰好 3 个值(锁定)."""
        assert len(list(DraftTone)) == 3

    def test_draft_tone_values_locked(self) -> None:
        """3 个值固定 FORMAL / FRIENDLY / CONCISE(后续扩枚举需 B 类审批)."""
        assert {t.value for t in DraftTone} == {"FORMAL", "FRIENDLY", "CONCISE"}

    def test_draft_tone_cannot_be_extended(self) -> None:
        """DraftTone 是 final 枚举, 不能运行时扩展."""
        with pytest.raises(ValueError):
            DraftTone("APOLOGETIC")
        with pytest.raises(ValueError):
            DraftTone("INSPIRATIONAL")

    def test_parse_rejects_tone_outside_3(self) -> None:
        """_parse_draft_response 拒契约 3 之外的 tone."""
        content = (
            '{"subject": "Re: x", "body": "感谢您的来信, 项目进展顺利。", "tone": "APOLOGETIC"}'
        )
        with pytest.raises(DrafterResponseError) as exc_info:
            parse_draft_response(content)
        # 验证 reason 字段含 invalid_tone=APOLOGETIC(契约 3 机器可读标识)
        assert "invalid_tone=APOLOGETIC" in exc_info.value.reason


class TestContract4ScopeLimited:
    """**契约 4 锁定**: D4.7 范围限定 — 只生成 + emit 事件 + 推进 Lane; 不写 drafts 表 / 不创建 Mail.app 草稿 / 不接 iCloud CalDAV."""

    def test_drafter_module_no_db_imports(self) -> None:
        """Drafter 模块不应 import DB models / events / policy / sqlalchemy."""
        drafter_path = (
            Path(__file__).parent.parent.parent / "src" / "my_ai_employee" / "ai" / "drafter.py"
        )
        source = drafter_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        # **契约 4 验证**: 不应 import DB / events / policy / sqlalchemy
        forbidden_prefixes = [
            "my_ai_employee.core.models",  # SQLAlchemy models
            "my_ai_employee.core.schema",  # DB schema
            "my_ai_employee.events",  # 事件层
            "my_ai_employee.policy",  # 策略层
            "sqlalchemy",
            "sqlcipher3",
        ]
        for imp in imports:
            for forbidden in forbidden_prefixes:
                assert not imp.startswith(forbidden), (
                    f"**契约 4 违反**: D4.7 drafter 模块不应 import {forbidden!r}, "
                    f"但发现 import {imp!r}. D4.7 范围限定: 只生成 + emit 事件 + 推进 Lane; "
                    f"不写 drafts 表 / 不创建 Mail.app 草稿 / 不接 iCloud CalDAV."
                )

    def test_draft_result_has_no_drafts_field(self) -> None:
        """DraftResult 数据类不应含 drafts / mail / caldav 字段(契约 4)."""
        from dataclasses import fields

        field_names = {f.name for f in fields(DraftResult)}
        forbidden_fields = {"drafts", "draft_id", "mail_app_path", "caldav_url", "icloud_event_id"}
        for forbidden in forbidden_fields:
            assert forbidden not in field_names, (
                f"**契约 4 违反**: DraftResult 不应有 {forbidden!r} 字段! "
                f"D4.7 范围限定: 不写 drafts 表 / 不创建 Mail.app 草稿 / 不接 iCloud CalDAV."
            )

    def test_drafter_does_not_emit_events(self) -> None:
        """Drafter.draft 不返回 events / 不写 lane(契约 4: 范围限定)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft(subject="x", sender="y", body_excerpt="z")
        # Drafter.draft 只返回 DraftResult, 不返回 events / lane
        assert isinstance(result, DraftResult)
        assert not hasattr(result, "events")
        assert not hasattr(result, "lane_entry_id")


# ============================================================
# Section 9: stats 可观测性
# ============================================================


class TestDrafterStats:
    """EmailDrafter stats 可观测性测试."""

    def test_stats_initial(self) -> None:
        """初始 stats 全 0."""
        drafter = EmailDrafter(router=MagicMock())
        stats = drafter.stats()
        assert stats["total"] == 0
        assert stats["success"] == 0
        assert stats["response_error"] == 0
        assert stats["validation_error"] == 0
        assert stats["llm_error"] == 0

    def test_stats_accumulate(self) -> None:
        """stats 累加正确."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        for _ in range(3):
            drafter.draft(subject="x", sender="y", body_excerpt="z")
        stats = drafter.stats()
        assert stats["total"] == 3
        assert stats["success"] == 3
        assert stats["response_error"] == 0
        assert stats["llm_error"] == 0
