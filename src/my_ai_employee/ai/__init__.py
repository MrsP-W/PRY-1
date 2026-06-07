"""L3 智能层。

4 个核心服务：
  - classifier          邮件 5 类分类（Claude Haiku）
  - drafter             邮件草稿生成（Claude Sonnet）
  - finance_analyzer    财务异常检测 + 月度报告（Claude Sonnet）
  - note_structurer     剪贴板/Notes 结构化（Claude Haiku）

当前 LLM：minimax M3（通过 Claude Code SDK）
Fallback：规则引擎（关键词/正则）— 不做本地 Ollama

D4（classifier + drafter）+ D8（finance_analyzer + note_structurer）实施。
"""
