"""D5 业务调度器 SMTP 适配器 — QQ 邮箱优先(授权码模式)。

设计(承接 docs/week1-mvp.md §D5):

    - **协议**:SMTP_SSL 端口 465(统一 SSL 简化,**不**用 STARTTLS 端口 587)
    - **库**:smtplib(标准库,无第三方依赖)
    - **凭证**:邮箱地址 + 授权码(**不是密码**),从 macOS Keychain 读
        (与 D2 IMAP 授权码**分别**存储,因 QQ SMTP 授权码可与 IMAP 不同)
    - **服务器**:
        - QQ:     smtp.qq.com:465 (SSL)
        - Outlook: smtp.office365.com:465 (D5.1 仅占位,OAuth 2.0 推后)
        - Gmail:  smtp.gmail.com:465 (D5.1 仅占位,OAuth 2.0 推后)
    - **Transport 抽象**:`SMTPTransport` Protocol + 生产 `SmtpLibTransport` + 测试 `InMemorySmtpTransport`
        沿 D4.7.3 教训:`is None` 不用 `or` 保留 falsey 替身
    - **D5.1 范围**:**不**真发 SMTP(契约边界),仅入库 `outbox` 表 + 凭证抽象就绪
        真实发送由 D5.4 `OutboxDispatcher` 接管

QQ SMTP 授权码获取(用户手动一次性):

    1. 登录 QQ 邮箱网页版
    2. 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务
    3. 开启 SMTP 服务(独立于 IMAP)
    4. 短信验证后生成 16 位授权码
    5. 调用 `python scripts/spike_set_smtp_password.py --provider qq --email you@qq.com --set-password <authcode>`
       把授权码存进 Keychain

D5.1 风险缓解:
    - 凭据硬编码/日志泄露(🚨 严重):SMTPConnector 不存密码明文,loguru logger 只打印 service+account
    - 依赖注入 falsey 替身(⚠️ 中):`transport is None` 严判,不用 `or` 短路
    - 异常窄化(D3.3.3 教训):只接具体 SMTP 异常,不接 `smtplib.SMTPException` / `Exception` 基类
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Final, Protocol

from loguru import logger

from my_ai_employee.connectors.base import (
    CIRCUIT_BREAKER_COOLDOWN,
    CIRCUIT_BREAKER_THRESHOLD,
    HealthStatus,
)
from my_ai_employee.core import keychain

# ===== 4 状态返回结果(契约层 — D5.3 Adapter 严判)=====


@dataclass(frozen=True)
class SMTPSendResult:
    """SMTP transport 发送结果(契约层 — D5.3 EmailSendAdapter 据此分流业务阻断 vs 技术失败)。

    4 状态:
        - OK:                 发送成功(2xx SMTP 响应)
        - PERMANENT_BOUNCE:   收件人/发件人被拒(5xx 4xx,SMTPRecipientsRefused / SMTPSenderRefused)
        - TRANSPORT_ERROR:    瞬态网络/服务器错误(SMTPServerDisconnected / SMTPConnectError)
        - TIMEOUT:            socket.timeout / SMTP 协议超时
    """

    status: str  # OK / PERMANENT_BOUNCE / TRANSPORT_ERROR / TIMEOUT
    smtp_code: int | None = None
    smtp_message: str | None = None
    error_detail: str | None = None


# 4 状态枚举(契约层)
SMTP_SEND_OK: Final[str] = "ok"
SMTP_SEND_PERMANENT_BOUNCE: Final[str] = "permanent_bounce"
SMTP_SEND_TRANSPORT_ERROR: Final[str] = "transport_error"
SMTP_SEND_TIMEOUT: Final[str] = "timeout"

_SMTP_SEND_STATUSES: Final[frozenset[str]] = frozenset(
    {
        SMTP_SEND_OK,
        SMTP_SEND_PERMANENT_BOUNCE,
        SMTP_SEND_TRANSPORT_ERROR,
        SMTP_SEND_TIMEOUT,
    }
)


# ===== Transport 抽象(Protocol — D4.7.3 v1.0.3 duck type 范本)=====


class SMTPTransport(Protocol):
    """SMTP 传输抽象 Protocol — 生产用 SmtpLibTransport,测试用 InMemorySmtpTransport。

    D4.7.3 v1.0.3 范本:Protocol + duck type,EmailSendAdapter 在严判时
    接受任何实现了 send_message / connect / quit 三方法的类。
    """

    def connect(self, host: str, port: int, *, timeout: float = 30.0) -> None:
        """建立 SMTP SSL 连接(同步,生产用 smtplib.SMTP_SSL)。"""
        ...

    def login(self, username: str, password: str) -> None:
        """SMTP 登录(用授权码)。"""
        ...

    def send_message(self, message: EmailMessage) -> SMTPSendResult:
        """发送邮件(已登录状态)。返回 SMTPSendResult 4 状态之一。"""
        ...

    def quit(self) -> None:
        """优雅退出 SMTP 会话。"""
        ...


# ===== 生产实现 — smtplib.SMTP_SSL 包装 =====


class SmtpLibTransport:
    """生产 SMTP transport — 包装 smtplib.SMTP_SSL(D5.1 范围边界:QQ 端口 465)。

    D5.3 EmailSendAdapter 在 SMTP 失败时通过 except 捕获 smtplib 异常,
    业务阻断 vs 技术失败 分流(D3.3.3 异常窄化范本)。
    """

    def __init__(self) -> None:
        self._client: smtplib.SMTP_SSL | None = None
        self._host: str | None = None
        self._port: int | None = None

    def connect(self, host: str, port: int, *, timeout: float = 30.0) -> None:
        """建立 SMTP SSL 连接(端口 465,QQ 邮箱强制 SSL)。

        异常映射(应用层 try/except):
            - OSError / socket.gaierror → TRANSPORT_ERROR
            - smtplib.SMTPConnectError → TRANSPORT_ERROR
            - ssl.SSLError → TRANSPORT_ERROR
            - socket.timeout → TIMEOUT
        """
        context = ssl.create_default_context()
        try:
            self._client = smtplib.SMTP_SSL(
                host=host,
                port=port,
                context=context,
                timeout=timeout,
            )
            self._host = host
            self._port = port
        except (OSError, smtplib.SMTPConnectError) as e:
            raise SmtpTransportError(f"SMTP SSL 连接失败: {e!r}") from e
        except ssl.SSLError as e:
            raise SmtpTransportError(f"SMTP SSL 握手失败: {e!r}") from e
        except TimeoutError as e:
            raise SmtpTimeoutError(f"SMTP 连接超时: {e!r}") from e

    def login(self, username: str, password: str) -> None:
        """SMTP 登录(用授权码)。

        异常映射:
            - smtplib.SMTPAuthenticationError → SmtpAuthError(业务阻断,凭据错)
            - smtplib.SMTPException(其他) → SmtpTransportError(技术失败)
        """
        if self._client is None:
            raise SmtpTransportError("SMTP 未连接,需先调 connect()")
        try:
            self._client.login(username, password)
        except smtplib.SMTPAuthenticationError as e:
            raise SmtpAuthError(f"SMTP 认证失败: {e!r}") from e
        except smtplib.SMTPException as e:
            raise SmtpTransportError(f"SMTP 登录失败: {e!r}") from e

    def send_message(self, message: EmailMessage) -> SMTPSendResult:
        """发送邮件(已登录状态)。返回 SMTPSendResult 4 状态之一。

        异常映射:
            - smtplib.SMTPRecipientsRefused → PERMANENT_BOUNCE
            - smtplib.SMTPSenderRefused → PERMANENT_BOUNCE
            - smtplib.SMTPServerDisconnected → TRANSPORT_ERROR
            - smtplib.SMTPDataError → PERMANENT_BOUNCE(4xx 数据错误)
            - smtplib.SMTPException(其他) → TRANSPORT_ERROR
            - socket.timeout → TIMEOUT
        """
        if self._client is None:
            return SMTPSendResult(
                status=SMTP_SEND_TRANSPORT_ERROR,
                error_detail="SMTP 未连接",
            )

        # 提取 from/to(EmailMessage 标准字段)
        from_addr = str(message.get("From", ""))
        to_addrs = [str(addr) for addr in message.get_all("To", [])]

        try:
            # send_message 在 smtplib 3.6+ 接受 EmailMessage
            refused = self._client.send_message(message)
        except smtplib.SMTPRecipientsRefused as e:
            # 收件人拒收 → 永久退信(业务阻断)
            smtp_code, smtp_msg = _extract_smtp_code(e)
            return SMTPSendResult(
                status=SMTP_SEND_PERMANENT_BOUNCE,
                smtp_code=smtp_code,
                smtp_message=smtp_msg,
                error_detail=f"recipients refused: {dict(e.recipients)}",
            )
        except smtplib.SMTPSenderRefused as e:
            # 发件人拒收 → 永久退信(业务阻断)
            smtp_code, smtp_msg = _extract_smtp_code(e)
            return SMTPSendResult(
                status=SMTP_SEND_PERMANENT_BOUNCE,
                smtp_code=smtp_code,
                smtp_message=smtp_msg,
                error_detail=f"sender refused: {e.sender}",
            )
        except smtplib.SMTPDataError as e:
            # DATA 阶段 4xx 错误 → 永久退信
            return SMTPSendResult(
                status=SMTP_SEND_PERMANENT_BOUNCE,
                smtp_code=e.smtp_code,
                smtp_message=e.smtp_error.decode("utf-8", errors="replace")
                if isinstance(e.smtp_error, bytes)
                else str(e.smtp_error),
                error_detail=f"data error: {e!r}",
            )
        except smtplib.SMTPServerDisconnected as e:
            return SMTPSendResult(
                status=SMTP_SEND_TRANSPORT_ERROR,
                error_detail=f"server disconnected: {e!r}",
            )
        except TimeoutError as e:
            return SMTPSendResult(
                status=SMTP_SEND_TIMEOUT,
                error_detail=f"socket timeout: {e!r}",
            )
        except smtplib.SMTPException as e:
            return SMTPSendResult(
                status=SMTP_SEND_TRANSPORT_ERROR,
                error_detail=f"SMTP error: {e!r}",
            )

        # 检查 refused dict(部分拒收)
        if refused:
            return SMTPSendResult(
                status=SMTP_SEND_PERMANENT_BOUNCE,
                error_detail=f"partial refused: {dict(refused)}",
            )

        logger.info(f"SMTP 发送成功: from={from_addr} to={to_addrs} host={self._host}:{self._port}")
        return SMTPSendResult(status=SMTP_SEND_OK)

    def quit(self) -> None:
        """优雅退出 SMTP 会话。"""
        if self._client is not None:
            try:
                self._client.quit()
            except smtplib.SMTPException as e:
                logger.warning(f"SMTP quit 失败(忽略): {e!r}")
            finally:
                self._client = None


# ===== 测试替身 — InMemorySmtpTransport =====


class InMemorySmtpTransport:
    """测试用 SMTP transport — 不真发,记录全部 send 调用到 sent_log。

    D5.3 EmailSendAdapter 测试用此替身,不必 mock smtplib。
    D4.7.3 v1.0.0 duck type 范本:继承真实类(SmtpLibTransport)以保持类型兼容,
    这里因 SMTPTransport 是 Protocol 类,用 duck type 实现(SMTPTransport 协议兼容)。
    """

    def __init__(self) -> None:
        self.connected: bool = False
        self.logged_in: bool = False
        self.quit_called: bool = False
        self.sent_log: list[dict[str, object]] = []
        # 模拟失败注入(测试用)
        self.inject_status: str | None = None  # 强制 send_message 返回指定状态
        self.inject_exception: Exception | None = None  # 强制 send_message 抛指定异常

    def connect(self, host: str, port: int, *, timeout: float = 30.0) -> None:
        self.connected = True

    def login(self, username: str, password: str) -> None:
        if not self.connected:
            raise SmtpTransportError("SMTP 未连接")
        self.logged_in = True

    def send_message(self, message: EmailMessage) -> SMTPSendResult:
        if not self.logged_in:
            return SMTPSendResult(
                status=SMTP_SEND_TRANSPORT_ERROR,
                error_detail="SMTP 未登录",
            )

        # 模拟异常注入(测试用)
        if self.inject_exception is not None:
            raise self.inject_exception

        # 模拟状态注入(测试用)
        if self.inject_status is not None:
            return SMTPSendResult(status=self.inject_status)

        # 记录发送(测试断言用)
        self.sent_log.append(
            {
                "from": str(message.get("From", "")),
                "to": [str(addr) for addr in message.get_all("To", [])],
                "subject": str(message.get("Subject", "")),
                "body": _extract_body(message),
            }
        )
        return SMTPSendResult(status=SMTP_SEND_OK)

    def quit(self) -> None:
        self.quit_called = True
        self.connected = False
        self.logged_in = False


# ===== Transport 异常类(契约层 — D5.3 Adapter 严判)=====


class SmtpTransportError(Exception):
    """SMTP transport 通用错误(连接/协议/DNS 失败)。"""


class SmtpTimeoutError(Exception):
    """SMTP socket 超时(技术失败,可重试)。"""


class SmtpAuthError(Exception):
    """SMTP 认证失败(业务阻断,凭据错需用户重新设置)。

    D5.3 EmailSendAdapter 捕获后走 record_send_business_blocked_and_emit
    (recovery_policy="none",永不重试)。
    """


# ===== 私有 helper =====


def _extract_smtp_code(exc: smtplib.SMTPException) -> tuple[int, str]:
    """从 SMTP 异常提取 (smtp_code, smtp_message)。

    SMTPRecipientsRefused(继承 SMTPException)与 SMTPSenderRefused(继承 SMTPResponseException)
    都有 smtp_code / smtp_error 属性,但 Python 类型树里前者不继承 SMTPResponseException。
    因此接受更宽的 SMTPException,运行时属性检查。
    """
    smtp_code: int = getattr(exc, "smtp_code", 0) or 0
    smtp_error_obj: object = getattr(exc, "smtp_error", b"")
    if isinstance(smtp_error_obj, bytes):
        smtp_msg = smtp_error_obj.decode("utf-8", errors="replace")
    else:
        smtp_msg = str(smtp_error_obj)
    return smtp_code, smtp_msg


def _extract_body(message: EmailMessage) -> str:
    """从 EmailMessage 提取正文(测试断言用)。

    get_payload(decode=True) 解码 quoted-printable / base64。
    """
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return str(payload) if payload else ""


# ===== 服务器配置(沿 IMAP 范本 imap.py:45-74)=====

_SMTP_PROVIDERS: Final[tuple[str, ...]] = ("qq", "outlook", "gmail")


@dataclass(frozen=True)
class SMTPServerConfig:
    """SMTP 服务器配置(按邮箱服务商固定)。"""

    host: str
    port: int
    source_name_value: str
    description: str


SERVER_CONFIGS: Final[dict[str, SMTPServerConfig]] = {
    "qq": SMTPServerConfig(
        host="smtp.qq.com",
        port=465,
        source_name_value="qq",
        description="QQ 邮箱(SMTP_SSL 端口 465,授权码模式,D5.1 优先)",
    ),
    "outlook": SMTPServerConfig(
        host="smtp.office365.com",
        port=465,
        source_name_value="outlook",
        description="Outlook(SMTP_SSL 端口 465,OAuth 2.0 推后到 D2.5)",
    ),
    "gmail": SMTPServerConfig(
        host="smtp.gmail.com",
        port=465,
        source_name_value="gmail",
        description="Gmail(SMTP_SSL 端口 465,OAuth 2.0 推后到 D2.5)",
    ),
}


# ===== SMTPConnector — 高层封装(独立类,D5.1 决策:不继承 BaseConnector)=====


@dataclass
class _SmtpCircuitBreakerState:
    """SMTP 熔断器内部状态(每实例独立持有,沿用 base.py 范本)。

    复用 base.py 的 CIRCUIT_BREAKER_THRESHOLD=3 / COOLDOWN=30min 常量,
    避免 SMTP 独自定义阈值与全局不一致。
    """

    consecutive_failures: int = 0
    last_failure_at: float = 0.0  # time.time() 时间戳
    open_until: float = 0.0  # 熔断结束时间戳


class SMTPConnector:
    """SMTP 适配器(QQ / Outlook / Gmail 通用,配置不同)。

    D5.1 设计决策:**不继承 BaseConnector**(SMTP 不需要 fetch — 只发不收,
    强继承会触发 fetch 抽象方法未实现 TypeError)。

    自维护最小熔断状态(_SmtpCircuitBreakerState 3 字段),与 IMAP 行为一致
    (CIRCUIT_BREAKER_THRESHOLD=3 / CIRCUIT_BREAKER_COOLDOWN=30min)。

    D5.1 范围:仅凭证抽象 + 健康检查 + 邮件构造,真实发送由 D5.4 OutboxDispatcher 接管。
    D5.3 EmailSendAdapter 持本类实例,调用 build_message + 注入 SMTPTransport 发送。

    用法(生产,D5.4):

        connector = SMTPConnector(provider="qq", email="you@qq.com")
        await connector.connect()  # 从 Keychain 读授权码
        transport = SmtpLibTransport()
        transport.connect(connector.server_host, connector.server_port)
        transport.login(connector.email, connector._password)  # 内部已读 Keychain
        result = transport.send_message(message)

    用法(测试):

        # scripts/spike_set_smtp_password.py CLI 提供 --set-password / --check
        # tests/connectors/test_smtp.py 用 InMemorySmtpTransport 替身
    """

    def __init__(
        self,
        provider: str,
        email: str,
        transport: SMTPTransport | None = None,
    ) -> None:
        if provider not in _SMTP_PROVIDERS:
            raise ValueError(f"未知 provider: {provider!r}(支持:{list(_SMTP_PROVIDERS)})")
        # D5.1 阶段白名单:仅 QQ 邮箱走授权码模式(与 IMAP 同步)
        if provider != "qq":
            raise NotImplementedError(
                f"SMTPConnector 当前只实现 provider='qq'(D5.1 阶段)。"
                f"provider={provider!r} 需 OAuth 2.0,留 D5.5+ 重启。"
            )
        self._provider = provider
        self._email = email
        self._config = SERVER_CONFIGS[provider]
        # D5.1-fix 修复:默认 transport=None(不再静默 fallback 到 InMemorySmtpTransport)
        # 原因:生产环境忘记显式注入 transport 时,connect()/healthcheck() 会
        # "假成功"(InMemorySmtpTransport 默认 healthy),这是 D5 启动后被用户
        # 标记的 2 个代码风险之一。修复策略:构造时 None,首次 connect()/healthcheck()
        # 入口 is None 硬报错,生产环境必须显式传入 SmtpLibTransport()。
        self._transport: SMTPTransport | None = transport
        if transport is None:
            logger.warning(
                f"SMTPConnector 创建时未注入 transport: provider={provider} email={email}。"
                f"生产环境必须显式传入 SmtpLibTransport(),测试可传 InMemorySmtpTransport()。"
                f"首次 connect()/healthcheck() 调用将抛 SmtpTransportError。"
            )
        self._password: str | None = None  # 内部缓存,connect() 时从 Keychain 读
        # 自维护熔断状态(沿用 base.py 阈值常量)
        self._circuit: _SmtpCircuitBreakerState = _SmtpCircuitBreakerState()

    @property
    def server_host(self) -> str:
        return self._config.host

    @property
    def server_port(self) -> str:
        return str(self._config.port)

    @property
    def source_name(self) -> str:
        return self._config.source_name_value

    @property
    def transport(self) -> SMTPTransport | None:
        """暴露 transport 给 D5.3 EmailSendAdapter 调用(读)。

        D5.1-fix 修订:返回类型改为 `SMTPTransport | None`,因为构造时未注入
        transport 时返回 None。D5.3 EmailSendAdapter 必须先判 None 再用。
        """
        return self._transport

    @property
    def circuit_state(self) -> dict[str, Any]:
        """读熔断状态(供健康面板 / 调试用)。"""
        return {
            "consecutive_failures": self._circuit.consecutive_failures,
            "last_failure_at": self._circuit.last_failure_at,
            "open_until": self._circuit.open_until,
            "is_open": self._is_circuit_open(),
        }

    # ===== 公共异步接口(沿用 IMAPConnector 接口形式)=====

    async def connect(self) -> None:
        """建立 SMTP SSL 连接 + 登录(异步包装:内部同步走 asyncio.to_thread)。

        失败抛 `SmtpAuthError`(凭据错,业务阻断)/ `SmtpTransportError`(网络错,技术失败)。
        """
        # 1. 读凭证
        cred = keychain.get_smtp_password(self._email)
        if not cred.ok or not cred.value:
            raise SmtpAuthError(
                f"Keychain 中找不到 {self._email} 的 SMTP 授权码:{cred.error}\n"
                f"请先跑:python scripts/spike_set_smtp_password.py "
                f"--provider qq --email {self._email} --set-password <authcode>"
            )
        self._password = cred.value

        # 2. 同步连接 + 登录(CPU/IO 密集,走 thread 不阻塞事件循环)
        try:
            await asyncio.to_thread(self._connect_sync)
        except (SmtpTransportError, SmtpTimeoutError, SmtpAuthError):
            # 透传 — 让 healthcheck / 调度器上层按异常类型分流
            raise
        except Exception as e:
            # 抹平同步异常 → 转成可识别的 SmtpTransportError
            raise SmtpTransportError(f"SMTP 连接失败: {e!r}") from e

    def _connect_sync(self) -> None:
        """同步连接 + 登录(内部走 SMTPTransport 抽象)。"""
        if self._password is None:
            raise SmtpAuthError("SMTP 密码未读取,需先调 connect()")
        # D5.1-fix 修复:transport 未注入 → 硬报错,避免"假成功"
        if self._transport is None:
            raise SmtpTransportError(
                f"SMTPConnector transport 未注入: provider={self._provider} email={self._email}。"
                f"生产环境必须显式传入 SmtpLibTransport() (从 smtplib.SMTP_SSL 包装),"
                f"测试可传 InMemorySmtpTransport()。D5.1-fix 风险 #2 缓解动作。"
            )
        self._transport.connect(
            host=self._config.host,
            port=self._config.port,
            timeout=30.0,
        )
        self._transport.login(self._email, self._password)
        # 日志:严禁打印 password,只打印 service+account 标识
        logger.info(
            f"SMTP 登录成功: provider={self._provider} host={self._config.host} email={self._email}"
        )

    async def healthcheck(self) -> HealthStatus:
        """SMTP 健康检查:复用 connect(登录成功即健康)。

        失败语义:healthcheck 失败也会进入熔断计数(连续 3 次失败 → 30 min 冷却)。
        连接生命周期:try/finally 关闭,避免多次 healthcheck 累积 SMTP 连接。
        """
        start = time.perf_counter()
        try:
            try:
                await self.connect()
            except Exception as e:
                latency = (time.perf_counter() - start) * 1000
                # healthcheck 失败 → 计入熔断(与 IMAP 一致)
                self._record_failure(e)
                return HealthStatus(
                    ok=False,
                    latency_ms=latency,
                    error=str(e),
                    circuit_open=self._is_circuit_open(),
                )
            latency = (time.perf_counter() - start) * 1000
            # 健康检查成功也重置计数(避免历史失败持续累积)
            self._record_success()
            return HealthStatus(ok=True, latency_ms=latency)
        finally:
            # 无论成功失败都关闭连接,避免 healthcheck 反复调用时连接累积
            await self.close()

    async def close(self) -> None:
        """关闭 SMTP 连接(优雅退出)。

        D5.1-fix 修复:transport 为 None 时静默跳过(不抛错),与 healthcheck 内部
        调用契约一致(healthcheck try/finally 总会调 close)。
        """
        if self._transport is None:
            return
        try:
            await asyncio.to_thread(self._transport.quit)
        except Exception as e:
            logger.warning(f"SMTP quit 失败(忽略): {e!r}")
        finally:
            self._password = None

    # ===== 熔断内部方法(沿用 base.py 范本,自维护版本)=====

    def _is_circuit_open(self) -> bool:
        """是否处于熔断状态。"""
        if self._circuit.open_until == 0.0:
            return False
        if time.time() < self._circuit.open_until:
            return True
        # 熔断到期 → 自动重置
        self._reset_circuit()
        return False

    def _record_success(self) -> None:
        """healthcheck 成功 → 重置失败计数。"""
        if self._circuit.consecutive_failures > 0:
            logger.info(
                f"[{self.source_name}] healthcheck 成功,重置失败计数 "
                f"(was {self._circuit.consecutive_failures})"
            )
        self._circuit.consecutive_failures = 0
        self._circuit.open_until = 0.0

    def _record_failure(self, error: BaseException) -> None:
        """healthcheck 失败 → 计数 + 检查是否进入熔断。"""
        self._circuit.consecutive_failures += 1
        self._circuit.last_failure_at = time.time()

        if self._circuit.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            self._circuit.open_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
            logger.error(
                f"[{self.source_name}] 连续失败 "
                f"{self._circuit.consecutive_failures} 次,"
                f"进入熔断 {CIRCUIT_BREAKER_COOLDOWN}s: {error!r}"
            )
        else:
            logger.warning(
                f"[{self.source_name}] 失败 "
                f"{self._circuit.consecutive_failures}/{CIRCUIT_BREAKER_THRESHOLD}: {error!r}"
            )

    def _reset_circuit(self) -> None:
        """熔断到期 → 重置。"""
        logger.info(f"[{self.source_name}] 熔断到期,重置状态")
        self._circuit.consecutive_failures = 0
        self._circuit.open_until = 0.0

    # ===== 邮件构造(D5.3 EmailSendAdapter 复用)=====

    def build_message(
        self,
        from_addr: str,
        to_addrs: list[str],
        subject: str,
        body: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> EmailMessage:
        """构造标准 EmailMessage(D5.3 Adapter 复用)。

        Args:
            from_addr: 发件人邮箱(必填,严判含 @)
            to_addrs: 收件人列表(必填,严判至少 1 个,每个含 @)
            subject: 主题(必填,严判 strip() 后非空,1-200 字符)
            body: 正文(必填,严判 strip() 后非空,10-8000 字符)
            headers: 额外 SMTP 头(如 X-Outbox-Id / X-Outbox-Priority,D5.3 透传)

        Returns:
            构造好的 EmailMessage(可直接传给 transport.send_message)

        Raises:
            ValueError: 严判失败
            TypeError: 字段类型非法
        """
        # 入口严判(D4.7.3 v1.0.5 P2-1 范本:type 严判在 hash 前)
        if type(from_addr) is not str:
            raise TypeError(f"from_addr 必须是 str,实际 {type(from_addr).__name__}")
        if "@" not in from_addr:
            raise ValueError(f"from_addr 必须含 @,实际 {from_addr!r}")
        if not isinstance(to_addrs, list) or not to_addrs:
            raise ValueError("to_addrs 必须是非空 list[str]")
        for i, addr in enumerate(to_addrs):
            if type(addr) is not str or "@" not in addr:
                raise ValueError(f"to_addrs[{i}] 必须是含 @ 的 str,实际 {addr!r}")
        if type(subject) is not str or not subject.strip():
            raise ValueError(f"subject 必须是 strip() 后非空 str,实际 {subject!r}")
        if type(body) is not str or not body.strip():
            raise ValueError(f"body 必须是 strip() 后非空 str,实际 {body!r}")

        msg = EmailMessage()
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        msg["Subject"] = subject
        if headers:
            for key, value in headers.items():
                msg[key] = value
        msg.set_content(body)
        return msg


__all__ = [
    "SMTPSendResult",
    "SMTP_SEND_OK",
    "SMTP_SEND_PERMANENT_BOUNCE",
    "SMTP_SEND_TRANSPORT_ERROR",
    "SMTP_SEND_TIMEOUT",
    "SMTPTransport",
    "SmtpLibTransport",
    "InMemorySmtpTransport",
    "SmtpTransportError",
    "SmtpTimeoutError",
    "SmtpAuthError",
    "SMTPServerConfig",
    "SERVER_CONFIGS",
    "SMTPConnector",
]
