"""v0.2.53.9 — GET /api/reports 集成测试.

边界(沿 v0.2.53 范本):
    - 只读文件系统扫描 · 不写 · 不触发 DB I/O
    - 静默降级:目录不存在 / 权限错 / 文件过大 → 跳过
    - 不真发邮件 / 不读 Keychain 明文 / 不 kickstart launchd / 不打 tag
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Generator
from http.server import HTTPServer
from pathlib import Path
from typing import Any

import pytest

from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.handlers import handler_factory
from my_ai_employee.dashboard.reports import (
    _extract_date,
    _extract_status,
    _extract_title,
    _resolve_report_path,
    read_report_preview,
    scan_reports,
)
from my_ai_employee.dashboard.responses import build_report_preview_payload, build_reports_payload

# ===== 单元测试:scanner helpers =====


class TestExtractDate:
    """_extract_date 范本 — 2 种 pattern(YYYY-MM-DD / YYYYMMDD)."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("2026-06-25-monthly-review.md", "2026-06-25"),
            ("v0.2.53.6-outbox-2026-06-25.md", "2026-06-25"),
            ("spike_send_100_20260625_163607.md", "2026-06-25"),
            ("D3.1-数据层基础完成.md", None),
            ("architecture.md", None),
            ("2026-13-99-bad.md", None),  # 无效月份/日期
        ],
    )
    def test_extract_date(self, name: str, expected: str | None) -> None:
        assert _extract_date(name) == expected


