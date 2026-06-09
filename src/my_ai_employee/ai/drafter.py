"""D4.7 — 邮件草稿生成器(3 类 tone 枚举).

设计要点:

  - 复用 D4.1.1 LLM Router:`router.route(TaskType.DRAFT, messages)` 自动走
    DeepSeek → Qwen → M3 fallback 链(`fallback.FALLBACK_CHAINS[TaskType.DRAFT]` 已配)
  - 严判 LLM 响应:必须严格 JSON `{"subject": str, "body": str, "tone": <枚举>}`
    - 字段缺 / 类型错 / tone 不在 3 类 → 抛 DrafterResponseError
    - 编程错误(type/ValueError) 透传(D3.3.3 教训:不 catch-all 兜底)
  - 批量:`draft_batch` 顺序串行(避免触发熔断/雪崩,D4.7.1+ 改并发)
  - 不写 DB / 不接 events / 不接 policy(本步只做"草稿生成"原子能力,契约 4)
  - 不创建 Mail.app 草稿 / 不接 iCloud CalDAV(契约 4)

D5+ 业务层接入用 `EmailDrafterAdapter`(`policy/integration.py` 新增),
把草稿结果(subject + body + tone)封装成 TaskPacket 喂 PolicyEngine,落 events + lane,
沿用 D4.5 `SyncPolicyAdapter` 4 依赖范本 + D4.6 `EmailClassifierAdapter` 双入口架构。

参考 D3.3.3 教训("异常范围要窄化"):
  - DrafterResponseError 是业务异常(LLM 输出脏),由调用方决定重试
  - 编程错误(参数 type 错) → ValueError 透传,不在本模块包装

D4.7 4 项契约(2026-06-09 用户审批锁定,D4.7.1 起始固定):

  1. **草稿无 confidence 字段** → 业务验收用**明确长度/必填/tone 枚举**判定
     (`validate_draft` 公共 API: subject 非空 AND body 10-8000 AND tone ∈ 3 类)
  2. **拒 markdown-wrapped JSON**(不剥离 ```json ... ``` fence)→ LLM 必须
     返回**裸 JSON**,违者拒收触发 retry;body 字段内容允许 markdown
  3. **tone 枚举锁定**:FORMAL / FRIENDLY / CONCISE 三选一,后续扩枚举需 B 类审批
  4. **范围限定**:D4.7 只生成草稿文本 + emit 业务事件 + 推进 Lane;不写
     `drafts` 数据库表、不创建 Mail.app 草稿、不接 iCloud CalDAV

D4.7.1 实施细节:
  - placeholder system prompt 内置(D4.7.2 替换为 `ai/prompts/draft.py`)
  - 严判入口:`type() is str` 严判,`isinstance(x, bool)` 拒 bool 子类
  - 平衡括号定位 JSON(复用 D4.6 范本,无强制字段顺序)
  - 4 项契约测试:契约 1 (业务验收) / 契约 2 (拒 markdown) / 契约 3 (tone 锁定) /
    契约 4 (范围限定,ast 静态验证不 import drafts/events/db 模块)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger

from .capability import TaskType
from .classifier import EmailCategory
from .providers import LLMError
from .router import LLMRouter, get_router

# ===== tone 枚举(契约 3 锁定 3 类)=====


class DraftTone(StrEnum):
    """草稿语气 3 类枚举(StrEnum, 与 LLM 输出严格 1:1).

    D4.7.1 起始固定,后续扩枚举需 B 类审批。
    顺序固定(FORMAL → FRIENDLY → CONCISE),业务层做"按语气分组"时可直接用
    `list(DraftTone)` 排序。
    """

    FORMAL = "FORMAL"  # 正式: 商务 / 官方 / 客户沟通
    FRIENDLY = "FRIENDLY"  # 友好: 同事 / 熟人 / 协作
    CONCISE = "CONCISE"  # 简洁: 通知 / 确认 / 单点沟通


# 3 类枚举值集合(O(1) 校验)
_DRAFT_TONE_CHOICES: frozenset[str] = frozenset(t.value for t in DraftTone)

# 5 类邮件标签值(P1-1: 严判 email_category 字符串)
# Drafter 是 D4.6 分类结果的下游消费者, 严判字符串 ∈ 5 类
_EMAIL_CATEGORY_VALUES: frozenset[str] = frozenset(c.value for c in EmailCategory)


# ===== 业务异常(D3.3.3 教训:窄化异常范围)=====


class DrafterError(Exception):
    """草稿生成器业务异常基类."""


class DrafterResponseError(DrafterError):
    """LLM 响应解析失败(非严格 JSON / tone 不在 3 类 / 字段类型错 / markdown-wrapped).

    Attributes:
        raw_content: LLM 原始输出(便于排查,截断到 500 字符)
        reason: 解析失败原因(机器可读,如 'invalid_tone=APOLOGETIC' / 'markdown_fenced')
    """

    def __init__(self, message: str, raw_content: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.raw_content = raw_content[:500]
        self.reason = reason


# ===== 草稿结果数据类 =====


@dataclass(frozen=True)
class DraftResult:
    """单邮件草稿结果.

    Attributes:
        subject: 草稿主题(非空, 1-200 字符)
        body: 草稿正文(10-8000 字符, 内容允许 markdown)
        tone: 3 类语气之一(DraftTone 枚举)
        model_full_id: 实际调用的 provider/model(便于审计/计费)
        latency_ms: 单次草稿生成耗时
        raw_content: LLM 原始响应(便于排查,截断到 500 字符)
    """

    subject: str
    body: str
    tone: DraftTone
    model_full_id: str
    latency_ms: int
    raw_content: str

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(便于 JSON 化)."""
        return {
            "subject": self.subject,
            "body": self.body,
            "tone": self.tone.value,
            "model_full_id": self.model_full_id,
            "latency_ms": self.latency_ms,
            "raw_content": self.raw_content,
        }


