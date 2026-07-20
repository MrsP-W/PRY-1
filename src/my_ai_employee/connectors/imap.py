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
from datetime import UTC, datetime
from typing import Any, Final

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


SERVER_CONFIGS: Final[dict[str, IMAPServerConfig]] = {
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
            raise ValueError(f"未知 provider: {provider!r}（支持：{list(SERVER_CONFIGS)}）")
        # D2 阶段白名单：仅 QQ 邮箱走授权码模式。
        # Outlook/Gmail 需 OAuth 2.0，留给 D2.5 spike；提前构造就报错（fail-fast）
        # 避免 D3 误用。
        if provider != "qq":
            raise NotImplementedError(
                f"IMAPConnector 当前只实现 provider='qq'（D2 阶段）。"
                f"provider={provider!r} 需 OAuth 2.0，留 D2.5 spike 重启。"
                f"详见 docs/spike-imap-compat.md。"
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
        """同步连接（D2 收窄版用 imapclient 的同步 API）。

        流程（参考 IMAPClient 官方示例）：
            1. IMAPClient() — 建立 SSL socket
            2. .login(user, password) — 鉴权
            3. .select_folder("INBOX", readonly=True) — 进入收件箱
               readonly=True → 不会修改已读/未读状态，避免误标邮件
        """
        self._client = IMAPClient(
            host=self._config.host,
            port=self._config.port,
            ssl=True,
            timeout=15,
        )
        # imapclient.login 在鉴权失败时抛 `IMAP4.error`
        self._client.login(self._email, password)
        # 官方示例：登录后必须显式 select_folder，否则 search 会因"未选中邮箱"失败
        # readonly=True 防止意外标记已读（D2 阶段只读不写）
        self._client.select_folder("INBOX", readonly=True)
        logger.info(
            f"IMAP 登录成功 + INBOX 已选中: provider={self._provider} "
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
        since_naive = since.astimezone(UTC).replace(tzinfo=None)
        try:
            uids = await asyncio.to_thread(self._client.search, ["SINCE", since_naive])
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
        skipped_bad = 0
        for uid, data in fetch_data.items():
            envelope = data.get(b"ENVELOPE")
            size = data.get(b"RFC822.SIZE", 0)
            if not envelope:
                continue
            # P2：单封坏 envelope 不拖垮整次 fetch（兄弟 UID 仍可入库）
            try:
                results.append(self._envelope_to_dict(uid, envelope, size))
            except Exception as e:
                skipped_bad += 1
                logger.warning(
                    f"IMAP envelope 解析跳过: provider={self._provider} uid={uid!r} err={e!r}"
                )

        logger.info(
            f"IMAP fetch 完成: provider={self._provider} "
            f"uids={len(uids)} returned={len(results)} skipped_bad={skipped_bad} "
            f"since={since_naive}"
        )
        return results

    def _envelope_to_dict(self, uid: int | bytes, envelope: Any, size: int) -> dict[str, Any]:
        """imapclient 的 ENVELOPE → 标准 dict。

        真实 imapclient 3.x 返回的是 `Envelope` namedtuple，字段：
            date: datetime | None
            subject: str | bytes
            from_: tuple[Address, ...]  (Address = namedtuple(name, route, mailbox, host))
            message_id: str | bytes

        ⚠️ D13.x P0 修复(2026-07-07,撞坑 #71 业务代码改动日破例):
            imapclient 3.x 实际返回 bytes(utf-8 编码),2.x 是 str。
            直接 bytes 入库会导致 SQLAlchemy `Mapped[str]` 严判 type 时抛 ValueError,
            Email 读取时收到 bytes(因为 sqlcipher3 driver 对 TEXT 列也返回 bytes),
            下游 classifier.classify 严判 type(subject) is not str → ValueError → classify_failed。

            修复:_to_str helper 统一 decode utf-8(errors="replace"),保证入 dict 全部 str。
            配合 models.BytesToStr TypeDecorator 做读取侧二次防御。
        """

        def _to_str(val: Any, *, default: str = "") -> str:
            """bytes/str/None 统一转 str(bytes 走 utf-8 decode,errors='replace' 防炸)。"""
            if val is None:
                return default
            if isinstance(val, bytes):
                return val.decode("utf-8", errors="replace")
            return str(val)

        subject = _to_str(envelope.subject)
        sender = ""
        if envelope.from_:
            # from_ = (name, route, mailbox, host) — 实际是 bytes
            addr = envelope.from_[0]
            mailbox = _to_str(addr.mailbox)
            host = _to_str(addr.host)
            if mailbox and host:
                sender = f"{mailbox}@{host}"
        message_id = _to_str(envelope.message_id)
        # date 已经是 datetime(无需 decode)
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
        """IMAP 健康检查：复用 connect（登录成功即健康）。

        失败语义：healthcheck 失败也会进入熔断计数（连续 3 次失败 → 30 min 冷却）。
        连接生命周期：try/finally 关闭，避免多次 healthcheck 累积 IMAP 连接。
        """
        import time as _time

        start = _time.perf_counter()
        try:
            try:
                await self.connect()
            except Exception as e:
                latency = (_time.perf_counter() - start) * 1000
                # healthcheck 失败 → 计入熔断（与 safe_fetch 一致）
                self._record_failure(e)
                return HealthStatus(
                    ok=False,
                    latency_ms=latency,
                    error=str(e),
                    circuit_open=self._is_circuit_open(),
                )
            latency = (_time.perf_counter() - start) * 1000
            # 健康检查成功也重置计数（避免历史失败持续累积）
            self._record_success()
            return HealthStatus(ok=True, latency_ms=latency)
        finally:
            # 无论成功失败都关闭连接，避免 healthcheck 反复调用时连接累积
            # （close 内部已用 try/except 处理"已断开"场景）
            await self.close()

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
