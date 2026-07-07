"""D14+ LLM 草稿安全护栏(撞坑 #85 三层防御 · Layer 1)。

设计动机(2026-07-07,撞坑 #85 暴露):
    - 阶段 2.3 `process_inbox --execute --limit 10` 后,outbox 入了 2 封 LLM
      幻觉草稿,收件人是 `root@systemmail.yunwu.ai`,主题"紧急 API 服务异常需立即
      处理",原邮件 `emails.id=10, 11` 的 sender 就是 `root@systemmail.yunwu.ai`
      (典型 server-side spoofing),body 空。
    - 撞坑 #76 严判 `pending_send` 严格小写 + `last_approved_at_ms` 必传规则
      都通过,但**撞坑 #76 只防"审批伪造",不防"LLM 草稿内容本身的不可信"**。
    - LLM hallucination 链路:
        1. 分类器把"紧急 API 服务异常通知" + body 空 + system sender 误判 TODO
        2. process_inbox 用 `sender` 当 `recipient_email` 直接入 outbox
        3. send_one_approved `--recipient` 严判 OK,但用户需主动传对白名单值
    - 缺口: 分类器没拦"system sender + 紧急主题 + 空 body" 三联信号。

Layer 1 职责(本模块):
    - 提供纯函数 `is_obvious_spam(sender, subject, body_excerpt)` 给分类器入口短路
      (不调 LLM,直接返 `ClassificationResult(category=SPAM, confidence=0.99, ...)`)。
    - 提供纯函数 `is_system_sender(sender)` 给 process_inbox.py Layer 2 短路
      (撞坑 #85 暴露后,Drafter SpamBlockedError 不足以覆盖"system sender +
      分类非 SPAM 仍走 TODO"路径)。

设计原则:
    - **纯函数**: 无副作用,无 LLM 调用,无 DB 操作。
    - **严判入口**: `type() is str` 严判(type 错 → ValueError,沿 D4.4 P1 范本)。
    - **白名单前置**: 黑名单常量冻结(frozenset / tuple),不依赖外部配置。
    - **可审计**: 返回 bool 而非抛异常(业务层决定如何处置)。

范本参考:
    - 撞坑 #76: outbox status 严格小写 + 防审批伪造
    - D4.6 v1.0.2 P1-4: 解析器严判入口 type() is str
    - D4.7.2 v1.0.2 P1-1: SPAM 业务硬阻断(本模块扩展)

不在本模块范围:
    - 不调 LLM(纯函数,no side effect)
    - 不写 DB / 不接 events
    - 不做白名单 domain 校验(留给 Layer 3 send_one_approved env 门控)
"""

from __future__ import annotations

# ===== 撞坑 #85 黑名单常量(冻结,O(1) 查询)=====

# System-style 本地名(典型 server-side spoofing / noreply 攻击向量)
# 业务语义: 这类邮箱不应作为"收件人"(无真人接管),也不应作为"发件人"信任源。
# 撞坑 #85 案例: root@systemmail.yunwu.ai(攻击向量),noreply@*.example.com(批量)
_SYSTEM_SENDER_LOCALPARTS: frozenset[str] = frozenset(
    {
        # Unix / server classic
        "root",
        "postmaster",
        "abuse",
        "admin",
        "administrator",
        "system",
        # noreply 系列(批量通知 / 营销 / 钓鱼)
        "noreply",
        "no-reply",
        "no_reply",
        "donotreply",
        "do-not-reply",
        # 自动告警 / 通知
        "alerts",
        "alert",
        "notifications",
        "notification",
        "support",
        "help",
        "info",
        "service",
        "operations",
        "ops",
    }
)

# 主题黑名单词(撞坑 #85 案例: "紧急 API 服务异常需立即处理" / "您的账户异常登录")
# 设计动机: 仅在 body 极短/空 时触发(避免误杀"客户紧急投诉"等真实 URGENT 邮件)
# 双信号严判(黑名单词 + body 空)防止 LLM 单信号误判。
_OBVIOUS_SPAM_SUBJECT_KEYWORDS: tuple[str, ...] = (
    # 中文
    "紧急",
    "API 异常",
    "服务异常",
    "账户异常",
    "登录异常",
    "立即处理",
    "立即修复",
    "系统异常",
    "安全告警",
    "密码过期",
    "账户锁定",
    # 英文(常见 phishing)
    "verify",
    "urgent",
    "suspend",
    "suspended",
    "locked",
    "unlock",
    "confirm your account",
    "action required",
)

# 主题黑名单词命中所需的 body 长度上限(字符)
# 设计: < 30 字符视为"裸主题 spam"(真实业务邮件 body 通常 > 30 字符)
_BODY_EXCERPT_SHORT_THRESHOLD = 30


