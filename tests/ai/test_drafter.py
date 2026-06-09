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
# Section 0.5: DraftResult 自校验(6/9 v1.0.2 P2-3)
# ============================================================


class TestDraftResultPostInit:
    """DraftResult __post_init__ 严判 5 字段(6/9 v1.0.2 P2-3)."""

    def _valid_kwargs(self) -> dict:
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
            validate_draft_subject(123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(["A"])  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        """D4.4 P1 教训: 拒 bool 子类陷阱(isinstance(True, int) == True)."""
        with pytest.raises(ValueError, match="subject 必须是 str"):
            validate_draft_subject(True)  # type: ignore[arg-type]

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
            validate_draft_body(123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="body 必须是 str"):
            validate_draft_body(None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="body 必须是 str"):
            validate_draft_body(["x"] * 10)  # type: ignore[arg-type]

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

        6/9 P1-2 修复后: `[1,2,3]` 整段 json.loads 成功, 走到 dict 严判 → 顶层必须是 object.
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
        assert has_markdown_fence(123) is False  # type: ignore[arg-type]
        assert has_markdown_fence(None) is False  # type: ignore[arg-type]

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
        from my_ai_employee.ai.drafter import SpamBlockedError

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
        """list 元素不是 dict → ValueError 入 list(D3.3.3 教训)."""
        from typing import Any, cast

        mock_router = MagicMock()
        mock_router.route.return_value = _mock_router_response(_valid_draft_json())
        drafter = EmailDrafter(router=mock_router)
        emails = cast(
            list[dict[str, Any]],
            [
                {"subject": "s", "sender": "x", "body_excerpt": "b"},
                "not a dict",
            ],
        )
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
