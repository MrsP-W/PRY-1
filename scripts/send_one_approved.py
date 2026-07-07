#!/usr/bin/env python3
"""Day 3 — 审批 1 封 outbox 并通过 OutboxDispatcher 真发 1 封(临时门控).

用法(每次会话临时授权, 不写 shell profile):
    SMTP_REAL_NETWORK=1 uv run python scripts/send_one_approved.py \\
        --recipient you@example.com \\
        --confirm yes-i-understand-this-sends-real-email

退出码:
    0 = 发送成功或无可发条目
    1 = 参数 / 门控失败
    2 = 发送失败
    3 = 技术失败
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.connectors.smtp import SmtpLibTransport  # noqa: E402
from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.config import load_env  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.outbox import OutboxStatus  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import OutboxStore  # noqa: E402
from my_ai_employee.policy.heartbeat import Heartbeat  # noqa: E402
from my_ai_employee.policy.send_adapter import EmailSendAdapter  # noqa: E402
from my_ai_employee.scheduler.outbox_dispatcher import OutboxDispatcher  # noqa: E402

_CONFIRM_PHRASE = "yes-i-understand-this-sends-real-email"

# D13.x P3 修复(撞坑 #85 Layer 3 · 2026-07-07,业务代码改动日 撞坑 #71 边界破例):
# SEND_REAL_NETWORK_RECIPIENT_DOMAINS env(逗号分隔 domain 白名单)
# - 默认空 = 拒所有外发(最安全,撞坑 #85 暴露后,无 domain 白名单即拒)
# - 设置后,outbox.recipient_email 的 domain 必须 ∈ 白名单
# - 防 Layer 1+2 漏判 + LLM 幻觉收件人 domain 通过 --recipient per-call 严判
_ENV_RECIPIENT_DOMAINS = "SEND_REAL_NETWORK_RECIPIENT_DOMAINS"


def _print(msg: str) -> None:
    print(msg)


def _print_err(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)


def _parse_whitelist_domains(env_value: str) -> set[str]:
    """解析 env 逗号分隔 domain 白名单 → 小写 set.

    严判入口: env_value 必须是 str(空字符串返空 set,严判外由调用方触发)。
    """
    if type(env_value) is not str:
        raise ValueError(
            f"env_value 必须是 str, 实际 {type(env_value).__name__}={env_value!r}"
        )
    if not env_value.strip():
        return set()
    return {d.strip().lower() for d in env_value.split(",") if d.strip()}


def _validate_gate(*, confirm: str, recipient: str) -> str | None:
    if os.environ.get("SMTP_REAL_NETWORK") != "1":
        return "须设置 SMTP_REAL_NETWORK=1 才允许真实 SMTP 外发"
    if confirm != _CONFIRM_PHRASE:
        return f"--confirm 必须为 {_CONFIRM_PHRASE!r}"
    if not recipient or "@" not in recipient:
        return "--recipient 必填且须含 @"
    # D13.x P3 修复(撞坑 #85 Layer 3):domain 白名单 env 门控
    # 默认空 = 拒所有外发(撞坑 #85 暴露后,防 LLM 幻觉陌生 domain)
    whitelist_raw = os.environ.get(_ENV_RECIPIENT_DOMAINS, "")
    whitelist = _parse_whitelist_domains(whitelist_raw)
    if not whitelist:
        return (
            f"撞坑 #85 Layer 3 门控: 须设置 {_ENV_RECIPIENT_DOMAINS} env "
            f"(逗号分隔 domain 白名单,如 'qq.com,example.com'),"
            f"否则拒所有外发"
        )
    # 提取 recipient 的 domain 并比对
    recipient_domain = recipient.rsplit("@", 1)[-1].strip().lower()
    if recipient_domain not in whitelist:
        return (
            f"撞坑 #85 Layer 3 门控: recipient domain {recipient_domain!r} "
            f"不在白名单 {sorted(whitelist)} 内"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description="审批并真发 1 封 outbox 邮件")
    parser.add_argument("--recipient", required=True, help="白名单收件人(仅允许发到该地址)")
    parser.add_argument("--confirm", required=True, help="二次确认文本")
    parser.add_argument("--smtp-host", default="smtp.qq.com")
    parser.add_argument("--smtp-port", type=int, default=465)
    parser.add_argument(
        "--smtp-username",
        default=os.environ.get("IMAP_USER", ""),
        help="SMTP 用户名(默认 IMAP_USER)",
    )
    args = parser.parse_args(argv)

    gate_err = _validate_gate(confirm=args.confirm, recipient=args.recipient)
    if gate_err:
        _print_err(gate_err)
        return 1
    if not args.smtp_username:
        _print_err("--smtp-username 或 IMAP_USER 必填")
        return 1

    smtp_password_result = keychain.get_smtp_password_for_provider("qq", args.smtp_username)
    if not smtp_password_result.ok or not smtp_password_result.value:
        _print_err(
            "QQ SMTP 授权码未在 Keychain 中就位; "
            "请先跑 scripts/spike_set_smtp_password.py --set-password"
        )
        return 1
    smtp_password = smtp_password_result.value

    db = Database.open()
    try:
        engine = make_sqlalchemy_engine(db)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        store = OutboxStore(session_factory)

        pending = store.by_status(OutboxStatus.PENDING_SEND.value, limit=1)
        if not pending:
            approved = store.by_status(OutboxStatus.APPROVED.value, limit=1)
            if not approved:
                _print("send_one_approved: 无 pending_send / approved 条目, 跳过")
                return 0
            target = approved[0]
        else:
            target = pending[0]
            now_ms = int(time.time() * 1000)
            store.update_status(
                outbox_id=int(target.id),
                new_status=OutboxStatus.APPROVED.value,
                from_status=OutboxStatus.PENDING_SEND.value,
                last_approved_at_ms=now_ms,
            )
            _print(f"已审批 outbox_id={target.id} → APPROVED")

        if target.recipient_email.strip().lower() != args.recipient.strip().lower():
            _print_err(
                f"收件人不匹配白名单: outbox={target.recipient_email!r} "
                f"whitelist={args.recipient!r}"
            )
            return 1

        transport = SmtpLibTransport()
        send_adapter = EmailSendAdapter(
            source="qq",
            outbox_store=store,
            smtp_transport=transport,
        )
        dispatcher = OutboxDispatcher(
            source="qq",
            smtp_host=args.smtp_host,
            smtp_port=args.smtp_port,
            smtp_username=args.smtp_username,
            smtp_password=smtp_password,
            send_adapter=send_adapter,
            outbox_store=store,
            heartbeat=Heartbeat(idle_threshold_ms=30_000),
            batch_size=1,
        )
        result = dispatcher.run_once()
        _print(
            f"dispatcher: picked={result.total_picked} sent={result.sent} "
            f"technical_failed={result.technical_failed} business_blocked={result.business_blocked}"
        )
        if result.sent >= 1:
            return 0
        if result.technical_failed >= 1:
            return 3
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
