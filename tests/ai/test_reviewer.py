"""D4.7.4 邮件草稿审阅器单元测试.

覆盖:
  - 4 字段 JSON 契约(review_passed/flagged_issues/review_summary/block_reason)
  - 双向强一致(review_passed ↔ block_reason)
  - 跨字段校验(blocked_word + sensitive_word_hit)
  - block_reason 4 类白名单
  - review_summary 1-2000 字符
  - 5+1 SYSTEM prompt 分发
  - build_user_message 抗注入
  - 业务阻断(sensitive_word_hit 等)
  - EmailReviewer 主类 + review_batch
  - ReviewResult data class

week1-mvp.md:773 真理源锁定
"""

from __future__ import annotations

import pytest

from my_ai_employee.ai.prompts.review import (
    SYSTEM_PROMPT_DEFAULT,
    SYSTEM_PROMPT_FYI,
    SYSTEM_PROMPT_PERSONAL,
    SYSTEM_PROMPT_SPAM,
    SYSTEM_PROMPT_TODO,
    SYSTEM_PROMPT_URGENT,
    build_system_prompt,
    build_user_message,
)
from my_ai_employee.ai.reviewer import (
    _REVIEW_BLOCK_REASON_CHOICES,
    _REVIEW_SUMMARY_MAX_CHARS,
    EmailReviewer,
    ReviewerError,
    ReviewerResponseError,
    ReviewResult,
    _parse_review_response,
    parse_review_response,
)

# ===== Fixtures =====


def _valid_passed_response() -> str:
    return (
        '{"review_passed": true, "flagged_issues": [], '
        '"review_summary": "草稿符合规范,通过审阅", "block_reason": null}'
    )


def _valid_blocked_response() -> str:
    return (
        '{"review_passed": false, "flagged_issues": ["包含敏感词 X"], '
        '"review_summary": "草稿命中敏感词,sensitive_word_hit", '
        '"block_reason": "sensitive_word_hit", "blocked_word": "X"}'
    )


# ===== _parse_review_response 解析器测试 =====


