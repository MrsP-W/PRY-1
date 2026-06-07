"""L1 IMAP 适配器 — QQ 邮箱优先（授权码模式）。

设计（[docs/week1-mvp.md §D2.2]）：

    - **协议**：IMAP4 + 授权码（QQ 邮箱专用流程）
    - **库**：imapclient（PyPI 官方，XOAUTH2 支持）
    - **凭证**：邮箱地址 + 授权码（**不是密码**），从 macOS Keychain 读
    - **服务器**：
        - QQ:     imap.qq.com:993 (SSL)
        - Outlook: outlook.office365.com:993 (D2.5 spike，OAuth 2.0 推后)
        - Gmail:   imap.gmail.com:993 (D2.5 spike，OAuth 2.0 推后)

QQ 授权码获取（用户手动一次性）：

    1. 登录 QQ 邮箱网页版
    2. 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务
    3. 开启 IMAP/SMTP 服务
    4. 短信验证后生成 16 位授权码
    5. 调用 `python scripts/test_imap.py --set-password your@qq.com`
       把授权码存进 Keychain

失败模式（应急版范本应用）：

    - 网络断 → 抛 ConnectionError → safe_fetch 隔离
    - 授权码错 → IMAPClient 抛 `IMAP4.error` → safe_fetch 隔离
    - 服务器挂 → healthcheck 返回 ok=False → 熔断
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar

from imapclient import IMAPClient
from loguru import logger

from my_ai_employee.connectors.base import BaseConnector, HealthStatus
from my_ai_employee.core import keychain


# ===== 服务器配置 =====


@dataclass(frozen=True)
class IMAPServerConfig:
    """IMAP 服务器配置（按邮箱服务商固定）。"""

    host: str
    port: int
    source_name_value: str
    description: str


SERVER_CONFIGS: ClassVar[dict[str, IMAPServerConfig]] = {
    "qq": IMAPServerConfig(
        host="imap.qq.com",
        port=993,
        source_name_value="qq",
        description="QQ 邮箱（授权码模式，D2 优先）",
    ),
    "outlook": IMAPServerConfig(
        host="outlook.office365.com",
        port=993,
        source_name_value="outlook",
        description="Outlook（OAuth 2.0 推后到 D2.5 spike）",
    ),
    "gmail": IMAPServerConfig(
        host="imap.gmail.com",
        port=993,
        source_name_value="gmail",
        description="Gmail（OAuth 2.0 推后到 D2.5 spike）",
    ),
}


class IMAPConnector(BaseConnector):
    """IMAP 适配器（QQ / Outlook / Gmail 通用，配置不同）。

    用法（生产）：

        from datetime import datetime, timezone, timedelta
        connector = IMAPConnector(provider="qq", email="you@qq.com")
        await connector.connect()  # 从 Keychain 读授权码
        emails = await connector.safe_fetch(
            since=datetime.now(timezone.utc) - timedelta(days=7)
        )

    用法（测试）：

        # test_imap.py CLI 提供 --set-password / --check / --fetch-latest
    """

    def __init__(self, provider: str, email: str) -> None:
        super().__init__()  # 初始化熔断状态
        if provider not in SERVER_CONFIGS:
            raise ValueError(
                f"未知 provider: {provider!r}（支持：{list(SERVER_CONFIGS)}）"
            )
        self._provider = provider
        self._email = email
        self._config = SERVER_CONFIGS[provider]
        self._client: IMAPClient | None = None  # 懒连接

    # ===== BaseConnector 契约 =====

    @property
    def source_name(self) -> str:
        return self._config.source_name_value

    async def connect(self) -> None:
        """建立 IMAP SSL 连接（异步包装：内部同步走 asyncio.to_thread）。

        失败抛 `ConnectionError` / `PermissionError`（授权码错）。
        """
        # 1. 读凭证
        cred = keychain.get_imap_password(self._email)
        if not cred.ok or not cred.value:
            raise PermissionError(
                f"Keychain 中找不到 {self._email} 的授权码：{cred.error}\n"
                f"请先跑：python scripts/test_imap.py --set-password {self._email}"
            )

        # 2. 同步连接 + 登录（CPU/IO 密集，走 thread 不阻塞事件循环）
        try:
            await asyncio.to_thread(self._connect_sync, cred.value)
        except Exception as e:
            # 抹平同步异常 → 转成异步可识别的 ConnectionError
            raise ConnectionError(f"IMAP 连接失败: {e!r}") from e

    def _connect_sync(self, password: str) -> None:
        """同步连接（D2 收窄版用 imapclient 的同步 API）。"""
        self._client = IMAPClient(
            host=self._config.host,
            port=self._config.port,
            ssl=True,
            timeout=15,
        )
        # imapclient.login 在鉴权失败时抛 `IMAP4.error`
        self._client.login(self._email, password)
        logger.info(
            f"IMAP 登录成功: provider={self._provider} "
            f"host={self._config.host} email={self._email}"
        )

    async def fetch(self, since: datetime) -> list[dict[str, Any]]:
        """拉取 `since` 以来的邮件（默认查 INBOX）。

        返回的 dict 字段：
            - source: "qq" / "outlook" / "gmail"
            - message_id: RFC 5322 Message-ID
            - subject: 解码后的主题
            - sender: 发件人（From 头）
            - received_at: 收件时间（datetime，带 tz）
            - raw_size: 原始大小（bytes）
        """
        if self._client is None:
            await self.connect()

        assert self._client is not None
        # imapclient 的 search 需要 naive UTC 时间
        since_naive = since.astimezone(timezone.utc).replace(tzinfo=None)
        try:
            uids = await asyncio.to_thread(
                self._client.search, ["SINCE", since_naive]
            )
        except Exception as e:
            # 重新抛 → 让 safe_fetch 接住
            raise ConnectionError(f"IMAP search 失败: {e!r}") from e

        if not uids:
            return []

        # 拉取每封的 envelope（不下载 body，省流量）
        try:
            fetch_data = await asyncio.to_thread(
                self._client.fetch, uids, ["ENVELOPE", "RFC822.SIZE"]
            )
        except Exception as e:
            raise ConnectionError(f"IMAP fetch 失败: {e!r}") from e

        results: list[dict[str, Any]] = []
        for uid, data in fetch_data.items():
            envelope = data.get(b"ENVELOPE")
            size = data.get(b"RFC822.SIZE", 0)
            if not envelope:
                continue
            results.append(self._envelope_to_dict(uid, envelope, size))

        logger.info(
            f"IMAP fetch 完成: provider={self._provider} "
            f"uids={len(uids)} returned={len(results)} since={since_naive}"
        )
        return results

    def _envelope_to_dict(
        self, uid: int | bytes, envelope: Any, size: int
    ) -> dict[str, Any]:
        """imapclient 的 ENVELOPE → 标准 dict。

        真实 imapclient 3.x 返回的是 `Envelope` namedtuple，字段：
            date: datetime | None
            subject: str
            from_: tuple[Address, ...]  (Address = namedtuple(name, route, mailbox, host))
            message_id: str
        """
        # imapclient 3.x: 字段都是 str / datetime / Address（不是 bytes）
        subject = envelope.subject or ""
        sender = ""
        if envelope.from_:
            # from_ = (name, route, mailbox, host) — 全部 str
            addr = envelope.from_[0]
            mailbox = addr.mailbox or ""
            host = addr.host or ""
            if mailbox and host:
                sender = f"{mailbox}@{host}"
        message_id = envelope.message_id or ""
        # date 已经是 datetime
        received_at = envelope.date
        uid_int = uid if isinstance(uid, int) else int(uid)
        return {
            "source": self.source_name,
            "uid": uid_int,
            "message_id": message_id,
            "subject": subject,
            "sender": sender,
            "received_at": received_at,
            "raw_size": size,
        }

    async def healthcheck(self) -> HealthStatus:
        """IMAP 健康检查：复用 connect（登录成功即健康）。"""
        import time as _time

        start = _time.perf_counter()
        try:
            await self.connect()
            latency = (_time.perf_counter() - start) * 1000
            return HealthStatus(ok=True, latency_ms=latency)
        except Exception as e:
            latency = (_time.perf_counter() - start) * 1000
            return HealthStatus(
                ok=False,
                latency_ms=latency,
                error=str(e),
                circuit_open=self._is_circuit_open(),
            )

    async def close(self) -> None:
        """关闭连接（优雅退出）。"""
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.logout)
            except Exception as e:
                logger.warning(f"IMAP logout 失败（忽略）: {e!r}")
            finally:
                self._client = None


__all__ = [
    "IMAPConnector",
    "IMAPServerConfig",
    "SERVER_CONFIGS",
]
