"""D5 业务调度器 — 业务调度层.

承接:
  - D5.1 SMTP transport + Keychain service(`connectors/smtp.py`)
  - D5.2 outbox 状态机 6 状态 + ALLOWED_TRANSITIONS(`core/outbox.py` + `db/outbox.py`)
  - D5.3 EmailSendAdapter 三入口(`policy/send_adapter.py`)

当前(D5.5.1)包含:
  - `OutboxDispatcher` — 主循环(沿 `core/sync.py:IMAPSync.run_once` 6 步范本)
  - `DispatcherResult` — 单次调度结果统计(沿 `core/sync.py:SyncResult` 范本)
  - `SLAEvaluator` — URGENT 5min / HIGH 30min / NORMAL 4h SLA 告警
  - `compute_retry_after_ms` — 指数退避公式(2^failures * 60s,封顶 1h)
  - Heartbeat 3 态(HEALTHY/STALLED/TRANSPORT_DEAD)在 run_once 内的联动策略
"""

from my_ai_employee.scheduler.backoff import compute_retry_after_ms
from my_ai_employee.scheduler.outbox_dispatcher import DispatcherResult, OutboxDispatcher
from my_ai_employee.scheduler.sla import SLAEvaluation, SLAEvaluator, SLAStatus

__all__ = [
    "DispatcherResult",
    "OutboxDispatcher",
    "SLAEvaluation",
    "SLAEvaluator",
    "SLAStatus",
    "compute_retry_after_ms",
]
