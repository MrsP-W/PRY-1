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
  - DraftResult 自校验(6/9 v1.0.2 P2-3):__post_init__ 严判 5 字段
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
  - P1-1 SPAM 业务硬阻断:drafter.draft() 收到 SPAM 默认抛 SpamBlockedError;
    加 `allow_spam_reply: bool=False` 显式参数,业务层硬阻断不依赖 prompt 文案;
    新增 `draft_blocked_category()` 独立入口(不调 LLM, 直接返回 DraftBlockedResult)
  - P1-2 纯空白草稿拦截:`_validate_draft_subject/body` 改用 `value.strip()`
    严判语义非空(拒 "   " 主题 / 十个空格 body);DraftResult.__post_init__
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
from .prompts.draft import build_system_prompt as _build_draft_system_prompt
from .prompts.draft import build_user_message as _build_draft_user_message
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

    与 DraftTone 区别:
      - DraftTone 是"语气"(FORMAL/FRIENDLY/CONCISE)
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


class SpamBlockedError(DrafterError):
    """SPAM 业务硬阻断(6/9 v1.0.2 P1-1 修复).

    业务异常: 邮件被 D4.6 分类为 SPAM 并进入 BLOCKED 流程, drafter 业务层
    默认拒收(不调 LLM, 不消耗配额),与 D4.6 分类结果形成双保险。

    Attributes:
        email_category: 触发阻断的邮件分类(SPAM, 未来可扩 OTHER_BLOCKED)
        allow_spam_reply: 触发时调用方是否传 True(便于审计: 调用方误用记录)
        reason: 阻断原因(机器可读, 如 'spam_business_blocked')

    Raises:
        父类 DrafterError(便于上层 catch 业务异常统一处理)
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
class DraftResult:
    """单邮件草稿结果.

    Attributes:
        subject: 草稿主题(非空, 1-200 字符)
        body: 草稿正文(10-8000 字符, 内容允许 markdown)
        tone: 3 类语气之一(DraftTone 枚举)
        model_full_id: 实际调用的 provider/model(便于审计/计费)
        latency_ms: 单次草稿生成耗时(非负)
        raw_content: LLM 原始响应(便于排查,截断到 500 字符)
        spam_reply_authorized: 6/9 v1.0.6 P2-1 新增, 6/10 v1.0.7 P1-1 修正语义,
                              6/10 v1.0.7 P2-1 新增 spam_reply_intent 字段。
                              - True: 该草稿由 SPAM 邮件 + allow_spam_reply=True 授权触发
                              - False: 非 SPAM 邮件 或 虽 SPAM 但未授权(业务硬阻断路径)
                              一致性: spam_reply_authorized=True 时 spam_reply_intent 必非空
        spam_reply_intent: 6/10 v1.0.7 P2-1 新增, 实际授权意图(枚举/None)
                          - 枚举(UNSUBSCRIBE/REJECT): SPAM 授权放行时记录实际意图
                          - None: 非 SPAM 邮件 或 SPAM 阻断场景
                          便于 D4.7.3 Adapter 事件审计区分"礼貌退订"与"明确拒收"
                          严格 type 严判(枚举实例 / None, 拒 str 真值陷阱)

    6/9 v1.0.2 P2-3 修复: __post_init__ 严判 5 字段, 防止构造非法状态
    (空 subject / 短 body / str tone / 负延迟 / 空 model), 复用契约 1 helper。
    6/9 v1.0.6 P2-1 修复: 增加 `spam_reply_authorized: bool` 字段(契约外增量),
    便于 D4.7.3 EmailDrafterAdapter 事件审计追溯"是否通过 allow_spam_reply=True 生成"
    (v1.0.5 缺口: 成功结果无法区分"普通草稿"和"SPAM 授权放行草稿", 审计盲点)。
    6/10 v1.0.7 P1-1 修复: spam_reply_authorized 计算必须结合 email_category_str
    (v1.0.6 漏洞: 直接 spam_reply_authorized=allow_spam_reply, URGENT+allow=True
    会被误标为"SPAM 授权", 审计语义错位)
    6/10 v1.0.7 P2-1 修复: 增加 `spam_reply_intent` 字段记录实际授权意图
    (v1.0.6 缺口: 仅记录 bool 授权, 无法区分 UNSUBSCRIBE 与 REJECT)
    """

    subject: str
    body: str
    tone: DraftTone
    model_full_id: str
    latency_ms: int
    raw_content: str
    # 6/9 v1.0.6 P2-1 新增 + 6/10 v1.0.7 P1-1 修正: SPAM 授权标记
    # - False(默认): 非 SPAM 邮件(URGENT/TODO/FYI/PERSONAL) 或 SPAM 业务阻断路径
    # - True: SPAM 邮件 + allow_spam_reply=True 显式放行, 实际生成了可投递草稿
    # 严格 bool 严判(type value is bool, 拒 "false" / 1 真值陷阱)
    spam_reply_authorized: bool = False
    # 6/10 v1.0.7 P2-1 新增: 实际授权意图(便于 D4.7.3 Adapter 事件审计)
    # - DraftSpamReplyIntent 枚举实例: SPAM 授权放行时记录实际意图(UNSUBSCRIBE/REJECT)
    # - None: 非 SPAM 邮件(任何 allow_spam_reply 值都返回 None)
    #         或 SPAM 业务阻断路径(allow_spam_reply=False)
    # 一致性约束(由调用方负责 + __post_init__ 兜底校验):
    #   spam_reply_authorized=True  →  spam_reply_intent 必为 DraftSpamReplyIntent 枚举
    #   spam_reply_authorized=False →  spam_reply_intent 必为 None
    spam_reply_intent: DraftSpamReplyIntent | None = None

    def __post_init__(self) -> None:
        """自校验 7 字段(6/9 v1.0.2 P2-3 + v1.0.6 P2-1 + v1.0.7 P1-1 + v1.0.7 P2-1).

        编程错误(type 错 / 越界 / 一致性违反) → ValueError(透传, 不包装为 DrafterError).
        业务验收(长度/枚举) → 复用 _validate_draft_subject / _validate_draft_body
        / _validate_draft_tone(契约 1 严判下沉, D4.6 v1.0.2-second 范本).
        """
        # 严判入口(拒 bool 子类陷阱: isinstance(True, int) == True)
        if type(self.subject) is not str:
            raise ValueError(
                f"subject 必须是 str, 实际 {type(self.subject).__name__}={self.subject!r}"
            )
        if type(self.body) is not str:
            raise ValueError(f"body 必须是 str, 实际 {type(self.body).__name__}={self.body!r}")
        if not isinstance(self.tone, DraftTone):
            raise ValueError(
                f"tone 必须是 DraftTone 枚举, 实际 {type(self.tone).__name__}={self.tone!r}"
            )
        if type(self.model_full_id) is not str:
            raise ValueError(
                f"model_full_id 必须是 str, 实际 "
                f"{type(self.model_full_id).__name__}={self.model_full_id!r}"
            )
        if type(self.latency_ms) is not int or isinstance(self.latency_ms, bool):
            raise ValueError(
                f"latency_ms 必须是 int, 实际 {type(self.latency_ms).__name__}={self.latency_ms!r}"
            )
        if type(self.raw_content) is not str:
            raise ValueError(
                f"raw_content 必须是 str, 实际 "
                f"{type(self.raw_content).__name__}={self.raw_content!r}"
            )
        # 6/9 v1.0.6 P2-1 新增: spam_reply_authorized 严格 bool 严判
        # 拒 "false"(str)/ 1(int) 等真值陷阱, 与 P2-1 范本保持一致
        if type(self.spam_reply_authorized) is not bool:
            raise ValueError(
                f"spam_reply_authorized 必须是 bool, 实际 "
                f"{type(self.spam_reply_authorized).__name__}={self.spam_reply_authorized!r}"
            )
        # 6/10 v1.0.7 P2-1 新增: spam_reply_intent 严判
        # - 枚举实例: 直接接受(实际授权场景)
        # - None: 允许(非 SPAM 邮件 或 SPAM 业务阻断场景)
        # - 其他 type(str / int / bool) → 拒收(拒 str 真值陷阱, 严禁 "REJECT" 等隐式转换)
        if self.spam_reply_intent is not None and not isinstance(
            self.spam_reply_intent, DraftSpamReplyIntent
        ):
            raise ValueError(
                f"spam_reply_intent 必须是 DraftSpamReplyIntent 枚举或 None, 实际 "
                f"{type(self.spam_reply_intent).__name__}={self.spam_reply_intent!r}"
            )
        # 6/10 v1.0.7 P2-1 一致性校验: spam_reply_authorized 与 spam_reply_intent 必一致
        # - 授权=True → 实际意图必为枚举(否则 audit 拿不到"为什么授权放行"语义)
        # - 授权=False → 实际意图必为 None(否则 audit 会被误导"该草稿是 SPAM 授权放行")
        # 这是数据类兜底, 调用方(draft())应优先保证, 但构造时被绕过也要拦截
        if self.spam_reply_authorized and self.spam_reply_intent is None:
            raise ValueError(
                "spam_reply_authorized=True 时 spam_reply_intent 必为 DraftSpamReplyIntent 枚举"
                "(一致性契约, 防 audit 拿不到'为什么授权放行'语义), 实际 None"
            )
        if not self.spam_reply_authorized and self.spam_reply_intent is not None:
            raise ValueError(
                "spam_reply_authorized=False 时 spam_reply_intent 必为 None"
                f"(一致性契约, 防 audit 误读'该草稿是 SPAM 授权放行'), "
                f"实际 {self.spam_reply_intent!r}"
            )

        # 业务验收(契约 1 严判下沉)
        # 6/9 v1.0.3 P2-2 修复: strip() 严判语义非空("   " 长度 3 仍会被旧版绕过)
        if not self.model_full_id or not self.model_full_id.strip():
            raise ValueError(
                f"model_full_id 不能为空(仅空白也算空, 审计需要实际调用的 "
                f"provider/model): {self.model_full_id!r}"
            )
        if self.latency_ms < 0:
            raise ValueError(f"latency_ms 不能为负: {self.latency_ms}")
        _validate_draft_subject(self.subject)
        _validate_draft_body(self.body)
        # _validate_draft_tone 接受 DraftTone | str, 这里 tone 已是 DraftTone, 必通过

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(便于 JSON 化)."""
        return {
            "subject": self.subject,
            "body": self.body,
            "tone": self.tone.value,
            "model_full_id": self.model_full_id,
            "latency_ms": self.latency_ms,
            "raw_content": self.raw_content,
            "spam_reply_authorized": self.spam_reply_authorized,
            # 6/10 v1.0.7 P2-1: 序列化实际授权意图(枚举 .value, None → None)
            "spam_reply_intent": self.spam_reply_intent.value if self.spam_reply_intent else None,
        }


