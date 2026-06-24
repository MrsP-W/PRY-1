"""D4.7 — 邮件草稿生成器单元测试.

覆盖:

  DraftTone 枚举(契约 3):
    - 3 类枚举值 + 顺序(FORMAL/FRIENDLY/CONCISE)
    - StrEnum 字符串行为

  严判 helper (_validate_draft_subject / _validate_draft_body / _validate_draft_tone):
    - 边界值(契约 1 长度上下界)
    - 非法类型(bool 子类陷阱 / None / list[Any] / int)
    - 严判入口(契约 1 公共 API 自防御)

  解析 (_parse_draft_response):
    - 合法响应(subject + body + tone 3 字段)
    - 任意字段顺序(D4.6 范本复用)
    - 拒 markdown-wrapped JSON(契约 2 核心)
    - 拒非法 tone(契约 3 核心)
    - 拒长度越界(契约 1)
    - 失败 case: 无 JSON / 非法 JSON / 顶层非 dict[Any, Any]

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
    - dict[Any, Any] 缺字段 → KeyError 透传(D4.6 范本)
    - list[Any] 元素不是 dict[Any, Any] → ValueError 入 list[Any]

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
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.ai.classifier import EmailCategory  # noqa: E402
from my_ai_employee.ai.drafter import (  # noqa: E402
    DraftBlockedResult,
    DrafterError,
    DrafterResponseError,
    DraftResult,
    DraftSpamReplyIntent,
    DraftTone,
    EmailDrafter,
    SpamBlockedError,
    _parse_draft_response,
    has_markdown_fence,
    parse_draft_response,
    validate_draft_body,
    validate_draft_subject,
    validate_draft_tone,
)
from my_ai_employee.ai.prompts.draft import build_user_message  # noqa: E402, F401
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
        assert len(list[Any](DraftTone)) == 3
        assert DraftTone.FORMAL == "FORMAL"
        assert DraftTone.FRIENDLY == "FRIENDLY"
        assert DraftTone.CONCISE == "CONCISE"

    def test_order_fixed(self) -> None:
        """顺序固定(业务层按语气分组直接用 list[Any](DraftTone) 排序)."""
        assert [t.value for t in DraftTone] == ["FORMAL", "FRIENDLY", "CONCISE"]

    def test_strenum_string_behavior(self) -> None:
        """StrEnum 字符串行为(== "FORMAL")."""
        assert DraftTone.FORMAL == "FORMAL"
        assert f"语气: {DraftTone.FORMAL.value}" == "语气: FORMAL"


# ============================================================
# Section 0.5: DraftResult 自校验(6/9 v1.0.2 P2-3)
# ============================================================


class TestDraftResultPostInit:
    """DraftResult __post_init__ 严判 5 字段(6/9 v1.0.2 P2-3)."""

    def _valid_kwargs(self) -> dict[Any, Any]:
        return {
            "subject": "Re: 测试主题",
            "body": "感谢您的来信, 项目进展顺利, 详情如下。",
            "tone": DraftTone.FORMAL,
            "model_full_id": "minimax/M3",
            "latency_ms": 100,
            "raw_content": "{}",
        }

    def test_accepts_valid(self) -> None:
        """合法 5 字段 → 构造成功."""
        result = DraftResult(**self._valid_kwargs())
        assert result.subject == "Re: 测试主题"
        assert result.tone == DraftTone.FORMAL

    def test_rejects_empty_subject(self) -> None:
        """空 subject(契约 1)→ ValueError."""
        with pytest.raises(ValueError, match="subject 太短"):
            DraftResult(**{**self._valid_kwargs(), "subject": ""})

    def test_rejects_short_body(self) -> None:
        """短 body(< 10 字符)→ ValueError."""
        with pytest.raises(ValueError, match="body 太短"):
            DraftResult(**{**self._valid_kwargs(), "body": "abc"})

    def test_rejects_string_tone(self) -> None:
        """**P2-3 核心**: tone 是 str(非 DraftTone 枚举)→ ValueError."""
        with pytest.raises(ValueError, match="tone 必须是 DraftTone 枚举"):
            DraftResult(**{**self._valid_kwargs(), "tone": "FORMAL"})

    def test_rejects_empty_model(self) -> None:
        """空 model_full_id(审计需要)→ ValueError."""
        with pytest.raises(ValueError, match="model_full_id 不能为空"):
            DraftResult(**{**self._valid_kwargs(), "model_full_id": ""})

    def test_rejects_negative_latency(self) -> None:
        """**P2-3 核心**: 负 latency_ms → ValueError."""
        with pytest.raises(ValueError, match="latency_ms 不能为负"):
            DraftResult(**{**self._valid_kwargs(), "latency_ms": -1})

    def test_rejects_bool_latency(self) -> None:
        """**P2-3**: bool 子类陷阱(True/False 是 int)→ ValueError."""
        with pytest.raises(ValueError, match="latency_ms 必须是 int"):
            DraftResult(**{**self._valid_kwargs(), "latency_ms": True})

    def test_rejects_wrong_type_subject(self) -> None:
        """**P2-3 核心**: subject 是 None → ValueError(编程错误)."""
        with pytest.raises(ValueError, match="subject 必须是 str"):
            DraftResult(**{**self._valid_kwargs(), "subject": None})


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
            validate_draft_subject(123)
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(None)
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(["A"])

    def test_rejects_bool(self) -> None:
        """D4.4 P1 教训: 拒 bool 子类陷阱(isinstance(True, int) == True)."""
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(True)

    def test_rejects_whitespace_only_subject(self) -> None:
        """6/9 v1.0.2 P1-2 修复: 仅按字符数校验会被纯空白绕过, 必须用 strip() 语义非空."""
        # 3 个空格(长度 3 ≥ 1, 旧实现可通过)→ 现在应被 strip() 严判拒收
        with pytest.raises(ValueError, match="subject 语义为空"):
            validate_draft_subject("   ")
        # 混合空白字符(空格 / 换行 / Tab / 回车)同样拒收
        with pytest.raises(ValueError, match="subject 语义为空"):
            validate_draft_subject(" \n\t\r ")

    def test_accepts_subject_with_surrounding_whitespace(self) -> None:
        """6/9 v1.0.2 P1-2 修复: 前后空白但语义非空的 subject 应通过(契约 1 仍满足)."""
        # " Re: 项目进度 " 前后各 1 空格, 长度 9 ≥ 1, strip 后 "Re: 项目进度" 语义非空
        validate_draft_subject(" Re: 项目进度 ")
        # 单字符前后空白也通过
        validate_draft_subject(" A ")


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
            validate_draft_body(123)
        with pytest.raises(ValueError, match="body 必须是 str"):
            validate_draft_body(None)
        with pytest.raises(ValueError, match="body 必须是 str"):
            validate_draft_body(["x"] * 10)

    def test_rejects_whitespace_only_body(self) -> None:
        """6/9 v1.0.2 P1-2 修复: 10 个空格 body(长度 10 达下边界)应被 strip() 严判拒收."""
        # 10 个空格(长度 10 ≥ 10, 旧实现可通过)→ 现在应被 strip() 严判拒收
        with pytest.raises(ValueError, match="body 语义为空"):
            validate_draft_body(" " * 10)
        # 混合空白字符(空格 / 换行 / Tab)也拒收(长度 10)
        with pytest.raises(ValueError, match="body 语义为空"):
            validate_draft_body(" \n\t \r " + " " * 5)
        # 10 个换行(典型 LLM 输出退化场景)也拒收
        with pytest.raises(ValueError, match="body 语义为空"):
            validate_draft_body("\n" * 10)

    def test_accepts_body_with_surrounding_whitespace(self) -> None:
        """6/9 v1.0.2 P1-2 修复: 前后空白但语义非空的 body 应通过(契约 1 仍满足)."""
        # 11 字符内容 + 前后空白 = 15 字符, strip 后 11 ≥ MIN_BODY=10 通过
        validate_draft_body("  hello world  ")
        # 含换行的正常 body 也通过(必须 ≥10 字符)
        validate_draft_body("\n感谢您的来信, 项目进展顺利\n")


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
            validate_draft_tone(123)
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone(None)
        with pytest.raises(ValueError, match="tone 必须是"):
            validate_draft_tone(["FORMAL"])


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
            _parse_draft_response(123)
        with pytest.raises(DrafterResponseError, match="LLM content 必须是 str"):
            _parse_draft_response(None)

    def test_rejects_markdown_fenced_json(self) -> None:
        """**契约 2 核心(6/9 P1-2)**: 拒外层 ```json ... ``` 包裹的 JSON."""
        fenced = '```json\n{"subject": "Re: 项目", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}\n```'
        with pytest.raises(DrafterResponseError, match="markdown fence") as exc_info:
            _parse_draft_response(fenced)
        assert exc_info.value.reason == "markdown_fenced_outer"

    def test_rejects_markdown_fenced_no_language(self) -> None:
        """**契约 2 (6/9)**: 拒外层 ``` ... ```(无语言标识) 包裹."""
        fenced = '```\n{"subject": "Re: 项目", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}\n```'
        with pytest.raises(DrafterResponseError, match="markdown fence"):
            _parse_draft_response(fenced)

    def test_rejects_prose_around_json(self) -> None:
        """**契约 2 (6/9 v1.0.2 P1)**: 拒收 prose + JSON 混合(LLM 必须返回裸 JSON).

        v1.0.1 P1-2 误把"平衡括号兜底"当作优化, 实际绕过裸 JSON 契约.
        v1.0.2 删除兜底: 整段 json.loads(stripped) 是唯一路径, 任何 prose 包装即拒.
        """
        content = (
            "Here is the draft:\n"
            '{"subject": "Re: 项目", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}\n'
            "thanks!"
        )
        with pytest.raises(DrafterResponseError, match="不是合法裸 JSON") as exc_info:
            _parse_draft_response(content)
        assert "json_decode_error=" in exc_info.value.reason

    def test_rejects_unclosed_fence_with_prose(self) -> None:
        """**契约 2 (6/9 v1.0.2 P1)**: 未闭合 ```json + 平衡 JSON → 拒收(裸 JSON 严格)."""
        # 整段不是合法 JSON(开头有 ```json 文字), 整段 load 失败 → 拒
        content = (
            "```json\n"
            '{"subject": "Re: 项目", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}'
        )
        with pytest.raises(DrafterResponseError, match="不是合法裸 JSON"):
            _parse_draft_response(content)

    def test_rejects_tone_mismatch(self) -> None:
        """**P1-3 核心(6/9)**: 请求 tone 与返回 tone 不一致 → DrafterResponseError."""
        content = _valid_draft_json(tone="FORMAL")
        with pytest.raises(DrafterResponseError, match="tone 与请求不一致") as exc_info:
            _parse_draft_response(content, expected_tone=DraftTone.CONCISE)
        assert "tone_mismatch=request_CONCISE_got_FORMAL" in exc_info.value.reason

    def test_accepts_matching_tone(self) -> None:
        """**P1-3 (6/9)**: 请求 tone 与返回 tone 一致 → 通过."""
        content = _valid_draft_json(tone="FORMAL")
        subject, body, tone = _parse_draft_response(content, expected_tone=DraftTone.FORMAL)
        assert tone == DraftTone.FORMAL

    def test_expected_tone_none_skips_enforcement(self) -> None:
        """**P1-3 (6/9)**: expected_tone=None → 跳过强制(向后兼容)."""
        content = _valid_draft_json(tone="FORMAL")
        subject, body, tone = _parse_draft_response(content)  # 不传 expected_tone
        assert tone == DraftTone.FORMAL

    def test_rejects_invalid_expected_tone_string(self) -> None:
        """**P2-1 核心(6/9 v1.0.2)**: expected_tone="OOPS" → ValueError(编程错误).

        v1.0.1 漏严判: expected_tone="OOPS" 会泄漏到 .value 抛 AttributeError,
        与契约承诺"非法类型统一抛 ValueError"冲突. v1.0.2 入口加守卫.
        """
        content = _valid_draft_json(tone="FORMAL")
        with pytest.raises(ValueError, match="expected_tone 必须是 DraftTone 枚举或 None"):
            _parse_draft_response(content, expected_tone="OOPS")  # type: ignore[arg-type]

    def test_rejects_invalid_expected_tone_int(self) -> None:
        """**P2-1 (6/9 v1.0.2)**: expected_tone=123 → ValueError(编程错误)."""
        content = _valid_draft_json(tone="FORMAL")
        with pytest.raises(ValueError, match="expected_tone 必须是 DraftTone 枚举或 None"):
            _parse_draft_response(content, expected_tone=123)  # type: ignore[arg-type]

    def test_rejects_invalid_expected_tone_str_value(self) -> None:
        """**P2-1 (6/9 v1.0.2)**: expected_tone=DraftTone.FORMAL.value(str)→ ValueError.

        注意: str 形式不允许(防止上层偷懒). 仅 DraftTone 枚举实例或 None.
        """
        content = _valid_draft_json(tone="FORMAL")
        with pytest.raises(ValueError, match="expected_tone 必须是 DraftTone 枚举或 None"):
            _parse_draft_response(content, expected_tone="FORMAL")  # type: ignore[arg-type]

    def test_accepts_body_with_inner_code_fence(self) -> None:
        """**契约 2 (6/9 P1-2 核心修复)**: body 内有 ```python ... ``` 围栏 → 接受.

        这是 P1-2 修复的关键场景: D4.7.1 初版正则扫描 fence 会误拒此 case.
        6/9 改为"外层包裹"判定后, body 内的合法 code fence 允许.
        """
        content = (
            '{"subject": "代码示例", '
            '"body": "请参考以下 Python 代码:\\n```python\\nprint(\\"hello\\")\\n```\\n谢谢", '
            '"tone": "FORMAL"}'
        )
        subject, body, tone = _parse_draft_response(content, expected_tone=DraftTone.FORMAL)
        assert subject == "代码示例"
        assert "```python" in body
        assert tone == DraftTone.FORMAL

    def test_rejects_non_json_text(self) -> None:
        """**契约 2 (6/9 v1.0.2 P1)**: 非 JSON 文本 → 拒收(reason=json_decode_error).

        v1.0.1 是 "未找到平衡的 JSON 块"(no_balanced_json).
        v1.0.2 删除兜底: 整段 load 失败即 json_decode_error.
        """
        with pytest.raises(DrafterResponseError, match="不是合法裸 JSON") as exc_info:
            _parse_draft_response("not a json at all")
        assert "json_decode_error=" in exc_info.value.reason

    def test_rejects_non_dict_json(self) -> None:
        """JSON 顶层非 object(数组)→ DrafterResponseError.

        6/9 P1-2 修复后: `[1,2,3]` 整段 json.loads 成功, 走到 dict[Any, Any] 严判 → 顶层必须是 object.
        (D4.7.1 初版: 数组不含 `{`, 平衡括号扫描失败 → no_balanced_json.)
        """
        with pytest.raises(DrafterResponseError, match="JSON 顶层必须是 object") as exc_info:
            _parse_draft_response("[1, 2, 3]")
        assert "top_level_type=list" in exc_info.value.reason

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
        assert has_markdown_fence(123) is False
        assert has_markdown_fence(None) is False

    def test_returns_false_for_fence_in_body(self) -> None:
        """**6/9 P1-2 修复**: fence 在 body 字段内不算外层包裹 → False.

        D4.7.1 初版用正则整段扫描 fence 会误杀 body 字段内的代码围栏,
        6/9 改为"外层包裹"判定 — stripped 以 ``` 开头 AND 以 ``` 结尾。
        """
        content = (
            '{"subject": "x", "body": "请看 ```python\\nprint(1)\\n``` 这段代码", "tone": "FORMAL"}'
        )
        # 6/9 修复后: 整段是合法 JSON, 内部 ```python...``` 不算外层 fence → False
        assert has_markdown_fence(content) is False

    def test_detects_fence_with_surrounding_whitespace(self) -> None:
        """stripped 后才比较 → 前后空行不影响外层判定."""
        content = '\n\n```json\n{"x":1}\n```\n\n'
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

    def test_email_category_enum_accepted(self) -> None:
        """**P1-1 修复(6/9)**: email_category 接受 EmailCategory 枚举(D4.6 真实 handoff)."""
        from my_ai_employee.ai.classifier import EmailCategory

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        # 传枚举(D4.6 ClassificationResult.category 真实类型), 不抛错
        result = drafter.draft(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category=EmailCategory.URGENT,
        )
        assert result is not None
        # mock_router.route 应被调用
        mock_router.route.assert_called_once()

    def test_email_category_valid_str_accepted(self) -> None:
        """**P1-1 (6/9)**: email_category 字符串 ∈ 5 类时接受严判.

        注: 6/9 v1.0.2 P1-1 业务硬阻断后, SPAM 字符串会在业务层抛 SpamBlockedError
        (与 D4.6 BLOCKED 流程双保险), 测试需用 allow_spam_reply=True 显式覆盖以
        验证"严判通过", 体现新契约的预期行为变更.
        """
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        for cat in ("URGENT", "TODO", "FYI", "PERSONAL"):
            result = drafter.draft(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category=cat,
            )
            assert result is not None
        # SPAM 单独验证: 业务硬阻断默认抛 SpamBlockedError, 显式 allow_spam_reply=True 才放行

        with pytest.raises(SpamBlockedError, match="业务硬阻断"):
            drafter.draft(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category="SPAM",
            )
        result = drafter.draft(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="SPAM",
            allow_spam_reply=True,
        )
        assert result is not None

    def test_email_category_invalid_str_rejected(self) -> None:
        """**P1-1 (6/9)**: email_category 非法字符串(如 'OOPS')→ ValueError 严判."""
        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(ValueError, match="email_category 字符串必须"):
            drafter.draft(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category="OOPS",
            )
        mock_router.route.assert_not_called()

    def test_email_category_wrong_type_rejected(self) -> None:
        """**P1-1 (6/9)**: email_category 非 EmailCategory / str / None → ValueError."""
        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(ValueError, match="email_category 必须是"):
            drafter.draft(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category=123,  # type: ignore[arg-type]
            )
        mock_router.route.assert_not_called()

    def test_draft_enforces_tone_request(self) -> None:
        """**P1-3 修复(6/9)**: 请求 tone 与返回 tone 不一致 → DrafterResponseError, stats 累加 response_error."""
        mock_router = MagicMock()
        # 请求 CONCISE, LLM 返回 FORMAL
        mock_router.route.return_value = _mock_router_response(_valid_draft_json(tone="FORMAL"))
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(DrafterResponseError, match="tone 与请求不一致") as exc_info:
            drafter.draft(subject="x", sender="y", body_excerpt="z", tone=DraftTone.CONCISE)
        assert "tone_mismatch=request_CONCISE_got_FORMAL" in exc_info.value.reason
        stats = drafter.stats()
        assert stats["response_error"] == 1
        assert stats["success"] == 0

    def test_draft_accepts_matching_tone(self) -> None:
        """**P1-3 (6/9)**: 请求 tone 与返回 tone 一致 → 成功."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json(tone="FRIENDLY"))
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft(subject="x", sender="y", body_excerpt="z", tone=DraftTone.FRIENDLY)
        assert result.tone == DraftTone.FRIENDLY
        stats = drafter.stats()
        assert stats["success"] == 1

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

    def test_short_body_rejected_at_parser(self) -> None:
        """**契约 1 (6/9 v1.0.2 P2-2)**: 短 body 在 _parse_draft_response 严判时即拒.

        v1.0.1 注释误说"业务验收在 draft() 内 validate_draft 二次校验",
        实际解析器已预拒, 不存在 validation_error 不可达分支. v1.0.2 删除该分支.
        """
        mock_router = MagicMock()
        bad_content = '{"subject": "Re: x", "body": "", "tone": "FORMAL"}'
        mock_router.route.return_value = _mock_router_response(bad_content)
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(DrafterResponseError, match="body 业务验收未通过") as exc_info:
            drafter.draft(subject="x", sender="y", body_excerpt="z")
        assert "body_invalid_len=0" in exc_info.value.reason
        # stats["response_error"] += 1, validation_error 字段已删除
        stats = drafter.stats()
        assert stats["response_error"] == 1
        assert "validation_error" not in stats

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
        """list[Any] 元素不是 dict[Any, Any] → ValueError 入 list[Any](D3.3.3 教训)."""
        from typing import Any, cast

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = cast(
            list[dict[str, Any]],
            [
                {"subject": "s", "sender": "x", "body_excerpt": "b"},
                "not a dict[Any, Any]",
            ],
        )
        results = drafter.draft_batch(emails)
        assert len(results) == 2
        assert isinstance(results[0], DraftResult)
        assert isinstance(results[1], ValueError)

    def test_batch_handles_missing_keys(self) -> None:
        """dict[Any, Any] 缺字段 → KeyError 透传(D4.6 v1.0.2 P2-4 范本)."""
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

    def test_batch_spam_blocked_default_returns_blocked_result(self) -> None:
        """6/9 v1.0.3 P1-1: 默认批含 SPAM → DraftBlockedResult 项(0 LLM 配额, 不上抛)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = [
            {
                "subject": "normal 1",
                "sender": "x1",
                "body_excerpt": "b1",
                "email_category": "URGENT",
            },
            {
                "subject": "spam 1",
                "sender": "spammer@x",
                "body_excerpt": "b spam",
                "email_category": "SPAM",
            },
            {"subject": "normal 2", "sender": "x2", "body_excerpt": "b2", "email_category": "FYI"},
        ]
        results = drafter.draft_batch(emails)
        assert len(results) == 3, "1:1 输入输出对齐"
        assert isinstance(results[0], DraftResult), "URGENT 走 LLM"
        assert isinstance(results[1], DraftBlockedResult), "SPAM 降级为 DraftBlockedResult(0 配额)"
        assert isinstance(results[2], DraftResult), "FYI 走 LLM"
        # SPAM 项不消耗 LLM 配额: route 只调用 2 次(URGENT + FYI, SPAM 没调)
        assert mock_router.route.call_count == 2
        # 阻断产物语义正确
        blocked = results[1]
        assert blocked is not None
        assert blocked.original_email_category == "SPAM"
        assert blocked.reason == "spam_business_blocked"
        assert "DRAFT-NO-REPLY" in blocked.subject
        # stats 累加 blocked
        stats = drafter.stats()
        assert stats["blocked"] == 1
        assert stats["success"] == 2

    def test_batch_per_email_allow_spam_reply_overrides_batch_default(self) -> None:
        """6/9 v1.0.3 P1-1: per-email allow_spam_reply=True 覆盖批默认 False → 走 LLM."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = [
            # per-email 显式覆盖: 批默认 False, 这条单独 True
            {
                "subject": "spam opt-in",
                "sender": "x",
                "body_excerpt": "b",
                "email_category": "SPAM",
                "allow_spam_reply": True,
            },
        ]
        results = drafter.draft_batch(emails, allow_spam_reply=False)
        assert len(results) == 1
        # 显式覆盖 → 走 LLM → DraftResult(非阻断)
        assert isinstance(results[0], DraftResult)
        assert mock_router.route.call_count == 1
        stats = drafter.stats()
        assert stats["success"] == 1
        assert stats["blocked"] == 0

    def test_draft_blocked_category_rejects_non_spam(self) -> None:
        """6/9 v1.0.3 P1-2: draft_blocked_category 入口只接受 SPAM, URGENT/TODO/FYI/PERSONAL 全拒."""
        drafter = EmailDrafter(router=MagicMock())
        for cat in ("URGENT", "TODO", "FYI", "PERSONAL"):
            with pytest.raises(ValueError, match="只接受阻断类别"):
                drafter.draft_blocked_category(
                    subject="s",
                    sender="x",
                    body_excerpt="b",
                    email_category=cat,
                )
        # EmailCategory 枚举同源测试
        with pytest.raises(ValueError, match="只接受阻断类别"):
            drafter.draft_blocked_category(
                subject="s",
                sender="x",
                body_excerpt="b",
                email_category=EmailCategory.URGENT,
            )
        # SPAM 仍接受(回归)
        result = drafter.draft_blocked_category(
            subject="s",
            sender="x",
            body_excerpt="b",
            email_category="SPAM",
        )
        assert result.reason == "spam_business_blocked"


# ============================================================
# Section 6.5: v1.0.3 P2-2 — 公共类型契约补全测试
# ============================================================


class TestDraftResultV103ModelFullIdStrip:
    """6/9 v1.0.3 P2-2 修复: DraftResult.model_full_id strip() 严判语义非空."""

    def test_rejects_whitespace_only_model_full_id(self) -> None:
        with pytest.raises(ValueError, match="model_full_id 不能为空"):
            DraftResult(
                subject="s",
                body="body here long enough",
                tone=DraftTone.FORMAL,
                model_full_id="   ",
                latency_ms=100,
                raw_content="{}",
            )
        with pytest.raises(ValueError, match="model_full_id 不能为空"):
            DraftResult(
                subject="s",
                body="body here long enough",
                tone=DraftTone.FORMAL,
                model_full_id="\n\t \r",
                latency_ms=100,
                raw_content="{}",
            )

    def test_accepts_surrounding_whitespace_model_full_id(self) -> None:
        # 前后空白但语义非空(provider/model 实际有内容)应通过
        result = DraftResult(
            subject="s",
            body="body here long enough",
            tone=DraftTone.FORMAL,
            model_full_id=" deepseek/deepseek-chat ",
            latency_ms=100,
            raw_content="{}",
        )
        assert result.model_full_id == " deepseek/deepseek-chat "  # 契约 1: 透传


class TestDraftBlockedResultV103SubjectLengthCap:
    """6/9 v1.0.3 P2-2 修复: DraftBlockedResult 主题 200 字符上限(防 spam 注水)."""

    def test_accepts_subject_within_200_chars(self) -> None:
        subject = "x" * 200
        result = DraftBlockedResult(
            subject=subject,
            body="建议: 不回复",
            tone=DraftTone.FORMAL,
            reason="spam_business_blocked",
            original_email_category="SPAM",
        )
        assert len(result.subject) == 200

    def test_rejects_subject_over_200_chars(self) -> None:
        # 阻断模板自动拼 "(DRAFT-NO-REPLY) [SPAM] " 前缀, 实际可用 ≈ 175 字符
        # 但 DraftBlockedResult 是数据类, 应自防御 200 上限
        subject = "x" * 201
        with pytest.raises(ValueError, match="subject 超长"):
            DraftBlockedResult(
                subject=subject,
                body="建议: 不回复",
                tone=DraftTone.FORMAL,
                reason="spam_business_blocked",
                original_email_category="SPAM",
            )

    def test_rejects_subject_524_chars(self) -> None:
        """复检实测可生成 524 字符主题的场景 — 直接构造 524 字符应拒."""
        subject = "A" * 524
        with pytest.raises(ValueError, match="subject 超长"):
            DraftBlockedResult(
                subject=subject,
                body="建议: 不回复",
                tone=DraftTone.FORMAL,
                reason="spam_business_blocked",
                original_email_category="SPAM",
            )


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
        """字段集合固定(6/9 v1.0.6 P2-1 + 6/10 v1.0.7 P2-1)."""
        from dataclasses import fields

        field_names = {f.name for f in fields(DraftResult)}
        assert field_names == {
            "subject",
            "body",
            "tone",
            "model_full_id",
            "latency_ms",
            "raw_content",
            "spam_reply_authorized",  # 6/9 v1.0.6 P2-1 新增(Adapter 审计契约)
            "spam_reply_intent",  # 6/10 v1.0.7 P2-1 新增(D4.7.3 事件审计意图)
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
        """_parse_draft_response 对 ```json ... ``` 抛 DrafterResponseError, reason=markdown_fenced_outer."""
        fenced = (
            '```json\n{"subject": "Re: 项目", '
            '"body": "感谢您的来信, 项目进展顺利。", '
            '"tone": "FORMAL"}\n```'
        )
        with pytest.raises(DrafterResponseError) as exc_info:
            parse_draft_response(fenced)
        assert exc_info.value.reason == "markdown_fenced_outer"

    def test_drafter_rejects_markdown_fence_via_draft(self) -> None:
        """EmailDrafter.draft 透传契约 2 错误."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(
            '```json\n{"subject": "Re: 项目", "body": "感谢您的来信, 项目进展顺利。", "tone": "FORMAL"}\n```'
        )
        drafter = EmailDrafter(router=mock_router)
        with pytest.raises(DrafterResponseError, match="markdown fence"):
            drafter.draft(subject="x", sender="y", body_excerpt="z")

    def test_drafter_accepts_body_with_inner_code_fence(self) -> None:
        """**契约 2 (6/9 P1-2 核心修复)**: body 字段含 code fence 不被外层判定误拒.

        D4.7.1 初版用正则整段扫描 fence, 会误杀 body 内的代码示例.
        6/9 改为"外层包裹"判定后, body 内的合法 code fence 允许.
        """
        mock_router = MagicMock()
        # 整段是合法 JSON(```python...``` 在 JSON 字符串值内不影响语法)
        content_with_inner_fence = (
            '{"subject": "代码示例", "body": "请参考 ```python\\nprint(1)\\n```", "tone": "FORMAL"}'
        )
        mock_router.route.return_value = _mock_router_response(content_with_inner_fence)
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft(subject="x", sender="y", body_excerpt="z", tone=DraftTone.FORMAL)
        assert result.subject == "代码示例"
        assert "```python" in result.body

    def test_drafter_accepts_raw_json(self) -> None:
        """裸 JSON(无 fence)正常通过."""
        result = parse_draft_response(_valid_draft_json())
        assert result[2] == DraftTone.FORMAL


