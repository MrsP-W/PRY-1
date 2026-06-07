"""Mock IMAPClient（仅测试用）。

设计：pytest fixture 把 `IMAPConnector._client` 替换成这个 `MockIMAPClient`，
从而：
    - 不开 socket
    - 不需要真 QQ 邮箱
    - 可控返回（成功/失败/超时）

支持的 mock 行为：
    - login(): 成功 / 抛 IMAP4.error（鉴权失败）
    - search(): 返回预设 UID 列表
    - fetch(): 返回预设 envelope 数据（用真实 imapclient.response_types.Envelope）
    - logout(): 幂等

使用（test_imap.py 里）：

    @pytest.fixture
    def mock_imap(monkeypatch):
        return MockIMAPClient()
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from imapclient.response_types import Address, Envelope


class MockIMAPError(Exception):
    """模拟 imapclient 的 `IMAP4.error`。"""


class MockIMAPClient:
    """Mock `IMAPClient`，行为可注入。

    字段：
        - login_should_fail: bool — login 时是否抛错
        - search_uids: list[int] — search 返回的 UID
        - fetch_data: dict[int, dict] — fetch 返回的数据（key=UID, value=envelope）
        - logout_called: bool — 是否调用过 logout（验证 close 路径）
    """

    def __init__(self) -> None:
        self.login_should_fail: bool = False
        self.search_uids: list[int] = []
        self.fetch_data: dict[int, dict[str, Any]] = {}
        self.logout_called: bool = False
        self.connected_host: str | None = None
        self.connected_port: int | None = None

    def login(self, username: str, password: str) -> tuple[str, list[bytes]]:
        """Mock login。失败抛 MockIMAPError。"""
        if self.login_should_fail:
            raise MockIMAPError(f"Mock: login failed for {username}")
        return "OK", [b"CAPABILITY IMAP4rev1"]

    def search(self, criteria: list[Any]) -> list[int]:
        """Mock search。返回预设 UID 列表。"""
        return list(self.search_uids)

    def fetch(self, uids: list[int], parts: list[str]) -> dict[int, dict[str, Any]]:
        """Mock fetch。返回预设 envelope 数据。"""
        result = {}
        for uid in uids:
            if uid in self.fetch_data:
                result[uid] = self.fetch_data[uid]
        return result

    def logout(self) -> tuple[str, list[bytes]]:
        """Mock logout。"""
        self.logout_called = True
        return "BYE", []


def _parse_sender(sender: str) -> Address:
    """`"Name <a@x.com>"` / `"a@x.com"` → `Address` namedtuple。"""
    if "<" in sender and ">" in sender:
        name_part, addr_part = sender.split("<", 1)
        name = name_part.strip().strip('"') or None
        addr = addr_part.split(">", 1)[0].strip()
    else:
        name = None
        addr = sender.strip()
    if "@" in addr:
        mailbox, host = addr.split("@", 1)
    else:
        mailbox, host = addr, ""
    return Address(name=name, route=None, mailbox=mailbox, host=host)


def make_envelope(
    uid: int,
    *,
    subject: str = "Test Subject",
    sender: str = "test@example.com",
    message_id: str | None = None,
    received_at: datetime | None = None,
    size: int = 1024,
) -> dict[int, dict[str, Any]]:
    """构造真实 imapclient `Envelope` 对象（不是 list）。

    返回的 dict 格式：`{uid: {b"ENVELOPE": Envelope(...), b"RFC822.SIZE": size}}`
    """
    if received_at is None:
        received_at = datetime.now(timezone.utc)
    if message_id is None:
        message_id = f"<test-{uid}@example.com>"

    env = Envelope(
        date=received_at,
        subject=subject,
        from_=(_parse_sender(sender),),
        sender=None,
        reply_to=None,
        to=None,
        cc=None,
        bcc=None,
        in_reply_to=None,
        message_id=message_id,
    )
    return {uid: {b"ENVELOPE": env, b"RFC822.SIZE": size}}


def install_mock(monkeypatch, target: Any, mock: MockIMAPClient) -> None:
    """把 MockIMAPClient 注入到 IMAPConnector._connect_sync 内部的 IMAPClient 构造点。

    原理：IMAPConnector._connect_sync 直接构造 `IMAPClient(host, port, ssl, timeout)`。
    我们 monkeypatch `my_ai_employee.connectors.imap.IMAPClient` 类，让它返回 mock 实例。
    """
    import my_ai_employee.connectors.imap as imap_module

    class _FakeIMAPClient:
        def __init__(self, *, host: str, port: int, ssl: bool, timeout: int) -> None:
            mock.connected_host = host
            mock.connected_port = port
            # 把 mock 暴露给 target（方便测试断言）
            target._client = mock

        def login(self, username: str, password: str):
            return mock.login(username, password)

        def search(self, criteria):
            return mock.search(criteria)

        def fetch(self, uids, parts):
            return mock.fetch(uids, parts)

        def logout(self):
            return mock.logout()

    monkeypatch.setattr(imap_module, "IMAPClient", _FakeIMAPClient)
