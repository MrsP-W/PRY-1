"""v0.2.66 / Day 9 — 移动伴侣只读真实接入 + 写端点 POST dry-run 映射测试.

边界(沿撞坑 #18 5 门严判 + #64 公共 API 一致性 + #71 已解除):
    - 6 只读端点 HTTP 200 + read_only=true
    - 6 只读端点响应与对应 /api/* 完全一致(契约稳定)
    - 写路径 POST /api/companion/approval-gate/{decide,actions} 精确映射到原生端点(5 门 dry-run)
    - 路径混淆攻击:非白名单路径(如 /api/companion-X)不被识别为白名单
    - 离线兜底契约:read_only=true 字段始终为 True
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Generator
from typing import Any

import pytest

from my_ai_employee.dashboard.approval_gate import CONFIRM_TEXT
from my_ai_employee.dashboard.context import DashboardContext, QualityGateSnapshot
from my_ai_employee.dashboard.server import create_server

# ====== fixtures(沿 test_api.py 范本) ======


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
        quality_gates=QualityGateSnapshot(pytest="2727 passed / 1 skipped"),
    )


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


def _fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310 — 测试 localhost
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# ====== 白名单 6 只读端点映射对照表 ======


_COMPANION_READ_ONLY_ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/companion/status", "/api/status"),
    ("/api/companion/tasks/today", "/api/tasks/today"),
    ("/api/companion/outbox", "/api/outbox"),
    ("/api/companion/notes/pending", "/api/notes/pending"),
    ("/api/companion/finance/anomalies", "/api/finance/anomalies"),
    ("/api/companion/approval-gate/audits", "/api/approval-gate/audits"),
)


# ====== 1) 6 端点 HTTP 200 + read_only=true ======


class TestCompanionReadOnlyEndpoints:
    """6 只读端点 200 + read_only=true(沿撞坑 #18 5 门只读契约)."""

    @pytest.mark.parametrize(
        ("companion_path", "_legacy_path"),
        _COMPANION_READ_ONLY_ROUTES,
        ids=[p[0] for p in _COMPANION_READ_ONLY_ROUTES],
    )
    def test_companion_endpoint_returns_200_and_read_only(
        self,
        running_server: str,
        companion_path: str,
        _legacy_path: str,
    ) -> None:
        status, body = _fetch_json(f"{running_server}{companion_path}")
        assert status == 200
        assert body.get("read_only") is True

    def test_all_companion_routes_count(self, running_server: str) -> None:
        """6 端点全部 200 — 显式遍历(防止 parametrize 误隐藏某个失败)."""
        for companion_path, _ in _COMPANION_READ_ONLY_ROUTES:
            status, body = _fetch_json(f"{running_server}{companion_path}")
            assert status == 200, f"{companion_path} 不是 200"
            assert body.get("read_only") is True, f"{companion_path} read_only != True"


# ====== 2) 6 端点与对应 /api/* 响应一致 ======


class TestCompanionMatchesLegacyApi:
    """6 只读端点响应与对应 /api/* 完全一致(契约稳定 · 撞坑 #64)."""

    @pytest.mark.parametrize(
        ("companion_path", "legacy_path"),
        _COMPANION_READ_ONLY_ROUTES,
        ids=[p[0] for p in _COMPANION_READ_ONLY_ROUTES],
    )
    def test_companion_response_equals_legacy(
        self,
        running_server: str,
        companion_path: str,
        legacy_path: str,
    ) -> None:
        _status_c, companion_body = _fetch_json(f"{running_server}{companion_path}")
        _status_l, legacy_body = _fetch_json(f"{running_server}{legacy_path}")
        # 响应字典完全相等(契约稳定 — 撞坑 #64 公共 API 一致性)
        assert companion_body == legacy_body


# ====== 3) 写路径 POST 精确映射 — 仍走 do_POST 5 门 dry-run ======


class TestCompanionWritePostAliases:
    """写路径 POST 映射到原生 /api/approval-gate/*,响应与原生端点一致(5 门 dry-run)."""

    _DRY_RUN_DECIDE_PAYLOAD: dict[str, Any] = {
        "audit_id": "outbox-1",
        "decision": "approve",
        "confirm_text": CONFIRM_TEXT,
        "dry_run": True,
        "actor": "mobile_companion",
        "reason": "companion dry-run",
    }

    def test_companion_decide_get_returns_404(self, running_server: str) -> None:
        """GET /api/companion/approval-gate/decide → 404(写端点仅 POST)."""
        with pytest.raises(urllib.error.HTTPError) as exc:
            _fetch_json(f"{running_server}/api/companion/approval-gate/decide")
        assert exc.value.code == 404

    def test_companion_actions_get_returns_404(self, running_server: str) -> None:
        """GET /api/companion/approval-gate/actions → 404."""
        with pytest.raises(urllib.error.HTTPError) as exc:
            _fetch_json(f"{running_server}/api/companion/approval-gate/actions")
        assert exc.value.code == 404

    def test_companion_decide_post_matches_native_dry_run(self, running_server: str) -> None:
        """POST companion decide 与原生 decide 响应一致(dry_run, write_executed=False)."""
        companion_status, companion_body = _post_json(
            f"{running_server}/api/companion/approval-gate/decide",
            self._DRY_RUN_DECIDE_PAYLOAD,
        )
        native_status, native_body = _post_json(
            f"{running_server}/api/approval-gate/decide",
            self._DRY_RUN_DECIDE_PAYLOAD,
        )
        assert companion_status == native_status
        assert companion_body == native_body
        if companion_status == 200:
            assert companion_body.get("write_executed") is False
            assert companion_body.get("dry_run") is True

    def test_companion_actions_post_matches_native_dry_run(self, running_server: str) -> None:
        """POST companion actions 与原生 actions 响应一致(dry_run)."""
        payload = {
            "action": "notes.confirm",
            "target_id": "note-1",
            "confirm_text": CONFIRM_TEXT,
            "dry_run": True,
            "actor": "mobile_companion",
            "reason": "companion dry-run",
        }
        companion_status, companion_body = _post_json(
            f"{running_server}/api/companion/approval-gate/actions",
            payload,
        )
        native_status, native_body = _post_json(
            f"{running_server}/api/approval-gate/actions",
            payload,
        )
        assert companion_status == native_status
        assert companion_body == native_body
        if companion_status == 200:
            assert companion_body.get("write_executed") is False


# ====== 4) 路径混淆攻击 — 非白名单前缀不识别 ======


class TestCompanionAliasWhitelistStrict:
    """严判白名单:仅路径完全等于白名单才改写,前缀相近但不在白名单的路径不被识别.

    撞坑:不能用 startswith 一刀切,必须用 dict 精确匹配。
    """

    @pytest.mark.parametrize(
        "bogus_path",
        [
            "/api/companion-status",  # 无斜杠前缀混淆
            "/api/companion/statusX",  # 尾部追加
            "/api/companionX/status",  # 中间插入
            "/api/companionstatus",  # 完全拼接
            "/api/companion/",  # 空 action
            "/api/companion",
        ],
    )
    def test_bogus_path_not_aliased(self, running_server: str, bogus_path: str) -> None:
        """所有非白名单路径返回 404(不被识别为只读端点)."""
        with pytest.raises(urllib.error.HTTPError) as exc:
            _fetch_json(f"{running_server}{bogus_path}")
        assert exc.value.code == 404


# ====== 5) 移动伴侣契约稳定性 — 模块导出白名单键 ======


class TestCompanionWhitelistExported:
    """handlers.py 内部 _COMPANION_READ_ONLY_ALIASES 与契约模块 mobile_companion.py 一致.

    沿撞坑 #64 公共 API 一致性:server 路由白名单必须与契约 COMPANION_ROUTES 中
    requires_write_gate=False 的 GET 端点集合对齐。
    """

    def test_handler_aliases_match_contract_read_only_gets(self) -> None:
        from my_ai_employee.api.mobile_companion import (
            COMPANION_ROUTES,
            CompanionMethod,
        )
        from my_ai_employee.dashboard.handlers import (
            _COMPANION_READ_ONLY_ALIASES,
        )

        contract_read_only_paths = {
            r.path
            for r in COMPANION_ROUTES
            if r.method == CompanionMethod.GET and not r.requires_write_gate
        }
        handler_paths = set(_COMPANION_READ_ONLY_ALIASES.keys())
        # 契约有 6 只读,handler 必须包含全部 6 路径
        assert contract_read_only_paths == handler_paths
        assert len(handler_paths) == 6


# ====== 6) 离线兜底契约字段(撞坑 #65 + 契约 §4) ======


class TestCompanionReadOnlyOfflineFallbackContract:
    """所有 6 只读端点响应 read_only=True — 移动伴侣可缓存,断网时按钮置灰."""

    @pytest.mark.parametrize(
        "companion_path",
        [p[0] for p in _COMPANION_READ_ONLY_ROUTES],
        ids=[p[0] for p in _COMPANION_READ_ONLY_ROUTES],
    )
    def test_read_only_field_present_and_true(
        self, running_server: str, companion_path: str
    ) -> None:
        _status, body = _fetch_json(f"{running_server}{companion_path}")
        assert "read_only" in body
        assert body["read_only"] is True
