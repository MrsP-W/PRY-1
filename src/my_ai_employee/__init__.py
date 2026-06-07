"""我的AI员工 — 全天候个人 AI 数字员工。

5 层架构：
  L0 设备层 — macOS 原生（AppleScript/Keychain/launchd）
  L1 适配器层 — IMAP/CalDAV/账单/Notes
  L2 数据层 — SQLite 加密（**sqlcipher3**，D1.1 替代 pysqlcipher3）
  L3 智能层 — minimax M3 LLM
  L4 Agent 层 — @管家/@审计员 + Agent Assistant 软链

当前状态：D2 IMAP 适配器完成（QQ 授权码模式 + Keychain 凭证 + 熔断 + mock + 14 个测试 + 32/32 套件 + 71.2% 覆盖率）
下一棒：D3 数据层（SQLCipher 加密 SQLite + 邮件入库）
"""

__version__ = "0.1.0"
__author__ = "Mr-PRY"