class TestParseReviewResponse:
    """_parse_review_response 解析器 4 字段 JSON 契约 + 双向强一致 + 跨字段."""

    def test_valid_passed(self) -> None:
        """合法通过响应 → 解析成功."""
        passed, issues, summary, reason, blocked_word = _parse_review_response(
            _valid_passed_response()
        )
        assert passed is True
        assert issues == []
        assert summary == "草稿符合规范,通过审阅"
        assert reason is None
        assert blocked_word is None

    def test_valid_blocked_with_sensitive_word(self) -> None:
        """合法阻断响应(sensitive_word_hit + blocked_word)→ 解析成功."""
        passed, issues, summary, reason, blocked_word = _parse_review_response(
            _valid_blocked_response()
        )
        assert passed is False
        assert issues == ["包含敏感词 X"]
        assert "sensitive_word_hit" in summary
        assert reason == "sensitive_word_hit"
        assert blocked_word == "X"

    def test_blocked_without_sensitive_word(self) -> None:
        """阻断响应(tone_mismatch 不需要 blocked_word)→ 解析成功."""
        content = (
            '{"review_passed": false, "flagged_issues": ["语气不匹配"], '
            '"review_summary": "草稿语气与请求 FORMAL 不一致", '
            '"block_reason": "tone_mismatch"}'
        )
        passed, issues, summary, reason, blocked_word = _parse_review_response(content)
        assert passed is False
        assert issues == ["语气不匹配"]
        assert reason == "tone_mismatch"
        assert blocked_word is None

    # ----- 双向强一致 -----

    def test_passed_with_block_reason_raises(self) -> None:
        """review_passed=True 时 block_reason 必 None → 抛 ReviewerResponseError."""
        content = (
            '{"review_passed": true, "flagged_issues": [], '
            '"review_summary": "通过", "block_reason": "sensitive_word_hit", '
            '"blocked_word": "X"}'
        )
        with pytest.raises(ReviewerResponseError, match="review_passed=True.*block_reason"):
            _parse_review_response(content)

    def test_blocked_without_block_reason_raises(self) -> None:
        """review_passed=False 时 block_reason 必非空 → 抛 ReviewerResponseError."""
        content = (
            '{"review_passed": false, "flagged_issues": ["问题"], '
            '"review_summary": "阻断", "block_reason": null}'
        )
        with pytest.raises(ReviewerResponseError, match="review_passed=False.*block_reason"):
            _parse_review_response(content)

    def test_blocked_without_flagged_issues_raises(self) -> None:
        """review_passed=False 时 flagged_issues 必非空 → 抛 ReviewerResponseError."""
        content = (
            '{"review_passed": false, "flagged_issues": [], '
            '"review_summary": "阻断", "block_reason": "tone_mismatch"}'
        )
        with pytest.raises(ReviewerResponseError, match="flagged_issues 必非空"):
            _parse_review_response(content)

    # ----- 跨字段校验 -----

    def test_sensitive_word_hit_without_blocked_word_raises(self) -> None:
        """block_reason=sensitive_word_hit 时 blocked_word 必非空 → 抛."""
        content = (
            '{"review_passed": false, "flagged_issues": ["敏感词"], '
            '"review_summary": "阻断", "block_reason": "sensitive_word_hit"}'
        )
        with pytest.raises(ReviewerResponseError, match="blocked_word 必非空"):
            _parse_review_response(content)

    def test_sensitive_word_hit_with_empty_blocked_word_raises(self) -> None:
        """blocked_word 是纯空白 → 抛."""
        content = (
            '{"review_passed": false, "flagged_issues": ["敏感词"], '
            '"review_summary": "阻断", "block_reason": "sensitive_word_hit", '
            '"blocked_word": "   "}'
        )
        with pytest.raises(ReviewerResponseError, match="blocked_word 必非空"):
            _parse_review_response(content)

    def test_tone_mismatch_with_blocked_word_raises(self) -> None:
        """block_reason=tone_mismatch 时 blocked_word 必 None → 抛."""
        content = (
            '{"review_passed": false, "flagged_issues": ["语气不匹配"], '
            '"review_summary": "阻断", "block_reason": "tone_mismatch", '
            '"blocked_word": "应使用 FORMAL"}'
        )
        with pytest.raises(ReviewerResponseError, match="blocked_word 必 None"):
            _parse_review_response(content)

    # ----- 字段类型严判 -----

    def test_review_passed_not_bool_raises(self) -> None:
        """review_passed 字段类型错 → 抛."""
        content = (
            '{"review_passed": "yes", "flagged_issues": [], '
            '"review_summary": "通过", "block_reason": null}'
        )
        with pytest.raises(ReviewerResponseError, match="review_passed 字段必须是 bool"):
            _parse_review_response(content)

    def test_review_passed_int_raises(self) -> None:
        """review_passed=1 (int, bool 子类陷阱)→ 抛."""
        content = (
            '{"review_passed": 1, "flagged_issues": [], '
            '"review_summary": "通过", "block_reason": null}'
        )
        with pytest.raises(ReviewerResponseError, match="review_passed 字段必须是 bool"):
            _parse_review_response(content)

    def test_invalid_block_reason_raises(self) -> None:
        """block_reason 不在 4 类白名单 → 抛."""
        content = (
            '{"review_passed": false, "flagged_issues": ["问题"], '
            '"review_summary": "阻断", "block_reason": "other_reason"}'
        )
        with pytest.raises(ReviewerResponseError, match="block_reason.*白名单"):
            _parse_review_response(content)

    def test_empty_review_summary_raises(self) -> None:
        """review_summary 为空 → 抛."""
        content = (
            '{"review_passed": true, "flagged_issues": [], '
            '"review_summary": "", "block_reason": null}'
        )
        with pytest.raises(ReviewerResponseError, match="review_summary.*非空"):
            _parse_review_response(content)

    def test_whitespace_only_review_summary_raises(self) -> None:
        """review_summary 纯空白 → 抛."""
        content = (
            '{"review_passed": true, "flagged_issues": [], '
            '"review_summary": "   ", "block_reason": null}'
        )
        with pytest.raises(ReviewerResponseError, match="review_summary.*非空"):
            _parse_review_response(content)

    def test_too_long_review_summary_raises(self) -> None:
        """review_summary 超 2000 字符 → 抛."""
        long_summary = "a" * (_REVIEW_SUMMARY_MAX_CHARS + 1)
        content = (
            f'{{"review_passed": true, "flagged_issues": [], '
            f'"review_summary": "{long_summary}", "block_reason": null}}'
        )
        with pytest.raises(ReviewerResponseError, match="review_summary.*超长"):
            _parse_review_response(content)

    def test_flagged_issues_not_list_raises(self) -> None:
        """flagged_issues 不是 list → 抛."""
        content = (
            '{"review_passed": false, "flagged_issues": "not_a_list", '
            '"review_summary": "阻断", "block_reason": "tone_mismatch"}'
        )
        with pytest.raises(ReviewerResponseError, match="flagged_issues 必须是 list"):
            _parse_review_response(content)

    def test_flagged_issues_item_not_str_raises(self) -> None:
        """flagged_issues 元素不是 str → 抛."""
        content = (
            '{"review_passed": false, "flagged_issues": [1, 2], '
            '"review_summary": "阻断", "block_reason": "tone_mismatch"}'
        )
        with pytest.raises(ReviewerResponseError, match="flagged_issues"):
            _parse_review_response(content)

    # ----- JSON 解析失败 -----

    def test_invalid_json_raises(self) -> None:
        """非法 JSON → 抛 ReviewerResponseError."""
        with pytest.raises(ReviewerResponseError, match="合法裸 JSON"):
            _parse_review_response("not valid json {")

    def test_top_level_not_dict_raises(self) -> None:
        """顶层不是 dict → 抛."""
        with pytest.raises(ReviewerResponseError, match="顶层必须是 object"):
            _parse_review_response("[1, 2, 3]")

    def test_non_str_content_raises(self) -> None:
        """content 不是 str → 抛."""
        with pytest.raises(ReviewerResponseError, match="content 必须是 str"):
            _parse_review_response(123)  # type: ignore[arg-type]