# ===== 草稿生成器主类 =====


class EmailDrafter:
    """邮件草稿生成器(D4.7 主类).

    用法:

        from my_ai_employee.ai import EmailDrafter, DraftTone
        from my_ai_employee.ai.router import get_router

        router = get_router()
        drafter = EmailDrafter(router=router)
        result = drafter.draft(
            subject="[紧急] 客户投诉",
            sender="client@example.com",
            body_excerpt="订单 #1234 严重延迟...",
            email_category=EmailCategory.URGENT,
            tone=DraftTone.FORMAL,
        )
        assert result.tone == DraftTone.FORMAL
        assert 10 <= len(result.body) <= 8000

    设计:
      - router 可注入(测试时传 mock router, 生产传 get_router() 单例)
      - 严判响应(JSON 解析 + tone 3 类 + 拒 markdown-wrapped)
      - 不写 DB / 不接 events(纯生成能力,契约 4)
    """

    # 输入 body_excerpt 最大长度(防止巨型正文把 prompt 撑爆)
    MAX_BODY_CHARS = 2000

    # 草稿长度约束(契约 1: 业务验收明确长度/必填/tone 枚举)
    MIN_SUBJECT_CHARS = 1
    MAX_SUBJECT_CHARS = 200
    MIN_DRAFT_BODY_CHARS = 10
    MAX_DRAFT_BODY_CHARS = 8000

    def __init__(
        self,
        *,
        router: LLMRouter | None = None,
        max_tokens: int = 1024,
    ) -> None:
        """初始化草稿生成器.

        Args:
            router: LLM 路由器(默认 get_router() 单例)
            max_tokens: 输出上限(草稿需要中长响应,默认 1024 足够)
        """
        self._router = router or get_router()
        self._max_tokens = max_tokens
        # 运行时统计(可观测性, 类似 RouterStats)
        self._stats: dict[str, int] = {
            "total": 0,
            "success": 0,
            "response_error": 0,
            "validation_error": 0,
            "llm_error": 0,
        }

    def stats(self) -> dict[str, int]:
        """返回草稿生成器统计(便于 mmx policy status 等可观测性子命令)."""
        return dict(self._stats)

    def validate_draft(
        self,
        *,
        subject: str,
        body: str,
        tone: DraftTone | str,
    ) -> bool:
        """业务验收(契约 1 公共 API).

        验收规则:
          - subject: type is str AND 1 <= len <= 200(非空, 不超长)
          - body: type is str AND 10 <= len <= 8000(明确长度边界)
          - tone: DraftTone 枚举值 OR str ∈ {FORMAL, FRIENDLY, CONCISE}

        Args:
            subject: 草稿主题
            body: 草稿正文
            tone: 草稿语气(枚举或字符串)

        Returns:
            True = 通过验收 / False = 拒绝(任一字段不满足)

        Raises:
            ValueError: 参数 type 错(编程错误, 透传)
        """
        try:
            _validate_draft_subject(subject)
            _validate_draft_body(body)
            _validate_draft_tone(tone)
        except ValueError:
            return False
        return True

    def draft(
        self,
        *,
        subject: str,
        sender: str,
        body_excerpt: str,
        email_category: EmailCategory | str | None = None,
        tone: DraftTone | str = DraftTone.FORMAL,
    ) -> DraftResult:
        """单邮件草稿生成.

        Args:
            subject: 邮件主题(允许空字符串)
            sender: 发件人(允许空字符串)
            body_excerpt: 正文前 N 字符(> MAX_BODY_CHARS 时截断)
            email_category: 5 类邮件标签(D4.6 分类结果, 接受 EmailCategory 枚举 /
                            5 类字符串 / None; 6/9 P1-1 修复允许 D4.6 真实 handoff)
            tone: 草稿语气(默认 FORMAL)

        Returns:
            DraftResult(含 subject + body + tone + 调用模型)

        Raises:
            ValueError: 参数 type 错(编程错误, 透传)
            DrafterResponseError: LLM 响应解析失败(非严格 JSON / tone 不在 3 类 /
                                  markdown-wrapped / 字段类型错 / tone 与请求不一致)
            LLMError: 全链失败(router 抛, 由调用方决定 fallback)
        """
        # 严判入口(D4.4 P1 + D4.5 P0 教训应用)
        if type(subject) is not str:
            raise ValueError(f"subject 必须是 str, 实际 {type(subject).__name__}={subject!r}")
        if type(sender) is not str:
            raise ValueError(f"sender 必须是 str, 实际 {type(sender).__name__}={sender!r}")
        if type(body_excerpt) is not str:
            raise ValueError(
                f"body_excerpt 必须是 str, 实际 {type(body_excerpt).__name__}={body_excerpt!r}"
            )
        # P1-1 修复(6/9): 接受 EmailCategory | str | None
        # - EmailCategory 枚举直接接受(D4.6 ClassificationResult.category 真实 handoff)
        # - str 严判 ∈ 5 类(拒 'OOPS' 等非法值)
        # - None 允许(drafter 可独立运行, 不强制 D4.6 上下文)
        if email_category is not None:
            if isinstance(email_category, EmailCategory):
                pass  # 枚举直接接受
            elif type(email_category) is str:
                if email_category not in _EMAIL_CATEGORY_VALUES:
                    raise ValueError(
                        f"email_category 字符串必须 ∈ {sorted(_EMAIL_CATEGORY_VALUES)}, "
                        f"实际 {email_category!r}"
                    )
            else:
                raise ValueError(
                    f"email_category 必须是 EmailCategory 枚举 / str / None, "
                    f"实际 {type(email_category).__name__}"
                )
        # tone 入参允许 DraftTone 或 str, 内部统一转 DraftTone
        if isinstance(tone, DraftTone):
            tone_enum = tone
        elif type(tone) is str:
            # 严判字符串(契约 3 锁定 3 类, 大小写敏感)
            try:
                tone_enum = DraftTone(tone)
            except ValueError as e:
                raise ValueError(
                    f"tone 字符串必须 ∈ {sorted(_DRAFT_TONE_CHOICES)}, 实际 {tone!r}"
                ) from e
        else:
            raise ValueError(f"tone 必须是 DraftTone 或 str, 实际 {type(tone).__name__}")

        # 正文截断(防御巨型 body)
        if len(body_excerpt) > self.MAX_BODY_CHARS:
            body_excerpt = body_excerpt[: self.MAX_BODY_CHARS]

        self._stats["total"] += 1

        # 构造 messages(placeholder system prompt, D4.7.2 替换为 ai/prompts/draft.py)
        messages = [
            system_to_message(_PLACEHOLDER_SYSTEM_PROMPT),
            *build_user_message(
                subject=subject,
                sender=sender,
                body_excerpt=body_excerpt,
                email_category=email_category,
                tone=tone_enum,
            ),
        ]

        # 调 router(走 fallback 链, 熔断隔离, 单例统计)
        try:
            response = self._router.route(
                task_type=TaskType.DRAFT,
                messages=messages,
                temperature=0.7,  # 草稿任务: 中温保创意但稳定
                max_tokens=self._max_tokens,
            )
        except LLMError as e:
            self._stats["llm_error"] += 1
            logger.warning(f"[drafter] LLM 全链失败 | subject={subject!r} | err={e!r}")
            raise

        # 严判响应(D4.7 严判入口)
        # P1-3 修复(6/9): 强制 expected_tone, LLM 返回的 tone 必须 == 请求 tone
        try:
            draft_subject, draft_body, draft_tone = _parse_draft_response(
                response.content, expected_tone=tone_enum
            )
        except DrafterResponseError as e:
            self._stats["response_error"] += 1
            logger.warning(
                f"[drafter] 响应解析失败 | subject={subject!r} | "
                f"reason={e.reason} | raw={e.raw_content!r}"
            )
            raise

        # 业务验收(契约 1: 长度/必填/tone 严判)
        # - 不抛错(响应已 parse 成功),但记录 validation_error 计数
        # - D4.7.3 EmailDrafterAdapter 复用 validate_draft 公共 API 判定 business_accepted
        if not self.validate_draft(subject=draft_subject, body=draft_body, tone=draft_tone):
            self._stats["validation_error"] += 1
            logger.warning(
                f"[drafter] 草稿业务验收未通过(契约 1) | subject={draft_subject!r} | "
                f"body_len={len(draft_body)} | tone={draft_tone}"
            )
            # 不抛错: 业务验收未通过 ≠ LLM 死, 由 D4.7.3 Adapter 决定 fallback
            # (L704 教训: 业务验收独立于传输存活)

        self._stats["success"] += 1
        return DraftResult(
            subject=draft_subject,
            body=draft_body,
            tone=draft_tone,
            model_full_id=response.model_full_id,
            latency_ms=response.latency_ms,
            raw_content=response.content,
        )

    def draft_batch(
        self,
        emails: list[dict],
    ) -> list[DraftResult | DrafterResponseError | LLMError | ValueError | KeyError]:
        """批量草稿生成(顺序串行, 避免触发熔断).

        Args:
            emails: list[dict], 每条 dict 必须包含 subject/sender/body_excerpt 3 key
                   (类型不匹配 / 缺字段 → 异常入 results, 不静默吞掉, 不外抛)

        Returns:
            list[DraftResult | 异常], 与 emails 1:1 对齐
              - 成功: DraftResult
              - 响应解析失败: DrafterResponseError
              - LLM 全链失败: LLMError
              - 编程错误(非 dict): ValueError
              - 编程错误(缺字段): KeyError
            异常透传, 不静默吞掉(D3.3.3 教训)。
        """
        results: list[DraftResult | DrafterResponseError | LLMError | ValueError | KeyError] = []
        for i, email in enumerate(emails):
            if not isinstance(email, dict):
                results.append(ValueError(f"emails[{i}] 必须是 dict, 实际 {type(email).__name__}"))
                continue
            # 缺字段时 KeyError 收容入 list(D4.6 v1.0.2 P2-4 范本)
            missing_keys = [k for k in ("subject", "sender", "body_excerpt") if k not in email]
            if missing_keys:
                results.append(KeyError(f"emails[{i}] 缺字段 {missing_keys}"))
                continue
            try:
                result = self.draft(
                    subject=email["subject"],
                    sender=email["sender"],
                    body_excerpt=email["body_excerpt"],
                    email_category=email.get("email_category"),
                    tone=email.get("tone", DraftTone.FORMAL),
                )
                results.append(result)
            except (DrafterResponseError, LLMError, ValueError) as e:
                results.append(e)
        return results


