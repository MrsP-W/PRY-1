"""Dashboard 服务入口的启动、退出与本地绑定保护测试。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from my_ai_employee.dashboard import server
from my_ai_employee.dashboard.context import DashboardContext


def test_create_server_uses_default_context_and_handler_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = object()
    handler = object()
    http_server = Mock()
    default_mock = Mock(return_value=context)
    handler_factory_mock = Mock(return_value=handler)
    monkeypatch.setattr(DashboardContext, "default", default_mock)
    monkeypatch.setattr(server, "handler_factory", handler_factory_mock)
    monkeypatch.setattr(server, "ThreadingHTTPServer", http_server)

    result = server.create_server(host="127.0.0.1", port=0)

    assert result is http_server.return_value
    default_mock.assert_called_once_with()
    handler_factory_mock.assert_called_once_with(context)
    http_server.assert_called_once_with(("127.0.0.1", 0), handler)


def test_create_server_preserves_explicit_context(monkeypatch: pytest.MonkeyPatch) -> None:
    context = Mock()
    handler_factory_mock = Mock(return_value=Mock())
    monkeypatch.setattr(server, "handler_factory", handler_factory_mock)
    monkeypatch.setattr(server, "ThreadingHTTPServer", Mock())

    server.create_server(context, port=0)

    handler_factory_mock.assert_called_once_with(context)


def test_run_server_prints_bound_address_and_always_shuts_down(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    http_server = Mock(server_address=("127.0.0.1", 9123))
    monkeypatch.setattr(server, "create_server", Mock(return_value=http_server))

    server.run_server(port=9123)

    assert "http://127.0.0.1:9123/api/status" in capsys.readouterr().out
    http_server.serve_forever.assert_called_once_with()
    http_server.shutdown.assert_called_once_with()


def test_run_server_handles_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    http_server = Mock(server_address=("127.0.0.1", 8765))
    http_server.serve_forever.side_effect = KeyboardInterrupt
    monkeypatch.setattr(server, "create_server", Mock(return_value=http_server))

    server.run_server()

    assert "Dashboard API 已停止" in capsys.readouterr().out
    http_server.shutdown.assert_called_once_with()


def test_build_parser_supports_local_host_and_custom_port() -> None:
    args = server.build_parser().parse_args(["--host", "127.0.0.1", "--port", "9123"])

    assert args.host == "127.0.0.1"
    assert args.port == 9123


def test_main_passes_local_options_to_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    run_server = Mock()
    monkeypatch.setattr(server, "run_server", run_server)

    assert server.main(["--port", "9123"]) == 0
    run_server.assert_called_once_with(host="127.0.0.1", port=9123)


def test_main_rejects_non_local_bind_before_server_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    run_server = Mock()
    monkeypatch.setattr(server, "run_server", run_server)

    with pytest.raises(SystemExit, match="仅允许本地绑定"):
        server.main(["--host", "0.0.0.0"])

    run_server.assert_not_called()
