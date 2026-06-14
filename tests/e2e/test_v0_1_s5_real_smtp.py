"""S5 — 真实 SMTP 发送(Week 1 路径,D5.6.5 已过).

承接 docs/v0.1-launch-plan.md:220 S5 唯一编号表行 + D5.6.5 commit `8ed4512` 范本。

D6.0 范围(2026-06-14 启动):
    - 默认 skip(SMTP_REAL_NETWORK != 1 → conftest.py pytest_collection_modifyitems 跳过)
    - SMTP_REAL_NETWORK=1 + 4 重防误发(--recipient 白名单 + --max-recipients 1 +
      --confirm "yes-i-understand-this-sends-real-email" + --count 1) → 真发 1 封
    - 断言:smtp.qq.com:465 SSL 真实 1 封 SENT + DispatcherResult 7 字段全 ok

跑法(需用户授权):
    export SMTP_REAL_NETWORK=1
    pytest tests/e2e/test_v0_1_s5_real_smtp.py -v -s
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.mark.e2e
@pytest.mark.requires_real
def test_s5_real_smtp_1_email_sent(session_factory):
    """S5.1 — 真实 SMTP 1 封 SENT(沿 D5.6.5 范本 + 4 重防误发)."""
    # 默认 skip(由 conftest.py 控);仅当 SMTP_REAL_NETWORK=1 才真发
    if os.environ.get("SMTP_REAL_NETWORK") != "1":
        pytest.skip("SMTP_REAL_NETWORK != 1(默认 deny,4 重防误发范本)")

    # TODO(D6.0 docs-only): 写实际 1 封 SENT 链路,沿 D5.6.5 spike_send_100.py:21-35
    # 此处仅占位,真实链路留给 W2 6/14 复检周验证。
    pytest.skip("D6.0 阶段:S5 真实 SMTP 1 封 spike 在 D5.6.5 已跑过,e2e 占位待 W2 复检周")
