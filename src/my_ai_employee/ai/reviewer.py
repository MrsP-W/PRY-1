"""D4.7.4 — 邮件草稿审阅器(LLM 规则审阅).

设计要点:

  - 复用 D4.1.1 LLM Router:`router.route(TaskType.REVIEW, messages)` 自动走
    DeepSeek → Qwen → M3 fallback 链(`fallback.FALLBACK_CHAINS[TaskType.REVIEW]` 已配)
  - 严判 LLM 响应:必须严格 JSON `{"subject": str, "body": str, "tone": <枚举>}`
    - 字段缺 / 类型错 / tone 不在 3 类 → 抛 ReviewerResponseError
    - 编程错误(type/ValueError) 透传(D3.3.3 教训:不 catch-all 兜底)
  - 批量:`review_batch` 顺序串行(避免触发熔断/雪崩,D4.7.1+ 改并发)
  - 不写 DB / 不接 events / 不接 policy(本步只做"草稿生成"原子能力,契约 4)
  - 不创建 Mail.app 草稿 / 不接 iCloud CalDAV(契约 4)

D5+ 业务层接入用 `EmailReviewerAdapter`(`policy/integration.py` 新增),
把草稿结果(subject + body + tone)封装成 TaskPacket 喂 PolicyEngine,落 events + lane,
沿用 D4.5 `SyncPolicyAdapter` 4 依赖范本 + D4.6 `EmailClassifierAdapter` 双入口架构。

参考 D3.3.3 教训("异常范围要窄化"):
  - ReviewerResponseError 是业务异常(LLM 输出脏),由调用方决定重试
  - 编程错误(参数 type 错) → ValueError 透传,不在本模块包装

D4.7 4 项契约(2026-06-09 用户审批锁定,D4.7.1 起始固定):

  1. **草稿无 confidence 字段** → 业务验收用**明确长度/必填/tone 枚举**判定
     (`validate_draft` 公共 API: subject 非空 AND body 10-8000 AND tone ∈ 3 类)
  2. **拒 markdown-wrapped JSON**(不剥离 ```json ... ``` fence)→ LLM 必须
     返回**裸 JSON**(`json.loads(stripped)` 唯一解析路径, 无 prose / 无外层 fence);
     违者拒收触发 retry;body 字段内容允许 markdown(含 code fence)
  3. **tone 枚举锁定**:FORMAL / FRIENDLY / CONCISE 三选一,后续扩枚举需 B 类审批
  4. **范围限定**:D4.7 只生成草稿文本 + emit 业务事件 + 推进 Lane;不写
     `drafts` 数据库表、不创建 Mail.app 草稿、不接 iCloud CalDAV

D4.7.1 实施细节:
  - 严判入口:`type() is str` 严判,`isinstance(x, bool)` 拒 bool 子类
  - 裸 JSON 契约(6/9 v1.0.2 P1):`json.loads(stripped)` 唯一解析路径,
    删除 v1.0.1 的"平衡括号兜底"(该兜底接受 prose 包装, 绕过契约)
  - 业务验收下沉(6/9 v1.0.2 P2-2):契约 1 严判移到 _parse_draft_response,
    删除 draft() 内的 validation_error 不可达分支
  - ReviewResult 自校验(6/9 v1.0.2 P2-3):__post_init__ 严判 5 字段
  - 4 项契约测试:契约 1 (业务验收) / 契约 2 (拒外层 fence + 拒 prose) /
    契约 3 (tone 锁定 + 请求 tone 强制) / 契约 4 (范围限定,ast 静态验证)

D4.7.2 实施细节(6/9):
  - 新增 `ai/prompts/draft.py`:5+1 类 SYSTEM prompt(URGENT/TODO/FYI/SPAM/
    PERSONAL/DEFAULT) + `build_system_prompt` 分发 + `build_user_message`
  - 替换 v1.0 内置的 placeholder system prompt,drafter 调
    `prompts.draft.build_system_prompt(email_category)` 取 5+1 类 prompt
  - email_category=None 走 DEFAULT(中性回退),drafter 可独立运行不依赖 D4.6
  - prompts 层接受字符串化的 email_category/tone(解耦 drafter 枚举依赖)

D4.7.2 v1.0.2 实施细节(6/9 第三次复检收口):
  - P1-1 SPAM 业务硬阻断:drafter.review() 收到 SPAM 默认抛 ReviewerBlockedError;
    加 `allow_spam_reply: bool=False` 显式参数,业务层硬阻断不依赖 prompt 文案;
    新增 `review_blocked_category()` 独立入口(不调 LLM, 直接返回 ReviewBlockedResult)
  - P1-2 纯空白草稿拦截:`_validate_draft_subject/body` 改用 `value.strip()`
    严判语义非空(拒 "   " 主题 / 十个空格 body);ReviewResult.__post_init__
    严判 model_full_id 非空(契约 1 自校验)
  - P2-1 抗注入三字段包裹:`prompts/draft.build_user_message` 主题/发件人/正文
    全部用 `json.dumps()` 序列化为 UNTRUSTED_DATA block(取代 BEGIN/END_EMAIL_BODY),
    防主题/发件人注入 + 防正文自含 END 标签绕过
  - P2-2 公共 builder 自防御:`build_user_message` 顶层 API 加 MAX_BODY_CHARS=2000
    截断(与 drafter.MAX_BODY_CHARS 同步),即便用户绕过 drafter 也不会撑爆 prompt
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger

from .capability import TaskType
from .classifier import EmailCategory
from .prompts.review import build_system_prompt as _build_review_system_prompt
from .prompts.review import build_user_message as _build_review_user_message
from .providers import LLMError
from .router import LLMRouter, get_router

# ===== tone 枚举(契约 3 锁定 3 类)=====


class ReviewTone(StrEnum):
    """草稿语气 3 类枚举(StrEnum, 与 LLM 输出严格 1:1).

    D4.7.1 起始固定,后续扩枚举需 B 类审批。
    顺序固定(FORMAL → FRIENDLY → CONCISE),业务层做"按语气分组"时可直接用
    `list(ReviewTone)` 排序。
    """

    FORMAL = "FORMAL"  # 正式: 商务 / 官方 / 客户沟通
    FRIENDLY = "FRIENDLY"  # 友好: 同事 / 熟人 / 协作
    CONCISE = "CONCISE"  # 简洁: 通知 / 确认 / 单点沟通


# D4.7.4 4 类业务阻断白名单(week1-mvp.md:773 契约 2 锁定)
_REVIEW_BLOCK_REASON_CHOICES: frozenset[str] = frozenset(
    {"sensitive_word_hit", "template_violation", "tone_mismatch", "factual_conflict"}
)

# D4.7.4 review_summary 字符上限(契约 3 锁定 1-2000)
_REVIEW_SUMMARY_MAX_CHARS = 2000

# 3 类枚举值集合(O(1) 校验)
_DRAFT_TONE_CHOICES: frozenset[str] = frozenset(t.value for t in ReviewTone)

# 5 类邮件标签值(P1-1: 严判 email_category 字符串)
# Drafter 是 D4.6 分类结果的下游消费者, 严判字符串 ∈ 5 类
_EMAIL_CATEGORY_VALUES: frozenset[str] = frozenset(c.value for c in EmailCategory)


# 6/9 v1.0.6 P2-2 新增: SPAM 授权意图枚举(消除"确认收悉"与 SYSTEM_PROMPT_SPAM 矛盾)
# - v1.0.5 漏洞: 授权行措辞"礼貌退订/确认收悉" 与 SYSTEM prompt "避免确认邮箱活跃" 矛盾
#   模型收到互相冲突的指令时, 可能错误地走"确认收悉"路径, 让发件方知道你打开了邮件
# - 真修: 严格枚举白名单, **排除"ACKNOWLEDGE/确认收悉"**(与 SYSTEM prompt 业务硬规则矛盾)
# - 仅允许明确的"退订"或"拒收"意图(都是单向拒绝语义, 不暴露"用户已读"信号)
# - 未来扩枚举(如 BLOCK_SENDER 等) 需 B 类审批
class DraftSpamReplyIntent(StrEnum):
    """SPAM 授权回复意图(6/9 v1.0.6 P2-2 新增, 排除 ACKNOWLEDGE 语义冲突).

    UNSUBSCRIBE: 礼貌退订(请将我移除列表/请勿再发送同类邮件)
    REJECT     : 明确拒收(我不感兴趣, 拒绝任何后续沟通, 升级法律风险)

    与 ReviewTone 区别:
      - ReviewTone 是"语气"(FORMAL/FRIENDLY/CONCISE)
      - DraftSpamReplyIntent 是"业务意图"(UNSUBSCRIBE/REJECT, 互斥)

    未来扩枚举需 B 类审批(D4.7.2 契约外增量)。
    """

    UNSUBSCRIBE = "UNSUBSCRIBE"  # 礼貌退订
    REJECT = "REJECT"  # 明确拒收


_DRAFT_SPAM_REPLY_INTENT_CHOICES: frozenset[str] = frozenset(t.value for t in DraftSpamReplyIntent)


# ===== 业务异常(D3.3.3 教训:窄化异常范围)=====

# 6/9 v1.0.5 P2-2 修复: 阻断原因 reason 锁定白名单
# 当前阻断类别仅 SPAM, reason 限定为 "spam_business_blocked"
# 未来扩阻断类别(OTHER_BLOCKED / PHISHING_BLOCKED 等)需 B 类审批 + 扩白名单
_BLOCKED_REASON_VALUES: frozenset[str] = frozenset({"spam_business_blocked"})


def _serialize_audit_field(value: str, *, max_chars: int = 100) -> str:
    """Return a complete JSON string literal within the character budget."""
    if type(value) is not str:
        raise ValueError(f"audit field 必须是 str, 实际 {type(value).__name__}")
    if type(max_chars) is not int or isinstance(max_chars, bool) or max_chars < 2:
        raise ValueError(f"max_chars 必须是 >= 2 的 int, 实际 {max_chars!r}")

    encoded = json.dumps(value, ensure_ascii=True)
    if len(encoded) <= max_chars:
        return encoded

    low = 0
    high = len(value)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = json.dumps(value[:middle], ensure_ascii=True)
        if len(candidate) <= max_chars:
            low = middle
        else:
            high = middle - 1
    return json.dumps(value[:low], ensure_ascii=True)


class ReviewerError(Exception):
    """草稿生成器业务异常基类."""


class ReviewerResponseError(ReviewerError):
    """LLM 响应解析失败(非严格 JSON / tone 不在 3 类 / 字段类型错 / markdown-wrapped).

    Attributes:
        raw_content: LLM 原始输出(便于排查,截断到 500 字符)
        reason: 解析失败原因(机器可读,如 'invalid_tone=APOLOGETIC' / 'markdown_fenced')
    """

    def __init__(self, message: str, raw_content: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.raw_content = raw_content[:500]
        self.reason = reason


class ReviewerBlockedError(ReviewerError):
    """SPAM 业务硬阻断(6/9 v1.0.2 P1-1 修复).

    业务异常: 邮件被 D4.6 分类为 SPAM 并进入 BLOCKED 流程, drafter 业务层
    默认拒收(不调 LLM, 不消耗配额),与 D4.6 分类结果形成双保险。

    Attributes:
        email_category: 触发阻断的邮件分类(SPAM, 未来可扩 OTHER_BLOCKED)
        allow_spam_reply: 触发时调用方是否传 True(便于审计: 调用方误用记录)
        reason: 阻断原因(机器可读, 如 'spam_business_blocked')

    Raises:
        父类 ReviewerError(便于上层 catch 业务异常统一处理)
    """

    def __init__(
        self,
        message: str,
        *,
        email_category: str = "SPAM",
        allow_spam_reply: bool = False,
        reason: str = "spam_business_blocked",
    ) -> None:
        super().__init__(message)
        self.email_category = email_category
        self.allow_spam_reply = allow_spam_reply
        self.reason = reason


# ===== 草稿结果数据类 =====


@dataclass(frozen=True)
class ReviewResult:
    """单邮件草稿审阅结果(D4.7.4 主产物).

    字段契约对齐(week1-mvp.md:773 真理源, 2026-06-10):
      - review_passed: bool, True=通过, False=阻断
      - flagged_issues: list[str], 阻断时必非空
      - review_summary: str, 1-2000 字符
      - block_reason: str|None, 4 类白名单(sensitive_word_hit / template_violation / tone_mismatch / factual_conflict)
      - blocked_word: str|None, 仅 sensitive_word_hit 时非空(命中词)
      - model_full_id: 实际调用的 provider/model
      - latency_ms: 单次审阅耗时
      - raw_content: LLM 原始响应(截断到 500 字符)

    双向强一致(7 项核心契约):
      - review_passed=True  → block_reason 必 None, blocked_word 必 None
      - review_passed=False → block_reason 必 ∈ 4 类白名单, flagged_issues 必非空
      - block_reason=sensitive_word_hit → blocked_word 必非空
      - block_reason=tone_mismatch / template_violation / factual_conflict → blocked_word 必 None
    """

    review_passed: bool
    flagged_issues: list[str]
    review_summary: str
    block_reason: str | None
    blocked_word: str | None
    model_full_id: str
    latency_ms: int
    raw_content: str

    def __post_init__(self) -> None:
        """工厂层 + __post_init__ 双层防御(7 项核心契约).

        D4.7.4 v1.0.1 严判:
          - 字段类型严判(拒 bool 子类陷阱)
          - 双向强一致(review_passed ↔ block_reason)
          - 跨字段校验(blocked_word + sensitive_word_hit)
          - length 契约(review_summary 1-2000, raw_content 截断到 500)
        """
        # type 严判(7 项核心契约)
        if type(self.review_passed) is not bool:
            raise ValueError(f"review_passed 必须是 bool, 实际 {type(self.review_passed).__name__}")
        if type(self.flagged_issues) is not list:
            raise ValueError(
                f"flagged_issues 必须是 list[str], 实际 {type(self.flagged_issues).__name__}"
            )
        for i, issue in enumerate(self.flagged_issues):
            if type(issue) is not str:
                raise ValueError(f"flagged_issues[{i}] 必须是 str, 实际 {type(issue).__name__}")
        if type(self.review_summary) is not str:
            raise ValueError(
                f"review_summary 必须是 str, 实际 {type(self.review_summary).__name__}"
            )
        if not self.review_summary.strip():
            raise ValueError("review_summary 语义为空(仅空白)")
        if len(self.review_summary) > _REVIEW_SUMMARY_MAX_CHARS:
            raise ValueError(
                f"review_summary 超长(> {_REVIEW_SUMMARY_MAX_CHARS} 字符): "
                f"实际 {len(self.review_summary)} 字符"
            )
        if self.block_reason is not None and type(self.block_reason) is not str:
            raise ValueError(
                f"block_reason 必须是 str 或 None, 实际 {type(self.block_reason).__name__}"
            )
        if self.block_reason is not None and self.block_reason not in _REVIEW_BLOCK_REASON_CHOICES:
            raise ValueError(f"block_reason 必须在 4 类白名单中, 实际 {self.block_reason!r}")
        if self.blocked_word is not None and type(self.blocked_word) is not str:
            raise ValueError(
                f"blocked_word 必须是 str 或 None, 实际 {type(self.blocked_word).__name__}"
            )
        if type(self.model_full_id) is not str or not self.model_full_id.strip():
            raise ValueError(f"model_full_id 必填非空 str, 实际 {self.model_full_id!r}")
        if type(self.latency_ms) is not int or isinstance(self.latency_ms, bool):
            raise ValueError(
                f"latency_ms 必须是 int(拒 bool 子类), 实际 {type(self.latency_ms).__name__}"
            )
        if self.latency_ms < 0:
            raise ValueError(f"latency_ms 必须 >= 0, 实际 {self.latency_ms}")
        if type(self.raw_content) is not str:
            raise ValueError(f"raw_content 必须是 str, 实际 {type(self.raw_content).__name__}")

        # 双向强一致(7 项核心契约)
        if self.review_passed and self.block_reason is not None:
            raise ValueError(
                f"review_passed=True 时 block_reason 必 None, 实际 {self.block_reason!r}"
            )
        if not self.review_passed and self.block_reason is None:
            raise ValueError("review_passed=False 时 block_reason 必非空")
        if not self.review_passed and not self.flagged_issues:
            raise ValueError("review_passed=False 时 flagged_issues 必非空")

        # 跨字段校验:blocked_word + sensitive_word_hit
        if self.block_reason == "sensitive_word_hit" and (
            self.blocked_word is None or not self.blocked_word.strip()
        ):
            raise ValueError("block_reason=sensitive_word_hit 时 blocked_word 必非空")
        if (
            self.block_reason in ("tone_mismatch", "template_violation", "factual_conflict")
            and self.blocked_word is not None
        ):
            raise ValueError(f"block_reason={self.block_reason} 时 blocked_word 必 None")

        # raw_content 截断到 500 字符(防放大事件载荷, D4.7.3 v1.0.8 范本)
        if len(self.raw_content) > 500:
            object.__setattr__(self, "raw_content", self.raw_content[:500])

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(便于 JSON 化)."""
        return {
            "review_passed": self.review_passed,
            "flagged_issues": list(self.flagged_issues),
            "review_summary": self.review_summary,
            "block_reason": self.block_reason,
            "blocked_word": self.blocked_word,
            "model_full_id": self.model_full_id,
            "latency_ms": self.latency_ms,
            "raw_content": self.raw_content,
        }


