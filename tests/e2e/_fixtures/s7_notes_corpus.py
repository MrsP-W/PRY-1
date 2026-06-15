"""S7 端到端测试复用 fixtures — 剪贴板样本 + 笔记 corpus.

承接 v0.1-launch-plan.md §D9.2+ 决策 + 2026-06-15 plan §4 C5:
    - CLIPBOARD_SAMPLE_PATH 指向 _fixtures/s7_clipboard.txt(500 字符 Markdown)
    - make_clipboard_text() 动态构造剪贴板文本(避免静态 fixture 漂移)
    - make_fake_note(apple_note_id, title, body, is_private=False) 工厂函数

设计要点:
    - 不依赖外部网络/真实 Apple Notes DB
    - pytest fixture 透传路径,test 只管断言
    - 沿 tests/fixtures/notes_faker/ 范本(若 C1 已落,直接复用)
"""

from __future__ import annotations

from pathlib import Path

# ===== 静态剪贴板 fixture 路径(沿 _fixtures/ 范本)=====

FIXTURES_DIR: Path = Path(__file__).resolve().parent
CLIPBOARD_SAMPLE_PATH: Path = FIXTURES_DIR / "s7_clipboard.txt"


def load_clipboard_sample() -> str:
    """加载 _fixtures/s7_clipboard.txt 静态样本.

    Returns:
        Markdown 格式剪贴板文本(~500 字符)
    """
    return CLIPBOARD_SAMPLE_PATH.read_text(encoding="utf-8")


# ===== 动态剪贴板文本构造 =====
# 沿 D4.7.2 v1.0.5 strip() 严判范本: body 必 strip 后非空


def make_clipboard_text(title: str, body_paragraphs: list[str]) -> str:
    """动态构造剪贴板文本(测试用,避免静态 fixture 漂移).

    Args:
        title: 笔记标题
        body_paragraphs: 段落列表(自动过滤空字符串)

    Returns:
        "# {title}\\n\\n{段落1}\\n\\n{段落2}..." 格式
    """
    cleaned = [p.strip() for p in body_paragraphs if p and p.strip()]
    body = "\n\n".join(cleaned)
    return f"# {title.strip()}\n\n{body}" if cleaned else f"# {title.strip()}"


# ===== Fake Note 工厂(直接构造 ORM 入库,绕开 osascript)=====


def make_fake_note_kwargs(
    *,
    apple_note_id: str,
    title: str,
    body: str,
    folder: str = "Notes",
    updated_at_ms: int = 1749964800000,  # 2025-06-15 00:00:00 UTC ms
    is_private: bool = False,
    tags: str | None = None,
) -> dict[str, object]:
    """构造 NoteStore.insert 入参 dict(测试用).

    沿 NoteStore.insert 9 字段签名范本(D9.1 锁定)。
    """
    return {
        "apple_note_id": apple_note_id,
        "folder": folder,
        "title": title,
        "body": body,
        "updated_at_ms": updated_at_ms,
        "is_private": is_private,
        "tags": tags,
    }


__all__ = [
    "CLIPBOARD_SAMPLE_PATH",
    "FIXTURES_DIR",
    "load_clipboard_sample",
    "make_clipboard_text",
    "make_fake_note_kwargs",
]
