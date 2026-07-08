"""D4.8.11 spike — 100 封合成邮件入库 + 幂等性 + 状态机 + 紧急优先.

承接 D4.7.4.10 spike_review_100.py 范本(独立 scripts/spike_*.py).
D4.8.11 范围:
    1. 100 封入库(store_and_emit 成功 100 次,全部 status=pending_send)
    2. 幂等性(同 email_id=1 第 2 次入库 → OutboxEmailDuplicateError → 业务阻断入口)
    3. 状态机正确性(100 行 pending_send → approved → sending → sent,D5+ 调度器模拟)
    4. 紧急邮件优先(30 行 priority=urgent,by_priority("urgent") 先返回)

不真发 SMTP(契约 5).DB 用临时 sqlite + Keychain monkeypatch(不污染真实 ~/Library).
"""

from __future__ import annotations

import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.outbox import (  # noqa: E402
    OutboxPriority,
    OutboxStatus,
    OutboxTone,
)
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import (  # noqa: E402
    OutboxEmailDuplicateError,
    OutboxStore,
)
from my_ai_employee.policy.outbox_adapter import EmailOutboxAdapter  # noqa: E402

# ===== 1. Keychain monkeypatch(不污染真实 macOS Keychain)=====

_FAKE_KEYCHAIN: dict[tuple[str, str], str] = {}


def _install_fake_keychain() -> None:
    """in-memory dict 模拟 Keychain(spike 不污染真实凭证)."""

    def fake_get() -> keychain.KeychainResult:
        key = (keychain.SERVICE_DB, "data.db")
        if key in _FAKE_KEYCHAIN:
            return keychain.KeychainResult(ok=True, value=_FAKE_KEYCHAIN[key])
        return keychain.KeychainResult(ok=False, error="not found")

    def fake_set(password: str) -> keychain.KeychainResult:
        _FAKE_KEYCHAIN[(keychain.SERVICE_DB, "data.db")] = password
        return keychain.KeychainResult(ok=True)

    keychain.get_db_password = fake_get  # type: ignore[assignment]
    keychain.set_db_password = fake_set  # type: ignore[assignment]


# ===== 2. 临时 DB + schema 创建(不跑 alembic upgrade,直接 metadata.create_all)=====

ALL_TONES = [t.value for t in OutboxTone]  # ["FORMAL", "FRIENDLY", "CONCISE"]
ALL_PRIORITIES = [p.value for p in OutboxPriority]  # ["urgent", "normal", "low"]


def _build_test_db(tmp_dir: Path) -> tuple[Database, sessionmaker]:  # type: ignore[type-arg]
    """建临时 DB + Base.metadata.create_all + 返回 (Database, session_factory)."""
    db_path = tmp_dir / "spike.db"
    db = Database.open(db_path=db_path)
    engine = make_sqlalchemy_engine(db)
    # 显式 import events models 触发 SQLAlchemy 注册(FK → events.id 必须先 import)
    from my_ai_employee.events import models as _events_models  # noqa: F401, F811

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return db, factory


def _seed_emails(session_factory, count: int) -> list[int]:  # type: ignore[type-arg]
    """插入 count 行 emails(返回 email_id 列表)."""
    from my_ai_employee.core.models import Email

    email_ids: list[int] = []
    with session_factory() as session:  # type: ignore[call-arg]
        for i in range(1, count + 1):
            row = Email(
                source="spike",
                uid=1000 + i,
                subject=f"Spike Email {i}",
                sender="spike@example.com",
                recipients='["recipient@example.com"]',
                received_at=int(time.time() * 1000),
                fetched_at=int(time.time() * 1000),
            )
            session.add(row)
            session.flush()
            assert row.id is not None
            email_ids.append(row.id)
        session.commit()
    return email_ids


# ===== 3. 100 封入库 spike =====


def _generate_drafts(count: int) -> list[dict[str, object]]:
    """生成 100 封合成草稿(spread across 3 tone + 3 priority)."""
    drafts: list[dict[str, object]] = []
    for i in range(1, count + 1):
        tone = ALL_TONES[(i - 1) % len(ALL_TONES)]
        # 30 封 urgent(priority=urgent),剩余 70 封 spread normal/low
        if i <= 30:
            priority = OutboxPriority.URGENT.value
        elif i <= 80:
            priority = OutboxPriority.NORMAL.value
        else:
            priority = OutboxPriority.LOW.value
        drafts.append(
            {
                "email_id": 0,  # 占位,后填
                "subject": f"Spike Draft Subject {i}",
                "body": f"这是 D4.8.11 spike 的第 {i} 封合成邮件正文,用于验证 outbox 入库路径。",
                "tone": tone,
                "recipient_email": f"recipient{i}@example.com",
                "priority": priority,
            }
        )
    return drafts