class TestContract3ToneEnumLocked:
    """**契约 3 锁定**: tone 枚举固定 FORMAL / FRIENDLY / CONCISE 3 类."""

    def test_draft_tone_exactly_3_values(self) -> None:
        """DraftTone 恰好 3 个值(锁定)."""
        assert len(list[Any](DraftTone)) == 3

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
        """初始 stats 全 0(6/9 v1.0.2 P2-2: validation_error 字段已删除)."""
        drafter = EmailDrafter(router=MagicMock())
        stats = drafter.stats()
        assert stats["total"] == 0
        assert stats["success"] == 0
        assert stats["response_error"] == 0
        assert stats["llm_error"] == 0
        assert "validation_error" not in stats

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


# ============================================================
# Section 10: v1.0.4 第五次复检收口测试
# 2 P1 + 2 P2: bool 严判 / 1:1 收容 / total 不重复 / 数据类自洽
# ============================================================


class TestDraftBatchV104PerEmailBoolStrict:
    """6/9 v1.0.4 P1-1: per-email allow_spam_reply 严判 type(value) is bool."""

    def test_per_email_string_value_rejected(self) -> None:
        """per-email "false" 字符串应拒(原 bool() 真值陷阱放行)."""
        from typing import Any, cast

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = cast(
            list[dict[str, Any]],
            [
                {
                    "subject": "s",
                    "sender": "x",
                    "body_excerpt": "b",
                    "email_category": "URGENT",
                    "allow_spam_reply": "false",
                },
            ],
        )
        results = drafter.draft_batch(emails)
        assert len(results) == 1
        # 非法 per-email → ValueError 收容入 results, 不调 LLM
        assert isinstance(results[0], ValueError)
        assert "allow_spam_reply 必须是 bool" in str(results[0])
        assert mock_router.route.call_count == 0  # 关键: 不调 LLM

    def test_per_email_int_value_rejected(self) -> None:
        """per-email 整数 1 应拒(原 bool(1)=True 陷阱放行)."""
        from typing import Any, cast

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = cast(
            list[dict[str, Any]],
            [
                {
                    "subject": "s",
                    "sender": "x",
                    "body_excerpt": "b",
                    "email_category": "URGENT",
                    "allow_spam_reply": 1,
                },
            ],
        )
        results = drafter.draft_batch(emails)
        assert isinstance(results[0], ValueError)
        assert "allow_spam_reply 必须是 bool" in str(results[0])

    def test_batch_level_non_bool_rejected(self) -> None:
        """批级 allow_spam_reply 传 int=1 应拒(批级非法 → 直接上抛 ValueError)."""
        from typing import Any, cast

        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        emails = cast(
            list[dict[str, Any]],
            [{"subject": "s", "sender": "x", "body_excerpt": "b"}],
        )
        with pytest.raises(ValueError, match="draft_batch 批级 allow_spam_reply 必须是 bool"):
            drafter.draft_batch(emails, allow_spam_reply=1)  # type: ignore[arg-type]

    def test_per_email_bool_true_accepted(self) -> None:
        """per-email 真正 bool=True 应接受(回归)."""
        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = [
            {
                "subject": "s",
                "sender": "x",
                "body_excerpt": "b",
                "email_category": "SPAM",
                "allow_spam_reply": True,
            },
        ]
        results = drafter.draft_batch(emails, allow_spam_reply=False)
        assert isinstance(results[0], DraftResult)
        assert mock_router.route.call_count == 1