# ===== 模块内辅助函数 =====


def system_to_message(content: str) -> dict:
    """把 system prompt 字符串转 OpenAI 风格 message dict.

    严判: content 必须是原生 str(D4.5 P0 教训应用)。
    """
    if type(content) is not str or not content:
        raise ValueError(f"system content 必填非空 str, 实际 {type(content).__name__}")
    return {"role": "system", "content": content}


def build_user_message(
    *,
    subject: str,
    sender: str,
    body_excerpt: str,
    email_category: EmailCategory | str | None = None,
    tone: DraftTone = DraftTone.FORMAL,
) -> list[dict]:
    """构造 user 消息列表(OpenAI 风格, D4.7.2 替换为 ai/prompts/draft.py).

    Args:
        subject: 邮件主题(可能为空)
        sender: 发件人
        body_excerpt: 正文前 N 字符(默认调用方截断到 2000 字符)
        email_category: 5 类邮件标签(来自 D4.6, 接受 EmailCategory 枚举 / str / None)
        tone: 草稿语气

    Returns:
        1 条 user 消息(多轮可扩展, 本步 D4.7.1 单轮)
    """
    # 严判
    if type(subject) is not str:
        raise ValueError(f"subject 必须是 str, 实际 {type(subject).__name__}")
    if type(sender) is not str:
        raise ValueError(f"sender 必须是 str, 实际 {type(sender).__name__}")
    if type(body_excerpt) is not str:
        raise ValueError(f"body_excerpt 必须是 str, 实际 {type(body_excerpt).__name__}")
    # P1-1 修复(6/9): 接受 EmailCategory | str | None
    if email_category is not None:
        if isinstance(email_category, EmailCategory):
            pass
        elif type(email_category) is str:
            if email_category not in _EMAIL_CATEGORY_VALUES:
                raise ValueError(
                    f"email_category 字符串必须 ∈ {sorted(_EMAIL_CATEGORY_VALUES)}, "
                    f"实际 {email_category!r}"
                )
        else:
            raise ValueError(
                f"email_category 必须是 EmailCategory 枚举 / str / None, "
                f"实际 {type(email_category).__name__}"
            )
    if not isinstance(tone, DraftTone):
        raise ValueError(f"tone 必须是 DraftTone 枚举, 实际 {type(tone).__name__}")

    # 枚举转字符串值(LLM prompt 友好)
    category_str = (
        email_category.value if isinstance(email_category, EmailCategory) else email_category
    )
    category_line = f"分类: {category_str}\n" if category_str else ""
    return [
        {
            "role": "user",
            "content": (
                f"主题: {subject or '(空)'}\n"
                f"发件人: {sender or '(空)'}\n"
                f"正文: {body_excerpt or '(空)'}\n"
                f"{category_line}"
                f"语气: {tone.value}"
            ),
        }
    ]


