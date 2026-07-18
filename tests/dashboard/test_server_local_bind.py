"""Dashboard 服务端必须在库级阻止非本地绑定。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from my_ai_employee.dashboard import server


def test_create_server_rejects_non_local_bind_before_constructing_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """直接调用 create_server 也不能绕过 CLI 的本地绑定边界。"""
    http_server = Mock()
    monkeypatch.setattr(server, "ThreadingHTTPServer", http_server)

    with pytest.raises(ValueError, match="仅允许本地绑定 127.0.0.1"):
        server.create_server(host="0.0.0.0")

    http_server.assert_not_called()
