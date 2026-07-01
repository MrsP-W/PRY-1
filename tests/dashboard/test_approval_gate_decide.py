"""v0.2.57 / Day 8 候选 A — 1-click 审批 /decide 端点契约 + 5 门严判测试.

本测试覆盖:
    - evaluate_decide_request 的 8 路径决策矩阵(沿撞坑 #68 决策矩阵与可视化拆分模式)
    - decision 映射(approve → outbox.approve, reject → outbox.cancel)
    - 严判:decision 必填 + 白名单、audit_id 必填 + 长度上限、dry_run bool 严判
    - 第一道门 DASHBOARD_WRITE_API=1 严判(未设 → 403)
    - 第二道门 confirm_text=CONFIRM_WRITE 严判
    - 第三道门 BUSINESS_WRITER_ENABLED=1 严判
    - 路径 3.5(dry_run=True + writer 启用)→ 200 dry-run-ready
    - 路径 4(dry_run=False + writer 启用)→ 200 实写入口(handler 委派 BusinessWriterImpl)
    - handler POST /api/approval-gate/decide 路由表测试
    - 5 门集成:同 payload 多次提交都稳定

撞坑 #71 解除(业务代码改动日)· 撞坑 #59 红线维持(不自动真发邮件)·
撞坑 #65 沿用(BusinessWriter + AuditContext)。
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import ThreadingHTTPServer

import pytest

from my_ai_employee.dashboard.action_contracts import (
    ACTION_OUTBOX_APPROVE,
    ACTION_OUTBOX_CANCEL,
)
from my_ai_employee.dashboard.approval_gate import (
    CONFIRM_TEXT,
    CONTRACT_VERSION,
    DECISION_OUTBOX_APPROVE,
    DECISION_OUTBOX_REJECT,
    SUPPORTED_DECISIONS,
    evaluate_decide_request,
)
from my_ai_employee.dashboard.context import DashboardContext

# ===== 单元: evaluate_decide_request =====


class TestEvaluateDecideRequest:
    """evaluate_decide_request 单测 — 5 门 + 决策映射 + 严判."""

    def test_contract_version_is_v0_2_57(self) -> None:
        """契约版本号必须为 v0.2.57(Day 8 候选 A 标志)."""
        assert CONTRACT_VERSION == "v0.2.57"

    def test_supported_decisions_constant(self) -> None:
        """SUPPORTED_DECISIONS 必须 = (approve, reject),顺序稳定."""
        assert SUPPORTED_DECISIONS == (DECISION_OUTBOX_APPROVE, DECISION_OUTBOX_REJECT)

    # ---- 路径 1: write_disabled (DASHBOARD_WRITE_API 未设) ----

    def test_path1_write_disabled_returns_403(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
            },
            write_enabled=False,
        )
        assert status == HTTPStatus.FORBIDDEN
        assert payload["error"] == "write_disabled"
        assert payload["write_executed"] is False
        assert payload["approval_gate_passed"] is False
        # Day 8 候选 A 扩展字段
        assert payload["endpoint"] == "decide"
        assert payload["decision"] == "approve"
        assert payload["audit_id"] == "outbox-1"
        assert payload["mapped_action"] == ACTION_OUTBOX_APPROVE

    def test_path1_write_disabled_with_reject_maps_to_cancel(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-2",
                "decision": "reject",
                "confirm_text": CONFIRM_TEXT,
            },
            write_enabled=False,
        )
        assert status == HTTPStatus.FORBIDDEN
        assert payload["mapped_action"] == ACTION_OUTBOX_CANCEL

    # ---- 路径 2: 字段严判失败 ----

    def test_path2_missing_decision_returns_400(self) -> None:
        status, payload = evaluate_decide_request(
            {"audit_id": "outbox-1", "confirm_text": CONFIRM_TEXT},
            write_enabled=True,
        )
        assert status == HTTPStatus.BAD_REQUEST
        assert payload["error"] == "missing_decision"
        # 空字符串被规整为 None(沿 _decide_error:"decision or None")
        assert payload["decision"] is None
        assert payload["audit_id"] == "outbox-1"
        assert payload["mapped_action"] is None

    def test_path2_unsupported_decision_returns_400(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "maybe",
                "confirm_text": CONFIRM_TEXT,
            },
            write_enabled=True,
        )
        assert status == HTTPStatus.BAD_REQUEST
        assert payload["error"] == "unsupported_decision"
        assert payload["decision"] == "maybe"
        assert payload["mapped_action"] is None

    def test_path2_missing_audit_id_returns_400(self) -> None:
        status, payload = evaluate_decide_request(
            {"decision": "approve", "confirm_text": CONFIRM_TEXT},
            write_enabled=True,
        )
        assert status == HTTPStatus.BAD_REQUEST
        assert payload["error"] == "missing_audit_id"
        assert payload["decision"] == "approve"
        assert payload["mapped_action"] == ACTION_OUTBOX_APPROVE  # 决策已映射

    def test_path2_audit_id_too_long_returns_400(self) -> None:
        long_id = "x" * 200
        status, payload = evaluate_decide_request(
            {
                "audit_id": long_id,
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
            },
            write_enabled=True,
        )
        assert status == HTTPStatus.BAD_REQUEST
        assert payload["error"] == "audit_id_too_long"
        # 回显截断到 80
        assert payload["audit_id"] is not None
        assert len(payload["audit_id"]) == 80

    def test_path2_invalid_dry_run_type_returns_400(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": "yes",  # 错:不是 bool
            },
            write_enabled=True,
        )
        assert status == HTTPStatus.BAD_REQUEST
        assert payload["error"] == "invalid_dry_run"

    # ---- 路径 2: 第二道门 confirm_text 错 ----

    def test_path2_wrong_confirm_text_returns_403(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": "WRONG",
            },
            write_enabled=True,
        )
        assert status == HTTPStatus.FORBIDDEN
        assert payload["error"] == "confirmation_required"
        assert payload["decision"] == "approve"

    # ---- 路径 3: writer 未启用 → 501 ----

    def test_path3_writer_disabled_returns_501(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
            write_enabled=True,
            writer_enabled=False,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.NOT_IMPLEMENTED
        assert payload["error"] == "write_not_implemented"
        assert payload["mapped_action"] == ACTION_OUTBOX_APPROVE

    def test_path3_writer_env_disabled_impl_true_still_501(self) -> None:
        """撞坑 #68 决策矩阵:env 关闭时,即便 impl 注入,仍 501。"""
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "reject",
                "confirm_text": CONFIRM_TEXT,
            },
            write_enabled=True,
            writer_enabled=False,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.NOT_IMPLEMENTED
        assert payload["mapped_action"] == ACTION_OUTBOX_CANCEL

    def test_path3_impl_not_injected_returns_501(self) -> None:
        """撞坑 #68 + v0.2.53.30:writer_impl_injected not True → 501。"""
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=False,
        )
        assert status == HTTPStatus.NOT_IMPLEMENTED

    # ---- 路径 3.5: dry-run ready (writer 启用 + dry_run=True) ----

    def test_path3_5_dry_run_ready_returns_200(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
                "actor": "tester",
                "reason": "unit test dry-run",
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.OK
        assert payload["approval_gate_passed"] is True
        assert payload["dry_run"] is True
        assert payload["write_executed"] is False
        # 沿 evaluate_writer_dry_run 字段
        assert payload["write_enabled"] is True
        assert payload["writer_enabled"] is True
        # Day 8 候选 A 扩展字段
        assert payload["endpoint"] == "decide"
        assert payload["decision"] == "approve"
        assert payload["audit_id"] == "outbox-1"
        assert payload["mapped_action"] == ACTION_OUTBOX_APPROVE

    def test_path3_5_reject_decision_maps_to_cancel(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-2",
                "decision": "reject",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.OK
        assert payload["decision"] == "reject"
        assert payload["mapped_action"] == ACTION_OUTBOX_CANCEL

    def test_path3_5_actor_reason_carried(self) -> None:
        """actor / reason 字段必须由 payload 透传(沿 v0.2.53.11 audit 字段)."""
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-3",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
                "actor": "Mr-PRY",
                "reason": "Day 8 候选 A 测试",
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.OK
        assert payload["audit"]["actor"] == "Mr-PRY"
        assert payload["audit"]["reason"] == "Day 8 候选 A 测试"

    def test_path3_5_actor_truncated_to_80(self) -> None:
        """actor 长度上限 80 字符(沿 AuditContext.MAX_ACTOR_LEN)."""
        long_actor = "x" * 200
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
                "actor": long_actor,
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.OK
        assert len(payload["audit"]["actor"]) == 80

    def test_path3_5_reason_truncated_to_240(self) -> None:
        """reason 长度上限 240 字符(沿 AuditContext.MAX_REASON_LEN)."""
        long_reason = "y" * 500
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
                "reason": long_reason,
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.OK
        assert len(payload["audit"]["reason"]) == 240

    # ---- 路径 4: 实写入口(dry_run=False + writer 启用) ----

    def test_path4_dry_run_false_returns_200(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": False,
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.OK
        assert payload["dry_run"] is False
        # 沿 evaluate_writer_dry_run:实写入口返回 would_allow=True
        assert payload["would_allow"] is True
        assert payload["mapped_action"] == ACTION_OUTBOX_APPROVE
        # 实写由 BusinessWriterImpl 5 门严判(此处只是 ApprovalGate 通过)
        assert payload["write_executed"] is False  # 写动作实际执行由 handler 委派

    def test_path4_reject_dry_run_false(self) -> None:
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "reject",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": False,
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.OK
        assert payload["would_allow"] is True
        assert payload["mapped_action"] == ACTION_OUTBOX_CANCEL


# ===== 集成: handler POST /api/approval-gate/decide =====


def _start_dashboard_server(
    ctx: DashboardContext, port: int = 0
) -> tuple[str, ThreadingHTTPServer]:
    """测试用 helper — 启动 Dashboard server 并返回 base_url."""
    import socket
    import threading
    import time

    from my_ai_employee.dashboard.server import create_server

    server = create_server(ctx, port=port)
    host_raw, bound_port = server.server_address[:2]
    # server_address[0] 在 ThreadingHTTPServer 上是 str(server.py 显式传 str)
    host = host_raw if isinstance(host_raw, str) else host_raw.decode("utf-8")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # 等待 server 起来
    for _ in range(20):
        try:
            with socket.create_connection((host, bound_port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    return f"http://{host}:{bound_port}", server


class TestHandlerDecideEndpoint:
    """handler POST /api/approval-gate/decide 路由表测试.

    沿 v0.2.53.11 + v0.2.57 协议:
        - 默认 write_enabled=False → 403 write_disabled
        - 缺 decision → 400 missing_decision
        - 缺 audit_id → 400 missing_audit_id
        - 错 confirm_text → 403 confirmation_required
        - 5 门齐全 + dry_run=True → 200 dry-run-ready
    """

    def test_post_decide_default_returns_403(self) -> None:
        """未设 DASHBOARD_WRITE_API → 403."""
        import os
        import urllib.error

        from my_ai_employee.dashboard.context import DashboardContext

        os.environ.pop("DASHBOARD_WRITE_API", None)
        os.environ.pop("BUSINESS_WRITER_ENABLED", None)
        ctx = DashboardContext.default()
        base_url, server = _start_dashboard_server(ctx)
        try:
            import urllib.request

            req = urllib.request.Request(
                f"{base_url}/api/approval-gate/decide",
                data=json.dumps(
                    {
                        "audit_id": "outbox-1",
                        "decision": "approve",
                        "confirm_text": CONFIRM_TEXT,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=2)
            assert exc_info.value.code == HTTPStatus.FORBIDDEN
            body = json.loads(exc_info.value.read().decode("utf-8"))
            assert body["error"] == "write_disabled"
            assert body["endpoint"] == "decide"
            assert body["decision"] == "approve"
        finally:
            server.shutdown()
            server.server_close()

    def test_post_decide_missing_decision_returns_400(self) -> None:
        """write_enabled=True + 缺 decision → 400."""
        import os
        import urllib.error

        from my_ai_employee.dashboard.context import DashboardContext

        os.environ["DASHBOARD_WRITE_API"] = "1"
        try:
            ctx = DashboardContext.default()
            base_url, server = _start_dashboard_server(ctx)
            try:
                import urllib.request

                req = urllib.request.Request(
                    f"{base_url}/api/approval-gate/decide",
                    data=json.dumps({"audit_id": "outbox-1", "confirm_text": CONFIRM_TEXT}).encode(
                        "utf-8"
                    ),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with pytest.raises(urllib.error.HTTPError) as exc_info:
                    urllib.request.urlopen(req, timeout=2)
                assert exc_info.value.code == HTTPStatus.BAD_REQUEST
                body = json.loads(exc_info.value.read().decode("utf-8"))
                assert body["error"] == "missing_decision"
            finally:
                server.shutdown()
                server.server_close()
        finally:
            os.environ.pop("DASHBOARD_WRITE_API", None)

    def test_post_decide_options_allows_post(self) -> None:
        """OPTIONS /api/approval-gate/decide 必须声明 POST 允许."""
        from my_ai_employee.dashboard.context import DashboardContext

        ctx = DashboardContext.default()
        base_url, server = _start_dashboard_server(ctx)
        try:
            import urllib.request

            req = urllib.request.Request(f"{base_url}/api/approval-gate/decide", method="OPTIONS")
            with urllib.request.urlopen(req, timeout=2) as resp:
                assert resp.status == HTTPStatus.NO_CONTENT
                allow = resp.headers.get("Allow", "")
                assert "POST" in allow
        finally:
            server.shutdown()
            server.server_close()

    def test_post_decide_unsupported_decision_returns_400(self) -> None:
        """write_enabled=True + decision=maybe → 400."""
        import os
        import urllib.error

        from my_ai_employee.dashboard.context import DashboardContext

        os.environ["DASHBOARD_WRITE_API"] = "1"
        try:
            ctx = DashboardContext.default()
            base_url, server = _start_dashboard_server(ctx)
            try:
                import urllib.request

                req = urllib.request.Request(
                    f"{base_url}/api/approval-gate/decide",
                    data=json.dumps(
                        {
                            "audit_id": "outbox-1",
                            "decision": "maybe",
                            "confirm_text": CONFIRM_TEXT,
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with pytest.raises(urllib.error.HTTPError) as exc_info:
                    urllib.request.urlopen(req, timeout=2)
                assert exc_info.value.code == HTTPStatus.BAD_REQUEST
                body = json.loads(exc_info.value.read().decode("utf-8"))
                assert body["error"] == "unsupported_decision"
            finally:
                server.shutdown()
                server.server_close()
        finally:
            os.environ.pop("DASHBOARD_WRITE_API", None)


# ===== 5 门集成稳定性测试 =====


class TestFiveGatesStability:
    """5 门集成稳定性 — 同 payload 多次提交都稳定(撞坑 #50 漂移防御)."""

    @pytest.mark.parametrize(
        "decision,expected_action",
        [
            ("approve", ACTION_OUTBOX_APPROVE),
            ("reject", ACTION_OUTBOX_CANCEL),
        ],
    )
    def test_dry_run_decision_stable(self, decision: str, expected_action: str) -> None:
        """同一 decision 5 次提交必须稳定(5 门一致)."""
        for _ in range(5):
            status, payload = evaluate_decide_request(
                {
                    "audit_id": "outbox-1",
                    "decision": decision,
                    "confirm_text": CONFIRM_TEXT,
                    "dry_run": True,
                },
                write_enabled=True,
                writer_enabled=True,
                writer_impl_injected=True,
            )
            assert status == HTTPStatus.OK
            assert payload["mapped_action"] == expected_action
            assert payload["decision"] == decision

    def test_response_field_set_stable(self) -> None:
        """200 响应字段集合必须稳定(便于前端解析)."""
        status, payload = evaluate_decide_request(
            {
                "audit_id": "outbox-1",
                "decision": "approve",
                "confirm_text": CONFIRM_TEXT,
                "dry_run": True,
            },
            write_enabled=True,
            writer_enabled=True,
            writer_impl_injected=True,
        )
        assert status == HTTPStatus.OK
        required_keys = {
            "endpoint",
            "decision",
            "audit_id",
            "mapped_action",
            "approval_gate_passed",
            "would_allow",
            "write_executed",
            "dry_run",
            "error",
            "reason",
            "action",
            "target_id",
            "action_contract",
            "audit",
            "contract_version",
        }
        assert required_keys.issubset(set(payload.keys()))


# ===== v0.2.57 / Day 8 候选 B — decide audit 落档链测试 =====


class TestDecideAuditChain:
    """v0.2.57 / Day 8 候选 B — /api/approval-gate/decide → audit_store 落档链.

    验证 4 个不变量:
        1. AuditRecord 新增 `decision` 字段(可选 None,严判 "approve"/"reject")
        2. AuditRecord.to_dict() 暴露 `decision` 字段
        3. InMemoryApprovalGateAuditStore 能记录带 decision 的 audit
        4. BusinessWriterImpl._record_audit 新增 decision 关键字参数
    """

    def test_audit_record_default_decision_is_none(self) -> None:
        """AuditRecord 默认 decision=None(向后兼容 4 类 action)."""
        from my_ai_employee.menu_bar.approval_gate_audit import AuditRecord

        rec = AuditRecord(
            action="approve_outbox",
            target_id="outbox-1",
            actor="tester",
            reason="",
            write_executed=True,
            affected_id="1",
            error=None,
            executed_at_ms=1234567890000,
        )
        assert rec.decision is None
        d = rec.to_dict()
        assert d["decision"] is None

    def test_audit_record_with_decision_approve(self) -> None:
        """AuditRecord 可显式设置 decision='approve'."""
        from my_ai_employee.menu_bar.approval_gate_audit import AuditRecord

        rec = AuditRecord(
            action="approve_outbox",
            target_id="outbox-1",
            actor="Mr-PRY",
            reason="Day 8 候选 B 1-click 批准",
            write_executed=True,
            affected_id="42",
            error=None,
            executed_at_ms=1234567890000,
            decision="approve",
        )
        assert rec.decision == "approve"
        d = rec.to_dict()
        assert d["decision"] == "approve"

    def test_audit_record_with_decision_reject(self) -> None:
        """AuditRecord 可显式设置 decision='reject'."""
        from my_ai_employee.menu_bar.approval_gate_audit import AuditRecord

        rec = AuditRecord(
            action="cancel_outbox",
            target_id="outbox-2",
            actor="Mr-PRY",
            reason="Day 8 候选 B 1-click 拒绝",
            write_executed=True,
            affected_id="43",
            error=None,
            executed_at_ms=1234567890000,
            decision="reject",
        )
        assert rec.decision == "reject"

    def test_audit_record_rejects_invalid_decision(self) -> None:
        """AuditRecord decision 严判:仅 'approve' / 'reject' / None."""
        from my_ai_employee.menu_bar.approval_gate_audit import AuditRecord

        with pytest.raises(ValueError, match="decision 必须为"):
            AuditRecord(
                action="approve_outbox",
                target_id="outbox-1",
                actor="tester",
                reason="",
                write_executed=True,
                affected_id="1",
                error=None,
                executed_at_ms=1234567890000,
                decision="maybe",  # 非法
            )

    def test_inmemory_audit_store_records_decision(self) -> None:
        """InMemoryApprovalGateAuditStore 能记录带 decision 的 audit."""
        from my_ai_employee.menu_bar.approval_gate_audit import (
            AuditRecord,
            InMemoryApprovalGateAuditStore,
        )

        store = InMemoryApprovalGateAuditStore()
        assert store.is_enabled() is True
        # 记录 1 条带 decision=approve 的 audit
        rec = AuditRecord(
            action="approve_outbox",
            target_id="outbox-1",
            actor="Mr-PRY",
            reason="Day 8 候选 B 1-click 批准",
            write_executed=True,
            affected_id="42",
            error=None,
            executed_at_ms=1234567890000,
            decision="approve",
        )
        result = store.record(rec)
        assert result.success is True
        assert result.audit_id == "audit:1"
        # list_recent 必须返回带 decision 字段
        recent = store.list_recent(limit=10)
        assert len(recent) == 1
        assert recent[0]["decision"] == "approve"
        assert recent[0]["action"] == "approve_outbox"

    def test_business_writer_impl_record_audit_accepts_decision(self) -> None:
        """BusinessWriterImpl._record_audit 接受 decision 关键字参数."""
        from my_ai_employee.dashboard.business_writer import AuditContext
        from my_ai_employee.dashboard.business_writer_impl import BusinessWriterImpl
        from my_ai_employee.menu_bar.approval_gate_audit import InMemoryApprovalGateAuditStore

        audit_store = InMemoryApprovalGateAuditStore()
        writer = BusinessWriterImpl(
            session_factory=None,
            outbox_store=None,
            note_confirm_service=None,
            anomaly_dismissal_service=None,
            audit_store=audit_store,
            real_write_handler_enabled=False,
            enable_path_4_write=False,
        )
        # 调用 _record_audit 带 decision
        audit_id = writer._record_audit(
            action="approve_outbox",
            target_id="outbox-1",
            audit=AuditContext(actor="Mr-PRY", reason="1-click 批准", source="dashboard"),
            write_executed=True,
            affected_id="42",
            error=None,
            decision="approve",
        )
        assert audit_id == "audit:1"
        recent = audit_store.list_recent(limit=10)
        assert recent[0]["decision"] == "approve"
        assert recent[0]["actor"] == "Mr-PRY"
        assert recent[0]["affected_id"] == "42"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