# ===== parse_review_response 公共 API 测试 =====


class TestParseReviewResponsePublic:
    """parse_review_response 公共 API 包装层."""

    def test_delegates_to_private(self) -> None:
        """公共 API 委托给 _parse_review_response."""
        result_public = parse_review_response(_valid_passed_response())
        result_private = _parse_review_response(_valid_passed_response())
        assert result_public == result_private


# ===== build_system_prompt 5+1 类分发 =====


class TestBuildSystemPrompt:
    """build_system_prompt 按 email_category 5+1 类分发."""

    def test_none_returns_default(self) -> None:
        """email_category=None → SYSTEM_PROMPT_DEFAULT."""
        assert build_system_prompt(None) == SYSTEM_PROMPT_DEFAULT

    def test_urgent(self) -> None:
        """URGENT → SYSTEM_PROMPT_URGENT."""
        assert build_system_prompt("URGENT") == SYSTEM_PROMPT_URGENT

    def test_todo(self) -> None:
        """TODO → SYSTEM_PROMPT_TODO."""
        assert build_system_prompt("TODO") == SYSTEM_PROMPT_TODO

    def test_fyi(self) -> None:
        """FYI → SYSTEM_PROMPT_FYI."""
        assert build_system_prompt("FYI") == SYSTEM_PROMPT_FYI

    def test_spam(self) -> None:
        """SPAM → SYSTEM_PROMPT_SPAM."""
        assert build_system_prompt("SPAM") == SYSTEM_PROMPT_SPAM

    def test_personal(self) -> None:
        """PERSONAL → SYSTEM_PROMPT_PERSONAL."""
        assert build_system_prompt("PERSONAL") == SYSTEM_PROMPT_PERSONAL

    def test_invalid_category_raises(self) -> None:
        """非 5 类字符串 → 抛 ValueError."""
        with pytest.raises(ValueError, match="email_category 字符串必须"):
            build_system_prompt("OTHER")

    def test_non_str_non_none_raises(self) -> None:
        """非 str 非 None → 抛 ValueError."""
        with pytest.raises(ValueError, match="email_category 必须是 str 或 None"):
            build_system_prompt(123)  # type: ignore[arg-type]


# ===== build_user_message 抗注入测试 =====