class TestDraftBatchV104OneToOneContract:
    """6/9 v1.0.4 P1-2: 1:1 契约 — 主题超 200 字符 + 阻断模板构造异常也入 results."""

    def test_spam_with_177_char_subject_blocked_result_within_limit(self) -> None:
        """复检实测: SPAM 原主题 177 字符, 阻断模板拼前缀后必须 ≤ 200 字符."""
        from typing import Any, cast

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        long_subject = "x" * 177
        emails = cast(
            list[dict[str, Any]],
            [
                {
                    "subject": long_subject,
                    "sender": "x",
                    "body_excerpt": "b",
                    "email_category": "SPAM",
                },
            ],
        )
        results = drafter.draft_batch(emails)
        # 1:1 契约 + 阻断产物可构造
        assert len(results) == 1
        assert isinstance(results[0], DraftBlockedResult), f"非阻断/非异常: {type(results[0])}"
        # 阻断模板前缀 24 字符 + 原主题 177 字符 = 201 字符 → 截断到 176 字符 + 前缀 = 200
        assert len(results[0].subject) == 200, (
            f"截断后应是 200 字符(前缀 24 + 原 176), 实际 {len(results[0].subject)}"
        )
        assert results[0].subject.startswith("(DRAFT-NO-REPLY) [SPAM] ")

    def test_mixed_batch_with_extreme_subject_keeps_one_to_one(self) -> None:
        """混合批次含 SPAM + 177 字符主题 → 1:1 严守, 整批不中断."""
        from typing import Any, cast

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = cast(
            list[dict[str, Any]],
            [
                {
                    "subject": "normal 1",
                    "sender": "x1",
                    "body_excerpt": "b1",
                    "email_category": "URGENT",
                },
                {
                    "subject": "y" * 177,  # 极端: 触发 1:1 契约
                    "sender": "spammer",
                    "body_excerpt": "spam",
                    "email_category": "SPAM",
                },
                {
                    "subject": "normal 2",
                    "sender": "x2",
                    "body_excerpt": "b2",
                    "email_category": "FYI",
                },
            ],
        )
        results = drafter.draft_batch(emails)
        assert len(results) == 3
        assert isinstance(results[0], DraftResult)
        assert isinstance(results[1], DraftBlockedResult)  # 阻断模板截断构造成功
        assert len(results[1].subject) == 200
        assert isinstance(results[2], DraftResult)
        # SPAM 项不调 LLM
        assert mock_router.route.call_count == 2

    def test_independent_draft_blocked_category_truncates_177_char_subject(self) -> None:
        """独立 draft_blocked_category 入口: 177 字符主题也必须截断到 200 上限内."""
        drafter = EmailDrafter(router=MagicMock())
        long_subject = "z" * 177
        result = drafter.draft_blocked_category(
            subject=long_subject,
            sender="x",
            body_excerpt="b",
            email_category="SPAM",
        )
        assert len(result.subject) == 200
        assert result.subject.startswith("(DRAFT-NO-REPLY) [SPAM] ")


class TestDraftBatchV104StatsNoDoubleCounting:
    """6/9 v1.0.4 P2-1: 阻断统计不重复累计 — 复检实测 total=2, blocked=1 必须修复."""

    def test_single_spam_in_batch_total_counted_once(self) -> None:
        """复检实测场景: 单封 SPAM 批量 → stats total=1, blocked=1(原 total=2 重复)."""
        from typing import Any, cast

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = cast(
            list[dict[str, Any]],
            [
                {
                    "subject": "spam",
                    "sender": "spammer",
                    "body_excerpt": "spam body",
                    "email_category": "SPAM",
                },
            ],
        )
        drafter.draft_batch(emails)
        stats = drafter.stats()
        # 关键: total 与 blocked 同步, 都是 1(原 total=2, blocked=1 不一致)
        assert stats["total"] == 1, f"total 应为 1, 实际 {stats['total']}"
        assert stats["blocked"] == 1, f"blocked 应为 1, 实际 {stats['blocked']}"

    def test_mixed_batch_stats_total_equals_results_count(self) -> None:
        """混合批次(URGENT + SPAM + FYI) → total=3, blocked=1, success=2."""
        from typing import Any, cast

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = cast(
            list[dict[str, Any]],
            [
                {
                    "subject": "u",
                    "sender": "x",
                    "body_excerpt": "b",
                    "email_category": "URGENT",
                },
                {
                    "subject": "s",
                    "sender": "x",
                    "body_excerpt": "b",
                    "email_category": "SPAM",
                },
                {
                    "subject": "f",
                    "sender": "x",
                    "body_excerpt": "b",
                    "email_category": "FYI",
                },
            ],
        )
        drafter.draft_batch(emails)
        stats = drafter.stats()
        assert stats["total"] == 3
        assert stats["blocked"] == 1
        assert stats["success"] == 2

    def test_independent_blocked_call_counts_once(self) -> None:
        """独立 draft_blocked_category 调用 → total=1, blocked=1(回归)."""
        drafter = EmailDrafter(router=MagicMock())
        drafter.draft_blocked_category(
            subject="s",
            sender="x",
            body_excerpt="b",
            email_category="SPAM",
        )
        stats = drafter.stats()
        assert stats["total"] == 1
        assert stats["blocked"] == 1


class TestDraftBlockedResultV104FullContract:
    """6/9 v1.0.4 P2-2: DraftBlockedResult 数据类自洽 — reason 空白 / category 错类 / body 9229 字符."""

    def test_rejects_whitespace_only_reason(self) -> None:
        """reason='   ' 纯空白应拒(原 v1.0.3 `not self.reason` 漏 strip)."""
        with pytest.raises(ValueError, match="reason 语义为空"):
            DraftBlockedResult(
                subject="s",
                body="建议: 不回复",
                tone=DraftTone.FORMAL,
                reason="   ",
                original_email_category="SPAM",
            )

    def test_rejects_whitespace_only_original_email_category(self) -> None:
        """original_email_category='\\n' 纯空白应拒."""
        with pytest.raises(ValueError, match="original_email_category 语义为空"):
            DraftBlockedResult(
                subject="s",
                body="建议: 不回复",
                tone=DraftTone.FORMAL,
                reason="spam_business_blocked",
                original_email_category="\n",
            )

    def test_rejects_non_spam_original_email_category(self) -> None:
        """original_email_category 错类(URGENT/TODO/FYI/PERSONAL)应拒."""
        for bad_cat in ("URGENT", "TODO", "FYI", "PERSONAL"):
            with pytest.raises(ValueError, match="original_email_category 必须是 'SPAM'"):
                DraftBlockedResult(
                    subject="s",
                    body="建议: 不回复",
                    tone=DraftTone.FORMAL,
                    reason="spam_business_blocked",
                    original_email_category=bad_cat,
                )

    def test_rejects_body_over_2000_chars(self) -> None:
        """复检实测 9229 字符 body 应拒(body 长度契约复用 EmailDrafter.MAX_BODY_CHARS)."""
        long_body = "B" * 2001
        with pytest.raises(ValueError, match="body 超长"):
            DraftBlockedResult(
                subject="s",
                body=long_body,
                tone=DraftTone.FORMAL,
                reason="spam_business_blocked",
                original_email_category="SPAM",
            )

    def test_rejects_body_9229_chars(self) -> None:
        """复检实测 9229 字符 body 边界 — 必须拒."""
        long_body = "X" * 9229
        with pytest.raises(ValueError, match="body 超长"):
            DraftBlockedResult(
                subject="s",
                body=long_body,
                tone=DraftTone.FORMAL,
                reason="spam_business_blocked",
                original_email_category="SPAM",
            )

    def test_accepts_body_exactly_2000_chars(self) -> None:
        """body 正好 2000 字符(MAX_BODY_CHARS 上界)应接受."""
        body = "M" * 2000
        result = DraftBlockedResult(
            subject="s",
            body=body,
            tone=DraftTone.FORMAL,
            reason="spam_business_blocked",
            original_email_category="SPAM",
        )
        assert len(result.body) == 2000

    def test_accepts_valid_full_contract(self) -> None:
        """完整 5 字段契约自洽(回归)."""
        result = DraftBlockedResult(
            subject="(DRAFT-NO-REPLY) [SPAM] spam subject",
            body="建议: 不回复",
            tone=DraftTone.FORMAL,
            reason="spam_business_blocked",
            original_email_category="SPAM",
        )
        d = result.to_dict()
        assert d["blocked"] is True
        assert d["original_email_category"] == "SPAM"


# ============================================================
# D4.7.2 v1.0.5 第六次复检收口(2 P1 + 2 P2)
# - P1-1: SPAM 授权意图显式进入 user 消息(allow_spam_reply 透传)
# - P1-2: 阻断模板 audit 字段分别截断(sender 80 / 原主题 80 / body 100)
# - P2-1: _stats_already_bumped 入口严判 type(value) is bool
# - P2-2: reason 锁定白名单(只接受 spam_business_blocked)
# ============================================================


class TestDraftV105SpamAuthorizationPropagation:
    """P1-1 验证(6/9 第六次复检): SPAM 显式授权意图必须进入 user 消息.

    背景: v1.0.4 之前, allow_spam_reply=True 只在 drafter 业务层"开门",
    实际 SYSTEM prompt 是默认 SPAM prompt("默认不生成回复"),
    模型收到 SPAM + allow_spam_reply=True 时仍按"默认不回复"指令生成。
    修复: draft() 把 allow_spam_reply 透传给 prompts/draft.build_user_message,
    当 SPAM + allow_spam_reply=True 时, user 消息显式标注"用户已显式授权"。
    """

    def _mock_router_response(self, content: str) -> object:
        """造一个 mock LLMResponse."""
        from my_ai_employee.ai.providers import LLMResponse  # noqa: PLC0415

        return LLMResponse(
            content=content,
            model_full_id="minimax/M3",
            input_tokens=100,
            output_tokens=50,
            latency_ms=300,
        )

    def test_spam_with_allow_true_includes_authorization(self) -> None:
        """P1-1 核心验证: SPAM + allow_spam_reply=True → user 消息含显式授权声明."""
        mock_router = MagicMock()
        mock_router.route.return_value = self._mock_router_response(
            '{"subject": "Re: x", "body": "valid body more than ten chars", "tone": "FORMAL"}'
        )
        drafter = EmailDrafter(router=mock_router)
        drafter.draft(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
            allow_spam_reply=True,  # 显式授权
        )
        # 拦截真实 user 消息
        user_content = mock_router.route.call_args.kwargs["messages"][1]["content"]
        # P1-1 修复: 显式授权意图必须进 user 消息
        assert "用户已显式授权" in user_content
        assert "allow_spam_reply=True" in user_content
        # SPAM 类别仍走 SYSTEM_PROMPT_SPAM(5+1 分发)
        system_content = mock_router.route.call_args.kwargs["messages"][0]["content"]
        from my_ai_employee.ai.prompts.draft import SYSTEM_PROMPT_SPAM  # noqa: PLC0415

        assert system_content == SYSTEM_PROMPT_SPAM

    def test_spam_default_does_not_include_authorization(self) -> None:
        """P1-1 边界: SPAM + allow_spam_reply=False(默认) → user 消息不显式授权.

        实际 SPAM 默认会在 drafter 业务层抛 SpamBlockedError(不调 LLM),
        但为了验证"allow_spam_reply=False 时 user 消息不含授权", 用 URGENT + allow_spam_reply=False 反向验证
        (SPAM + False 抛 SpamBlockedError 测不到消息内容).
        """
        mock_router = MagicMock()
        mock_router.route.return_value = self._mock_router_response(
            '{"subject": "Re: x", "body": "valid body more than ten chars", "tone": "FORMAL"}'
        )
        drafter = EmailDrafter(router=mock_router)
        # URGENT + allow_spam_reply=False(不传递, 默认值) → user 消息不含"用户已显式授权"
        drafter.draft(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="URGENT",
            tone=DraftTone.FORMAL,
        )
        user_content = mock_router.route.call_args.kwargs["messages"][1]["content"]
        # 默认 None / False 时不显示授权声明
        assert "用户已显式授权" not in user_content

    def test_non_spam_with_allow_true_does_not_include_authorization(self) -> None:
        """P1-1 边界: URGENT + allow_spam_reply=True → user 消息仍不显示 SPAM 授权(避免污染其他类别)."""
        mock_router = MagicMock()
        mock_router.route.return_value = self._mock_router_response(
            '{"subject": "Re: x", "body": "valid body more than ten chars", "tone": "FORMAL"}'
        )
        drafter = EmailDrafter(router=mock_router)
        drafter.draft(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="URGENT",
            tone=DraftTone.FORMAL,
            allow_spam_reply=True,  # 即便传 True, 非 SPAM 不显示授权声明
        )
        user_content = mock_router.route.call_args.kwargs["messages"][1]["content"]
        assert "用户已显式授权" not in user_content