class EmailReviewer:
    """邮件草稿生成器(D4.7.4 主类).

    用法:

        from my_ai_employee.ai import EmailReviewer, ReviewTone
        from my_ai_employee.ai.router import get_router

        router = get_router()
        drafter = EmailReviewer(router=router)
        result = drafter.review(
            subject="[紧急] 客户投诉",
            sender="client@example.com",
            body_excerpt="订单 #1234 严重延迟...",
            email_category=EmailCategory.URGENT,
            tone=ReviewTone.FORMAL,
        )
        assert result.tone == ReviewTone.FORMAL
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
        """初始化草稿审阅器(D4.7.4).

        Args:
            router: LLM 路由器(默认 get_router() 单例; v1.0.1 修复: 用 is None
                   范式不吞 falsey 替身, 保留测试用 mock router)
            max_tokens: 输出上限(审阅需要短响应,默认 1024 足够; v1.0.1 修复:
                       type() is int + >0 严判, 拒 -1/True/"512" 等无效值)
        """
        # v1.0.1 P2-2 修复: is None 范式, 保留 falsey 替身(D4.7.3 v1.0.3 P2-2 范本)
        if router is None:
            self._router = get_router()
        else:
            self._router = router
        # v1.0.1 P2-2 修复: max_tokens 类型严判
        # 拒 bool 子类陷阱(isinstance(True, int)==True)+ 拒 -1/"512"/None 等
        if type(max_tokens) is not int or isinstance(max_tokens, bool):
            raise ValueError(
                f"max_tokens 必须是 int(拒 bool 子类), 实际 {type(max_tokens).__name__}"
            )
        if max_tokens <= 0:
            raise ValueError(f"max_tokens 必须 > 0, 实际 {max_tokens}")
        self._max_tokens = max_tokens
        # 运行时统计(可观测性, 类似 RouterStats)
        # 6/9 v1.0.2 P2-2 修复: 删除 validation_error 字段
        # 解析器(_parse_draft_response)已对 subject / body / tone 严判
        # 业务验收不可达, 统计无意义
        self._stats: dict[str, int] = {
            "total": 0,
            "success": 0,
            "response_error": 0,
            "llm_error": 0,
            "blocked": 0,  # 6/9 v1.0.2 P1-1 新增: SPAM 业务硬阻断计数
        }

    def stats(self) -> dict[str, int]:
        """返回草稿生成器统计(便于 mmx policy status 等可观测性子命令)."""
        return dict(self._stats)

    def validate_draft(
        self,
        *,
        subject: str,
        body: str,
        tone: ReviewTone | str,
    ) -> bool:
        """业务验收(契约 1 公共 API).

        验收规则:
          - subject: type is str AND 1 <= len <= 200(非空, 不超长)
          - body: type is str AND 10 <= len <= 8000(明确长度边界)
          - tone: ReviewTone 枚举值 OR str ∈ {FORMAL, FRIENDLY, CONCISE}

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
            if not (1 <= len(subject) <= 200):
                return False
            if not (10 <= len(body) <= 8000):
                return False
        except (TypeError, ValueError):
            return False
        return True

    def review(
        self,
        *,
        draft_subject: str,
        draft_body: str,
        email_category: EmailCategory | str | None = None,
        orig_subject: str = "",
        orig_sender: str = "",
        orig_body_excerpt: str = "",
    ) -> ReviewResult:
        """单邮件草稿审阅(D4.7.4 主入口).

        D4.7.4 4 项契约 + 7 项核心契约 + 25 教训沉淀应用:
          - 5+1 SYSTEM prompt 分发(URGENT/TODO/FYI/SPAM/PERSONAL/DEFAULT)
          - 4 字段裸 JSON 契约(review_passed/flagged_issues/review_summary/block_reason)
          - 双向强一致(review_passed ↔ block_reason)
          - 跨字段校验(blocked_word + sensitive_word_hit)
          - 业务硬阻断(sensitive_word_hit → ReviewerBlockedResult)
          - 技术失败(LLM 全链失败 / 响应解析失败)→ ReviewerResponseError / LLMError 透传

        Args:
            draft_subject: 待审阅草稿主题(1-200 字符)
            draft_body: 待审阅草稿正文(10-8000 字符, > 2000 自动截断到 2000)
            email_category: 5 类邮件标签(D4.6 分类结果)
            orig_subject: 原邮件主题(可能为空)
            orig_sender: 原邮件发件人
            orig_body_excerpt: 原邮件正文前 N 字符

        Returns:
            ReviewResult(含 review_passed + flagged_issues + review_summary + block_reason + blocked_word + 调用模型 + latency_ms)

        Raises:
            ValueError: 参数 type 错 / 长度超 8000(编程错误, 透传)
            ReviewerResponseError: LLM 响应解析失败(非严格 JSON / 字段缺失 / 双向不一致)
            LLMError: 全链失败(router 抛, 由调用方决定 fallback)
        """
        # 入口严判 type(D4.4 P1 + D4.5 P0 教训应用)
        if type(draft_subject) is not str:
            raise ValueError(f"draft_subject 必须是 str, 实际 {type(draft_subject).__name__}")
        if type(draft_body) is not str:
            raise ValueError(f"draft_body 必须是 str, 实际 {type(draft_body).__name__}")
        if type(orig_subject) is not str:
            raise ValueError(f"orig_subject 必须是 str, 实际 {type(orig_subject).__name__}")
        if type(orig_sender) is not str:
            raise ValueError(f"orig_sender 必须是 str, 实际 {type(orig_sender).__name__}")
        if type(orig_body_excerpt) is not str:
            raise ValueError(
                f"orig_body_excerpt 必须是 str, 实际 {type(orig_body_excerpt).__name__}"
            )

        # 输入长度严判(契约: 1-200 subject, 10-8000 body)
        if not (1 <= len(draft_subject) <= 200):
            raise ValueError(f"draft_subject 长度必须 1-200 字符, 实际 {len(draft_subject)}")
        if not (10 <= len(draft_body) <= 8000):
            raise ValueError(f"draft_body 长度必须 10-8000 字符, 实际 {len(draft_body)}")

        # email_category 严判(接受 EmailCategory 枚举 / str / None)
        email_category_str: str | None
        if email_category is None:
            email_category_str = None
        elif isinstance(email_category, EmailCategory):
            email_category_str = email_category.value
        elif type(email_category) is str:
            if email_category not in _EMAIL_CATEGORY_VALUES:
                raise ValueError(
                    f"email_category 字符串必须 ∈ {sorted(_EMAIL_CATEGORY_VALUES)}, "
                    f"实际 {email_category!r}"
                )
            email_category_str = email_category
        else:
            raise ValueError(
                f"email_category 必须是 EmailCategory 枚举 / str / None, "
                f"实际 {type(email_category).__name__}"
            )

        self._stats["total"] += 1

        # 构造 messages(委托 prompts/review.py)
        system_prompt = _build_review_system_prompt(email_category_str)
        messages = [
            {"role": "system", "content": system_prompt},
            *_build_review_user_message(
                draft_subject=draft_subject,
                draft_body=draft_body,
                email_category=email_category_str,
                orig_subject=orig_subject,
                orig_sender=orig_sender,
                orig_body_excerpt=orig_body_excerpt,
            ),
        ]

        # 调 router(走 fallback 链, 熔断隔离)
        try:
            response = self._router.route(
                task_type=TaskType.REVIEW,
                messages=messages,
                temperature=0.3,  # 审阅任务: 低温保稳定, 不需要创意
                max_tokens=self._max_tokens,
            )
        except LLMError as e:
            self._stats["llm_error"] += 1
            logger.warning(f"[reviewer] LLM 全链失败 | draft_subject={draft_subject!r} | err={e!r}")
            raise

        # 严判响应(D4.7.4 4 字段 JSON 契约)
        try:
            (
                review_passed,
                flagged_issues,
                review_summary,
                block_reason,
                blocked_word,
            ) = _parse_review_response(response.content)
        except ReviewerResponseError as e:
            self._stats["response_error"] += 1
            logger.warning(
                f"[reviewer] 响应解析失败 | draft_subject={draft_subject!r} | "
                f"reason={e.reason} | raw={e.raw_content!r}"
            )
            raise

        # 业务阻断:sensitive_word_hit → 阻断
        # 阻断不抛异常,而是返回 ReviewResult(review_passed=False, block_reason=...)
        # 与 D4.7.3 EmailDrafter 不同: drafter 是 SPAM 业务硬阻断抛 ReviewerBlockedError,
        # reviewer 是业务软阻断(LLM 判定)返回 review_passed=False, 由调用方决定
        result = ReviewResult(
            review_passed=review_passed,
            flagged_issues=flagged_issues,
            review_summary=review_summary,
            block_reason=block_reason,
            blocked_word=blocked_word,
            model_full_id=response.model_full_id,
            latency_ms=response.latency_ms,
            raw_content=response.content,
        )
        self._stats["success"] += 1
        if not review_passed:
            self._stats["blocked"] = self._stats.get("blocked", 0) + 1
        return result

    def review_batch(
        self,
        emails: list[dict],
    ) -> list[ReviewResult | ReviewerResponseError | LLMError | ValueError | KeyError]:
        """批量草稿审阅(D4.7.4,顺序串行,避免触发熔断).

        Args:
            emails: list[dict], 每条 dict 必须包含 draft_subject/draft_body 2 key
                   (类型不匹配 / 缺字段 → 异常入 results, 不静默吞掉, 不外抛)
                   可选 key: email_category / orig_subject / orig_sender / orig_body_excerpt

        Returns:
            list[ReviewResult | 异常], 与 emails 1:1 对齐
              - 成功: ReviewResult(review_passed=True/False 都可能)
              - 响应解析失败: ReviewerResponseError
              - LLM 全链失败: LLMError
              - 编程错误: ValueError / KeyError
        """
        results: list[ReviewResult | ReviewerResponseError | LLMError | ValueError | KeyError] = []
        for i, email in enumerate(emails):
            if not isinstance(email, dict):
                results.append(ValueError(f"emails[{i}] 必须是 dict, 实际 {type(email).__name__}"))
                continue
            missing_keys = [k for k in ("draft_subject", "draft_body") if k not in email]
            if missing_keys:
                results.append(KeyError(f"emails[{i}] 缺字段 {missing_keys}"))
                continue
            try:
                result = self.review(
                    draft_subject=email["draft_subject"],
                    draft_body=email["draft_body"],
                    email_category=email.get("email_category"),
                    orig_subject=email.get("orig_subject", ""),
                    orig_sender=email.get("orig_sender", ""),
                    orig_body_excerpt=email.get("orig_body_excerpt", ""),
                )
                results.append(result)
            except (ReviewerResponseError, LLMError, ValueError) as e:
                results.append(e)
        return results


