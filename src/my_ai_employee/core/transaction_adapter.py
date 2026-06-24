"""D6.5 + D6.6 — TransactionAdapter: CSV 解析结果 → 分类 / 指纹 / 去重 / 入库.

承接 D6.1-D6.4:
    - connectors.wechat_csv.RawTransaction 解析层产物
    - core.categorizer.categorize 关键词分类
    - core.fingerprint.normalize_fingerprint 跨源候选指纹
    - db.transactions.TransactionStore 入库 + 状态机

D6.6 P2 修复(检查员驳回):
    - 原子化 insert + update_status(单事务,任一失败全回滚)
      沿 db.transactions.TransactionStore.insert_and_advance_status
    - 多候选信息记录(candidate_count + candidate_ids 字段)
    - failed_items 列表(每行失败的 ext_id + error_type + error_message)

本模块只做编排,不重复解析器 / Store 的严判逻辑。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from my_ai_employee.connectors.alipay_csv import AlipayCSVConnector
from my_ai_employee.connectors.wechat_csv import RawTransaction, WeChatCSVConnector
from my_ai_employee.core.categorizer import categorize
from my_ai_employee.core.fingerprint import normalize_fingerprint
from my_ai_employee.core.transactions import (
    TransactionIllegalTransitionError,
    TransactionStatus,
)
from my_ai_employee.db.transactions import (
    TransactionDuplicateError,
    TransactionStore,
)


@dataclass(frozen=True)
class FailedItem:
    """单行导入失败的详情(D6.6 P2 修复 — 给 failed_items 列表用).

    Attributes:
        external_transaction_id: 业务侧交易流水号(用户定位用)
        error_type: 异常类型名(如 'ValueError' / 'TransactionIllegalTransitionError')
        error_message: 异常 message(可空,None 表示没消息)
    """

    external_transaction_id: str
    error_type: str
    error_message: str


@dataclass(frozen=True)
class TransactionImportResult:
    """一次导入的结构化结果(D6.5 CLI / tests 共用 + D6.6 P2 扩展).

    D6.6 P2 扩展字段:
        - failed_items: 每行失败的 ext_id + error_type + error_message(原子化失败也记)
        - candidate_count: 跨源候选总数(累加,L2 命中次数)
        - candidate_ids: 所有候选 id(累加,可能有重复,因为不同 row 可能命中同一候选)
    """

    source: str
    parsed: int
    inserted: int
    categorized: int
    duplicates: int
    needs_confirm: int
    failed: int
    imported_ids: tuple[int, ...] = field(default_factory=tuple)
    duplicate_external_ids: tuple[str, ...] = field(default_factory=tuple)
    failed_items: tuple[FailedItem, ...] = field(default_factory=tuple)
    candidate_count: int = 0
    candidate_ids: tuple[int, ...] = field(default_factory=tuple)


class TransactionAdapter:
    """交易导入编排层(D6.5 + D6.6).

    设计:
      1. L1: import 前用 by_external_id 预检,insert_and_advance_status 原子兜底
      2. 分类: categorizer 规则分类,写 category
      3. 指纹: normalize_fingerprint(date, amount, counterparty)
      4. L2/L3: 若跨源同 fingerprint 已存在,新交易只标记 needs_confirm
      5. 状态: insert_and_advance_status 原子推到 categorized / needs_confirm
              (D6.6 P2 修复:单事务,任一失败全回滚)
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        wechat_connector: WeChatCSVConnector | None = None,
        alipay_connector: AlipayCSVConnector | None = None,
    ) -> None:
        self._store = TransactionStore(session_factory)
        self._wechat_connector = wechat_connector or WeChatCSVConnector()
        self._alipay_connector = alipay_connector or AlipayCSVConnector()

    def import_wechat_csv(
        self, path: Path, *, max_rows: int | None = None
    ) -> TransactionImportResult:
        """解析并导入微信 CSV 文件.

        Args:
            path: 微信账单 CSV 路径(已 sniff 版本,必传)
            max_rows: 限制单次导入行数(到达即 break);None = 全量(默认)

        v0.2.1 #2 真账单 spike 4 重防误发范本:spike 时通常传 1。
        """

        if not isinstance(path, Path):
            raise TypeError(f"path 必须是 Path,实际 {type(path).__name__}")
        if max_rows is not None and max_rows <= 0:
            raise ValueError(f"max_rows 必须为正整数,实际 {max_rows}")
        rows = self._wechat_connector.safe_parse(path)
        return self.import_raw_transactions(rows, source="wechat", max_rows=max_rows)

    def import_alipay_csv(
        self, path: Path, *, max_rows: int | None = None
    ) -> TransactionImportResult:
        """解析并导入支付宝 CSV 文件(D7.4 跨源共用).

        Args:
            path: 支付宝账单 CSV 路径(已 sniff 版本,必传)
            max_rows: 限制单次导入行数(到达即 break);None = 全量(默认)
        """

        if not isinstance(path, Path):
            raise TypeError(f"path 必须是 Path,实际 {type(path).__name__}")
        if max_rows is not None and max_rows <= 0:
            raise ValueError(f"max_rows 必须为正整数,实际 {max_rows}")
        rows = self._alipay_connector.safe_parse(path)
        return self.import_raw_transactions(rows, source="alipay", max_rows=max_rows)

    def import_raw_transactions(
        self,
        rows: Iterable[RawTransaction],
        *,
        source: str,
        max_rows: int | None = None,
    ) -> TransactionImportResult:
        """导入解析层交易列表,供 D6 微信和 D7 支付宝共用同一管线.

        Args:
            rows: 解析层产物
            source: 'wechat' / 'alipay'
            max_rows: 限制单次导入行数(到达即 break);None = 全量(默认)

        D6.6 P2 修复:
            - 原子化 insert + 状态机推进(单事务)
            - 业务/严判失败(TransactionIllegalTransitionError / ValueError / TypeError)→ 记 failed_items,继续
            - 业务阻断(TransactionDuplicateError)→ 记 duplicates,继续
            - 技术失败(OperationalError / DataError / InterfaceError)→ 透传,不捕获
              (沿 D3.3.3 教训,OperationalError 必透传)
            - 多候选:记录 candidate_count + candidate_ids(测试锁定:选最小 id 是有意设计)

        v0.2.1 #2 真账单 spike 4 重防误发:max_rows=None(默认)走全量;
        spike 时传 max_rows=1 限制为 1 行(配合 --confirm + --count 锁 1)。
        """

        parsed = 0
        inserted = 0
        categorized = 0
        duplicates = 0
        needs_confirm = 0
        failed = 0
        imported_ids: list[int] = []
        duplicate_external_ids: list[str] = []
        failed_items: list[FailedItem] = []
        candidate_count_total = 0
        candidate_ids: list[int] = []

        for raw in rows:
            # v0.2.1 #2 真账单 spike 4 重防误发:max_rows 到达即 break(不继续)
            # 优先在循环最前判:已 parsed 数量 + 1 == max_rows 时不进入本轮
            if max_rows is not None and parsed >= max_rows:
                break
            parsed += 1
            if self._store.by_external_id(source, raw.external_transaction_id) is not None:
                duplicates += 1
                duplicate_external_ids.append(raw.external_transaction_id)
                continue

            try:
                category = categorize(raw.counterparty, raw.amount)
                # v0.2.28 L2 fingerprint sign-lock:消除反向符号误判导致的偶然跨源 L2 命中
                # 跨源判定:微信(收/付) ↔ 支付宝(收/支) 共用同一 sign 才命中
                # type="支出"(微信付/支付宝支)→ sign=+1;type="收入"(微信收/支付宝收)→ sign=-1
                _sign = +1 if raw.type == "支出" else -1
                fingerprint = normalize_fingerprint(
                    raw.date, raw.amount, raw.counterparty, sign=_sign
                )
                candidates = [
                    candidate
                    for candidate in self._store.find_candidates_by_fingerprint(fingerprint)
                    if candidate.source != source
                ]
                candidate_id = candidates[0].id if candidates else None

                # 记录多候选信息(D6.6 P2 — 测试锁定:选最小 id 是有意设计)
                if len(candidates) > 0:
                    candidate_count_total += len(candidates)
                    candidate_ids.extend(c.id for c in candidates)
                    if len(candidates) > 1:
                        logger.info(
                            f"[{source}] 多候选: ext_id={raw.external_transaction_id!r}, "
                            f"candidate_count={len(candidates)}, "
                            f"candidate_ids={[c.id for c in candidates]}, "
                            f"selected=min_id={candidate_id} "
                            f"(有意设计:选最早出现的,id ASC 排序)"
                        )

                target_status = (
                    TransactionStatus.NEEDS_CONFIRM
                    if candidate_id is not None
                    else TransactionStatus.CATEGORIZED
                )

                # 原子化 insert + 状态机推进(D6.6 P2 修复)
                tx = self._store.insert_and_advance_status(
                    source=source,
                    external_transaction_id=raw.external_transaction_id,
                    transaction_date=raw.date,
                    amount=raw.amount,
                    counterparty=raw.counterparty,
                    category=category.value,
                    payment_method=raw.payment_method or None,
                    normalized_fingerprint=fingerprint,
                    raw_row_json=self._raw_transaction_json(raw, source=source),
                    needs_confirm=candidate_id is not None,
                    candidate_match_id=candidate_id,
                    new_status=target_status,
                    from_status=TransactionStatus.IMPORTED,
                )
                inserted += 1
                imported_ids.append(tx.id)
                if tx.status == TransactionStatus.NEEDS_CONFIRM.value:
                    needs_confirm += 1
                elif tx.status == TransactionStatus.CATEGORIZED.value:
                    categorized += 1
            except TransactionDuplicateError:
                duplicates += 1
                duplicate_external_ids.append(raw.external_transaction_id)
            except (TransactionIllegalTransitionError, ValueError, TypeError) as e:
                # 业务/严判/状态机失败(D6.6 P2 修复:不 re-raise,记 failed_items,继续)
                # 沿 D3.3.3 教训:OperationalError 不在此列(技术失败必透传)
                failed += 1
                failed_items.append(
                    FailedItem(
                        external_transaction_id=raw.external_transaction_id,
                        error_type=type(e).__name__,
                        error_message=str(e) or repr(e),
                    )
                )
            # OperationalError / DataError / InterfaceError 不捕获(沿 D3.3.3 教训,透传)

        return TransactionImportResult(
            source=source,
            parsed=parsed,
            inserted=inserted,
            categorized=categorized,
            duplicates=duplicates,
            needs_confirm=needs_confirm,
            failed=failed,
            imported_ids=tuple(imported_ids),
            duplicate_external_ids=tuple(duplicate_external_ids),
            failed_items=tuple(failed_items),
            candidate_count=candidate_count_total,
            candidate_ids=tuple(candidate_ids),
        )

    @staticmethod
    def _raw_transaction_json(raw: RawTransaction, *, source: str) -> str:
        payload: dict[str, Any] = {
            "source": source,
            "date": raw.date.isoformat(),
            "amount": str(raw.amount),
            "counterparty": raw.counterparty,
            "type": raw.type,
            "payment_method": raw.payment_method,
            "external_transaction_id": raw.external_transaction_id,
            "raw_row_hash": raw.raw_row_hash,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


__all__ = [
    "TransactionAdapter",
    "TransactionImportResult",
    "FailedItem",
    "categorize",
]