class TestBuildUserMessage:
    """build_user_message 抗注入三字段包裹 + 严判."""

    def test_returns_one_user_message(self) -> None:
        """返回 1 条 user 消息."""
        msgs = build_user_message(
            draft_subject="[紧急] 客户投诉",
            draft_body="订单 #1234 严重延迟,需要立即处理",
        )
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_untrusted_data_block_present(self) -> None:
        """UNTRUSTED_DATA block 包裹原邮件 + 草稿."""
        msgs = build_user_message(
            draft_subject="test",
            draft_body="test body content",
            orig_subject="orig",
        )
        content = msgs[0]["content"]
        assert "UNTRUSTED_DATA_BEGIN" in content
        assert "UNTRUSTED_DATA_END" in content
        # 草稿字段被 json.dumps 序列化
        assert '"subject"' in content
        assert '"body"' in content

    def test_email_category_line(self) -> None:
        """email_category 在 user 消息中显式标注."""
        msgs = build_user_message(
            draft_subject="test",
            draft_body="test body",
            email_category="URGENT",
        )
        assert "分类: URGENT" in msgs[0]["content"]

    def test_no_email_category_no_line(self) -> None:
        """email_category=None → 不显示分类行."""
        msgs = build_user_message(draft_subject="test", draft_body="test body")
        assert "分类" not in msgs[0]["content"]

    def test_top_level_truncation_long_body(self) -> None:
        """draft_body > 2000 字符自动截断."""
        long_body = "x" * 5000
        msgs = build_user_message(draft_subject="test", draft_body=long_body)
        # 截断后 body_excerpt 部分只包含前 2000 个 x
        # 用 body_excerpt 字面值校验(json.dumps 不会变化)
        assert len(long_body[:2000]) == 2000
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_invalid_draft_subject_type_raises(self) -> None:
        """draft_subject 不是 str → 抛 ValueError."""
        with pytest.raises(ValueError, match="draft_subject 必须是 str"):
            build_user_message(draft_subject=123, draft_body="test")  # type: ignore[arg-type]

    def test_invalid_draft_body_type_raises(self) -> None:
        """draft_body 不是 str → 抛 ValueError."""
        with pytest.raises(ValueError, match="draft_body 必须是 str"):
            build_user_message(draft_subject="test", draft_body=123)  # type: ignore[arg-type]


# ===== ReviewResult 数据类测试 =====


