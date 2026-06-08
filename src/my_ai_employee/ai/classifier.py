"""D4.6 — 邮件分类器(5 类标签).

设计要点:

  - 复用 D4.1.1 LLM Router:`router.route(TaskType.CLASSIFY, messages)` 自动走
    DeepSeek → Qwen → M3 fallback 链(`fallback.FALLBACK_CHAINS` 已配)
  - 严判 LLM 响应:必须严格 JSON `{"category": "<枚举>", "confidence": <float>}`
    - 字段缺 / 类型错 / category 不在 5 类 → 抛 ClassifierResponseError
    - 编程错误(type/ValueError) 透传(D3.3.3 教训:不 catch-all 兜底)
  - 批量:`classify_batch` 顺序串行(避免触发熔断/雪崩,D4.6.1+ 改并发)
  - 不写 DB / 不接 events / 不接 policy(本步只做"分类决策"原子能力)

D5+ 业务层接入用 `EmailClassifierAdapter`(`policy/integration.py` 新增),
把分类结果(类别 + 置信度)封装成 TaskPacket 喂 PolicyEngine,落 events + lane,
沿用 D4.5 `SyncPolicyAdapter` 4 依赖范本。

参考 D3.3.3 教训("异常范围要窄化"):
  - ClassifierResponseError 是业务异常(LLM 输出脏),由调用方决定重试
  - 编程错误(参数 type 错) → ValueError 透传,不在本模块包装
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger

from .capability import TaskType
from .providers import LLMError
from .router import LLMRouter, get_router


class EmailCategory(StrEnum):
    """5 类邮件标签(StrEnum, 与 LLM 输出严格 1:1).

    顺序固定(URGENT → TODO → FYI → SPAM → PERSONAL),
    业务层做"按类别分组"时可直接用 `list(EmailCategory)` 排序。
    """

    URGENT = "URGENT"
    TODO = "TODO"
    FYI = "FYI"
    SPAM = "SPAM"
    PERSONAL = "PERSONAL"


# ===== 业务异常(D3.3.3 教训:窄化异常范围)=====


class ClassifierError(Exception):
    """邮件分类器业务异常基类."""


class ClassifierResponseError(ClassifierError):
    """LLM 响应解析失败(非严格 JSON / category 不在 5 类 / 字段类型错).

    Attributes:
        raw_content: LLM 原始输出(便于排查)
        reason: 解析失败原因
    """

    def __init__(self, message: str, raw_content: str = "", reason: str = "") -> None:
        super().__init__(message)
        self.raw_content = raw_content[:500]
        self.reason = reason


# ===== 分类结果数据类 =====


@dataclass(frozen=True)
class ClassificationResult:
    """单邮件分类结果.

    Attributes:
        category: 5 类之一(EmailCategory 枚举)
        confidence: 置信度 [0.0, 1.0](LLM 输出,严判 0<=x<=1)
        model_full_id: 实际调用的 provider/model(便于审计/计费)
        latency_ms: 单次分类耗时
        raw_content: LLM 原始响应(便于排查,截断到 500 字符)
    """

    category: EmailCategory
    confidence: float
    model_full_id: str
    latency_ms: int
    raw_content: str

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict(便于 JSON 化)."""
        return {
            "category": self.category.value,
            "confidence": self.confidence,
            "model_full_id": self.model_full_id,
            "latency_ms": self.latency_ms,
            "raw_content": self.raw_content,
        }


# ===== 分类器主类 =====


