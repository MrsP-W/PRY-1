"""D4.7.2 v1.0.3 P2-1 — ai 顶层包导出测试.

验证 `my_ai_employee.ai.__all__` 同步导出 v1.0.2 新增的
SpamBlockedError + DraftBlockedResult, 顶层导入可成功。
"""


class TestAIPackageExportsV103:
    """6/9 v1.0.3 P2-1 修复: ai.__all__ 同步 v1.0.2 新增公共类型."""

    def test_spam_blocked_error_top_level_importable(self) -> None:
        """SpamBlockedError 顶层导入可成功(不在 __all__ → ImportError)."""
        from my_ai_employee.ai import SpamBlockedError  # noqa: F401

        assert SpamBlockedError is not None

    def test_draft_blocked_result_top_level_importable(self) -> None:
        """DraftBlockedResult 顶层导入可成功(不在 __all__ → ImportError)."""
        from my_ai_employee.ai import DraftBlockedResult  # noqa: F401

        assert DraftBlockedResult is not None

    def test_spam_blocked_error_in_all(self) -> None:
        """SpamBlockedError 必须在 __all__ 中(否则 importlib 顶层导入会失败)."""
        import my_ai_employee.ai as ai_pkg

        assert "SpamBlockedError" in ai_pkg.__all__

    def test_draft_blocked_result_in_all(self) -> None:
        """DraftBlockedResult 必须在 __all__ 中."""
        import my_ai_employee.ai as ai_pkg

        assert "DraftBlockedResult" in ai_pkg.__all__

    def test_spam_blocked_error_is_drafter_error_subclass(self) -> None:
        """SpamBlockedError 继承自 DrafterError(便于上层 catch 业务异常统一处理)."""
        from my_ai_employee.ai import DrafterError, SpamBlockedError

        assert issubclass(SpamBlockedError, DrafterError)

    def test_draft_blocked_result_has_5_fields(self) -> None:
        """DraftBlockedResult 必含 5 字段(subject/body/tone/reason/original_email_category)."""
        from my_ai_employee.ai import DraftBlockedResult, DraftTone

        result = DraftBlockedResult(
            subject="(DRAFT-NO-REPLY) [SPAM] s",
            body="建议: 不回复",
            tone=DraftTone.FORMAL,
            reason="spam_business_blocked",
            original_email_category="SPAM",
        )
        d = result.to_dict()
        assert d["subject"] == "(DRAFT-NO-REPLY) [SPAM] s"
        assert d["body"] == "建议: 不回复"
        assert d["tone"] == "FORMAL"
        assert d["reason"] == "spam_business_blocked"
        assert d["original_email_category"] == "SPAM"
        assert d["blocked"] is True  # 显式标记, 上层可识别"阻断产物 vs LLM 产物"