# ===== 契约 4 范围限定验证(D4.7.4 移除: 4 字段契约下, 业务阻断统一由 review() 返回 review_passed=False 表达)


# ===== _parse_review_response 解析器(D4.7.4 4 字段 JSON 契约)=====


def _parse_review_response(
    content: Any,
) -> tuple[bool, list[str], str, str | None, str | None]:
    """严判解析 LLM 审阅响应, 返回 5 元组.

    Args:
        content: LLM 原始响应

    Returns:
        (review_passed, flagged_issues, review_summary, block_reason, blocked_word)
    """
    if type(content) is not str:
        raise ReviewerResponseError(
            "LLM content 必须是 str",
            raw_content=str(content),
            reason=f"type={type(content).__name__}",
        )
    stripped = content.strip()
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError) as parse_err:
        raise ReviewerResponseError(
            f"LLM 响应不是合法裸 JSON(契约 2): {parse_err}",
            raw_content=content,
            reason=f"json_decode_error={type(parse_err).__name__}",
        ) from parse_err
    if not isinstance(data, dict):
        raise ReviewerResponseError(
            "JSON 顶层必须是 object",
            raw_content=content,
            reason=f"top_level_type={type(data).__name__}",
        )
    review_passed = data.get("review_passed")
    if type(review_passed) is not bool:
        raise ReviewerResponseError(
            "review_passed 字段必须是 bool",
            raw_content=content,
            reason=f"review_passed_type={type(review_passed).__name__}",
        )
    review_summary = data.get("review_summary")
    if type(review_summary) is not str or not review_summary.strip():
        raise ReviewerResponseError(
            "review_summary 必填非空 str",
            raw_content=content,
            reason="review_summary_invalid",
        )
    if len(review_summary) > _REVIEW_SUMMARY_MAX_CHARS:
        raise ReviewerResponseError(
            f"review_summary 超长(> {_REVIEW_SUMMARY_MAX_CHARS})",
            raw_content=content,
            reason=f"review_summary_too_long={len(review_summary)}",
        )
    block_reason = data.get("block_reason")
    if block_reason is not None and type(block_reason) is not str:
        raise ReviewerResponseError(
            "block_reason 必须是 str 或 None",
            raw_content=content,
            reason=f"block_reason_type={type(block_reason).__name__}",
        )
    if block_reason is not None and block_reason not in _REVIEW_BLOCK_REASON_CHOICES:
        raise ReviewerResponseError(
            f"block_reason 不在 4 类白名单中: {block_reason!r}",
            raw_content=content,
            reason=f"invalid_block_reason={block_reason}",
        )
    flagged_issues = data.get("flagged_issues", [])
    if not isinstance(flagged_issues, list):
        raise ReviewerResponseError(
            "flagged_issues 必须是 list[str]",
            raw_content=content,
            reason=f"flagged_issues_type={type(flagged_issues).__name__}",
        )
    for i, issue in enumerate(flagged_issues):
        if type(issue) is not str:
            raise ReviewerResponseError(
                f"flagged_issues[{i}] 必须是 str, 实际 {type(issue).__name__}",
                raw_content=content,
                reason=f"flagged_issues[{i}]_type={type(issue).__name__}",
            )
    if not review_passed and not flagged_issues:
        raise ReviewerResponseError(
            "review_passed=False 时 flagged_issues 必非空",
            raw_content=content,
            reason="flagged_issues_empty_when_blocked",
        )
    blocked_word = data.get("blocked_word")
    if blocked_word is not None and type(blocked_word) is not str:
        raise ReviewerResponseError(
            "blocked_word 必须是 str 或 None",
            raw_content=content,
            reason=f"blocked_word_type={type(blocked_word).__name__}",
        )
    if block_reason == "sensitive_word_hit" and (blocked_word is None or not blocked_word.strip()):
        raise ReviewerResponseError(
            "block_reason=sensitive_word_hit 时 blocked_word 必非空",
            raw_content=content,
            reason="blocked_word_empty_when_sensitive_word_hit",
        )
    if (
        block_reason in ("tone_mismatch", "template_violation", "factual_conflict")
        and blocked_word is not None
    ):
        raise ReviewerResponseError(
            f"block_reason={block_reason} 时 blocked_word 必 None(仅 sensitive_word_hit 才需要)",
            raw_content=content,
            reason=f"blocked_word_unexpected_for_{block_reason}",
        )
    # 双向强一致
    if review_passed and block_reason is not None:
        raise ReviewerResponseError(
            "review_passed=True 时 block_reason 必 None",
            raw_content=content,
            reason=f"block_reason_unexpected_when_passed={block_reason}",
        )
    if not review_passed and block_reason is None:
        raise ReviewerResponseError(
            "review_passed=False 时 block_reason 必非空",
            raw_content=content,
            reason="block_reason_missing_when_blocked",
        )
    return review_passed, flagged_issues, review_summary, block_reason, blocked_word


__all__ = [
    "ReviewTone",
    "ReviewerError",
    "ReviewerResponseError",
    "ReviewResult",
    "EmailReviewer",
    "parse_review_response",
]


def parse_review_response(
    content: Any,
) -> tuple[bool, list[str], str, str | None, str | None]:
    """公共 API 包装层(契约 1 严判下沉复用).

    D4.7.4 适配审阅 4 字段 JSON 契约, 返回 5 元组
    (review_passed, flagged_issues, review_summary, block_reason, blocked_word).
    """
    return _parse_review_response(content)