# ===== 阻断草稿结果数据类(6/9 v1.0.2 P1-1 新增)=====


@dataclass(frozen=True)
class DraftBlockedResult:
    """被业务阻断的邮件草稿结果(不调 LLM,直接产出"建议: 不回复"模板).

    D4.6 分类层已对 SPAM / 未来其他 BLOCKED 类别做业务拒绝,
    但 drafter 仍可能被独立调用(用户主动草稿 / 第三方集成).
    该数据类给上层(EmailDrafterAdapter / CLI)一个不抛异常、直接产出的通道,
    避免"草稿任务失败"误上报为"系统故障".

    Attributes:
        subject: 阻断草稿主题(典型: "(DRAFT-NO-REPLY) 风险标注: <原主题>")
        body: 阻断草稿正文(典型: "建议: 不回复\\n\\n原因: SPAM...")
        tone: 用户请求的 tone(透传,便于业务层 audit)
        reason: 阻断原因(机器可读, 如 'spam_business_blocked')
        original_email_category: 触发阻断的邮件分类
        spam_reply_authorized: 6/9 v1.0.6 P2-1 新增, 调用方当时是否传 allow_spam_reply=True
                              (业务层 audit: 即便最终被阻断, 也记录"调用方授权意图"
                              便于 D4.7.3 Adapter 事件审计追溯"为什么阻断"+"是否本来可放行")

    与 DraftResult 区别:
      - DraftResult 是 LLM 实际生成的草稿(含 model_full_id / latency_ms)
      - DraftBlockedResult 是模板化阻断产物(无 LLM 调用, 无 model 信息)

    Raises:
        __post_init__ 严判 6 字段, 编程错误 → ValueError(透传).
    """

    subject: str
    body: str
    tone: DraftTone
    reason: str
    original_email_category: str
    # 6/9 v1.0.6 P2-1 新增 + 6/10 v1.0.7 P2-1 补 intent 字段
    # - False(默认): 调用方未传 allow_spam_reply=True, 走"业务硬阻断"路径
    # - True: 调用方传了 allow_spam_reply=True, 但仍有阻断(本类只产出阻断模板不调 LLM)
    # 严格 bool 严判(type value is bool, 拒 "false" / 1 真值陷阱)
    spam_reply_authorized: bool = False
    # 6/10 v1.0.7 P2-1 新增: 调用方实际授权意图(便于 D4.7.3 Adapter 事件审计)
    # - DraftSpamReplyIntent 枚举: 调用方传了 allow_spam_reply=True + 明确 intent
    # - None: 调用方未授权(intent 即使在 draft() 严判通过, 阻断场景下也不入产物)
    # 注: 阻断场景 spam_reply_authorized 仍按调用方原 allow_spam_reply 记录(True/False),
    #     意图单独记录, 不做"授权+意图一致性"强约束(阻断是降级, 记录调用方意图即可)
    spam_reply_intent: DraftSpamReplyIntent | None = None

    def __post_init__(self) -> None:
        # 严判入口(拒 bool 子类陷阱)
        if type(self.subject) is not str:
            raise ValueError(
                f"subject 必须是 str, 实际 {type(self.subject).__name__}={self.subject!r}"
            )
        if type(self.body) is not str:
            raise ValueError(f"body 必须是 str, 实际 {type(self.body).__name__}={self.body!r}")
        if not isinstance(self.tone, DraftTone):
            raise ValueError(
                f"tone 必须是 DraftTone 枚举, 实际 {type(self.tone).__name__}={self.tone!r}"
            )
        if type(self.reason) is not str or not self.reason:
            raise ValueError(
                f"reason 必填非空 str, 实际 {type(self.reason).__name__}={self.reason!r}"
            )
        if type(self.original_email_category) is not str or not self.original_email_category:
            raise ValueError(
                f"original_email_category 必填非空 str, "
                f"实际 {type(self.original_email_category).__name__}"
            )
        # 6/9 v1.0.6 P2-1 新增: spam_reply_authorized 严格 bool 严判
        # 拒 "false"(str)/ 1(int) 等真值陷阱, 与 DraftResult 范本保持一致
        if type(self.spam_reply_authorized) is not bool:
            raise ValueError(
                f"spam_reply_authorized 必须是 bool, 实际 "
                f"{type(self.spam_reply_authorized).__name__}={self.spam_reply_authorized!r}"
            )
        # 6/10 v1.0.7 P2-1 新增: spam_reply_intent 严判
        # - 枚举实例: 直接接受(调用方传了 intent)
        # - None: 允许(未授权 或 调用方未指定 intent)
        # - 其他 type → 拒收
        if self.spam_reply_intent is not None and not isinstance(
            self.spam_reply_intent, DraftSpamReplyIntent
        ):
            raise ValueError(
                f"spam_reply_intent 必须是 DraftSpamReplyIntent 枚举或 None, 实际 "
                f"{type(self.spam_reply_intent).__name__}={self.spam_reply_intent!r}"
            )
        # 业务验收(subject / body / reason / original_email_category 至少语义非空, 防空字符串绕过)
        if not self.subject.strip():
            raise ValueError(f"subject 语义为空(仅空白): {self.subject!r}")
        if not self.body.strip():
            raise ValueError(f"body 语义为空(仅空白): {self.body!r}")
        # 6/9 v1.0.4 P2-2 修复: reason / original_email_category 同样需 strip() 严判(防纯空白绕过)
        if not self.reason.strip():
            raise ValueError(f"reason 语义为空(仅空白): {self.reason!r}")
        if not self.original_email_category.strip():
            raise ValueError(
                f"original_email_category 语义为空(仅空白): {self.original_email_category!r}"
            )
        # 6/9 v1.0.4 P2-2 修复: original_email_category 限定 SPAM 集合(本数据类专为阻断场景设计,
        # 拒收 URGENT/TODO/FYI/PERSONAL 错类, 与 draft_blocked_category 入口严判保持一致)
        if self.original_email_category not in {"SPAM"}:
            raise ValueError(
                f"original_email_category 必须是 'SPAM', 实际 {self.original_email_category!r}"
            )
        # 6/9 v1.0.5 P2-2 修复: reason 锁定白名单(防 "other" 等任意字符串构造不一致状态)
        # 当前阻断类别仅 SPAM, reason 限定为 "spam_business_blocked"
        # 未来扩阻断类别需 B 类审批 + 扩 _BLOCKED_REASON_VALUES
        if self.reason not in _BLOCKED_REASON_VALUES:
            raise ValueError(
                f"reason 必须是 {sorted(_BLOCKED_REASON_VALUES)} 之一, 实际 {self.reason!r}"
            )
        # 6/9 v1.0.3 P2-2 修复: subject 上限 200 字符(与 DraftResult.MAX_SUBJECT_CHARS 同步)
        # 阻断模板会自动拼 "(DRAFT-NO-REPLY) [SPAM] " 前缀, 实际可用 ≈ 175 字符
        if len(self.subject) > 200:
            raise ValueError(f"subject 超长(> 200 字符): 实际 {len(self.subject)} 字符")
        # 6/9 v1.0.4 P2-2 修复: body 长度上限契约复用 EmailDrafter.MAX_BODY_CHARS=2000
        # 防止超长 sender 注入式构造 9229 字符 body 突破契约
        if len(self.body) > EmailDrafter.MAX_BODY_CHARS:
            raise ValueError(
                f"body 超长(> {EmailDrafter.MAX_BODY_CHARS} 字符): 实际 {len(self.body)} 字符"
            )

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(便于 JSON 化)."""
        return {
            "subject": self.subject,
            "body": self.body,
            "tone": self.tone.value,
            "reason": self.reason,
            "original_email_category": self.original_email_category,
            "blocked": True,  # 显式标记,便于上层识别"阻断产物 vs LLM 产物"
            "spam_reply_authorized": self.spam_reply_authorized,
            # 6/10 v1.0.7 P2-1: 序列化调用方实际授权意图
            "spam_reply_intent": self.spam_reply_intent.value if self.spam_reply_intent else None,
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
        allow_spam_reply: bool = False,
        spam_reply_intent: DraftSpamReplyIntent | str | None = None,
    ) -> DraftResult:
        """单邮件草稿生成.

        Args:
            subject: 邮件主题(允许空字符串)
            sender: 发件人(允许空字符串)
            body_excerpt: 正文前 N 字符(> MAX_BODY_CHARS 时截断)
            email_category: 5 类邮件标签(D4.6 分类结果, 接受 EmailCategory 枚举 /
                            5 类字符串 / None; 6/9 P1-1 修复允许 D4.6 真实 handoff)
            tone: 草稿语气(默认 FORMAL)
            allow_spam_reply: 6/9 v1.0.2 P1-1 新增, 是否允许为 SPAM 邮件生成可投递草稿.
                            默认 False(业务硬阻断, 与 D4.6 BLOCKED 流程形成双保险);
                            True 时显式覆盖阻断, 但调用方必须在业务层 audit(避免误用).
                            若需"产出阻断模板但不抛异常", 请用 draft_blocked_category() 独立入口.
            spam_reply_intent: 6/9 v1.0.6 P2-2 新增, 6/10 v1.0.7 P2-2 文档统一契约.
                            **永远先严判**(独立于 allow_spam_reply):
                            - 严判位置: draft() 入口段(spam_reply_authorized 严判后,
                              tone 校验前)
                            - 接受类型: DraftSpamReplyIntent 枚举 / 字符串 / None
                            - 枚举: 直接接受
                            - 字符串: 严判 ∈ {UNSUBSCRIBE, REJECT}, **排除 ACKNOWLEDGE**
                              (与 SYSTEM_PROMPT_SPAM "避免确认邮箱活跃" 业务硬规则矛盾)
                            - None: 允许(默认 UNSUBSCRIBE, 在 SPAM 授权时启用)
                            - 其他 type(非枚举非字符串非None) → ValueError
                            **应用场景**:
                            - allow_spam_reply=True + email_category=SPAM: 实际生效
                              None → UNSUBSCRIBE(最安全的"单向拒绝"语义)
                              UNSUBSCRIBE → 礼貌退订
                              REJECT → 明确拒收
                            - allow_spam_reply=False + email_category=SPAM: SPAM 阻断,
                              严判通过后 intent 进入 DraftBlockedResult.spam_reply_intent
                              (便于 D4.7.3 audit 追溯"调用方意图")
                            - email_category=非 SPAM: 严判通过后, spam_reply_authorized
                              仍为 False(防误标, v1.0.7 P1-1), intent 记录为 None
                            v1.0.6 文档错误修正: 原文档"未授权时被忽略" 不准确, 实际
                            参数**永远先严判**(类型错 / 非法字符串 → ValueError),
                            不存在"忽略"语义。意图是否生效由 allow_spam_reply + email_category
                            共同决定(详见 P2-2 范本)。

        Returns:
            DraftResult(含 subject + body + tone + 调用模型 + spam_reply_authorized)

        Raises:
            ValueError: 参数 type 错(编程错误, 透传)
            SpamBlockedError: email_category=SPAM 且 allow_spam_reply=False(业务硬阻断)
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
        # allow_spam_reply 类型严判(D5 严判入口范本)
        if type(allow_spam_reply) is not bool:
            raise ValueError(
                f"allow_spam_reply 必须是 bool, 实际 {type(allow_spam_reply).__name__}"
            )
        # 6/9 v1.0.6 P2-2 新增: spam_reply_intent 严判
        # - 枚举/字符串 2 类(契约外增量, 排除 ACKNOWLEDGE 语义冲突)
        # - None 允许(默认 UNSUBSCRIBE, 在 SPAM 授权时启用)
        # 6/9 v1.0.6 P2-2: spam_reply_intent 严判(类型 + 白名单)
        # - 枚举/字符串 2 类(契约外增量, 排除 ACKNOWLEDGE 语义冲突)
        # - None 允许(默认 UNSUBSCRIBE, 在 SPAM 授权时启用)
        intent_enum: DraftSpamReplyIntent | None
        if spam_reply_intent is not None:
            if isinstance(spam_reply_intent, DraftSpamReplyIntent):
                intent_enum = spam_reply_intent
            elif type(spam_reply_intent) is str:
                try:
                    intent_enum = DraftSpamReplyIntent(spam_reply_intent)
                except ValueError as e:
                    raise ValueError(
                        f"spam_reply_intent 字符串必须 ∈ "
                        f"{sorted(_DRAFT_SPAM_REPLY_INTENT_CHOICES)}, "
                        f"实际 {spam_reply_intent!r}"
                    ) from e
            else:
                raise ValueError(
                    f"spam_reply_intent 必须是 DraftSpamReplyIntent 枚举 / str / None, "
                    f"实际 {type(spam_reply_intent).__name__}"
                )
        else:
            # allow_spam_reply=True 时 None → 默认 UNSUBSCRIBE(最安全语义)
            # allow_spam_reply=False 时 忽略(后续 SPAM 阻断会抛)
            intent_enum = DraftSpamReplyIntent.UNSUBSCRIBE if allow_spam_reply else None
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

        # 6/9 v1.0.6 P1-1 修复: tone 校验必须在 SPAM 阻断**之前**
        # - 检查员第七次复检 P1: 非法 tone(如 "OOPS")若在 SPAM 阻断后校验,
        #   会先被记录为业务阻断(stats["total"]+=1, stats["blocked"]+=1),
        #   再抛 ValueError 退出, 污染 total/blocked 统计, 上层 audit 误读
        #   "SPAM 阻断率虚高"
        # - 范本: "先完成全部参数校验, 再执行阻断及统计变更"
        #   (与 D4.4 P1 入口严判范本 + D4.6 v1.0.2-second 业务验收前参数严判一致)
        # - DraftTone 枚举 / 字符串 3 类(契约 3 锁定, 大小写敏感)
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

        # 6/9 v1.0.2 P1-1 业务硬阻断: SPAM 默认阻断(不调 LLM)
        # - 不依赖 prompt 文案(那是软引导), 业务层必须有硬阻断
        # - 与 D4.6 分类层 BLOCKED 流程形成双保险
        # - allow_spam_reply=True 显式覆盖(调用方需在业务层 audit)
        # - 6/9 v1.0.6 P1-1 修复后: 此处 tone 已是 DraftTone 枚举, 非法 tone 不会污染
        email_category_str = (
            email_category.value if isinstance(email_category, EmailCategory) else email_category
        )
        if email_category_str == "SPAM" and not allow_spam_reply:
            self._stats["total"] += 1
            self._stats["blocked"] = self._stats.get("blocked", 0) + 1
            logger.warning(
                f"[drafter] SPAM 业务硬阻断 | subject={subject!r} | "
                f"sender={sender!r} | allow_spam_reply=False"
            )
            raise SpamBlockedError(
                "SPAM 邮件被业务硬阻断(allow_spam_reply=False), 与 D4.6 BLOCKED 流程保持一致",
                email_category="SPAM",
                allow_spam_reply=False,
                reason="spam_business_blocked",
            )

        # 正文截断(防御巨型 body)
        if len(body_excerpt) > self.MAX_BODY_CHARS:
            body_excerpt = body_excerpt[: self.MAX_BODY_CHARS]

        self._stats["total"] += 1

        # 构造 messages(D4.7.2 v1.0.1 P1 修复: 委托 prompts/draft.py build_user_message)
        # - SYSTEM prompt: _build_draft_system_prompt 按 email_category 5+1 类分发
        # - user 消息: _build_draft_user_message 含 P1-3 tone 末行重述 + 抗注入声明
        #   (本地旧 build_user_message 已删除, v1.0 误用旧版导致 P1 tone 重述未生效)
        # - email_category 枚举/字符串 → 内部统一 str 用于分发(SPAM 已在前面阻断,
        #   此处只可能走 URGENT/TODO/FYI/PERSONAL/None 5 路径)
        # - None → SYSTEM_PROMPT_DEFAULT(中性回退)
        # 6/9 v1.0.5 P1-1 修复: 把 allow_spam_reply 透传给 build_user_message,
        # SPAM 显式授权意图才能进入 user 消息(此前模型只看到 SYSTEM prompt 的
        # "默认不生成回复"指令, 不知道调用方已显式放行, 模型仍按默认拒收生成)
        # 6/9 v1.0.6 P2-2 修复: 透传 spam_reply_intent(枚举或 None),
        # 让 build_user_message 根据枚举值选择措辞(UNSUBSCRIBE/REJECT),
        # 排除"确认收悉"等与 SYSTEM_PROMPT_SPAM "避免确认邮箱活跃"矛盾的措辞
        system_prompt = _build_draft_system_prompt(email_category_str)
        messages = [
            system_to_message(system_prompt),
            *_build_draft_user_message(
                subject=subject,
                sender=sender,
                body_excerpt=body_excerpt,
                email_category=email_category_str,
                tone=tone_enum.value,
                allow_spam_reply=allow_spam_reply,
                spam_reply_intent=intent_enum.value if intent_enum is not None else None,
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
        # 6/9 v1.0.2 P2-2 修复: 业务验收(契约 1) 已下沉到 _parse_draft_response,
        # 解析成功即通过验收, 不再有 validation_error 计数分支
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

        self._stats["success"] += 1
        # 6/10 v1.0.7 P1-1 修复: spam_reply_authorized 计算必须结合 email_category_str
        # - v1.0.6 漏洞: 直接 spam_reply_authorized=allow_spam_reply, URGENT+allow=True
        #   被审计为"SPAM 授权", 与 D4.7.3 事件审计需求矛盾(非 SPAM 不应有授权标记)
        # - v1.0.7 真修: 仅当 email_category_str=="SPAM" AND allow_spam_reply=True 时
        #   才记录 True(代表"该草稿确实由 SPAM 授权意图触发并生成可投递草稿")
        # - 非 SPAM 邮件无论 allow_spam_reply 为何值, 永远 spam_reply_authorized=False
        # - 6/10 v1.0.7 P2-1 修复: 同时透传 intent_enum(SPAM 授权场景下必非空,
        #   非 SPAM 场景为 None, 与 spam_reply_authorized 一致性绑定)
        spam_reply_authorized: bool = email_category_str == "SPAM" and allow_spam_reply
        return DraftResult(
            subject=draft_subject,
            body=draft_body,
            tone=draft_tone,
            model_full_id=response.model_full_id,
            latency_ms=response.latency_ms,
            raw_content=response.content,
            # 6/10 v1.0.7 P1-1: 授权计算必须结合 email_category_str
            # 6/10 v1.0.7 P2-1: 透传实际 intent(SPAM 时为 UNSUBSCRIBE/REJECT, 非 SPAM 时为 None)
            spam_reply_authorized=spam_reply_authorized,
            spam_reply_intent=intent_enum if spam_reply_authorized else None,
        )

    def draft_batch(
        self,
        emails: list[dict],
        *,
        allow_spam_reply: bool = False,
    ) -> list[
        DraftResult
        | DraftBlockedResult
        | DrafterResponseError
        | LLMError
        | ValueError
        | KeyError
        | TypeError
    ]:
        """批量草稿生成(顺序串行, 避免触发熔断).

        Args:
            emails: list[dict], 每条 dict 必须包含 subject/sender/body_excerpt 3 key
                   (类型不匹配 / 缺字段 → 异常入 results, 不静默吞掉, 不外抛)
                   可选 key: email_category / tone / allow_spam_reply(per-email 覆盖批默认)
            allow_spam_reply: 批级默认 SPAM 阻断策略(默认 False = 业务硬阻断)
                - per-email dict 中若含 "allow_spam_reply" 键, 则用 per-email 值覆盖
                - True: SPAM 走 draft 路径(可能调用 LLM)
                - False(默认): SPAM 业务硬阻断, 产出 DraftBlockedResult(不调 LLM)

        Returns:
            list[DraftResult | DraftBlockedResult | 异常], 与 emails 1:1 对齐
              - 成功: DraftResult
              - SPAM 业务阻断(默认): DraftBlockedResult(0 配额, 不调 LLM)
              - 响应解析失败: DrafterResponseError
              - LLM 全链失败: LLMError
              - 编程错误(非 dict / 类型错): ValueError
              - 编程错误(缺字段): KeyError
              - 6/9 v1.0.4 P1-2 新增: 阻断模板构造异常降级: TypeError
            SpamBlockedError 绝不上抛 — 6/9 v1.0.3 P1-1 修复(批次不中断, 输入输出 1:1)。
        """
        # 6/9 v1.0.4 P1-1 修复: 批级参数严判 type(value) is bool
        # 签名默认 bool=False, 但 Python 不拒 int=1 / str="true" 等真值陷阱
        # 严判后返回空 list + logger 告警(让"批级非法"立即被上层发现, 不静默)
        if type(allow_spam_reply) is not bool:
            raise ValueError(
                f"draft_batch 批级 allow_spam_reply 必须是 bool, "
                f"实际 {type(allow_spam_reply).__name__}={allow_spam_reply!r}"
            )
        results: list[
            DraftResult
            | DraftBlockedResult
            | DrafterResponseError
            | LLMError
            | ValueError
            | KeyError
            | TypeError
        ] = []
        for i, email in enumerate(emails):
            if not isinstance(email, dict):
                results.append(ValueError(f"emails[{i}] 必须是 dict, 实际 {type(email).__name__}"))
                continue
            # 缺字段时 KeyError 收容入 list(D4.6 v1.0.2 P2-4 范本)
            missing_keys = [k for k in ("subject", "sender", "body_excerpt") if k not in email]
            if missing_keys:
                results.append(KeyError(f"emails[{i}] 缺字段 {missing_keys}"))
                continue
            # per-email allow_spam_reply 优先, 缺则用批默认(D4.7.2 v1.0.3 P1-1)
            per_email_allow = email.get("allow_spam_reply", allow_spam_reply)
            # 6/9 v1.0.4 P1-1 修复: per-email 值必须 type(value) is bool(拒 bool() 吞真值陷阱)
            # 严判位置: 在调 draft() 之前, 非法项 → ValueError 收容入 results, 不调 LLM
            if type(per_email_allow) is not bool:
                results.append(
                    ValueError(
                        f"emails[{i}] allow_spam_reply 必须是 bool, "
                        f"实际 {type(per_email_allow).__name__}={per_email_allow!r}"
                    )
                )
                continue
            try:
                result = self.draft(
                    subject=email["subject"],
                    sender=email["sender"],
                    body_excerpt=email["body_excerpt"],
                    email_category=email.get("email_category"),
                    tone=email.get("tone", DraftTone.FORMAL),
                    allow_spam_reply=per_email_allow,
                    # 6/10 v1.0.7 P1-2 修复: 批量入口透传 spam_reply_intent
                    # - v1.0.6 漏洞: draft_batch 未透传 intent 字段, 调用方指定 REJECT
                    #   时会静默退化为默认 UNSUBSCRIBE, 业务层 audit 无法追溯"调用方
                    #   真实授权意图", D4.7.3 事件审计也拿不到 intent
                    # - v1.0.7 真修: 优先 per-email 字段, 缺则用批默认; None 允许
                    #   (None 在 draft() 内部会被严判, draft() 入口已确保合法)
                    spam_reply_intent=email.get("spam_reply_intent"),
                )
                results.append(result)
            except SpamBlockedError as e:
                # SPAM 业务硬阻断 — 不上抛, 降级为 DraftBlockedResult 项(0 配额)
                # 与 D4.6 BLOCKED 流程形成双保险(批维度), 避免混合批次中断
                # 注: stats["blocked"] 已在 draft() 内累加过, 此处不再 +1
                logger.info(
                    f"[drafter] 批量 SPAM 业务硬阻断(不调 LLM) | index={i} | "
                    f"subject={email['subject']!r} | reason={e.reason}"
                )
                try:
                    blocked = self.draft_blocked_category(
                        subject=email["subject"],
                        sender=email["sender"],
                        body_excerpt=email["body_excerpt"],
                        email_category=e.email_category,
                        tone=email.get("tone", DraftTone.FORMAL),
                        # 6/9 v1.0.6 P2-1 新增: 透传调用方授权意图(便于 D4.7.3 Adapter 事件审计)
                        spam_reply_authorized=per_email_allow,
                        # 6/10 v1.0.7 P2-1 修复: 透传调用方实际授权意图(阻断场景下也记录)
                        spam_reply_intent=email.get("spam_reply_intent"),
                        _stats_already_bumped=True,  # draft() 已 +1, 避免重复
                    )
                    results.append(blocked)
                except (ValueError, TypeError) as blocked_err:
                    # 6/9 v1.0.4 P1-2 修复: 阻断模板降级构造异常也入 results, 严守 1:1 契约
                    # 兜底场景: 极端 subject(空字符 / 巨型字符) / body 异常构造
                    logger.warning(
                        f"[drafter] 批量阻断模板构造失败(降级入 results) | index={i} | "
                        f"err={blocked_err!r}"
                    )
                    results.append(blocked_err)
            except (DrafterResponseError, LLMError, ValueError) as e:
                results.append(e)
        return results

    def draft_blocked_category(
        self,
        *,
        subject: str,
        sender: str,
        body_excerpt: str,
        email_category: EmailCategory | str,
        tone: DraftTone | str = DraftTone.FORMAL,
        spam_reply_authorized: bool = False,
        # 6/10 v1.0.7 P2-1 新增: 调用方实际授权意图(SPAM 阻断场景下也记录, 便于 audit)
        # 严判: 枚举/字符串/None 3 类(字符串在内部转枚举, None 允许)
        spam_reply_intent: DraftSpamReplyIntent | str | None = None,
        _stats_already_bumped: bool = False,
    ) -> DraftBlockedResult:
        """为业务阻断邮件产出"建议: 不回复"模板(不调 LLM, 6/9 v1.0.2 P1-1 新增).

        与 draft() 区别:
          - **不调 LLM**: 直接构造阻断模板, 0 LLM 配额消耗, 0 延迟
          - **不抛 SpamBlockedError**: 即便 email_category=SPAM 也直接返回模板
            (本入口专为"产出阻断模板"设计, 上层做"安全降级"语义)
          - **不消耗熔断配额**: 即便 router 全链失败, 本入口仍可用(降级通道)
          - **可投递性**: 阻断产物可投递(带 (DRAFT-NO-REPLY) 标注),
            也可作 audit 留底(便于后续追溯"为什么没有正式草稿")

        Args:
            subject: 邮件主题(允许空字符串)
            sender: 发件人(允许空字符串)
            body_excerpt: 正文(本入口不调 LLM, 仅用于审计/正文摘要)
            email_category: 触发阻断的邮件分类(SPAM 或未来其他 BLOCKED 类别)
            tone: 透传给 DraftBlockedResult.tone(便于业务层 audit)
            spam_reply_authorized: 6/9 v1.0.6 P2-1 新增, 调用方当时是否传 allow_spam_reply=True
                                  (业务层 audit: 即便最终被阻断, 也记录"调用方授权意图"
                                  便于 D4.7.3 Adapter 事件审计追溯"为什么阻断"+"是否本来可放行")
                                  严格 bool 严判(type value is bool, 拒 "false" / 1 真值陷阱)
            spam_reply_intent: 6/10 v1.0.7 P2-1 新增, 调用方实际授权意图(SPAM 阻断场景下记录)
                              严判: DraftSpamReplyIntent 枚举 / 字符串 / None
                              - 枚举: 直接接受
                              - 字符串: 严判 ∈ {UNSUBSCRIBE, REJECT}, 排除 ACKNOWLEDGE
                              - None: 允许(未授权 或 调用方未指定 intent)
                              拒绝非枚举非字符串(防止 str 真值陷阱)
                              **与 draft() 入口严判范本保持一致**(P2-2 文档统一契约)

        Returns:
            DraftBlockedResult(含 subject="(DRAFT-NO-REPLY) ..." + body="建议: 不回复..."
                              + tone + reason="spam_business_blocked"
                              + original_email_category=email_category
                              + spam_reply_authorized)

        Raises:
            ValueError: 参数 type 错 / 非法 email_category 字符串(编程错误, 透传)
        """
        # 严判入口(与 draft() 一致范本)
        if type(subject) is not str:
            raise ValueError(f"subject 必须是 str, 实际 {type(subject).__name__}={subject!r}")
        if type(sender) is not str:
            raise ValueError(f"sender 必须是 str, 实际 {type(sender).__name__}={sender!r}")
        if type(body_excerpt) is not str:
            raise ValueError(
                f"body_excerpt 必须是 str, 实际 {type(body_excerpt).__name__}={body_excerpt!r}"
            )
        # 6/9 v1.0.5 P2-1 修复: 私有统计参数严判 type(value) is bool
        # 实测传入 _stats_already_bumped="false" 或 1 时:
        #   - "false"(str):  bool("false") == True → if not _stats_already_bumped 走 +1
        #   - 1(int):        bool(1) == True → if not _stats_already_bumped 走 +1
        #   两种误用都会让"批量路径不重复 total"语义被打破, stats 计数错误
        # 私有参数也必须严判(防外部误传 / 误用), 与 v1.0.4 P1-1 批级严判保持范本一致
        if type(_stats_already_bumped) is not bool:
            raise ValueError(
                f"draft_blocked_category _stats_already_bumped 必须是 bool, "
                f"实际 {type(_stats_already_bumped).__name__}={_stats_already_bumped!r}"
            )
        # 6/9 v1.0.6 P2-1 新增: spam_reply_authorized 入口严判
        # 拒 "false"(str)/ 1(int) 等真值陷阱, 与 DraftBlockedResult __post_init__ 保持范本一致
        if type(spam_reply_authorized) is not bool:
            raise ValueError(
                f"draft_blocked_category spam_reply_authorized 必须是 bool, "
                f"实际 {type(spam_reply_authorized).__name__}={spam_reply_authorized!r}"
            )
        # 6/10 v1.0.7 P2-1 + P2-2 修复: spam_reply_intent 入口严判(类型 + 白名单)
        # - 枚举/字符串 2 类(契约外增量, 排除 ACKNOWLEDGE 语义冲突)
        # - None 允许(未授权场景)
        # 严判位置: 在 type(value) is bool 之后, 与 draft() 入口范本一致(P2-2 文档统一)
        if spam_reply_intent is not None:
            if isinstance(spam_reply_intent, DraftSpamReplyIntent):
                intent_enum = spam_reply_intent
            elif type(spam_reply_intent) is str:
                try:
                    intent_enum = DraftSpamReplyIntent(spam_reply_intent)
                except ValueError as e:
                    raise ValueError(
                        f"draft_blocked_category spam_reply_intent 字符串必须 ∈ "
                        f"{sorted(_DRAFT_SPAM_REPLY_INTENT_CHOICES)}, "
                        f"实际 {spam_reply_intent!r}"
                    ) from e
            else:
                raise ValueError(
                    f"draft_blocked_category spam_reply_intent 必须是 "
                    f"DraftSpamReplyIntent 枚举 / str / None, "
                    f"实际 {type(spam_reply_intent).__name__}"
                )
        else:
            intent_enum = None
        # email_category 必填(本入口专给阻断场景用, 不允许 None 走 DEFAULT)
        if email_category is None:
            raise ValueError("email_category 必填(本入口只接受阻断类别, 不允许 None)")
        if isinstance(email_category, EmailCategory):
            cat_str = email_category.value
        elif type(email_category) is str:
            if email_category not in _EMAIL_CATEGORY_VALUES:
                raise ValueError(
                    f"email_category 字符串必须 ∈ {sorted(_EMAIL_CATEGORY_VALUES)}, "
                    f"实际 {email_category!r}"
                )
            cat_str = email_category
        else:
            raise ValueError(
                f"email_category 必须是 EmailCategory 枚举或 str, "
                f"实际 {type(email_category).__name__}"
            )
        # 6/9 v1.0.3 P1-2 修复: 本入口只接受阻断类别(SPAM / 未来 OTHER_BLOCKED),
        # URGENT/TODO/FYI/PERSONAL 等非阻断类一律拒收(防伪造 *_business_blocked 产物)
        if cat_str != "SPAM":
            raise ValueError(
                f"draft_blocked_category 入口只接受阻断类别(SPAM), "
                f"实际 {cat_str!r}(非阻断类应走 draft() 而非本降级通道)"
            )
        # tone 转枚举(与 draft() 同范本)
        if isinstance(tone, DraftTone):
            tone_enum = tone
        elif type(tone) is str:
            try:
                tone_enum = DraftTone(tone)
            except ValueError as e:
                raise ValueError(
                    f"tone 字符串必须 ∈ {sorted(_DRAFT_TONE_CHOICES)}, 实际 {tone!r}"
                ) from e
        else:
            raise ValueError(f"tone 必须是 DraftTone 或 str, 实际 {type(tone).__name__}")

        # 构造阻断模板(不调 LLM, 0 配额消耗)
        # stats 累加语义:
        #   - 独立调用本入口(draft() 未触发): _stats_already_bumped=False, +1 blocked, +1 total
        #   - 从 draft_batch 收容处调用: _stats_already_bumped=True(draft() 已 +1 total, +1 blocked), 0 重复
        # 防"独立调用 vs 批量调用"路径 stats 计数不一致
        # 6/9 v1.0.4 P2-1 修复: 批量路径不重复 total(原无条件 +1 是 bug, draft() 抛 SPAM 之前已 +1)
        if not _stats_already_bumped:
            self._stats["total"] += 1
            self._stats["blocked"] = self._stats.get("blocked", 0) + 1
        reason = f"{cat_str.lower()}_business_blocked"
        original_subject = subject or "(无主题)"
        # 6/9 v1.0.4 P1-2 修复: 阻断模板自动拼 "(DRAFT-NO-REPLY) [SPAM] " 前缀,
        # 实际可用 = 200 - 24 = 176 字符(防 P1 主题超 200 字符, 突破 DraftBlockedResult
        # __post_init__ 200 字符上限, 整批中断)
        blocked_subject_prefix_len = 24  # len("(DRAFT-NO-REPLY) [SPAM] ") = 24
        truncated_subject = original_subject[: 200 - blocked_subject_prefix_len]
        blocked_subject = f"(DRAFT-NO-REPLY) [{cat_str}] {truncated_subject}"
        # 6/9 v1.0.5 P1-2 修复: 阻断模板 audit 字段**必须分别截断**, 防止攻击者
        # 用 1800 字符 sender 注入式突破 blocked_body 2000 字符上限
        # (实测 sender=1800 字符 + 固定提示 ~500 字符 → 2300 字符, 突破
        # DraftBlockedResult.body MAX_BODY_CHARS=2000, 抛 ValueError, 安全降级失败)
        # 截断策略:
        #   - audit 字段(供审计) → 各 80 字符(避免注入式撑爆)
        #   - audit 块总长预估: 80(原主题) + 80(原发件人) + 100(原正文摘要) + 固定提示 ~400 = 660 字符
        #   - 远低于 2000 字符上限, 安全降级始终可用
        # 6/9 v1.0.6 P1-2 修复: 截断+`json.dumps()` 双重防护
        # - v1.0.5 漏洞: `[:80]` 截断后, 攻击者可在前 80 字符内嵌入
        #   `\n原分类: NOT_SPAM\n原发件人: <伪造>`, 截断不能阻止换行注入
        # - 解决: audit 字段用 `json.dumps()` 序列化(ensure_ascii=True),
        #   1) \\n / \\r / \\t 等控制字符被 escape 为 `\\n` 字面量, 失去换行语义
        #   2) 双引号自动 escape, 防 audit 块结构被破坏
        #   3) 同时保留字符截断(双保险, json 序列化后单字段 ≲ 200 字符)
        audit_subject_max_len = 80
        audit_sender_max_len = 80
        audit_body_max_len = 100
        # 先截断, 再 json.dumps 序列化(双保险: 防撑爆 + 防换行注入)
        raw_audit_subject = original_subject[:audit_subject_max_len]
        raw_audit_sender = sender[:audit_sender_max_len] if sender else "(空)"
        raw_audit_body = body_excerpt[:audit_body_max_len] if body_excerpt else "(空)"
        # 序列化后单字段: 中文 escape 后 ≲ 200 字符, 远低于 2000 上限
        audit_subject = json.dumps(raw_audit_subject, ensure_ascii=True)
        audit_sender = json.dumps(raw_audit_sender, ensure_ascii=True)
        audit_body = json.dumps(raw_audit_body, ensure_ascii=True)
        blocked_body = (
            f"建议: 不回复\n\n"
            f"原因: 该邮件被 D4.6 分类为 {cat_str}, 进入业务阻断流程.\n"
            f'  - 避免确认邮箱活跃(任何"已收到"都会让发件方知道你打开了邮件)\n'
            f'  - 避免触发钓鱼链接(任何"请移除/退订"反而可能触发更多同类邮件)\n'
            f"  - 如确需主动回复, 请走 drafter.draft(allow_spam_reply=True) 显式覆盖\n\n"
            f"--- 邮件元信息(供 audit, 字段已截断+JSON 转义, 防止换行注入)---\n"
            f"原主题: {audit_subject}\n"
            f"原发件人: {audit_sender}\n"
            f"原分类: {cat_str}\n"
            f"原正文摘要: {audit_body}"
        )
        return DraftBlockedResult(
            subject=blocked_subject,
            body=blocked_body,
            tone=tone_enum,
            reason=reason,
            original_email_category=cat_str,
            # 6/9 v1.0.6 P2-1 新增: 透传调用方授权意图(便于 D4.7.3 Adapter 事件审计
            # 追溯"调用方当时是否传 allow_spam_reply=True")
            spam_reply_authorized=spam_reply_authorized,
            # 6/10 v1.0.7 P2-1 新增: 透传调用方实际授权意图(枚举, 阻断场景下也记录)
            spam_reply_intent=intent_enum,
        )


# ===== 模块内辅助函数 =====


def system_to_message(content: str) -> dict:
    """把 system prompt 字符串转 OpenAI 风格 message dict.

    严判: content 必须是原生 str(D4.5 P0 教训应用)。
    """
    if type(content) is not str or not content:
        raise ValueError(f"system content 必填非空 str, 实际 {type(content).__name__}")
    return {"role": "system", "content": content}


# D4.7.2 v1.0.1 P1 修复: 本地 build_user_message 已删除, 委托给 prompts/draft.py
# (旧实现缺少 P1-3 tone 末行重述 + 抗注入声明, 真实生产消息未生效)


# ===== 3 个 _validate_draft_* helper(契约 1 公共 API,供 D4.7.3 严判下沉复用)=====


def _validate_draft_subject(subject: Any) -> None:
    """严判草稿 subject(契约 1).

    规则:
      - type 必须是 str(拒 bool 子类陷阱,D4.4 P1 教训)
      - 1 <= len <= 200(非空, 不超长)
      - **strip() 语义非空**(6/9 v1.0.2 P1-2 修复): 拒纯空白 subject("   " / 换行等)
        仅按字符数校验会被纯空白绕过
      - 严判入口: type 错 → ValueError(编程错误, 透传)

    Raises:
        ValueError: 长度越界 / type 错 / 纯空白(编程错误)
    """
    # 拒 bool 子类陷阱(isinstance(True, int) == True, 易误过)
    if type(subject) is not str:
        raise ValueError(f"subject 必须是 str, 实际 {type(subject).__name__}={subject!r}")
    if len(subject) < EmailDrafter.MIN_SUBJECT_CHARS:
        raise ValueError(f"subject 太短(契约 1): {len(subject)} < {EmailDrafter.MIN_SUBJECT_CHARS}")
    if len(subject) > EmailDrafter.MAX_SUBJECT_CHARS:
        raise ValueError(f"subject 太长(契约 1): {len(subject)} > {EmailDrafter.MAX_SUBJECT_CHARS}")
    # 6/9 v1.0.2 P1-2 修复: strip() 语义非空校验, 拒纯空白 subject
    if not subject.strip():
        raise ValueError(f"subject 语义为空(仅空白字符, 契约 1): {subject!r}")


def _validate_draft_body(body: Any) -> None:
    """严判草稿 body(契约 1).

    规则:
      - type 必须是 str
      - 10 <= len <= 8000(明确长度边界)
      - **strip() 语义非空**(6/9 v1.0.2 P1-2 修复): 拒纯空白 body(10 个空格 / 换行等)
        仅按字符数校验会被纯空白绕过
      - 严判入口: type 错 → ValueError(编程错误, 透传)

    Raises:
        ValueError: 长度越界 / type 错 / 纯空白
    """
    if type(body) is not str:
        raise ValueError(f"body 必须是 str, 实际 {type(body).__name__}={body!r}")
    if len(body) < EmailDrafter.MIN_DRAFT_BODY_CHARS:
        raise ValueError(f"body 太短(契约 1): {len(body)} < {EmailDrafter.MIN_DRAFT_BODY_CHARS}")
    if len(body) > EmailDrafter.MAX_DRAFT_BODY_CHARS:
        raise ValueError(f"body 太长(契约 1): {len(body)} > {EmailDrafter.MAX_DRAFT_BODY_CHARS}")
    # 6/9 v1.0.2 P1-2 修复: strip() 语义非空校验, 拒纯空白 body
    if not body.strip():
        raise ValueError(f"body 语义为空(仅空白字符, 契约 1): {body!r}")


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

# D4.7 契约 2 修复史(2026-06-09 三轮迭代):
#   v1.0 P0: 正则整段扫描 fence → 误杀 body 内的 ```python ... ``` 围栏
#   v1.0.1 P1-2: 优先 json.loads 整段, 失败回退平衡括号定位 → 仍接受 prose 包装
#   v1.0.2 P1(检查员第二次复检): 删除平衡括号兜底, **只允许 json.loads(stripped)**
#     - LLM 必须返回"裸 JSON"(无 prose / 无外层 fence / 无前后说明文字)
#     - 整段 load 失败 + 外层 fence → 拒收(reason=markdown_fenced_outer)
#     - 整段 load 失败 + 无外层 fence → 拒收(reason=json_decode_error)
#     - body 字段内允许 markdown(包括 code fence), 因为 body 是字符串内容
# 决择依据: 契约 2 "LLM 响应必须为裸 JSON" 严格落实, 避免"提示工程漂移"


def _has_outer_markdown_fence(raw: str) -> bool:
    """检测 raw 是否被外层 markdown fence 包裹(契约 2).

    判定: stripped 内容以 ``` 开头 AND 以 ``` 结尾(允许前后空行)。
    不再扫描内部任意位置的 fence(避免误杀 body 字段内的 code fence)。

    Args:
        raw: LLM 原始响应

    Returns:
        True = 外层被 fence 包裹(契约 2 拒收)
        False = 无外层包裹(继续走整段 JSON 解析)
    """
    if type(raw) is not str:
        return False  # 留到 _parse_draft_response 上层抛 type 错
    stripped = raw.strip()
    return stripped.startswith("```") and stripped.endswith("```")


# ===== 严判解析主函数(契约 2 拒外层 fence + 契约 3 tone 严判 + P1-3 强制)=====


def _parse_draft_response(
    content: Any,
    *,
    expected_tone: DraftTone | None = None,
) -> tuple[str, str, DraftTone]:
    """严判解析 LLM 草稿响应, 返回 (subject, body, tone).

    解析策略(D4.7 4 项契约 + 6/9 P1 + P2-1 应用):
      1. type() 严判 content 是 str
      2. 入口严判 expected_tone: 仅接受 DraftTone | None(6/9 P2-1 修复)
      3. **裸 JSON 契约**: 只执行 `json.loads(content.strip())` 整段解析
         (不允许 prose / 不允许外层 fence / 不允许平衡括号兜底)
      4. 整段解析失败 → 检测外层 fence 包裹 → 拒收(reason=markdown_fenced_outer)
         或 拒收(reason=json_decode_error)
      5. 严判结构(必须 dict) + 严判 subject / body / tone 字段类型与值
      6. **P1-3 强制**: 若传入 expected_tone, 返回 tone 必须 == expected_tone

    任何一步失败 → DrafterResponseError(业务异常, 可重试).
    编程错误(KeyError/TypeError 等在解析前) → 透传(不在本函数包装).

    Args:
        content: LLM 原始响应
        expected_tone: 请求的语气(6/9 P1-3 新增, 强制 LLM 返回一致 tone;
                       6/9 P2-1 修复: 仅接受 DraftTone | None, 非法值 ValueError)
    """
    # P2-1 修复(6/9): 入口严判 expected_tone, 防止 "OOPS" / 123 等泄漏到 .value 抛 AttributeError
    if expected_tone is not None and not isinstance(expected_tone, DraftTone):
        raise ValueError(
            f"expected_tone 必须是 DraftTone 枚举或 None, "
            f"实际 {type(expected_tone).__name__}={expected_tone!r}"
        )

    if type(content) is not str:
        raise DrafterResponseError(
            "LLM content 必须是 str",
            raw_content=str(content),
            reason=f"type={type(content).__name__}",
        )

    # 契约 2 (6/9 v1.0.2 P1 修复): **只允许裸 JSON**
    # - 整段 json.loads(stripped) 是唯一解析路径
    # - 整段失败 + 外层 fence → 拒收(reason=markdown_fenced_outer)
    # - 整段失败 + 无外层 fence → 拒收(reason=json_decode_error)
    # - 删除 v1.0.1 的"平衡括号兜底": 该兜底接受 prose 包装的 JSON,
    #   与锁定契约"无其他文字"冲突
    # - body 字段内的 markdown(含 code fence)仍然允许, 因为 body 是字符串内容
    stripped = content.strip()
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError) as parse_err:
        # 整段不是合法 JSON → 检测是否被外层 fence 包裹(便于运维定位)
        if _has_outer_markdown_fence(content):
            raise DrafterResponseError(
                "LLM 响应被外层 markdown fence 包裹(契约 2: 拒收, 不剥离)",
                raw_content=content,
                reason="markdown_fenced_outer",
            ) from parse_err
        # 裸 JSON 契约: 不容错, 不兜底, 整段 load 失败即拒
        raise DrafterResponseError(
            f"LLM 响应不是合法裸 JSON(契约 2): {parse_err}",
            raw_content=content,
            reason=f"json_decode_error={type(parse_err).__name__}",
        ) from parse_err

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
    "SpamBlockedError",
    "DraftResult",
    "DraftBlockedResult",
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
