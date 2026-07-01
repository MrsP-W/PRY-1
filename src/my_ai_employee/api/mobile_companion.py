"""v0.2.57 / Day 8 候选 C — 移动伴侣 API 路由表契约.

本模块定义"移动伴侣 App"(iOS / macOS 伴侣)与本地 Dashboard 之间
的 API 契约。**仅契约定义,不在 Day 8 实施真实路由**(纯 docs 先行)。
真实接入由 `dashboard/server.py` 在 Day 9+ 复用现有 handlers,只需
追加 mobile 专用端点即可(沿 v0.2.53.11 ApprovalGate 范本)。

设计原则:
    - 复用现有 Dashboard 5 门:所有写操作走 ApprovalGate 严判
    - 端点命名约定: `/api/companion/{category}/{action}`(与 `/api/{category}/{action}` 对齐)
    - 响应统一 schema: `{"read_only": bool, "data": ..., "error": str|None, "reason": str|None}`
    - 鉴权:本地 127.0.0.1 绑定(沿 dashboard/server.py 范本),无 HTTP 鉴权
    - 离线兜底:移动伴侣可缓存最近一次响应,网络断开时不绕过 Dashboard 写入

撞坑关联:
    - 撞坑 #1:不直连 DB,所有数据访问经 Dashboard API
    - 撞坑 #18:ENABLE_PATH_4_WRITE 维持 UNSET,5 门替代
    - 撞坑 #59:outlook/gmail 仍不配置
    - 撞坑 #65:BusinessWriter + AuditContext 沿用
    - 撞坑 #71 解除:业务代码改动日,本模块是 docs-only 接口设计
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final


class CompanionMethod(StrEnum):
    """HTTP 方法枚举(沿 stdlib StrEnum 范本,Python 3.11+)."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


@dataclass(frozen=True, slots=True)
class CompanionRoute:
    """移动伴侣路由契约.

    字段:
        method: HTTP 方法
        path: 路由路径(以 / 开头)
        category: 业务分类(outbox / notes / finance / reports / system)
        action: 端点动作(get / list / decide / status 等)
        requires_write_gate: 是否需要 5 门审批(POST/PUT/DELETE 都默认 True)
        summary: 端点功能简述(中文)
        request_schema: 请求 JSON schema 描述(无敏感信息)
        response_schema: 响应 JSON schema 描述(无敏感信息)
        offline_fallback: 离线时的兜底数据描述(便于移动伴侣缓存展示)
    """

    method: CompanionMethod
    path: str
    category: str
    action: str
    requires_write_gate: bool
    summary: str
    request_schema: dict[str, str]
    response_schema: dict[str, str]
    offline_fallback: str


# 契约版本号(Day 8 候选 C 启动点)
COMPANION_API_VERSION: Final = "v0.2.57-companion"


# ===== 路由表 — 8 个核心端点(沿 dashboard 已实现 5 端点 + 新增 3 移动专用) =====