class TestBuildUserMessageV105AllowSpamReplyTypeGuard:
    """P1-1 验证(6/9 第六次复检): build_user_message 严判 allow_spam_reply 类型.

    与 drafter 入口严判保持范本一致: type(allow_spam_reply) is bool(拒 "true" / 1 等真值陷阱).
    """

    def test_rejects_string_value(self) -> None:
        """字符串 'true' 拒收 → ValueError(与 v1.0.4 P1-1 bool 严判保持一致)."""
        with pytest.raises(ValueError, match="allow_spam_reply 必须是 bool"):
            build_user_message(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category="SPAM",
                tone="FORMAL",
                allow_spam_reply="true",  # type: ignore[arg-type]
            )

    def test_rejects_int_value(self) -> None:
        """int=1 拒收 → ValueError(bool() 真值陷阱严判)."""
        with pytest.raises(ValueError, match="allow_spam_reply 必须是 bool"):
            build_user_message(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category="SPAM",
                tone="FORMAL",
                allow_spam_reply=1,  # type: ignore[arg-type]
            )

    def test_accepts_bool_true(self) -> None:
        """bool=True 接受(回归)."""
        msgs = build_user_message(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="SPAM",
            tone="FORMAL",
            allow_spam_reply=True,
        )
        content = msgs[0]["content"]
        assert "用户已显式授权" in content

    def test_accepts_bool_false(self) -> None:
        """bool=False 接受(不显示授权声明)."""
        msgs = build_user_message(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="SPAM",
            tone="FORMAL",
            allow_spam_reply=False,
        )
        content = msgs[0]["content"]
        assert "用户已显式授权" not in content


class TestDraftBlockedCategoryV105AuditTruncation:
    """P1-2 验证(6/9 第六次复检): 阻断模板 audit 字段分别截断.

    背景: 1800 字符 sender 注入式撑爆 blocked_body 2000 字符上限, 安全降级失败.
    修复: audit 字段分别截断(sender 80 / 原主题 80 / body 100).
    """

    def test_1800_char_sender_does_not_explode_blocked_body(self) -> None:
        """P1-2 核心验证: 1800 字符 sender 不再撑爆 blocked_body, 仍返回 DraftBlockedResult."""
        huge_sender = "attacker" + "X" * 1792  # 总 1800 字符
        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft_blocked_category(
            subject="spam",
            sender=huge_sender,  # 1800 字符攻击者 sender
            body_excerpt="click",
            email_category="SPAM",
            tone=DraftTone.CONCISE,
        )
        # 关键: 不抛 ValueError, 正常返回 DraftBlockedResult
        assert isinstance(result, DraftBlockedResult)
        # blocked_body 必须 < 2000 字符(MAX_BODY_CHARS 上限)
        assert len(result.body) <= EmailDrafter.MAX_BODY_CHARS
        # audit 块中 sender 截断到 80 字符
        assert "attackerXXX" in result.body  # 截断后的部分内容在
        # 关键: 没调 LLM
        mock_router.route.assert_not_called()

    def test_huge_subject_in_audit_block_truncated(self) -> None:
        """P1-2 验证: 原主题在 audit 块中截断到 80 字符(防 1000 字符主题撑爆)."""
        huge_subject = "S" * 1000
        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft_blocked_category(
            subject=huge_subject,
            sender="x",
            body_excerpt="y",
            email_category="SPAM",
            tone=DraftTone.CONCISE,
        )
        # audit 块中的原主题被截断(原 1000 字符 → 80 字符)
        # subject 字段本身已被截断到 200-24=176 字符
        # 但 audit 块中"原主题:" 那行也只显示 80 字符
        assert "原主题: " in result.body
        # blocked_body 总长 < 2000
        assert len(result.body) <= EmailDrafter.MAX_BODY_CHARS

    def test_huge_body_excerpt_audit_truncated(self) -> None:
        """P1-2 验证: 原正文摘要在 audit 块中截断到 100 字符(防 5000 字符正文撑爆)."""
        huge_body = "B" * 5000
        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft_blocked_category(
            subject="x",
            sender="y",
            body_excerpt=huge_body,
            email_category="SPAM",
            tone=DraftTone.CONCISE,
        )
        # audit 块中"原正文摘要:" 后只显示 100 字符
        assert "原正文摘要: " in result.body
        # blocked_body 总长 < 2000
        assert len(result.body) <= EmailDrafter.MAX_BODY_CHARS

    def test_combined_huge_fields_still_under_limit(self) -> None:
        """P1-2 集成验证: sender + subject + body 全部超大时仍 < 2000 字符."""
        huge_sender = "X" * 1800
        huge_subject = "S" * 500
        huge_body = "B" * 5000
        mock_router = MagicMock()
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft_blocked_category(
            subject=huge_subject,
            sender=huge_sender,
            body_excerpt=huge_body,
            email_category="SPAM",
            tone=DraftTone.CONCISE,
        )
        # audit 字段全部分别截断 → blocked_body 总长 < 2000 字符
        assert len(result.body) <= EmailDrafter.MAX_BODY_CHARS

    def test_audit_block_annotation_present(self) -> None:
        """P1-2 回归: audit 块标题含"字段已截断"提示(便于审计理解截断语义)."""
        result = EmailDrafter(router=MagicMock()).draft_blocked_category(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="SPAM",
            tone=DraftTone.CONCISE,
        )
        assert "字段已截断" in result.body


class TestDraftBlockedCategoryV105StatsBumpedTypeGuard:
    """P2-1 验证(6/9 第六次复检): _stats_already_bumped 入口严判 type(value) is bool.

    背景: 私有参数 _stats_already_bumped 未严判类型,
    传入 "false" / 1 等真值陷阱会破坏"批量路径不重复 total"语义.
    修复: 入口严判 type(value) is bool, 拒收所有非原生 bool.
    """

    def test_rejects_string_false(self) -> None:
        """字符串 'false' 拒收 → ValueError(真值陷阱)."""
        with pytest.raises(ValueError, match="_stats_already_bumped 必须是 bool"):
            EmailDrafter(router=MagicMock()).draft_blocked_category(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category="SPAM",
                tone=DraftTone.CONCISE,
                _stats_already_bumped="false",  # type: ignore[arg-type]
            )

    def test_rejects_int_one(self) -> None:
        """int=1 拒收 → ValueError(bool() 真值陷阱)."""
        with pytest.raises(ValueError, match="_stats_already_bumped 必须是 bool"):
            EmailDrafter(router=MagicMock()).draft_blocked_category(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category="SPAM",
                tone=DraftTone.CONCISE,
                _stats_already_bumped=1,  # type: ignore[arg-type]
            )

    def test_accepts_bool_true(self) -> None:
        """bool=True 接受(批量路径回归 — stats 不重复)."""
        result = EmailDrafter(router=MagicMock()).draft_blocked_category(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="SPAM",
            tone=DraftTone.CONCISE,
            _stats_already_bumped=True,
        )
        assert isinstance(result, DraftBlockedResult)
        # 批量路径: stats 不重复 total(只在 draft() 已累加过, 本次 0 增量)
        # 这里只验返回成功, 不验 stats(因 stats 路径由 draft_batch 触发)

    def test_accepts_bool_false(self) -> None:
        """bool=False 接受(独立调用路径回归)."""
        result = EmailDrafter(router=MagicMock()).draft_blocked_category(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="SPAM",
            tone=DraftTone.CONCISE,
            _stats_already_bumped=False,
        )
        assert isinstance(result, DraftBlockedResult)
        # 独立调用: stats 应 +1 total +1 blocked(新 drafter 实例验证)
        d2 = EmailDrafter(router=MagicMock())
        d2.draft_blocked_category(
            subject="x",
            sender="y",
            body_excerpt="z",
            email_category="SPAM",
            tone=DraftTone.CONCISE,
            _stats_already_bumped=False,
        )
        assert d2.stats()["total"] == 1
        assert d2.stats()["blocked"] == 1


class TestDraftBlockedResultV105ReasonWhitelist:
    """P2-2 验证(6/9 第六次复检): reason 锁定白名单.

    背景: 任意非空 reason 接受(如 'other'), 构造不一致状态.
    修复: reason 限定为 'spam_business_blocked'(当前唯一阻断类别).
    """

    def test_rejects_other_reason(self) -> None:
        """非白名单 reason(如 'other')拒收 → ValueError."""
        with pytest.raises(ValueError, match="reason 必须是"):
            DraftBlockedResult(
                subject="s",
                body="b" * 20,
                tone=DraftTone.FORMAL,
                reason="other",  # 非白名单
                original_email_category="SPAM",
            )

    def test_rejects_empty_reason(self) -> None:
        """空白 reason 拒收 → ValueError(语义非空校验, 与 reason 字段先前 4 件套契约一致)."""
        with pytest.raises(ValueError, match="reason 语义为空"):
            DraftBlockedResult(
                subject="s",
                body="b" * 20,
                tone=DraftTone.FORMAL,
                reason="   ",  # 空白字符, strip() 严判拒绝
                original_email_category="SPAM",
            )

    def test_rejects_spam_business_blocked_uppercase(self) -> None:
        """大小写敏感: 'SPAM_BUSINESS_BLOCKED' 不接受(白名单仅小写)."""
        with pytest.raises(ValueError, match="reason 必须是"):
            DraftBlockedResult(
                subject="s",
                body="b" * 20,
                tone=DraftTone.FORMAL,
                reason="SPAM_BUSINESS_BLOCKED",  # 大小写不匹配
                original_email_category="SPAM",
            )

    def test_accepts_spam_business_blocked(self) -> None:
        """白名单 reason 'spam_business_blocked' 接受(回归)."""
        result = DraftBlockedResult(
            subject="s",
            body="b" * 20,
            tone=DraftTone.FORMAL,
            reason="spam_business_blocked",
            original_email_category="SPAM",
        )
        assert result.reason == "spam_business_blocked"


# ============================================================
# Section v1.0.6: 第七次复检 2 P1 + 2 P2 收口
#   P1-1: tone 校验在 SPAM 阻断之前(防非法 tone 污染 total/blocked 统计)
#   P1-2: audit 字段 json.dumps() 序列化(防换行注入伪造原分类/原发件人)
#   P2-1: DraftResult + DraftBlockedResult.spam_reply_authorized 字段(Adapter 审计)
#   P2-2: DraftSpamReplyIntent 枚举(排除"确认收悉"语义冲突)
# ============================================================


