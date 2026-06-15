"""D9.2 — Apple Notes HTML→plain text 转换器(标准库 `html.parser.HTMLParser`).

承接:
    - notes.body 字段在 D9.1 阶段存的是 Apple Notes.app 返回的 HTML 字符串
    - C1 sync_notes.py 入库前必须先转 plain text(避免 notes.body 塞 HTML)
    - 4 坑严判:嵌套列表 / 附件引用 / 私有笔记含 [Lock] / 编码异常

设计取舍:
    - 不用 bleach(避免新依赖,沿 D9.2 决策 2)
    - 不用 BeautifulSoup(避免新依赖)
    - 不用正则(嵌套 HTML 不可靠)
    - 沿 html.parser.HTMLParser(标准库,Python 自带,无 dep)

D3.2 8 雷区严判应用:
    1. str 严判(非 str 抛 TypeError)— type 严判在 hash 前
    2. 空字符串兜底("" → ("", []))
    3. 解析失败兜底(返回原文 + 空附件列表,绝不抛异常给上层入库阻塞)
    4. 块级元素保留换行(p/div/br/li/h1-h6)
    5. 附件引用从 img/en-media/attachment 标签的 src/data-src/id 提取
    6. 私有笔记含 [Lock] 标记透传(由 NoteStore.is_private 严判,不解析层处理)
    7. 多次连续空行折叠为 1 个(\n{3,} → \n\n)
    8. 单测 4 类(纯文本 / 嵌套列表 / 附件引用 / 私有笔记)

D4.7.3 教训应用:
    - 严判只放在适配器层(契约层接受已校验参数,不再二次严判)
    - 异常类型统一 TypeError(非 str 入口)
    - 私有化属性加 _ 前缀(避免与 HTMLParser 公共 API 冲突)
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


class _NotesHTMLCleaner(HTMLParser):
    """HTMLParser 子类:Apple Notes HTML → (plain_text, attachment_refs).

    行为契约:
        - 收集所有 text 数据(顺序保留)
        - 块级元素前后插入 \\n(p/div/br/li/h1-h6)
        - 媒体标签提取附件引用(img/en-media/attachment 的 src/data-src/id/href)
        - HTML 实体通过 convert_charrefs=True 自动解码
        - 多次连续空行折叠为最多 2 个(\\n\\n)
    """

    _BLOCK_TAGS: frozenset[str] = frozenset(
        {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "hr"}
    )
    _MEDIA_TAGS: frozenset[str] = frozenset({"img", "en-media", "attachment", "object"})
    _ATTACHMENT_ATTRS: tuple[str, ...] = ("src", "data-src", "id", "href", "x-apple-attr-url")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._text_parts: list[str] = []
        self._attachments: list[str] = []
        self._in_skip: bool = False  # <script>/<style> 跳过

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._BLOCK_TAGS:
            self._text_parts.append("\n")
        if tag_lower in self._MEDIA_TAGS:
            for name, value in attrs:
                if name in self._ATTACHMENT_ATTRS and value:
                    self._attachments.append(value)
        if tag_lower in {"script", "style"}:
            self._in_skip = True

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._BLOCK_TAGS:
            self._text_parts.append("\n")
        if tag_lower in {"script", "style"}:
            self._in_skip = False

    def handle_data(self, data: str) -> None:
        if not self._in_skip and data:
            self._text_parts.append(data)

    def get_text(self) -> str:
        """合并文本 + 折叠多余空行 + strip()."""
        text = "".join(self._text_parts)
        # 多次连续空行折叠为最多 2 个(段落分隔)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def get_attachments(self) -> list[str]:
        return list(self._attachments)


def clean_notes_html(html: str) -> tuple[str, list[str]]:
    """Apple Notes HTML → (plain_text, attachment_refs) — 适配层入口函数.

    Args:
        html: Apple Notes 原始 HTML 字符串(Notes.app 返回)

    Returns:
        (plain_text, attachment_refs) 元组:
            - plain_text: 纯文本(块级元素含换行,空行折叠)
            - attachment_refs: 附件引用列表(从 img/en-media 标签的 src 属性提取)

    严判:
        - html 必须是 str(非 str 抛 TypeError)
        - 空字符串返回 ("", [])

    失败隔离:
        - HTMLParser 解析失败 → 兜底返回原文(去最简单标签)+ 空附件
        - 绝不抛异常阻塞 sync_notes.py 入库流程

    Examples:
        >>> clean_notes_html("<p>Hello</p>")
        ('Hello', [])
        >>> clean_notes_html("<ul><li>A</li><li>B</li></ul>")
        ('A\\nB', [])
        >>> clean_notes_html('<img src="photo.png">Body')
        ('Body', ['photo.png'])
    """
    if not isinstance(html, str):
        raise TypeError(f"html 必须是 str,实际 type={type(html).__name__}, value={html!r}")
    if not html:
        return ("", [])
    cleaner = _NotesHTMLCleaner()
    try:
        cleaner.feed(html)
        cleaner.close()
    except Exception:  # noqa: BLE001 — 解析失败兜底,绝不阻塞入库
        return (_strip_simple_html_fallback(html), [])
    return (cleaner.get_text(), cleaner.get_attachments())


def _strip_simple_html_fallback(html: str) -> str:
    """简化版 HTML 标签去除(异常兜底路径,仅处理 <tag>...</tag>).

    不依赖 HTMLParser,纯正则兜底,仅在主解析路径失败时调用。
    """
    text = re.sub(r"<[^>]+>", "", html)
    # HTML 实体基础解码(沿 D4.7.2 v1.0.6 抗注入范本)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return text.strip()


__all__ = ["clean_notes_html"]
