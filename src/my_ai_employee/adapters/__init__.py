"""Adapters — 数据适配层(沿 D6.5+D9.2 范本).

承接:
    - adapters.apple_notes.html_cleaner(D9.2 — Apple Notes HTML→plain text 转换器)

定位(沿 D6.5 connectors 与 adapters 边界):
    - connectors/:负责与外部数据源对接(AppleScript / IMAP / SMTP / CSV)
    - adapters/:负责数据形态转换(HTML→plain text / 字段映射 / 类型转换)

D3.2 8 雷区严判应用:
    1. str 严判(非 str 抛 TypeError)
    2. type 严判在 hash 操作前
    3. 失败隔离(单条失败不影响其他)
    4. 标准库优先(避免引入新依赖 bleach/BeautifulSoup)
"""