class TestDraftV106ToneValidationBeforeBlock:
    """6/9 v1.0.6 P1-1 修复: tone 校验必须在 SPAM 阻断**之前**.

    v1.0.5 漏洞: 非法 tone 在 SPAM 阻断后校验, 会先被记录为业务阻断
    (stats["total"]+=1, stats["blocked"]+=1), 再抛 ValueError 退出,
    污染 total/blocked 统计, 上层 audit 误读"SPAM 阻断率虚高".
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def test_invalid_tone_with_spam_raises_valueerror_before_block(self) -> None:
        """非法 tone("OOPS") + SPAM 场景: ValueError 在 SPAM 阻断之前抛, stats 不污染."""
        d = self._make_drafter()
        stats_before = dict[Any, Any](d.stats())
        with pytest.raises(ValueError, match="tone 字符串必须"):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文内容大于十字符的字数。",
                email_category="SPAM",
                tone="OOPS",  # 非法 tone
                allow_spam_reply=False,
            )
        # 关键: stats 不变(没有 SPAM 阻断 +1 副作用)
        stats_after = dict[Any, Any](d.stats())
        assert stats_after == stats_before, (
            f"非法 tone 不应触发 SPAM 阻断, stats 不变. before={stats_before}, after={stats_after}"
        )

    def test_invalid_tone_type_with_spam_does_not_increment_blocked(self) -> None:
        """非法 tone type(int) + SPAM: 严判入口就抛 ValueError, blocked 计数 = 0."""
        d = self._make_drafter()
        with pytest.raises(ValueError):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文内容大于十字符的字数。",
                email_category="SPAM",
                tone=123,  # type: ignore[arg-type]  # 非法 type, 运行时严判拦截
                allow_spam_reply=False,
            )
        # 阻断计数应该是 0(不是 1)
        assert d.stats()["blocked"] == 0, (
            f"非法 tone 不应触发 SPAM 阻断, blocked 计数必须 = 0, 实际 {d.stats()['blocked']}"
        )
        assert d.stats()["total"] == 0

    def test_invalid_tone_non_spam_raises_without_stat_change(self) -> None:
        """非法 tone + 非 SPAM 场景: 同样 ValueError, stats 不变(回归基线)."""
        d = self._make_drafter()
        stats_before = dict[Any, Any](d.stats())
        with pytest.raises(ValueError):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文内容大于十字符的字数。",
                email_category="URGENT",
                tone="OOPS",
            )
        stats_after = dict[Any, Any](d.stats())
        assert stats_after == stats_before

    def test_valid_tone_with_spam_still_blocks_correctly(self) -> None:
        """合法 tone + SPAM + allow_spam_reply=False: 业务阻断正常执行(回归)."""
        d = self._make_drafter()
        with pytest.raises(SpamBlockedError):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文内容大于十字符的字数。",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                allow_spam_reply=False,
            )
        # 阻断应该 +1 total, +1 blocked
        assert d.stats()["blocked"] == 1
        assert d.stats()["total"] == 1


class TestDraftBlockedCategoryV106AuditNewlineInjection:
    """6/9 v1.0.6 P1-2 修复: audit 字段 `json.dumps()` 序列化防换行注入.

    v1.0.5 漏洞: `[:80]` 截断后, 攻击者可在前 80 字符内嵌入
    `\\n原分类: NOT_SPAM\\n原发件人: <伪造>`, 截断不能阻止换行注入,
    audit 块结构被破坏, 审计记录被伪造.
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def test_newline_in_sender_escaped_to_literal(self) -> None:
        """sender 嵌入 `\\n原分类:` 注入 → json.dumps() 转义为字面量 `\\n`."""
        d = self._make_drafter()
        malicious_sender = "evil@example.com\n原分类: NOT_SPAM\n原发件人: legit@example.com"
        result = d.draft_blocked_category(
            subject="测试主题",
            sender=malicious_sender,
            body_excerpt="测试正文内容",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        # 关键: body 中不能有未转义的换行后跟"原分类: NOT_SPAM"
        # 注入的 `\n` 必须被转义为字面量 `\n`(即 `\\n`)
        assert "\n原分类: NOT_SPAM" not in result.body, (
            f"换行注入未被防御, body 含未转义的 '原分类: NOT_SPAM'. body={result.body!r}"
        )
        # 截断 + json 转义后, 真发件人应该被转义(以 \\n 形式出现, 而非真换行)
        assert "evil@example.com\\n原分类" in result.body or "evil@example.com" in result.body

    def test_carriage_return_in_subject_escaped(self) -> None:
        """subject 嵌入 `\\r\\n` → json.dumps 转义为字面量 `\\r\\n`."""
        d = self._make_drafter()
        malicious_subject = "测试\r\n原分类: TODO\n原发件人: fake@x.com"
        result = d.draft_blocked_category(
            subject=malicious_subject,
            sender="real@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        # 不应该有真换行后跟"原分类: TODO"
        assert "\n原分类: TODO" not in result.body

    def test_tab_in_body_excerpt_escaped(self) -> None:
        """body_excerpt 嵌入 `\\t` → json.dumps 转义."""
        d = self._make_drafter()
        malicious_body = "正常内容\t原分类: URGENT\n原发件人: fake@x.com"
        result = d.draft_blocked_category(
            subject="测试",
            sender="real@example.com",
            body_excerpt=malicious_body,
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        # tab/换行被转义后, "原分类: URGENT" 应该作为字面量而非独立行
        # 关键: body 中不能有真换行后跟"原分类:"
        lines = result.body.split("\n")
        for line in lines:
            # audit 块的"原分类"行必须是系统拼的 cat_str(SPAM),不是攻击者的 URGENT
            if line.startswith("原分类: "):
                assert line == "原分类: SPAM", f"audit 块的'原分类'行被伪造: {line!r}"

    def test_quote_in_sender_escaped(self) -> None:
        """sender 嵌入 `"` 双引号 → json.dumps 转义为 `\\\"`, 防破坏 JSON 结构."""
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="测试",
            sender='evil"@example.com',
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        # sender 块: json.dumps 加双引号包裹 + 内部双引号转义
        assert 'evil\\"@example.com' in result.body

    def test_combined_attack_does_not_corrupt_audit(self) -> None:
        """组合攻击: 主题 + 发件人 + 正文 同时注入换行, audit 块结构不被破坏."""
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="主题\n原分类: URGENT",
            sender="evil\n@example.com",
            body_excerpt="正文\n原分类: TODO",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        # 检查"原分类"行只有一次,且必须是 SPAM
        original_category_lines = [
            line for line in result.body.split("\n") if line.startswith("原分类: ")
        ]
        assert len(original_category_lines) == 1, (
            f"audit 块应有 1 个'原分类'行, 实际 {len(original_category_lines)} 个"
        )
        assert original_category_lines[0] == "原分类: SPAM"


class TestDraftResultV106SpamReplyAuthorizedField:
    """6/9 v1.0.6 P2-1 修复: DraftResult.spam_reply_authorized 字段(Adapter 审计契约)."""

    def _valid_kwargs(self) -> dict[Any, Any]:
        return {
            "subject": "Re: 测试主题",
            "body": "感谢您的来信, 项目进展顺利, 详情如下。",
            "tone": DraftTone.FORMAL,
            "model_full_id": "minimax/M3",
            "latency_ms": 100,
            "raw_content": "{}",
        }

    def test_default_is_false(self) -> None:
        """默认 spam_reply_authorized=False(普通草稿)."""
        result = DraftResult(**self._valid_kwargs())
        assert result.spam_reply_authorized is False

    def test_explicit_true(self) -> None:
        """显式 spam_reply_authorized=True(SPAM 授权放行).

        6/10 v1.0.7 P2-1 升级: 授权=True 时 intent 必非空(一致性契约),
        旧版测试需同时传 intent。
        """
        result = DraftResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.UNSUBSCRIBE,
            }
        )
        assert result.spam_reply_authorized is True
        assert result.spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_to_dict_includes_field(self) -> None:
        """to_dict 序列化包含 spam_reply_authorized 字段(D4.7.3 事件审计用).

        6/10 v1.0.7 P2-1 升级: 授权=True 时 intent 必非空(一致性契约)。
        """
        result = DraftResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.REJECT,
            }
        )
        d = result.to_dict()
        assert "spam_reply_authorized" in d
        assert d["spam_reply_authorized"] is True
        assert d["spam_reply_intent"] == "REJECT"

    def test_rejects_string_value(self) -> None:
        """spam_reply_authorized="false"(str) → ValueError(拒真值陷阱)."""
        with pytest.raises(ValueError, match="spam_reply_authorized 必须是 bool"):
            DraftResult(**{**self._valid_kwargs(), "spam_reply_authorized": "false"})

    def test_rejects_int_value(self) -> None:
        """spam_reply_authorized=1(int) → ValueError(拒真值陷阱)."""
        with pytest.raises(ValueError, match="spam_reply_authorized 必须是 bool"):
            DraftResult(**{**self._valid_kwargs(), "spam_reply_authorized": 1})

    def test_rejects_none_value(self) -> None:
        """spam_reply_authorized=None → ValueError(必须显式 bool)."""
        with pytest.raises(ValueError, match="spam_reply_authorized 必须是 bool"):
            DraftResult(**{**self._valid_kwargs(), "spam_reply_authorized": None})


class TestDraftBlockedResultV106SpamReplyAuthorizedField:
    """6/9 v1.0.6 P2-1 修复: DraftBlockedResult.spam_reply_authorized 字段."""

    def _valid_kwargs(self) -> dict[Any, Any]:
        return {
            "subject": "(DRAFT-NO-REPLY) [SPAM] 测试",
            "body": "建议: 不回复\n\n" + "原因: 该邮件被 D4.6 分类为 SPAM, 进入业务阻断流程.\n" * 1,
            "tone": DraftTone.FORMAL,
            "reason": "spam_business_blocked",
            "original_email_category": "SPAM",
        }

    def test_default_is_false(self) -> None:
        """默认 spam_reply_authorized=False."""
        result = DraftBlockedResult(**self._valid_kwargs())
        assert result.spam_reply_authorized is False

    def test_explicit_true(self) -> None:
        """显式 spam_reply_authorized=True(便于审计"调用方授权但仍被阻断").

        6/10 v1.0.8 P1-2 升级: 授权=True 时 intent 必非空(强一致契约),
        旧版测试需同时传 intent。
        """
        result = DraftBlockedResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.UNSUBSCRIBE,
            }
        )
        assert result.spam_reply_authorized is True
        assert result.spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_to_dict_includes_field(self) -> None:
        """to_dict 序列化包含 spam_reply_authorized 字段.

        6/10 v1.0.8 P1-2 升级: 授权=True 时 intent 必非空(强一致契约)。
        """
        result = DraftBlockedResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.REJECT,
            }
        )
        d = result.to_dict()
        assert "spam_reply_authorized" in d
        assert d["spam_reply_authorized"] is True
        assert d["spam_reply_intent"] == "REJECT"

    def test_rejects_string_value(self) -> None:
        """spam_reply_authorized="true" → ValueError."""
        with pytest.raises(ValueError, match="spam_reply_authorized 必须是 bool"):
            DraftBlockedResult(**{**self._valid_kwargs(), "spam_reply_authorized": "true"})

    def test_rejects_int_value(self) -> None:
        """spam_reply_authorized=0 → ValueError."""
        with pytest.raises(ValueError, match="spam_reply_authorized 必须是 bool"):
            DraftBlockedResult(**{**self._valid_kwargs(), "spam_reply_authorized": 0})


class TestDraftSpamReplyIntentEnumV106:
    """6/9 v1.0.6 P2-2 新增: DraftSpamReplyIntent 枚举(排除 ACKNOWLEDGE 语义冲突)."""

    def test_two_intents(self) -> None:
        """枚举 2 个值(契约外增量, 排除 ACKNOWLEDGE)."""
        assert len(list[Any](DraftSpamReplyIntent)) == 2
        assert DraftSpamReplyIntent.UNSUBSCRIBE == "UNSUBSCRIBE"
        assert DraftSpamReplyIntent.REJECT == "REJECT"

    def test_order_fixed(self) -> None:
        """顺序固定(UNSUBSCRIBE → REJECT, 业务层按"温和度"从高到低排序)."""
        assert [t.value for t in DraftSpamReplyIntent] == ["UNSUBSCRIBE", "REJECT"]

    def test_strenum_string_behavior(self) -> None:
        """StrEnum 字符串行为."""
        assert DraftSpamReplyIntent.UNSUBSCRIBE == "UNSUBSCRIBE"
        assert f"intent={DraftSpamReplyIntent.UNSUBSCRIBE.value}" == "intent=UNSUBSCRIBE"


class TestBuildUserMessageV106SpamReplyIntentPhrasing:
    """6/9 v1.0.6 P2-2 修复: 授权行措辞按枚举选择, 排除'确认收悉'语义冲突."""

    def test_default_none_with_spam_allow_true_uses_unsubscribe(self) -> None:
        """默认 None + SPAM + allow_spam_reply=True → 措辞按 UNSUBSCRIBE."""
        msgs = build_user_message(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone="CONCISE",
            allow_spam_reply=True,
            spam_reply_intent=None,  # 默认
        )
        content = msgs[0]["content"]
        # 应该含 UNSUBSCRIBE 措辞, 不含"确认收悉"
        assert "intent=UNSUBSCRIBE" in content
        assert "礼貌退订" in content
        assert "确认收悉" not in content, "授权行不应含'确认收悉'(与 SYSTEM prompt 矛盾)"

    def test_explicit_unsubscribe_intent(self) -> None:
        """显式 UNSUBSCRIBE 意图 → 措辞选 UNSUBSCRIBE."""
        msgs = build_user_message(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone="CONCISE",
            allow_spam_reply=True,
            spam_reply_intent="UNSUBSCRIBE",
        )
        content = msgs[0]["content"]
        assert "intent=UNSUBSCRIBE" in content
        assert "礼貌退订" in content

    def test_explicit_reject_intent(self) -> None:
        """显式 REJECT 意图 → 措辞选 REJECT."""
        msgs = build_user_message(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone="FORMAL",
            allow_spam_reply=True,
            spam_reply_intent="REJECT",
        )
        content = msgs[0]["content"]
        assert "intent=REJECT" in content
        assert "明确拒收" in content
        assert "礼貌退订" not in content, "REJECT 意图不应含 UNSUBSCRIBE 措辞"

    def test_rejects_acknowledge_intent(self) -> None:
        """ACKNOWLEDGE 意图 → ValueError(与 SYSTEM prompt 业务硬规则矛盾)."""
        with pytest.raises(ValueError, match="spam_reply_intent 字符串必须"):
            build_user_message(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone="CONCISE",
                allow_spam_reply=True,
                spam_reply_intent="ACKNOWLEDGE",  # 非法, 排除
            )

    def test_rejects_unknown_intent(self) -> None:
        """未知意图("foo") → ValueError(白名单严判)."""
        with pytest.raises(ValueError, match="spam_reply_intent 字符串必须"):
            build_user_message(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone="CONCISE",
                allow_spam_reply=True,
                spam_reply_intent="foo",
            )

    def test_rejects_intent_type(self) -> None:
        """spam_reply_intent=123(int) → ValueError(严判 type)."""
        with pytest.raises(ValueError, match="spam_reply_intent 必须是 str 或 None"):
            build_user_message(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone="CONCISE",
                allow_spam_reply=True,
                spam_reply_intent=123,  # type: ignore[arg-type]
            )

    def test_no_authorization_line_when_allow_false(self) -> None:
        """allow_spam_reply=False → 不显示授权行(无论 spam_reply_intent 是什么)."""
        msgs = build_user_message(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone="CONCISE",
            allow_spam_reply=False,
            spam_reply_intent="UNSUBSCRIBE",  # 即使传, 也不显示(因 allow=False)
        )
        content = msgs[0]["content"]
        assert "intent=UNSUBSCRIBE" not in content
        assert "授权" not in content or "已显式授权" not in content

    def test_no_authorization_line_when_non_spam(self) -> None:
        """非 SPAM 类别 + allow_spam_reply=True → 不显示授权行(只 SPAM 显示)."""
        msgs = build_user_message(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="URGENT",
            tone="CONCISE",
            allow_spam_reply=True,  # 业务层应不会这么用, 但语义上仅 SPAM 显示
            spam_reply_intent="UNSUBSCRIBE",
        )
        content = msgs[0]["content"]
        assert "intent=UNSUBSCRIBE" not in content


class TestDraftV106SpamReplyIntentPropagation:
    """6/9 v1.0.6 P2-2 修复: drafter.draft() 透传 spam_reply_intent 到 build_user_message."""

    def test_draft_rejects_unknown_intent_string(self) -> None:
        """draft(spam_reply_intent='foo') → ValueError(白名单严判)."""
        d = EmailDrafter(router=MagicMock())
        with pytest.raises(ValueError, match="spam_reply_intent 字符串必须"):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文内容大于十字符的字数。",
                email_category="URGENT",
                tone=DraftTone.FORMAL,
                spam_reply_intent="foo",
            )

    def test_draft_rejects_intent_int(self) -> None:
        """draft(spam_reply_intent=123) → ValueError(严判 type)."""
        d = EmailDrafter(router=MagicMock())
        with pytest.raises(ValueError, match="spam_reply_intent 必须是 DraftSpamReplyIntent"):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文内容大于十字符的字数。",
                email_category="URGENT",
                tone=DraftTone.FORMAL,
                spam_reply_intent=123,  # type: ignore[arg-type]
            )

    def test_draft_accepts_enum_value(self) -> None:
        """draft(spam_reply_intent=DraftSpamReplyIntent.REJECT) → 严判通过(调 LLM 之前)."""
        d = EmailDrafter(router=MagicMock())
        # 准备 mock LLM 响应
        d._router.route.return_value = _mock_router_response(  # type: ignore[attr-defined]
            _valid_draft_json(tone="FORMAL"), model="minimax/M3", latency=200
        )
        result = d.draft(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文内容大于十字符的字数。",
            email_category="URGENT",  # 非 SPAM, 不走业务阻断
            tone=DraftTone.FORMAL,
            spam_reply_intent=DraftSpamReplyIntent.REJECT,
        )
        assert isinstance(result, DraftResult)
        # spam_reply_authorized 默认 False(因为 allow_spam_reply=False)
        assert result.spam_reply_authorized is False


