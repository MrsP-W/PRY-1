"""v0.2.57 / Day 8 候选 C — 移动伴侣 API 契约测试.

本测试覆盖:
    - 路由表 8 端点的契约稳定性(method/path/category/action)
    - 5 门严判的端点必须 requires_write_gate=True
    - 离线兜底字段必须非空
    - list_companion_routes() 与 build_companion_routes_table() API 一致性
    - COMPANION_API_VERSION 必须稳定 v0.2.57-companion
    - 业务分类必须含 outbox/notes/finance/system

撞坑 #1 隐私铁律 + 撞坑 #65 沿用 + 撞坑 #71 解除 docs-only 契约。
"""

from __future__ import annotations

import pytest

from my_ai_employee.api.mobile_companion import (
    COMPANION_API_VERSION,
    COMPANION_ROUTES,
    CompanionMethod,
    build_companion_routes_table,
    list_companion_routes,
)


class TestCompanionRoutesContract:
    """移动伴侣路由表契约 — 8 端点稳定性."""

    def test_companion_api_version_is_v0_2_57(self) -> None:
        """契约版本号必须稳定(Day 8 候选 C 标志)."""
        assert COMPANION_API_VERSION == "v0.2.57-companion"

    def test_routes_table_has_8_routes(self) -> None:
        """路由表必须 = 8 端点(6 GET + 2 POST)."""
        assert len(COMPANION_ROUTES) == 8

    def test_routes_methods_distributed(self) -> None:
        """6 GET + 2 POST(只读 + 写动作)."""
        methods = [r.method for r in COMPANION_ROUTES]
        assert methods.count(CompanionMethod.GET) == 6
        assert methods.count(CompanionMethod.POST) == 2

    def test_all_routes_start_with_api_companion(self) -> None:
        """所有路由必须 /api/companion/ 前缀(避免与 dashboard 端点冲突)."""
        for r in COMPANION_ROUTES:
            assert r.path.startswith("/api/companion/"), f"{r.path} 缺 /api/companion/ 前缀"

    def test_no_duplicate_routes(self) -> None:
        """路由表无重复(method+path 唯一)."""
        seen = set()
        for r in COMPANION_ROUTES:
            key = (r.method, r.path)
            assert key not in seen, f"重复路由:{key}"
            seen.add(key)

    def test_write_methods_require_write_gate(self) -> None:
        """所有 POST 端点必须 requires_write_gate=True(沿 5 门严判)."""
        for r in COMPANION_ROUTES:
            if r.method in {CompanionMethod.POST, CompanionMethod.PUT, CompanionMethod.DELETE}:
                assert r.requires_write_gate, f"{r.method} {r.path} 缺 5 门严判"

    def test_get_methods_no_write_gate(self) -> None:
        """所有 GET 端点必须 requires_write_gate=False(只读)."""
        for r in COMPANION_ROUTES:
            if r.method == CompanionMethod.GET:
                assert not r.requires_write_gate, f"GET {r.path} 不应有 5 门严判"

    def test_categories_cover_4_business(self) -> None:
        """业务分类必须含 outbox/notes/finance/system."""
        categories = {r.category for r in COMPANION_ROUTES}
        assert "outbox" in categories
        assert "notes" in categories
        assert "finance" in categories
        assert "system" in categories

    def test_offline_fallback_not_empty(self) -> None:
        """每个路由的 offline_fallback 必须非空(沿撞坑 #1 离线兜底)."""
        for r in COMPANION_ROUTES:
            assert r.offline_fallback.strip(), f"{r.path} 缺 offline_fallback"

    def test_summary_not_empty(self) -> None:
        """每个路由的 summary 必须非空."""
        for r in COMPANION_ROUTES:
            assert r.summary.strip(), f"{r.path} 缺 summary"

    def test_request_schema_dict(self) -> None:
        """每个路由的 request_schema 必须是 dict(可空)."""
        for r in COMPANION_ROUTES:
            assert isinstance(r.request_schema, dict)

    def test_response_schema_dict(self) -> None:
        """每个路由的 response_schema 必须是 dict."""
        for r in COMPANION_ROUTES:
            assert isinstance(r.response_schema, dict)


class TestListCompanionRoutes:
    """list_companion_routes() API 稳定性测试."""

    def test_returns_list_of_dicts(self) -> None:
        """必须返回 list[dict](便于 JSON 序列化)."""
        routes = list_companion_routes()
        assert isinstance(routes, list)
        assert len(routes) == 8
        for r in routes:
            assert isinstance(r, dict)

    def test_dict_has_required_keys(self) -> None:
        """每个 dict 必须含 method/path/category/action/requires_write_gate/summary."""
        required = {"method", "path", "category", "action", "requires_write_gate", "summary"}
        for r in list_companion_routes():
            assert required.issubset(set(r.keys())), f"缺字段:{required - set(r.keys())}"

    def test_method_is_string(self) -> None:
        """method 字段必须是 str(沿 JSON 序列化范本)."""
        for r in list_companion_routes():
            assert isinstance(r["method"], str)

    def test_requires_write_gate_is_bool(self) -> None:
        """requires_write_gate 字段必须是 bool."""
        for r in list_companion_routes():
            assert isinstance(r["requires_write_gate"], bool)


