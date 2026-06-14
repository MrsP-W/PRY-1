"""D6.5 — TransactionAdapter: CSV 解析结果 → 分类 / 指纹 / 去重 / 入库.

承接 D6.1-D6.4:
    - connectors.wechat_csv.RawTransaction 解析层产物
    - core.categorizer.categorize 关键词分类
    - core.fingerprint.normalize_fingerprint 跨源候选指纹
    - db.transactions.TransactionStore 入库 + 状态机

本模块只做编排,不重复解析器 / Store 的严判逻辑。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from my_ai_employee.connectors.wechat_csv import RawTransaction, WeChatCSVConnector
from my_ai_employee.core.categorizer import categorize
from my_ai_employee.core.fingerprint import normalize_fingerprint
from my_ai_employee.core.transactions import TransactionStatus
from my_ai_employee.db.transactions import (
    TransactionDuplicateError,
    TransactionStore,
)


@dataclass(frozen=True)
class TransactionImportResult:
    """一次导入的结构化结果(D6.5 CLI / tests 共用)."""

    source: str
    parsed: int
    inserted: int
    categorized: int
    duplicates: int
    needs_confirm: int
    failed: int
    imported_ids: tuple[int, ...] = field(default_factory=tuple)
    duplicate_external_ids: tuple[str, ...] = field(default_factory=tuple)


class TransactionAdapter:
    """交易导入编排层(D6.5).

    设计:
      1. L1: import 前用 by_external_id 预检,insert UNIQUE 兜底
      2. 分类: categorizer 规则分类,写 category
      3. 指纹: normalize_fingerprint(date, amount, counterparty)
      4. L2/L3: 若跨源同 fingerprint 已存在,新交易只标记 needs_confirm
      5. 状态: inserted 后从 imported 推到 categorized / needs_confirm
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        wechat_connector: WeChatCSVConnector | None = None,
    ) -> None:
        self._store = TransactionStore(session_factory)
        self._wechat_connector = wechat_connector or WeChatCSVConnector()

    def import_wechat_csv(self, path: Path) -> TransactionImportResult:
        """解析并导入微信 CSV 文件."""

        if not isinstance(path, Path):
            raise TypeError(f"path 必须是 Path,实际 {type(path).__name__}")
        rows = self._wechat_connector.safe_parse(path)
        return self.import_raw_transactions(rows, source="wechat")

    def import_raw_transactions(
        self,
        rows: Iterable[RawTransaction],
        *,
        source: str,
    ) -> TransactionImportResult:
        """导入解析层交易列表,供 D6 微信和 D7 支付宝共用同一管线."""

        parsed = 0
        inserted = 0
        categorized = 0
        duplicates = 0
        needs_confirm = 0
        failed = 0
        imported_ids: list[int] = []
        duplicate_external_ids: list[str] = []

        for raw in rows:
            parsed += 1
            if self._store.by_external_id(source, raw.external_transaction_id) is not None:
                duplicates += 1
                duplicate_external_ids.append(raw.external_transaction_id)
                continue

            try:
                category = categorize(raw.counterparty, raw.amount)
                fingerprint = normalize_fingerprint(raw.date, raw.amount, raw.counterparty)
                candidates = [
                    candidate
                    for candidate in self._store.find_candidates_by_fingerprint(fingerprint)
                    if candidate.source != source
                ]
                candidate_id = candidates[0].id if candidates else None
                tx = self._store.insert(
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
                )
                inserted += 1
                imported_ids.append(tx.id)

                target_status = (
                    TransactionStatus.NEEDS_CONFIRM
                    if candidate_id is not None
                    else TransactionStatus.CATEGORIZED
                )
                updated = self._store.update_status(
                    tx.id,
                    target_status.value,
                    from_status=TransactionStatus.IMPORTED.value,
                )
                if updated.status == TransactionStatus.NEEDS_CONFIRM.value:
                    needs_confirm += 1
                elif updated.status == TransactionStatus.CATEGORIZED.value:
                    categorized += 1
            except TransactionDuplicateError:
                duplicates += 1
                duplicate_external_ids.append(raw.external_transaction_id)
            except Exception:
                failed += 1
                raise

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
]
