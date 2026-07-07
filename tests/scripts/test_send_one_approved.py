"""send_one_approved.py — SMTP 真发门控单元测试.

覆盖:

  _validate_gate 基础门控:
    - 无 SMTP_REAL_NETWORK env → 拒
    - confirm 错 → 拒
    - recipient 缺 @ → 拒

  撞坑 #85 Layer 3 domain 白名单门控(D13.x P3 修复):
    - 默认(无 SEND_REAL_NETWORK_RECIPIENT_DOMAINS env)= 拒所有
    - 设白名单 + recipient domain 在内 → 通过
    - 设白名单 + recipient domain 不在内 → 拒
    - 设空白白名单(env="" 或 "  ,  ")→ 视为未设,拒
    - 大小写不敏感(recipient "A@QQ.COM" 匹配白名单 "qq.com")
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.send_one_approved import _CONFIRM_PHRASE, _validate_gate  # noqa: E402

# ===== 基础门控(撞坑 #76 防审批伪造范本)=====


def test_gate_rejects_without_smtp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 SMTP_REAL_NETWORK env → 拒."""
    monkeypatch.delenv("SMTP_REAL_NETWORK", raising=False)
    monkeypatch.delenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", raising=False)
    err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@qq.com")
    assert err is not None
    assert "SMTP_REAL_NETWORK=1" in err


def test_gate_rejects_wrong_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    """confirm 短语错 → 拒."""
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com")
    err = _validate_gate(confirm="wrong-phrase", recipient="alice@qq.com")
    assert err is not None
    assert _CONFIRM_PHRASE in err


def test_gate_rejects_missing_at_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    """recipient 缺 @ → 拒."""
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com")
    err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="not_an_email")
    assert err is not None
    assert "@" in err


# ===== 撞坑 #85 Layer 3 domain 白名单门控 =====


class TestPitfall85Layer3DomainWhitelist:
    """撞坑 #85 Layer 3: SEND_REAL_NETWORK_RECIPIENT_DOMAINS env 白名单.

    设计动机:
      - 撞坑 #85 暴露 LLM 幻觉陌生 domain(yunwu.ai)的真实外发风险
      - Layer 1+2 已拦 spam sender,但 process_inbox 流程仍可能产生"普通 sender
        + LLM 幻觉 email address"的草稿
      - Layer 3 是最后一道门:用户必须显式列出允许外发的 domain 列表
      - 默认(无 env)→ 拒所有外发(撞坑 #85 暴露后最安全策略)
    """

    def test_default_no_env_rejects_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """默认(无 SEND_REAL_NETWORK_RECIPIENT_DOMAINS env)→ 拒所有外发."""
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.delenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", raising=False)
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@qq.com")
        assert err is not None
        assert "SEND_REAL_NETWORK_RECIPIENT_DOMAINS" in err
        assert "撞坑 #85 Layer 3" in err

    def test_empty_env_rejects_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 空字符串 → 拒(视为未设)."""
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "")
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@qq.com")
        assert err is not None
        assert "SEND_REAL_NETWORK_RECIPIENT_DOMAINS" in err

    def test_whitespace_only_env_rejects_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 仅空白/逗号 → 拒(白名单实质为空)."""
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "  ,  ,  ")
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@qq.com")
        assert err is not None

    def test_whitelist_with_matching_domain_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """白名单含 recipient domain → 通过."""
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com,example.com")
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@qq.com")
        assert err is None

    def test_whitelist_with_non_matching_domain_rejects(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """白名单不含 recipient domain → 拒(撞坑 #85 防御点)."""
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com,example.com")
        # 撞坑 #85 案例: root@systemmail.yunwu.ai 应该在拒收
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="root@systemmail.yunwu.ai")
        assert err is not None
        assert "yunwu.ai" in err
        assert "白名单" in err

    def test_case_insensitive_domain_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """domain 大小写不敏感(recipient "A@QQ.COM" 匹配白名单 "qq.com")."""
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com")
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@QQ.COM")
        assert err is None

    def test_case_insensitive_whitelist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """白名单 domain 大小写不敏感(env "QQ.com" 匹配 recipient "alice@qq.com")."""
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "QQ.com")
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@qq.com")
        assert err is None

    def test_subdomain_not_matched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """子域名不匹配(mail.qq.com 不在 "qq.com" 白名单).

        设计: 严判完整 domain,避免 attacker 注册 mail.qq.com.attacker.com 绕过。
        """
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com")
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@mail.qq.com")
        assert err is not None
        assert "mail.qq.com" in err
