"""我的AI员工 — 全天候个人 AI 数字员工。

5 层架构：
  L0 设备层 — macOS 原生（AppleScript/Keychain/launchd）
  L1 适配器层 — IMAP/CalDAV/账单/Notes
  L2 数据层 — SQLite 加密（pysqlcipher3）
  L3 智能层 — minimax M3 LLM
  L4 Agent 层 — @管家/@审计员 + Agent Assistant 软链

当前状态：D1 脚手架（仅目录树 + 接口契约）
"""

__version__ = "0.1.0"
__author__ = "Mr-PRY"
