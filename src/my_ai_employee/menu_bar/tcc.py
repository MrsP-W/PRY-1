"""D9.5 — macOS TCC(Transparency, Consent, and Control)权限异常 + 引导 helper.

承接 docs/v0.1-launch-plan.md §D9.5 + plan §4 C4:
    - 异常类: TCCPermissionError(op, reason) — 当 pynput 启动失败/无权限时 raise
    - helper : open_privacy_settings(op) → int,返回 subprocess 退出码

设计要点(沿 D4.7.3 v1.0.5 强一致契约 + 2026-06-15 plan §4 C4 决策 5):
    - TCCPermissionError 双层防御(工厂层 raise + `__post_init__` 兜底)
    - 严判 type is str(防 bool 子类陷阱,沿 D4.7.3 v1.0.5 P1 范本)
    - op 必 ∈ {Accessibility, Automation, FullDiskAccess, InputMonitoring}
      4 类白名单(严判 `if op not in {...}`,沿 D4.7.2 v1.0.8 P1)
    - 严判 macOS 系统(sys.platform == "darwin",否则 raise OSError,沿
      D4.7.3 v1.0.5 异常统一)
    - URL 协议: x-apple.systempreferences:com.apple.preference.security?Privacy_{op}
      (macOS 13+ 工作,本轮仅 Apple Silicon 实测,Intel 留 A 类)
    - subprocess.run 透传 raise,不静默吞(沿 D4.7.3 v1.0.5 P3 范本)

D4.7.3 教训应用:
    - 异常类型统一 (TCCPermissionError 继承 RuntimeError,业务层可直接
      `except RuntimeError as e: ...` 不必引入新类型层)
    - type 严判 (拒 bool 子类陷阱,沿 v1.0.5 P1 范本)
    - 公开 API 入口必加 strip() 严判语义非空(防 Exception(" ") str() 后绕过)
    - 工厂层 + 数据类 __post_init__ 双层防御(沿 v1.0.5 范本)

不做:
    - 不 mock sys.platform(测试用 monkeypatch)
    - 不重试 URL 协议(单次打开即可,失败让用户手动去系统设置)
    - 不返回 status(沿 D4.7.3 v1.0.5:bool 不返回具体状态码,仅 returncode int)
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

# ===== TCC op 白名单(macOS 4 类典型授权)=====

_TCC_OPS: frozenset[str] = frozenset(
    {"Accessibility", "Automation", "FullDiskAccess", "InputMonitoring"}
)

# URL 协议模板(macOS 13+ 工作,沿 D5 AppleScript 4 坑 + 2026-06-15 计划)
_TCC_PRIVACY_URL_TEMPLATE: str = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_{op}"
)


# ===== 异常类(沿 D4.7.3 v1.0.5 双层防御)=====


@dataclass
class TCCPermissionError(RuntimeError):
    """macOS TCC 授权被拒(沿 D4.7.3 公共异常基类 RuntimeError 范本).

    Attributes:
        op: 授权类别,必 ∈ {_TCC_OPS} 4 类
        reason: 拒绝原因字符串(pynput 启动失败 / 显式 raise 等)
    """

    op: str
    reason: str

    def __post_init__(self) -> None:
        """双层防御:严判 type 严判 / 范围 / strip() 语义非空(沿 v1.0.5 P1/P2)."""
        # 严判 type(拒 bool/int 混入)
        if type(self.op) is not str:
            raise ValueError(f"op 必须是 str, 实际 {type(self.op).__name__}")
        if type(self.reason) is not str:
            raise ValueError(f"reason 必须是 str, 实际 {type(self.reason).__name__}")
        # 严判 op 白名单
        if self.op not in _TCC_OPS:
            raise ValueError(f"op 必 ∈ {sorted(_TCC_OPS)}, 实际 {self.op!r}")
        # 严判 reason 语义非空
        if not self.reason.strip():
            raise ValueError("reason 必填非空白字符串")
        # 调 RuntimeError.__init__ 让 raise TCCPermissionError(op, reason)
        # 时,str(e) 输出 reason(沿 D4.7.3 范本)
        super().__init__(self.reason)


# ===== 公开 API(顶层 API 自防御)=====


def open_privacy_settings(op: str = "Accessibility") -> int:
    """打开 macOS 系统设置 → 隐私与安全性 → 指定 op 授权页.

    Args:
        op: 授权类别,4 类之一(Accessibility / Automation / FullDiskAccess
            / InputMonitoring)

    Returns:
        subprocess 退出码(0 = 成功打开 URL)

    Raises:
        ValueError: op 非法(非 str 或非 4 类之一)或不在 macOS 系统
        OSError: 严判 sys.platform == "darwin"(沿 D4.7.3 v1.0.5)
    """
    # 严判 type + 白名单
    if type(op) is not str:
        raise ValueError(f"op 必须是 str, 实际 {type(op).__name__}")
    if op not in _TCC_OPS:
        raise ValueError(f"op 必 ∈ {sorted(_TCC_OPS)}, 实际 {op!r}")
    # 严判 macOS
    if sys.platform != "darwin":
        raise OSError(
            f"TCC 引导仅 macOS 可用(sys.platform={sys.platform!r}),非 darwin 系统请手动授权"
        )
    # 构造 URL + 调 subprocess 打开
    url = _TCC_PRIVACY_URL_TEMPLATE.format(op=op)
    result = subprocess.run(  # noqa: S603 — URL 协议由 op 白名单守护,eval 风险为零
        ["open", url],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return int(result.returncode)


__all__ = [
    "TCCPermissionError",
    "open_privacy_settings",
    "subprocess",
]
