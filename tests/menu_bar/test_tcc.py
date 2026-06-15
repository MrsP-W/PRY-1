"""D9.5 — TCC 异常 + open_privacy_settings 测试(4 cases).

承接 D9.5 plan §4 C4:
  - TCCPermissionError 严判:type is str / op 白名单 / reason 语义非空
  - open_privacy_settings 严判:op 白名单 + macOS 系统 + 透传 subprocess
  - URL 协议: x-apple.systempreferences:com.apple.preference.security?Privacy_{op}

D4.7.3 范本:
  - type 严判(拒 bool/int 陷阱,沿 v1.0.5 P1)
  - strip() 严判语义非空(沿 v1.0.5 P2)
  - 异常类型统一 (RuntimeError 基类 + ValueError 边界)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# ===== T1. 异常类合法构造 =====


def test_tcc_permission_denied_valid_construction() -> None:
    """T1: op ∈ {Accessibility, Automation, FullDiskAccess, InputMonitoring} + reason 非空白 → 正常构造."""
    from my_ai_employee.menu_bar.tcc import TCCPermissionError

    exc = TCCPermissionError(op="Accessibility", reason="辅助功能未授权")
    assert exc.op == "Accessibility"
    assert exc.reason == "辅助功能未授权"
    assert str(exc) == "辅助功能未授权"  # 沿 D4.7.3 范本 RuntimeError.__init__(reason)
    # 异常类型统一 (RuntimeError 基类,业务层 except RuntimeError 可接)
    assert isinstance(exc, RuntimeError)


# ===== T2. 异常类 op 白名单严判 =====


def test_tcc_permission_denied_op_whitelist() -> None:
    """T2: op ∉ 白名单 4 类 → ValueError("op 必 ∈ ...")."""
    from my_ai_employee.menu_bar.tcc import TCCPermissionError

    with pytest.raises(ValueError, match="op 必 ∈"):
        TCCPermissionError(op="Bluetooth", reason="test")  # type: ignore[arg-type]


# ===== T3. 异常类 reason 语义非空严判 =====


def test_tcc_permission_denied_reason_nonempty() -> None:
    """T3: reason 是 "" / "   " / 非 str → ValueError(沿 D4.7.3 v1.0.5 P2 范本)."""
    from my_ai_employee.menu_bar.tcc import TCCPermissionError

    # 空字符串
    with pytest.raises(ValueError, match="reason 必填非空白"):
        TCCPermissionError(op="Automation", reason="")
    # 纯空白
    with pytest.raises(ValueError, match="reason 必填非空白"):
        TCCPermissionError(op="Automation", reason="   \t\n")
    # 非 str
    with pytest.raises(ValueError, match="reason 必须是 str"):
        TCCPermissionError(op="Automation", reason=123)  # type: ignore[arg-type]


# ===== T4. open_privacy_settings 严判 + URL 协议 =====


def test_open_privacy_settings_url_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """T4: open_privacy_settings 在 macOS 调 `open <URL>` + return subprocess returncode."""
    from my_ai_employee.menu_bar import tcc as tcc_module

    # mock sys.platform=darwin + subprocess.run
    monkeypatch.setattr(sys, "platform", "darwin")
    mock_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr(tcc_module.subprocess, "run", mock_run)

    rc = tcc_module.open_privacy_settings(op="Accessibility")

    assert rc == 0
    # 验 subprocess.run 入参:open + URL
    call_args = mock_run.call_args
    assert call_args[0][0] == [
        "open",
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    ]
    assert call_args[1]["timeout"] == 10
    assert call_args[1]["capture_output"] is True


# ===== T5. open_privacy_settings 非 macOS 抛 OSError =====


def test_open_privacy_settings_rejects_non_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    """T5: sys.platform != darwin → OSError(TCC 引导仅 macOS 可用,沿 D4.7.3 范本)."""
    from my_ai_employee.menu_bar import tcc as tcc_module

    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(OSError, match="TCC 引导仅 macOS 可用"):
        tcc_module.open_privacy_settings(op="Accessibility")


# ===== T6. open_privacy_settings 非法 op 抛 ValueError =====


def test_open_privacy_settings_rejects_invalid_op() -> None:
    """T6: op 非白名单 → ValueError(op 必 ∈ ...) 早于 OSError 严判."""
    from my_ai_employee.menu_bar import tcc as tcc_module

    with pytest.raises(ValueError, match="op 必 ∈"):
        tcc_module.open_privacy_settings(op="Bluetooth")  # type: ignore[arg-type]


# ===== T7. open_privacy_settings 非 str op 抛 ValueError =====


def test_open_privacy_settings_rejects_non_str_op() -> None:
    """T7: op 非 str(int / None / list) → ValueError(拒 type 错)."""
    from my_ai_employee.menu_bar import tcc as tcc_module

    with pytest.raises(ValueError, match="op 必须是 str"):
        tcc_module.open_privacy_settings(op=42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="op 必须是 str"):
        tcc_module.open_privacy_settings(op=None)  # type: ignore[arg-type]
