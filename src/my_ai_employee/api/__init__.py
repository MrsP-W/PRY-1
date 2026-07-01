"""v0.2.57 / Day 8 候选 C — 移动伴侣 API 设计(docs 先行).

本模块定义本地 Dashboard 之外,**移动伴侣**(iOS / macOS 伴侣 App)接入
"我的AI员工"所需的 API 契约。**仅设计,不在 Day 8 实施**。真实接入留
Day 9+(沿 v0.2-launch-plan 候选 C 评注"docs 先行")。

设计目标:
    - **本地优先**:移动伴侣只与本地 127.0.0.1 Dashboard 通信,
      不直连云端、不接 SaaS(沿撞坑 #1 隐私铁律)
    - **只读 + 显式写动作**:移动端只读 + 1-click 审批(沿 v0.2.53.11
      ApprovalGate 契约)
    - **离线兜底**:网络断开时,移动端有"未同步"标记,
      不绕过本地 Dashboard 写入

设计边界(沿撞坑 #1 + 撞坑 #59 + 撞坑 #18 + 撞坑 #65):
    - 移动伴侣不持有 SQLCipher Keychain 密码
    - 移动伴侣不发 SMTP / 不写 Keychain / 不 kickstart launchd
    - 所有写操作走现有 ApprovalGate 5 门(write_enabled + confirm_text +
      BUSINESS_WRITER_ENABLED + writer_impl + ENABLE_PATH_4_WRITE)
    - 移动伴侣可发"指令"但不能直连 DB(所有读写经 Dashboard 中转)

撞坑关联:
    - 撞坑 #1:不直连 DB,所有数据访问经 Dashboard API
    - 撞坑 #18:ENABLE_PATH_4_WRITE 维持 UNSET,5 门替代
    - 撞坑 #59:outlook/gmail 仍不配置,SMTP 多账户禁用
    - 撞坑 #65:BusinessWriter + AuditContext 沿用
    - 撞坑 #71 解除:业务代码改动日,本模块是 docs-only 接口设计

Day 8 候选 C 范围:
    - 路由表(GET / POST 端点)
    - 响应 schema(TypedDict)
    - 鉴权契约(无鉴权,本地绑定 127.0.0.1)
    - 5 门契约沿用(写操作不绕过)
    - 错误码 + 离线兜底
"""

from my_ai_employee.api.mobile_companion import (
    COMPANION_API_VERSION,
    COMPANION_ROUTES,
    CompanionMethod,
    CompanionRoute,
    build_companion_routes_table,
    list_companion_routes,
)

__all__ = [
    "COMPANION_API_VERSION",
    "COMPANION_ROUTES",
    "CompanionMethod",
    "CompanionRoute",
    "build_companion_routes_table",
    "list_companion_routes",
]
