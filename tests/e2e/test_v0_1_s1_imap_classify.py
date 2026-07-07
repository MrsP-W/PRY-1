"""S1 — 新邮件到达 → IMAP 轮询 → 分类(Week 1 路径).

承接 docs/v0.1-launch-plan.md:216 S1 唯一编号表行。

D6.0 范围(2026-06-14 启动):
    - 10 封 faker 邮件(MockIMAPClient 注入,无真实 socket)
    - IMAPConnector.fetch 拉邮件 → list[dict[Any, Any]](沿 D2.7 safe_fetch 范本)
    - EmailClassifierAdapter.classify_and_emit 入口契约(不调真实 LLM,Mock router)
    - 断言:10 封全拉 + source 字段齐 + 与 5 类一致

跑法:
    pytest tests/e2e/test_v0_1_s1_imap_classify.py -v
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _make_envelope(uid: int, subject: str, sender: str) -> dict[Any, Any]:
    """构造 imapclient Envelope 兼容的 dict[Any, Any](MockIMAPClient.fetch_data 格式).

    imapclient 3.x Envelope 完整字段(11 个):
        date, subject:bytes, from_, sender, reply_to, to, cc, bcc, in_reply_to:bytes, message_id:bytes
    """
    from imapclient.response_types import Address, Envelope

    return {
        b"ENVELOPE": Envelope(
            date=datetime(2026, 6, 14, 9, 0, 0, tzinfo=UTC),
            subject=subject.encode("utf-8"),
            from_=(
                Address(
                    name=b"",
                    route=None,
                    mailbox=sender.split("@")[0].encode("utf-8"),
                    host=sender.split("@")[1].encode("utf-8"),
                ),
            ),
            sender=None,
            reply_to=None,
            to=None,
            cc=None,
            bcc=None,
            in_reply_to=b"",
            message_id=f"<{uid}@e2e.test>".encode(),
        ),
        b"RFC822.SIZE": 1024,
    }


@pytest.mark.e2e
def test_s1_imap_fetch_10_emails(monkeypatch: Any, tmp_path: Any) -> Any:
    """S1.1 — 10 封 faker 邮件 IMAP fetch 全返回."""

    from my_ai_employee.connectors.imap import IMAPConnector
    from my_ai_employee.core import keychain
    from tests.connectors.mock_imap import MockIMAPClient, install_mock

    # 1. 装 fake keychain
    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=True, value="mock-auth-code"),
    )

    # 2. 构造 10 封 faker 邮件
    mock_client = MockIMAPClient()
    mock_client.search_uids = list[Any](range(1, 11))
    mock_client.fetch_data = {
        uid: _make_envelope(
            uid,
            subject=f"测试邮件 #{uid}",
            sender=f"sender{uid}@example.com",
        )
        for uid in range(1, 11)
    }

    # 3. 注入 MockIMAPClient
    conn = IMAPConnector(provider="qq", email="test@qq.com")
    install_mock(monkeypatch, conn, mock_client)

    # 4. fetch(用 asyncio.run 驱动)
    import asyncio

    result = asyncio.run(conn.safe_fetch(datetime(2026, 6, 1, tzinfo=UTC)))

    # 5. 断言
    assert len(result) == 10, f"期望 10 封,实际 {len(result)}"
    assert all("source" in r for r in result)
    assert all(r["source"] == "qq" for r in result)
    # imapclient 3.x: subject 是 bytes,D13.x P0 修复后 _to_str helper 自动 decode utf-8 → str
    assert result[0]["subject"] == "测试邮件 #1"
    # mailbox/host 是 bytes,f-string 拼成 "b'sender10'@b'example.com'" str 形式
    assert "sender10" in result[9]["sender"] and "example.com" in result[9]["sender"]


@pytest.mark.e2e
def test_s1_imap_circuit_breaker(monkeypatch: Any, tmp_path: Any) -> Any:
    """S1.2 — 连续失败 3 次触发熔断(沿 BaseConnector CIRCUIT_BREAKER_THRESHOLD=3).

    D6.0 简化:monkeypatch 替换 conn.fetch 每次抛 ConnectionError,
    绕过 IMAPConnector 内部 connect/login 流程(那部分在 D2.7 test_imap 已测),
    直接测 BaseConnector.safe_fetch 熔断逻辑。
    """
    from datetime import UTC, datetime

    from my_ai_employee.connectors.imap import IMAPConnector
    from my_ai_employee.core import keychain

    monkeypatch.setattr(
        keychain,
        "get_imap_password",
        lambda email: keychain.KeychainResult(ok=True, value="mock-auth-code"),
    )

    conn = IMAPConnector(provider="qq", email="test@qq.com")

    # monkeypatch conn.fetch 永远抛 ConnectionError(模拟网络失败)
    async def _failing_fetch(since: Any) -> Any:  # noqa: ARG001
        raise ConnectionError("mock network failure for circuit breaker test")

    conn.fetch = _failing_fetch  # type: ignore[method-assign]

    import asyncio

    # 第 1-3 次:fetch 失败,触发失败计数
    for i in range(3):
        result = asyncio.run(conn.safe_fetch(datetime(2026, 6, 1, tzinfo=UTC)))
        assert result == [], f"第 {i + 1} 次失败应返回空,实际 {result!r}"

    # 第 4 次:熔断开启,直接返回空(不调 fetch)
    state = conn.circuit_state
    assert state["is_open"] is True, f"熔断应开启,实际 {state}"
    assert state["consecutive_failures"] >= 3


@pytest.mark.e2e
def test_s1_classify_emails(monkeypatch: Any, session_factory: Any) -> Any:
    """S1.3 — 5 封邮件走 EmailClassifierAdapter 分类入口契约(Mock LLM router).

    D6.0 阶段:不调真实 LLM,Mock router 返回固定 5 类(每类各 1 封).
    真实 LLM 分类准确率在 D4.6 单元测试里测(AI 层独立验证).
    """
    from my_ai_employee.ai.classifier import ClassificationResult, EmailCategory, EmailClassifier
    from my_ai_employee.ai.providers import LLMResponse

    # Mock LLM router(返回固定 5 类)
    class _MockRouter:
        def __init__(self) -> None:
            self._call_count = 0

        def route(self, *, task_type: Any, messages: Any, temperature: Any, max_tokens: Any) -> Any:
            # 5 类循环
            categories = list[Any](EmailCategory)
            category = categories[self._call_count % len(categories)]
            self._call_count += 1
            return LLMResponse(
                content=f'{{"category": "{category.value}", "confidence": 0.9}}',
                model_full_id="mock-e2e",
                input_tokens=50,
                output_tokens=20,
                latency_ms=10,
            )

    classifier = EmailClassifier(router=_MockRouter())  # type: ignore[arg-type]

    emails = [
        {"subject": f"邮件 #{i}", "sender": f"u{i}@x.com", "body_excerpt": f"内容 {i}"}
        for i in range(5)
    ]

    results = [classifier.classify(**e) for e in emails]
    assert all(isinstance(r, ClassificationResult) for r in results)
    assert all(r.confidence == 0.9 for r in results)
    assert all(r.model_full_id == "mock-e2e" for r in results)
    # 5 类各出现 1 次(分布 100%)
    categories = {r.category for r in results}
    assert len(categories) >= 3, f"5 类分布应至少覆盖 3 类,实际 {categories}"