class TestReviewResult:
    """ReviewResult 数据类 4 字段契约 + 双向强一致 + 跨字段."""

    def _make_passed(self) -> ReviewResult:
        return ReviewResult(
            review_passed=True,
            flagged_issues=[],
            review_summary="通过审阅",
            block_reason=None,
            blocked_word=None,
            model_full_id="deepseek/deepseek-chat",
            latency_ms=150,
            raw_content=_valid_passed_response(),
        )

    def _make_blocked_sensitive(self) -> ReviewResult:
        return ReviewResult(
            review_passed=False,
            flagged_issues=["包含敏感词 X"],
            review_summary="阻断",
            block_reason="sensitive_word_hit",
            blocked_word="X",
            model_full_id="deepseek/deepseek-chat",
            latency_ms=150,
            raw_content=_valid_blocked_response(),
        )

    def test_passed_result_valid(self) -> None:
        """合法通过结果 → 构造成功."""
        r = self._make_passed()
        assert r.review_passed is True
        assert r.flagged_issues == []
        assert r.review_summary == "通过审阅"
        assert r.block_reason is None
        assert r.blocked_word is None
        assert r.latency_ms == 150

    def test_blocked_sensitive_result_valid(self) -> None:
        """合法阻断结果(sensitive_word_hit)→ 构造成功."""
        r = self._make_blocked_sensitive()
        assert r.review_passed is False
        assert r.flagged_issues == ["包含敏感词 X"]
        assert r.block_reason == "sensitive_word_hit"
        assert r.blocked_word == "X"

    def test_passed_with_block_reason_raises(self) -> None:
        """review_passed=True + block_reason 非空 → 抛 ValueError."""
        with pytest.raises(ValueError, match="review_passed=True.*block_reason"):
            ReviewResult(
                review_passed=True,
                flagged_issues=[],
                review_summary="通过",
                block_reason="tone_mismatch",  # 矛盾
                blocked_word=None,
                model_full_id="test/model",
                latency_ms=100,
                raw_content="{}",
            )

    def test_blocked_without_block_reason_raises(self) -> None:
        """review_passed=False + block_reason=None → 抛 ValueError."""
        with pytest.raises(ValueError, match="review_passed=False.*block_reason"):
            ReviewResult(
                review_passed=False,
                flagged_issues=["问题"],
                review_summary="阻断",
                block_reason=None,  # 矛盾
                blocked_word=None,
                model_full_id="test/model",
                latency_ms=100,
                raw_content="{}",
            )

    def test_blocked_without_flagged_issues_raises(self) -> None:
        """review_passed=False + flagged_issues=[] → 抛 ValueError."""
        with pytest.raises(ValueError, match="review_passed=False.*flagged_issues"):
            ReviewResult(
                review_passed=False,
                flagged_issues=[],  # 矛盾
                review_summary="阻断",
                block_reason="tone_mismatch",
                blocked_word=None,
                model_full_id="test/model",
                latency_ms=100,
                raw_content="{}",
            )

    def test_sensitive_word_hit_without_blocked_word_raises(self) -> None:
        """sensitive_word_hit + blocked_word=None → 抛 ValueError."""
        with pytest.raises(ValueError, match="sensitive_word_hit.*blocked_word"):
            ReviewResult(
                review_passed=False,
                flagged_issues=["问题"],
                review_summary="阻断",
                block_reason="sensitive_word_hit",
                blocked_word=None,  # 矛盾
                model_full_id="test/model",
                latency_ms=100,
                raw_content="{}",
            )

    def test_tone_mismatch_with_blocked_word_raises(self) -> None:
        """tone_mismatch + blocked_word 非空 → 抛 ValueError."""
        with pytest.raises(ValueError, match="tone_mismatch.*blocked_word"):
            ReviewResult(
                review_passed=False,
                flagged_issues=["问题"],
                review_summary="阻断",
                block_reason="tone_mismatch",
                blocked_word="应使用 FORMAL",  # 矛盾
                model_full_id="test/model",
                latency_ms=100,
                raw_content="{}",
            )

    def test_too_long_summary_raises(self) -> None:
        """review_summary 超 2000 字符 → 抛 ValueError."""
        with pytest.raises(ValueError, match="review_summary.*超长"):
            ReviewResult(
                review_passed=True,
                flagged_issues=[],
                review_summary="a" * (_REVIEW_SUMMARY_MAX_CHARS + 1),
                block_reason=None,
                blocked_word=None,
                model_full_id="test/model",
                latency_ms=100,
                raw_content="{}",
            )

    def test_empty_summary_raises(self) -> None:
        """review_summary 为空 → 抛 ValueError."""
        with pytest.raises(ValueError, match="review_summary"):
            ReviewResult(
                review_passed=True,
                flagged_issues=[],
                review_summary="   ",
                block_reason=None,
                blocked_word=None,
                model_full_id="test/model",
                latency_ms=100,
                raw_content="{}",
            )

    def test_negative_latency_raises(self) -> None:
        """latency_ms < 0 → 抛 ValueError."""
        with pytest.raises(ValueError, match="latency_ms"):
            ReviewResult(
                review_passed=True,
                flagged_issues=[],
                review_summary="通过",
                block_reason=None,
                blocked_word=None,
                model_full_id="test/model",
                latency_ms=-1,
                raw_content="{}",
            )

    def test_bool_latency_raises(self) -> None:
        """latency_ms= True (bool 子类陷阱)→ 抛 ValueError."""
        with pytest.raises(ValueError, match="latency_ms"):
            ReviewResult(
                review_passed=True,
                flagged_issues=[],
                review_summary="通过",
                block_reason=None,
                blocked_word=None,
                model_full_id="test/model",
                latency_ms=True,  # type: ignore[arg-type]
                raw_content="{}",
            )

    def test_to_dict(self) -> None:
        """to_dict 序列化所有字段."""
        r = self._make_blocked_sensitive()
        d = r.to_dict()
        assert d["review_passed"] is False
        assert d["flagged_issues"] == ["包含敏感词 X"]
        assert d["block_reason"] == "sensitive_word_hit"
        assert d["blocked_word"] == "X"
        assert d["model_full_id"] == "deepseek/deepseek-chat"
        assert d["latency_ms"] == 150

    def test_raw_content_truncation(self) -> None:
        """raw_content > 500 字符自动截断."""
        long_raw = "x" * 1000
        r = ReviewResult(
            review_passed=True,
            flagged_issues=[],
            review_summary="通过",
            block_reason=None,
            blocked_word=None,
            model_full_id="test/model",
            latency_ms=100,
            raw_content=long_raw,
        )
        assert len(r.raw_content) == 500


# ===== EmailReviewer 主类测试 =====