COMPANION_ROUTES: Final[tuple[CompanionRoute, ...]] = (
    # ---- 只读 GET 端点(沿 dashboard/server.py 范本) ----
    CompanionRoute(
        method=CompanionMethod.GET,
        path="/api/companion/status",
        category="system",
        action="status",
        requires_write_gate=False,
        summary="移动伴侣系统状态(质量门 + 5 门 + Keychain 探测)",
        request_schema={},
        response_schema={
            "version": "str",
            "git_head": "str",
            "quality_gates": "{pytest, coverage, mypy, lint}",
            "approval_gates": "dict(5 门全部状态)",
            "offline": "bool(mobile 自报离线标记)",
        },
        offline_fallback="{} (网络断开时显示 'offline' badge)",
    ),
    CompanionRoute(
        method=CompanionMethod.GET,
        path="/api/companion/tasks/today",
        category="system",
        action="tasks_today",
        requires_write_gate=False,
        summary="今日待办摘要(邮件 / Notes / 财务异常数)",
        request_schema={},
        response_schema={"total": "int", "tasks": "[{id, title, count, priority}]"},
        offline_fallback="[] (显示 '上次同步于 HH:MM')",
    ),
    CompanionRoute(
        method=CompanionMethod.GET,
        path="/api/companion/outbox",
        category="outbox",
        action="list",
        requires_write_gate=False,
        summary="邮件草稿队列(待审批 + 已审批 + 已取消)",
        request_schema={"limit": "int(1-100,默认 10)"},
        response_schema={"count": "int", "items": "[outbox_dict]"},
        offline_fallback="[] (移动伴侣缓存最近一次响应)",
    ),
    CompanionRoute(
        method=CompanionMethod.GET,
        path="/api/companion/notes/pending",
        category="notes",
        action="list",
        requires_write_gate=False,
        summary="Apple Notes 待确认列表",
        request_schema={"limit": "int(1-100,默认 10)"},
        response_schema={"count": "int", "items": "[note_dict]"},
        offline_fallback="[] (移动伴侣缓存最近一次响应)",
    ),
    CompanionRoute(
        method=CompanionMethod.GET,
        path="/api/companion/finance/anomalies",
        category="finance",
        action="list",
        requires_write_gate=False,
        summary="财务异常列表(消费金额异常 / 商家画像漂移 / 频率异常)",
        request_schema={"limit": "int(1-100,默认 10)"},
        response_schema={"count": "int", "items": "[anomaly_dict]"},
        offline_fallback="[] (移动伴侣缓存最近一次响应)",
    ),
    CompanionRoute(
        method=CompanionMethod.GET,
        path="/api/companion/approval-gate/audits",
        category="system",
        action="audit_list",
        requires_write_gate=False,
        summary="最近 5 门审批记录(沿 v0.2.53.52 audit 端点)",
        request_schema={"limit": "int(1-100,默认 10)"},
        response_schema={"enabled": "bool", "count": "int", "items": "[audit_dict]"},
        offline_fallback="[] (移动伴侣缓存最近 1 小时内记录)",
    ),
    # ---- 写操作 POST 端点(全部沿用 5 门) ----
    CompanionRoute(
        method=CompanionMethod.POST,
        path="/api/companion/approval-gate/decide",
        category="outbox",
        action="decide",
        requires_write_gate=True,
        summary="1-click 审批(v0.2.57 候选 A · 沿 5 门严判)",
        request_schema={
            "audit_id": "str(必填,≤ 80)",
            "decision": "approve|reject(必填)",
            "actor": "str(可选,默认 'mobile_companion',≤ 80)",
            "reason": "str(可选,≤ 240)",
            "confirm_text": "CONFIRM_WRITE(必填)",
            "dry_run": "bool(默认 True)",
        },
        response_schema={
            "endpoint": "decide",
            "decision": "approve|reject|null",
            "audit_id": "str",
            "mapped_action": "outbox.approve|outbox.cancel|null",
            "approval_gate_passed": "bool",
            "would_allow": "bool",
            "write_executed": "bool",
            "error": "str|null",
            "reason": "str|null",
        },
        offline_fallback="mobile 必须先联机再决定;离线时按钮置灰",
    ),
    CompanionRoute(
        method=CompanionMethod.POST,
        path="/api/companion/approval-gate/actions",
        category="notes",
        action="decide",
        requires_write_gate=True,
        summary="Notes 确认 / 财务异常忽略(沿 v0.2.53.11 actions 端点)",
        request_schema={
            "action": "notes.confirm|finance.dismiss_anomaly(必填)",
            "target_id": "str(必填,≤ 80)",
            "actor": "str(可选,默认 'mobile_companion')",
            "reason": "str(可选,≤ 240)",
            "confirm_text": "CONFIRM_WRITE(必填)",
            "dry_run": "bool(默认 True)",
        },
        response_schema={"action": "str", "target_id": "str", "approval_gate_passed": "bool"},
        offline_fallback="mobile 必须先联机再决定;离线时按钮置灰",
    ),
)


# ===== 辅助函数:路由表查询 =====


def list_companion_routes() -> list[dict[str, Any]]:
    """返回前端可展示的移动伴侣路由表(无敏感信息).

    Returns:
        list[dict],每个 dict 包含 method/path/category/action/requires_write_gate/summary 字段。
        沿 `list_action_contracts()` 范本(避免 hardcode 在 dashboard.html)。
    """
    return [
        {
            "method": r.method.value,
            "path": r.path,
            "category": r.category,
            "action": r.action,
            "requires_write_gate": r.requires_write_gate,
            "summary": r.summary,
        }
        for r in COMPANION_ROUTES
    ]


def build_companion_routes_table() -> dict[str, Any]:
    """返回移动伴侣 API 元信息(端点总数 + 5 门严判的端点数).

    沿 `build_approval_gate_status()` 范本。

    Returns:
        dict 包含:
            - contract_version: COMPANION_API_VERSION
            - total_routes: 路由总数
            - write_gated_routes: 需 5 门严判的路由数
            - read_only_routes: 只读路由数
            - categories: 涉及的业务分类列表
            - routes: list[dict](沿 list_companion_routes)
    """
    routes = list_companion_routes()
    write_gated = [r for r in COMPANION_ROUTES if r.requires_write_gate]
    read_only = [r for r in COMPANION_ROUTES if not r.requires_write_gate]
    categories = sorted({r.category for r in COMPANION_ROUTES})
    return {
        "contract_version": COMPANION_API_VERSION,
        "total_routes": len(COMPANION_ROUTES),
        "write_gated_routes": len(write_gated),
        "read_only_routes": len(read_only),
        "categories": categories,
        "routes": routes,
    }


__all__ = [
    "COMPANION_API_VERSION",
    "COMPANION_ROUTES",
    "CompanionMethod",
    "CompanionRoute",
    "build_companion_routes_table",
    "list_companion_routes",
]