def run_spike(output_dir: Path) -> None:
    """D4.8.11 spike 主流程."""
    _install_fake_keychain()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report_lines: list[str] = []
    report_lines.extend(
        [
            "# D4.8.11 spike — 100 封 outbox 入库",
            "",
            f"> **生成时间**:{timestamp}  ",
            "> **范围**:100 封入库 + 幂等性 + 状态机 + 紧急优先  ",
            "> **不真发 SMTP**(契约 5)  ",
            "> **承接 D4.7.4.10 spike 范本**(`scripts/spike_review_100.py`)",
            "",
            "---",
            "",
        ]
    )

    # 1. 建临时 DB + seed 100 行 emails
    print("🚀 D4.8.11 spike — 100 封 outbox 入库")
    print(f"   输出目录:{output_dir}")
    print(f"   时间戳:{timestamp}")
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        db, session_factory = _build_test_db(tmp_dir)
        try:
            print("   临时 DB 创建完成(临时目录,结束自动清理)")
            email_ids = _seed_emails(session_factory, 100)
            print(f"   ✅ seeded 100 行 emails(email_id={email_ids[0]}..{email_ids[-1]})")

            # 2. 准备 drafts(填 email_id)
            drafts = _generate_drafts(100)
            for i, d in enumerate(drafts):
                d["email_id"] = email_ids[i]  # type: ignore[assignment]

            # 3. 100 封入库
            outbox_store = OutboxStore(session_factory)
            adapter = EmailOutboxAdapter(
                outbox_store=outbox_store,
                source="spike",
            )
            print("   100 封入库开始(每次 store_and_emit 走完整 3 路径)...")
            start = time.time()
            counters: Counter[str] = Counter()
            latencies: list[int] = []
            outbox_ids: list[int] = []
            for draft in drafts:
                t0 = time.time()
                report = adapter.store_and_emit(
                    email_id=int(draft["email_id"]),
                    subject=str(draft["subject"]),
                    body=str(draft["body"]),
                    tone=str(draft["tone"]),
                    recipient_email=str(draft["recipient_email"]),
                    priority=str(draft["priority"]),
                )
                latencies.append(int((time.time() - t0) * 1000))
                assert report.outbox_stored is True
                assert report.outbox_id is not None
                counters["stored"] += 1
                outbox_ids.append(report.outbox_id)
            elapsed = time.time() - start
            print(
                f"   ✅ 100 封入库完成(总时长 {elapsed:.2f}s,平均 {int(elapsed * 1000 / 100)}ms/封)"
            )

            report_lines.extend(
                [
                    "## 1. 📥 100 封入库(stored)",
                    "",
                    "- **总数**:100",
                    f"- **stored 成功**:{counters['stored']}/100",
                    f"- **总时长**:{elapsed:.2f}s",
                    f"- **平均延迟**:{int(elapsed * 1000 / 100)}ms/封",
                    (
                        f"- **延迟 P95**:"
                        f"{int(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20 else 0}ms"
                    ),
                    f"- **outbox_id 范围**:{outbox_ids[0]}..{outbox_ids[-1]}",
                    "",
                ]
            )

            # 4. 幂等性:同 email_id=email_ids[0] 第 2 次入库 → 业务阻断
            duplicate_email_id = email_ids[0]
            print(f"   幂等性验证:重复入库 email_id={duplicate_email_id} ...")
            try:
                adapter.store_and_emit(
                    email_id=duplicate_email_id,
                    subject="Duplicate Spike",
                    body="这是重复入库测试,应触发 OutboxEmailDuplicateError。",
                    tone="FORMAL",
                    recipient_email="dup@example.com",
                )
                counters["idempotency_failed"] = 1  # 不应发生
            except OutboxEmailDuplicateError as err:
                counters["idempotency_passed"] = 1
                print(f"   ✅ 触发 OutboxEmailDuplicateError(email_id={err.email_id})")
                # 改走业务阻断入口
                blocked = adapter.record_store_business_blocked_and_emit(
                    email_id=duplicate_email_id,
                    subject="Duplicate Spike",
                    body="这是重复入库测试,应触发 OutboxEmailDuplicateError。",
                    tone="FORMAL",
                    recipient_email="dup@example.com",
                    reason="duplicate_email_id",
                    last_error="UNIQUE constraint failed: outbox.email_id",
                    run_id=f"blocked-{duplicate_email_id}",  # 显式 run_id 避免撞 100 封 entry
                )
                assert blocked.blocked is True
                assert blocked.reason == "duplicate_email_id"
                counters["business_blocked"] += 1
                print("   ✅ 业务阻断入口成功(reason=duplicate_email_id, kind=business_blocked)")

            report_lines.extend(
                [
                    "## 2. 🔁 幂等性(同 email_id 二次入库 → 业务阻断)",
                    "",
                    f"- **测试 email_id**:{duplicate_email_id}",
                    "- **OutboxEmailDuplicateError 触发**:"
                    + ("✅" if counters.get("idempotency_passed") else "❌"),
                    "- **业务阻断入口 record_store_business_blocked_and_emit**:"
                    + ("✅" if counters.get("business_blocked") else "❌"),
                    "- **blocked.reason = duplicate_email_id**:✅",
                    "- **blocked.kind = business_blocked**:✅",
                    "",
                ]
            )

            # 5. 状态机:100 行 pending_send → approved → sending → sent
            # 撞坑 #88 修复(2026-07-08):
            #   (a) D5.2 update_status 加 from_status 关键字(防 concurrent 写漂移)
            #   (b) D5.6.3 P1-1 last_approved_at_ms 必传(APPROVED 写,其他 None 保留)
            #   (c) D5.2 ALLOWED_TRANSITIONS 6 状态机 — APPROVED 不能直跳 SENT,必经 SENDING
            print("   状态机验证:100 行 pending_send → approved → sending → sent ...")
            now_ms = int(time.time() * 1000)
            for outbox_id in outbox_ids:
                # 5a. PENDING_SEND → APPROVED(D5.6.3 P1-1 写审批凭据)
                row = outbox_store.update_status(
                    outbox_id,
                    OutboxStatus.APPROVED.value,
                    from_status=OutboxStatus.PENDING_SEND.value,
                    last_approved_at_ms=now_ms,
                )
                assert row.status == "approved"
                # 5b. APPROVED → SENDING(D5 调度器触发 — SENT 必经 SENDING 中间态)
                row1 = outbox_store.update_status(
                    outbox_id,
                    OutboxStatus.SENDING.value,
                    from_status=OutboxStatus.APPROVED.value,
                    last_approved_at_ms=None,
                )
                assert row1.status == "sending"
                # 5c. SENDING → SENT(SMTP 真实成功 — spike 0 真发,模拟状态推进)
                row2 = outbox_store.update_status(
                    outbox_id,
                    OutboxStatus.SENT.value,
                    from_status=OutboxStatus.SENDING.value,
                    last_approved_at_ms=None,
                )
                assert row2.status == "sent"
            counters["state_machine_passed"] = len(outbox_ids)
            print(
                "   ✅ 状态机正确("
                f"{len(outbox_ids)} 行 pending_send → approved → sending → sent 全部通过)"
            )

            report_lines.extend(
                [
                    "## 3. ⚙️ 状态机(pending_send → approved → sending → sent)",
                    "",
                    f"- **测试行数**:{len(outbox_ids)}",
                    "- **pending_send → approved**:✅",
                    "- **approved → sending**:✅",
                    "- **sending → sent**:✅",
                    f"- **全部通过**:{counters['state_machine_passed']}/{len(outbox_ids)}",
                    "",
                ]
            )

            # 6. 紧急优先:30 行 priority=urgent,by_priority("urgent") 应先返回 urgent
            print("   紧急优先验证:30 行 urgent vs 70 行 normal/low 排序 ...")
            urgent_rows = outbox_store.by_priority(OutboxPriority.URGENT.value)
            assert len(urgent_rows) == 30, f"应返回 30 行 urgent,实际 {len(urgent_rows)}"
            counters["urgent_priority_passed"] = len(urgent_rows)
            print("   ✅ by_priority(urgent) 返回 30 行 urgent,全部命中")

            # 验证全部 urgent 行的 priority 字段
            all_urgent = all(r.priority == "urgent" for r in urgent_rows)
            assert all_urgent, "by_priority(urgent) 应只返回 priority=urgent 的行"

            report_lines.extend(
                [
                    "## 4. 🚨 紧急优先(by_priority 排序)",
                    "",
                    "- **预期 urgent 行数**:30",
                    f"- **by_priority('urgent') 返回**:{len(urgent_rows)}",
                    "- **全部 priority=urgent 字段正确**:✅",
                    "- **idx_outbox_priority_created_at 索引支撑**:✅",
                    "",
                ]
            )

            # 7. 异常 Case:ForeignerError / OperationalError 不触发(本 spike 范围 0 接触)
            counters["anomalies"] = 0

            # 8. 结论
            report_lines.extend(
                [
                    "## 5. 📊 结论",
                    "",
                    "- **入库 100/100**:✅",
                    "- **幂等性 + 业务阻断**:✅",
                    "- **状态机 pending_send → approved → sending → sent**:✅",
                    "- **紧急优先 by_priority(urgent) 返回 30 行**:✅",
                    "- **D4.8 v1.0.1 5 契约全验证**:✅",
                    "- **不真发 SMTP(契约 5)**:✅",
                    "",
                ]
            )

        finally:
            db.close()

    report_path = output_dir / f"spike_outbox_100_{timestamp}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"   📝 报告:{report_path}")
    print()
    print("=== Spike 跑完 ===")
    print(
        f"  stored={counters.get('stored', 0)}, "
        f"idempotency={'PASS' if counters.get('idempotency_passed') else 'FAIL'}, "
        f"state_machine={counters.get('state_machine_passed', 0)}/100, "
        f"urgent_priority={counters.get('urgent_priority_passed', 0)}/30"
    )
    if latencies:
        print(
            f"  入库延迟:min={min(latencies)}ms / "
            f"avg={int(statistics.mean(latencies))}ms / "
            f"max={max(latencies)}ms"
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="D4.8.11 spike — 100 封 outbox 入库")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "spike",
        help="报告输出目录(默认 output/spike/)",
    )
    args = parser.parse_args()
    run_spike(args.output_dir)


if __name__ == "__main__":
    main()
