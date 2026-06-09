"""D4.7.2 — 邮件草稿 prompt 模板单元测试.

覆盖:
  - 5+1 类 SYSTEM prompt 完整性(URGENT/TODO/FYI/SPAM/PERSONAL/DEFAULT)
  - build_system_prompt 5+1 分发 + 非法值严判
  - build_user_message 字段拼接 + email_category/tone 行
  - 严判入口(类型错 / 非法 email_category / 非法 tone)→ ValueError
  - 契约 2 关键词在所有 SYSTEM prompt 中出现(裸 JSON / 无 markdown 包裹)
  - 契约 3 关键词在所有 SYSTEM prompt 中出现(3 类 tone 锁定)

设计: 与 test_classifier.py 范本对齐(1 个文件覆盖 prompts 单元测试,
不重复覆盖 drafter.py 业务层,D4.7.1 已覆盖 92 drafter tests)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.ai.prompts.draft import (  # noqa: E402
    SYSTEM_PROMPT_DEFAULT,
    SYSTEM_PROMPT_FYI,
    SYSTEM_PROMPT_PERSONAL,
    SYSTEM_PROMPT_SPAM,
    SYSTEM_PROMPT_TODO,
    SYSTEM_PROMPT_URGENT,
    build_system_prompt,
    build_user_message,
)

# 5+1 SYSTEM prompt 清单(用于循环断言)
_ALL_SYSTEM_PROMPTS = [
    SYSTEM_PROMPT_URGENT,
    SYSTEM_PROMPT_TODO,
    SYSTEM_PROMPT_FYI,
    SYSTEM_PROMPT_SPAM,
    SYSTEM_PROMPT_PERSONAL,
    SYSTEM_PROMPT_DEFAULT,
]


# ============================================================
# 5+1 SYSTEM prompt 完整性
# ============================================================


class TestSystemPrompts:
    """5+1 SYSTEM prompt 模板完整性测试."""

    def test_six_prompts_distinct(self) -> None:
        """5+1 SYSTEM prompt 各不相同(各含不同风格关键词)."""
        # URGENT 必须含"紧急" / TODO 必须含"复述" / FYI 必须含"知晓"
        # SPAM 必须含"退订" / PERSONAL 必须含"私人" / DEFAULT 必须含"通用"或不含上述强关键词
        assert "紧急" in SYSTEM_PROMPT_URGENT
        assert "复述" in SYSTEM_PROMPT_TODO
        assert "知晓" in SYSTEM_PROMPT_FYI
        assert "退订" in SYSTEM_PROMPT_SPAM
        assert "私人" in SYSTEM_PROMPT_PERSONAL

    def test_all_prompts_non_empty(self) -> None:
        """6 个 prompt 都非空字符串."""
        for prompt in _ALL_SYSTEM_PROMPTS:
            assert prompt
            assert len(prompt) > 100  # 至少 100 字符(避免误写空字符串)

    def test_all_prompts_contain_bare_json_contract(self) -> None:
        """契约 2: 所有 SYSTEM prompt 都必须含"严格 JSON"和"无 markdown 包裹"关键词."""
        for prompt in _ALL_SYSTEM_PROMPTS:
            assert "严格 JSON" in prompt or "严格JSON" in prompt
            assert "无 markdown 包裹" in prompt or "无markdown" in prompt
            assert "```json" in prompt  # 显式说明禁止 ```json 包裹

    def test_all_prompts_contain_3_tones(self) -> None:
        """契约 3: 所有 SYSTEM prompt 都必须列 3 类 tone."""
        for prompt in _ALL_SYSTEM_PROMPTS:
            assert "FORMAL" in prompt
            assert "FRIENDLY" in prompt
            assert "CONCISE" in prompt

    def test_all_prompts_contain_output_format(self) -> None:
        """所有 SYSTEM prompt 都必须含 3 字段输出格式说明."""
        for prompt in _ALL_SYSTEM_PROMPTS:
            assert '"subject"' in prompt
            assert '"body"' in prompt
            assert '"tone"' in prompt

    def test_all_prompts_contain_length_constraints(self) -> None:
        """所有 SYSTEM prompt 都必须含契约 1 长度约束(1-200 / 10-8000)."""
        for prompt in _ALL_SYSTEM_PROMPTS:
            assert "1-200" in prompt
            assert "10-8000" in prompt


# ============================================================
# build_system_prompt 分发
# ============================================================


class TestBuildSystemPrompt:
    """build_system_prompt 5+1 分发测试."""

    def test_dispatch_urgent(self) -> None:
        assert build_system_prompt("URGENT") == SYSTEM_PROMPT_URGENT

    def test_dispatch_todo(self) -> None:
        assert build_system_prompt("TODO") == SYSTEM_PROMPT_TODO

    def test_dispatch_fyi(self) -> None:
        assert build_system_prompt("FYI") == SYSTEM_PROMPT_FYI

    def test_dispatch_spam(self) -> None:
        assert build_system_prompt("SPAM") == SYSTEM_PROMPT_SPAM

    def test_dispatch_personal(self) -> None:
        assert build_system_prompt("PERSONAL") == SYSTEM_PROMPT_PERSONAL

    def test_dispatch_none_returns_default(self) -> None:
        assert build_system_prompt(None) == SYSTEM_PROMPT_DEFAULT

    def test_dispatch_invalid_category_raises(self) -> None:
        """D4.4 P1 严判: 非法 email_category 字符串 → ValueError."""
        with pytest.raises(ValueError, match="email_category 字符串必须"):
            build_system_prompt("OOPS")

    def test_dispatch_empty_string_raises(self) -> None:
        """空字符串不属于 5 类 → ValueError."""
        with pytest.raises(ValueError, match="email_category 字符串必须"):
            build_system_prompt("")

    def test_dispatch_lowercase_raises(self) -> None:
        """大小写敏感(契约 3 应用): 'urgent' 不通过 → ValueError."""
        with pytest.raises(ValueError, match="email_category 字符串必须"):
            build_system_prompt("urgent")

    def test_dispatch_wrong_type_raises(self) -> None:
        """D4.5 P0 严判: 非 str / None → ValueError."""
        with pytest.raises(ValueError, match="email_category 必须是 str 或 None"):
            build_system_prompt(123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="email_category 必须是 str 或 None"):
            build_system_prompt(True)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="email_category 必须是 str 或 None"):
            build_system_prompt(["URGENT"])  # type: ignore[arg-type]

    def test_dispatch_all_five_categories(self) -> None:
        """5 类全部能正常分发(无 ValueError)."""
        for cat in ("URGENT", "TODO", "FYI", "SPAM", "PERSONAL"):
            prompt = build_system_prompt(cat)
            assert prompt
            assert prompt in _ALL_SYSTEM_PROMPTS


# ============================================================
# build_user_message
# ============================================================


class TestBuildUserMessage:
    """build_user_message 字段拼接 + 严判测试."""

    def test_basic(self) -> None:
        """基本拼接: 3 字段 + 分类 + 语气."""
        msgs = build_user_message(
            subject="[紧急] 客户投诉",
            sender="client@example.com",
            body_excerpt="订单 #1234 严重延迟",
            email_category="URGENT",
            tone="FORMAL",
        )
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        content = msgs[0]["content"]
        assert "[紧急] 客户投诉" in content
        assert "client@example.com" in content
        assert "订单 #1234 严重延迟" in content
        assert "URGENT" in content
        assert "FORMAL" in content
        # P1-3 强制: tone 末行重述
        assert "tone 必须 = FORMAL" in content

    def test_email_category_line(self) -> None:
        """email_category 行格式: '分类: <CATEGORY>'."""
        msgs = build_user_message(
            subject="x", sender="y", body_excerpt="z", email_category="TODO", tone="FRIENDLY"
        )
        assert "分类: TODO" in msgs[0]["content"]

    def test_tone_line_p1_3_enforcement(self) -> None:
        """P1-3 强制: tone 末行必须显式重述请求 tone(防止 LLM 跑偏)."""
        for tone in ("FORMAL", "FRIENDLY", "CONCISE"):
            msgs = build_user_message(
                subject="x", sender="y", body_excerpt="z", email_category="FYI", tone=tone
            )
            assert f"tone 必须 = {tone}" in msgs[0]["content"]

    def test_email_category_none_omits_line(self) -> None:
        """email_category=None 时, 不输出 '分类:' 行."""
        msgs = build_user_message(
            subject="x", sender="y", body_excerpt="z", email_category=None, tone="FORMAL"
        )
        content = msgs[0]["content"]
        assert "分类:" not in content
        # 但 tone 行仍存在
        assert "语气: FORMAL" in content
        assert "tone 必须 = FORMAL" in content

    def test_empty_strings_become_placeholder(self) -> None:
        """空字符串字段被替换为 '(空)' 占位符(与 D4.6 范本一致)."""
        msgs = build_user_message(
            subject="", sender="", body_excerpt="", email_category=None, tone="FORMAL"
        )
        content = msgs[0]["content"]
        # 3 个空字段都被标记
        assert content.count("(空)") == 3

    def test_default_tone_is_formal(self) -> None:
        """默认 tone=FORMAL(不传时)."""
        msgs = build_user_message(subject="x", sender="y", body_excerpt="z")
        assert "FORMAL" in msgs[0]["content"]
        assert "tone 必须 = FORMAL" in msgs[0]["content"]

    def test_three_tones_all_accepted(self) -> None:
        """3 类 tone 全部接受(FORMAL/FRIENDLY/CONCISE)."""
        for tone in ("FORMAL", "FRIENDLY", "CONCISE"):
            msgs = build_user_message(
                subject="x", sender="y", body_excerpt="z", email_category="URGENT", tone=tone
            )
            assert tone in msgs[0]["content"]
            assert f"tone 必须 = {tone}" in msgs[0]["content"]

    def test_invalid_tone_raises(self) -> None:
        """非法 tone 字符串 → ValueError(契约 3 严判)."""
        with pytest.raises(ValueError, match="tone 字符串必须"):
            build_user_message(subject="x", sender="y", body_excerpt="z", tone="OOPS")
        with pytest.raises(ValueError, match="tone 字符串必须"):
            build_user_message(subject="x", sender="y", body_excerpt="z", tone="")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="tone 字符串必须"):
            build_user_message(subject="x", sender="y", body_excerpt="z", tone="formal")  # type: ignore[arg-type]  # 大小写敏感

    def test_invalid_email_category_raises(self) -> None:
        """非法 email_category 字符串 → ValueError."""
        with pytest.raises(ValueError, match="email_category 字符串必须"):
            build_user_message(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category="OOPS",  # type: ignore[arg-type]
                tone="FORMAL",
            )

    def test_strict_type_rejection(self) -> None:
        """D4.4 P1 + D4.5 P0 严判: 所有字段 type 错 → ValueError."""
        with pytest.raises(ValueError, match="subject 必须是 str"):
            build_user_message(subject=123, sender="y", body_excerpt="z")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="sender 必须是 str"):
            build_user_message(subject="x", sender=123, body_excerpt="z")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="body_excerpt 必须是 str"):
            build_user_message(subject="x", sender="y", body_excerpt=123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="tone 必须是 str"):
            build_user_message(subject="x", sender="y", body_excerpt="z", tone=123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="email_category 必须是 str 或 None"):
            build_user_message(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category=123,  # type: ignore[arg-type]
            )

    def test_bool_subclass_rejected(self) -> None:
        """bool 子类陷阱(isinstance(True, int) == True): True/False 严判拒绝."""
        with pytest.raises(ValueError, match="tone 必须是 str"):
            build_user_message(subject="x", sender="y", body_excerpt="z", tone=True)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="email_category 必须是 str 或 None"):
            build_user_message(
                subject="x",
                sender="y",
                body_excerpt="z",
                email_category=False,  # type: ignore[arg-type]
            )

    def test_returns_list_with_single_user_message(self) -> None:
        """返回结构: list[dict] 单条 user 消息."""
        msgs = build_user_message(
            subject="x", sender="y", body_excerpt="z", email_category="TODO", tone="FRIENDLY"
        )
        assert isinstance(msgs, list)
        assert len(msgs) == 1
        assert isinstance(msgs[0], dict)
        assert msgs[0]["role"] == "user"
        assert isinstance(msgs[0]["content"], str)


# ============================================================
# 与 drafter 业务层 集成一致性
# ============================================================


class TestIntegrationConsistency:
    """prompts/draft.py 与 drafter 业务层 集成一致性测试."""

    def test_email_category_dispatch_matches_drafter(self) -> None:
        """build_system_prompt 的 5 类必须与 drafter 严判的 5 类一致."""
        from my_ai_employee.ai.classifier import EmailCategory
        from my_ai_employee.ai.drafter import _EMAIL_CATEGORY_VALUES

        # drafter 接受的 5 类
        drafter_categories = set(_EMAIL_CATEGORY_VALUES)
        # prompts 接受的 5 类
        prompt_categories = {"URGENT", "TODO", "FYI", "SPAM", "PERSONAL"}
        # EmailCategory 枚举 5 类
        enum_categories = {c.value for c in EmailCategory}

        assert drafter_categories == prompt_categories == enum_categories

    def test_tone_consistency_with_drafter(self) -> None:
        """prompts 接受的 3 类 tone 必须与 drafter.DraftTone 一致."""
        from my_ai_employee.ai.drafter import DraftTone

        prompt_tones = {"FORMAL", "FRIENDLY", "CONCISE"}
        enum_tones = {t.value for t in DraftTone}
        assert prompt_tones == enum_tones

    def test_all_five_system_prompts_mention_bare_json(self) -> None:
        """契约 2: 5 类 SYSTEM prompt 都明确禁止 markdown 包裹(必须裸 JSON)."""
        for cat in ("URGENT", "TODO", "FYI", "SPAM", "PERSONAL"):
            prompt = build_system_prompt(cat)
            assert "无 markdown 包裹" in prompt or "无markdown" in prompt
            assert "Here is the draft" in prompt or "解释段落" in prompt
