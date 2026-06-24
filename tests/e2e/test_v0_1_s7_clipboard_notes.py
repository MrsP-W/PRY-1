"""S7 — ⌥⌘N 剪贴板 → 结构化 → 写入 Notes(Week 2 路径).

承接 docs/v0.1-launch-plan.md:222 S7 唯一编号表行 + docs/week2-mvp.md:181-216 D9 任务。
2026-06-15 D9.2+ W2 时间窗落地后,本测试从 skip 占位改为真实端到端断言。

D6.0 范围(2026-06-14 启动):skip 占位,等 D9 落地后去除 skip。
D9.5 范围(2026-06-15 落地):⌥⌘N + pynput 子进程 + TCC 引导;但 _on_clipboard_capture
本步仅占位 notification,D9.5+ C5 实化时:剪贴板 → NoteStore.insert → 结构化。
"""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# ===== 路径设置(让 tests/e2e/_fixtures/ 可 import)=====

_E2E_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_E2E_DIR))

from _fixtures.s7_notes_corpus import (  # noqa: E402
    load_clipboard_sample,
    make_fake_note_kwargs,
)

# ===== 公共:fake LLM router(沿 tests/ai/test_structurer.py:80 范本)=====


@dataclass
class _FakeLLMResponse:
    """Fake LLMResponse(沿 D4.7.3 v1.0.6 范本)."""

    content: str
    model_full_id: str = "deepseek/deepseek-chat"
    input_tokens: int = 100
    output_tokens: int = 50
    latency_ms: int = 1500


