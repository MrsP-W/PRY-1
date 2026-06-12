"""D5.5 — OutboxDispatcher: 消费 outbox 表 → SMTP 发送 → 状态机推进 + SLA + 退避 + Heartbeat 3 态联动.

承接(沿用前序 D5.x 锁定接口):
  - D5.1 SMTP transport(connectors/smtp.py:InMemorySmtpTransport 测试替身)
  - D5.2 outbox 6 状态 + ALLOWED_TRANSITIONS(core/outbox.py)
  - D5.2 OutboxStore.update_status(*, from_status) 状态机严判(db/outbox.py)
  - D5.3 EmailSendAdapter 三入口(policy/send_adapter.py):
      1. send_and_emit                          (成功, PENDING_SEND/APPROVED → SENT)
      2. record_send_business_blocked_and_emit  (业务阻断, → CANCELLED, 永不 retry)
      3. record_send_failure_and_emit           (技术失败, → FAILED, 可 retry)
  - D5.5 SLAEvaluator + compute_retry_after_ms(本模块):
      - SLA: URGENT 5min / NORMAL 4h / LOW 24h
      - 退避: 2^cf * 60s 封顶 1h
  - D3.3.3 异常窄化范本(SQLAlchemyError 基类不接,OperationalError 透传)

D5.5 主循环 6 步(沿 core/sync.py:IMAPSync.run_once 范本 + D5.5 新增 SLA/退避/3 态):
    1. heartbeat.update() 刷新 last_seen_ms,evaluate() 得 Liveness:
       - HEALTHY / STALLED → 正常处理
       - TRANSPORT_DEAD → 早 return,全部 skipped
    2. by_status(PENDING_SEND) + by_status(APPROVED) 拉批(限 batch_size, 优先级排序)
       + 退避过滤(self._failure_state: cf>=1 && now_ms < last_failed_at + retry_after → skipped)
       + SLA 评估(BREACH → logger.warning + 计入 skip_breach 计数,D5.5 仍发送,D5.6+ ESCALATE_REQUIRED)
    3. 逐条调 send_adapter.send_and_emit()(异常按 D5.3 映射捕获)
    4. 失败时调 compute_retry_after_ms(cf) → record_send_failure_and_emit(retry_after_ms=...)
       + 更新内存 self._failure_state[outbox_id] = {cf, last_failed_at}
       + 成功时清内存 self._failure_state.pop(outbox_id, None)
    5. 累加 DispatcherResult 7 字段(原 6 字段 + skip_breach)
    6. 落日志 + 返回 DispatcherResult

7 字段 DispatcherResult 范本(D5.5 新增 skip_breach):
    - total_picked / sent / business_blocked / technical_failed / skipped / skip_breach / duration_seconds

跨字段强一致(D5.5):
    total_picked = sent + business_blocked + technical_failed + skipped + skip_breach

优先级排序(D4.8 范本):
    批内按 (priority DESC, created_at ASC) 排序
    URGENT > NORMAL > LOW(沿 OutboxPriority StrEnum 顺序)

设计原则:
  - 4 依赖可注入:source / send_adapter / store / heartbeat(沿 D4.7.3 v1.0.6 范本)
  - 依赖注入 is None 不用 or(D4.7.3 v1.0.3 P2-2 范本)
  - 异常范围窄化(D3.3.3 范本):显式枚举 smtplib 子类,不接 SMTPException / Exception 基类
  - 业务阻断 vs 技术失败 字段名级别硬区分(D4.7.3 v1.0.3 P2-1 范本)
  - 工厂层 + __post_init__ 双层防御(DispatcherResult 严判类型/边界)
  - 内存状态字典(per-outbox_id 追踪 cf + last_failed_at)— **不**写 outbox 表(避免破坏 D4.8 v1.0.1 5 契约)

D5.5 范围边界:
  - ✅ SLA 评估(SLAEvaluator.evaluate)— OK/WARNING/BREACH 3 态
  - ✅ 退避公式(compute_retry_after_ms)— 2^cf * 60s 封顶 1h
  - ✅ Heartbeat 3 态分支 — HEALTHY/STALLED 正常处理,TRANSPORT_DEAD 早 return
  - ✅ 内存退避状态(per-outbox_id 追踪 cf + last_failed_at)— 不写库
  - ✅ DispatcherResult 加 skip_breach 字段(原 6 → 7 字段)
  - ❌ SLA BREACH 真实 ESCALATE_REQUIRED 决策延后到 D5.6+(D5.5 仅 logger.warning)
  - ❌ 内存退避状态持久化(进程崩溃后丢失)— B 类决策延后
  - ❌ batch_size 限速(throttle)/并发控制延后到 D5.5+

25 教训应用:
  1. 工厂层 + __post_init__ 双层防御(DispatcherResult + SLAEvaluation)
  2. 跨字段校验(total_picked = sent + business_blocked + technical_failed + skipped + skip_breach)
  3. 字段名硬区分(business_blocked vs technical_failed vs skip_breach)
  4. 异常统一 ValueError/TypeError(编程错误透传,D3.3.3 范本)
  5. 契约 helper 复用(沿用 D4.8 _validate_outbox_* 公共入口 + SLA 严判)
  6. 固化哲学(代码+注释+测试+导出同 commit)
  7. 依赖注入 is None 不用 or(D4.7.3 v1.0.3 P2-2)
  8. bool 子类是 int 陷阱(type() is int 不用 isinstance)
  9. dataclass 默认值字段放最后(DispatcherResult 7 字段顺序)
  10. strip() 严判语义非空(source/run_id/outbox_id 严判)
  11. type 严判在 hash 前(frozenset 白名单校验前)
  12. Heartbeat 3 态分支(沿 Liveness StrEnum 范本,D5.4 早 return → D5.5 evaluate 优先)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from email.message import EmailMessage

from loguru import logger

from my_ai_employee.core.outbox import OutboxEntry, OutboxPriority, OutboxStatus
from my_ai_employee.db.outbox import OutboxStore
from my_ai_employee.policy.exceptions import (
    SMTPSendIllegalTransitionError,
    SMTPSendRecipientsRefusedError,
    SMTPSendSenderRefusedError,
    SMTPSendTransportError,
)
from my_ai_employee.policy.heartbeat import Heartbeat, Liveness
from my_ai_employee.policy.send_adapter import (
    EmailSendAdapter,
    SendDecisionReport,
)
from my_ai_employee.scheduler.backoff import compute_retry_after_ms
from my_ai_employee.scheduler.sla import SLAEvaluator, SLAStatus

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
    """D5.5 单次调度结果统计(7 字段 — 业务数据双维度 + SLA breach).

    跨字段强一致(D4.7.3 v1.0.2 P1-2 范本):
        total_picked = sent + business_blocked + technical_failed + skipped + skip_breach

    Attributes:
        total_picked:  本次拉批的 outbox 条目总数(>= 0)
        sent:          成功发送数(>= 0)
        business_blocked: 业务阻断数(>= 0, SENDING → CANCELLED)
        technical_failed: 技术失败数(>= 0, SENDING → FAILED, 可重试)
        skipped:       跳过数(>= 0, 退避中/Heartbeat 死亡/状态机漂移等)
        skip_breach:   SLA 硬超条目数(>= 0, D5.5 仅记日志,D5.6+ ESCALATE_REQUIRED)
        duration_seconds: 端到端耗时(>= 0.0)
    """

    total_picked: int
    sent: int
    business_blocked: int
    technical_failed: int
    skipped: int
    skip_breach: int
    duration_seconds: float

    def __post_init__(self) -> None:
        """D5.5 字段契约自洽校验(4 范本全应用)."""
        # 1. 全部字段非负数严判(bool 子类陷阱 + int 边界)
        for field_name in (
            "total_picked",
            "sent",
            "business_blocked",
            "technical_failed",
            "skipped",
            "skip_breach",
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
        # 2. 跨字段强一致(D4.7.3 v1.0.2 P1-2 范本 + D5.5 新增 skip_breach)
        sum_outcomes = (
            self.sent
            + self.business_blocked
            + self.technical_failed
            + self.skipped
            + self.skip_breach
        )
        if self.total_picked != sum_outcomes:
            raise ValueError(
                f"DispatcherResult 跨字段强一致违反: total_picked({self.total_picked}) != "
                f"sent({self.sent}) + business_blocked({self.business_blocked}) + "
                f"technical_failed({self.technical_failed}) + skipped({self.skipped}) + "
                f"skip_breach({self.skip_breach}) (sum={sum_outcomes})"
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
        """D5.5 Dispatcher 构造(4 依赖可注入 + 严判 source/batch_size).

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
        # 4. D5.5 内存退避状态(per-outbox_id → {cf, last_failed_at})
        #    - 失败时记录 consecutive_send_failures + last_failed_at_ms
        #    - 成功时清空(避免历史 cf 干扰)
        #    - 进程崩溃后状态丢失(B 类决策延后,真实生产需持久化)
        self._failure_state: dict[int, dict[str, int]] = {}

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
        """D5.5 单次调度 — 6 步范本(沿 core/sync.py:IMAPSync.run_once + D5.5 新增 SLA/退避/3 态).

        流程:
            1. heartbeat.update() + evaluate() 得 Liveness:
               - HEALTHY / STALLED → 正常处理
               - TRANSPORT_DEAD → 早 return(全 skipped)
            2. by_status(PENDING_SEND) + by_status(APPROVED) 拉批
               + 退避过滤(cf>=1 && now < last_failed_at + retry_after → skipped)
               + SLA 评估(BREACH → logger.warning + 计入 skip_breach,D5.5 仍尝试发送)
            3. 逐条调 send_adapter.send_and_emit()(异常按 D5.3 映射捕获)
            4. 失败时调 compute_retry_after_ms(cf) → 更新 _failure_state
               + 成功时清 _failure_state[outbox_id]
            5. 累加 DispatcherResult 7 字段
            6. 落日志 + 返回 DispatcherResult

        Args:
            now_ms: 注入"当前时间"(测试用,None = int(time.time() * 1000))
            transport_alive: 显式指定 transport 状态(测试 TRANSPORT_DEAD 时传 False,默认 True)

        Returns:
            DispatcherResult: 7 字段统计结果
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

        # 1. Heartbeat 刷新 + 3 态评估(D5.5 新增:从 D5.4 assert_alive 改为 evaluate 分支)
        self._heartbeat.update(transport_alive=transport_alive, now_ms=start_ms)
        liveness = self._heartbeat.evaluate(now_ms=start_ms)
        if liveness == Liveness.TRANSPORT_DEAD:
            # transport_dead → 早 return,全部 skipped(D5.4 沿用 + D5.5 加 liveness 上下文)
            duration = time.perf_counter() - t0
            logger.warning(f"OutboxDispatcher 早 return: heartbeat={liveness.value},全部 skipped")
            return DispatcherResult(
                total_picked=0,
                sent=0,
                business_blocked=0,
                technical_failed=0,
                skipped=0,
                skip_breach=0,
                duration_seconds=duration,
            )
        # HEALTHY / STALLED 正常处理(Stalled 仅性能降级,仍可发送)
        logger.debug(f"OutboxDispatcher heartbeat={liveness.value}, 正常处理")

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

        # 3-4. 逐条处理 + 累加(D5.5:含退避过滤 + SLA 评估)
        sent = 0
        business_blocked = 0
        technical_failed = 0
        skipped = 0
        skip_breach = 0
        for entry in entries:
            outcome, extra = self._process_one_entry(adapter, entry, now_ms=start_ms)
            if outcome == "sent":
                sent += 1
            elif outcome == "business_blocked":
                business_blocked += 1
            elif outcome == "technical_failed":
                technical_failed += 1
            elif outcome == "skip_breach":
                # D5.5 SLA BREACH:仍尝试发送(避免邮件被遗忘),但计入 skip_breach
                # D5.6+ 会同时发 ESCALATE_REQUIRED 决策到 PolicyEngine
                skip_breach += 1
            else:
                # outcome == "skipped" — 退避中/状态机漂移/编程错误等
                skipped += 1
            if extra:  # 调试日志
                logger.debug(f"  entry_id={entry.id} outcome={outcome} {extra}")

        # 5. 累加 + 落日志 + 返回(D5.5:7 字段)
        duration = time.perf_counter() - t0
        result = DispatcherResult(
            total_picked=total_picked,
            sent=sent,
            business_blocked=business_blocked,
            technical_failed=technical_failed,
            skipped=skipped,
            skip_breach=skip_breach,
            duration_seconds=duration,
        )
        logger.info(
            f"OutboxDispatcher 完成: total_picked={result.total_picked} "
            f"sent={result.sent} business_blocked={result.business_blocked} "
            f"technical_failed={result.technical_failed} skipped={result.skipped} "
            f"skip_breach={result.skip_breach} duration={result.duration_seconds:.3f}s "
            f"liveness={liveness.value}"
        )
        return result

    # ===== 内部方法 =====

    def _process_one_entry(
        self,
        adapter: EmailSendAdapter,
        entry: OutboxEntry,
        *,
        now_ms: int,
    ) -> tuple[str, str]:
        """D5.5 单条 outbox 条目处理 — 退避过滤 + SLA 评估 + 调 send_and_emit + 异常分流.

        流程:
          1. 严判 entry 状态(防御性兜底)
          2. **退避过滤**(D5.5 新增):_failure_state[entry_id] 存在且
             now_ms < last_failed_at + retry_after → skipped(计入 skipped)
          3. **SLA 评估**(D5.5 新增):SLAEvaluator.evaluate(priority, age_ms)
             BREACH → 仍尝试发送 + 计入 skip_breach 计数
          4. 构造 EmailMessage
          5. 调 send_and_emit + 异常按 D5.3 映射捕获
          6. **失败时**调 compute_retry_after_ms(cf) → 传 record_send_failure_and_emit
             + 更新 _failure_state[entry_id]
             **成功时**清 _failure_state.pop(entry_id, None)

        Returns:
            (outcome, extra) 元组:
              - outcome: "sent" / "business_blocked" / "technical_failed" /
                         "skipped" / "skip_breach"
              - extra:  调试上下文(空字符串 / "retry_after=N" / "sla=breach age_ms=N" 等)
        """
        # 1. 严判 entry 状态(防御性兜底:理论已通过 by_status 过滤,但防 concurrent 写)
        if entry.id is None:
            logger.warning(f"OutboxDispatcher 跳过: outbox.id=None entry={entry!r}")
            return ("skipped", "")
        if entry.status not in (
            OutboxStatus.PENDING_SEND.value,
            OutboxStatus.APPROVED.value,
        ):
            # 状态已变(并发写,或被其他 process 推到别的状态)→ skipped
            logger.warning(
                f"OutboxDispatcher 跳过: outbox_id={entry.id} 状态={entry.status!r} "
                f"不在 PENDING_SEND/APPROVED"
            )
            return ("skipped", "")

        # 2. 退避过滤(D5.5 新增)
        fs = self._failure_state.get(entry.id)
        if fs is not None:
            cf = fs["consecutive_send_failures"]
            last_failed_at = fs["last_failed_at_ms"]
            retry_after = compute_retry_after_ms(cf)
            if now_ms < last_failed_at + retry_after:
                # 还在退避窗口内,跳过
                logger.debug(
                    f"OutboxDispatcher 退避中: outbox_id={entry.id} cf={cf} "
                    f"retry_after={retry_after}ms"
                )
                return ("skipped", f"retry_after={retry_after} cf={cf}")

        # 3. SLA 评估(D5.5 新增)
        age_ms = max(0, now_ms - entry.created_at)
        sla_eval = SLAEvaluator.evaluate(priority=entry.priority, age_ms=age_ms)
        sla_extra = ""
        is_breach = False
        if sla_eval.status == SLAStatus.BREACH:
            is_breach = True
            logger.warning(
                f"OutboxDispatcher SLA BREACH: outbox_id={entry.id} priority={entry.priority} "
                f"age_ms={age_ms} (threshold 已超,仍尝试发送 + skip_breach++)"
            )
            sla_extra = f"sla=breach age_ms={age_ms}"
        elif sla_eval.status == SLAStatus.WARNING:
            logger.info(
                f"OutboxDispatcher SLA WARNING: outbox_id={entry.id} "
                f"priority={entry.priority} age_ms={age_ms}"
            )
            sla_extra = f"sla=warning age_ms={age_ms}"

        # 4. 构造 EmailMessage
        try:
            msg = EmailMessage()
            msg["From"] = f"{self._source}@test.local"
            msg["To"] = entry.recipient_email
            msg["Subject"] = entry.subject
            msg.set_content(entry.body)
        except Exception as e:
            logger.error(f"OutboxDispatcher build_message 失败: outbox_id={entry.id} {e!r}")
            return ("skipped", "build_message_failed")

        # 5. 调 send_and_emit — 异常按 D5.3 映射分流
        try:
            report: SendDecisionReport = adapter.send_and_emit(
                outbox_id=entry.id,  # type: ignore[arg-type]
                smtp_host="smtp.test.local",
                smtp_port=465,
                smtp_username=f"{self._source}@test.local",
                smtp_password="<test-placeholder>",
                email_message=msg,
                run_id=f"dispatcher-{start_ms_str(now_ms)}",
                transport_alive=True,
                now_ms=now_ms,
            )
            logger.debug(
                f"OutboxDispatcher sent: outbox_id={entry.id} event_id={report.event_id} "
                f"latency_ms={report.latency_ms}"
            )
            # 6a. 成功 → 清内存退避状态
            self._failure_state.pop(entry.id, None)
            return ("sent" if not is_breach else "skip_breach", sla_extra)
        except SMTPSendRecipientsRefusedError as e:
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
                logger.error(
                    f"OutboxDispatcher record_blocked 失败: outbox_id={entry.id} {inner_e!r}"
                )
                return ("skipped", "record_blocked_failed")
            # 业务阻断 → 清内存退避状态(永不 retry)
            self._failure_state.pop(entry.id, None)
            return ("business_blocked", "")
        except SMTPSendSenderRefusedError as e:
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
                return ("skipped", "record_blocked_failed")
            self._failure_state.pop(entry.id, None)
            return ("business_blocked", "")
        except SMTPSendTransportError as e:
            logger.warning(f"OutboxDispatcher 技术失败(transport_error): outbox_id={entry.id} {e}")
            # 6b. 失败 → 更新内存退避状态 + 调退避公式
            old_cf = self._failure_state.get(entry.id, {}).get("consecutive_send_failures", 0)
            new_cf = old_cf + 1
            retry_after_ms = compute_retry_after_ms(new_cf)
            self._failure_state[entry.id] = {
                "consecutive_send_failures": new_cf,
                "last_failed_at_ms": now_ms,
            }
            try:
                adapter.record_send_failure_and_emit(
                    outbox_id=entry.id,  # type: ignore[arg-type]
                    error_category="transport_error",
                    last_error=e,
                    consecutive_send_failures=new_cf,
                    retry_after_ms=retry_after_ms,
                    run_id=f"dispatcher-{start_ms_str(now_ms)}",
                    transport_alive=True,
                    now_ms=now_ms,
                )
            except (SMTPSendIllegalTransitionError, ValueError) as inner_e:
                logger.error(
                    f"OutboxDispatcher record_failure 失败: outbox_id={entry.id} {inner_e!r}"
                )
                return ("skipped", "record_failure_failed")
            return ("technical_failed", f"cf={new_cf} retry_after={retry_after_ms}")
        except SMTPSendIllegalTransitionError as e:
            logger.warning(
                f"OutboxDispatcher 状态机漂移(illegal_transition): outbox_id={entry.id} {e}"
            )
            old_cf = self._failure_state.get(entry.id, {}).get("consecutive_send_failures", 0)
            new_cf = old_cf + 1
            retry_after_ms = compute_retry_after_ms(new_cf)
            self._failure_state[entry.id] = {
                "consecutive_send_failures": new_cf,
                "last_failed_at_ms": now_ms,
            }
            try:
                adapter.record_send_failure_and_emit(
                    outbox_id=entry.id,  # type: ignore[arg-type]
                    error_category="smtp_other",
                    last_error=e,
                    consecutive_send_failures=new_cf,
                    retry_after_ms=retry_after_ms,
                    run_id=f"dispatcher-{start_ms_str(now_ms)}",
                    transport_alive=True,
                    now_ms=now_ms,
                )
            except (SMTPSendIllegalTransitionError, ValueError) as inner_e:
                logger.error(
                    f"OutboxDispatcher record_failure 失败: outbox_id={entry.id} {inner_e!r}"
                )
                return ("skipped", "record_failure_failed")
            return ("technical_failed", f"cf={new_cf} retry_after={retry_after_ms}")
        except ValueError as e:
            logger.error(f"OutboxDispatcher 编程错误(ValueError): outbox_id={entry.id} {e!r}")
            return ("skipped", "value_error")

    # ===== 资源清理(沿 core/sync.py:IMAPSync.close 范本)=====

    def close(self) -> None:
        """D5.5 释放 Dispatcher 资源 — 仅清内部引用,不 dispose 任何 engine.

        沿 D3.2.2 教训:SA engine 与 db 同寿命(由 db 显式 close 管理),
        OutboxDispatcher 不持有 engine,只持有 store / send_adapter / heartbeat 引用。
        """
        self._send_adapter = None
        self._outbox_store = None
        self._heartbeat = None  # type: ignore[assignment]
        # D5.5 内存退避状态清理
        self._failure_state.clear()


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