# Placeholder system prompt(D4.7.2 替换为 ai/prompts/draft.py)
# 临时约束: LLM 必须返回严格 JSON 3 字段 (subject + body + tone)
_PLACEHOLDER_SYSTEM_PROMPT = """你是邮件草稿生成助手,负责根据邮件主题/发件人/正文生成专业草稿。

语气(必须严格匹配 value, 大小写敏感, 契约 3 锁定 3 类):
  - FORMAL  : 正式, 商务 / 官方 / 客户沟通
  - FRIENDLY: 友好, 同事 / 熟人 / 协作
  - CONCISE : 简洁, 通知 / 确认 / 单点沟通

输出格式(严格 JSON, 无其他文字, 无 markdown 包裹, 契约 2):
{"subject": "<string>", "body": "<string>", "tone": "<FORMAL|FRIENDLY|CONCISE>"}

约束:
  - subject 1-200 字符, 非空
  - body 10-8000 字符, 内容允许 markdown
  - tone 必须是 FORMAL / FRIENDLY / CONCISE 三选一
  - 不允许额外文字 / ```json ... ``` 包裹 / 解释段落
"""


# ===== 3 个 _validate_draft_* helper(契约 1 公共 API,供 D4.7.3 严判下沉复用)=====


def _validate_draft_subject(subject: Any) -> None:
    """严判草稿 subject(契约 1).

    规则:
      - type 必须是 str(拒 bool 子类陷阱,D4.4 P1 教训)
      - 1 <= len <= 200(非空, 不超长)
      - 严判入口: type 错 → ValueError(编程错误, 透传)

    Raises:
        ValueError: 长度越界 / type 错(编程错误)
    """
    # 拒 bool 子类陷阱(isinstance(True, int) == True, 易误过)
    if type(subject) is not str:
        raise ValueError(f"subject 必须是 str, 实际 {type(subject).__name__}={subject!r}")
    if len(subject) < EmailDrafter.MIN_SUBJECT_CHARS:
        raise ValueError(f"subject 太短(契约 1): {len(subject)} < {EmailDrafter.MIN_SUBJECT_CHARS}")
    if len(subject) > EmailDrafter.MAX_SUBJECT_CHARS:
        raise ValueError(f"subject 太长(契约 1): {len(subject)} > {EmailDrafter.MAX_SUBJECT_CHARS}")


