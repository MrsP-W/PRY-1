"""D3.3 — IMAP 邮件同步入库（ORM 100/批 commit + SyncState 增量）。

设计（[docs/week1-mvp.md §D3.3]）：

    - **同步入口**：`IMAPConnector.safe_fetch` (D2 已实现，应急版范本 +
      熔断 + 失败隔离)
    - **增量策略**：`SyncState.last_uid` 记录上次同步的最大 UID，
      下次只拉 > last_uid 的邮件（避免重复入库）
    - **批量入库**：每 100 封 `session.commit()` 一次（避免 SQLite 长事务锁）
    - **失败隔离**：单封失败不阻塞后续（per-batch try/except + 跳过 + 计数）
    - **received_at 缺失 fallback** 到 `fetched_at`（D3.1.1 决策 — 入库映射层落实）
    - **JSON 字段**：`JSONList TypeDecorator`（D3.2.3）— 写 `recipients=[]` / `labels=[]` 直生效
    - **关系双轨**：本模块只写 JSON 字段 `Email.labels`（D3 阶段快速过滤），
      `EmailLabel` 关系表由 D4+ 写

用法：

    db = Database.open()
    connector = IMAPConnector(provider="qq", email="user@qq.com")
    sync = IMAPSync(db, connector)
    result = await sync.run_once()
    print(f"fetched={result.total_fetched} inserted={result.inserted} "
          f"failed={result.failed} new_last_uid={result.new_last_uid} "
          f"duration={result.duration_seconds:.2f}s")
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlcipher3.dbapi2 as _sqlcipher_dbapi
from loguru import logger
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from my_ai_employee.connectors.base import BaseConnector
from my_ai_employee.core.db import Database
from my_ai_employee.core.models import Email, SyncState
from my_ai_employee.core.sqlcipher_compat import make_sqlalchemy_engine

# ===== 公共类型 =====


@dataclass(frozen=True)
class SyncResult:
    """单次同步结果（D3.3 入库性能 + 业务数据双维度统计）。"""

    total_fetched: int  # safe_fetch 返回的原始邮件数
    inserted: int  # 实际写入 DB 的新邮件数
    skipped: int  # 已存在 (UNIQUE 冲突) 跳过的
    failed: int  # 失败隔离的（单封异常不阻塞）
    new_last_uid: int  # 同步后 SyncState 更新到的新 last_uid
    duration_seconds: float  # 端到端耗时


# ===== IMAPSync 核心类 =====


class IMAPSync:
    """IMAP → SQLCipher DB 同步（100/批 commit + SyncState 增量）。"""

    def __init__(
        self,
        db: Database,
        connector: BaseConnector,
        batch_size: int = 100,
    ) -> None:
        self._db = db
        self._connector = connector
        self._batch_size = batch_size
        # SA engine + sessionmaker（懒加载 + 复用；close() 后变 None）
        self._engine: Engine | None = make_sqlalchemy_engine(db)
        # sessionmaker 需 Engine bind（close() 前 sessionmaker 不可用）
        self._session_factory = (
            sessionmaker(bind=self._engine, expire_on_commit=False)
            if self._engine is not None
            else None
        )

    async def run_once(self, since: datetime | None = None) -> SyncResult:
        """单次同步（拉取 + 批量入库 + 更新 SyncState）。

        流程：
            1. 拿上次 last_uid（from SyncState）— 首次为 0
            2. safe_fetch(since) 拉取（失败隔离由 safe_fetch 负责）
            3. 按 uid 升序排序（IMAP UID 是单调递增的整数）
            4. 过滤掉 uid <= last_uid 的（旧邮件）
            5. 100/批 commit ORM 入库（每批独立 try/except — 单封失败不阻塞）
            6. 更新 SyncState.last_uid + last_sync_at + last_status
        """
        t0 = time.perf_counter()
        source = self._connector.source_name  # type: ignore[attr-defined]
        now_ms = int(datetime.now(UTC).timestamp() * 1000)

        # 1) 读 SyncState
        assert self._session_factory is not None  # close() 后才 None
        with self._session_factory() as session:
            last_uid = self._get_last_uid(session, source)

        # 2) safe_fetch 拉取（D2 应急版范本 — 失败隔离 + 熔断）
        if since is None:
            # 默认拉最近 30 天（D3 阶段合理起点 — SyncState 会持续收口）
            # ⚠️ D3.3.1 修复：直接算 UTC timestamp 再 fromtimestamp 构造 aware datetime，
            # 避免 `replace(tzinfo=None)` 把 naive datetime 视为本地时间 (Asia/Shanghai)
            # 导致 .timestamp() 偏移 8 小时
            since = datetime.fromtimestamp(datetime.now(UTC).timestamp() - 30 * 24 * 3600, tz=UTC)

        raw_emails = await self._connector.safe_fetch(since)
        total_fetched = len(raw_emails)
        logger.info(f"safe_fetch 返回 {total_fetched} 封（source={source} last_uid={last_uid}）")

        # 3) 过滤旧邮件（uid <= last_uid）
        new_emails = [e for e in raw_emails if e.get("uid", 0) > last_uid]
        new_emails.sort(key=lambda e: e.get("uid", 0))
        logger.info(f"过滤后剩 {len(new_emails)} 封新邮件（last_uid={last_uid}）")

        # 4) 100/批 commit ORM 入库（单批 try/except — 失败隔离）
        inserted = 0
        skipped = 0
        failed = 0
        new_last_uid = last_uid

        for batch_start in range(0, len(new_emails), self._batch_size):
            batch = new_emails[batch_start : batch_start + self._batch_size]
            try:
                b_inserted, b_skipped, b_max_uid = self._commit_batch(source, now_ms, batch)
                inserted += b_inserted
                skipped += b_skipped
                new_last_uid = max(new_last_uid, b_max_uid)
            except SQLAlchemyError as e:
                # 整批失败（如 DB 锁）— 不阻塞下一批
                failed += len(batch)
                logger.error(f"批次入库失败（{len(batch)} 封）: {e!r}")
                continue

        # 5) 更新 SyncState
        assert self._session_factory is not None  # close() 后才 None
        with self._session_factory() as session:
            self._update_sync_state(session, source, now_ms, new_last_uid, failed)

        duration = time.perf_counter() - t0
        result = SyncResult(
            total_fetched=total_fetched,
            inserted=inserted,
            skipped=skipped,
            failed=failed,
            new_last_uid=new_last_uid,
            duration_seconds=duration,
        )
        logger.info(
            f"同步完成: fetched={result.total_fetched} "
            f"inserted={result.inserted} skipped={result.skipped} "
            f"failed={result.failed} new_last_uid={result.new_last_uid} "
            f"duration={result.duration_seconds:.2f}s"
        )
        return result

    # ===== 内部方法 =====

    def _commit_batch(
        self, source: str, now_ms: int, batch: list[dict[str, Any]]
    ) -> tuple[int, int, int]:
        """单批入库 — 返回 (inserted, skipped, max_uid)。

        单封失败时整批继续（try/except 在外层 — 这里只接受整批 OK 或全失败）。
        """
        inserted = 0
        skipped = 0
        max_uid = 0
        with self._session_factory() as session:
            try:
                for raw in batch:
                    email = self._raw_to_email(source, raw, now_ms)
                    session.add(email)
                    max_uid = max(max_uid, email.uid)
                session.commit()
                inserted = len(batch)
            except (SQLAlchemyError, _sqlcipher_dbapi.IntegrityError):
                # UNIQUE(source, uid) 冲突 — 已被另一个 sync 写入
                # ⚠️ D3.3.2 修复：SQLCipher dialect 不包装 DBAPI 异常，
                # 实际抛出的是 `sqlcipher3.dbapi2.IntegrityError`，
                # 不是 `sqlalchemy.exc.IntegrityError` — D3.3.1 的 `except IntegrityError`
                # 漏掉这个类型，导致 IntegrityError 逃逸到 run_once 外层 try/except
                # 被错认为 "整批失败"（failed=100 而非 skipped=100）
                # ⚠️ D3.3.2 修复：rollback 显式 try/except — SQLCipher 在 session
                # 已 abort 状态时 rollback 可能再次失败，导致 `with session` __exit__
                # 重新抛出 IntegrityError 逃逸 try/except
                try:
                    session.rollback()
                except Exception as rb_err:
                    logger.warning(f"rollback 失败（已忽略）: {rb_err!r}")
                # 整批视作 skipped（D3 阶段简化：单封冲突不细化）
                # ⚠️ D3.3.1 修复：max_uid 重置为 0 — 整批回滚时未真正入库任何 uid，
                # 若返回原 max_uid 会让 SyncState.last_uid 跳到冲突 uid，
                # 下次 sync 时过滤 `uid > last_uid` 会跳过中间未入库邮件（数据丢失）
                max_uid = 0
                skipped = len(batch)
                logger.warning(f"批次 UNIQUE 冲突（{len(batch)} 封）— 视为已存在")
        return inserted, skipped, max_uid

    def _raw_to_email(self, source: str, raw: dict[str, Any], now_ms: int) -> Email:
        """IMAP raw dict → Email ORM 对象（D3.3 入库映射层）。

        关键映射：
            - received_at 缺失 → fallback 到 fetched_at（D3.1.1 决策）
            - recipients / labels → list[str]（JSONList TypeDecorator 处理）
            - body_text / body_html → D3 阶段先填空（不在 D3.3 范围，
              留 D4 LLM 分类后再回填）
        """
        received_at = raw.get("received_at")
        if received_at is None:
            # D3.1.1 决策：fallback 到 fetched_at
            received_at = now_ms
        elif isinstance(received_at, datetime):
            received_at = int(received_at.timestamp() * 1000)

        return Email(
            source=source,
            uid=raw.get("uid", 0),
            message_id=raw.get("message_id"),
            subject=raw.get("subject", ""),
            sender=raw.get("sender", ""),
            recipients=raw.get("recipients", []),
            received_at=received_at,
            raw_size=raw.get("raw_size", 0),
            body_text="",  # D4 LLM 分类时回填
            body_html="",  # D4 LLM 分类时回填
            fetched_at=now_ms,
            labels=raw.get("labels", []),
        )

    def _get_last_uid(self, session: Session, source: str) -> int:
        """读 SyncState.last_uid（首次返回 0）。"""
        stmt = select(SyncState.last_uid).where(SyncState.source == source)
        result = session.execute(stmt).scalar_one_or_none()
        return int(result) if result is not None else 0

    def _update_sync_state(
        self,
        session: Session,
        source: str,
        now_ms: int,
        new_last_uid: int,
        failed_count: int,
    ) -> None:
        """更新 SyncState（upsert 语义 — 首次写入、后续更新）。

        失败时记 last_status="failed" + last_error（便于后续调试），
        成功时 last_status="ok" + 清 last_error。
        """
        stmt = select(SyncState).where(SyncState.source == source)
        state = session.execute(stmt).scalar_one_or_none()

        if state is None:
            # 首次写入
            state = SyncState(
                source=source,
                last_sync_at=now_ms,
                last_uid=new_last_uid,
                last_status="failed" if failed_count > 0 else "ok",
                last_error="" if failed_count == 0 else f"{failed_count} 封失败",
                consecutive_failures=1 if failed_count > 0 else 0,
                updated_at=now_ms,
            )
            session.add(state)
        else:
            # 更新
            state.last_sync_at = now_ms
            state.last_uid = new_last_uid
            if failed_count > 0:
                state.last_status = "failed"
                state.last_error = f"{failed_count} 封失败"
                state.consecutive_failures += 1
            else:
                state.last_status = "ok"
                state.last_error = ""
                state.consecutive_failures = 0
            state.updated_at = now_ms

        session.commit()

    # ===== 资源清理 =====

    def close(self) -> None:
        """清理 sync 状态。

        D3.2.2 教训：SA engine 默认 SingletonThreadPool，**复用 db 的 conn**。
        若调 `engine.dispose()` 会把 db 的 SQLCipher conn 也关掉，
        导致后续 `db.execute/fetch_*` 报 "Cannot operate on a closed database"。

        因此 close() 只清内部状态引用，**不** dispose engine —
        SA engine 与 db 同寿命（由 db 显式 close 管理）。
        """
        self._engine = None  # 释放引用；db 仍持有底层 conn


# ===== 异步入口（scripts/sync_imap.py 用）=====


async def run_sync(
    db: Database,
    connector: BaseConnector,
    batch_size: int = 100,
    since: datetime | None = None,
) -> SyncResult:
    """一次性同步（async wrapper — 关闭 connector + 释放资源）。"""
    sync = IMAPSync(db, connector, batch_size=batch_size)
    try:
        return await sync.run_once(since=since)
    finally:
        sync.close()
        if hasattr(connector, "close"):
            await connector.close()