# ===== 纯函数 1: is_system_sender(供 process_inbox Layer 2 短路用)=====


def is_system_sender(sender: str) -> bool:
    """判定发件人是否 system-style 本地名(撞坑 #85 攻击向量)。

    Args:
        sender: 发件人 email(如 "root@systemmail.yunwu.ai" / "Alice <a@b.com>")
                仅取 `@` 之前的 localpart 严判,大小写不敏感。

    Returns:
        True = system-style(无真人接管,典型 server-side spoofing / noreply)
        False = 普通用户邮箱

    Raises:
        ValueError: sender 不是 str(编程错误,透传)

    严判范本(D4.4 P1):
        - type() is str(拒 bool 子类陷阱)
        - localpart 取 `@` 前部分(容错 "<Name <a@b.com>>" 嵌套用 rsplit 一次)
        - lower() + strip() 大小写不敏感
    """
    if type(sender) is not str:
        raise ValueError(f"sender 必须是 str, 实际 {type(sender).__name__}={sender!r}")

    # 防御嵌套格式 "Alice <a@b.com>": 先去掉 "<...>" 部分
    cleaned = sender.strip()
    if "<" in cleaned and ">" in cleaned:
        # 取 <> 内部分
        start = cleaned.find("<")
        end = cleaned.find(">", start)
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start + 1 : end].strip()

    # 取 localpart(防御 "a@b@c" 这种异常输入,rsplit 一次)
    local = cleaned.rsplit("@", 1)[0].strip().lower() if "@" in cleaned else cleaned.lower().strip()

    return local in _SYSTEM_SENDER_LOCALPARTS


# ===== 纯函数 2: is_obvious_spam(供 classifier Layer 1 短路用)=====


def is_obvious_spam(*, sender: str, subject: str, body_excerpt: str) -> bool:
    """判定邮件是否"明显 spam"(撞坑 #85 Layer 1 分类器短路)。

    触发条件(双信号,任一命中即返 True):
      A. **system-style sender**(撞坑 #85 案例 root@systemmail.yunwu.ai)
         → 不管主题/正文,直接返 True(典型 server-side spoofing 攻击向量)
      B. **主题黑名单词 + body 极短/空**(撞坑 #85 案例"紧急 API 服务异常需立即处理"
         body 空 → 主题黑名单词"紧急"+"API"+"立即处理"命中)
         → 防御"看似真实主题但 body 空"的 phishing/spam

    Args:
        sender: 发件人 email
        subject: 邮件主题
        body_excerpt: 正文前 N 字符(允许空字符串)

    Returns:
        True = 明显 spam(分类器应短路返 SPAM,不走 LLM)
        False = 不命中,需走 LLM 5 类分类

    Raises:
        ValueError: 任一参数不是 str(编程错误,透传)

    设计说明:
        - system-style sender 单独判定(不依赖 body/主题),因为典型 phishing
          攻击者会用真实主题掩盖 system sender 信号。
        - 主题黑名单词 + body 极短是双信号(防误杀"客户紧急投诉"等真实 URGENT,
          真实 URGENT 通常 body > 30 字符有上下文)。
        - 不在本函数调 LLM(纯函数,零延迟,零配额)。
    """
    if type(sender) is not str:
        raise ValueError(f"sender 必须是 str, 实际 {type(sender).__name__}={sender!r}")
    if type(subject) is not str:
        raise ValueError(f"subject 必须是 str, 实际 {type(subject).__name__}={subject!r}")
    if type(body_excerpt) is not str:
        raise ValueError(
            f"body_excerpt 必须是 str, 实际 {type(body_excerpt).__name__}={body_excerpt!r}"
        )

    # 信号 A: system-style sender(无条件短路,撞坑 #85 root@systemmail 案例)
    if is_system_sender(sender):
        return True

    # 信号 B: 主题黑名单词 + body 极短(< 30 字符视为"裸主题 spam")
    body_clean = body_excerpt.strip()
    if len(body_clean) < _BODY_EXCERPT_SHORT_THRESHOLD:
        subject_lower = subject.lower()
        for kw in _OBVIOUS_SPAM_SUBJECT_KEYWORDS:
            if kw.lower() in subject_lower:
                return True

    return False


# ===== 模块导出 =====

__all__ = [
    "is_obvious_spam",
    "is_system_sender",
    "_SYSTEM_SENDER_LOCALPARTS",  # 测试用
    "_OBVIOUS_SPAM_SUBJECT_KEYWORDS",  # 测试用
    "_BODY_EXCERPT_SHORT_THRESHOLD",  # 测试用
]