def _validate_draft_body(body: Any) -> None:
    """严判草稿 body(契约 1).

    规则:
      - type 必须是 str
      - 10 <= len <= 8000(明确长度边界)
      - 严判入口: type 错 → ValueError(编程错误, 透传)

    Raises:
        ValueError: 长度越界 / type 错
    """
    if type(body) is not str:
        raise ValueError(f"body 必须是 str, 实际 {type(body).__name__}={body!r}")
    if len(body) < EmailDrafter.MIN_DRAFT_BODY_CHARS:
        raise ValueError(f"body 太短(契约 1): {len(body)} < {EmailDrafter.MIN_DRAFT_BODY_CHARS}")
    if len(body) > EmailDrafter.MAX_DRAFT_BODY_CHARS:
        raise ValueError(f"body 太长(契约 1): {len(body)} > {EmailDrafter.MAX_DRAFT_BODY_CHARS}")


def _validate_draft_tone(tone: Any) -> None:
    """严判草稿 tone(契约 3 锁定 3 类).

    规则:
      - 必须是 DraftTone 枚举实例 OR str ∈ {FORMAL, FRIENDLY, CONCISE}
      - 大小写敏感(契约 3 锁定)
      - 严判入口: type 错 / 非法枚举值 → ValueError(编程错误, 透传)

    Raises:
        ValueError: 非法枚举值 / type 错
    """
    if isinstance(tone, DraftTone):
        return
    if type(tone) is str:
        if tone in _DRAFT_TONE_CHOICES:
            return
        raise ValueError(
            f"tone 必须是 DraftTone 枚举或 str ∈ {sorted(_DRAFT_TONE_CHOICES)}, 实际 {tone!r}"
        )
    raise ValueError(f"tone 必须是 DraftTone 枚举或 str, 实际 {type(tone).__name__}={tone!r}")