class TestExtractStatus:
    """_extract_status 范本 — 扫前 N 行匹配状态关键词."""

    def test_done_with_checkmark(self, tmp_path: Path) -> None:
        path = tmp_path / "done.md"
        path.write_text(
            "# Test\n✅ 已落地\n✅ 完成\n✅ 已收口\n",
            encoding="utf-8",
        )
        assert _extract_status(path) == "done"

    def test_active_with_green_circle(self, tmp_path: Path) -> None:
        path = tmp_path / "active.md"
        path.write_text("# Test\n🟢 进行中\n", encoding="utf-8")
        assert _extract_status(path) == "active"

    def test_pending_with_yellow_circle(self, tmp_path: Path) -> None:
        path = tmp_path / "pending.md"
        path.write_text("# Test\n🟡 延后\n", encoding="utf-8")
        assert _extract_status(path) == "pending"

    def test_failed_with_red_x(self, tmp_path: Path) -> None:
        path = tmp_path / "failed.md"
        path.write_text("# Test\n❌ 未通过\n", encoding="utf-8")
        assert _extract_status(path) == "failed"

    def test_unknown_when_no_keywords(self, tmp_path: Path) -> None:
        path = tmp_path / "plain.md"
        path.write_text("# Test\njust plain text\n", encoding="utf-8")
        assert _extract_status(path) == "unknown"

    def test_missing_file_returns_unknown(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.md"
        assert _extract_status(path) == "unknown"


class TestExtractTitle:
    """_extract_title 范本 — 找第一行 H1."""

    def test_first_h1(self, tmp_path: Path) -> None:
        path = tmp_path / "test.md"
        path.write_text("# My Title\n\nbody\n", encoding="utf-8")
        assert _extract_title(path) == "My Title"

    def test_first_hash_line_wins_regardless_of_level(self, tmp_path: Path) -> None:
        """`_extract_title` 返回第一行遇到的 `#`(H2 也算,不严判 H1)."""
        path = tmp_path / "test.md"
        path.write_text("## Second header\n# First header\n", encoding="utf-8")
        assert _extract_title(path) == "Second header"

    def test_no_h1_falls_back_to_stem(self, tmp_path: Path) -> None:
        path = tmp_path / "fallback-name.md"
        path.write_text("no headers here\n", encoding="utf-8")
        assert _extract_title(path) == "fallback name"

    def test_empty_file_returns_stem(self, tmp_path: Path) -> None:
        path = tmp_path / "empty-name.md"
        path.write_text("", encoding="utf-8")
        assert _extract_title(path) == "empty name"


# ===== 集成测试:scan_reports =====


class TestScanReports:
    """scan_reports 范本 — 扫描 docs/ + reports/ + output/ 3 类目录."""

    def _setup_fake_tree(self, tmp_path: Path) -> None:
        """构造最小可扫描目录结构."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "v0.2.53.9-test-2026-06-25.md").write_text(
            "# 测试报告\n✅ 已完成\n",
            encoding="utf-8",
        )
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "D-Test-Done.md").write_text(
            "# D 测试\n✅ 已收口\n",
            encoding="utf-8",
        )
        output = tmp_path / "output"
        output.mkdir()
        spike = output / "spike"
        spike.mkdir()
        (spike / "spike_send_100_20260625.md").write_text(
            "# Spike 测试\n✅ 已落地\n",
            encoding="utf-8",
        )
        agent_day = output / "2026-06-25"
        agent_day.mkdir()
        (agent_day / "morning-news.md").write_text(
            "# 晨报\n🟢 进行中\n",
            encoding="utf-8",
        )

    def test_scan_finds_all_three_types(self, tmp_path: Path) -> None:
        self._setup_fake_tree(tmp_path)
        oversized_paths = {
            "docs/too-large.md",
            "reports/too-large.md",
            "output/2026-07-17/too-large.json",
        }
        for rel_path in oversized_paths:
            path = tmp_path / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x" * (256 * 1024 + 1), encoding="utf-8")

        entries = scan_reports(project_root=tmp_path, limit=20)
        types = {e.type for e in entries}
        assert types == {"doc", "phase_report", "spike", "agent_output"}
        assert {entry.path for entry in entries}.isdisjoint(oversized_paths)

    def test_scan_skips_symlink_target_outside_project_root(self, tmp_path: Path) -> None:
        """报告扫描不得经 docs/ 内的 symlink 暴露项目根外元数据。"""
        project_root = tmp_path / "project"
        project_root.mkdir()
        self._setup_fake_tree(project_root)
        external_report = tmp_path / "outside.md"
        external_report.write_text("# 项目外报告\n✅ 已完成\n", encoding="utf-8")
        (project_root / "docs" / "outside-link.md").symlink_to(external_report)

        paths = {entry.path for entry in scan_reports(project_root=project_root, limit=20)}

        assert "docs/v0.2.53.9-test-2026-06-25.md" in paths
        assert "docs/outside-link.md" not in paths

    def test_entries_have_required_fields(self, tmp_path: Path) -> None:
        self._setup_fake_tree(tmp_path)
        entries = scan_reports(project_root=tmp_path, limit=20)
        for e in entries:
            assert e.path
            assert e.type in {"doc", "phase_report", "spike", "agent_output"}
            assert e.title
            assert e.status in {"done", "active", "pending", "failed", "draft", "unknown"}
            assert e.size_bytes >= 0

    def test_type_filter(self, tmp_path: Path) -> None:
        self._setup_fake_tree(tmp_path)
        entries = scan_reports(project_root=tmp_path, limit=20, type_filter="spike")
        assert all(e.type == "spike" for e in entries)
        assert len(entries) == 1

    def test_limit_caps_results(self, tmp_path: Path) -> None:
        self._setup_fake_tree(tmp_path)
        entries = scan_reports(project_root=tmp_path, limit=2)
        assert len(entries) <= 2

    def test_missing_docs_dir_no_crash(self, tmp_path: Path) -> None:
        # 只有 output 目录
        output = tmp_path / "output"
        output.mkdir()
        entries = scan_reports(project_root=tmp_path, limit=20)
        # 不会崩,且可能返回空(因为 output 也没有 spike 子目录)
        assert isinstance(entries, list)

    def test_nonexistent_project_root_no_crash(self, tmp_path: Path) -> None:
        # tmp_path 本身是 root,但 docs/reports/output 都不存在
        entries = scan_reports(project_root=tmp_path, limit=20)
        assert entries == []

    def test_zero_results_for_unknown_filter(self, tmp_path: Path) -> None:
        self._setup_fake_tree(tmp_path)
        entries = scan_reports(project_root=tmp_path, limit=20, type_filter="nonexistent")
        assert entries == []

    def test_path_is_relative_posix(self, tmp_path: Path) -> None:
        self._setup_fake_tree(tmp_path)
        entries = scan_reports(project_root=tmp_path, limit=20)
        for e in entries:
            # 不应包含绝对路径前缀
            assert not e.path.startswith("/")
            # 应使用 POSIX 分隔符
            assert "\\" not in e.path


# ===== 集成测试:build_reports_payload =====


class TestBuildReportsPayload:
    """build_reports_payload 范本 — 响应格式 + 边界."""

    def test_returns_required_keys(self) -> None:
        ctx = DashboardContext.default()
        payload = build_reports_payload(ctx, limit=10)
        assert payload["read_only"] is True
        assert "count" in payload
        assert "items" in payload
        assert isinstance(payload["count"], int)
        assert isinstance(payload["items"], list)

    def test_items_shape(self) -> None:
        ctx = DashboardContext.default()
        payload = build_reports_payload(ctx, limit=5)
        for item in payload["items"]:
            assert set(item.keys()) == {
                "path",
                "type",
                "title",
                "date",
                "status",
                "size_bytes",
            }

    def test_limit_zero_defaults_to_safe(self) -> None:
        ctx = DashboardContext.default()
        payload = build_reports_payload(ctx, limit=0)
        # limit=0 应降级到 1(避免除零 / 空响应)
        assert payload["count"] >= 1

    def test_limit_negative_defaults_to_safe(self) -> None:
        ctx = DashboardContext.default()
        payload = build_reports_payload(ctx, limit=-5)
        assert payload["count"] >= 1

    def test_type_filter_in_payload(self) -> None:
        ctx = DashboardContext.default()
        payload = build_reports_payload(ctx, limit=50, type_filter="doc")
        for item in payload["items"]:
            assert item["type"] == "doc"

    def test_real_project_has_reports(self) -> None:
        """实际项目根目录扫描,应能扫到 docs/ + reports/ 内容."""
        ctx = DashboardContext.default()
        payload = build_reports_payload(ctx, limit=50)
        # 实际项目有 docs/ 和 reports/ 大量内容
        assert payload["count"] >= 1
        # 至少包含 doc 类型
        assert any(item["type"] == "doc" for item in payload["items"])


# ===== 集成测试:HTTP endpoint /api/reports =====


@pytest.fixture
def http_server() -> Generator[tuple[str, HTTPServer], None, None]:
    """启动后台 HTTP server 在空闲端口,127.0.0.1."""
    ctx = DashboardContext.default()
    handler_cls = handler_factory(ctx)
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    addr = server.server_address
    host_str = str(addr[0])
    port = int(addr[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host_str}:{port}", server
    server.shutdown()
    server.server_close()


def _get_json(url: str) -> dict[str, Any]:
    """GET URL → JSON dict(失败抛异常)."""
    with urllib.request.urlopen(url, timeout=5) as resp:
        data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return data


class TestReportsHttpEndpoint:
    """GET /api/reports HTTP 端点测试."""

    def test_endpoint_returns_ok(self, http_server: tuple[str, HTTPServer]) -> None:
        base, _ = http_server
        payload = _get_json(f"{base}/api/reports?limit=10")
        assert payload["read_only"] is True
        assert isinstance(payload["items"], list)

    def test_endpoint_with_limit(self, http_server: tuple[str, HTTPServer]) -> None:
        base, _ = http_server
        payload = _get_json(f"{base}/api/reports?limit=3")
        assert payload["count"] <= 3

    def test_endpoint_with_type_filter(self, http_server: tuple[str, HTTPServer]) -> None:
        base, _ = http_server
        payload = _get_json(f"{base}/api/reports?limit=20&type=doc")
        for item in payload["items"]:
            assert item["type"] == "doc"

    def test_endpoint_invalid_type_filter_returns_empty(
        self, http_server: tuple[str, HTTPServer]
    ) -> None:
        base, _ = http_server
        payload = _get_json(f"{base}/api/reports?type=nonexistent_type")
        assert payload["count"] == 0
        assert payload["items"] == []


# ===== v0.2.53.10 报告预览 =====


class TestResolveReportPath:
    """路径严判 — 禁止穿越 + 仅允许白名单目录."""

    def test_allows_docs_md(self, tmp_path: Path) -> None:
        f = tmp_path / "docs" / "test.md"
        f.parent.mkdir(parents=True)
        f.write_text("# hi", encoding="utf-8")
        assert _resolve_report_path("docs/test.md", tmp_path) == f.resolve()

    def test_rejects_traversal(self, tmp_path: Path) -> None:
        assert _resolve_report_path("../etc/passwd", tmp_path) is None
        assert _resolve_report_path("docs/../../secret.md", tmp_path) is None

    def test_rejects_unknown_prefix(self, tmp_path: Path) -> None:
        f = tmp_path / "secret.md"
        f.write_text("# x", encoding="utf-8")
        assert _resolve_report_path("secret.md", tmp_path) is None


class TestReadReportPreview:
    """read_report_preview — 截断预览 + 元数据."""

    def test_preview_truncated_flag(self, tmp_path: Path) -> None:
        f = tmp_path / "docs" / "big.md"
        f.parent.mkdir(parents=True)
        f.write_text("x" * 100, encoding="utf-8")
        result = read_report_preview("docs/big.md", project_root=tmp_path, max_bytes=50)
        assert result is not None
        assert result["truncated"] is True
        assert len(str(result["preview"])) == 50

    def test_preview_missing_returns_none(self, tmp_path: Path) -> None:
        assert read_report_preview("docs/missing.md", project_root=tmp_path) is None


class TestBuildReportPreviewPayload:
    def test_payload_shape(self, tmp_path: Path) -> None:
        f = tmp_path / "reports" / "sample.md"
        f.parent.mkdir(parents=True)
        f.write_text("# Sample\n\n✅ 已落地", encoding="utf-8")
        with pytest.MonkeyPatch.context() as mp:
            mp.chdir(tmp_path)
            payload = build_report_preview_payload("reports/sample.md")
        assert payload is not None
        assert payload["read_only"] is True
        assert "preview" in payload
        assert payload["type"] == "phase_report"


class TestReportPreviewHttpEndpoint:
    def test_preview_ok(self, http_server: tuple[str, HTTPServer], tmp_path: Path) -> None:
        f = tmp_path / "docs" / "preview-test.md"
        f.parent.mkdir(parents=True)
        f.write_text("# Preview Test", encoding="utf-8")
        base, _ = http_server
        with pytest.MonkeyPatch.context() as mp:
            mp.chdir(tmp_path)
            payload = _get_json(f"{base}/api/reports/preview?path=docs/preview-test.md")
        assert payload["read_only"] is True
        assert "Preview Test" in str(payload["preview"])

    def test_preview_missing_path_400(self, http_server: tuple[str, HTTPServer]) -> None:
        base, _ = http_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get_json(f"{base}/api/reports/preview")
        assert exc.value.code == 400

    def test_preview_not_found_404(self, http_server: tuple[str, HTTPServer]) -> None:
        base, _ = http_server
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get_json(f"{base}/api/reports/preview?path=docs/no-such-file.md")
        assert exc.value.code == 404