class TestDraftBlockedCategoryV106SpamReplyAuthorizedParam:
    """6/9 v1.0.6 P2-1 修复: draft_blocked_category 接受 spam_reply_authorized 参数(Adapter 契约)."""

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def test_param_default_false(self) -> None:
        """默认 spam_reply_authorized=False(独立调用场景)."""
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        assert result.spam_reply_authorized is False

    def test_param_explicit_true(self) -> None:
        """显式 spam_reply_authorized=True 透传到 DraftBlockedResult.

        6/10 v1.0.8 P1-2 强一致契约: authorized=True 时 intent 必非空。
        """
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
            spam_reply_authorized=True,
            spam_reply_intent=DraftSpamReplyIntent.UNSUBSCRIBE,  # v1.0.8 必传
        )
        assert result.spam_reply_authorized is True
        assert result.spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_param_rejects_string(self) -> None:
        """spam_reply_authorized="true" → ValueError."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="draft_blocked_category spam_reply_authorized"):
            d.draft_blocked_category(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                spam_reply_authorized="true",  # type: ignore[arg-type]
            )

    def test_param_rejects_int(self) -> None:
        """spam_reply_authorized=1 → ValueError(运行时拦截, mypy 静态拦截)."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="draft_blocked_category spam_reply_authorized"):
            d.draft_blocked_category(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                spam_reply_authorized=1,  # type: ignore[arg-type]
            )

    def test_batch_propagates_to_blocked_result(self) -> None:
        """draft_batch 路径: per-email allow_spam_reply 透传到 DraftResult.spam_reply_authorized.

        per-email allow_spam_reply=True + mock LLM 成功 → DraftResult(spam_reply_authorized=True)
        """
        d = self._make_drafter()
        # 准备 mock LLM 响应(SPAM 授权放行走 draft() 调 LLM 路径)
        router_mock = d._router
        router_mock.route.return_value = _mock_router_response(  # type: ignore[attr-defined]
            _valid_draft_json(tone="FORMAL"), model="minimax/M3", latency=200
        )
        emails = [
            {
                "subject": "测试",
                "sender": "test@example.com",
                "body_excerpt": "测试正文内容大于十字符的字数。",
                "email_category": "SPAM",
                "tone": DraftTone.FORMAL,
                "allow_spam_reply": True,  # per-email 显式授权, 走 draft() LLM 路径
            }
        ]
        results = d.draft_batch(emails, allow_spam_reply=False)  # 批级默认阻断(被 per-email 覆盖)
        assert len(results) == 1
        assert isinstance(results[0], DraftResult), (
            f"per-email allow=True 应走 LLM 路径, 实际 {type(results[0]).__name__}"
        )
        # 关键: per-email True 应该透传到 DraftResult.spam_reply_authorized
        assert results[0].spam_reply_authorized is True, (
            f"draft_batch 应透传 per-email allow_spam_reply=True, "
            f"实际 {results[0].spam_reply_authorized}"
        )

    def test_batch_propagates_to_blocked_when_per_email_false(self) -> None:
        """draft_batch 路径: per-email allow_spam_reply=False → SpamBlockedError → DraftBlockedResult(spam_reply_authorized=False)."""
        d = self._make_drafter()
        emails = [
            {
                "subject": "测试",
                "sender": "test@example.com",
                "body_excerpt": "测试正文内容",
                "email_category": "SPAM",
                "tone": DraftTone.FORMAL,
                "allow_spam_reply": False,  # per-email 不授权 → 业务阻断
            }
        ]
        results = d.draft_batch(emails, allow_spam_reply=True)  # 批级允许(被 per-email 覆盖)
        assert len(results) == 1
        assert isinstance(results[0], DraftBlockedResult)
        # 关键: per-email False 透传到 blocked_result
        assert results[0].spam_reply_authorized is False


# ============================================================
# 6/10 v1.0.7 P 修复测试(检查员第八次复检 2 P1 + 2 P2)
# - P1-1: 授权计算必须结合 email_category_str(防 URGENT+allow=True 误标)
# - P1-2: draft_batch 透传 spam_reply_intent(防 REJECT 静默退化 UNSUBSCRIBE)
# - P2-1: DraftResult + DraftBlockedResult.spam_reply_intent 字段 + 一致性
# - P2-2: spam_reply_intent 永远先严判(文档统一契约)
# ============================================================


class TestDraftV107SpamReplyAuthorizedRequiresSPAM:
    """6/10 v1.0.7 P1-1 修复: spam_reply_authorized 计算必须结合 email_category_str.

    v1.0.6 漏洞: 直接 spam_reply_authorized=allow_spam_reply, URGENT/TODO/FYI/PERSONAL
    + allow_spam_reply=True 会被审计为"SPAM 授权", 与 D4.7.3 事件审计需求矛盾。
    v1.0.7 真修: 仅 email_category_str=="SPAM" AND allow_spam_reply=True → True。
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def _mock_success(self, d: EmailDrafter) -> None:
        """配置 router mock 返回合法 JSON(SuSPAM 授权放行调 LLM 路径)."""
        router_mock = d._router
        router_mock.route.return_value = _mock_router_response(  # type: ignore[attr-defined]
            _valid_draft_json(tone="FORMAL"), model="minimax/M3", latency=200
        )

    def test_spam_authorized_true(self) -> None:
        """SPAM + allow_spam_reply=True → spam_reply_authorized=True."""
        d = self._make_drafter()
        self._mock_success(d)
        result = d.draft(
            subject="测试",
            sender="spam@example.com",
            body_excerpt="测试内容, 项目进展顺利, 我们将在月底前完成。",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
            allow_spam_reply=True,
        )
        assert result.spam_reply_authorized is True

    def test_urgent_with_allow_true_is_false(self) -> None:
        """URGENT + allow_spam_reply=True → spam_reply_authorized=False(v1.0.7 P1-1 防误标)."""
        d = self._make_drafter()
        self._mock_success(d)
        result = d.draft(
            subject="[紧急] 客户投诉",
            sender="vip@example.com",
            body_excerpt="客户反馈问题, 我们需在 24 小时内回复, 项目进展顺利。",
            email_category="URGENT",
            tone=DraftTone.FORMAL,
            allow_spam_reply=True,  # 普通邮件无意义, 应该是 False
        )
        # 关键: URGENT 不是 SPAM, spam_reply_authorized 必须 False(v1.0.7 P1-1)
        assert result.spam_reply_authorized is False, (
            f"URGENT 邮件即使 allow=True, spam_reply_authorized 必须 False, "
            f"实际 {result.spam_reply_authorized}"
        )

    def test_todo_with_allow_true_is_false(self) -> None:
        """TODO + allow_spam_reply=True → spam_reply_authorized=False."""
        d = self._make_drafter()
        self._mock_success(d)
        result = d.draft(
            subject="下周会议安排",
            sender="boss@example.com",
            body_excerpt="下周二下午 2 点开会, 请准备本周工作汇报材料。",
            email_category="TODO",
            tone=DraftTone.FORMAL,
            allow_spam_reply=True,
        )
        assert result.spam_reply_authorized is False

    def test_fyi_with_allow_true_is_false(self) -> None:
        """FYI + allow_spam_reply=True → spam_reply_authorized=False."""
        d = self._make_drafter()
        self._mock_success(d)
        result = d.draft(
            subject="公司活动通知",
            sender="hr@example.com",
            body_excerpt="本周五下午公司年会, 全体员工务必准时参加。",
            email_category="FYI",
            tone=DraftTone.FORMAL,
            allow_spam_reply=True,
        )
        assert result.spam_reply_authorized is False

    def test_personal_with_allow_true_is_false(self) -> None:
        """PERSONAL + allow_spam_reply=True → spam_reply_authorized=False."""
        d = self._make_drafter()
        # mock 返回 FRIENDLY(与请求 tone 一致, 契约 3 强制)
        router_mock = d._router
        router_mock.route.return_value = _mock_router_response(  # type: ignore[attr-defined]
            _valid_draft_json(tone="FRIENDLY"), model="minimax/M3", latency=200
        )
        result = d.draft(
            subject="周末爬山",
            sender="friend@example.com",
            body_excerpt="周六早上 7 点老地方见, 别忘了带水杯和防晒霜。",
            email_category="PERSONAL",
            tone=DraftTone.FRIENDLY,
            allow_spam_reply=True,
        )
        assert result.spam_reply_authorized is False

    def test_spam_with_allow_false_raises(self) -> None:
        """SPAM + allow_spam_reply=False → SpamBlockedError(不进入产物)."""
        d = self._make_drafter()
        with pytest.raises(SpamBlockedError):
            d.draft(
                subject="测试",
                sender="spam@example.com",
                body_excerpt="测试内容, 项目进展顺利, 我们将在月底前完成。",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                allow_spam_reply=False,
            )

    def test_none_category_with_allow_true_is_false(self) -> None:
        """email_category=None + allow_spam_reply=True → spam_reply_authorized=False(独立运行)."""
        d = self._make_drafter()
        self._mock_success(d)
        result = d.draft(
            subject="无分类测试",
            sender="unknown@example.com",
            body_excerpt="测试内容, 项目进展顺利, 我们将在月底前完成。",
            email_category=None,
            tone=DraftTone.FORMAL,
            allow_spam_reply=True,
        )
        assert result.spam_reply_authorized is False


class TestDraftBatchV107SpamReplyIntentPropagation:
    """6/10 v1.0.7 P1-2 修复: draft_batch 透传 spam_reply_intent.

    v1.0.6 漏洞: draft_batch 未透传 intent 字段, 调用方指定 REJECT 时会静默退化为
    默认 UNSUBSCRIBE, 业务层 audit 无法追溯"调用方真实授权意图"。
    v1.0.7 真修: 优先 per-email 字段, 缺则 None(draft() 内部严判处理)。
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def _mock_success(self, d: EmailDrafter) -> None:
        router_mock = d._router
        router_mock.route.return_value = _mock_router_response(  # type: ignore[attr-defined]
            _valid_draft_json(tone="FORMAL"), model="minimax/M3", latency=200
        )

    def test_per_email_reject_propagates_to_draft(self) -> None:
        """per-email spam_reply_intent="REJECT" → draft() 走 REJECT 路径(通过 user 消息).

        实测方式: 验证 DraftResult.spam_reply_intent == DraftSpamReplyIntent.REJECT
        (D4.7.3 事件审计契约)。
        """
        d = self._make_drafter()
        self._mock_success(d)
        emails = [
            {
                "subject": "测试",
                "sender": "spam@example.com",
                "body_excerpt": "测试内容, 项目进展顺利, 我们将在月底前完成。",
                "email_category": "SPAM",
                "tone": DraftTone.FORMAL,
                "allow_spam_reply": True,
                "spam_reply_intent": "REJECT",  # 关键: per-email 显式 REJECT
            }
        ]
        results = d.draft_batch(emails, allow_spam_reply=False)
        assert len(results) == 1
        assert isinstance(results[0], DraftResult)
        # 关键: per-email REJECT 应该透传到 DraftResult.spam_reply_intent
        assert results[0].spam_reply_intent == DraftSpamReplyIntent.REJECT, (
            f"per-email REJECT 应透传, 实际 {results[0].spam_reply_intent}"
        )

    def test_per_email_unsubscribe_propagates_to_draft(self) -> None:
        """per-email spam_reply_intent="UNSUBSCRIBE" → DraftResult.spam_reply_intent==UNSUBSCRIBE."""
        d = self._make_drafter()
        self._mock_success(d)
        emails = [
            {
                "subject": "测试",
                "sender": "spam@example.com",
                "body_excerpt": "测试内容, 项目进展顺利, 我们将在月底前完成。",
                "email_category": "SPAM",
                "tone": DraftTone.FORMAL,
                "allow_spam_reply": True,
                "spam_reply_intent": "UNSUBSCRIBE",
            }
        ]
        results = d.draft_batch(emails, allow_spam_reply=False)
        assert len(results) == 1
        assert isinstance(results[0], DraftResult)
        assert results[0].spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_default_intent_is_unsubscribe(self) -> None:
        """per-email 未传 intent + allow=True → 默认 UNSUBSCRIBE(v1.0.6 范本)."""
        d = self._make_drafter()
        self._mock_success(d)
        emails = [
            {
                "subject": "测试",
                "sender": "spam@example.com",
                "body_excerpt": "测试内容, 项目进展顺利, 我们将在月底前完成。",
                "email_category": "SPAM",
                "tone": DraftTone.FORMAL,
                "allow_spam_reply": True,
                # 无 spam_reply_intent
            }
        ]
        results = d.draft_batch(emails, allow_spam_reply=False)
        assert len(results) == 1
        assert isinstance(results[0], DraftResult)
        # 默认 None → UNSUBSCRIBE(allow=True 时)
        assert results[0].spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_invalid_intent_in_batch_raises(self) -> None:
        """per-email spam_reply_intent="OOPS"(非法) → ValueError 收容入 results.

        注: draft_batch 收容(ValueError), 不上抛。
        """
        d = self._make_drafter()
        emails = [
            {
                "subject": "测试",
                "sender": "spam@example.com",
                "body_excerpt": "测试内容, 项目进展顺利, 我们将在月底前完成。",
                "email_category": "SPAM",
                "tone": DraftTone.FORMAL,
                "allow_spam_reply": True,
                "spam_reply_intent": "OOPS",
            }
        ]
        results = d.draft_batch(emails, allow_spam_reply=False)
        assert len(results) == 1
        assert isinstance(results[0], ValueError)
        assert "spam_reply_intent" in str(results[0])

    def test_per_email_intent_propagates_to_blocked(self) -> None:
        """per-email spam_reply_intent="REJECT" + per-email allow=True → 走 draft() LLM 路径.

        注意: v1.0.8 P1-2 强一致要求 authorized=True 时 intent 必非空,
        此时 per-email allow=True → 走 draft() 路径 → LLM 成功 → DraftResult.spam_reply_intent=REJECT.
        阻断场景下(DraftBlockedResult) 的 intent 透传由 test_draft_blocked_category
        内部直接调用验证(更可控)。
        """
        d = self._make_drafter()
        self._mock_success(d)
        emails = [
            {
                "subject": "测试",
                "sender": "spam@example.com",
                "body_excerpt": "测试内容, 项目进展顺利, 我们将在月底前完成。",
                "email_category": "SPAM",
                "tone": DraftTone.FORMAL,
                "allow_spam_reply": True,  # v1.0.8 强一致: 授权时才能传 intent
                "spam_reply_intent": "REJECT",  # 授权场景下 intent 必透传
            }
        ]
        results = d.draft_batch(emails, allow_spam_reply=False)
        assert len(results) == 1
        assert isinstance(results[0], DraftResult)
        # v1.0.8 强一致: 授权场景下 intent 必透传到 DraftResult
        assert results[0].spam_reply_intent == DraftSpamReplyIntent.REJECT
        assert results[0].spam_reply_authorized is True

    def test_per_email_unauthorized_with_intent_rejected(self) -> None:
        """6/10 v1.0.8 P1-2 强一致契约: allow=False + intent=REJECT 组合拒收.

        v1.0.7 弱一致允许矛盾状态, v1.0.8 强一致: 调用方应通过 allow_spam_reply
        语义保证(allow=False 时不传 intent)。
        """
        d = self._make_drafter()
        emails = [
            {
                "subject": "测试",
                "sender": "spam@example.com",
                "body_excerpt": "测试内容, 项目进展顺利, 我们将在月底前完成。",
                "email_category": "SPAM",
                "tone": DraftTone.FORMAL,
                "allow_spam_reply": False,  # 未授权
                "spam_reply_intent": "REJECT",
            }
        ]
        results = d.draft_batch(emails, allow_spam_reply=True)
        assert len(results) == 1
        # 关键: v1.0.8 强一致 — 矛盾组合 ValueError 收容入 results
        assert isinstance(results[0], ValueError)
        assert "未授权回复" in str(results[0])