# ===== markdown fence 检测(契约 2 拒外层包裹)=====

# D4.7 契约 2 修复(6/9 P1-2): 只拒"外层包裹", body 内合法 code fence 允许
# - D4.7.1 初版用正则整段扫描 fence → 误杀 body 内的 ```python ... ``` 围栏
# - 6/9 改为: 优先 json.loads 整段, 失败再检测外层包裹(以 ``` 开头 AND 以 ``` 结尾)
# - 这样 LLM 可在 body 字段中正常输出 markdown 代码示例, 不被契约 2 误拒
# - D4.6 v1.0.1 P1-4 是"剥 fence", D4.7 改为"拒外层 fence" — 决择见 week1-mvp.md L706


def _has_outer_markdown_fence(raw: str) -> bool:
    """检测 raw 是否被外层 markdown fence 包裹(契约 2).

    判定: stripped 内容以 ``` 开头 AND 以 ``` 结尾(允许前后空行)。
    不再扫描内部任意位置的 fence(避免误杀 body 字段内的 code fence)。

    Args:
        raw: LLM 原始响应

    Returns:
        True = 外层被 fence 包裹(契约 2 拒收)
        False = 无外层包裹(继续走整段 JSON 解析或平衡括号定位)
    """
    if type(raw) is not str:
        return False  # 留到 _parse_draft_response 上层抛 type 错
    stripped = raw.strip()
    return stripped.startswith("```") and stripped.endswith("```")


# ===== 平衡括号定位(复用 D4.6 范本)=====


def _find_all_balanced_json(raw: str) -> list[str]:
    """扫描 raw, 返回所有平衡的 { ... } 块文本列表(不含外层字符).

    平衡括号扫描: 跟踪 { 与 } 嵌套深度, 忽略字符串内 / 转义后的括号.
    D4.6 v1.0.2 P2-3 范本复用: 找所有平衡 JSON 块, 便于 _extract_balanced_json
    在多个候选中选含 subject+body+tone 字段的。
    """
    blocks: list[str] = []
    start = raw.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(raw[start : i + 1])
                    break
        start = raw.find("{", start + 1)
    return blocks