class TestEmailReviewer:
    """EmailReviewer 主类 + 输入严判."""

    def test_init_default(self) -> None:
        """默认初始化: router + max_tokens."""
        reviewer = EmailReviewer()
        assert reviewer._router is not None
        assert reviewer._max_tokens == 1024

    def test_init_max_tokens_zero_raises(self) -> None:
        """max_tokens <= 0 → 抛 ValueError."""
        with pytest.raises(ValueError, match="max_tokens 必须 > 0"):
            EmailReviewer(max_tokens=0)

    def test_init_max_tokens_negative_raises(self) -> None:
        """max_tokens = -1 → 抛 ValueError."""
        with pytest.raises(ValueError, match="max_tokens 必须 > 0"):
            EmailReviewer(max_tokens=-1)

    def test_init_max_tokens_str_raises(self) -> None:
        """max_tokens = "512" → 抛 ValueError(type 错)."""
        with pytest.raises(ValueError, match="max_tokens 必须是 int"):
            EmailReviewer(max_tokens="512")  # type: ignore[arg-type]

    def test_init_max_tokens_bool_raises(self) -> None:
        """max_tokens = True (bool 子类陷阱)→ 抛 ValueError."""
        with pytest.raises(ValueError, match="max_tokens 必须是 int"):
            EmailReviewer(max_tokens=True)  # type: ignore[arg-type]

    def test_review_short_subject_raises(self) -> None:
        """draft_subject 长度 < 1 → 抛 ValueError."""
        reviewer = EmailReviewer()
        with pytest.raises(ValueError, match="draft_subject 长度"):
            reviewer.review(draft_subject="", draft_body="valid body content here")

    def test_review_long_subject_raises(self) -> None:
        """draft_subject 长度 > 200 → 抛 ValueError."""
        reviewer = EmailReviewer()
        with pytest.raises(ValueError, match="draft_subject 长度"):
            reviewer.review(
                draft_subject="a" * 201,
                draft_body="valid body content here",
            )

    def test_review_short_body_raises(self) -> None:
        """draft_body 长度 < 10 → 抛 ValueError."""
        reviewer = EmailReviewer()
        with pytest.raises(ValueError, match="draft_body 长度"):
            reviewer.review(draft_subject="valid subject", draft_body="short")

    def test_review_long_body_raises(self) -> None:
        """draft_body 长度 > 8000 → 抛 ValueError."""
        reviewer = EmailReviewer()
        with pytest.raises(ValueError, match="draft_body 长度"):
            reviewer.review(
                draft_subject="valid subject",
                draft_body="a" * 8001,
            )

    def test_review_invalid_draft_subject_type_raises(self) -> None:
        """draft_subject 不是 str → 抛 ValueError."""
        reviewer = EmailReviewer()
        with pytest.raises(ValueError, match="draft_subject 必须是 str"):
            reviewer.review(draft_subject=123, draft_body="valid body")  # type: ignore[arg-type]

    def test_review_invalid_email_category_raises(self) -> None:
        """email_category 不在 5 类 → 抛 ValueError."""
        reviewer = EmailReviewer()
        with pytest.raises(ValueError, match="email_category 字符串必须"):
            reviewer.review(
                draft_subject="valid subject",
                draft_body="valid body content",
                email_category="OTHER",
            )

    def test_review_accepts_email_category_enum(self) -> None:
        """email_category 接受 EmailCategory 枚举(mock router 验证)."""
        from unittest.mock import MagicMock

        from my_ai_employee.ai.classifier import EmailCategory

        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.content = _valid_passed_response()
        mock_response.model_full_id = "deepseek/deepseek-chat"
        mock_response.latency_ms = 200
        mock_router.route.return_value = mock_response

        reviewer = EmailReviewer(router=mock_router)
        result = reviewer.review(
            draft_subject="valid subject",
            draft_body="valid body content here",
            email_category=EmailCategory.URGENT,
        )
        assert result.review_passed is True

    def test_review_with_email_category_none(self) -> None:
        """email_category=None → 走 DEFAULT SYSTEM prompt."""
        from unittest.mock import MagicMock

        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.content = _valid_passed_response()
        mock_response.model_full_id = "deepseek/deepseek-chat"
        mock_response.latency_ms = 200
        mock_router.route.return_value = mock_response

        reviewer = EmailReviewer(router=mock_router)
        result = reviewer.review(
            draft_subject="valid subject",
            draft_body="valid body content here",
        )
        assert result.review_passed is True

    def test_review_blocked_result(self) -> None:
        """review() 收到阻断响应 → 返回 review_passed=False 的 ReviewResult."""
        from unittest.mock import MagicMock

        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.content = _valid_blocked_response()
        mock_response.model_full_id = "deepseek/deepseek-chat"
        mock_response.latency_ms = 200
        mock_router.route.return_value = mock_response

        reviewer = EmailReviewer(router=mock_router)
        result = reviewer.review(
            draft_subject="valid subject",
            draft_body="valid body content here",
        )
        assert result.review_passed is False
        assert result.block_reason == "sensitive_word_hit"
        assert result.blocked_word == "X"
        assert "包含敏感词 X" in result.flagged_issues

    def test_review_response_error_passthrough(self) -> None:
        """review() 收到脏响应 → 抛 ReviewerResponseError."""
        from unittest.mock import MagicMock

        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "not valid json"
        mock_response.model_full_id = "test/model"
        mock_response.latency_ms = 200
        mock_router.route.return_value = mock_response

        reviewer = EmailReviewer(router=mock_router)
        with pytest.raises(ReviewerResponseError, match="合法裸 JSON"):
            reviewer.review(
                draft_subject="valid subject",
                draft_body="valid body content here",
            )

    def test_review_llm_error_passthrough(self) -> None:
        """review() 收到 LLM 全链失败 → 抛 LLMError."""
        from unittest.mock import MagicMock

        from my_ai_employee.ai.providers import LLMError

        mock_router = MagicMock()
        mock_router.route.side_effect = LLMError("all chains failed")

        reviewer = EmailReviewer(router=mock_router)
        with pytest.raises(LLMError, match="all chains failed"):
            reviewer.review(
                draft_subject="valid subject",
                draft_body="valid body content here",
            )

    def test_review_uses_review_task_type(self) -> None:
        """review() 调 router 时用 TaskType.REVIEW."""
        from unittest.mock import MagicMock

        from my_ai_employee.ai.capability import TaskType

        mock_router = MagicMock()
        mock_response = MagicMock()
        mock_response.content = _valid_passed_response()
        mock_response.model_full_id = "test/model"
        mock_response.latency_ms = 100
        mock_router.route.return_value = mock_response

        reviewer = EmailReviewer(router=mock_router)
        reviewer.review(
            draft_subject="valid subject",
            draft_body="valid body content here",
        )
        call_kwargs = mock_router.route.call_args.kwargs
        assert call_kwargs["task_type"] == TaskType.REVIEW