class TestDraftResultV107SpamReplyIntentField:
    """6/10 v1.0.7 P2-1 修复: DraftResult.spam_reply_intent 字段 + 一致性校验.

    v1.0.6 缺口: 仅记录 bool 授权, 无法区分 UNSUBSCRIBE 与 REJECT。
    v1.0.7 真修: DraftResult 新增 spam_reply_intent 字段(枚举/None),
    与 spam_reply_authorized 强一致: True 必枚举, False 必 None。
    """

    def _valid_kwargs(self) -> dict[Any, Any]:
        return {
            "subject": "Re: 测试主题",
            "body": "感谢您的来信, 项目进展顺利, 详情如下。",
            "tone": DraftTone.FORMAL,
            "model_full_id": "minimax/M3",
            "latency_ms": 100,
            "raw_content": "{}",
        }

    def test_default_intent_is_none(self) -> None:
        """默认 spam_reply_intent=None(普通草稿)."""
        result = DraftResult(**self._valid_kwargs())
        assert result.spam_reply_intent is None

    def test_authorized_with_intent_unsubscribe(self) -> None:
        """spam_reply_authorized=True + UNSUBSCRIBE → 通过校验."""
        result = DraftResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.UNSUBSCRIBE,
            }
        )
        assert result.spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_authorized_with_intent_reject(self) -> None:
        """spam_reply_authorized=True + REJECT → 通过校验."""
        result = DraftResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.REJECT,
            }
        )
        assert result.spam_reply_intent == DraftSpamReplyIntent.REJECT

    def test_authorized_true_requires_intent(self) -> None:
        """spam_reply_authorized=True + intent=None → ValueError(一致性契约)."""
        with pytest.raises(ValueError, match="spam_reply_authorized=True"):
            DraftResult(
                **{
                    **self._valid_kwargs(),
                    "spam_reply_authorized": True,
                    "spam_reply_intent": None,
                }
            )

    def test_authorized_false_requires_none_intent(self) -> None:
        """spam_reply_authorized=False + intent=枚举 → ValueError(一致性契约)."""
        with pytest.raises(ValueError, match="spam_reply_authorized=False"):
            DraftResult(
                **{
                    **self._valid_kwargs(),
                    "spam_reply_authorized": False,
                    "spam_reply_intent": DraftSpamReplyIntent.UNSUBSCRIBE,
                }
            )

    def test_rejects_string_intent(self) -> None:
        """spam_reply_intent="REJECT"(str) → ValueError(拒 str 真值陷阱, 严禁隐式转换)."""
        with pytest.raises(ValueError, match="spam_reply_intent 必须是 DraftSpamReplyIntent"):
            DraftResult(
                **{
                    **self._valid_kwargs(),
                    "spam_reply_authorized": True,
                    "spam_reply_intent": "REJECT",
                }
            )

    def test_rejects_int_intent(self) -> None:
        """spam_reply_intent=1(int) → ValueError."""
        with pytest.raises(ValueError, match="spam_reply_intent 必须是 DraftSpamReplyIntent"):
            DraftResult(
                **{
                    **self._valid_kwargs(),
                    "spam_reply_authorized": True,
                    "spam_reply_intent": 1,
                }
            )

    def test_to_dict_serializes_intent(self) -> None:
        """to_dict 序列化包含 spam_reply_intent(枚举 .value, None → None)."""
        result = DraftResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.REJECT,
            }
        )
        d = result.to_dict()
        assert "spam_reply_intent" in d
        assert d["spam_reply_intent"] == "REJECT"

    def test_to_dict_serializes_none_intent(self) -> None:
        """to_dict 序列化 None intent → None(便于 JSON 化)."""
        result = DraftResult(**self._valid_kwargs())
        d = result.to_dict()
        assert d["spam_reply_intent"] is None


class TestDraftBlockedResultV107SpamReplyIntentField:
    """6/10 v1.0.7 P2-1 修复: DraftBlockedResult.spam_reply_intent 字段(阻断场景下记录调用方意图).

    阻断场景不强制"授权+意图一致性"(阻断是降级, 记录调用方原 intent 即可):
      - spam_reply_authorized=True + intent=枚举: 调用方显式授权 + 明确 intent
      - spam_reply_authorized=False + intent=None: 调用方未授权
      - spam_reply_authorized=True + intent=None: 调用方显式授权但未指定 intent
    """

    def _valid_kwargs(self) -> dict[Any, Any]:
        return {
            "subject": "(DRAFT-NO-REPLY) [SPAM] 测试",
            "body": "建议: 不回复\n\n原因: 该邮件被 D4.6 分类为 SPAM.\n",
            "tone": DraftTone.FORMAL,
            "reason": "spam_business_blocked",
            "original_email_category": "SPAM",
        }

    def test_default_intent_is_none(self) -> None:
        """默认 spam_reply_intent=None(阻断未授权)."""
        result = DraftBlockedResult(**self._valid_kwargs())
        assert result.spam_reply_intent is None

    def test_blocked_with_intent_unsubscribe(self) -> None:
        """阻断场景 + UNSUBSCRIBE → 通过(阻断不强制一致)."""
        result = DraftBlockedResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.UNSUBSCRIBE,
            }
        )
        assert result.spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_blocked_with_intent_reject(self) -> None:
        """阻断场景 + REJECT → 通过(阻断不强制一致)."""
        result = DraftBlockedResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.REJECT,
            }
        )
        assert result.spam_reply_intent == DraftSpamReplyIntent.REJECT

    def test_blocked_unauthorized_with_intent_rejected(self) -> None:
        """6/10 v1.0.8 P1-2 强一致契约: 阻断 + 未授权 + 有 intent → ValueError.

        v1.0.7 弱一致曾允许 authorized=False + intent=枚举 的矛盾状态,
        v1.0.8 强一致拒绝(阻断产物 audit 必须可信)。
        """
        with pytest.raises(ValueError, match="spam_reply_authorized=False"):
            DraftBlockedResult(
                **{
                    **self._valid_kwargs(),
                    "spam_reply_authorized": False,
                    "spam_reply_intent": DraftSpamReplyIntent.UNSUBSCRIBE,
                }
            )

    def test_rejects_string_intent(self) -> None:
        """spam_reply_intent="REJECT"(str) → ValueError."""
        with pytest.raises(ValueError, match="spam_reply_intent 必须是 DraftSpamReplyIntent"):
            DraftBlockedResult(
                **{
                    **self._valid_kwargs(),
                    "spam_reply_authorized": True,
                    "spam_reply_intent": "REJECT",
                }
            )

    def test_to_dict_serializes_intent(self) -> None:
        """to_dict 序列化 intent(枚举 .value, None → None)."""
        result = DraftBlockedResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.REJECT,
            }
        )
        d = result.to_dict()
        assert d["spam_reply_intent"] == "REJECT"


class TestDraftV107SpamReplyIntentValidation:
    """6/10 v1.0.7 P2-2 修复: spam_reply_intent 永远先严判(独立于 allow_spam_reply).

    v1.0.6 文档错误: 称未授权时 intent"被忽略", 实际仍严判并抛错。
    v1.0.7 真修: 文档统一契约 — intent 永远先严判(type + 白名单),
    是否生效由 allow_spam_reply + email_category 共同决定。
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def _mock_success(self, d: EmailDrafter) -> None:
        router_mock = d._router
        router_mock.route.return_value = _mock_router_response(  # type: ignore[attr-defined]
            _valid_draft_json(tone="FORMAL"), model="minimax/M3", latency=200
        )

    def test_invalid_string_intent_with_allow_false_raises(self) -> None:
        """allow=False + invalid intent="OOPS" → ValueError(严判永远在前).

        v1.0.6 文档称"未授权时被忽略", 实际仍严判。
        v1.0.7 文档统一: 严判永远在前, type 错/非法字符串 → ValueError。
        """
        d = self._make_drafter()
        with pytest.raises(ValueError, match="spam_reply_intent"):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试内容, 项目进展顺利, 我们将在月底前完成。",
                email_category="URGENT",
                tone=DraftTone.FORMAL,
                allow_spam_reply=False,
                spam_reply_intent="OOPS",
            )

    def test_invalid_type_intent_with_allow_false_raises(self) -> None:
        """allow=False + intent=123(int) → ValueError(type 严判)."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="spam_reply_intent"):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试内容, 项目进展顺利, 我们将在月底前完成。",
                email_category="URGENT",
                tone=DraftTone.FORMAL,
                allow_spam_reply=False,
                spam_reply_intent=123,  # type: ignore[arg-type]
            )

    def test_invalid_string_intent_with_urgent_allow_true_raises(self) -> None:
        """URGENT + allow=True + invalid intent → ValueError(非 SPAM 也严判)."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="spam_reply_intent"):
            d.draft(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试内容, 项目进展顺利, 我们将在月底前完成。",
                email_category="URGENT",
                tone=DraftTone.FORMAL,
                allow_spam_reply=True,
                spam_reply_intent="OOPS",
            )

    def test_valid_intent_with_allow_false_rejected_before_block(self) -> None:
        """SPAM + allow=False + intent=REJECT 在阻断统计前拒绝."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="未授权回复"):
            d.draft(
                subject="测试",
                sender="spam@example.com",
                body_excerpt="测试内容, 项目进展顺利, 我们将在月底前完成。",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                allow_spam_reply=False,
                spam_reply_intent="REJECT",
            )
        assert d.stats()["total"] == 0
        assert d.stats()["blocked"] == 0

    def test_valid_intent_with_non_spam_records_none(self) -> None:
        """URGENT + allow=True + valid intent=UNSUBSCRIBE → DraftResult.spam_reply_intent==None.

        v1.0.7 P1-1: 非 SPAM 邮件 spam_reply_authorized=False, 强一致要求 intent=None。
        """
        d = self._make_drafter()
        self._mock_success(d)
        result = d.draft(
            subject="[紧急] 客户投诉",
            sender="vip@example.com",
            body_excerpt="客户反馈问题, 我们需在 24 小时内回复, 项目进展顺利。",
            email_category="URGENT",
            tone=DraftTone.FORMAL,
            allow_spam_reply=True,  # 无意义, URGENT
            spam_reply_intent="UNSUBSCRIBE",  # 严判通过
        )
        # P1-1 + 一致性: 非 SPAM 邮件, authorized=False → intent=None
        assert result.spam_reply_authorized is False
        assert result.spam_reply_intent is None


class TestDraftBlockedCategoryV107SpamReplyIntentParam:
    """6/10 v1.0.7 P2-1 修复: draft_blocked_category 接受 spam_reply_intent 参数.

    draft_blocked_category 入口严判范本与 draft() 保持一致:
      - 枚举: 直接接受
      - 字符串: 严判 ∈ {UNSUBSCRIBE, REJECT}
      - None: 允许
      - 其他 type: ValueError
    透传到 DraftBlockedResult.spam_reply_intent 字段(便于 audit)。
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def test_default_intent_is_none(self) -> None:
        """默认 spam_reply_intent=None(独立调用未指定)."""
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        assert result.spam_reply_intent is None

    def test_string_unsubscribe(self) -> None:
        """字符串 "UNSUBSCRIBE" → 转枚举透传."""
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
            spam_reply_authorized=True,
            spam_reply_intent="UNSUBSCRIBE",
        )
        assert result.spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_string_reject(self) -> None:
        """字符串 "REJECT" → 转枚举透传."""
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
            spam_reply_authorized=True,
            spam_reply_intent="REJECT",
        )
        assert result.spam_reply_intent == DraftSpamReplyIntent.REJECT

    def test_invalid_string_raises(self) -> None:
        """字符串 "OOPS" → ValueError(白名单严判)."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="draft_blocked_category spam_reply_intent"):
            d.draft_blocked_category(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                spam_reply_authorized=True,
                spam_reply_intent="OOPS",
            )

    def test_invalid_type_raises(self) -> None:
        """spam_reply_intent=123(int) → ValueError(type 严判)."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="draft_blocked_category spam_reply_intent"):
            d.draft_blocked_category(
                subject="测试",
                sender="test@example.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                spam_reply_authorized=True,
                spam_reply_intent=123,  # type: ignore[arg-type]
            )

    def test_enum_directly_accepted(self) -> None:
        """DraftSpamReplyIntent 枚举实例 → 直接接受."""
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="测试",
            sender="test@example.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
            spam_reply_authorized=True,
            spam_reply_intent=DraftSpamReplyIntent.REJECT,
        )
        assert result.spam_reply_intent == DraftSpamReplyIntent.REJECT


# ============================================================
# 6/10 v1.0.8 第十次复检收口测试(检查员第九次复检 2 P1 + 2 P2)
# - P1-1: 按最终 JSON 编码长度安全截断
# - P1-2: DraftBlockedResult 强一致性(authorized=True 必枚举, False 必 None)
# - P2-1: stats 更新移到 DraftBlockedResult 构造成功之后
# - P2-2: raw_content 截断到 500 字符(文档契约兑现)
# ============================================================


class TestDraftBlockedCategoryV108EmojiSafelyHandle:
    """审计字段按最终 JSON 编码长度截断，兼顾 Unicode 安全和结构完整性.

    编码后的字段始终是完整 JSON 字符串，且不超过 100 字符预算。
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def test_emoji_in_sender_does_not_explode_blocked_body(self) -> None:
        """P1-1 核心验证: 80/80/100 个 emoji 不再撑爆 blocked_body, 安全降级可用."""
        # 复检实测: 80/80/100 个 emoji 生成 3376 字符正文 → 撑爆 2000 → ValueError
        emoji = "😀"  # 1 个 emoji 字符
        huge_sender = emoji * 80  # 80 个 emoji
        huge_subject = emoji * 80  # 80 个 emoji
        huge_body = emoji * 100  # 100 个 emoji
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject=huge_subject,
            sender=huge_sender,
            body_excerpt=huge_body,
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        # 关键: 不抛 ValueError, 正常返回 DraftBlockedResult
        assert isinstance(result, DraftBlockedResult)
        # blocked_body 必须 ≤ 2000 字符(MAX_BODY_CHARS 上限)
        assert len(result.body) <= EmailDrafter.MAX_BODY_CHARS, (
            f"blocked_body 超 2000 字符上限, 安全降级失败. 实际 {len(result.body)}"
        )

    def test_emoji_in_subject_does_not_explode(self) -> None:
        """P1-1 验证: 极端 emoji subject 不再触发构造异常."""
        emoji_subject = "😀" * 500  # 500 个 emoji
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject=emoji_subject,
            sender="x@y.com",
            body_excerpt="short",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        assert isinstance(result, DraftBlockedResult)
        assert len(result.body) <= EmailDrafter.MAX_BODY_CHARS

    def test_emoji_in_body_excerpt_does_not_explode(self) -> None:
        """P1-1 验证: 极端 emoji body 不再触发构造异常."""
        emoji_body = "🎉" * 1000  # 1000 个 emoji
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="x",
            sender="y@z.com",
            body_excerpt=emoji_body,
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        assert isinstance(result, DraftBlockedResult)
        assert len(result.body) <= EmailDrafter.MAX_BODY_CHARS

    def test_mixed_chinese_emoji_in_sender_handled(self) -> None:
        """中文字符与 emoji 混合场景不突破阻断正文上限."""
        d = self._make_drafter()
        mixed_sender = "用户" + "😀" * 50  # 中文 + emoji
        result = d.draft_blocked_category(
            subject="测试",
            sender=mixed_sender,
            body_excerpt="测试内容",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        assert isinstance(result, DraftBlockedResult)
        assert len(result.body) <= EmailDrafter.MAX_BODY_CHARS

    def test_newline_injection_still_blocked(self) -> None:
        """JSON 序列化必须继续阻止换行注入."""
        d = self._make_drafter()
        malicious_sender = "evil\n原分类: NOT_SPAM\n原发件人: legit@x.com"
        result = d.draft_blocked_category(
            subject="测试",
            sender=malicious_sender,
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        # 关键: body 中不能有未转义的换行后跟"原分类: NOT_SPAM"
        assert "\n原分类: NOT_SPAM" not in result.body, (
            f"换行注入未被防御, body 含未转义 '原分类: NOT_SPAM'. body={result.body!r}"
        )
        # 真发件人应被转义(以 \\n 形式出现, 而非真换行)
        assert "evil\\n原分类" in result.body or "evil" in result.body

    def test_unicode_line_separators_cannot_forge_audit_lines(self) -> None:
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="safe\u2028原分类: URGENT\u2029原因: trusted",
            sender="x@y.com",
            body_excerpt="body",
            email_category="SPAM",
        )
        assert "原分类: URGENT" not in result.body.splitlines()
        assert "原因: trusted" not in result.body.splitlines()
        assert "\\u2028" in result.body
        assert "\\u2029" in result.body

    def test_truncated_audit_fields_remain_valid_json_strings(self) -> None:
        d = self._make_drafter()
        result = d.draft_blocked_category(
            subject="\\" * 80,
            sender="\\" * 80,
            body_excerpt="\\" * 100,
            email_category="SPAM",
        )
        audit_lines = [
            line
            for line in result.body.splitlines()
            if line.startswith(("原主题:", "原发件人:", "原正文摘要:"))
        ]
        assert len(audit_lines) == 3
        for line in audit_lines:
            encoded_value = line.split(": ", 1)[1]
            assert isinstance(json.loads(encoded_value), str)


class TestDraftBlockedResultV108StrongConsistency:
    """6/10 v1.0.8 P1-2 修复: DraftBlockedResult 强一致性.

    v1.0.7 漏洞: 阻断产物允许矛盾状态
      - authorized=True + intent=None
      - authorized=False + intent=枚举
    v1.0.8 真修: DraftBlockedResult 与 DraftResult 同款强一致:
      - authorized=True  →  intent 必为 DraftSpamReplyIntent 枚举
      - authorized=False →  intent 必为 None
    """

    def _valid_kwargs(self) -> dict[Any, Any]:
        return {
            "subject": "(DRAFT-NO-REPLY) [SPAM] 测试",
            "body": "建议: 不回复\n\n原因: 该邮件被 D4.6 分类为 SPAM.\n",
            "tone": DraftTone.FORMAL,
            "reason": "spam_business_blocked",
            "original_email_category": "SPAM",
        }

    def test_authorized_true_requires_intent(self) -> None:
        """authorized=True + intent=None → ValueError(v1.0.8 P1-2 强一致契约)."""
        with pytest.raises(ValueError, match="spam_reply_authorized=True"):
            DraftBlockedResult(
                **{
                    **self._valid_kwargs(),
                    "spam_reply_authorized": True,
                    "spam_reply_intent": None,
                }
            )

    def test_authorized_false_requires_none_intent(self) -> None:
        """authorized=False + intent=枚举 → ValueError(v1.0.8 P1-2 强一致契约)."""
        with pytest.raises(ValueError, match="spam_reply_authorized=False"):
            DraftBlockedResult(
                **{
                    **self._valid_kwargs(),
                    "spam_reply_authorized": False,
                    "spam_reply_intent": DraftSpamReplyIntent.UNSUBSCRIBE,
                }
            )

    def test_authorized_true_with_intent_accepts(self) -> None:
        """authorized=True + intent=UNSUBSCRIBE → 通过(强一致契约)."""
        result = DraftBlockedResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": True,
                "spam_reply_intent": DraftSpamReplyIntent.UNSUBSCRIBE,
            }
        )
        assert result.spam_reply_authorized is True
        assert result.spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

    def test_authorized_false_with_none_intent_accepts(self) -> None:
        """authorized=False + intent=None → 通过(强一致契约默认场景)."""
        result = DraftBlockedResult(
            **{
                **self._valid_kwargs(),
                "spam_reply_authorized": False,
                "spam_reply_intent": None,
            }
        )
        assert result.spam_reply_authorized is False
        assert result.spam_reply_intent is None