def _extract_balanced_json_draft(raw: str) -> str | None:
    """扫描 raw, 返回第一个同时含 subject + body + tone 字段的平衡 JSON 块文本.

    D4.6 v1.0.1 P1-4 范本复用: 不再强制字段顺序, 允许 LLM 输出任意字段顺序。
    D4.6 v1.0.2 P2-3 范本复用: 扫描所有平衡 JSON 块, 选第一个同时含
    `subject` + `body` + `tone` 字段的(避免前面无关对象遮蔽草稿结果)。

    兜底: 若所有块都不含 3 字段, 返回第一个平衡 JSON(原 v1.0.1 行为)。
    全部无平衡 JSON 时返回 None(上层抛 no_balanced_json)。
    """
    blocks = _find_all_balanced_json(raw)
    for block in blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and {"subject", "body", "tone"} <= data.keys():
            return block
    return blocks[0] if blocks else None


# ===== 严判解析主函数(契约 2 拒外层 fence + 契约 3 tone 严判 + P1-3 强制)=====


def _parse_draft_response(
    content: Any,
    *,
    expected_tone: DraftTone | None = None,
) -> tuple[str, str, DraftTone]:
    """严判解析 LLM 草稿响应, 返回 (subject, body, tone).

    解析策略(D4.7 4 项契约 + 6/9 P1-2 + P1-3 应用):
      1. type() 严判 content 是 str
      2. **优先** `json.loads(content.strip())` 整段解析
         (允许 prose + JSON 混合 / body 内 code fence)
      3. 整段解析失败 → 检测**外层** markdown fence 包裹 → 拒收(契约 2)
      4. 兜底: 平衡括号定位 JSON(允许任意字段顺序)
      5. 严判 "subject" 字段: type is str, 复用 _validate_draft_subject
      6. 严判 "body" 字段: type is str, 复用 _validate_draft_body
      7. 严判 "tone" 字段: 必须是 3 类枚举之一(契约 3)
      8. **P1-3 强制**: 若传入 expected_tone, 返回 tone 必须 == expected_tone

    任何一步失败 → DrafterResponseError(业务异常, 可重试).
    编程错误(KeyError/TypeError 等在解析前) → 透传(不在本函数包装).

    Args:
        content: LLM 原始响应
        expected_tone: 请求的语气(6/9 P1-3 新增, 强制 LLM 返回一致 tone)
    """
    if type(content) is not str:
        raise DrafterResponseError(
            "LLM content 必须是 str",
            raw_content=str(content),
            reason=f"type={type(content).__name__}",
        )

    # 契约 2 (6/9 P1-2 修复): 优先整段 json.loads, 允许 body 内 code fence
    stripped = content.strip()
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError) as parse_err:
        # 整段不是合法 JSON → 检测是否被外层 fence 包裹
        if _has_outer_markdown_fence(content):
            raise DrafterResponseError(
                "LLM 响应被外层 markdown fence 包裹(契约 2: 拒收, 不剥离)",
                raw_content=content,
                reason="markdown_fenced_outer",
            ) from parse_err
        # 兜底: 平衡括号定位(允许 LLM 输出 prose + JSON 混合)
        json_text = _extract_balanced_json_draft(content)
        if json_text is None:
            raise DrafterResponseError(
                "未找到平衡的 JSON 块",
                raw_content=content,
                reason="no_balanced_json",
            ) from parse_err
        try:
            data = json.loads(json_text)
        except (json.JSONDecodeError, ValueError) as e:
            raise DrafterResponseError(
                f"JSON 解析失败: {e}",
                raw_content=content,
                reason=f"json_decode_error={type(e).__name__}",
            ) from e

    # 严判结构(必须是 dict)
    if not isinstance(data, dict):
        raise DrafterResponseError(
            "JSON 顶层必须是 object",
            raw_content=content,
            reason=f"top_level_type={type(data).__name__}",
        )

    # 严判 subject 字段
    subject_raw = data.get("subject")
    if type(subject_raw) is not str:
        raise DrafterResponseError(
            "subject 字段必须是 str",
            raw_content=content,
            reason=f"subject_type={type(subject_raw).__name__}",
        )
    try:
        _validate_draft_subject(subject_raw)
    except ValueError as e:
        raise DrafterResponseError(
            f"subject 业务验收未通过(契约 1): {e}",
            raw_content=content,
            reason=f"subject_invalid_len={len(subject_raw)}",
        ) from e

    # 严判 body 字段
    body_raw = data.get("body")
    if type(body_raw) is not str:
        raise DrafterResponseError(
            "body 字段必须是 str",
            raw_content=content,
            reason=f"body_type={type(body_raw).__name__}",
        )
    try:
        _validate_draft_body(body_raw)
    except ValueError as e:
        raise DrafterResponseError(
            f"body 业务验收未通过(契约 1): {e}",
            raw_content=content,
            reason=f"body_invalid_len={len(body_raw)}",
        ) from e

    # 严判 tone 字段(契约 3 锁定 3 类)
    tone_raw = data.get("tone")
    if type(tone_raw) is not str:
        raise DrafterResponseError(
            "tone 字段必须是 str",
            raw_content=content,
            reason=f"tone_type={type(tone_raw).__name__}",
        )
    if tone_raw not in _DRAFT_TONE_CHOICES:
        raise DrafterResponseError(
            f"tone 值不在 3 类枚举中(契约 3): {tone_raw!r}",
            raw_content=content,
            reason=f"invalid_tone={tone_raw}",
        )
    tone = DraftTone(tone_raw)  # 此时一定成功

    # P1-3 强制(6/9): 请求 tone 必须与返回 tone 一致
    if expected_tone is not None and tone != expected_tone:
        raise DrafterResponseError(
            f"tone 与请求不一致(契约 3 强制): 请求 {expected_tone.value}, 返回 {tone.value}",
            raw_content=content,
            reason=f"tone_mismatch=request_{expected_tone.value}_got_{tone.value}",
        )

    return subject_raw, body_raw, tone


