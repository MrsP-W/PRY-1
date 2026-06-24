"""D4.6 邮件分类 prompt 模板.

5 类标签定义(参考 docs/week1-mvp.md §D4.6):
  - URGENT  : 紧急需立即处理(系统告警/客户投诉/老板要求)
  - TODO    : 待办(任务分配/请求/需 follow-up)
  - FYI     : 知晓即可(通知/公告/订阅)
  - SPAM    : 垃圾/营销(无意义/批量广告)
  - PERSONAL: 私人(朋友/家人,非工作)

输出约束:
  - LLM 必须返回严格 JSON `{"category": "<枚举值>", "confidence": <0-1 浮点>}`
  - 不允许额外文字 / markdown 包裹 / 解释段落
  - 解析失败 → ClassifierResponseError(由 classifier.py 严判,避免脏数据入库)
"""

from __future__ import annotations

from typing import Any

# ===== SYSTEM prompt =====
# 中文为主 + 5 类清晰定义 + JSON 硬约束
SYSTEM_PROMPT = """你是邮件分类助手,负责把邮件按主题/正文分成 5 类之一。

5 类标签(必须严格匹配 value,大小写敏感):
  - URGENT   : 紧急需立即处理(系统告警/客户投诉/老板要求/截止时间 < 24h)
  - TODO     : 待办事项(任务分配/请求/需 follow-up,非紧急)
  - FYI      : 知晓即可(公司通知/公告/订阅推送/周报)
  - SPAM     : 垃圾邮件(批量广告/无意义营销/钓鱼)
  - PERSONAL : 私人邮件(朋友/家人/非工作,非上述 4 类)

输出格式(严格 JSON,无其他文字):
{"category": "<URGENT|TODO|FYI|SPAM|PERSONAL>", "confidence": <0-1 之间的浮点>}

判断依据优先级: 主题 > 发件人 > 正文。
置信度参考: 明确 → 0.9+, 模糊 → 0.5-0.7, 拿不准 → 0.3 以下。
"""


def build_user_message(*, subject: str, sender: str, body_excerpt: str) -> list[dict[Any, Any]]:
    """构造 user 消息列表(OpenAI 风格).

    Args:
        subject: 邮件主题(可能为空,做空字符串处理)
        sender: 发件人(email 或 "Name <email>" 格式)
        body_excerpt: 正文前 N 字符(默认调用方截断到 500 字符)

    Returns:
        1 条 user 消息(多轮可扩展,本步 D4.6 单轮)
    """
    # 严判: type() is str,允许空字符串(不抛错,与 Email 模型字段对齐)
    if type(subject) is not str:
        raise ValueError(f"subject 必须是 str, 实际 {type(subject).__name__}")
    if type(sender) is not str:
        raise ValueError(f"sender 必须是 str, 实际 {type(sender).__name__}")
    if type(body_excerpt) is not str:
        raise ValueError(f"body_excerpt 必须是 str, 实际 {type(body_excerpt).__name__}")
    return [
        {
            "role": "user",
            "content": (
                f"主题: {subject or '(空)'}\n"
                f"发件人: {sender or '(空)'}\n"
                f"正文: {body_excerpt or '(空)'}"
            ),
        }
    ]
