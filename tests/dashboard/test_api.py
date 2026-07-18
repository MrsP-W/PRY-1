"""v0.2.53.2 P2 — Dashboard 只读 API 测试."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from my_ai_employee.dashboard.context import DashboardContext, QualityGateSnapshot
from my_ai_employee.dashboard.handlers import handler_factory
from my_ai_employee.dashboard.responses import (
    build_finance_anomalies_payload,
    build_notes_pending_payload,
    build_outbox_payload,
    build_status_payload,
    build_tasks_today_payload,
)
from my_ai_employee.dashboard.server import create_server


class _CountingDraft:
    def get_pending_draft_count(self) -> int:
        return 2

    def list_pending_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {
                "outbox_id": 101,
                "subject": "供应商付款确认",
                "status": "pending_send",
                "priority": "urgent",
            }
        ][:limit]


class _CountingConfirm:
    def get_pending_confirm_count(self) -> int:
        return 3

    def list_pending_confirm(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {
                "apple_note_id": "note-1",
                "title": "L2 候选",
                "folder": "工作",
                "needs_confirm": 1,
            }
        ][:limit]

    def confirm_note(self, apple_note_id: str) -> None:
        return None


class _CountingExpense:
    def get_total_notes_count(self) -> int:
        return 0

    def get_unsynced_count(self) -> int:
        return 0

    def get_recent_note_titles(self, limit: int = 5) -> list[str]:
        return []

    def is_clipboard_listener_running(self) -> bool:
        return False

    def get_tcc_authorization_status(self) -> bool:
        return False

    def get_anomaly_count(self) -> int:
        return 1

    def get_recent_anomalies(self, limit: int = 10) -> list[dict[str, Any]]:
        return [
            {
                "date": "2026-06-25",
                "counterparty": "支付宝",
                "amount": 1299,
                "kinds": "amount_spike",
            }
        ][:limit]


@pytest.fixture
def dashboard_ctx() -> DashboardContext:
    return DashboardContext(
        expense_service=_CountingExpense(),
        note_confirm_service=_CountingConfirm(),
        outbox_draft_service=_CountingDraft(),
        git_head_resolver=lambda: "abc123",
        keychain_probe=lambda _s: False,
        quality_gates=QualityGateSnapshot(pytest="2278 passed / 1 skipped"),
    )


def test_build_status_payload_read_only(dashboard_ctx: DashboardContext) -> None:
    payload = build_status_payload(dashboard_ctx)
    assert payload["read_only"] is True
    assert payload["git_head"] == "abc123"
    assert payload["quality_gates"]["pytest"] == "2278 passed / 1 skipped"
    assert payload["providers"]["keychain"]["smtp_qq"] == "missing"
    assert payload["approval_gates"]["keychain_write"] is False


class TestDryRunThreeGateStatus:
    """v0.2.53.28 三门联调 status payload — 第三道门以 Impl 实际注入为准.

    覆盖 3 态:
        - 默认(双门都未开):outcome=disabled
        - env 开但 Impl 未注入:outcome=writer_required
        - Impl 已注入 + env 开:outcome=dry_run_ready
    """

    def _base_payload(self) -> dict[str, Any]:
        from my_ai_employee.dashboard.responses import build_status_payload

        payload: dict[str, Any] = build_status_payload(self._make_ctx())
        return payload

    @staticmethod
    def _make_ctx() -> DashboardContext:
        return DashboardContext(
            git_head_resolver=lambda: "abc123",
            keychain_probe=lambda _s: False,
            quality_gates=QualityGateSnapshot(pytest="2518 passed / 1 skipped"),
        )

    def test_default_state_outcome_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.responses import build_status_payload

        monkeypatch.delenv(DASHBOARD_WRITE_API_ENV, raising=False)
        monkeypatch.delenv(BUSINESS_WRITER_ENABLED_ENV, raising=False)
        payload = build_status_payload(self._make_ctx())
        ag = payload["approval_gates"]
        assert ag["dashboard_write_api"] is False
        assert ag["business_writer_enabled"] is False
        assert ag["business_writer_env_enabled"] is False
        assert ag["business_writer_impl_injected"] is False
        assert ag["business_writer_ready"] is False
        status = ag["v0_2_53_26_dry_run_status"]
        assert status["first_gate"] == "closed"
        assert status["second_gate"] == "confirm_required_per_action"
        assert status["third_gate"] == "closed"
        assert status["outcome"] == "disabled"

    def test_writer_env_only_outcome_writer_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.responses import build_status_payload

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        payload = build_status_payload(self._make_ctx())
        ag = payload["approval_gates"]
        assert ag["business_writer_env_enabled"] is True
        assert ag["business_writer_impl_injected"] is False
        assert ag["business_writer_ready"] is False
        status = ag["v0_2_53_26_dry_run_status"]
        assert status["first_gate"] == "open"
        assert status["second_gate"] == "confirm_required_per_action"
        assert status["third_gate"] == "closed"
        assert status["outcome"] == "writer_required"

    def test_dashbaord_write_api_only_outcome_writer_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.responses import build_status_payload

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.delenv(BUSINESS_WRITER_ENABLED_ENV, raising=False)
        payload = build_status_payload(self._make_ctx())
        ag = payload["approval_gates"]
        assert ag["dashboard_write_api"] is True
        assert ag["business_writer_enabled"] is False
        status = ag["v0_2_53_26_dry_run_status"]
        assert status["first_gate"] == "open"
        assert status["second_gate"] == "confirm_required_per_action"
        assert status["third_gate"] == "closed"
        assert status["outcome"] == "writer_required"

    def test_both_gates_open_outcome_dry_run_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl
        from my_ai_employee.dashboard.responses import build_status_payload

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        ctx = self._make_ctx().with_business_writer(BusinessWriterImpl())
        payload = build_status_payload(ctx)
        ag = payload["approval_gates"]
        assert ag["dashboard_write_api"] is True
        assert ag["business_writer_enabled"] is True
        assert ag["business_writer_env_enabled"] is True
        assert ag["business_writer_impl_injected"] is True
        assert ag["business_writer_ready"] is True
        status = ag["v0_2_53_26_dry_run_status"]
        assert status["first_gate"] == "open"
        assert status["second_gate"] == "confirm_required_per_action"
        assert status["third_gate"] == "open"
        assert status["outcome"] == "dry_run_ready"


class TestPath4FiveGateStatus:
    """v0.2.55 /api/status Path 4 五门字段 — Dashboard 5 门 card 数据源."""

    @staticmethod
    def _make_ctx() -> DashboardContext:
        return DashboardContext(
            git_head_resolver=lambda: "abc123",
            keychain_probe=lambda _s: False,
        )

    def test_default_path4_gates_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.business_writer_impl import (
            ENABLE_PATH_4_WRITE_ENV,
            BusinessWriterImpl,
        )

        monkeypatch.delenv(DASHBOARD_WRITE_API_ENV, raising=False)
        monkeypatch.delenv(BUSINESS_WRITER_ENABLED_ENV, raising=False)
        monkeypatch.delenv(ENABLE_PATH_4_WRITE_ENV, raising=False)
        payload = build_status_payload(self._make_ctx().with_business_writer(BusinessWriterImpl()))
        ag = payload["approval_gates"]
        assert ag["enable_path_4_write_env_enabled"] is False
        assert ag["path4_write_ready"] is False
        assert ag["v0_2_53_26_dry_run_status"]["fifth_gate"] == "closed"

    def test_path4_env_and_writer_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from my_ai_employee.dashboard.approval_gate import (
            BUSINESS_WRITER_ENABLED_ENV,
            DASHBOARD_WRITE_API_ENV,
        )
        from my_ai_employee.dashboard.business_writer_impl import (
            ENABLE_PATH_4_WRITE_ENV,
            BusinessWriterImpl,
        )

        monkeypatch.setenv(DASHBOARD_WRITE_API_ENV, "1")
        monkeypatch.setenv(BUSINESS_WRITER_ENABLED_ENV, "1")
        monkeypatch.setenv(ENABLE_PATH_4_WRITE_ENV, "1")
        writer = BusinessWriterImpl(
            real_write_handler_enabled=True,
            enable_path_4_write=True,
        )
        payload = build_status_payload(self._make_ctx().with_business_writer(writer))
        ag = payload["approval_gates"]
        assert ag["enable_path_4_write_env_enabled"] is True
        assert ag["path4_write_ready"] is True
        assert ag["v0_2_53_26_dry_run_status"]["fifth_gate"] == "open"


def test_build_tasks_today_payload_counts(dashboard_ctx: DashboardContext) -> None:
    payload = build_tasks_today_payload(dashboard_ctx)
    assert payload["read_only"] is True
    assert payload["total"] == 6
    assert payload["tasks"][0]["count"] == 2
    assert payload["tasks"][1]["count"] == 3
    assert payload["tasks"][2]["count"] == 1


def test_build_outbox_payload_items(dashboard_ctx: DashboardContext) -> None:
    payload = build_outbox_payload(dashboard_ctx)
    assert payload["read_only"] is True
    assert payload["count"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["outbox_id"] == 101


def test_build_notes_pending_payload_items(dashboard_ctx: DashboardContext) -> None:
    payload = build_notes_pending_payload(dashboard_ctx)
    assert payload["count"] == 3
    assert payload["items"][0]["apple_note_id"] == "note-1"


def test_build_finance_anomalies_payload_items(dashboard_ctx: DashboardContext) -> None:
    payload = build_finance_anomalies_payload(dashboard_ctx)
    assert payload["count"] == 1
    assert payload["items"][0]["counterparty"] == "支付宝"


def test_parse_limit_clamps() -> None:
    from my_ai_employee.dashboard.context import parse_limit

    assert parse_limit(None) == 10
    assert parse_limit("5") == 5
    assert parse_limit("0") == 1
    assert parse_limit("999") == 100
    assert parse_limit("bad") == 10


# ============================================================
# v0.2.53.52 GET /api/approval-gate/audits 测试
# ============================================================


class TestApprovalGateAuditsPayload:
    """v0.2.53.52 build_approval_gate_audits_payload 测试.

    边界(沿 v0.2.53.51 + 撞坑 #65 opt-in 4 阶段):
        - 默认 ApprovalGateAuditStoreStub → enabled=False,count=0
        - InMemoryApprovalGateAuditStore 注入 → enabled=True,items 按 executed_at_ms DESC
        - limit 严判由 parse_limit 处理
    """

    def test_default_stub_returns_empty(self) -> None:
        """默认 Stub → enabled=False,空列表(撞坑 #65 默认禁写)."""
        from my_ai_employee.dashboard.responses import build_approval_gate_audits_payload

        ctx = DashboardContext()  # 默认 audit_store=Stub
        payload = build_approval_gate_audits_payload(ctx)
        assert payload["read_only"] is True
        assert payload["enabled"] is False
        assert payload["count"] == 0
        assert payload["items"] == []

    def test_inmemory_audit_returns_items(self) -> None:
        """注入 InMemoryApprovalGateAuditStore → enabled=True,按时间倒序返回."""
        from my_ai_employee.dashboard.responses import build_approval_gate_audits_payload
        from my_ai_employee.menu_bar.approval_gate_audit import (
            AuditRecord,
            InMemoryApprovalGateAuditStore,
        )

        store = InMemoryApprovalGateAuditStore()
        store.record(
            AuditRecord(
                action="approve_outbox",
                target_id="100",
                actor="tester",
                reason="first",
                write_executed=True,
                affected_id="100",
                error=None,
                executed_at_ms=1000,
            )
        )
        store.record(
            AuditRecord(
                action="cancel_outbox",
                target_id="200",
                actor="tester",
                reason="second",
                write_executed=True,
                affected_id="200",
                error=None,
                executed_at_ms=2000,
            )
        )
        ctx = DashboardContext(audit_store=store)
        payload = build_approval_gate_audits_payload(ctx, limit=10)
        assert payload["read_only"] is True
        assert payload["enabled"] is True
        assert payload["count"] == 2
        # 按 executed_at_ms DESC 倒序(2000 先)
        assert payload["items"][0]["action"] == "cancel_outbox"
        assert payload["items"][1]["action"] == "approve_outbox"
        assert payload["items"][0]["affected_id"] == "200"
        assert payload["items"][1]["affected_id"] == "100"

    def test_inmemory_audit_respects_limit(self) -> None:
        """limit 严判 — InMemory 内部 list_recent limit 已严判 1-100."""
        from my_ai_employee.dashboard.responses import build_approval_gate_audits_payload
        from my_ai_employee.menu_bar.approval_gate_audit import (
            AuditRecord,
            InMemoryApprovalGateAuditStore,
        )

        store = InMemoryApprovalGateAuditStore()
        for i in range(5):
            store.record(
                AuditRecord(
                    action="approve_outbox",
                    target_id=str(i),
                    actor="tester",
                    reason=f"r{i}",
                    write_executed=True,
                    affected_id=str(i),
                    error=None,
                    executed_at_ms=1000 + i,
                )
            )
        ctx = DashboardContext(audit_store=store)
        payload = build_approval_gate_audits_payload(ctx, limit=2)
        assert payload["count"] == 2
        # 倒序取最近 2 条
        assert payload["items"][0]["target_id"] == "4"
        assert payload["items"][1]["target_id"] == "3"

    def test_failure_audit_recorded_with_error(self) -> None:
        """失败 audit 落档(撞坑 #18 异常收窄)→ 仍返回 items,error 字段非 None."""
        from my_ai_employee.dashboard.responses import build_approval_gate_audits_payload
        from my_ai_employee.menu_bar.approval_gate_audit import (
            AuditRecord,
            InMemoryApprovalGateAuditStore,
        )

        store = InMemoryApprovalGateAuditStore()
        store.record(
            AuditRecord(
                action="approve_outbox",
                target_id="404",
                actor="failure_tester",
                reason="",
                write_executed=True,
                affected_id=None,
                error="ValueError: outbox not found",
                executed_at_ms=3000,
            )
        )
        ctx = DashboardContext(audit_store=store)
        payload = build_approval_gate_audits_payload(ctx)
        assert payload["count"] == 1
        assert payload["items"][0]["error"] == "ValueError: outbox not found"
        assert payload["items"][0]["affected_id"] is None
        assert payload["items"][0]["actor"] == "failure_tester"


class TestApprovalGateAuditsEndpoint:
    """v0.2.53.52 GET /api/approval-gate/audits 端点 e2e 测试(httptest)."""

    def test_endpoint_default_stub_empty(self) -> None:
        """默认 ctx → 端点返回 enabled=False,空列表."""
        from my_ai_employee.dashboard.server import create_server

        server = create_server(ctx=DashboardContext(), host="127.0.0.1", port=0)
        host, port = server.server_address[:2]
        # mypy --strict:server_address[0] 可能是 bytes,显式 str cast(沿 v0.2.53.7 范本)
        host_str = host if isinstance(host, str) else host.decode("utf-8")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, body = _fetch_json(f"http://{host_str}:{port}/api/approval-gate/audits")
            assert status == 200
            assert body["read_only"] is True
            assert body["enabled"] is False
            assert body["count"] == 0
            assert body["items"] == []
        finally:
            server.shutdown()

    def test_endpoint_inmemory_audits(self) -> None:
        """注入 InMemory store → 端点返回 enabled=True,带 items."""
        from my_ai_employee.dashboard.server import create_server
        from my_ai_employee.menu_bar.approval_gate_audit import (
            AuditRecord,
            InMemoryApprovalGateAuditStore,
        )

        store = InMemoryApprovalGateAuditStore()
        store.record(
            AuditRecord(
                action="dismiss_anomaly",
                target_id="2026-06-29|星巴克|38.50",
                actor="dashboard_tester",
                reason="ok",
                write_executed=True,
                affected_id="2026-06-29|星巴克|38.50",
                error=None,
                executed_at_ms=9999,
            )
        )
        ctx = DashboardContext(audit_store=store)
        server = create_server(ctx=ctx, host="127.0.0.1", port=0)
        host, port = server.server_address[:2]
        host_str = host if isinstance(host, str) else host.decode("utf-8")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, body = _fetch_json(f"http://{host_str}:{port}/api/approval-gate/audits?limit=5")
            assert status == 200
            assert body["enabled"] is True
            assert body["count"] == 1
            assert body["items"][0]["action"] == "dismiss_anomaly"
            assert body["items"][0]["actor"] == "dashboard_tester"
        finally:
            server.shutdown()


def _fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 — 测试 localhost
        return resp.status, json.loads(resp.read().decode("utf-8"))


@pytest.fixture
def running_server(dashboard_ctx: DashboardContext) -> Generator[str, None, None]:
    server = create_server(dashboard_ctx, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _host, port = server.server_address[:2]
    base = f"http://127.0.0.1:{port}"
    yield base
    server.shutdown()
    thread.join(timeout=2.0)


def test_http_api_status(running_server: str) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{running_server}/api/status",
        headers={"Origin": "null"},
    )
    with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310 — 测试 localhost
        status = resp.status
        cors_origin = resp.headers["Access-Control-Allow-Origin"]
        body = json.loads(resp.read().decode("utf-8"))
    assert status == 200
    assert cors_origin == "null"
    assert body["read_only"] is True
    assert "quality_gates" in body


def test_http_api_tasks_today(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/tasks/today")
    assert status == 200
    assert body["total"] == 6
    assert len(body["tasks"]) == 3


def test_http_api_outbox(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/outbox?limit=5")
    assert status == 200
    assert body["count"] == 2
    assert body["items"][0]["subject"] == "供应商付款确认"


def test_http_api_notes_pending(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/notes/pending")
    assert status == 200
    assert body["count"] == 3
    assert body["items"][0]["title"] == "L2 候选"


# ============================================================
# Day 10 Phase 1.2 — Dashboard /api/notes/pending 真实解密集成测试
# 沿 [src/my_ai_employee/dashboard/responses.py:151-155] build_notes_pending_payload
# 走 note_confirm_service.list_pending_confirm → NoteStore._decrypt_notes
# 出库前 title/body 已 in-place 解密为明文(撞坑 #65 兼容)
# ============================================================


@pytest.fixture
def dashboard_ctx_with_real_note_confirm() -> Any:
    """真实 NoteStore(Impl cipher) + NoteConfirmServiceImpl 注入的 ctx."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from my_ai_employee.core.models import Base
    from my_ai_employee.core.notes_encryption import NotesCipherImpl
    from my_ai_employee.dashboard.context import DashboardContext
    from my_ai_employee.db.notes import Note, NoteStore  # noqa: F401  # 触发 ORM 注册
    from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    sf = sessionmaker(bind=eng)

    # 直接 SQLAlchemy 写入 needs_confirm=1 的 note(模拟上游 sync 已就位)
    master = b"z" * 32
    with sf() as session:
        # 写 2 条全明文 + 1 条手动 enc:v1: 密文,验证混合场景
        session.add(
            Note(
                apple_note_id="x-coredata://ICNote/DASH-LEGACY1",
                folder="Notes",
                title="明文标题 A",
                body="明文正文 A",
                is_private=0,
                tags=None,
                synced_at_ms=1_700_000_001_000,
                updated_at_ms=1_700_000_001_000,
                sync_status="NEW",
                needs_confirm=1,
                candidate_match_id=None,
            )
        )
        # 手动预加密(用相同 master_key + NotesCipherImpl 写 enc:v1: ... 形式)
        from my_ai_employee.core.notes_encryption import DEFAULT_NOTES_FIELDS

        impl_for_seed = NotesCipherImpl(master_key=master)
        title_field = next(f for f in DEFAULT_NOTES_FIELDS if f.field_name == "title")
        body_field = next(f for f in DEFAULT_NOTES_FIELDS if f.field_name == "body")
        # impl.encrypt 返回的密文**已带 enc:v1: 前缀**(notes_encryption.py:196)
        enc_title = impl_for_seed.encrypt("密文标题 B", title_field)
        enc_body = impl_for_seed.encrypt("密文正文 B", body_field)
        session.add(
            Note(
                apple_note_id="x-coredata://ICNote/DASH-ENC1",
                folder="Work",
                title=enc_title,
                body=enc_body,
                is_private=0,
                tags=None,
                synced_at_ms=1_700_000_002_000,
                updated_at_ms=1_700_000_002_000,
                sync_status="NEW",
                needs_confirm=1,
                candidate_match_id=None,
            )
        )
        session.add(
            Note(
                apple_note_id="x-coredata://ICNote/DASH-LEGACY2",
                folder="Notes",
                title="明文标题 C",
                body="明文正文 C",
                is_private=0,
                tags=None,
                synced_at_ms=1_700_000_003_000,
                updated_at_ms=1_700_000_003_000,
                sync_status="NEW",
                needs_confirm=1,
                candidate_match_id=None,
            )
        )
        session.commit()

    # 用同一 master_key 的 Impl cipher 构造 store
    store = NoteStore(sf, cipher=NotesCipherImpl(master_key=master))
    service = NoteConfirmServiceImpl(store)
    base_ctx = DashboardContext(
        git_head_resolver=lambda: "abc1234",
        keychain_probe=lambda _s: False,
    )
    return base_ctx.with_note_confirm(service), store, master


def test_build_notes_pending_payload_decrypts_real_encrypted_notes(
    dashboard_ctx_with_real_note_confirm: Any,
) -> None:
    """真实 NoteStore(Impl)→ NoteConfirmServiceImpl → build_notes_pending_payload:
    库内密文(enc:v1:)和明文混存,items[].title 全部出库为明文(撞坑 #65 兼容)."""
    from my_ai_employee.core.notes_encryption import _CIPHERTEXT_PREFIX_V1
    from my_ai_employee.dashboard.responses import build_notes_pending_payload

    ctx, store, _master = dashboard_ctx_with_real_note_confirm
    payload = build_notes_pending_payload(ctx, limit=10)

    # 1) count = 3
    assert payload["count"] == 3
    assert payload["read_only"] is True
    assert len(payload["items"]) == 3

    # 2) 字段白名单 — 6 字段都在,无 cipher_prefix/body 泄漏
    expected_keys = {
        "apple_note_id",
        "title",
        "folder",
        "synced_at_ms",
        "candidate_match_id",
        "needs_confirm",
    }
    for item in payload["items"]:
        assert set(item.keys()) == expected_keys
        assert "body" not in item
        assert "cipher_prefix" not in item
        assert "encrypted_title" not in item

    # 3) 全部 title 是明文(无 enc:v1: 前缀)
    titles = {item["title"] for item in payload["items"]}
    assert titles == {"明文标题 A", "密文标题 B", "明文标题 C"}
    for item in payload["items"]:
        assert not item["title"].startswith(_CIPHERTEXT_PREFIX_V1)

    # 4) folder 字段同样按密文回退(明文 A/C=Notes,密文 B=Work)
    folders = {item["folder"] for item in payload["items"]}
    assert folders == {"Notes", "Work"}


def test_http_api_notes_pending_concurrent_sqlcipher_requests_are_thread_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#97 回归:真实 ThreadingHTTPServer 并发读不得跨线程关闭 SQLCipher 连接."""
    import logging

    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from my_ai_employee.core import keychain
    from my_ai_employee.core.models import Base
    from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine
    from my_ai_employee.db.notes import Note, NoteStore
    from my_ai_employee.menu_bar.note_confirm_service import NoteConfirmServiceImpl

    def fake_get_db_password() -> keychain.KeychainResult:
        return keychain.KeychainResult(ok=True, value="f" * 64)

    monkeypatch.setattr(keychain, "get_db_password", fake_get_db_password)
    engine = make_sqlalchemy_engine(db_path=tmp_path / "dashboard-threading.db")
    assert isinstance(engine.pool, NullPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(
            Note(
                apple_note_id="x-coredata://ICNote/THREADING",
                folder="Notes",
                title="并发待确认",
                body="只读 HTTP 回归数据",
                is_private=0,
                tags=None,
                synced_at_ms=1_700_000_004_000,
                updated_at_ms=1_700_000_004_000,
                sync_status="NEW",
                needs_confirm=1,
                candidate_match_id=None,
            )
        )
        session.commit()

    context = DashboardContext(
        git_head_resolver=lambda: "abc1234",
        keychain_probe=lambda _service: False,
    ).with_note_confirm(NoteConfirmServiceImpl(NoteStore(session_factory)))
    server = create_server(context, host="127.0.0.1", port=0)
    _host, port = server.server_address[:2]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def fetch_pending(_request_id: int) -> tuple[int, dict[str, Any]]:
        return _fetch_json(f"http://127.0.0.1:{port}/api/notes/pending")

    try:
        with (
            caplog.at_level(logging.WARNING, logger="sqlalchemy.pool"),
            ThreadPoolExecutor(max_workers=8) as executor,
        ):
            responses = list(executor.map(fetch_pending, range(32)))
        assert server_thread.is_alive()
    finally:
        server.shutdown()
        server_thread.join(timeout=2.0)
        engine.dispose()

    assert not server_thread.is_alive()
    for status, body in responses:
        assert status == 200
        assert body["count"] == 1
        assert body["items"][0]["title"] == "并发待确认"
    errors = [
        record.getMessage()
        for record in caplog.records
        if "ProgrammingError" in record.getMessage() or "check_same_thread" in record.getMessage()
    ]
    assert not errors, f"撞坑 #97 仍存在 SQLCipher 跨线程异常: {errors}"


def test_http_api_finance_anomalies(running_server: str) -> None:
    status, body = _fetch_json(f"{running_server}/api/finance/anomalies")
    assert status == 200
    assert body["count"] == 1
    assert body["items"][0]["amount"] == 1299


def test_http_api_not_found(running_server: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        _fetch_json(f"{running_server}/api/unknown")
    assert exc.value.code == 404


def test_http_post_not_allowed(running_server: str) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{running_server}/api/status",
        data=b"{}",
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=2)
    assert exc.value.code == 405


def test_http_options_for_static_file_dashboard(running_server: str) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{running_server}/api/status",
        headers={"Origin": "null"},
        method="OPTIONS",
    )
    with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310 — 测试 localhost
        assert resp.status == 204
        assert resp.headers["Access-Control-Allow-Origin"] == "null"
        assert resp.headers["Allow"] == "GET, OPTIONS"


def test_handler_factory_binds_context(dashboard_ctx: DashboardContext) -> None:
    handler_cls = handler_factory(dashboard_ctx)
    assert handler_cls.dashboard_context is dashboard_ctx
