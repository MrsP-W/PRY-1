"""S5 — 真实 SMTP 发送(Week 1 路径,D5.6.5 已过).

承接 docs/v0.1-launch-plan.md:220 S5 唯一编号表行 + D5.6.5 commit `8ed4512` 范本。

D6.0 范围(2026-06-14 启动):
    - 默认 skip(SMTP_REAL_NETWORK != 1 → conftest.py pytest_collection_modifyitems 跳过)
    - SMTP_REAL_NETWORK=1 但缺 CLI 临时确认标记 → fail-closed，不能把 direct pytest 当成功
    - 当前仍是占位，任何已开网络的路径均明确失败；真实 1 封链路留待实现后再启用

不要直接执行本文件来宣称真实发送成功；应由受确认的 CLI 子进程传入临时标记。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
_S5_CLI_CONFIRM_ENV = "MYAI_EMPLOYEE_S5_CLI_CONFIRMED"
_S5_CLI_CONFIRM_VALUE = "1"


@pytest.mark.e2e
@pytest.mark.requires_real
def test_s5_real_smtp_1_email_sent(session_factory: Any) -> Any:
    """S5.1 — 真实 SMTP 1 封 SENT(沿 D5.6.5 范本 + 4 重防误发)."""
    # 默认 skip(由 conftest.py 控);仅当 SMTP_REAL_NETWORK=1 才进入 fail-closed 路径。
    if os.environ.get("SMTP_REAL_NETWORK") != "1":
        pytest.skip("SMTP_REAL_NETWORK != 1(默认 deny,4 重防误发范本)")
    if os.environ.get(_S5_CLI_CONFIRM_ENV) != _S5_CLI_CONFIRM_VALUE:
        pytest.fail("S5 真实 SMTP 必须经已确认的 CLI 子 pytest 启动，direct pytest 默认拒绝")

    # TODO(D6.0 docs-only): 写实际 1 封 SENT 链路,沿 D5.6.5 spike_send_100.py:21-35
    # 占位不能被 pytest 记为成功，否则 spike CLI 会把 rc=0 误报为 PASS。
    pytest.fail("S5 真实 SMTP e2e 仍是占位实现，拒绝将其计为通过")
