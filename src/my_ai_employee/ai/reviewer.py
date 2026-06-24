"""D4.7.4 邮件草稿审阅原子能力."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from loguru import logger

from .capability import TaskType
from .classifier import EmailCategory
from .drafter import DraftTone, validate_draft_body, validate_draft_subject
from .prompts.review import build_system_prompt, build_user_message
from .providers import LLMError
from .router import LLMRouter, get_router


class ReviewBlockReason(StrEnum):
    """D4.7.4 锁定的四类业务阻断原因."""

    SENSITIVE_WORD_HIT = "sensitive_word_hit"
    TEMPLATE_VIOLATION = "template_violation"
    TONE_MISMATCH = "tone_mismatch"
    FACTUAL_CONFLICT = "factual_conflict"


_BLOCK_REASONS = frozenset(reason.value for reason in ReviewBlockReason)
_TONE_MISMATCH_FORBIDDEN: dict[EmailCategory, frozenset[DraftTone]] = {
    EmailCategory.URGENT: frozenset({DraftTone.FRIENDLY}),
    EmailCategory.PERSONAL: frozenset({DraftTone.FORMAL, DraftTone.CONCISE}),
}
_DEFAULT_SENSITIVE_WORDS = frozenset(
    {
        "身份证号",
        "银行卡号",
        "信用卡号",
        "银行密码",
        "登录密码",
        "短信验证码",
        "API密钥",
        "API key",
        "密钥",
        "token",
        "Bearer token",
        "OAuth",
        "访问令牌",
        "私钥",
        "凭证",
        "内部代号",
        "客户名单",
        "薪资明细",
        "绝密",
        "机密",
        "商业秘密",
        "保证退款",
        "承诺赔偿",
        "无条件赔付",
        "永久有效",
        "百分百保证",
    }
)


class ReviewerError(Exception):
    """审阅器业务异常基类."""


class ReviewerResponseError(ReviewerError):
    """LLM 审阅响应不符合锁定契约."""

    def __init__(self, message: str, *, raw_content: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.raw_content = raw_content[:500]
        self.reason = reason


def _validate_email_category(value: Any) -> EmailCategory:
    if isinstance(value, EmailCategory):
        return value
    if type(value) is str:
        try:
            return EmailCategory(value)
        except ValueError as exc:
            raise ValueError(
                f"email_category 必须在 {[item.value for item in EmailCategory]} 中, 实际 {value!r}"
            ) from exc
    raise ValueError(
        f"email_category 必须是 EmailCategory 或 str, 实际 {type(value).__name__}={value!r}"
    )


def _validate_tone(value: Any) -> DraftTone:
    if isinstance(value, DraftTone):
        return value
    if type(value) is str:
        try:
            return DraftTone(value)
        except ValueError as exc:
            raise ValueError(
                f"tone 必须在 {[item.value for item in DraftTone]} 中, 实际 {value!r}"
            ) from exc
    raise ValueError(f"tone 必须是 DraftTone 或 str, 实际 {type(value).__name__}={value!r}")


def _validate_nonblank_string(value: Any, *, field: str, max_chars: int | None = None) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} 必填非空白 str, 实际 {type(value).__name__}={value!r}")
    if max_chars is not None and len(value) > max_chars:
        raise ValueError(f"{field} 不能超过 {max_chars} 字符, 实际 {len(value)}")
    return value


def _validate_flagged_issues(value: Any, *, required: bool) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"flagged_issues 必须是 list[str], 实际 {type(value).__name__}={value!r}")
    issues: list[str] = []
    for index, issue in enumerate(value):
        if type(issue) is not str or not issue.strip():
            raise ValueError(
                f"flagged_issues[{index}] 必填非空白 str, 实际 {type(issue).__name__}={issue!r}"
            )
        issues.append(issue)
    if required and not issues:
        raise ValueError("review_passed=False 或业务阻断时 flagged_issues 必须至少包含 1 项")
    return issues


def _validate_common_draft_fields(
    *,
    subject: Any,
    body: Any,
    tone: Any,
    email_category: Any,
) -> tuple[DraftTone, EmailCategory]:
    validate_draft_subject(subject)
    validate_draft_body(body)
    return _validate_tone(tone), _validate_email_category(email_category)


@dataclass(frozen=True)
class ReviewResult:
    """LLM 草稿审阅结果."""

    subject: str
    body: str
    tone: DraftTone
    email_category: EmailCategory
    review_passed: bool
    flagged_issues: list[str]
    review_summary: str
    model_full_id: str
    latency_ms: int
    raw_content: str

    def __post_init__(self) -> None:
        tone, email_category = _validate_common_draft_fields(
            subject=self.subject,
            body=self.body,
            tone=self.tone,
            email_category=self.email_category,
        )
        object.__setattr__(self, "tone", tone)
        object.__setattr__(self, "email_category", email_category)
        if type(self.review_passed) is not bool:
            raise ValueError(
                f"review_passed 必须是 bool, 实际 "
                f"{type(self.review_passed).__name__}={self.review_passed!r}"
            )
        issues = _validate_flagged_issues(
            self.flagged_issues,
            required=not self.review_passed,
        )
        object.__setattr__(self, "flagged_issues", issues)
        _validate_nonblank_string(
            self.review_summary,
            field="review_summary",
            max_chars=2000,
        )
        _validate_nonblank_string(self.model_full_id, field="model_full_id")
        if type(self.latency_ms) is not int or isinstance(self.latency_ms, bool):
            raise ValueError(
                f"latency_ms 必须是 int(非 bool), 实际 "
                f"{type(self.latency_ms).__name__}={self.latency_ms!r}"
            )
        if self.latency_ms < 0:
            raise ValueError(f"latency_ms 必须 >= 0, 实际 {self.latency_ms}")
        if type(self.raw_content) is not str:
            raise ValueError(
                f"raw_content 必须是 str, 实际 "
                f"{type(self.raw_content).__name__}={self.raw_content!r}"
            )
        if len(self.raw_content) > 500:
            object.__setattr__(self, "raw_content", self.raw_content[:500])

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "tone": self.tone.value,
            "email_category": self.email_category.value,
            "review_passed": self.review_passed,
            "flagged_issues": list(self.flagged_issues),
            "review_summary": self.review_summary,
            "model_full_id": self.model_full_id,
            "latency_ms": self.latency_ms,
            "raw_content": self.raw_content,
        }


@dataclass(frozen=True)
class ReviewBlockedResult:
    """本地硬规则命中的业务阻断结果."""

    subject: str
    body: str
    tone: DraftTone
    email_category: EmailCategory
    blocked: Literal[True]
    reason: ReviewBlockReason
    blocked_word: str
    flagged_issues: list[str]
    review_summary: str

    def __post_init__(self) -> None:
        tone, email_category = _validate_common_draft_fields(
            subject=self.subject,
            body=self.body,
            tone=self.tone,
            email_category=self.email_category,
        )
        object.__setattr__(self, "tone", tone)
        object.__setattr__(self, "email_category", email_category)
        if self.blocked is not True:
            raise ValueError(f"ReviewBlockedResult.blocked 必为 True, 实际 {self.blocked!r}")
        if not isinstance(self.reason, ReviewBlockReason):
            raise ValueError(
                f"reason 必须是 ReviewBlockReason, 实际 "
                f"{type(self.reason).__name__}={self.reason!r}"
            )
        issues = _validate_flagged_issues(self.flagged_issues, required=True)
        object.__setattr__(self, "flagged_issues", issues)
        _validate_nonblank_string(
            self.review_summary,
            field="review_summary",
            max_chars=2000,
        )
        if type(self.blocked_word) is not str:
            raise ValueError(
                f"blocked_word 必须是 str, 实际 "
                f"{type(self.blocked_word).__name__}={self.blocked_word!r}"
            )
        if self.reason is ReviewBlockReason.SENSITIVE_WORD_HIT:
            _validate_nonblank_string(self.blocked_word, field="blocked_word")
        elif self.blocked_word:
            raise ValueError(
                f"reason={self.reason.value!r} 时 blocked_word 必须为空字符串, "
                f"实际 {self.blocked_word!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "tone": self.tone.value,
            "email_category": self.email_category.value,
            "blocked": self.blocked,
            "reason": self.reason.value,
            "blocked_word": self.blocked_word,
            "flagged_issues": list(self.flagged_issues),
            "review_summary": self.review_summary,
        }


@dataclass(frozen=True)
class ReviewFailureResult:
    """LLM 链路或响应解析失败结果."""

    subject: str
    body: str
    tone: DraftTone
    email_category: EmailCategory
    failed: Literal[True]
    last_error: str
    consecutive_review_failures: int

    def __post_init__(self) -> None:
        tone, email_category = _validate_common_draft_fields(
            subject=self.subject,
            body=self.body,
            tone=self.tone,
            email_category=self.email_category,
        )
        object.__setattr__(self, "tone", tone)
        object.__setattr__(self, "email_category", email_category)
        if self.failed is not True:
            raise ValueError(f"ReviewFailureResult.failed 必为 True, 实际 {self.failed!r}")
        _validate_nonblank_string(self.last_error, field="last_error")
        if (
            type(self.consecutive_review_failures) is not int
            or isinstance(self.consecutive_review_failures, bool)
            or self.consecutive_review_failures < 1
        ):
            raise ValueError(
                "consecutive_review_failures 必须是 int(非 bool) >= 1, "
                f"实际 {self.consecutive_review_failures!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "body": self.body,
            "tone": self.tone.value,
            "email_category": self.email_category.value,
            "failed": self.failed,
            "last_error": self.last_error,
            "consecutive_review_failures": self.consecutive_review_failures,
        }


def _has_outer_markdown_fence(raw: Any) -> bool:
    if type(raw) is not str:
        return False
    stripped = raw.strip()
    return stripped.startswith("```") and stripped.endswith("```")


def _parse_review_response(content: Any) -> tuple[bool, list[str], str]:
    """严格解析锁定的三字段裸 JSON 响应."""

    if type(content) is not str:
        raise ReviewerResponseError(
            "LLM content 必须是 str",
            raw_content=str(content),
            reason=f"type={type(content).__name__}",
        )
    try:
        data = json.loads(content.strip())
    except (json.JSONDecodeError, ValueError) as exc:
        reason = "markdown_fenced_outer" if _has_outer_markdown_fence(content) else "json_decode"
        raise ReviewerResponseError(
            "LLM 响应必须是无 markdown 包裹的裸 JSON",
            raw_content=content,
            reason=reason,
        ) from exc
    if not isinstance(data, dict):
        raise ReviewerResponseError(
            "JSON 顶层必须是 object",
            raw_content=content,
            reason=f"top_level={type(data).__name__}",
        )
    required_keys = {"review_passed", "flagged_issues", "review_summary"}
    if set(data) != required_keys:
        raise ReviewerResponseError(
            f"JSON 字段必须严格等于 {sorted(required_keys)}, 实际 {sorted(data)}",
            raw_content=content,
            reason="field_set_mismatch",
        )
    review_passed = data["review_passed"]
    if type(review_passed) is not bool:
        raise ReviewerResponseError(
            "review_passed 必须是 bool",
            raw_content=content,
            reason=f"review_passed_type={type(review_passed).__name__}",
        )
    try:
        issues = _validate_flagged_issues(
            data["flagged_issues"],
            required=not review_passed,
        )
        summary = _validate_nonblank_string(
            data["review_summary"],
            field="review_summary",
            max_chars=2000,
        )
    except ValueError as exc:
        raise ReviewerResponseError(
            str(exc),
            raw_content=content,
            reason="business_field_invalid",
        ) from exc
    return review_passed, issues, summary


def parse_review_response(content: Any) -> tuple[bool, list[str], str]:
    """公共 API: 复用同一套三字段严格解析契约."""

    return _parse_review_response(content)


def has_markdown_fence(raw: Any) -> bool:
    """公共 API: 判断响应是否被外层 markdown fence 包裹."""

    return _has_outer_markdown_fence(raw)


def _find_local_block(
    *,
    subject: str,
    body: str,
    tone: DraftTone,
    email_category: EmailCategory,
    original_body_excerpt: str,
    sensitive_words: frozenset[str],
) -> tuple[ReviewBlockReason, str, list[str], str] | None:
    combined = f"{subject}\n{body}"
    hits = sorted(word for word in sensitive_words if word in combined)
    if hits:
        word = hits[0]
        return (
            ReviewBlockReason.SENSITIVE_WORD_HIT,
            word,
            [f"草稿命中敏感词: {word}"],
            "草稿包含敏感信息或高风险承诺，已在本地规则层阻断。",
        )

    forbidden = _TONE_MISMATCH_FORBIDDEN.get(email_category, frozenset())
    if tone in forbidden:
        return (
            ReviewBlockReason.TONE_MISMATCH,
            "",
            [f"{email_category.value} 邮件不允许使用 {tone.value} 语气"],
            "草稿语气与邮件场景不匹配。",
        )

    markers = ("[DRAFT-TEST]", "[TEMP-DRAFT]", "测试草稿")
    marker = next((item for item in markers if item in combined), None)
    if marker is not None:
        return (
            ReviewBlockReason.TEMPLATE_VIOLATION,
            "",
            [f"草稿包含不可投递的测试标记: {marker}"],
            "草稿违反投递模板约束。",
        )

    conflicts: list[str] = []
    if "已读" in body and "已读" not in original_body_excerpt:
        conflicts.append("草稿声称已读，但原邮件上下文没有对应事实")
    # v1.0.3 改进项(personal_07/08 失配): 扩 7 个 factual 触发词
    # personal_07: "AA 退给你 50" → "退给你" + 数字
    # personal_08: "价值 500 块 免费送你" → "价值" + 数字 / "免费送" + 数字
    factual_patterns = (
        r"赔偿\s*\d+",
        r"退款\s*\d+",
        r"补偿\s*\d+",
        r"赔付\s*\d+",
        r"价值\s*\d+",
        r"退给你\s*\d+",
        r"免费送\s*\d+",
    )
    for pattern in factual_patterns:
        if re.search(pattern, body) and not re.search(pattern, original_body_excerpt):
            conflicts.append("草稿新增了原邮件未包含的具体金额承诺")
            break
    if conflicts:
        return (
            ReviewBlockReason.FACTUAL_CONFLICT,
            "",
            conflicts,
            "草稿与原邮件事实存在冲突。",
        )
    return None


class EmailReviewer:
    """邮件草稿审阅器."""

    def __init__(
        self,
        *,
        router: LLMRouter | None = None,
        max_tokens: int = 512,
        sensitive_words: frozenset[str] | None = None,
    ) -> None:
        if type(max_tokens) is not int or isinstance(max_tokens, bool) or max_tokens < 1:
            raise ValueError(f"max_tokens 必须是 int(非 bool) >= 1, 实际 {max_tokens!r}")
        if sensitive_words is not None and not isinstance(sensitive_words, frozenset):
            raise ValueError(
                f"sensitive_words 必须是 frozenset[str] 或 None, "
                f"实际 {type(sensitive_words).__name__}"
            )
        words = sensitive_words if sensitive_words is not None else _DEFAULT_SENSITIVE_WORDS
        for word in words:
            _validate_nonblank_string(word, field="sensitive_words item")
        self._router = router if router is not None else get_router()
        self._max_tokens = max_tokens
        self._sensitive_words = words
        self._stats = {
            "total": 0,
            "passed": 0,
            "review_rejected": 0,
            "business_blocked": 0,
            "response_error": 0,
            "llm_error": 0,
        }

    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    def review(
        self,
        *,
        subject: str,
        body: str,
        tone: DraftTone | str,
        email_category: EmailCategory | str,
        original_body_excerpt: str = "",
        email_id: str = "",
    ) -> ReviewResult | ReviewBlockedResult | ReviewFailureResult:
        tone_enum, category_enum = _validate_common_draft_fields(
            subject=subject,
            body=body,
            tone=tone,
            email_category=email_category,
        )
        if type(original_body_excerpt) is not str:
            raise ValueError(
                f"original_body_excerpt 必须是 str, 实际 {type(original_body_excerpt).__name__}"
            )
        if type(email_id) is not str:
            raise ValueError(f"email_id 必须是 str, 实际 {type(email_id).__name__}")

        local_block = _find_local_block(
            subject=subject,
            body=body,
            tone=tone_enum,
            email_category=category_enum,
            original_body_excerpt=original_body_excerpt,
            sensitive_words=self._sensitive_words,
        )
        self._stats["total"] += 1
        if local_block is not None:
            reason, blocked_word, issues, summary = local_block
            blocked_result = ReviewBlockedResult(
                subject=subject,
                body=body,
                tone=tone_enum,
                email_category=category_enum,
                blocked=True,
                reason=reason,
                blocked_word=blocked_word,
                flagged_issues=issues,
                review_summary=summary,
            )
            self._stats["business_blocked"] += 1
            return blocked_result

        messages = [
            {"role": "system", "content": build_system_prompt(category_enum.value)},
            build_user_message(
                subject=subject,
                body=body,
                tone=tone_enum.value,
                email_category=category_enum.value,
                original_body_excerpt=original_body_excerpt,
            ),
        ]
        try:
            response = self._router.route(
                task_type=TaskType.REVIEW,
                messages=messages,
                temperature=0.1,
                max_tokens=self._max_tokens,
            )
        except LLMError as exc:
            self._stats["llm_error"] += 1
            logger.warning(f"[reviewer] LLM 全链失败 | email_id={email_id!r} | err={exc!r}")
            return ReviewFailureResult(
                subject=subject,
                body=body,
                tone=tone_enum,
                email_category=category_enum,
                failed=True,
                last_error=str(exc) or type(exc).__name__,
                consecutive_review_failures=1,
            )

        try:
            review_passed, issues, summary = parse_review_response(response.content)
        except ReviewerResponseError as exc:
            self._stats["response_error"] += 1
            logger.warning(f"[reviewer] 响应解析失败 | email_id={email_id!r} | reason={exc.reason}")
            return ReviewFailureResult(
                subject=subject,
                body=body,
                tone=tone_enum,
                email_category=category_enum,
                failed=True,
                last_error=f"response_parse_error: {exc.reason}",
                consecutive_review_failures=1,
            )

        review_result = ReviewResult(
            subject=subject,
            body=body,
            tone=tone_enum,
            email_category=category_enum,
            review_passed=review_passed,
            flagged_issues=issues,
            review_summary=summary,
            model_full_id=response.model_full_id,
            latency_ms=response.latency_ms,
            raw_content=response.content,
        )
        self._stats["passed" if review_passed else "review_rejected"] += 1
        return review_result

    def review_batch(
        self,
        drafts: list[dict[str, Any]],
    ) -> list[ReviewResult | ReviewBlockedResult | ReviewFailureResult | ValueError | KeyError]:
        if not isinstance(drafts, list):
            raise ValueError(f"drafts 必须是 list, 实际 {type(drafts).__name__}")
        results: list[
            ReviewResult | ReviewBlockedResult | ReviewFailureResult | ValueError | KeyError
        ] = []
        for index, draft in enumerate(drafts):
            if not isinstance(draft, dict):
                results.append(
                    ValueError(f"drafts[{index}] 必须是 dict, 实际 {type(draft).__name__}")
                )
                continue
            missing = [
                key for key in ("subject", "body", "tone", "email_category") if key not in draft
            ]
            if missing:
                results.append(KeyError(f"drafts[{index}] 缺字段 {missing}"))
                continue
            try:
                results.append(
                    self.review(
                        subject=draft["subject"],
                        body=draft["body"],
                        tone=draft["tone"],
                        email_category=draft["email_category"],
                        original_body_excerpt=draft.get("original_body_excerpt", ""),
                        email_id=draft.get("email_id", ""),
                    )
                )
            except ValueError as exc:
                results.append(exc)
        return results


__all__ = [
    "EmailReviewer",
    "EmailCategory",
    "ReviewBlockReason",
    "ReviewBlockedResult",
    "ReviewFailureResult",
    "ReviewResult",
    "ReviewerError",
    "ReviewerResponseError",
    "has_markdown_fence",
    "parse_review_response",
]
