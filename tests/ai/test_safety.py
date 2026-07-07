"""D14+ LLM 草稿安全护栏(撞坑 #85 Layer 1)单元测试.

覆盖:

  is_system_sender:
    - 撞坑 #85 案例: root@systemmail.yunwu.ai → True
    - noreply / no-reply / admin / postmaster / system 等 system-style 本地名
    - 大小写不敏感(Root@ / ROOT@)
    - "Name <a@b.com>" 嵌套格式(只取 <> 内部分)
    - 普通用户邮箱 → False
    - 空字符串 / 无 @ 输入 → False
    - type 错 → ValueError

  is_obvious_spam:
    - 系统发件人无条件短路(撞坑 #85 案例)
    - 主题黑名单词 + body 极短(< 30 字符)双信号命中
    - 主题黑名单词 + body 长(> 30 字符) → 不命中(避免误杀真实 URGENT 邮件)
    - 普通邮件 → False
    - 中英文主题黑名单词都命中
    - type 错 → ValueError(任一参数)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ===== is_system_sender 测试 =====


class TestIsSystemSender:
    """is_system_sender 纯函数测试(撞坑 #85 Layer 1)."""

    def test_root_at_systemmail_yunwu_ai_returns_true(self) -> None:
        """撞坑 #85 案例: root@systemmail.yunwu.ai → True."""
        from my_ai_employee.ai.safety import is_system_sender

        assert is_system_sender("root@systemmail.yunwu.ai") is True

    @pytest.mark.parametrize(
        "localpart",
        [
            "root",
            "noreply",
            "no-reply",
            "admin",
            "postmaster",
            "abuse",
            "system",
            "support",
            "alerts",
            "notifications",
            "info",
            "help",
            "operations",
            "ops",
            "service",
        ],
    )
    def test_all_system_style_localparts_return_true(self, localpart: str) -> None:
        """冻结黑名单常量全部命中."""
        from my_ai_employee.ai.safety import is_system_sender

        assert is_system_sender(f"{localpart}@example.com") is True

    def test_case_insensitive(self) -> None:
        """大小写不敏感."""
        from my_ai_employee.ai.safety import is_system_sender

        assert is_system_sender("Root@example.com") is True
        assert is_system_sender("ROOT@EXAMPLE.COM") is True
        assert is_system_sender("Noreply@Example.Com") is True

    def test_nested_name_email_format_extracts_inner(self) -> None:
        """ "Name <a@b.com>" 嵌套格式只取 <> 内部分."""
        from my_ai_employee.ai.safety import is_system_sender

        # 即使外包 "Server Team <root@example.com>" 也要识别
        assert is_system_sender("Server Team <root@example.com>") is True
        # 普通用户嵌套格式
        assert is_system_sender("Alice <alice@example.com>") is False

    def test_normal_user_email_returns_false(self) -> None:
        """普通用户邮箱 → False."""
        from my_ai_employee.ai.safety import is_system_sender

        assert is_system_sender("alice@example.com") is False
        assert is_system_sender("bob.test@gmail.com") is False
        assert is_system_sender("user.name+tag@qq.com") is False

    def test_empty_string_returns_false(self) -> None:
        """空字符串 → False(不应抛错)."""
        from my_ai_employee.ai.safety import is_system_sender

        assert is_system_sender("") is False

    def test_no_at_sign_returns_false(self) -> None:
        """无 @ 输入 → False(不应抛错,容错)."""
        from my_ai_employee.ai.safety import is_system_sender

        assert is_system_sender("not_an_email") is False

    def test_type_error_raises_value_error(self) -> None:
        """type 错 → ValueError(沿 D4.4 P1 范本)."""
        from my_ai_employee.ai.safety import is_system_sender

        with pytest.raises(ValueError, match="sender 必须是 str"):
            is_system_sender(b"root@example.com")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="sender 必须是 str"):
            is_system_sender(123)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="sender 必须是 str"):
            is_system_sender(None)  # type: ignore[arg-type]


# ===== is_obvious_spam 测试 =====


