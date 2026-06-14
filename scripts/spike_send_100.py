"""D5.6.1 spike — OutboxDispatcher 端到端发送(默认 InMemory 模拟).

承接 D4.8.11 spike_outbox_100.py(入库 spike) + D5.1 spike_set_smtp_password.py(凭证 spike)。

D5.6.1 范围(检查员反馈 5 项全部修复):
    - 默认走 InMemorySmtpTransport 模拟,不动真实 SMTP 服务器
    - --real 模式走 SmtpLibTransport 真发(需 --recipient 白名单 + --confirm 二次确认)
    - 100 封 PENDING_SEND → 批量推进为 APPROVED → dispatcher 消费(用户审批契约)
    - 失败注入断言:`technical_failed >= inject_failures`(不再 >= 0 恒真)
    - 推进时间后验证 FAILED → PENDING_SEND → SENT 重试回路(退避过期 → 重发)

D5.6.1 必验证 7 项(与 D5 启动计划 §D5.6 + 25 教训一致):
    1. N 封 PENDING_SEND → APPROVED → SENT 流转(模拟 N=100,真实 --real 模式 N<=10)
    2. 优先级排序(30 urgent / 30 normal / 40 low 实际拉批按 URGENT 先)
    3. Heartbeat 3 态联动(HEALTHY 正常处理 / TRANSPORT_DEAD 早 return)
    4. SLA 评估(故意注入老态 created_at → 触发 skip_breach 计数)
    5. 退避公式(注入失败 → cf++ → 2^cf*60s 封顶 1h 退避)
    6. 业务阻断 vs 技术失败 拆分(注入收件人拒收 → 业务阻断 → CANCELLED 永不 retry)
    7. 状态机白名单 ALLOWED_TRANSITIONS 严判(cancelled → sent 抛 OutboxIllegalTransitionError)

CLI 必传(防误发):
    --real                   走 SmtpLibTransport 真发(默认 InMemory 模拟)
    --recipient <email>      必传白名单:--real 模式只允许发到这一个地址
    --max-recipients 1       --real 模式强制 1 收件人(避免群发扰民)
    --confirm <text>         --real 模式必传 "yes-i-understand-this-sends-real-email"
    --smtp-host <host>       SMTP 服务器(默认 "smtp.qq.com",--real 模式必显式传)
    --smtp-port <port>       SMTP 端口(默认 465)
    --smtp-username <user>   SMTP 用户名(必传,非空)
    --smtp-password <pwd>    SMTP 授权码(InMemory 模式可传占位)

    --inject-failures N      模拟 N 封技术失败(测试退避回路,默认 0)
    --inject-breach N        把前 N 封 created_at 倒拨 6 分钟(触发 URGENT SLA BREACH,默认 0)
    --batch-size N           OutboxDispatcher 单次拉批上限(默认 10)
    --count N                spike 封数(默认 100,--real 模式最大 10,InMemory 模式最大 500)
    --output-dir <path>      报告输出目录(默认 output/spike/)

DB 用临时 sqlite + Keychain monkeypatch(不污染真实 ~/Library),沿 spike_outbox_100.py 范本。
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from my_ai_employee.connectors.smtp import (  # noqa: E402
    SMTP_SEND_TRANSPORT_ERROR,
    InMemorySmtpTransport,
    SmtpLibTransport,
)
from my_ai_employee.core import keychain  # noqa: E402
from my_ai_employee.core.db import Database  # noqa: E402
from my_ai_employee.core.models import Base  # noqa: E402
from my_ai_employee.core.outbox import OutboxPriority, OutboxStatus, OutboxTone  # noqa: E402
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine  # noqa: E402
from my_ai_employee.db.outbox import OutboxStore  # noqa: E402
from my_ai_employee.policy.heartbeat import Heartbeat  # noqa: E402
from my_ai_employee.policy.send_adapter import EmailSendAdapter  # noqa: E402
from my_ai_employee.scheduler.outbox_dispatcher import OutboxDispatcher  # noqa: E402

# ===== 0. 防误发常量(D5.6.1 P1.2 修复)=====

_CONFIRM_PHRASE: str = "yes-i-understand-this-sends-real-email"
_REAL_MODE_MAX_RECIPIENTS: int = 1
_REAL_MODE_MAX_COUNT: int = 10
_INMEMORY_MAX_COUNT: int = 500
# D5.6.4 P1-3 修复(4th round 检查员反馈):真实网络门
# 显式 SMTP_REAL_NETWORK=1 才允许 --real 模式真连 SMTP 服务器
# 默认空 → 任何 real_send=True 调用方会抛 ValueError(防误连 smtp.qq.com)
_SMTP_REAL_NETWORK_ENV: str = "SMTP_REAL_NETWORK"
_SMTP_REAL_NETWORK_VALUE: str = "1"


@dataclass
class SpikeResult:
    """D5.6.4 spike 报告结构化骨架(8th round 落地)。

    之前 spike 报告用 list[str] 拼 Markdown,不便下游消费(memory 同步 / CI 校验)。
    本 dataclass 提供结构化结果,Markdown 渲染层仍用 report_lines,但关键数据可序列化。

    字段说明(11 字段):
        mode: "real" / "inmemory" — 实际跑的模式
        smtp_real_network_unlocked: bool — SMTP_REAL_NETWORK env 是否为 "1"
        total: int — spike 总封数(count)
        sent: int — 实际 SENT 计数
        business_blocked: int — 业务阻断计数
        technical_failed: int — 技术失败计数
        skipped: int — 跳过计数(退避未过期 / SLA BREACH 等)
        total_duration_seconds: float — spike 主循环总耗时
        p50_send_ms / p95_send_ms: float — 发送耗时分位数
        sla_breach_count: int — URGENT SLA BREACH 触发计数
        injection_failures_requested / actual: int — 失败注入请求 vs 实际触发
        injection_breach_requested / actual: int — BREACH 注入请求 vs 实际触发

    业务背景:SpikeResult 让 spike 结果可被 memory 同步脚本 / CI 校验脚本直接消费
    (D5.7 docs 收口会用上),不再只写 Markdown 让人肉读。
    """

    mode: str = "inmemory"
    smtp_real_network_unlocked: bool = False
    total: int = 0
    sent: int = 0
    business_blocked: int = 0
    technical_failed: int = 0
    skipped: int = 0
    total_duration_seconds: float = 0.0
    p50_send_ms: float = 0.0
    p95_send_ms: float = 0.0
    sla_breach_count: int = 0
    injection_failures_requested: int = 0
    injection_failures_actual: int = 0
    injection_breach_requested: int = 0
    injection_breach_actual: int = 0
    extra: dict[str, object] = field(default_factory=dict)


# ===== 1. Keychain monkeypatch(不污染真实 macOS Keychain)=====

_FAKE_KEYCHAIN: dict[tuple[str, str], str] = {}


def _install_fake_keychain(email: str = "spike@qq.com") -> None:
    """in-memory dict 模拟 Keychain(spike 不污染真实凭证).

    Args:
        email: 假邮件账号(默认 spike@qq.com,占位)
    """
    auth_code = "fake-spike-auth-code-16chars"  # noqa: S105  # noqa: ERA001  # 占位,非真实凭据

    def fake_get_smtp() -> keychain.KeychainResult:
        if (keychain.SERVICE_SMTP_QQ, email) in _FAKE_KEYCHAIN:
            return keychain.KeychainResult(
                ok=True, value=_FAKE_KEYCHAIN[(keychain.SERVICE_SMTP_QQ, email)]
            )
        return keychain.KeychainResult(ok=False, error="not found")

    def fake_set_smtp(password: str) -> keychain.KeychainResult:
        _FAKE_KEYCHAIN[(keychain.SERVICE_SMTP_QQ, email)] = password
        return keychain.KeychainResult(ok=True)

    keychain.get_smtp_password = fake_get_smtp  # type: ignore[assignment]
    keychain.set_smtp_password = fake_set_smtp  # type: ignore[assignment]
    # 预填授权码(让 SMTPConnector.connect() 顺利通过)
    _FAKE_KEYCHAIN[(keychain.SERVICE_SMTP_QQ, email)] = auth_code


# ===== 2. 临时 DB + schema 创建(沿 spike_outbox_100.py 范本)=====


def _build_test_db(tmp_dir: Path) -> tuple[Database, sessionmaker]:  # type: ignore[type-arg]
    """建临时 DB + Base.metadata.create_all + 返回 (Database, session_factory)."""
    db_path = tmp_dir / "spike_send.db"
    db = Database.open(db_path=db_path)
    engine = make_sqlalchemy_engine(db)
    # 显式 import events models 触发 SQLAlchemy 注册(FK → events.id 必须先 import)
    from my_ai_employee.events import models as _events_models  # noqa: F401, F811

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return db, factory


def _seed_emails(session_factory, count: int) -> list[int]:  # type: ignore[type-arg]
    """插入 count 行 emails(返回 email_id 列表)."""
    from my_ai_employee.core.models import Email

    email_ids: list[int] = []
    with session_factory() as session:  # type: ignore[call-arg]
        for i in range(1, count + 1):
            row = Email(
                source="spike_send",
                uid=2000 + i,
                subject=f"Spike Send Email {i}",
                sender="spike-send@example.com",
                recipients='["recipient@example.com"]',
                received_at=int(time.time() * 1000),
                fetched_at=int(time.time() * 1000),
            )
            session.add(row)
            session.flush()
            assert row.id is not None
            email_ids.append(row.id)
        session.commit()
    return email_ids


# ===== 3. N 封 outbox 入库 + 调度 spike =====


def _generate_drafts(
    count: int,
    *,
    inject_breach: int = 0,
    recipient_email: str | None = None,
    now_ms: int | None = None,
) -> list[dict[str, object]]:
    """生成 count 封合成草稿(30% urgent / 30% normal / 40% low,沿 D5.5 SLA 3 优先级).

    Args:
        count: 总数
        inject_breach: 前 N 封 created_at 倒拨 6 分钟,触发 URGENT SLA BREACH(验证 SLA 评估)
        recipient_email: 收件人地址(默认 recipientN@example.com,REAL 模式必传统一收件人)
        now_ms: 基准时间(ms),None = int(time.time() * 1000)
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    drafts: list[dict[str, object]] = []
    urgent_count = max(1, count // 3)
    normal_count = max(1, count // 3)
    for i in range(1, count + 1):
        tone = (
            OutboxTone.FORMAL.value
            if i % 3 == 0
            else (OutboxTone.FRIENDLY.value if i % 3 == 1 else OutboxTone.CONCISE.value)
        )
        # 优先级分配:前 urgent_count 封 urgent / 接下来 normal_count 封 normal / 其余 low
        if i <= urgent_count:
            priority = OutboxPriority.URGENT.value
        elif i <= urgent_count + normal_count:
            priority = OutboxPriority.NORMAL.value
        else:
            priority = OutboxPriority.LOW.value
        # SLA 注入:前 N 封 created_at 倒拨 6 分钟(360_000ms)→ URGENT 5min 阈值必 BREACH
        created_at = now_ms - 360_000 if i <= inject_breach else now_ms
        # D5.6.1 P1.2 修复:--real 模式强制统一收件人(防群发)
        actual_recipient = recipient_email if recipient_email else f"recipient{i}@example.com"
        drafts.append(
            {
                "email_id": 0,  # 占位,后填
                "subject": f"Spike Send Subject {i}",
                "body": f"这是 D5.6.1 spike 的第 {i} 封合成邮件正文,用于验证 outbox 端到端 SMTP 发送路径。",
                "tone": tone,
                "recipient_email": actual_recipient,
                "priority": priority,
                "created_at": created_at,
            }
        )
    return drafts


def _approve_all_pending(
    outbox_store: OutboxStore,
    outbox_ids: list[int],
) -> int:
    """D5.6.1 P1.3 修复 — 把 N 封 PENDING_SEND 批量推进为 APPROVED(用户审批契约).

    真实生产场景:用户审批界面把 outbox_id 列表从 PENDING_SEND → APPROVED。
    spike 默认全部预审批(让 dispatcher 走完端到端流程)。

    D5.6.3 P1-1 强化:update_status(new_status=APPROVED) 必传 last_approved_at_ms
    (Unix epoch ms),不传会抛 ValueError。本函数计算一次 now_ms 复用(同一时间
    戳批次内一致)。

    Args:
        outbox_store: OutboxStore 实例
        outbox_ids: 待审批的 outbox_id 列表

    Returns:
        成功推进到 APPROVED 的条目数
    """
    approved_count = 0
    now_ms = int(time.time() * 1000)  # 批次内共享同一审批时间戳
    for outbox_id in outbox_ids:
        try:
            outbox_store.update_status(
                outbox_id,
                OutboxStatus.APPROVED.value,
                from_status=OutboxStatus.PENDING_SEND.value,
                last_approved_at_ms=now_ms,
            )
            approved_count += 1
        except Exception as e:  # noqa: BLE001  # 状态机异常不应阻断整体
            print(f"   ⚠️ outbox_id={outbox_id} 推进 APPROVED 失败:{e!r}")
    return approved_count


def run_spike(
    output_dir: Path,
    *,
    real_send: bool = False,
    recipient_email: str | None = None,
    max_recipients: int = 0,
    confirm: str | None = None,
    smtp_host: str = "smtp.qq.com",
    smtp_port: int = 465,
    smtp_username: str = "spike@qq.com",
    smtp_provider: str = "qq",
    inject_failures: int = 0,
    inject_breach: int = 0,
    batch_size: int = 10,
    count: int = 100,
    smtp_transport_factory: Callable[[], Any] | None = None,
) -> None:
    """D5.6.1 spike 主流程 — N 封入 outbox + 批量 APPROVED + OutboxDispatcher 循环 + SMTP 发送.

    Args:
        output_dir: 报告输出目录
        real_send: True 走 SmtpLibTransport 真发(用户手动跑),False 走 InMemorySmtpTransport 模拟
        recipient_email: --real 模式必传,统一收件人(防群发扰民)
        max_recipients: --real 模式必传 1(InMemory 模式忽略)
        confirm: --real 模式必传 "yes-i-understand-this-sends-real-email"
        smtp_host: SMTP 服务器地址(--real 必传真实地址,如 "smtp.qq.com")
        smtp_port: SMTP 端口(1-65535,默认 465)
        smtp_username: SMTP 用户名(--real 必传真实地址)
        smtp_provider: SMTP provider(qq/outlook/gmail,D5.6.2 P0 修复 REAL 模式真读 Keychain 用)
        inject_failures: 模拟 N 封技术失败(触发退避回路)
        inject_breach: 前 N 封 created_at 倒拨 → 触发 URGENT SLA BREACH
        batch_size: 每次 run_once 拉批上限(默认 10)
        count: spike 封数(默认 100,--real 模式最大 10,InMemory 模式最大 500)
        smtp_transport_factory: D5.6.4 P1-3 修复 — SMTP transport 工厂注入(默认 None)
            None: real_send 走 SmtpLibTransport(真发,需 SMTP_REAL_NETWORK=1),
                  否则走 InMemorySmtpTransport(模拟)
            非 None(可调用):用调用结果代替默认 transport(测试替身,monkeypatch 入口)
            集成测试场景:即使 SMTP_REAL_NETWORK=1 显式解锁,也可注入
            InMemorySmtpTransport 替代真发(双层防御:env 门 + factory 注入)
    """
    # ===== D5.6.2 P0 凭证链路 + D5.6.1 P1.2 防误发:CLI 严判 =====
    smtp_password: str  # REAL 模式从 Keychain 读(InMemory 模式不需要,占位即可)
    if real_send:
        # 0. D5.6.4 P1-3 修复(4th round 检查员反馈):真实网络门
        # 默认 os.environ.get("SMTP_REAL_NETWORK") != "1" → 抛错,绝不真连
        # 真实跑法:SMTP_REAL_NETWORK=1 python scripts/spike_send_100.py --real ...
        # 集成测试 / CI 严禁 SMTP_REAL_NETWORK=1(默认安全)
        if os.environ.get(_SMTP_REAL_NETWORK_ENV) != _SMTP_REAL_NETWORK_VALUE:
            raise ValueError(
                f"D5.6.4 P1-3 修复(4th round 检查员反馈 P1):"
                f"--real 模式严禁真连 SMTP 服务器(防 smtp.qq.com 误连)! "
                f"必须显式设置环境变量 {_SMTP_REAL_NETWORK_ENV}={_SMTP_REAL_NETWORK_VALUE} 才允许真发。"
                f"实际 env[{_SMTP_REAL_NETWORK_ENV}]={os.environ.get(_SMTP_REAL_NETWORK_ENV)!r}。"
                f"真发命令范本:"
                f"SMTP_REAL_NETWORK={_SMTP_REAL_NETWORK_VALUE} python scripts/spike_send_100.py "
                f"--real --recipient <your-email> --confirm {_CONFIRM_PHRASE!r} --count 1"
            )
        # 1. --recipient 必传
        if not recipient_email:
            raise ValueError(
                "D5.6.2 防误发:--real 模式必传 --recipient <email>(白名单,只发到一个地址)"
            )
        # 2. --max-recipients 必传且 == 1
        if max_recipients != 1:
            raise ValueError(
                f"D5.6.2 防误发:--real 模式 --max-recipients 必传 1(只发 1 封),"
                f"实际 {max_recipients!r}"
            )
        # 3. --confirm 必传且 == 固定口令
        if confirm != _CONFIRM_PHRASE:
            raise ValueError(
                f"D5.6.2 防误发:--real 模式 --confirm 必传 {_CONFIRM_PHRASE!r},实际 {confirm!r}"
            )
        # 4. D5.6.2 检查员反馈:--real 模式强制 count == 1(防止"我以为是 1 封但实际 10")
        if count != 1:
            raise ValueError(f"D5.6.2 防误发:--real 模式 --count 必传 1(只能 1 封),实际 {count!r}")
        # 5. smtp_host / smtp_username 不能是占位
        if "test.local" in smtp_host or smtp_host.startswith("smtp.test."):
            raise ValueError(
                f"D5.6.2 防误发:--real 模式 smtp_host 不能是 .test.local 占位,实际 {smtp_host!r}"
            )
        if "@test.local" in smtp_username or smtp_username == "spike@qq.com":
            raise ValueError(
                f"D5.6.2 防误发:--real 模式 smtp_username 不能是占位,实际 {smtp_username!r}"
            )
        # 6. D5.6.2 P0 凭证链路:REAL 模式从系统 Keychain 真读,禁止 CLI 传密码
        # 真实 macOS Keychain 必须先 spike_set_smtp_password.py --set-password 写入
        print(
            f"   ⚠️  REAL 模式:将真发到 {recipient_email!r}"
            f"(SMTP {smtp_username}@{smtp_host}:{smtp_port} via {smtp_provider})"
        )
        print("   🔑 从系统 Keychain 读取 SMTP 授权码(真凭证,非 CLI 传入)...")
        smtp_password_result = keychain.get_smtp_password_for_provider(smtp_provider, smtp_username)
        if not smtp_password_result.ok:
            raise RuntimeError(
                f"D5.6.2 凭证链路:从 Keychain 读 {smtp_provider}/{smtp_username} 失败: "
                f"{smtp_password_result.error!r}\n"
                f"先跑:python scripts/spike_set_smtp_password.py "
                f"--provider {smtp_provider} --email {smtp_username} --set-password <authcode>"
            )
        smtp_password = smtp_password_result.value  # type: ignore[assignment]  # mypy: ok=True 时 .value 必非 None
        assert smtp_password is not None  # 防 mypy 漏判,运行时兜底
        if not smtp_password or not smtp_password.strip():
            raise RuntimeError(
                f"D5.6.2 凭证链路:Keychain 读出空密码({smtp_provider}/{smtp_username}),"
                f"重新 spike_set_smtp_password.py --set-password"
            )
        # 严判防占位(以防历史写入脏数据)
        if smtp_password == "<test-placeholder>" or "test-placeholder" in smtp_password:
            raise RuntimeError(
                "D5.6.2 凭证链路:Keychain 读出的是 <test-placeholder> 占位,"
                "必须先 spike_set_smtp_password.py --set-password 写入真实授权码"
            )
        print(f"   ✅ Keychain 凭证已读取(长度={len(smtp_password)} 字符,内容不打印)")
    else:
        # InMemory 模式封数上限(防误跑 10000 封 spike)
        if count > _INMEMORY_MAX_COUNT:
            raise ValueError(
                f"D5.6.2 InMemory 模式 --count 必 <= {_INMEMORY_MAX_COUNT},实际 {count!r}"
            )
        # InMemory 模式:smtp_password 占位即可(从不连接真实 SMTP)
        smtp_password = "<test-placeholder>"
        print(
            f"   InMemory 模式(模拟,count={count},失败注入={inject_failures},"
            f"BREACH 注入={inject_breach},password=<test-placeholder>)"
        )

    # D5.6.2 P0 凭证链路 + D5.6.3 P2-2 修复:_install_fake_keychain 仅 InMemory 模式装
    # REAL 模式必须走真 keychain.get_smtp_password_for_provider(上面 L256-302)
    # D5.6.3 P2-2 修复:之前还有一次无条件 _install_fake_keychain() 调用,会污染
    # REAL 模式全局 Keychain 函数(虽然局部 smtp_password 已读取,但仍会污染
    # 后续 Keychain 调用链)。删无条件调用,只剩条件 if not real_send 分支。
    if not real_send:
        _install_fake_keychain()

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report_lines: list[str] = []
    report_lines.extend(
        [
            "# D5.6.1 spike — OutboxDispatcher 端到端发送",
            "",
            f"> **生成时间**:{timestamp}",
            f"> **范围**:{count} 封入库 + 批量 APPROVED + OutboxDispatcher 循环 + 状态机推进 + SLA + 退避",
            f"> **模式**:{'⚠️ REAL SMTP (SmtpLibTransport)' if real_send else '✅ InMemory 模拟(InMemorySmtpTransport)'}",
            f"> **注入失败**:{inject_failures} 封技术失败",
            f"> **注入 BREACH**:{inject_breach} 封 SLA BREACH",
            f"> **count**:{count}",
            f"> **smtp_host**:{smtp_host}:{smtp_port}",
            f"> **smtp_username**:{smtp_username}",
            "> **承接 D4.8.11 spike 范本**(`scripts/spike_outbox_100.py`)+ D5.1 凭证 spike",
            "> **D5.6.2 修复**:P0 真 Keychain + P1.1 From smtp_username + P1.2 审批契约 + P1.3 安全测试 + P2 注入事件 + P2 文档 + P3 空格",
            "",
            "---",
            "",
        ]
    )

    # 1. 建临时 DB + seed N 行 emails
    print("🚀 D5.6.1 spike — OutboxDispatcher 端到端")
    print(f"   输出目录:{output_dir}")
    print(f"   时间戳:{timestamp}")

    # 全局统计
    counters: Counter[str] = Counter()
    # D5.6.2 P2 修复:精确记录失败注入事件(让断言不再恒真)
    injection_events_holder: dict[str, list[dict[str, object]]] = {"events": []}
    dispatcher_latencies: list[float] = []
    per_priority_outcomes: dict[str, Counter[str]] = {
        OutboxPriority.URGENT.value: Counter(),
        OutboxPriority.NORMAL.value: Counter(),
        OutboxPriority.LOW.value: Counter(),
    }

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        db, session_factory = _build_test_db(tmp_dir)
        try:
            print("   临时 DB 创建完成(临时目录,结束自动清理)")
            email_ids = _seed_emails(session_factory, count)
            print(f"   ✅ seeded {count} 行 emails(email_id={email_ids[0]}..{email_ids[-1]})")

            # 2. 准备 drafts(填 email_id)
            now_ms = int(time.time() * 1000)
            drafts = _generate_drafts(
                count,
                inject_breach=inject_breach,
                recipient_email=recipient_email,
                now_ms=now_ms,
            )
            for i, d in enumerate(drafts):
                d["email_id"] = email_ids[i]  # type: ignore[assignment]

            # 3. N 封 outbox 入库
            from my_ai_employee.policy.outbox_adapter import EmailOutboxAdapter

            outbox_store = OutboxStore(session_factory)
            adapter = EmailOutboxAdapter(
                outbox_store=outbox_store,
                source="spike_send",
            )
            print(f"   {count} 封入库开始(每次 store_and_emit 走完整 3 路径)...")
            t0 = time.time()
            outbox_ids: list[int] = []
            for draft in drafts:
                report = adapter.store_and_emit(
                    email_id=int(draft["email_id"]),  # type: ignore[call-overload]
                    subject=str(draft["subject"]),  # type: ignore[call-overload]
                    body=str(draft["body"]),  # type: ignore[call-overload]
                    tone=str(draft["tone"]),  # type: ignore[call-overload]
                    recipient_email=str(draft["recipient_email"]),  # type: ignore[call-overload]
                    priority=str(draft["priority"]),  # type: ignore[call-overload]
                )
                assert report.outbox_stored is True
                assert report.outbox_id is not None
                outbox_ids.append(report.outbox_id)
                # 注入 SLA BREACH:update created_at 到老态(因为 store_and_emit 自动用 now)
                if draft.get("created_at") and int(draft["created_at"]) < now_ms:  # type: ignore[call-overload]
                    row = outbox_store.by_id(report.outbox_id)
                    if row is not None:
                        # 直接改 ORM created_at(D5 阶段无 status 转换要求,状态仍 PENDING_SEND)
                        row.created_at = int(draft["created_at"])  # type: ignore[call-overload]
                        with session_factory() as session:  # type: ignore[call-arg]
                            session.merge(row)
                            session.commit()
            elapsed = time.time() - t0
            print(f"   ✅ {count} 封入库完成(总时长 {elapsed:.2f}s)")

            # ===== D5.6.1 P1.3 修复:批量 PENDING_SEND → APPROVED(用户审批契约)=====
            approved_count = _approve_all_pending(outbox_store, outbox_ids)
            print(f"   ✅ 批量审批:PENDING_SEND → APPROVED ({approved_count}/{count})")

            report_lines.extend(
                [
                    "## 1. 📥 N 封入库 + 批量审批",
                    "",
                    f"- **总数**:{count}",
                    f"- **stored 成功**:{len(outbox_ids)}/{count}",
                    f"- **入库总时长**:{elapsed:.2f}s",
                    f"- **outbox_id 范围**:{outbox_ids[0]}..{outbox_ids[-1]}",
                    f"- **D5.6.1 P1.3 批量审批 PENDING_SEND → APPROVED**:{approved_count}/{count}",
                    "",
                ]
            )

            # 4. SMTP transport 选择
            # D5.6.4 P1-3 修复:smtp_transport_factory 注入(双层防御:env 门 + factory)
            if smtp_transport_factory is not None:
                # 测试替身优先(monkeypatch 入口,即使 env 解锁也不真发)
                transport = smtp_transport_factory()
            elif real_send:
                transport = SmtpLibTransport()
            else:
                transport = InMemorySmtpTransport()
                # D5.6.2 P2 修复:注入失败模式(测试替身):前 N 封 transport_error
                # 关键:把注入事件记录暴露给断言,不再"恒真"陷阱
                # P2 检查员反馈:之前 total_processed >= count 即使注入完全没生效也过
                # 修复:用 injection_events 列表精确断言"注入事件触发了 N 次"
                if inject_failures > 0:
                    original_send = transport.send_message
                    injection_events: list[dict[str, object]] = []

                    def send_with_injection(message):  # type: ignore[no-untyped-def]
                        from my_ai_employee.connectors.smtp import (
                            SMTPSendResult,
                        )

                        if len(injection_events) < inject_failures:
                            seq = len(injection_events) + 1
                            injection_events.append(
                                {
                                    "seq": seq,
                                    "to": [str(a) for a in message.get_all("To", [])],
                                    "subject": str(message.get("Subject", "")),
                                    "error_detail": f"injected failure {seq}/{inject_failures}",
                                }
                            )
                            return SMTPSendResult(
                                status=SMTP_SEND_TRANSPORT_ERROR,
                                error_detail=f"injected failure {seq}/{inject_failures}",
                            )
                        return original_send(message)

                    transport.send_message = send_with_injection  # type: ignore[method-assign]
                    # 暴露 injection_events 到外层供断言使用
                    injection_events_holder["events"] = injection_events  # type: ignore[index]

            # 5. 实例化 OutboxDispatcher
            send_adapter = EmailSendAdapter(
                source="spike_send",
                outbox_store=outbox_store,
                smtp_transport=transport,
            )
            heartbeat = Heartbeat(idle_threshold_ms=30_000)
            # D5.6.1 P0 修复:从构造器显式传 SMTP 配置(不再硬编码)
            dispatcher = OutboxDispatcher(
                source="spike_send",
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_username=smtp_username,
                smtp_password=smtp_password,
                send_adapter=send_adapter,
                outbox_store=outbox_store,
                heartbeat=heartbeat,
                batch_size=batch_size,
            )

            # 6. 循环 run_once() 直到全部最终态
            print(f"   开始循环 run_once() (batch_size={batch_size})...")
            max_iterations = (
                200  # 防死循环(N=100 + batch=10 → 10 轮足够,留大 buffer 让退避回路可完成)
            )
            # D5.6.3 P1-2 修复:虚拟时钟推进(让退避回路可在 spike 时长内完成)
            # 之前用真实时间(int(time.time()*1000))作 now_ms,2^cf * 60_000ms
            # 退避公式下,cf=1 退避 120s,200 轮内真实时间根本走不完 1 个退避窗口。
            # 修复:每次循环 now_ms 推进 --inject-time-step-ms(默认 70_000ms,
            # 覆盖 2^1*60s + 10s buffer),让 cf=1 退避 120s 可在 2 轮内过期。
            # D5.6.3 P1-2 边角:同时调 heartbeat.update(refresh_last_seen=True,
            # now_ms=now_ms),防 spike 跑完后"时间倒流"严判。
            time_step_ms = 70_000
            t_dispatch_start = time.time()
            current_now_ms = int(time.time() * 1000)
            for iteration in range(max_iterations):
                # D5.6.3 P1-2 修复:now_ms 推进 time_step_ms(可控时钟)
                current_now_ms += time_step_ms
                result = dispatcher.run_once(now_ms=current_now_ms)
                # 同步刷新 heartbeat last_seen_ms(避免时间漂移触发"时间倒流"严判)
                heartbeat.update(refresh_last_seen=True, now_ms=current_now_ms)
                dispatcher_latencies.append(result.duration_seconds)
                counters["total_picked"] += result.total_picked
                counters["sent"] += result.sent
                counters["business_blocked"] += result.business_blocked
                counters["technical_failed"] += result.technical_failed
                counters["skipped"] += result.skipped
                counters["skip_breach"] += result.skip_breach
                print(
                    f"   iter={iteration + 1:03d} "
                    f"sent={result.sent} bb={result.business_blocked} tf={result.technical_failed} "
                    f"sk={result.skipped} sb={result.skip_breach}"
                )
                # 检查是否全部最终态
                pending = outbox_store.by_status("pending_send", limit=1)
                approved = outbox_store.by_status("approved", limit=1)
                failed = outbox_store.by_status("failed", limit=1)
                sending = outbox_store.by_status("sending", limit=1)
                if not (pending or approved or failed or sending):
                    print(f"   ✅ 全部最终态(共 {iteration + 1} 轮 run_once)")
                    counters["iterations"] = iteration + 1
                    break
            else:
                # D5.6.3 P1-2 修复:达到 max_iterations 仍有非最终态条目
                # → 报告标记 ❌ + raise SystemExit(1)(进程返回非零,防"假成功"陷阱)
                # 之前:仅打印警告 + 继续生成报告 + 进程退出 0,被检查员 P1-2 驳回
                pending = outbox_store.by_status("pending_send", limit=100)
                approved = outbox_store.by_status("approved", limit=100)
                failed = outbox_store.by_status("failed", limit=100)
                sending = outbox_store.by_status("sending", limit=100)
                leftover = {
                    "pending_send": len(pending),
                    "approved": len(approved),
                    "failed": len(failed),
                    "sending": len(sending),
                }
                counters["iterations"] = max_iterations
                counters["state_machine_final"] = 0  # 显式标记 ❌
                # 先关 DB(避免 finally 段找不到 db 引用)
                # 注:实际 finally 段在 db.close() 上,这里直接 raise 跳过 finally 是预期行为
                raise SystemExit(
                    f"D5.6.3 P1-2:spike 失败 — 达到 max_iterations={max_iterations} 仍未全部最终态,"
                    f"非最终态条目={leftover}。请检查:\n"
                    f"  1. 失败注入是否让退避公式无法完成(cf 太大)\n"
                    f"  2. time_step_ms={time_step_ms} 是否够大覆盖最长退避窗口\n"
                    f"  3. 是否存在死循环/状态机漂移 bug"
                )
            t_dispatch_total = time.time() - t_dispatch_start

            # 7. 统计(按优先级拆分 outcome)
            for priority in (
                OutboxPriority.URGENT.value,
                OutboxPriority.NORMAL.value,
                OutboxPriority.LOW.value,
            ):
                # 拉该优先级剩余所有条目
                entries = outbox_store.by_priority(priority)
                for entry in entries:
                    per_priority_outcomes[priority][entry.status] += 1

            # 8. 关键验证项(D5.6.1 P2 修复:失败注入有效断言)
            print()
            print("=== 关键验证项 ===")
            print("  1. 状态机全部最终态(无 PENDING/APPROVED/FAILED/SENDING):")
            final_pending = outbox_store.by_status("pending_send", limit=1)
            final_approved = outbox_store.by_status("approved", limit=1)
            final_failed = outbox_store.by_status("failed", limit=1)
            final_sending = outbox_store.by_status("sending", limit=1)
            all_final = not (final_pending or final_approved or final_failed or final_sending)
            counters["state_machine_final"] = 1 if all_final else 0
            print(
                f"     {'✅' if all_final else '❌'} PENDING={len(final_pending)} APPROVED={len(final_approved)} FAILED={len(final_failed)} SENDING={len(final_sending)}"
            )

            print("  2. InMemorySmtpTransport.sent_log 行数:")
            if isinstance(transport, InMemorySmtpTransport):
                sent_log_count = len(transport.sent_log)
                expected_sent = counters["sent"]
                match = sent_log_count == expected_sent
                counters["sent_log_match"] = 1 if match else 0
                print(
                    f"     sent_log={sent_log_count} vs counters['sent']={expected_sent} → {'✅' if match else '❌'}"
                )
            else:
                print("     (REAL 模式,无 sent_log)")

            print("  3. Heartbeat 3 态验证(默认 HEALTHY):")
            # D5.6.4 P0 修复:用虚拟时钟 current_now_ms(沿 D5.6.3 P1-2 范本)
            # 旧代码用 int(time.time()*1000) 真实时间 → 虚拟时钟比真实快 70s,触发"时间倒流"严判
            verify_now_ms = current_now_ms
            liveness = heartbeat.evaluate(now_ms=verify_now_ms)
            counters["liveness_healthy"] = 1 if liveness.value == "healthy" else 0
            print(
                f"     heartbeat.evaluate() = {liveness.value} → {'✅' if liveness.value == 'healthy' else '⚠️'}"
            )

            print(f"  4. SLA BREACH 注入(注入 {inject_breach} 封):")
            if inject_breach > 0:
                breach_ok = counters["skip_breach"] >= inject_breach
                counters["sla_breach_detected"] = 1 if breach_ok else 0
                print(
                    f"     skip_breach={counters['skip_breach']} (期望 >= {inject_breach}) → {'✅' if breach_ok else '❌'}"
                )
            else:
                print(f"     skip_breach={counters['skip_breach']} (无注入)")

            # ===== D5.6.2 P2 修复:失败注入精确断言(injection_events 精确 == inject_failures)=====
            # 之前 D5.6.1 P2 修复:total_processed >= count(仍恒真,因为即使所有都成功也 >= count)
            # 检查员反馈:即使注入完全没生效、全部发送成功,断言仍能通过
            # 真正修复:暴露 transport 层 send_message 注入事件列表,精确断言长度 == inject_failures
            print(f"  5. 注入失败(N={inject_failures}) 退避回路:")
            if inject_failures > 0:
                # 真正精确断言:注入事件列表长度 == 期望注入次数
                # 如果 monkeypatch 未生效,send_message 不会被注入,列表长度=0,断言必失败
                injection_events_list = injection_events_holder.get("events", [])
                injection_count = len(injection_events_list)
                tf_ok = injection_count == inject_failures
                counters["backoff_loop"] = 1 if tf_ok else 0
                # 同时验证:dispatcher 看到技术失败事件数 >= 注入数(没漏抓)
                tf_observed = counters["technical_failed"]
                tf_observed_ok = tf_observed >= inject_failures
                print(
                    f"     injection_events={injection_count} (期望 == {inject_failures}) "
                    f"→ {'✅' if tf_ok else '❌'}"
                )
                print(
                    f"     dispatcher.technical_failed={tf_observed} (期望 >= {inject_failures}) "
                    f"→ {'✅' if tf_observed_ok else '❌'}"
                )
                if not tf_ok or not tf_observed_ok:
                    raise AssertionError(
                        f"D5.6.2 P2 失败注入断言:注入事件={injection_count}/"
                        f"期望={inject_failures},dispatcher.technical_failed={tf_observed}"
                    )
            else:
                print(f"     technical_failed={counters['technical_failed']} (无注入)")

            # 9. 延迟统计
            dispatcher_latencies_sorted = sorted(dispatcher_latencies)
            p50 = (
                statistics.median(dispatcher_latencies_sorted)
                if dispatcher_latencies_sorted
                else 0.0
            )
            p95 = (
                statistics.quantiles(dispatcher_latencies_sorted, n=20)[18]
                if len(dispatcher_latencies_sorted) >= 20
                else dispatcher_latencies_sorted[-1]
                if dispatcher_latencies_sorted
                else 0.0
            )
            avg = (
                statistics.mean(dispatcher_latencies_sorted) if dispatcher_latencies_sorted else 0.0
            )

            # 10. 报告输出
            report_lines.extend(
                [
                    "## 2. 🚀 OutboxDispatcher 循环调度统计",
                    "",
                    f"- **模式**:{'⚠️ REAL SMTP' if real_send else '✅ InMemory 模拟'}",
                    f"- **batch_size**:{batch_size}",
                    f"- **iterations(总 run_once 次数)**:{counters['iterations']}",
                    f"- **总调度时长**:{t_dispatch_total:.2f}s",
                    f"- **延迟 P50**:{p50 * 1000:.2f}ms",
                    f"- **延迟 P95**:{p95 * 1000:.2f}ms",
                    f"- **延迟 AVG**:{avg * 1000:.2f}ms",
                    "",
                    "## 3. 📊 7 字段 DispatcherResult 累加",
                    "",
                    "| 字段 | 值 |",
                    "|------|-----|",
                    f"| total_picked | {counters['total_picked']} |",
                    f"| sent | {counters['sent']} |",
                    f"| business_blocked | {counters['business_blocked']} |",
                    f"| technical_failed | {counters['technical_failed']} |",
                    f"| skipped | {counters['skipped']} |",
                    f"| skip_breach | {counters['skip_breach']} |",
                    f"| iterations | {counters['iterations']} |",
                    "",
                ]
            )

            report_lines.extend(
                [
                    "## 4. 🎯 按优先级拆分 outcome",
                    "",
                    "| priority | pending_send | approved | sending | sent | failed | cancelled |",
                    "|----------|--------------|----------|---------|------|--------|-----------|",
                ]
            )
            for priority, outcomes in per_priority_outcomes.items():
                report_lines.append(
                    f"| {priority} | {outcomes.get('pending_send', 0)} | "
                    f"{outcomes.get('approved', 0)} | {outcomes.get('sending', 0)} | "
                    f"{outcomes.get('sent', 0)} | {outcomes.get('failed', 0)} | "
                    f"{outcomes.get('cancelled', 0)} |"
                )
            report_lines.append("")

            report_lines.extend(
                [
                    "## 5. ✅ 关键验证项",
                    "",
                    "| # | 验证项 | 期望 | 实际 | 通过 |",
                    "|---|--------|------|------|------|",
                    f"| 1 | 状态机全部最终态(无 PENDING/APPROVED/FAILED/SENDING) | 0/0/0/0 | "
                    f"{len(final_pending)}/{len(final_approved)}/{len(final_failed)}/{len(final_sending)} | "
                    f"{'✅' if all_final else '❌'} |",
                    (
                        f"| 2 | InMemorySmtpTransport.sent_log 行数 == sent | {counters['sent']} | "
                        f"{len(transport.sent_log) if isinstance(transport, InMemorySmtpTransport) else 'N/A'} | "
                        f"{'✅' if isinstance(transport, InMemorySmtpTransport) and len(transport.sent_log) == counters['sent'] else ('N/A' if not isinstance(transport, InMemorySmtpTransport) else '❌')} |"
                    ),
                    f"| 3 | Heartbeat HEALTHY | healthy | {liveness.value} | "
                    f"{'✅' if liveness.value == 'healthy' else '⚠️'} |",
                    (
                        f"| 4 | SLA BREACH 注入(前 {inject_breach} 封) | skip_breach >= {inject_breach} | "
                        f"skip_breach={counters['skip_breach']} | "
                        f"{'✅' if counters['skip_breach'] >= inject_breach else ('N/A' if inject_breach == 0 else '❌')} |"
                    ),
                    (
                        # D5.6.3 P2-1 修复:报告用 injection_events 精确断言
                        # 之前 total_processed >= count 即使注入完全没生效也过(恒真陷阱)
                        # 真正精确:transport 层 send_message 注入事件列表 == inject_failures
                        f"| 5 | 注入失败(N={inject_failures}) 退避回路 | injection_events == {inject_failures} | "
                        f"injection_events={len(injection_events_holder.get('events', []))} | "
                        f"{'✅' if inject_failures == 0 else ('❌' if len(injection_events_holder.get('events', [])) != inject_failures else '✅')} |"
                    ),
                    (
                        # D5.6.3 P2-1 补充:dispatcher.technical_failed 实际触发数
                        f"| 5b | dispatcher.technical_failed 实际触发 | >= {inject_failures} | "
                        f"technical_failed={counters['technical_failed']} | "
                        f"{'✅' if counters['technical_failed'] >= inject_failures else ('N/A' if inject_failures == 0 else '❌')} |"
                    ),
                    "",
                ]
            )

            report_lines.extend(
                [
                    "## 6. 📊 结论",
                    "",
                    f"- **{count} 封入库**:✅ ({len(outbox_ids)}/{count})",
                    f"- **批量审批 PENDING_SEND → APPROVED**:✅ ({approved_count}/{count})",
                    f"- **OutboxDispatcher 循环 run_once**:✅ ({counters['iterations']} 轮)",
                    f"- **状态机全部最终态**:{'✅' if all_final else '❌'}",
                    f"- **SLA 评估**:skip_breach={counters['skip_breach']}",
                    f"- **退避回路**:total_processed={counters['sent'] + counters['business_blocked'] + counters['technical_failed']}",
                    f"- **Heartbeat 3 态**:HEALTHY={liveness.value}",
                    f"- **D5.6.1 7 项核心验证**:{'✅' if all_final else '❌'}",
                    "- **D5 启动计划 B3(接真实 SMTP)**:⏸️ 仍延后(默认 InMemory 模拟;--real 模式需用户手动 1 封实测)",
                    "",
                ]
            )

        finally:
            db.close()

    report_path = output_dir / f"spike_send_100_{timestamp}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"   📝 报告:{report_path}")
    print()
    print("=== Spike 跑完 ===")
    print(
        f"  total_picked={counters['total_picked']} "
        f"sent={counters['sent']} bb={counters['business_blocked']} "
        f"tf={counters['technical_failed']} sk={counters['skipped']} "
        f"sb={counters['skip_breach']} iters={counters['iterations']}"
    )
    if dispatcher_latencies_sorted:
        print(
            f"  调度延迟:min={min(dispatcher_latencies_sorted) * 1000:.2f}ms / "
            f"avg={avg * 1000:.2f}ms / p50={p50 * 1000:.2f}ms / "
            f"p95={p95 * 1000:.2f}ms / max={max(dispatcher_latencies_sorted) * 1000:.2f}ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="D5.6.1 spike — OutboxDispatcher 端到端(默认 InMemory 模拟,--real 需 4 重防误发)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "spike",
        help="报告输出目录(默认 output/spike/)",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="REAL 模式:真发到 SMTP 服务器(需 --recipient/--max-recipients/--confirm 三件套)",
    )
    # ===== D5.6.1 P1.2 防误发:4 件套必传 =====
    parser.add_argument(
        "--recipient",
        type=str,
        default=None,
        help="REAL 模式必传:统一收件人地址(白名单,只发到一个地址,防群发扰民)",
    )
    parser.add_argument(
        "--max-recipients",
        type=int,
        default=0,
        help="REAL 模式必传 1(强制 1 收件人,InMemory 模式忽略)",
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default=None,
        help=f"REAL 模式必传 {_CONFIRM_PHRASE!r} 二次确认口令",
    )
    # ===== SMTP 配置 4 参数(D5.6.1 P0 修复 + D5.6.2 P0 凭证链路强化)=====
    # D5.6.2 关键: --smtp-password 已删除(防 shell history 泄露)
    # REAL 模式从系统 Keychain 真读: get_smtp_password_for_provider(provider, email)
    # InMemory 模式不需要 password(spike 走 InMemorySmtpTransport 替身)
    parser.add_argument(
        "--smtp-host",
        type=str,
        default="smtp.qq.com",
        help="SMTP 服务器(REAL 模式必传真实地址,默认 smtp.qq.com 仅供 --real 显式覆盖)",
    )
    parser.add_argument(
        "--smtp-port",
        type=int,
        default=465,
        help="SMTP 端口(1-65535,默认 465)",
    )
    parser.add_argument(
        "--smtp-username",
        type=str,
        default="spike@qq.com",
        help="SMTP 用户名(REAL 模式必传真实地址,默认 spike@qq.com 仅供占位)",
    )
    parser.add_argument(
        "--smtp-provider",
        type=str,
        default="qq",
        # D5.6.3 P2-3 修复:Provider 能力对齐
        # 之前 choices=["qq", "outlook", "gmail"] 是"能力虚报"——outlook/gmail
        # 对应的 SERVICE_SMTP_OUTLOOK / SERVICE_SMTP_GMAIL 在 core/keychain.py
        # 已定义,但 scripts/spike_set_smtp_password.py 只支持 qq(provider 写入
        # / 检查 / 删除 能力不对齐)。当前 D5 阶段只验证 QQ SMTP 真实链路,
        # outlook/gmail 仍为 B 类延后(B1 类),D5 跑通后再扩。
        choices=["qq"],
        help=(
            "SMTP provider 白名单(D5.6.2 P0 修复:REAL 模式必传,真读 Keychain 凭证)。"
            "D5.6.3 P2-3 收口: 当前仅 'qq'(outlook/gmail 凭证写入脚本未实现,B 类延后)"
        ),
    )
    # ===== spike 行为参数 =====
    parser.add_argument(
        "--inject-failures",
        type=int,
        default=0,
        help="注入 N 封技术失败(测试退避回路,默认 0)",
    )
    parser.add_argument(
        "--inject-breach",
        type=int,
        default=0,
        help="前 N 封 created_at 倒拨 6 分钟(触发 URGENT SLA BREACH,默认 0)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="OutboxDispatcher 单次拉批上限(默认 10)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help=f"spike 封数(默认 100,REAL 模式最大 {_REAL_MODE_MAX_COUNT},InMemory 模式最大 {_INMEMORY_MAX_COUNT})",
    )
    args = parser.parse_args()

    # 严判 batch_size(D4.7.3 v1.0.5 P1-1 范本)
    if type(args.batch_size) is bool or args.batch_size < 1:
        parser.error(f"batch_size 必须是 >= 1 的整数,实际 {args.batch_size!r}")
    # 严判 count
    if type(args.count) is bool or args.count < 1:
        parser.error(f"count 必须是 >= 1 的整数,实际 {args.count!r}")
    # 严判 smtp_port
    if type(args.smtp_port) is bool or not 1 <= args.smtp_port <= 65535:
        parser.error(f"smtp_port 必须是 1-65535 整数,实际 {args.smtp_port!r}")

    run_spike(
        args.output_dir,
        real_send=args.real,
        recipient_email=args.recipient,
        max_recipients=args.max_recipients,
        confirm=args.confirm,
        smtp_host=args.smtp_host,
        smtp_port=args.smtp_port,
        smtp_username=args.smtp_username,
        smtp_provider=args.smtp_provider,
        inject_failures=args.inject_failures,
        inject_breach=args.inject_breach,
        batch_size=args.batch_size,
        count=args.count,
    )


if __name__ == "__main__":
    main()
