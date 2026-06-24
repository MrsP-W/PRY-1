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

D4.6 v1.0.1 修复(D4.6 复检 P1-1 + P1-4):
  - P1-1 旁路:Classifier `except LLMError` 自动覆盖 LLMAllFallbacksError
    (router 抛,不再逃逸)
  - P1-4: 解析用平衡括号定位 JSON(原正则强制 category→confidence 字段顺序,
    反序 JSON 误拒;允许 markdown 包裹但显式剥离 fence);
    `math.isfinite()` 拒 NaN/Inf(原范围检查 0<=x<=1 NaN 通过)

D4.6 v1.0.2 修复(D4.6 6/9 复检 P2-3 + P2-4):
  - P2-3: `_extract_balanced_json` 扫描所有平衡 JSON 块,选第一个同时含
    `category` + `confidence` 字段的(原 v1.0.1 只取第一个平衡 JSON,若 LLM
    输出前面有无关对象 `{"debug": "info"}`,后面才是分类结果,合法结果被拒)
  - P2-4: `classify_batch` type hint 补 `ValueError | KeyError`;`email[k]`
    KeyError 不外抛终止整批,改为入 results 列表
"""

from __future__ import annotations

import json
import math
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
    业务层做"按类别分组"时可直接用 `list[Any](EmailCategory)` 排序。
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
        """序列化为 dict[Any, Any](便于 JSON 化)."""
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
        return dict[Any, Any](self._stats)

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
        emails: list[dict[Any, Any]],
    ) -> list[ClassificationResult | ClassifierResponseError | LLMError | ValueError | KeyError]:
        """批量分类(顺序串行, 避免触发熔断).

        Args:
            emails: list[dict[Any, Any]], 每条 dict[Any, Any] 必须包含 subject/sender/body_excerpt 3 key
                   (类型不匹配 / 缺字段 → 异常入 results, 不静默吞掉, 不外抛)

        Returns:
            list[ClassificationResult | 异常],与 emails 1:1 对齐
              - 成功: ClassificationResult
              - 响应解析失败: ClassifierResponseError
              - LLM 全链失败: LLMError
              - 编程错误(非 dict[Any, Any]): ValueError
              - 编程错误(缺字段): KeyError
            异常透传,不静默吞掉(D3.3.3 教训)。
            D4.6 v1.0.2 P2-4: 补 ValueError | KeyError 到 type hint(原版只标 3 类,
            实际 ValueError 已入 list[Any], type hint 与实现不一致; KeyError 之前
            会终止整批)。
        """
        results: list[
            ClassificationResult | ClassifierResponseError | LLMError | ValueError | KeyError
        ] = []
        for i, email in enumerate(emails):
            if not isinstance(email, dict):
                results.append(
                    ValueError(f"emails[{i}] 必须是 dict[Any, Any], 实际 {type(email).__name__}")
                )
                continue
            # D4.6 v1.0.2 P2-4: 缺字段时 KeyError 收容入 list[Any](原版 email[k] 抛
            # KeyError 会终止整批,违反"单条异常不阻塞"契约)
            missing_keys = [k for k in ("subject", "sender", "body_excerpt") if k not in email]
            if missing_keys:
                results.append(KeyError(f"emails[{i}] 缺字段 {missing_keys}"))
                continue
            try:
                result = self.classify(
                    subject=email["subject"],
                    sender=email["sender"],
                    body_excerpt=email["body_excerpt"],
                )
                results.append(result)
            except (ClassifierResponseError, LLMError, ValueError) as e:
                results.append(e)
        return results


# ===== 模块内辅助函数 =====


def system_to_message(content: str) -> dict[Any, Any]:
    """把 system prompt 字符串转 OpenAI 风格 message dict[Any, Any].

    严判: content 必须是原生 str(D4.5 P0 教训应用)。
    """
    if type(content) is not str or not content:
        raise ValueError(f"system content 必填非空 str, 实际 {type(content).__name__}")
    return {"role": "system", "content": content}


# 5 类枚举值集合(用于响应解析的 O(1) 校验,避免每次 O(5) 遍历)
_VALID_CATEGORIES: frozenset[str] = frozenset(c.value for c in EmailCategory)

# D4.6 v1.0.1 P1-4 修复: 改用平衡括号定位 JSON
# 旧版正则强制 category→confidence 字段顺序,反序合法 JSON 误拒
# 新版扫描所有 { ... } 候选,选最外层平衡的 + 含 category+confidence 字段
# 复杂度 O(N) 但响应通常 < 200 字符,实测无差


def _strip_markdown_fence(raw: str) -> str:
    """显式剥 markdown code fence(```json ... ```),返回剥后内容.

    D4.6 v1.0.1 P1-4 修复: 旧版靠 strip() 隐式容忍,新版本显式处理:
      - ```json ... ```
      - ``` ... ```
      - 首尾空白
    不存在 fence 时原样返回。
    """
    stripped = raw.strip()
    # 匹配 ```[可选语言] 开头到 ``` 结尾(可能跨行)
    fence_match = re.match(r"^```(?:json|JSON)?\s*\n?(.*?)\n?```\s*$", stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def _find_all_balanced_json(raw: str) -> list[str]:
    """扫描 raw, 返回所有平衡的 { ... } 块文本列表(不含外层字符).

    平衡括号扫描: 跟踪 { 与 } 嵌套深度,忽略字符串内 / 转义后的括号.
    D4.6 v1.0.2 P2-3 修复: 从"找第一个平衡 JSON"升级为"找所有平衡 JSON",
    便于 _extract_balanced_json 在多个候选中选含 category+confidence 字段的。
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