class EmailClassifier:
    """邮件分类器(D4.6 主类).

    用法:

        from my_ai_employee.ai import EmailClassifier, EmailCategory
        from my_ai_employee.ai.router import get_router

        router = get_router()
        classifier = EmailClassifier(router=router)
        result = classifier.classify(
            subject="[紧急] 客户投诉",
            sender="client@example.com",
            body_excerpt="订单 #1234 严重延迟...",
        )
        assert result.category == EmailCategory.URGENT
        assert result.confidence > 0.8

    设计:
      - router 可注入(测试时传 mock router, 生产传 get_router() 单例)
      - 严判响应(JSON 解析 + 5 类枚举 + 置信度范围)
      - 不写 DB / 不接 events(纯决策能力)
    """

    # body_excerpt 最大长度(防止巨型正文把 prompt 撑爆)
    MAX_BODY_CHARS = 2000

    def __init__(
        self,
        *,
        router: LLMRouter | None = None,
        max_tokens: int = 64,
    ) -> None:
        """初始化分类器.

        Args:
            router: LLM 路由器(默认 get_router() 单例)
            max_tokens: 输出上限(分类只需短响应,默认 64 足够)
        """
        self._router = router or get_router()
        self._max_tokens = max_tokens
        # 运行时统计(可观测性, 类似 RouterStats)
        self._stats: dict[str, int] = {
            "total": 0,
            "success": 0,
            "response_error": 0,
            "llm_error": 0,
        }

    def stats(self) -> dict[str, int]:
        """返回分类器统计(便于 mmx policy status 等可观测性子命令)."""
        return dict(self._stats)

    def classify(
        self,
        *,
        subject: str,
        sender: str,
        body_excerpt: str,
    ) -> ClassificationResult:
        """单邮件分类.

        Args:
            subject: 邮件主题(允许空字符串)
            sender: 发件人(允许空字符串)
            body_excerpt: 正文前 N 字符(> MAX_BODY_CHARS 时截断)

        Returns:
            ClassificationResult(含 5 类枚举 + 置信度 + 调用模型)

        Raises:
            ValueError: 参数 type 错(编程错误, 透传)
            ClassifierResponseError: LLM 响应解析失败(非严格 JSON / category 不在 5 类)
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

        # 正文截断(防御巨型 body)
        if len(body_excerpt) > self.MAX_BODY_CHARS:
            body_excerpt = body_excerpt[: self.MAX_BODY_CHARS]

        self._stats["total"] += 1

        # 构造 prompt(延迟 import 避免 prompts 包 init 时的循环)
        from .prompts.classify import SYSTEM_PROMPT, build_user_message

        messages = [
            system_to_message(SYSTEM_PROMPT),
            *build_user_message(
                subject=subject,
                sender=sender,
                body_excerpt=body_excerpt,
            ),
        ]

        # 调 router(走 fallback 链,熔断隔离, 单例统计)
        try:
            response = self._router.route(
                task_type=TaskType.CLASSIFY,
                messages=messages,
                temperature=0.1,  # 分类任务: 低温保稳定
                max_tokens=self._max_tokens,
            )
        except LLMError as e:
            self._stats["llm_error"] += 1
            logger.warning(f"[classifier] LLM 全链失败 | subject={subject!r} | err={e!r}")
            raise

        # 严判响应(D4.6 严判入口)
        try:
            category, confidence = _parse_classification_response(response.content)
        except ClassifierResponseError as e:
            self._stats["response_error"] += 1
            logger.warning(
                f"[classifier] 响应解析失败 | subject={subject!r} | "
                f"reason={e.reason} | raw={e.raw_content!r}"
            )
            raise

        self._stats["success"] += 1
        return ClassificationResult(
            category=category,
            confidence=confidence,
            model_full_id=response.model_full_id,
            latency_ms=response.latency_ms,
            raw_content=response.content,
        )

    def classify_batch(
        self,
        emails: list[dict],
    ) -> list[ClassificationResult | ClassifierResponseError | LLMError]:
        """批量分类(顺序串行, 避免触发熔断).

        Args:
            emails: list[dict], 每条 dict 必须包含 subject/sender/body_excerpt 3 key
                   (类型不匹配抛 ValueError, 不静默 coerce)

        Returns:
            list[ClassificationResult | 异常],与 emails 1:1 对齐
              - 成功: ClassificationResult
              - 响应解析失败: ClassifierResponseError
              - LLM 全链失败: LLMError
            异常透传,不静默吞掉(D3.3.3 教训)
        """
        results: list[ClassificationResult | ClassifierResponseError | LLMError] = []
        for i, email in enumerate(emails):
            if not isinstance(email, dict):
                results.append(ValueError(f"emails[{i}] 必须是 dict, 实际 {type(email).__name__}"))
                continue
            try:
                result = self.classify(
                    subject=email["subject"],
                    sender=email["sender"],
                    body_excerpt=email["body_excerpt"],
                )
                results.append(result)
            except (ClassifierResponseError, LLMError) as e:
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


# 5 类枚举值集合(用于响应解析的 O(1) 校验,避免每次 O(5) 遍历)
_VALID_CATEGORIES: frozenset[str] = frozenset(c.value for c in EmailCategory)

# 5 类 JSON 严格正则(双引号 + category 在枚举中 + 0-1 浮点)
# 允许 LLM 在 JSON 前后加少量 markdown(实测很多模型会包 ```json),先 strip 再验
_JSON_PATTERN = re.compile(r"\{[^{}]*\"category\"[^{}]*\"confidence\"[^{}]*\}")


def _parse_classification_response(content: str) -> tuple[EmailCategory, float]:
    """严判解析 LLM 响应, 返回 (EmailCategory, confidence).

    解析策略(防御性, 不假设 LLM 一定输出干净 JSON):
      1. type() 严判 content 是 str
      2. 用正则提取最外层 { ... }(允许 LLM 包 markdown)
      3. json.loads 严格解析(必须是 dict)
      4. 严判 "category" 字段: 必须是 str, 必须 ∈ _VALID_CATEGORIES
      5. 严判 "confidence" 字段: 必须是 float/int(0-1 范围)

    任何一步失败 → ClassifierResponseError(业务异常, 可重试).
    编程错误(KeyError/TypeError 等在解析前) → 透传(不在本函数包装).
    """
    if type(content) is not str:
        raise ClassifierResponseError(
            "LLM content 必须是 str",
            raw_content=str(content),
            reason=f"type={type(content).__name__}",
        )

    raw = content.strip()

    # 1. 提取 JSON 块(去掉 markdown 包裹)
    match = _JSON_PATTERN.search(raw)
    if match is None:
        raise ClassifierResponseError(
            "未找到 JSON 块(需含 category + confidence 字段)",
            raw_content=raw,
            reason="no_json_block",
        )
    json_text = match.group(0)

    # 2. 严格 JSON 解析
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ClassifierResponseError(
            f"JSON 解析失败: {e}",
            raw_content=raw,
            reason=f"json_decode_error={type(e).__name__}",
        ) from e

    # 3. 严判结构(必须是 dict)
    if not isinstance(data, dict):
        raise ClassifierResponseError(
            "JSON 顶层必须是 object",
            raw_content=raw,
            reason=f"top_level_type={type(data).__name__}",
        )

    # 4. 严判 category 字段
    category_raw = data.get("category")
    if not isinstance(category_raw, str):
        raise ClassifierResponseError(
            "category 字段必须是 str",
            raw_content=raw,
            reason=f"category_type={type(category_raw).__name__}",
        )
    if category_raw not in _VALID_CATEGORIES:
        raise ClassifierResponseError(
            f"category 值不在 5 类枚举中: {category_raw!r}",
            raw_content=raw,
            reason=f"invalid_category={category_raw}",
        )
    category = EmailCategory(category_raw)  # 此时一定成功

    # 5. 严判 confidence 字段(0-1 范围, 拒 bool 子类陷阱:D4.4 P1 教训)
    confidence_raw = data.get("confidence")
    if type(confidence_raw) is bool or not isinstance(confidence_raw, (int, float)):
        raise ClassifierResponseError(
            "confidence 字段必须是 0-1 的数字(非 bool)",
            raw_content=raw,
            reason=f"confidence_type={type(confidence_raw).__name__}",
        )
    confidence = float(confidence_raw)
    if confidence < 0.0 or confidence > 1.0:
        raise ClassifierResponseError(
            f"confidence 超出 0-1 范围: {confidence}",
            raw_content=raw,
            reason=f"confidence_out_of_range={confidence}",
        )

    return category, confidence


# ===== 模块导出 =====


__all__ = [
    "EmailCategory",
    "EmailClassifier",
    "ClassificationResult",
    "ClassifierError",
    "ClassifierResponseError",
]
