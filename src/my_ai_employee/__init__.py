"""我的AI员工 — 全天候个人 AI 数字员工。

5 层架构：
  L0 设备层 — macOS 原生（AppleScript/Keychain/launchd）
  L1 适配器层 — IMAP/CalDAV/账单/Notes
  L2 数据层 — SQLite 加密（**sqlcipher3**，D1.1 替代 pysqlcipher3）
  L3 智能层 — minimax M3 LLM
  L4 Agent 层 — @管家/@审计员 + Agent Assistant 软链

当前状态：D3 数据层完成（D3.1 SQLCipher 加密 SQLite + D3.2 ORM/alembic + D3.3 IMAP 同步 100/批 + SyncState + 1万封 spike 0.35s；D3.3.1 修复 3 处：make lint MD050 / sync.py 时区偏移 / UNIQUE 冲突 last_uid 推进）
下一棒：D4 智能层（LLM 分类/标签/优先级 + EmailLabel 关系表）
"""

__version__ = "0.1.0"
__author__ = "Mr-PRY"