class TestIsObviousSpam:
    """is_obvious_spam 纯函数测试(撞坑 #85 Layer 1 分类器短路)."""

    def test_root_systemmail_returns_true_unconditional(self) -> None:
        """撞坑 #85 案例: system sender 不管主题/正文,无条件返 True."""
        from my_ai_employee.ai.safety import is_obvious_spam

        assert (
            is_obvious_spam(
                sender="root@systemmail.yunwu.ai",
                subject="[紧急] 客户投诉",
                body_excerpt="订单 #1234 严重延迟,客户要求 24h 退款",
            )
            is True
        )

    def test_noreply_with_normal_subject_returns_true(self) -> None:
        """noreply + 普通主题 → True(典型批量通知/营销 spam)."""
        from my_ai_employee.ai.safety import is_obvious_spam

        assert (
            is_obvious_spam(
                sender="noreply@newsletter.example.com",
                subject="本周热门文章推荐",
                body_excerpt="点击查看本周精选...",
            )
            is True
        )

    @pytest.mark.parametrize(
        "subject",
        [
            "[紧急] 需立即处理事项",  # 撞坑 #85 案例
            "API 服务异常需立即处理",  # 撞坑 #85 案例
            "您的账户异常登录",
            "Verify your account",  # phishing
            "URGENT: Account suspended",  # phishing
            "立即修复系统异常",
            "[安全告警] 密码过期",
        ],
    )
    def test_spam_keyword_with_empty_body_returns_true(self, subject: str) -> None:
        """主题黑名单词 + body 空 → True."""
        from my_ai_employee.ai.safety import is_obvious_spam

        assert (
            is_obvious_spam(
                sender="someone@example.com",
                subject=subject,
                body_excerpt="",
            )
            is True
        )

    @pytest.mark.parametrize(
        "subject",
        [
            "[紧急] 客户投诉",
            "API 服务异常需立即处理",
            "您的账户异常登录",
        ],
    )
    def test_spam_keyword_with_long_body_returns_false(self, subject: str) -> None:
        """主题黑名单词 + body 长(> 30 字符) → 不命中。

        防御"客户紧急投诉"等真实 URGENT 邮件被误杀(撞坑 #85 设计原则:
        双信号防误杀,真实 URGENT 通常 body > 30 字符)。
        """
        from my_ai_employee.ai.safety import is_obvious_spam

        long_body = "订单 #1234 严重延迟超过 24 小时,客户已多次催促退款,请相关同事立即介入处理。"
        assert len(long_body) >= 30  # 测试假设
        assert (
            is_obvious_spam(
                sender="client@partner.example.com",
                subject=subject,
                body_excerpt=long_body,
            )
            is False
        )

    def test_normal_email_returns_false(self) -> None:
        """普通邮件 → False."""
        from my_ai_employee.ai.safety import is_obvious_spam

        assert (
            is_obvious_spam(
                sender="alice@example.com",
                subject="下周项目评审会议",
                body_excerpt="我们下周三下午 2 点开项目评审会,请准备相关材料。",
            )
            is False
        )

    def test_whitespace_body_counts_as_empty(self) -> None:
        """body 全空白 → 视为空(撞坑 #85 案例 body 真空)."""
        from my_ai_employee.ai.safety import is_obvious_spam

        assert (
            is_obvious_spam(
                sender="someone@example.com",
                subject="[紧急] 系统异常",
                body_excerpt="   \n\n  ",
            )
            is True
        )

    @pytest.mark.parametrize(
        "wrong_arg",
        [
            {"sender": 123},
            {"subject": b"bytes"},
            {"body_excerpt": None},
        ],
    )
    def test_type_error_raises_value_error(self, wrong_arg: dict[str, object]) -> None:
        """任一参数 type 错 → ValueError(沿 D4.4 P1 范本)."""
        from my_ai_employee.ai.safety import is_obvious_spam

        # 默认 3 个合法参数 + 一个错
        kwargs: dict[str, object] = {
            "sender": "a@b.com",
            "subject": "ok",
            "body_excerpt": "ok",
        }
        kwargs.update(wrong_arg)
        with pytest.raises(ValueError, match="必须是 str"):
            is_obvious_spam(**kwargs)  # type: ignore[arg-type]


# ===== 常量测试(冻结保证)=====


class TestFrozenConstants:
    """黑名单常量冻结保证(防止运行时被改)."""

    def test_system_sender_localparts_is_frozenset(self) -> None:
        """_SYSTEM_SENDER_LOCALPARTS 必须是 frozenset(冻结)."""
        from my_ai_employee.ai import safety

        assert isinstance(safety._SYSTEM_SENDER_LOCALPARTS, frozenset)

    def test_obvious_spam_keywords_is_tuple(self) -> None:
        """_OBVIOUS_SPAM_SUBJECT_KEYWORDS 必须是 tuple(冻结)."""
        from my_ai_employee.ai import safety

        assert isinstance(safety._OBVIOUS_SPAM_SUBJECT_KEYWORDS, tuple)

    def test_system_sender_contains_root(self) -> None:
        """撞坑 #85 案例 root@ 必须在黑名单内."""
        from my_ai_employee.ai import safety

        assert "root" in safety._SYSTEM_SENDER_LOCALPARTS

    def test_obvious_spam_contains_urgent_keyword(self) -> None:
        """撞坑 #85 案例"紧急"必须在主题黑名单内."""
        from my_ai_employee.ai import safety

        assert "紧急" in safety._OBVIOUS_SPAM_SUBJECT_KEYWORDS