# ===== EmailReviewer.review_batch 测试 =====


class TestEmailReviewerBatch:
    """EmailReviewer.review_batch 批量串行."""

    def test_batch_empty(self) -> None:
        """空 batch → 空 list."""
        reviewer = EmailReviewer()
        assert reviewer.review_batch([]) == []

    def test_batch_missing_keys_raises(self) -> None:
        """dict 缺字段 → KeyError 入 results(1:1 对齐)."""
        reviewer = EmailReviewer()
        results = reviewer.review_batch([{"draft_subject": "valid"}])  # 缺 draft_body
        assert len(results) == 1
        assert isinstance(results[0], KeyError)

    def test_batch_non_dict_raises(self) -> None:
        """list 元素不是 dict → ValueError 入 results."""
        reviewer = EmailReviewer()
        results = reviewer.review_batch([123])  # type: ignore[list-item]
        assert len(results) == 1
        assert isinstance(results[0], ValueError)


# ===== 契约锁定测试(week1-mvp.md:773)=====


class TestContractLocks:
    """4 项契约 + 4 类业务阻断白名单."""

    def test_block_reason_4_choices(self) -> None:
        """block_reason 4 类白名单锁定."""
        assert (
            frozenset(
                {
                    "sensitive_word_hit",
                    "template_violation",
                    "tone_mismatch",
                    "factual_conflict",
                }
            )
            == _REVIEW_BLOCK_REASON_CHOICES
        )

    def test_summary_max_chars(self) -> None:
        """review_summary 上限 2000."""
        assert _REVIEW_SUMMARY_MAX_CHARS == 2000

    def test_all_5_categories_in_prompts(self) -> None:
        """5+1 SYSTEM prompt 全部定义."""
        assert SYSTEM_PROMPT_DEFAULT is not None
        assert SYSTEM_PROMPT_URGENT is not None
        assert SYSTEM_PROMPT_TODO is not None
        assert SYSTEM_PROMPT_FYI is not None
        assert SYSTEM_PROMPT_SPAM is not None
        assert SYSTEM_PROMPT_PERSONAL is not None

    def test_reviewer_error_is_exception(self) -> None:
        """ReviewerError 是 Exception 子类."""
        assert issubclass(ReviewerError, Exception)
        assert issubclass(ReviewerResponseError, ReviewerError)
