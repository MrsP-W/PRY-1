"""L1 适配器层。

6 个适配器（Week 1+2 MVP）：
  - imap          QQ/Outlook/Gmail 邮件
  - caldav        iCloud/Google Calendar
  - wechat_csv    微信账单
  - alipay_csv    支付宝账单
  - apple_notes   Apple Notes
  - apple_reminders Reminders（复用 Agent Assistant）

Week 1 实施顺序：imap → caldav → apple_reminders
Week 2 实施顺序：wechat_csv → alipay_csv → apple_notes

设计原则：失败隔离（单适配器失败不传染，借鉴应急版范本）。
"""

from my_ai_employee.connectors._types import RawNote, RawTransaction
from my_ai_employee.connectors.apple_notes import (
    NotesConnector,
    NotesConnectorError,
    build_raw_note,
    safe_parse,
)

__all__ = [
    "RawNote",
    "RawTransaction",
    "NotesConnector",
    "NotesConnectorError",
    "build_raw_note",
    "safe_parse",
]
