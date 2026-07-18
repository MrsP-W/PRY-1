"""主 CLI 副作用分支的隔离测试。"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from my_ai_employee import main


def test_print_panel_falls_back_to_plain_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(main, "RICH_AVAILABLE", False)

    main._print_panel("标题", "[bold]正文[/bold]")

    output = capsys.readouterr().out
    assert "标题" in output
    assert "正文" in output
    assert "[bold]" not in output


def test_print_panel_uses_rich_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    console = Mock()
    panel = Mock(return_value="panel")
    monkeypatch.setattr(main, "RICH_AVAILABLE", True)
    monkeypatch.setattr(main, "_console", console)
    monkeypatch.setattr(main, "Panel", panel)

    main._print_panel("标题", "正文")

    panel.assert_called_once_with("正文", title="标题", border_style="blue", padding=(1, 2))
    console.print.assert_called_once_with("panel")


def test_main_selects_info_interactive_and_default_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_env = Mock()
    print_info = Mock()
    run_interactive = Mock()
    print_hello = Mock()
    monkeypatch.setattr("my_ai_employee.core.config.load_env", load_env)
    monkeypatch.setattr(main, "print_info", print_info)
    monkeypatch.setattr(main, "run_interactive", run_interactive)
    monkeypatch.setattr(main, "print_hello", print_hello)

    assert main.main(["--info"]) == 0
    assert main.main(["--interactive"]) == 0
    assert main.main([]) == 0

    assert load_env.call_count == 3
    print_info.assert_called_once_with()
    run_interactive.assert_called_once_with()
    print_hello.assert_called_once_with()


def test_run_interactive_explains_current_availability(capsys: pytest.CaptureFixture[str]) -> None:
    main.run_interactive()

    assert "尚未实现" in capsys.readouterr().out
