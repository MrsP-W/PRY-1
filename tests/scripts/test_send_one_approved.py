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
    - `--recipient` 只能是一个 envelope 地址；逗号/分号/多 @/换行等
      多收件人或 header 注入形态必须 fail-closed

  P0 审批顺序(撞坑 #85):
    - 收件人不匹配时拒批,不写 APPROVED
    - 收件人匹配后才写 APPROVED
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from my_ai_employee.core.outbox import OutboxStatus  # noqa: E402
from scripts import send_one_approved  # noqa: E402
from scripts.send_one_approved import (  # noqa: E402
    _CONFIRM_PHRASE,
    _recipient_matches,
    _validate_gate,
    main,
)

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

    @pytest.mark.parametrize(
        "recipient",
        [
            "alice@qq.com,evil@qq.com",
            "alice@qq.com;evil@qq.com",
            "alice@@qq.com",
            "@qq.com",
            "alice@",
            "alice @qq.com",
            "alice@qq.com\r\nBcc: evil@qq.com",
        ],
    )
    def test_gate_rejects_non_single_envelope_recipient(
        self, monkeypatch: pytest.MonkeyPatch, recipient: str
    ) -> None:
        """真实外发门控只接受一个无注入字符的 envelope 地址。"""
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com")
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient=recipient)
        assert err is not None
        assert "单一" in err

    def test_subdomain_not_matched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """子域名不匹配(mail.qq.com 不在 "qq.com" 白名单).

        设计: 严判完整 domain,避免 attacker 注册 mail.qq.com.attacker.com 绕过。
        """
        monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
        monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com")
        err = _validate_gate(confirm=_CONFIRM_PHRASE, recipient="alice@mail.qq.com")
        assert err is not None
        assert "mail.qq.com" in err


# ===== P0 审批顺序(撞坑 #85: 先校验收件人再写 APPROVED) =====


def test_recipient_matches_case_insensitive() -> None:
    assert _recipient_matches("Alice@QQ.COM", "alice@qq.com")
    assert not _recipient_matches("root@systemmail.yunwu.ai", "you@qq.com")


@pytest.mark.parametrize(
    ("outbox_recipient", "whitelist_recipient"),
    [
        ("alice@qq.com,evil@qq.com", "alice@qq.com,evil@qq.com"),
        ("alice@qq.com", "alice@qq.com;evil@qq.com"),
        ("alice@qq.com\r\nBcc: evil@qq.com", "alice@qq.com"),
    ],
)
def test_recipient_matches_rejects_non_single_envelope_addresses(
    outbox_recipient: str, whitelist_recipient: str
) -> None:
    """审批前的精确匹配也不得接受多收件人或 header 注入形态。"""
    assert not _recipient_matches(outbox_recipient, whitelist_recipient)


def _make_pending_entry(*, recipient: str) -> MagicMock:
    entry = MagicMock()
    entry.id = 42
    entry.email_id = 11
    entry.status = OutboxStatus.PENDING_SEND.value
    entry.recipient_email = recipient
    return entry


def _run_main_with_mock_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pending: MagicMock,
    whitelist_recipient: str,
) -> tuple[int, MagicMock]:
    monkeypatch.setenv("SMTP_REAL_NETWORK", "1")
    monkeypatch.setenv("SEND_REAL_NETWORK_RECIPIENT_DOMAINS", "qq.com")

    store = MagicMock()
    store.by_status.side_effect = lambda status, limit=1: (
        [pending] if status == OutboxStatus.PENDING_SEND.value else []
    )

    mock_db = MagicMock()
    dispatcher_result = MagicMock(
        total_picked=0,
        sent=0,
        technical_failed=0,
        business_blocked=0,
    )
    with (
        patch.object(send_one_approved, "Database") as mock_db_cls,
        patch.object(send_one_approved, "make_sqlalchemy_engine"),
        patch.object(send_one_approved, "OutboxStore", return_value=store),
        patch.object(
            send_one_approved.keychain,
            "get_smtp_password_for_provider",
            return_value=MagicMock(ok=True, value="smtp-pwd"),
        ),
        patch.object(send_one_approved, "OutboxDispatcher") as mock_dispatcher_cls,
    ):
        mock_db_cls.open.return_value = mock_db
        mock_dispatcher_cls.return_value.run_once.return_value = dispatcher_result
        rc = main(
            [
                "--recipient",
                whitelist_recipient,
                "--confirm",
                _CONFIRM_PHRASE,
                "--smtp-username",
                "sender@qq.com",
            ]
        )
    return rc, store


def test_main_rejects_mismatch_before_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """撞坑 #85: outbox 收件人与 --recipient 不符 → 拒批,不写 APPROVED."""
    pending = _make_pending_entry(recipient="root@systemmail.yunwu.ai")
    rc, store = _run_main_with_mock_store(
        monkeypatch,
        pending=pending,
        whitelist_recipient="you@qq.com",
    )
    assert rc == 1
    store.update_status.assert_not_called()


def test_main_approves_only_after_recipient_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """收件人匹配后才写 APPROVED."""
    pending = _make_pending_entry(recipient="you@qq.com")
    rc, store = _run_main_with_mock_store(
        monkeypatch,
        pending=pending,
        whitelist_recipient="you@QQ.COM",
    )
    assert rc == 2
    store.update_status.assert_called_once()
    kwargs = store.update_status.call_args.kwargs
    assert kwargs["new_status"] == OutboxStatus.APPROVED.value
    assert kwargs["from_status"] == OutboxStatus.PENDING_SEND.value
    assert kwargs["last_approved_at_ms"] is not None


def test_main_rejects_multi_recipient_before_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 CLI 边界：多收件人即使尾域白名单命中也不得进入审批。"""
    pending = _make_pending_entry(recipient="you@qq.com,evil@qq.com")
    rc, store = _run_main_with_mock_store(
        monkeypatch,
        pending=pending,
        whitelist_recipient="you@qq.com,evil@qq.com",
    )
    assert rc == 1
    store.update_status.assert_not_called()
