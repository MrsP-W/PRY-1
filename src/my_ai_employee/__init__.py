"""我的AI员工 — 全天候个人 AI 数字员工。

5 层架构：
  L0 设备层 — macOS 原生（AppleScript/Keychain/launchd）
  L1 适配器层 — IMAP/CalDAV/账单/Notes
  L2 数据层 — SQLite 加密（**sqlcipher3**，D1.1 替代 pysqlcipher3）
  L3 智能层 — minimax M3 LLM
  L4 Agent 层 — @管家/@审计员 + Agent Assistant 软链

当前状态：D1.1 脚手架重构完成（PEP 621 + uv + Python 3.12 + 包名重构 + 18 测试 + 62% 覆盖率）
下一棒：D2 IMAP 适配器（范围已收窄：BaseConnector + QQ + Keychain + mock + 健康检查）
"""

__version__ = "0.1.0"
__author__ = "Mr-PRY"
