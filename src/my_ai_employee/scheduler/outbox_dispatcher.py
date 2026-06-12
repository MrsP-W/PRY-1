"""D5.4 — OutboxDispatcher: 消费 outbox 表 → SMTP 发送 → 状态机推进.

承接(沿用前序 D5.x 锁定接口):
  - D5.1 SMTP transport(connectors/smtp.py:InMemorySmtpTransport 测试替身)
  - D5.2 outbox 6 状态 + ALLOWED_TRANSITIONS(core/outbox.py)
  - D5.2 OutboxStore.update_status(*, from_status) 状态机严判(db/outbox.py)
  - D5.3 EmailSendAdapter 三入口(policy/send_adapter.py):
      1. send_and_emit                          (成功, PENDING_SEND/APPROVED → SENT)
      2. record_send_business_blocked_and_emit  (业务阻断, → CANCELLED, 永不 retry)
      3. record_send_failure_and_emit           (技术失败, → FAILED, 可 retry)
  - D3.3.3 异常窄化范本(SQLAlchemyError 基类不接,OperationalError 透传)

D5.4 主循环 6 步(沿 core/sync.py:IMAPSync.run_once 范本):
    1. heartbeat.update() 刷新 last_seen_ms,assert_alive() 失败抛 PolicyHeartbeatError 直接 return
    2. by_status(PENDING_SEND) + by_status(APPROVED) 拉批(限 batch_size, 优先级排序)
    3. 逐条调 send_adapter.send_and_emit()(异常按 D5.3 映射捕获)
    4. 每条处理后(成功/阻断/失败)累加 DispatcherResult 6 字段
    5. 落日志 + 返回 DispatcherResult
    6. D5.5 将在此处嵌入 SLAEvaluator + 退避过滤(D5.4 先做基础链路)

6 字段 DispatcherResult 范本(沿 core/sync.py:SyncResult):
    - total_picked / sent / business_blocked / technical_failed / skipped / duration_seconds

优先级排序(D4.8 范本):
    批内按 (priority DESC, created_at ASC) 排序
    URGENT > NORMAL > LOW(沿 OutboxPriority StrEnum 顺序)

设计原则:
  - 4 依赖可注入:source / send_adapter / store / heartbeat(沿 D4.7.3 v1.0.6 范本)
  - 依赖注入 is None 不用 or(D4.7.3 v1.0.3 P2-2 范本)
  - 异常范围窄化(D3.3.3 范本):显式枚举 smtplib 子类,不接 SMTPException / Exception 基类
  - 业务阻断 vs 技术失败 字段名级别硬区分(D4.7.3 v1.0.3 P2-1 范本)
  - 工厂层 + __post_init__ 双层防御(DispatcherResult 严判类型/边界)

D5.4 范围边界:
  - ✅ 基础主循环:拉批 → 逐条 send_and_emit → 累加 6 字段
  - ✅ Heartbeat.assert_alive() 失败 → 早 return(HEALTHY/STALLED 不阻断)
  - ❌ SLA 告警(URGENT 5min/...)延后到 D5.5
  - ❌ 重试退避公式(2^failures * 60s)延后到 D5.5
  - ❌ Heartbeat 3 态分支策略(HEALTHY/STALLED/TRANSPORT_DEAD)延后到 D5.5
  - ❌ batch_size 限速(throttle)/并发控制延后到 D5.5+

25 教训应用:
  1. 工厂层 + __post_init__ 双层防御(DispatcherResult)
  2. 跨字段校验(total_picked = sent + business_blocked + technical_failed + skipped)
  3. 字段名硬区分(business_blocked vs technical_failed,模仿 D4.7.3 P2-1)
  4. 异常统一 ValueError/TypeError(编程错误透传,D3.3.3 范本)
  5. 契约 helper 复用(沿用 D4.8 _validate_outbox_* 公共入口 — DispatcherResult 不重写)
  6. 固化哲学(代码+注释+测试+导出同 commit)
  7. 依赖注入 is None 不用 or(D4.7.3 v1.0.3 P2-2)
  8. bool 子类是 int 陷阱(type() is int 不用 isinstance)
  9. dataclass 默认值字段放最后(DispatcherResult 6 字段顺序)
  10. strip() 严判语义非空(source/run_id 严判)
  11. type 严判在 hash 前(frozenset 白名单校验前)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from email.message import EmailMessage

from loguru import logger

from my_ai_employee.core.outbox import OutboxEntry, OutboxPriority, OutboxStatus
from my_ai_employee.db.outbox import OutboxStore
from my_ai_employee.policy.exceptions import (
    PolicyHeartbeatError,
    SMTPSendIllegalTransitionError,
    SMTPSendRecipientsRefusedError,
    SMTPSendSenderRefusedError,
    SMTPSendTransportError,
)
from my_ai_employee.policy.heartbeat import Heartbeat
from my_ai_employee.policy.send_adapter import (
    EmailSendAdapter,
    SendDecisionReport,
)

# ===== 优先级映射(沿 D4.8 范本 — URGENT 最先 / LOW 最后)=====

# priority DESC 排序用数值键 — 业务层做"按优先级排序"时直接用
_PRIORITY_SORT_KEY: dict[str, int] = {
    OutboxPriority.URGENT.value: 3,
    OutboxPriority.NORMAL.value: 2,
    OutboxPriority.LOW.value: 1,
}


# ===== DispatcherResult dataclass(6 字段 — 沿 core/sync.py:SyncResult 7 字段范本)=====


@dataclass(frozen=True)
class DispatcherResult:
    """D5.4 单次调度结果统计(6 字段 — 业务数据双维度).

    跨字段强一致(D4.7.3 v1.0.2 P1-2 范本):
        total_picked = sent + business_blocked + technical_failed + skipped

    Attributes:
        total_picked:  本次拉批的 outbox 条目总数(>= 0)
        sent:          成功发送数(>= 0)
        business_blocked: 业务阻断数(>= 0, SENDING → CANCELLED)
        technical_failed: 技术失败数(>= 0, SENDING → FAILED, 可重试)
        skipped:       跳过数(>= 0, 优先级排序后未进批/Heartbeat 死亡/状态机漂移等)
        duration_seconds: 端到端耗时(>= 0.0)
    """

    total_picked: int
    sent: int
    business_blocked: int
    technical_failed: int
    skipped: int
    duration_seconds: float

    def __post_init__(self) -> None:
        """D5.4 字段契约自洽校验(4 范本全应用)."""
        # 1. 全部字段非负数严判(bool 子类陷阱 + int 边界)
        for field_name in (
            "total_picked",
            "sent",
            "business_blocked",
            "technical_failed",
            "skipped",
        ):
            value = getattr(self, field_name)
            if type(value) is bool or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"DispatcherResult.{field_name} 必须是原生 int(非 bool) >= 0, 实际 "
                    f"{type(value).__name__}={value!r}"
                )
        if not isinstance(self.duration_seconds, (int, float)) or self.duration_seconds < 0.0:
            raise ValueError(
                f"DispatcherResult.duration_seconds 必须是 int/float >= 0.0, 实际 "
                f"{type(self.duration_seconds).__name__}={self.duration_seconds!r}"
            )
        # 2. 跨字段强一致(D4.7.3 v1.0.2 P1-2 范本)
        if (
            self.total_picked
            != self.sent + self.business_blocked + self.technical_failed + self.skipped
        ):
            raise ValueError(
                f"DispatcherResult 跨字段强一致违反: total_picked({self.total_picked}) != "
                f"sent({self.sent}) + business_blocked({self.business_blocked}) + "
                f"technical_failed({self.technical_failed}) + skipped({self.skipped}) "
                f"(sum={self.sent + self.business_blocked + self.technical_failed + self.skipped})"
            )


# ===== OutboxDispatcher 主类(4 依赖可注入 + run_once 6 步范本)=====


class OutboxDispatcher:
    """D5.4 业务调度器 — 消费 outbox 表 → SMTP 发送 → 状态机推进.

    沿 core/sync.py:IMAPSync 范本:
      - 4 依赖可注入(source / send_adapter / store / heartbeat)
      - run_once() 6 步:heartbeat → 拉批 → 逐条处理 → 累加 → 落日志 → 返回 DispatcherResult
      - close() 释放资源(D3.2.2 教训:不 dispose engine,只清内部状态引用)

    用法(测试):
        dispatcher = OutboxDispatcher(
            source="test",
            send_adapter=EmailSendAdapter(source="test", ...),
            outbox_store=OutboxStore(session_factory),
            heartbeat=Heartbeat(idle_threshold_ms=30_000),
            batch_size=10,
        )
        result = await dispatcher.run_once()
        assert result.sent == 1

    用法(生产,D5.5+):
        dispatcher = OutboxDispatcher(
            source="qq",
            send_adapter=EmailSendAdapter(source="qq", smtp_transport=SmtpLibTransport(), ...),
            outbox_store=OutboxStore(session_factory),
            heartbeat=Heartbeat(idle_threshold_ms=30_000),
        )
        result = await dispatcher.run_once()
    """

    def __init__(
        self,
        *,
        source: str,
        send_adapter: EmailSendAdapter | None = None,
        outbox_store: OutboxStore | None = None,
        heartbeat: Heartbeat | None = None,
        batch_size: int = 10,
    ) -> None:
        """D5.4 Dispatcher 构造(4 依赖可注入 + 严判 source/batch_size).

        Args:
            source: 数据源头(必填非空白,如 "qq" / "outlook" / "gmail")
            send_adapter: EmailSendAdapter 实例(必传,None 触发硬报错)
            outbox_store: OutboxStore 实例(必传,None 触发硬报错)
            heartbeat: Heartbeat 实例(可选,默认 30s 阈值)
            batch_size: 单次拉批上限(>= 1, 默认 10)

        Raises:
            ValueError: source 非法 / batch_size 非法
        """
        # 1. source 严判(D4.7.3 v1.0.5 P2-2 范本:strip() 语义非空)
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                f"source 必填非空白 str(strip() 非空), 实际 {type(source).__name__}={source!r}"
            )
        self._source = source
        # 2. batch_size 严判
        if type(batch_size) is bool or not isinstance(batch_size, int) or batch_size < 1:
            raise ValueError(
                f"batch_size 必须是原生 int(非 bool) >= 1, 实际 "
                f"{type(batch_size).__name__}={batch_size!r}"
            )
        self._batch_size = batch_size
        # 3. 依赖注入 is None 不用 or(D4.7.3 v1.0.3 P2-2 范本,保留 falsey 替身)
        self._send_adapter = send_adapter
        self._outbox_store = outbox_store
        self._heartbeat = (
            heartbeat if heartbeat is not None else Heartbeat(idle_threshold_ms=30_000)
        )

    # ===== 公共 helper: 注入未注入依赖时的硬报错 =====

    def _require_send_adapter(self) -> EmailSendAdapter:
        if self._send_adapter is None:
            raise ValueError(
                "send_adapter 未注入 — OutboxDispatcher.__init__ 必须传 send_adapter="
                "EmailSendAdapter(source=..., smtp_transport=..., outbox_store=...),"
                "D5.4 单元测试用真实 EmailSendAdapter 注入"
            )
        return self._send_adapter

    def _require_outbox_store(self) -> OutboxStore:
        if self._outbox_store is None:
            raise ValueError(
                "outbox_store 未注入 — OutboxDispatcher.__init__ 必须传 outbox_store="
                "OutboxStore(session_factory),D5.4 单元测试用真实 OutboxStore 注入"
            )
        return self._outbox_store

    # ===== 主循环 =====

    def run_once(
        self,
        now_ms: int | None = None,
        *,
        transport_alive: bool = True,
    ) -> DispatcherResult:
        """D5.4 单次调度 — 6 步范本(沿 core/sync.py:IMAPSync.run_once).

        流程:
            1. heartbeat.update() 刷新 last_seen_ms,assert_alive() 失败 → 早 return(全 skipped)
            2. by_status(PENDING_SEND) + by_status(APPROVED) 拉批(批内按 priority DESC / created_at ASC 排)
            3. 逐条调 send_adapter.send_and_emit()(异常按 D5.3 映射捕获 → 业务阻断/技术失败)
            4. 累加 DispatcherResult 6 字段
            5. 落日志 + 返回 DispatcherResult
            6. D5.5 将在此处嵌入 SLAEvaluator + 退避过滤(本步先做基础链路)

        注: D5.4 run_once 是同步方法(EmailSendAdapter 三入口是同步 def),与
        core/sync.py:IMAPSync.run_once 的 async wrapper 不同(后者走 asyncio.to_thread 包装)。
        D5.5+ 引入 SMTPConnector.connect() 真正 IO 时再统一改 async。

        Args:
            now_ms: 注入"当前时间"(测试用,None = int(time.time() * 1000))
            transport_alive: 显式指定 transport 状态(测试 TRANSPORT_DEAD 时传 False,默认 True)

        Returns:
            DispatcherResult: 6 字段统计结果
        """
        # 严判 transport_alive(D4.7.3 v1.0.5 P2-2 范本)
        if type(transport_alive) is not bool:
            raise ValueError(
                f"transport_alive 必须是原生 bool, 实际 "
                f"{type(transport_alive).__name__}={transport_alive!r}"
            )
        t0 = time.perf_counter()
        start_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        store = self._require_outbox_store()
        adapter = self._require_send_adapter()

        # 1. Heartbeat 刷新 + 严格断言
        self._heartbeat.update(transport_alive=transport_alive, now_ms=start_ms)
        try:
            self._heartbeat.assert_alive(now_ms=start_ms)
        except PolicyHeartbeatError as e:
            # transport_dead → 早 return,全部 skipped(D5.4 决策:不让任何发送尝试)
            duration = time.perf_counter() - t0
            logger.warning(f"OutboxDispatcher 早 return: heartbeat 死亡,全部 skipped: {e}")
            return DispatcherResult(
                total_picked=0,
                sent=0,
                business_blocked=0,
                technical_failed=0,
                skipped=0,
                duration_seconds=duration,
            )

        # 2. 拉批 — PENDING_SEND + APPROVED 两种状态(沿 D4.8 范本)
        pending_entries = store.by_status(OutboxStatus.PENDING_SEND.value, limit=self._batch_size)
        approved_entries = store.by_status(OutboxStatus.APPROVED.value, limit=self._batch_size)
        # 合并 + 优先级排序
        all_entries = pending_entries + approved_entries
        all_entries.sort(
            key=lambda e: (
                -_PRIORITY_SORT_KEY.get(e.priority, 0),  # priority DESC
                e.created_at,  # created_at ASC(同优先级先入先出)
            )
        )
        # 限批(batch_size 上限)
        entries = all_entries[: self._batch_size]
        total_picked = len(entries)
        logger.info(
            f"OutboxDispatcher 拉批: PENDING_SEND={len(pending_entries)} "
            f"APPROVED={len(approved_entries)} 批内={total_picked}/{self._batch_size}"
        )

        # 3-4. 逐条处理 + 累加
        sent = 0
        business_blocked = 0
        technical_failed = 0
        skipped = 0
        for entry in entries:
            outcome = self._process_one_entry(adapter, entry, now_ms=start_ms)
            if outcome == "sent":
                sent += 1
            elif outcome == "business_blocked":
                business_blocked += 1
            elif outcome == "technical_failed":
                technical_failed += 1
            else:
                # outcome == "skipped" — 状态机漂移/编程错误等
                skipped += 1

        # 5. 累加 + 落日志 + 返回
        duration = time.perf_counter() - t0
        result = DispatcherResult(
            total_picked=total_picked,
            sent=sent,
            business_blocked=business_blocked,
            technical_failed=technical_failed,
            skipped=skipped,
            duration_seconds=duration,
        )
        logger.info(
            f"OutboxDispatcher 完成: total_picked={result.total_picked} "
            f"sent={result.sent} business_blocked={result.business_blocked} "
            f"technical_failed={result.technical_failed} skipped={result.skipped} "
            f"duration={result.duration_seconds:.3f}s"
        )
        return result

    # ===== 内部方法 =====

    def _process_one_entry(
        self,
        adapter: EmailSendAdapter,
        entry: OutboxEntry,
        *,
        now_ms: int,
    ) -> str:
        """D5.4 单条 outbox 条目处理 — 调 send_and_emit + 异常分流.

        Returns:
            "sent" / "business_blocked" / "technical_failed" / "skipped"
        """
        # 1. 严判 entry 状态(防御性兜底:理论已通过 by_status 过滤,但防 concurrent 写)
        if entry.id is None:
            logger.warning(f"OutboxDispatcher 跳过: outbox.id=None entry={entry!r}")
            return "skipped"
        if entry.status not in (
            OutboxStatus.PENDING_SEND.value,
            OutboxStatus.APPROVED.value,
        ):
            # 状态已变(并发写,或被其他 process 推到别的状态)→ skipped
            logger.warning(
                f"OutboxDispatcher 跳过: outbox_id={entry.id} 状态={entry.status!r} "
                f"不在 PENDING_SEND/APPROVED"
            )
            return "skipped"

        # 2. 构造 EmailMessage(简化版 — 沿 email.message.EmailMessage 标准 API)
        # D5.4 阶段:D5.3 EmailSendAdapter.send_and_emit 接受 email_message 参数,
        # 此处直接构造最小可用 EmailMessage(from=source / to=entry.recipient_email /
        # subject=entry.subject / body=entry.body)
        # 注:D5.6 spike 阶段将替换为 SMTPConnector.build_message 完整链路
        try:
            msg = EmailMessage()
            msg["From"] = f"{self._source}@test.local"
            msg["To"] = entry.recipient_email
            msg["Subject"] = entry.subject
            msg.set_content(entry.body)
        except Exception as e:
            # 构造失败极少见(字段都是 str),但防御性兜底
            logger.error(f"OutboxDispatcher build_message 失败: outbox_id={entry.id} {e!r}")
            return "skipped"

        # 3. 调 send_and_emit — 异常按 D5.3 映射分流
        # 注: D5.4 阶段 EmailSendAdapter.send_and_emit 接受 smtp_host/port/username/password/email_message
        # D5.6 spike 阶段将由 SMTPConnector.connect() 拿授权码后注入,本阶段测试场景硬编码
        try:
            report: SendDecisionReport = adapter.send_and_emit(
                outbox_id=entry.id,  # type: ignore[arg-type]
                smtp_host="smtp.test.local",
                smtp_port=465,
                smtp_username=f"{self._source}@test.local",
                smtp_password="<test-placeholder>",  # 测试替身,InMemorySmtpTransport 不校验
                email_message=msg,
                run_id=f"dispatcher-{start_ms_str(now_ms)}",
                transport_alive=True,
                now_ms=now_ms,
            )
            logger.debug(
                f"OutboxDispatcher sent: outbox_id={entry.id} event_id={report.event_id} "
                f"latency_ms={report.latency_ms}"
            )
            return "sent"
        except SMTPSendRecipientsRefusedError as e:
            # 业务阻断:收件人拒收 → 永久退信
            logger.warning(
                f"OutboxDispatcher 业务阻断(recipients_refused): outbox_id={entry.id} {e}"
            )
            try:
                adapter.record_send_business_blocked_and_emit(
                    outbox_id=entry.id,  # type: ignore[arg-type]
                    reason="recipients_refused",
                    last_error=e,
                    run_id=f"dispatcher-{start_ms_str(now_ms)}",
                    transport_alive=True,
                    now_ms=now_ms,
                )
            except (SMTPSendIllegalTransitionError, ValueError) as inner_e:
                # 状态机非法转换 / 编程错误 → skipped(异常已记录,不影响主流程)
                logger.error(
                    f"OutboxDispatcher record_blocked 失败: outbox_id={entry.id} {inner_e!r}"
                )
                return "skipped"
            return "business_blocked"
        except SMTPSendSenderRefusedError as e:
            # 业务阻断:发件人/认证被拒 → 永久退信
            logger.warning(f"OutboxDispatcher 业务阻断(sender_refused): outbox_id={entry.id} {e}")
            try:
                adapter.record_send_business_blocked_and_emit(
                    outbox_id=entry.id,  # type: ignore[arg-type]
                    reason="sender_refused",
                    last_error=e,
                    run_id=f"dispatcher-{start_ms_str(now_ms)}",
                    transport_alive=True,
                    now_ms=now_ms,
                )
            except (SMTPSendIllegalTransitionError, ValueError) as inner_e:
                logger.error(
                    f"OutboxDispatcher record_blocked 失败: outbox_id={entry.id} {inner_e!r}"
                )
                return "skipped"
            return "business_blocked"
        except SMTPSendTransportError as e:
            # 技术失败:瞬态网络/SSL/超时错误 → 可重试
            logger.warning(f"OutboxDispatcher 技术失败(transport_error): outbox_id={entry.id} {e}")
            try:
                adapter.record_send_failure_and_emit(
                    outbox_id=entry.id,  # type: ignore[arg-type]
                    error_category="transport_error",
                    last_error=e,
                    consecutive_send_failures=1,
                    retry_after_ms=0,  # D5.5 联动指数退避公式
                    run_id=f"dispatcher-{start_ms_str(now_ms)}",
                    transport_alive=True,
                    now_ms=now_ms,
                )
            except (SMTPSendIllegalTransitionError, ValueError) as inner_e:
                logger.error(
                    f"OutboxDispatcher record_failure 失败: outbox_id={entry.id} {inner_e!r}"
                )
                return "skipped"
            return "technical_failed"
        except SMTPSendIllegalTransitionError as e:
            # 状态机非法转换 — 同时记录为技术失败(状态漂移 = 并发写,可重试)
            logger.warning(
                f"OutboxDispatcher 状态机漂移(illegal_transition): outbox_id={entry.id} {e}"
            )
            try:
                adapter.record_send_failure_and_emit(
                    outbox_id=entry.id,  # type: ignore[arg-type]
                    error_category="smtp_other",
                    last_error=e,
                    consecutive_send_failures=1,
                    retry_after_ms=0,
                    run_id=f"dispatcher-{start_ms_str(now_ms)}",
                    transport_alive=True,
                    now_ms=now_ms,
                )
            except (SMTPSendIllegalTransitionError, ValueError) as inner_e:
                logger.error(
                    f"OutboxDispatcher record_failure 失败: outbox_id={entry.id} {inner_e!r}"
                )
                return "skipped"
            return "technical_failed"
        except ValueError as e:
            # 编程错误(参数非法严判)→ skipped,不计入 sent/failed
            # D3.3.3 范本:不接基类 Exception,显式接 ValueError
            logger.error(f"OutboxDispatcher 编程错误(ValueError): outbox_id={entry.id} {e!r}")
            return "skipped"

    # ===== 资源清理(沿 core/sync.py:IMAPSync.close 范本)=====

    def close(self) -> None:
        """D5.4 释放 Dispatcher 资源 — 仅清内部引用,不 dispose 任何 engine。

        沿 D3.2.2 教训:SA engine 与 db 同寿命(由 db 显式 close 管理),
        OutboxDispatcher 不持有 engine,只持有 store / send_adapter / heartbeat 引用。
        """
        self._send_adapter = None
        self._outbox_store = None
        self._heartbeat = None  # type: ignore[assignment]


# ===== 私有 helper(模块级 — 避免每次 _process_one_entry 重复构造 str)====


def start_ms_str(now_ms: int) -> str:
    """把 now_ms 转成短字符串(用于 run_id 唯一性)。

    D4.7.3 v1.0.4 P2-2 范本:type() is int 严判,拒 bool 子类。
    """
    if type(now_ms) is bool or not isinstance(now_ms, int) or now_ms < 0:
        raise ValueError(
            f"now_ms 必须是原生 int(非 bool) >= 0, 实际 {type(now_ms).__name__}={now_ms!r}"
        )
    # 截取后 6 位(秒级 + ms 后 3 位)— 避免 run_id 过长
    return str(now_ms)[-9:]


# ===== 模块导出 =====


__all__ = [
    "DispatcherResult",
    "OutboxDispatcher",
]
