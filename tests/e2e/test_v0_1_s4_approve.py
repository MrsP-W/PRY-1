"""S4 — 1-click 审批 → 审批状态推进(Week 1 路径).

承接 docs/v0.1-launch-plan.md:219 S4 唯一编号表行。

D6.0 范围(2026-06-14 启动):
    - 5 封 outbox pending_send 草稿(从 S3 链入)
    - OutboxStore.update_status PENDING_SEND → APPROVED
    - 断言:状态机推进成功 + last_approved_at_ms 写入 + 非法转移抛 OutboxIllegalTransitionError

跑法:
    pytest tests/e2e/test_v0_1_s4_approve.py -v
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.mark.e2e
def test_s4_approve_5_outbox_to_approved(session_factory: Any) -> Any:
    """S4.1 — 5 封 outbox pending_send 1-click 审批 → APPROVED."""
    from my_ai_employee.core.outbox import OutboxStatus, OutboxTone
    from my_ai_employee.db.outbox import OutboxStore

    store = OutboxStore(session_factory)
    now_ms = int(time.time() * 1000)

    # 1. 准备 5 封 pending_send
    entry_ids = []
    for i in range(5):
        entry = store.insert(
            email_id=i + 1,
            subject=f"审批草稿 #{i + 1}",
            body=f"审批草稿 body #{i + 1} 必填 10 字符以上",
            tone=OutboxTone.FORMAL.value,
            recipient_email=f"approve{i + 1}@example.com",
        )
        assert entry.status == OutboxStatus.PENDING_SEND.value
        entry_ids.append(entry.id)

    # 2. 1-click 审批(逐封 update_status)
    for entry_id in entry_ids:
        updated = store.update_status(
            entry_id,
            OutboxStatus.APPROVED.value,
            from_status=OutboxStatus.PENDING_SEND.value,
            last_approved_at_ms=now_ms,  # APPROVED 必传
        )
        assert updated.status == OutboxStatus.APPROVED.value
        assert updated.last_approved_at_ms == now_ms


@pytest.mark.e2e
def test_s4_illegal_transition_pending_to_sent(session_factory: Any) -> Any:
    """S4.2 — 非法转移 PENDING_SEND → SENT → OutboxIllegalTransitionError(D5.2 白名单严判)."""
    from my_ai_employee.core.outbox import OutboxStatus, OutboxTone
    from my_ai_employee.db.outbox import OutboxIllegalTransitionError, OutboxStore

    store = OutboxStore(session_factory)
    entry = store.insert(
        email_id=999,
        subject="非法转移测试",
        body="非法转移测试 body 必填 10 字符以上",
        tone=OutboxTone.FORMAL.value,
        recipient_email="illegal@example.com",
    )

    # PENDING_SEND 合法目标: SENDING / APPROVED / FAILED / CANCELLED
    # SENT 不在白名单 → 非法转移
    with pytest.raises(OutboxIllegalTransitionError):
        store.update_status(
            entry.id,
            OutboxStatus.SENT.value,
            from_status=OutboxStatus.PENDING_SEND.value,
        )


@pytest.mark.e2e
def test_s4_approved_keeps_timestamp_on_resend(session_factory: Any) -> Any:
    """S4.3 — APPROVED → SENDING → SENT 过程保留 last_approved_at_ms(不重置)."""
    from my_ai_employee.core.outbox import OutboxStatus, OutboxTone
    from my_ai_employee.db.outbox import OutboxStore

    store = OutboxStore(session_factory)
    now_ms = int(time.time() * 1000)

    entry = store.insert(
        email_id=42,
        subject="审批时间戳保留",
        body="审批时间戳保留 body 必填 10 字符以上",
        tone=OutboxTone.FORMAL.value,
        recipient_email="keep@example.com",
    )

    # PENDING_SEND → APPROVED
    entry = store.update_status(
        entry.id,
        OutboxStatus.APPROVED.value,
        from_status=OutboxStatus.PENDING_SEND.value,
        last_approved_at_ms=now_ms,
    )
    assert entry.last_approved_at_ms == now_ms

    # APPROVED → SENDING(不传 last_approved_at_ms,严判传 None)
    entry = store.update_status(
        entry.id,
        OutboxStatus.SENDING.value,
        from_status=OutboxStatus.APPROVED.value,
        last_approved_at_ms=None,
    )
    assert entry.status == OutboxStatus.SENDING.value
    assert entry.last_approved_at_ms == now_ms  # 保留

    # SENDING → SENT(不传 last_approved_at_ms,严判传 None)
    entry = store.update_status(
        entry.id,
        OutboxStatus.SENT.value,
        from_status=OutboxStatus.SENDING.value,
        last_approved_at_ms=None,
    )
    assert entry.status == OutboxStatus.SENT.value
    assert entry.last_approved_at_ms == now_ms  # 保留(终态)