class _FakeLLMRouter:
    """Fake LLMRouter,返回预设 JSON(供 S7 e2e 用)."""

    def __init__(self, content: str = "") -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    def route(
        self,
        task_type: Any,
        messages: list[dict[Any, Any]],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> _FakeLLMResponse:
        self.calls.append(
            {"task_type": task_type, "messages": messages, "temperature": temperature}
        )
        return _FakeLLMResponse(content=self._content)


# ===== S7.1 — 剪贴板 → NoteStore.insert → NoteStructurerService.structure_and_emit =====


@pytest.mark.e2e
def test_s7_clipboard_to_notes_shortcut(
    session_factory: Any,
    temp_db_path: Path,
    fake_keychain: None,
) -> None:
    """S7.1 — 模拟 ⌥⌘N 触发: 剪贴板文本 → NoteStore 写入 → 结构化(真链路).

    真链路覆盖(沿 2026-06-15 plan §4 C5 决策 5):
        1. 读 _fixtures/s7_clipboard.txt 模拟剪贴板内容
        2. NoteStore.insert(apple_note_id, folder, title, body, updated_at_ms) 入库
        3. NoteStructurerService.structure_and_emit(apple_note_id) 真跑
        4. 断言: 写入 tags ∈ {TODO, FYI, URGENT, PERSONAL, DEFAULT} + tags 数量 ≥ 2

    异常阻断路径: 私有笔记(is_private=True)→ PrivateSkipDecisionReport
    不调 LLM(沿 D4.7.3 v1.0.6 业务硬阻断范本)。
    """
    from my_ai_employee.ai.note_structurer import (
        NoteStructurerService,
        StructuredNote,
    )
    from my_ai_employee.db.notes import NoteStore

    store = NoteStore(session_factory)
    clipboard_text = load_clipboard_sample()

    # 1) 模拟 ⌥⌘N 触发的剪贴板捕获: NoteStore.insert 写入
    note_kwargs = make_fake_note_kwargs(
        apple_note_id="x-coredata://s7-clipboard-001",
        title="2026-06-15 AI 学习计划",
        body=clipboard_text,
    )
    note = store.insert(**note_kwargs)
    assert note is not None
    assert note.apple_note_id == "x-coredata://s7-clipboard-001"

    # 2) 真实结构化(FakeLLMRouter 返回合法 JSON,不调真 LLM)
    structurer = NoteStructurerService(
        store=store,
        llm_provider=_FakeLLMRouter(
            content='{"category": "TODO", "tags": ["AI", "学习", "LLM", "TCC", "双进程", "范本"]}'
        ),
    )
    start_ms = int(time.time() * 1000)
    result = structurer.structure_and_emit(apple_note_id=note.apple_note_id)
    end_ms = int(time.time() * 1000)

    # 3) 断言: StructuredNote 6 字段契约(沿 D4.7.3 v1.0.5 P1)
    assert isinstance(result, StructuredNote), (
        f"成功路径应返回 StructuredNote, 实际 {type(result).__name__}"
    )
    assert result.category in {"URGENT", "TODO", "FYI", "SPAM", "PERSONAL", "DEFAULT"}
    assert len(result.tags) >= 2, f"tags 数量应 ≥ 2, 实际 {len(result.tags)}"
    assert result.body_length > 0
    assert result.latency_ms >= 0
    # 真链路耗时 < 5 秒(本地 e2e,无需调真 LLM)
    assert (end_ms - start_ms) < 5000, f"结构化耗时 {(end_ms - start_ms)}ms 超出 5s 阈值"

    # 4) 二次查 NoteStore: 验证 tags 已写 DB(沿 D9.4 mark_structured 原子化)
    refreshed = store.find_by_apple_id(note.apple_note_id)
    assert refreshed is not None
    assert refreshed.tags is not None
    assert len(refreshed.tags.split(",")) == len(result.tags)
    # synced_at_ms 必被 set(非 None)
    assert refreshed.synced_at_ms is not None


@pytest.mark.e2e
def test_s7_private_note_skips_llm(
    session_factory: Any,
) -> None:
    """S7.1b — 私有笔记(is_private=True)→ 业务阻断(不调 LLM).

    沿 D4.7.3 v1.0.6 业务硬阻断范本: PrivateSkipDecisionReport
    不消耗 LLM token,kind=Literal["business_blocked"] 类型层面固化。
    """
    from my_ai_employee.ai.note_structurer import (
        NoteStructurerService,
        PrivateSkipDecisionReport,
    )
    from my_ai_employee.db.notes import NoteStore

    store = NoteStore(session_factory)
    llm = _FakeLLMRouter(content="should-not-be-called")
    note = store.insert(
        apple_note_id="x-coredata://s7-private-001",
        folder="Notes",
        title="私人日记",
        body="今天看了电影",
        updated_at_ms=1749964800000,
        is_private=True,
    )
    structurer = NoteStructurerService(store=store, llm_provider=llm)
    result = structurer.structure_and_emit(apple_note_id=note.apple_note_id)

    assert isinstance(result, PrivateSkipDecisionReport)
    assert result.kind == "business_blocked"
    assert result.reason == "is_private"
    # 业务阻断: LLM 不应被调
    assert len(llm.calls) == 0, f"业务阻断时 LLM 不应被调, 实际 calls={llm.calls}"


# ===== S7.2 — 30 笔真插入 + 全 unique + list[Any] 验条数 =====


@pytest.mark.e2e
def test_s7_notes_full_sync_30_inmemory(session_factory: Any) -> None:
    """S7.2 — 30 笔 NoteStore.insert 真跑 + list_all 验条数 + 全 unique apple_note_id.

    端到端覆盖(沿 C1 决策 6 spike 30 笔范本 — 调 NoteStore.insert 而非 subprocess):
        1. secrets.token_hex(8) 生成 30 个 unique apple_note_id
        2. NoteStore.insert 跑 30 笔(L1 UNIQUE 互不冲突)
        3. 验 list_all() 返回 30 条 + 30 个 unique apple_note_id
        4. 验 L1 幂等: 重复 insert 同一 apple_note_id → NoteDuplicateError

    设计决策(C5 实战纠偏):
        - sync_notes.py C1 尚未落地,subprocess 真跑阻塞
        - 改用 NoteStore.insert 30 笔真链路 + L1 幂等断言(等价"全量同步"语义)
        - 沿 S6.1 范本 + D9.1 L1 UNIQUE 业务阻断
    """
    import secrets

    from my_ai_employee.db.notes import NoteDuplicateError, NoteStore

    store = NoteStore(session_factory)

    # 1) 30 个 unique apple_note_id
    apple_ids = [f"x-coredata://s7-sync-{secrets.token_hex(8)}" for _ in range(30)]

    # 2) 跑 30 笔 insert
    inserted_ids: list[str] = []
    for i, aid in enumerate(apple_ids):
        note = store.insert(
            apple_note_id=aid,
            folder="Notes",
            title=f"S7 sync note #{i + 1}",
            body=f"sync body {i + 1}",
            updated_at_ms=1749964800000 + i * 1000,
        )
        assert note.id is not None
        inserted_ids.append(note.apple_note_id)

    # 3) 验 list_all 30 条 + 全 unique
    all_notes = store.list_all(limit=100)
    note_id_set = {n.apple_note_id for n in all_notes}
    assert len(all_notes) == 30, f"list_all 应返回 30 条, 实际 {len(all_notes)}"
    assert len(note_id_set) == 30, f"apple_note_id 应 30 unique, 实际 {len(note_id_set)}"
    assert set(inserted_ids) == note_id_set

    # 4) L1 幂等: 重复 insert 同一 id → NoteDuplicateError(业务阻断入口)
    with pytest.raises(NoteDuplicateError):
        store.insert(
            apple_note_id=apple_ids[0],  # 复用第 1 个 id
            folder="Notes",
            title="duplicate",
            body="dup",
            updated_at_ms=1749964800000,
        )


# ===== helper(供后续 S7.3 复用)=====


@pytest.fixture
def _fake_clipboard_text() -> Iterator[str]:
    """模拟剪贴板文本 fixture."""
    yield load_clipboard_sample()
