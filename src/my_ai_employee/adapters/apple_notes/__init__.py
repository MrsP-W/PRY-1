"""Apple Notes 数据适配层(D9.2 — 沿 connectors/apple_notes.py 边界).

承接:
    - html_cleaner.clean_notes_html(HTML→plain text 转换器,标准库 HTMLParser)
    - 未来扩展:attachment 提取 / 全文检索索引 / 富文本解析

D9 决策(2026-06-15):
    - 仅用标准库 html.parser.HTMLParser(不引入 bleach/BeautifulSoup)
    - 附件只存元数据(不含二进制,避免 DB 膨胀)
"""
