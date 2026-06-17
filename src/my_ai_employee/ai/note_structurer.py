"""D9.4 — NoteStructurerService:Apple Notes 结构化业务层(3 入口 + 3 数据类).

承接 docs/v0.1-launch-plan.md §D9.4 + docs/week1-mvp.md D9.4 段:
  - 业务目标: Apple Notes 同步后, 调 LLM 提取笔记 category(6 类) + tags(3-10 关键词)
  - 业务接入: 沿 D4.7.3 EmailDrafterAdapter 三入口架构(成功 / 业务阻断 / 技术失败)
  - 不接 PolicyEngine / Heartbeat / LaneBoard(notes 没有"草稿 → 审阅 → 发送"流,
    D9.4 业务层只做"LLM 调成功 → 写 tags"原子操作, 简化 D4.7.3 4 依赖范本)
  - 沿 D4.7.2 prompts/note_structurer.py 6 类 SYSTEM prompt + 抗注入 user 消息

设计要点(沿 D4.7.3 范本 + 6 教训应用):
  - 三入口互斥: structure_and_emit(成功) + record_private_skip_and_emit(业务阻断,
    is_private=True) + record_failure_and_emit(技术失败, LLM/DB 异常)
  - 工厂层 + 数据类 __post_init__ 双层防御(严判下沉到 helper)
  - 异常范围窄化: LLMError 子类(LLMAllFallbacksError / LLMResponseError / LLMAPIError)
    + sqlalchemy.exc.OperationalError 透传 record_failure_and_emit
  - 业务阻断 ≠ 技术失败: 业务阻断 reason="is_private"(永不 retry, 不计入 cf)
    技术失败 reason="llm_failure" / "db_failure"(可 retry, cf 累加)

D4.7.3 v1.0.6 教训应用(2026-06-15 锁定):
  - 业务阻断用 kind=Literal["business_blocked"] / "private_skip" 区分
  - 强一致: record_private_skip_and_emit 不计入 cf 累加器(对应 cf=0)
  - 失败返回独立 FailureDecisionReport(不复用 PrivateSkipDecisionReport, 字段名级别硬区分)

D9.4 决策(2026-06-15 锁定):
  - C3 决策 1: NoteStructurerService 不接 PolicyEngine(notes 无草稿审阅流)
  - C3 决策 2: 简化 4 依赖为 3 依赖 — store(必) + llm_provider(必) + event_store(可选)
  - C3 决策 3: tags 长度 3-10 锁定, category 6 类锁定, 后续扩枚举需 B 类审批
  - C3 决策 4: NoteStore 新增 mark_structured(apple_note_id, tags) 公共方法(对 plan
    决策 3 微调, 因 D9.1 NoteStore 没暴露 session() 上下文方法)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from loguru import logger
from sqlalchemy.exc import OperationalError, SQLAlchemyError  # D3.3.3 教训应用

from my_ai_employee.ai.capability import TaskType
from my_ai_employee.ai.prompts.note_structurer import (
    build_system_prompt as _build_note_system_prompt,
)
from my_ai_employee.ai.prompts.note_structurer import (
    build_user_message as _build_note_user_message,
)
from my_ai_employee.ai.providers import (
    LLMError,
    LLMResponse,
    LLMResponseError,
)
from my_ai_employee.db.notes import Note, NoteStore

# ===== 业务常量 =====

# 6 类业务常量(与 prompts/note_structurer.py 6 类严格 1:1, 严判时复用)
_NOTE_CATEGORIES: frozenset[str] = frozenset(
    {"URGENT", "TODO", "FYI", "SPAM", "PERSONAL", "DEFAULT"}
)

# 业务阻断 reason 锁定白名单(week2-mvp.md D9.4 锁定, 扩枚举需 B 类)
_PRIVATE_SKIP_REASON: Literal["is_private"] = "is_private"

# 技术失败 reason 锁定白名单
_TECHNICAL_FAILURE_REASONS: frozenset[str] = frozenset({"llm_failure", "db_failure"})

# tags 长度上下界(week2-mvp.md D9.4 锁定)
_TAGS_MIN_COUNT: int = 3
_TAGS_MAX_COUNT: int = 10

# body 字符数(用于审计, 实际 LLM 调用前已被 prompts.build_user_message 截断到 2000)
_BODY_MAX_CHARS_AUDIT: int = 8000

# Latency 上界(D4.7.3 v1.0.4 P1-2 契约 1 锁定, 1 万字符 body 30s LLM 推理上限)
_MAX_LATENCY_MS: int = 30_000


# ===== 业务异常 =====


class NoteNotFoundError(Exception):
    """业务层异常: apple_note_id 不存在(D9.4).

    Adapter 层(NoteStructurerService)接住此异常,转写
    record_failure_and_emit,走技术失败入口(reason="db_failure")。

    Attributes:
        apple_note_id: 不存在的 Apple ID
    """

    def __init__(self, message: str, *, apple_note_id: str) -> None:
        super().__init__(message)
        self.apple_note_id = apple_note_id


# ===== 公共严判 helper(D4.7.3 v1.0.5 P1 范本:严判下沉到 helper)=====


def _validate_apple_note_id(apple_note_id: Any) -> str:
    """严判 apple_note_id 非空白 str(1-128 字符)."""
    if type(apple_note_id) is not str:
        raise ValueError(
            f"apple_note_id 必须是 str, 实际 type={type(apple_note_id).__name__},"
            f" value={apple_note_id!r}"
        )
    stripped = apple_note_id.strip()
    if not stripped:
        raise ValueError(f"apple_note_id 必非空(经 strip()), 实际 {apple_note_id!r}")
    if len(stripped) > 128:
        raise ValueError(f"apple_note_id 长度超 128(实际 {len(stripped)})")
    return stripped


def _validate_note_category(category: Any) -> str:
    """严判 category ∈ 6 类(week2-mvp.md D9.4 锁定)."""
    if type(category) is not str:
        raise ValueError(
            f"category 必须是 str, 实际 type={type(category).__name__}, value={category!r}"
        )
    if category not in _NOTE_CATEGORIES:
        raise ValueError(f"category 必须在 {sorted(_NOTE_CATEGORIES)} 之一, 实际 {category!r}")
    return category


def _validate_tags(tags: Any) -> list[str]:
    """严判 tags 非空 list[str](3-10 个, 每项 strip 非空)."""
    if not isinstance(tags, list):
        raise ValueError(f"tags 必须是 list[str], 实际 type={type(tags).__name__}, value={tags!r}")
    if len(tags) < _TAGS_MIN_COUNT or len(tags) > _TAGS_MAX_COUNT:
        raise ValueError(
            f"tags 长度必须在 [{_TAGS_MIN_COUNT}, {_TAGS_MAX_COUNT}], 实际 {len(tags)}"
        )
    cleaned: list[str] = []
    for idx, item in enumerate(tags):
        if not isinstance(item, str):
            raise ValueError(
                f"tags[{idx}] 必须是 str, 实际 type={type(item).__name__}, value={item!r}"
            )
        stripped = item.strip()
        if not stripped:
            raise ValueError(f"tags[{idx}] 仅含空白字符, 应传非空或非纯空白, 实际 {item!r}")
        if len(stripped) > 20:
            raise ValueError(f"tags[{idx}] 单元素长度超 20(实际 {len(stripped)}), 实际 {item!r}")
        cleaned.append(stripped)
    return cleaned


def _validate_latency_ms(latency_ms: Any) -> int:
    """严判 latency_ms int(非 bool) >= 0."""
    if type(latency_ms) is bool or not isinstance(latency_ms, int) or latency_ms < 0:
        raise ValueError(
            f"latency_ms 必须是原生 int(非 bool) >= 0,"
            f" 实际 type={type(latency_ms).__name__}, value={latency_ms!r}"
        )
    return latency_ms


def _validate_model_full_id(model_full_id: Any) -> str:
    """严判 model_full_id 非空白 str."""
    if type(model_full_id) is not str or not model_full_id.strip():
        raise ValueError(
            f"model_full_id 必填非空白 str(strip() 非空),"
            f" 实际 type={type(model_full_id).__name__}, value={model_full_id!r}"
        )
    return model_full_id


def _validate_body_length(body_length: Any) -> int:
    """严判 body_length int(非 bool) >= 0."""
    if type(body_length) is bool or not isinstance(body_length, int) or body_length < 0:
        raise ValueError(
            f"body_length 必须是原生 int(非 bool) >= 0,"
            f" 实际 type={type(body_length).__name__}, value={body_length!r}"
        )
    return body_length


# ===== 3 类可观测报告(D4.7.3 DecisionReport 范本简化版)=====


@dataclass(frozen=True)
class StructuredNote:
    """D9.4 业务层接入的可观测报告(成功结构化版本).

    Attributes:
        apple_note_id: 笔记唯一标识
        category: 6 类之一
        tags: 3-10 个非空字符串
        model_full_id: 实际调用的 provider/model
        latency_ms: LLM 调用耗时
        body_length: 笔记正文长度(原始, 调用前已被截断到 2000)
    """

    apple_note_id: str
    category: str
    tags: list[str]
    model_full_id: str
    latency_ms: int
    body_length: int

    def __post_init__(self) -> None:
        """6 字段契约自洽校验(D4.7.3 v1.0.5 P1 范本)."""
        _validate_apple_note_id(self.apple_note_id)
        _validate_note_category(self.category)
        # tags 严判 + 用 object.__setattr__ 替换为清洗后的 list(frozen dataclass 限制)
        object.__setattr__(self, "tags", _validate_tags(self.tags))
        _validate_model_full_id(self.model_full_id)
        _validate_latency_ms(self.latency_ms)
        _validate_body_length(self.body_length)


@dataclass(frozen=True)
class PrivateSkipDecisionReport:
    """D9.4 业务层接入的可观测报告(业务阻断: is_private=True 跳过 LLM).

    业务定义(沿 D4.7.3 v1.0.1 P1-1 范本: 业务阻断 ≠ 技术失败):
      - is_private=True 的笔记: D9.1 NoteStore.insert 时已标记, NoteStructurer
        不调 LLM(避免消耗 token + 业务无关)
      - 不计入 cf 累加器(业务阻断永不 retry, 沿 drafter SPAM 业务硬阻断范本)

    Attributes:
        apple_note_id: 笔记唯一标识
        reason: 阻断原因(锁定 "is_private", 扩枚举需 B 类)
        kind: Literal["business_blocked"](类型层面固化, 与 FailureDecisionReport 区分)
    """

    apple_note_id: str
    reason: Literal["is_private"] = _PRIVATE_SKIP_REASON
    kind: Literal["business_blocked"] = "business_blocked"

    def __post_init__(self) -> None:
        """字段契约自洽校验."""
        _validate_apple_note_id(self.apple_note_id)
        if self.reason != _PRIVATE_SKIP_REASON:
            raise ValueError(
                f"PrivateSkipDecisionReport.reason 必为 '{_PRIVATE_SKIP_REASON}',"
                f" 实际 {self.reason!r}"
            )
        if self.kind != "business_blocked":
            raise ValueError(
                f"PrivateSkipDecisionReport.kind 必为 'business_blocked'"
                f" (D4.7.3 v1.0.2 P2-1 类型层面固化), 实际 {self.kind!r}"
            )


@dataclass(frozen=True)
class FailureDecisionReport:
    """D9.4 业务层接入的可观测报告(技术失败版本).

    D4.7.3 v1.0.2 P1-1 真修(沿 drafter 范本): 独立类型, 字段名级别硬区分业务阻断。
    - PrivateSkipDecisionReport 用 kind="business_blocked" + blocked=True
    - FailureDecisionReport 用 kind="technical_failure" + failed=True
    - 通用 `if report.failed` 检查会误计业务阻断, 用字段名级别区分

    Attributes:
        apple_note_id: 笔记唯一标识
        last_error: 失败原因(必填非空, 截断到 200 字符)
        consecutive_failures: 连续失败次数(>= 1, 业务阻断允许 0, 技术失败必填 >= 1)
        reason: 失败原因类别("llm_failure" / "db_failure", 锁定白名单)
        kind: Literal["technical_failure"](类型层面固化, 与 PrivateSkipDecisionReport 区分)
    """

    apple_note_id: str
    last_error: str
    consecutive_failures: int
    reason: Literal["llm_failure", "db_failure"]
    kind: Literal["technical_failure"] = "technical_failure"
    failed: Literal[True] = True

    def __post_init__(self) -> None:
        """字段契约自洽校验(D4.7.3 v1.0.5 P1 范本: 双层防御之一)."""
        _validate_apple_note_id(self.apple_note_id)
        # last_error 严判 strip() 语义非空(D4.7.3 v1.0.5 P2-2 范本)
        if not isinstance(self.last_error, str) or not self.last_error.strip():
            raise ValueError(
                f"FailureDecisionReport.last_error 必填非空白 str(strip() 非空),"
                f" 实际 type={type(self.last_error).__name__}, value={self.last_error!r}"
            )
        if (
            type(self.consecutive_failures) is bool
            or not isinstance(self.consecutive_failures, int)
            or self.consecutive_failures < 1
        ):
            raise ValueError(
                f"FailureDecisionReport.consecutive_failures 必须是 int(非 bool) >= 1"
                f" (D9.4 决策: 技术失败必填 cf, 与 PrivateSkipDecisionReport 区分),"
                f" 实际 type={type(self.consecutive_failures).__name__},"
                f" value={self.consecutive_failures!r}"
            )
        if self.reason not in _TECHNICAL_FAILURE_REASONS:
            raise ValueError(
                f"FailureDecisionReport.reason 必须在 {sorted(_TECHNICAL_FAILURE_REASONS)}"
                f" 之一, 实际 {self.reason!r}"
            )
        if self.kind != "technical_failure":
            raise ValueError(
                f"FailureDecisionReport.kind 必为 'technical_failure'"
                f" (D4.7.3 v1.0.2 P2-1 类型层面固化), 实际 {self.kind!r}"
            )
        if self.failed is not True:
            raise ValueError(
                f"FailureDecisionReport.failed 必为 True"
                f" (D4.7.3 v1.0.2 P1-1 Literal[True] 类型层面固化),"
                f" 实际 {self.failed!r}"
            )


# ===== D9.4 业务层主类 =====


class NoteStructurerService:
    """D9.4 业务层接入适配器 — NotePrompts 接入 NoteStore + LLM Router.

    简化版 D4.7.3 EmailDrafterAdapter:
      - 必传: store(NoteStore) + llm_provider(LLMRouter)
      - 可选: event_store(EventStore | None) — 默认 None 跳过
      - 不接 PolicyEngine / Heartbeat / LaneBoard(notes 无"草稿 → 审阅 → 发送"流)

    3 入口互斥(沿 D4.7.3 范本):
      - structure_and_emit(apple_note_id) → StructuredNote(成功)
      - record_private_skip_and_emit(apple_note_id) → PrivateSkipDecisionReport
        (业务阻断, is_private=True 跳过 LLM)
      - record_failure_and_emit(apple_note_id, exc) → FailureDecisionReport
        (技术失败, LLM/DB 异常, 触发 retry/escalate)

    用法(生产):
        from my_ai_employee.ai.note_structurer import NoteStructurerService
        from my_ai_employee.db.notes import NoteStore
        from my_ai_employee.ai.router import get_router

        store = NoteStore(sessionmaker)
        router = get_router()
        structurer = NoteStructurerService(store=store, llm_provider=router)

        # 成功
        result = structurer.structure_and_emit(apple_note_id="x-coredata://note-001")
        assert isinstance(result, StructuredNote)
        assert result.category in {"URGENT", "TODO", "FYI", "SPAM", "PERSONAL", "DEFAULT"}

        # 业务阻断(is_private=True 笔记)
        report = structurer.record_private_skip_and_emit(apple_note_id="x-coredata://priv-001")
        assert isinstance(report, PrivateSkipDecisionReport)
    """

    def __init__(
        self,
        *,
        store: NoteStore,
        llm_provider: Any,  # LLMRouter(协议 duck type, 避免循环 import)
        event_store: Any | None = None,  # EventStore(协议 duck type)
    ) -> None:
        """初始化.

        Args:
            store: NoteStore 实例(D9.1 必传)
            llm_provider: LLMRouter 实例(D4.1 必传, 接受 duck type)
            event_store: EventStore 实例(可选, None 时跳过落 events)
        """
        if store is None:
            raise ValueError(f"store 必传非 None NoteStore, 实际 {type(store).__name__}")
        if llm_provider is None:
            raise ValueError(
                f"llm_provider 必传非 None LLMRouter, 实际 {type(llm_provider).__name__}"
            )
        self._store = store
        self._llm = llm_provider
        self._event_store = event_store  # 可选

    # ===== 私有 helper =====

    def _emit_event(
        self,
        *,
        apple_note_id: str,
        outcome: str,
        payload: dict[str, Any],
    ) -> None:
        """可选落 events(沿 D4.7.3 Heartbeat 范本: 失败不抛, 仅 logger).

        设计: D9.4 阶段 events 落库是可选增强, 失败不阻塞业务流.
        """
        if self._event_store is None:
            return
        try:
            from my_ai_employee.events.models import EventStatus, EventType  # noqa: I001

            self._event_store.insert(
                event=EventType.LLM_CALL_STARTED,  # 复用 LLM_CALL 系列, 后续可加 NOTE_STRUCTURED
                status=EventStatus.SUCCEEDED if outcome == "success" else EventStatus.FAILED,
                source="note_structurer",
                subject_id=apple_note_id,
                extra=payload,
            )
        except Exception as e:  # noqa: BLE001 — 落 events 失败不阻塞业务流
            logger.warning(
                f"[note_structurer] 落 events 失败(非阻塞) | apple_note_id={apple_note_id}"
                f" | outcome={outcome} | err={type(e).__name__}: {e}"
            )

    # ===== 3 入口 =====

    def structure_and_emit(
        self, apple_note_id: str
    ) -> StructuredNote | PrivateSkipDecisionReport | FailureDecisionReport:
        """成功结构化主入口: 查 note → 业务阻断判别 → 调 LLM → 写 tags → 落 events.

        业务流程:
          1. 查 NoteStore.find_by_apple_id(apple_note_id)
          2. is_private=True → record_private_skip_and_emit(本路径)
          3. 构造 SYSTEM + user 消息(沿 prompts/note_structurer.py 范本)
          4. 调 llm_provider.route(TaskType.STRUCTURE, messages)
          5. 解析 LLMResponse.content(裸 JSON `{"category", "tags"}`)
          6. 调 NoteStore.mark_structured(apple_note_id, tags) 写 DB
          7. 落 events(可选, 失败不阻塞)
          8. 返回 StructuredNote

        Args:
            apple_note_id: 笔记唯一标识(已存在 Note row)

        Returns:
            StructuredNote(成功)/ PrivateSkipDecisionReport(业务阻断) /
            FailureDecisionReport(技术失败, 3 入口互斥返回 1 种)

        Raises:
            ValueError: 参数 type 错(编程错误, 透传不包装)
        """
        apple_note_id = _validate_apple_note_id(apple_note_id)

        # 1. 查 note
        note: Note | None = self._store.find_by_apple_id(apple_note_id)
        if note is None:
            err = NoteNotFoundError(
                f"apple_note_id={apple_note_id!r} 不存在, 无法 structure_and_emit",
                apple_note_id=apple_note_id,
            )
            logger.warning(f"[note_structurer] {err}")
            return self.record_failure_and_emit(apple_note_id, err, reason="db_failure")

        # 2. 业务阻断(is_private=True 跳过 LLM)
        if note.is_private:
            logger.info(
                f"[note_structurer] 业务阻断(is_private=True 跳过 LLM) |"
                f" apple_note_id={apple_note_id}"
            )
            report = self.record_private_skip_and_emit(apple_note_id)
            self._emit_event(
                apple_note_id=apple_note_id,
                outcome="business_blocked",
                payload={"reason": "is_private"},
            )
            return report

        # 3. 构造 messages
        try:
            system_prompt = _build_note_system_prompt(note_category=None)
            user_messages = _build_note_user_message(
                title=note.title or "",
                apple_note_id=apple_note_id,
                body_excerpt=note.body or "",
                note_category=None,
            )
            messages = [{"role": "system", "content": system_prompt}] + user_messages
        except Exception as e:  # noqa: BLE001 — 构造 prompt 失败是技术失败
            logger.error(
                f"[note_structurer] 构造 prompt 失败 | apple_note_id={apple_note_id}"
                f" | err={type(e).__name__}: {e}"
            )
            return self.record_failure_and_emit(apple_note_id, e, reason="llm_failure")

        # 4. 调 LLM
        try:
            response: LLMResponse = self._llm.route(
                TaskType.STRUCTURE, messages, temperature=0.3, max_tokens=512
            )
        except (LLMError, LLMResponseError) as e:
            logger.error(
                f"[note_structurer] LLM 调用失败 | apple_note_id={apple_note_id}"
                f" | err={type(e).__name__}: {e}"
            )
            return self.record_failure_and_emit(apple_note_id, e, reason="llm_failure")

        # 5. 解析 LLM 响应(裸 JSON `{"category", "tags"}`, 沿 drafter 契约 2)
        try:
            category, tags = _parse_structurer_response(response.content)
        except (LLMResponseError, ValueError) as e:
            logger.error(
                f"[note_structurer] LLM 响应解析失败 | apple_note_id={apple_note_id}"
                f" | err={type(e).__name__}: {e}"
            )
            return self.record_failure_and_emit(apple_note_id, e, reason="llm_failure")

        # 6. 写 tags(NoteStore.mark_structured 沿 D9.4 决策 4)
        try:
            self._store.mark_structured(apple_note_id, tags)
        except (ValueError, OperationalError, SQLAlchemyError) as e:
            logger.error(
                f"[note_structurer] 写 tags 失败 | apple_note_id={apple_note_id}"
                f" | err={type(e).__name__}: {e}"
            )
            return self.record_failure_and_emit(apple_note_id, e, reason="db_failure")

        # 7. 落 events(可选)
        self._emit_event(
            apple_note_id=apple_note_id,
            outcome="success",
            payload={
                "category": category,
                "tags_count": len(tags),
                "model_full_id": response.model_full_id,
                "latency_ms": response.latency_ms,
            },
        )

        # 8. 成功返回
        return StructuredNote(
            apple_note_id=apple_note_id,
            category=category,
            tags=tags,
            model_full_id=response.model_full_id,
            latency_ms=response.latency_ms,
            body_length=len(note.body or ""),
        )

    def record_private_skip_and_emit(self, apple_note_id: str) -> PrivateSkipDecisionReport:
        """业务阻断入口: is_private=True 笔记, 不调 LLM, 永不 retry.

        v0.2.1 #4 增量(2026-06-17):
          - 同步调 NoteStore.mark_private_skip(apple_note_id) 写 sync_status='PRIVATE_SKIP'
          - 状态机守卫 NEW → PRIVATE_SKIP 唯一合法转换
          - 异常透传:ValueError(状态机守卫)/OperationalError(DB 锁)

        Args:
            apple_note_id: 笔记唯一标识

        Returns:
            PrivateSkipDecisionReport

        Raises:
            ValueError: 状态机守卫拒绝非法转换(非 NEW 状态)
            OperationalError: DB 锁/连接错误(透传)
        """
        apple_note_id = _validate_apple_note_id(apple_note_id)
        logger.info(
            f"[note_structurer] record_private_skip_and_emit | apple_note_id={apple_note_id}"
        )
        # v0.2.1 #4: 同步写 sync_status='PRIVATE_SKIP'(状态机守卫)
        # 设计:mark_private_skip 抛 ValueError 时(状态机守卫拒绝/note 不存在),仅 log warning
        # 不重抛,因为服务契约允许对未入库或已转换状态的 note 调业务阻断入口
        # OperationalError(DB 锁) 透传(沿 D3.3.3 教训 except 范围窄化)
        try:
            self._store.mark_private_skip(apple_note_id)
        except ValueError as e:
            logger.warning(
                f"[note_structurer] mark_private_skip 状态机守卫拒绝/note 不存在"
                f" | apple_note_id={apple_note_id} | err={e}"
            )
        return PrivateSkipDecisionReport(apple_note_id=apple_note_id)

    def record_failure_and_emit(
        self,
        apple_note_id: str,
        exc: BaseException,
        *,
        reason: Literal["llm_failure", "db_failure"] = "llm_failure",
        consecutive_failures: int = 1,
    ) -> FailureDecisionReport:
        """技术失败入口: LLM 异常 / DB 异常, 触发 retry / escalate.

        v0.2.1 #4 增量(2026-06-17):
          - 同步调 NoteStore.mark_failed(apple_note_id, error_class=...) 写 sync_status='FAILED'
          - 状态机守卫 NEW → FAILED 唯一合法转换(FAILED → STRUCTURED 由 mark_structured 处理)
          - 异常透传:ValueError(状态机守卫)/OperationalError(DB 锁)
          - mark_failed 失败不阻断 FailureDecisionReport 返回(沿 D3.3.3 教训 except 范围窄化)

        Args:
            apple_note_id: 笔记唯一标识
            exc: 触发的异常(LLMError / OperationalError / ValueError ...)
            reason: 失败原因类别("llm_failure" / "db_failure", 锁定白名单)
            consecutive_failures: 连续失败次数(必填 >= 1, 默认 1)

        Returns:
            FailureDecisionReport

        Raises:
            ValueError: reason / consecutive_failures 严判失败 OR 状态机守卫拒绝
            OperationalError: DB 锁/连接错误(透传)
        """
        apple_note_id = _validate_apple_note_id(apple_note_id)
        # reason 类型严判(锁白名单)
        if type(reason) is not str or reason not in _TECHNICAL_FAILURE_REASONS:
            raise ValueError(
                f"reason 必须在 {sorted(_TECHNICAL_FAILURE_REASONS)} 之一,"
                f" 实际 type={type(reason).__name__}, value={reason!r}"
            )
        # consecutive_failures 严判
        if (
            type(consecutive_failures) is bool
            or not isinstance(consecutive_failures, int)
            or consecutive_failures < 1
        ):
            raise ValueError(
                f"consecutive_failures 必须是原生 int(非 bool) >= 1,"
                f" 实际 type={type(consecutive_failures).__name__},"
                f" value={consecutive_failures!r}"
            )
        # last_error 转 str + 截断到 200(防 audit 撑爆, 沿 D4.7.3 v1.0.4 P1-1 范本)
        last_error = str(exc)[:200]
        error_class = type(exc).__name__
        logger.error(
            f"[note_structurer] record_failure_and_emit | apple_note_id={apple_note_id}"
            f" | reason={reason} | cf={consecutive_failures} | err={error_class}: {last_error}"
        )
        # v0.2.1 #4: 同步写 sync_status='FAILED'(状态机守卫 NEW → FAILED)
        # 设计:mark_failed 抛 ValueError 时(状态机守卫拒绝/note 不存在),仅 log warning
        # 不重抛,因为服务契约允许对未入库或已转换状态的 note 调失败入口(例如 retry 时已在 FAILED)
        # OperationalError(DB 锁) 透传(沿 D3.3.3 教训 except 范围窄化)
        try:
            self._store.mark_failed(apple_note_id, error_class=error_class)
        except ValueError as e:
            logger.warning(
                f"[note_structurer] mark_failed 状态机守卫拒绝/note 不存在"
                f" | apple_note_id={apple_note_id} | err={e}"
            )
        return FailureDecisionReport(
            apple_note_id=apple_note_id,
            last_error=last_error,
            consecutive_failures=consecutive_failures,
            reason=reason,  # type: ignore[arg-type]  # Literal 严判已过
        )


# ===== 私有 helper: 解析 LLM 响应(沿 drafter 契约 2 裸 JSON)=====


def _parse_structurer_response(raw_content: str) -> tuple[str, list[str]]:
    """解析 LLM 响应裸 JSON `{"category", "tags"}` 契约.

    契约(沿 D4.7.2 drafter 契约 2 + D9.4 严判):
      - 必须严格 JSON, 无 markdown 包裹 / 无 prose / 无 ```json ... ```
      - category 必 ∈ 6 类
      - tags 必 3-10 个非空字符串

    Args:
        raw_content: LLM 原始响应字符串

    Returns:
        (category, tags) tuple

    Raises:
        LLMResponseError: JSON 解析失败 / 字段缺 / 类型错 / 枚举外
    """
    import json

    if not isinstance(raw_content, str) or not raw_content.strip():
        raise LLMResponseError(f"LLM 响应为空或非 str, 实际 {type(raw_content).__name__}")
    try:
        # 沿 drafter 范本: json.loads(stripped) 唯一解析路径, 不剥离 ```json fence
        data = json.loads(raw_content.strip())
    except json.JSONDecodeError as e:
        raise LLMResponseError(
            f"LLM 响应非严格 JSON(契约 2 拒 markdown 包裹), 实际 {raw_content[:200]!r}"
        ) from e
    if not isinstance(data, dict):
        raise LLMResponseError(f"LLM 响应顶层不是 dict, 实际 {type(data).__name__}, value={data!r}")
    if "category" not in data or "tags" not in data:
        raise LLMResponseError(
            f"LLM 响应缺必填字段(必含 category + tags), 实际 keys={list(data.keys())}"
        )
    category = data["category"]
    tags = data["tags"]
    # 严判 category ∈ 6 类(透传严判 helper, 错误归 LLMResponseError)
    try:
        category = _validate_note_category(category)
    except ValueError as e:
        raise LLMResponseError(f"LLM 响应 category 非法: {e}") from e
    # 严判 tags(透传严判 helper, 错误归 LLMResponseError)
    try:
        tags = _validate_tags(tags)
    except ValueError as e:
        raise LLMResponseError(f"LLM 响应 tags 非法: {e}") from e
    return category, tags


# ===== 模块导出 =====

__all__ = [
    "NoteStructurerService",
    "NoteNotFoundError",
    "StructuredNote",
    "PrivateSkipDecisionReport",
    "FailureDecisionReport",
]
