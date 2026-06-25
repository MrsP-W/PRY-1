"""L5 Web Dashboard — 本地只读 API(v0.2.53.2 P2 骨架).

默认绑定 127.0.0.1,仅 GET:
    - /api/status
    - /api/tasks/today

写动作(P2+)必须走 ApprovalGate,本模块不提供 POST/PUT/DELETE。
"""

from my_ai_employee.dashboard.context import DashboardContext
from my_ai_employee.dashboard.server import create_server, run_server

__all__ = ["DashboardContext", "create_server", "run_server"]