def _extract_balanced_json(raw: str) -> str | None:
    """扫描 raw, 返回第一个同时含 category+confidence 字段的平衡 JSON 块文本.

    D4.6 v1.0.1 P1-4: 不再强制字段顺序,允许 LLM 输出
      `{"confidence":0.8,"category":"URGENT"}` 等任意字段顺序。
    D4.6 v1.0.2 P2-3: 进一步扫描所有平衡 JSON 块,选第一个同时含
      `category` + `confidence` 字段的(避免前面无关对象 {`debug`} 遮蔽分类结果)。

    兜底: 若所有块都不含 category+confidence, 返回第一个平衡 JSON(原 v1.0.1 行为)。
    全部无平衡 JSON 时返回 None(上层抛 no_balanced_json)。
    """
    blocks = _find_all_balanced_json(raw)
    for block in blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and "category" in data and "confidence" in data:
            return block
    return blocks[0] if blocks else None


def _parse_classification_response(content: str) -> tuple[EmailCategory, float]:
    """严判解析 LLM 响应, 返回 (EmailCategory, confidence).

    解析策略(D4.6 v1.0.1 P1-4 修复版):
      1. type() 严判 content 是 str
      2. 显式剥 markdown fence(```json ... ```)
      3. 平衡括号定位最外层 { ... }(允许任意字段顺序)
      4. json.loads 严格解析(必须是 dict[Any, Any])
      5. 严判 "category" 字段: 必须是 str, 必须 ∈ _VALID_CATEGORIES
      6. 严判 "confidence" 字段: type() is int/float(拒 bool)+ math.isfinite() + 0-1 范围

    任何一步失败 → ClassifierResponseError(业务异常, 可重试).
    编程错误(KeyError/TypeError 等在解析前) → 透传(不在本函数包装).
    """
    if type(content) is not str:
        raise ClassifierResponseError(
            "LLM content 必须是 str",
            raw_content=str(content),
            reason=f"type={type(content).__name__}",
        )

    # 1. 显式剥 markdown fence
    raw = _strip_markdown_fence(content)

    # 2. 平衡括号定位 JSON
    json_text = _extract_balanced_json(raw)
    if json_text is None:
        raise ClassifierResponseError(
            "未找到平衡的 JSON 块",
            raw_content=raw,
            reason="no_balanced_json",
        )

    # 3. 严格 JSON 解析
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError) as e:
        raise ClassifierResponseError(
            f"JSON 解析失败: {e}",
            raw_content=raw,
            reason=f"json_decode_error={type(e).__name__}",
        ) from e

    # 4. 严判结构(必须是 dict[Any, Any])
    if not isinstance(data, dict):
        raise ClassifierResponseError(
            "JSON 顶层必须是 object",
            raw_content=raw,
            reason=f"top_level_type={type(data).__name__}",
        )

    # 5. 严判 category 字段
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

    # 6. 严判 confidence 字段(D4.6 v1.0.1 P1-4 修复)
    # - 拒 bool 子类陷阱(D4.4 P1 教训)
    # - math.isfinite() 拒 NaN/Inf(NaN 任何比较返回 False,原范围检查漏过)
    confidence_raw = data.get("confidence")
    if type(confidence_raw) is bool or not isinstance(confidence_raw, (int, float)):
        raise ClassifierResponseError(
            "confidence 字段必须是数字(非 bool)",
            raw_content=raw,
            reason=f"confidence_type={type(confidence_raw).__name__}",
        )
    confidence = float(confidence_raw)
    if not math.isfinite(confidence):
        raise ClassifierResponseError(
            f"confidence 必须是有限数字(非 NaN/Inf): {confidence}",
            raw_content=raw,
            reason=f"confidence_not_finite={confidence}",
        )
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