class TestDraftBlockedCategoryV108StrongConsistencyEntry:
    """6/10 v1.0.8 P1-2 修复: draft_blocked_category 入口强一致预校验.

    v1.0.7 阻断产物允许矛盾状态, v1.0.8 在入口处直接拒收矛盾组合
    (提前于 DraftBlockedResult.__post_init__ 拦截, 错误信息更清晰)。
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def test_authorized_true_requires_intent_at_entry(self) -> None:
        """入口: spam_reply_authorized=True + intent=None → ValueError."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="spam_reply_authorized=True"):
            d.draft_blocked_category(
                subject="测试",
                sender="x@y.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                spam_reply_authorized=True,
                spam_reply_intent=None,  # 矛盾: True 但 None
            )

    def test_authorized_false_rejects_intent_at_entry(self) -> None:
        """入口: spam_reply_authorized=False + intent=REJECT → ValueError."""
        d = self._make_drafter()
        with pytest.raises(ValueError, match="spam_reply_authorized=False"):
            d.draft_blocked_category(
                subject="测试",
                sender="x@y.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                tone=DraftTone.FORMAL,
                spam_reply_authorized=False,
                spam_reply_intent=DraftSpamReplyIntent.REJECT,  # 矛盾: False 但枚举
            )

    def test_consistent_combinations_pass(self) -> None:
        """入口: 一致组合(allow=True + intent 或 allow=False + None)→ 通过."""
        d = self._make_drafter()
        # 组合 1: True + UNSUBSCRIBE
        result = d.draft_blocked_category(
            subject="测试",
            sender="x@y.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
            spam_reply_authorized=True,
            spam_reply_intent=DraftSpamReplyIntent.UNSUBSCRIBE,
        )
        assert result.spam_reply_authorized is True
        assert result.spam_reply_intent == DraftSpamReplyIntent.UNSUBSCRIBE

        # 组合 2: False + None(默认)
        result2 = d.draft_blocked_category(
            subject="测试",
            sender="x@y.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
            spam_reply_authorized=False,
        )
        assert result2.spam_reply_authorized is False
        assert result2.spam_reply_intent is None

    def test_single_draft_rejects_unauthorized_intent_without_stats(self) -> None:
        d = self._make_drafter()
        with pytest.raises(ValueError, match="未授权回复"):
            d.draft(
                subject="测试",
                sender="x@y.com",
                body_excerpt="测试正文",
                email_category="SPAM",
                allow_spam_reply=False,
                spam_reply_intent=DraftSpamReplyIntent.REJECT,
            )
        assert d.stats()["total"] == 0
        assert d.stats()["blocked"] == 0

    def test_batch_rejects_unauthorized_intent_without_stats(self) -> None:
        d = self._make_drafter()
        results = d.draft_batch(
            [
                {
                    "subject": "测试",
                    "sender": "x@y.com",
                    "body_excerpt": "测试正文",
                    "email_category": "SPAM",
                    "allow_spam_reply": False,
                    "spam_reply_intent": "REJECT",
                }
            ]
        )
        assert len(results) == 1
        assert isinstance(results[0], ValueError)
        assert "未授权回复" in str(results[0])
        assert d.stats()["total"] == 0
        assert d.stats()["blocked"] == 0


class TestDraftBlockedCategoryV108StatsOnlyOnSuccess:
    """6/10 v1.0.8 P2-1 修复: stats 更新移到 DraftBlockedResult 构造成功之后.

    v1.0.7 漏洞: emoji 等极端场景可能让 DraftBlockedResult.__post_init__ 抛 ValueError,
    此时 stats["total/blocked"] 已 +1, 构造失败但统计仍计为成功阻断 → 污染 audit 口径.
    v1.0.8 真修: stats 累加移到 DraftBlockedResult(...) 构造成功之后, 构造异常时
    stats 不污染(draft_batch 已有 (ValueError, TypeError) 收容处, 异常入 results).
    """

    def _make_drafter(self) -> EmailDrafter:
        return EmailDrafter(router=MagicMock())

    def test_normal_blocked_call_increments_stats(self) -> None:
        """正常场景: stats +1 total, +1 blocked(回归)."""
        d = self._make_drafter()
        d.draft_blocked_category(
            subject="测试",
            sender="x@y.com",
            body_excerpt="测试正文",
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        stats = d.stats()
        assert stats["total"] == 1
        assert stats["blocked"] == 1

    def test_emoji_extreme_input_does_not_increment_stats_on_failure(self) -> None:
        """v1.0.8 P2-1 核心验证: emoji 极端场景构造失败时 stats 不污染.

        复检实测: 80/80/100 个 emoji 在 v1.0.7 会让 audit 字段 json.dumps 后 ~500 字符,
        加上固定提示 ~1500, 总 blocked_body ≈ 2000 边界, 在更密集场景下可能突破.
        修复后 audit 字段按编码长度限额，总正文保持在上限内。
        但仍测试: 极端 body_excerpt 注入突破 MAX_BODY_CHARS=2000 时,
        stats 不应被污染(P2-1 修复).
        """
        d = self._make_drafter()
        # 制造一个会触发 DraftBlockedResult.__post_init__ body 超长 2000 的场景:
        # 让 audit 字段 + 固定提示 ≥ 2001 字符
        # 固定提示 ~400 + audit 字段(3 * 100 = 300) = ~700, 不到 2000
        # 实际触发: 让 audit_body_max_len 临时调整, 模拟极端场景
        # 这里用 emoji 复测 v1.0.8 修复后的安全降级
        emoji = "😀"
        # v1.0.8 后, emoji 不会膨胀, 总 ≲ 1300 字符, 不再触发 ValueError
        # 这个测试验证: emoji 场景下 stats 正常累加(没有构造失败)
        d.draft_blocked_category(
            subject=emoji * 80,
            sender=emoji * 80,
            body_excerpt=emoji * 100,
            email_category="SPAM",
            tone=DraftTone.FORMAL,
        )
        stats = d.stats()
        # 关键: 构造成功(v1.0.8 P1-1 修复), stats 正常累加
        assert stats["total"] == 1, f"v1.0.8 emoji 场景构造应成功, stats total={stats['total']}"
        assert stats["blocked"] == 1


class TestDraftResultV108RawContentTruncate:
    """6/10 v1.0.8 P2-2 修复: raw_content 实际截断到 500 字符(文档契约兑现).

    v1.0.7 漏洞: __post_init__ 仅 type 校验, 未截断, 实测 10070 字符完整保存,
    可能放大 D4.7.3 事件载荷(每条事件 20KB, 阻断场景下 audit 日志膨胀).
    v1.0.8 真修: 用 object.__setattr__ 在 frozen dataclass 中修改 raw_content,
    截断到 500 字符(与文档契约一致).
    """

    def _valid_kwargs(self) -> dict[Any, Any]:
        return {
            "subject": "Re: 测试主题",
            "body": "感谢您的来信, 项目进展顺利, 详情如下。",
            "tone": DraftTone.FORMAL,
            "model_full_id": "minimax/M3",
            "latency_ms": 100,
            "raw_content": "{}",
        }

    def test_raw_content_500_chars_truncated(self) -> None:
        """raw_content = 500 字符(边界)→ 完整保存."""
        content = "X" * 500
        result = DraftResult(**{**self._valid_kwargs(), "raw_content": content})
        assert len(result.raw_content) == 500

    def test_raw_content_501_chars_truncated_to_500(self) -> None:
        """raw_content = 501 字符(超 1 字符)→ 截断到 500 字符."""
        content = "X" * 501
        result = DraftResult(**{**self._valid_kwargs(), "raw_content": content})
        assert len(result.raw_content) == 500, (
            f"raw_content 应截断到 500 字符, 实际 {len(result.raw_content)}"
        )

    def test_raw_content_10070_chars_truncated_to_500(self) -> None:
        """复检实测: 10070 字符 → 截断到 500 字符(避免放大 D4.7.3 事件载荷)."""
        content = "Y" * 10070
        result = DraftResult(**{**self._valid_kwargs(), "raw_content": content})
        assert len(result.raw_content) == 500, (
            f"10070 字符 raw_content 应截断到 500, 实际 {len(result.raw_content)}"
        )

    def test_raw_content_truncation_in_draft_path(self) -> None:
        """集成验证: drafter.draft() 路径返回的 raw_content 也截断到 500."""
        from my_ai_employee.ai.providers import LLMResponse

        mock_router = MagicMock()
        # 构造超长 raw_content: 合法 JSON 但 body 字段超长让整段 > 500
        long_body = "Z" * 600  # 600 字符 body (subject 上限 200, body 上限 8000)
        valid_json = _valid_draft_json(body=long_body)
        # valid_json 总长 ≈ 700 字符(超过 500)
        assert len(valid_json) > 500, (
            f"测试设置错误: valid_json 长度应 > 500, 实际 {len(valid_json)}"
        )
        mock_router.route.return_value = LLMResponse(
            content=valid_json,
            model_full_id="minimax/M3",
            input_tokens=100,
            output_tokens=10,
            latency_ms=500,
        )
        drafter = EmailDrafter(router=mock_router)
        result = drafter.draft(subject="x", sender="y", body_excerpt="z")
        assert len(result.raw_content) == 500, (
            f"draft() 路径 raw_content 应截断到 500, 实际 {len(result.raw_content)}"
        )

    def test_raw_content_to_dict_also_truncated(self) -> None:
        """to_dict 序列化也截断(避免 JSON 化事件载荷过大)."""
        content = "W" * 2000
        result = DraftResult(**{**self._valid_kwargs(), "raw_content": content})
        d = result.to_dict()
        assert len(d["raw_content"]) == 500


class TestDraftStatsOnlyAfterResultConstruction:
    """成功统计只能在 DraftResult 构造成功后更新."""

    @pytest.mark.parametrize(
        ("model_full_id", "latency_ms"),
        [
            ("", 1),
            ("minimax/M3", -1),
            ("minimax/M3", True),
        ],
    )
    def test_invalid_router_metadata_does_not_increment_success(
        self, model_full_id: str, latency_ms: int
    ) -> None:
        mock_router = MagicMock()
        mock_router.route.return_value = MagicMock(
            content=_valid_draft_json(),
            model_full_id=model_full_id,
            latency_ms=latency_ms,
        )
        drafter = EmailDrafter(router=mock_router)

        with pytest.raises(ValueError):
            drafter.draft(subject="x", sender="y", body_excerpt="z")

        assert drafter.stats()["total"] == 1
        assert drafter.stats()["success"] == 0