class TestBuildCompanionRoutesTable:
    """build_companion_routes_table() 元信息 API 测试."""

    def test_returns_dict_with_meta(self) -> None:
        """必须返回 dict 含 contract_version/total_routes/write_gated_routes/read_only_routes/categories/routes."""
        table = build_companion_routes_table()
        required = {
            "contract_version",
            "total_routes",
            "write_gated_routes",
            "read_only_routes",
            "categories",
            "routes",
        }
        assert required.issubset(set(table.keys()))

    def test_total_routes_count(self) -> None:
        """total_routes 必须 = 8."""
        table = build_companion_routes_table()
        assert table["total_routes"] == 8

    def test_write_gated_count(self) -> None:
        """write_gated_routes 必须 = 2(2 个 POST 端点)."""
        table = build_companion_routes_table()
        assert table["write_gated_routes"] == 2

    def test_read_only_count(self) -> None:
        """read_only_routes 必须 = 6(6 个 GET 端点)."""
        table = build_companion_routes_table()
        assert table["read_only_routes"] == 6

    def test_categories_sorted_unique(self) -> None:
        """categories 必须排序且唯一."""
        table = build_companion_routes_table()
        cats = table["categories"]
        assert cats == sorted(set(cats))
        # 4 个分类
        assert len(cats) == 4

    def test_routes_equals_list_companion_routes(self) -> None:
        """routes 字段必须 == list_companion_routes()."""
        table = build_companion_routes_table()
        assert table["routes"] == list_companion_routes()


class TestCompanionRouteDataclass:
    """CompanionRoute dataclass 严判测试."""

    def test_dataclass_is_frozen(self) -> None:
        """CompanionRoute 必须 frozen(撞坑 #64 公共 API 一致性)."""
        r = COMPANION_ROUTES[0]
        with pytest.raises((AttributeError, TypeError)):
            r.path = "/api/companion/mutated"  # type: ignore[misc]

    def test_dataclass_slots(self) -> None:
        """CompanionRoute 必须 slots(避免 __dict__ 内存膨胀)."""
        r = COMPANION_ROUTES[0]
        assert hasattr(r, "__slots__") or not hasattr(r, "__dict__")

    def test_companion_method_enum_values(self) -> None:
        """CompanionMethod 枚举值必须稳定."""
        assert CompanionMethod.GET.value == "GET"
        assert CompanionMethod.POST.value == "POST"
        assert CompanionMethod.PUT.value == "PUT"
        assert CompanionMethod.DELETE.value == "DELETE"


class TestPath4ImportBoundary:
    """候选 C 边界测试 — 仅契约定义,无实写路径."""

    def test_module_does_not_depend_on_dashboard_server(self) -> None:
        """api/mobile_companion.py 不依赖 dashboard.server(避免循环依赖 + 边界)."""
        import my_ai_employee.api.mobile_companion as mod

        module_source = mod.__file__
        assert module_source is not None
        with open(module_source, encoding="utf-8") as f:
            content = f.read()
        # 不应 import dashboard.server(避免移动伴侣契约绑死 HTTP server)
        assert "from my_ai_employee.dashboard.server" not in content
        assert "import my_ai_employee.dashboard.server" not in content

    def test_module_does_not_depend_on_outbox_impl(self) -> None:
        """api/mobile_companion.py 不依赖 OutboxStore / NoteStore(撞坑 #1 隐私铁律).

        移动伴侣不直连 DB 存储,只通过 Dashboard 间接访问。
        """
        import my_ai_employee.api.mobile_companion as mod

        module_source = mod.__file__
        assert module_source is not None
        with open(module_source, encoding="utf-8") as f:
            content = f.read()
        # 不应 import db.outbox / db.notes(撞坑 #1 隐私铁律)
        assert "from my_ai_employee.db.outbox" not in content
        assert "from my_ai_employee.db.notes" not in content

    def test_module_does_not_depend_on_keychain(self) -> None:
        """api/mobile_companion.py 不依赖 Keychain(撞坑 #1 隐私铁律)."""
        import my_ai_employee.api.mobile_companion as mod

        module_source = mod.__file__
        assert module_source is not None
        with open(module_source, encoding="utf-8") as f:
            content = f.read()
        assert "from my_ai_employee.core.keychain" not in content
        assert "import keychain" not in content

    def test_module_does_not_depend_on_smtp(self) -> None:
        """api/mobile_companion.py 不依赖 SMTP 真实发送(撞坑 #59 红线)."""
        import my_ai_employee.api.mobile_companion as mod

        module_source = mod.__file__
        assert module_source is not None
        with open(module_source, encoding="utf-8") as f:
            content = f.read()
        assert "smtp" not in content.lower() or "smtp" in {"# smtp 仍 docs-only"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
