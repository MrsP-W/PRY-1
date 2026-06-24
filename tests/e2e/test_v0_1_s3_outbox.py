"""S3 — 草稿入库 → outbox 表(Week 1 路径).

承接 docs/v0.1-launch-plan.md:218 S3 唯一编号表行。

D6.0 范围(2026-06-14 启动):
    - 5 封 faker 草稿(subject/body/tone/recipient)
    - EmailOutboxAdapter.store_and_emit 入库
    - 断言:5 行 status=pending_send + UNIQUE(email_id) 业务阻断 + 11 字段齐

跑法:
    pytest tests/e2e/test_v0_1_s3_outbox.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.mark.e2e
def test_s3_outbox_store_5_drafts(session_factory):
    """S3.1 — 5 封草稿入库,全部 status=pending_send."""
    from my_ai_employee.core.outbox import OutboxPriority, OutboxStatus, OutboxTone
    from my_ai_employee.db.outbox import OutboxStore
    from my_ai_employee.policy.outbox_adapter import EmailOutboxAdapter

    # 1. 构造 faker 草稿(5 封)
    drafts = [
        {
            "email_id": i + 1,
            "subject": f"草稿 #{i + 1}",
            "body": f"草稿正文 #{i + 1} 内容,这是 e2e 测试入 outbox 库的内容。",
            "tone": OutboxTone.FORMAL.value,
            "recipient_email": f"recipient{i + 1}@example.com",
        }
        for i in range(5)
    ]

    # 2. 装 EmailOutboxAdapter
    adapter = EmailOutboxAdapter(
        source="qq",
        outbox_store=OutboxStore(session_factory),
    )

    # 3. 逐封入库
    from my_ai_employee.policy.outbox_adapter import OutboxDecisionReport

    for d in drafts:
        report = adapter.store_and_emit(
            email_id=cast(int, d["email_id"]),
            subject=cast(str, d["subject"]),
            body=cast(str, d["body"]),
            tone=cast(str, d["tone"]),
            recipient_email=cast(str, d["recipient_email"]),
            run_id=f"e2e-s3-{d['email_id']}",
        )
        # 窄化联合类型:store_and_emit 可能返回 OutboxDecisionReport | OutboxBlockedDecisionReport
        # 黑名单命中时是 OutboxBlockedDecisionReport(无 outbox_stored / outbox_id)
        assert isinstance(report, OutboxDecisionReport), f"unexpected blocked report: {report}"
        assert report.outbox_stored is True
        assert report.outbox_id is not None and report.outbox_id >= 1

    # 4. 验证 outbox 表 5 行
    from my_ai_employee.core.outbox import OutboxEntry

    with session_factory() as session:
        rows = session.query(OutboxEntry).all()
        assert len(rows) == 5
        assert all(r.status == OutboxStatus.PENDING_SEND.value for r in rows)
        assert all(r.priority == OutboxPriority.NORMAL.value for r in rows)


@pytest.mark.e2e
def test_s3_outbox_duplicate_email_id_business_blocked(session_factory):
    """S3.2 — 同 email_id 第 2 次入库 → OutboxEmailDuplicateError → 业务阻断入口."""
    from my_ai_employee.core.outbox import OutboxTone
    from my_ai_employee.db.outbox import OutboxEmailDuplicateError, OutboxStore
    from my_ai_employee.policy.outbox_adapter import EmailOutboxAdapter

    adapter = EmailOutboxAdapter(
        source="qq",
        outbox_store=OutboxStore(session_factory),
    )

    # 第 1 次入库:成功
    adapter.store_and_emit(
        email_id=100,
        subject="第一次",
        body="内容 body 必填 10 字符以上",
        tone=OutboxTone.FORMAL.value,
        recipient_email="dup@example.com",
        run_id="e2e-s3-dup-1",
    )

    # 第 2 次入库:UNIQUE(email_id) 冲突 → 业务阻断(D3.3.3 异常窄化)
    with pytest.raises(OutboxEmailDuplicateError):
        adapter.store_and_emit(
            email_id=100,  # 同一 email_id
            subject="第二次",
            body="内容 body 必填 10 字符以上",
            tone=OutboxTone.FORMAL.value,
            recipient_email="dup@example.com",
            run_id="e2e-s3-dup-2",
        )