# ===== 契约 4 范围限定验证(供测试用)=====

# 契约 4: D4.7 范围限定 — 不写 drafts 表 / 不创建 Mail.app 草稿 / 不接 iCloud
# Drafter 模块应仅依赖 ai/router + ai/providers + loguru, 不 import:
#   - my_ai_employee.core.models (DB models)
#   - my_ai_employee.events (事件层)
#   - my_ai_employee.policy (策略层)
#   - sqlalchemy / sqlcipher (DB driver)
#   - macOS Mail / CalDAV 相关
# 测试用 ast 静态验证(_test_drafter_scope.py 在 tests/ai/ 下)


# ===== 模块导出 =====

__all__ = [
    "DraftTone",
    "DrafterError",
    "DrafterResponseError",
    "DraftResult",
    "EmailDrafter",
    # helper(契约 1 公共 API, D4.7.3 严判下沉复用)
    "validate_draft_subject",
    "validate_draft_body",
    "validate_draft_tone",
    "parse_draft_response",
    "has_markdown_fence",
]


# 公共 API 包装层(契约 1: 严判下沉到公共 API, 防止 Adapter 重构后绕过)
# D4.6 v1.0.2-second P1 教训: helper 必须自防御
def validate_draft_subject(subject: Any) -> None:
    """公共 API: 严判草稿 subject(契约 1 严判下沉, D4.6 v1.0.2-second 范本复用)."""
    _validate_draft_subject(subject)


def validate_draft_body(body: Any) -> None:
    """公共 API: 严判草稿 body(契约 1 严判下沉)."""
    _validate_draft_body(body)


def validate_draft_tone(tone: Any) -> None:
    """公共 API: 严判草稿 tone(契约 3 严判下沉)."""
    _validate_draft_tone(tone)


def parse_draft_response(
    content: Any,
    *,
    expected_tone: DraftTone | None = None,
) -> tuple[str, str, DraftTone]:
    """公共 API: 严判解析 LLM 草稿响应(契约 2 + 契约 3 + P1-3).

    Args:
        content: LLM 原始响应
        expected_tone: 请求的语气(6/9 P1-3 新增), 强制 LLM 返回一致 tone
    """
    return _parse_draft_response(content, expected_tone=expected_tone)


def has_markdown_fence(raw: Any) -> bool:
    """公共 API: 检测外层 markdown fence 包裹(契约 2, 6/9 P1-2 语义收紧).

    仅检测"外层包裹"(stripped 内容以 ``` 开头 AND 以 ``` 结尾),
    不再扫描内部任意位置的 fence(避免误杀 body 字段内的 code fence)。
    """
    return _has_outer_markdown_fence(raw)
