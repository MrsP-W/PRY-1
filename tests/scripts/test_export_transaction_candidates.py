"""v0.2.29 — export_transaction_candidates.py 只读候选导出测试."""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


class _Tx:
    """脚本序列化测试用最小 Transaction duck type."""

    def __init__(
        self,
        *,
        tx_id: int,
        source: str,
        ext_id: str,
        amount: Decimal,
        counterparty: str,
        candidate_match_id: int | None = None,
    ) -> None:
        self.id = tx_id
        self.source = source
        self.external_transaction_id = ext_id
        self.transaction_date = date(2026, 6, 23)
        self.amount = amount
        self.counterparty = counterparty
        self.category = "dining"
        self.payment_method = "零钱"
        self.status = "needs_confirm"
        self.imported_at_ms = 1_782_200_000_000
        self.normalized_fingerprint = "a" * 32
        self.candidate_match_id = candidate_match_id


def test_build_candidate_review_row_includes_tx_and_candidate_fields() -> None:
    """JSON/CSV 共用行包含新交易 + 候选交易字段,Decimal/date 稳定字符串化."""
    from scripts.export_transaction_candidates import build_candidate_review_row

    tx = _Tx(
        tx_id=2,
        source="alipay",
        ext_id="alipay-1",
        amount=Decimal("38.5"),
        counterparty="星巴克",
        candidate_match_id=1,
    )
    candidate = _Tx(
        tx_id=1,
        source="wechat",
        ext_id="wechat-1",
        amount=Decimal("38.50"),
        counterparty="星巴克",
    )

    row = build_candidate_review_row(tx, candidate)  # type: ignore[arg-type]

    assert row["tx_id"] == 2
    assert row["amount"] == "38.50"
    assert row["transaction_date"] == "2026-06-23"
    assert row["candidate_missing"] is False
    assert row["candidate_source"] == "wechat"
    assert row["candidate_amount"] == "38.50"


def test_write_rows_jsonl_and_csv(tmp_path: Path) -> None:
    """导出函数支持 JSONL/CSV,字段稳定可被下游人工 review 工具读取."""
    from scripts.export_transaction_candidates import _write_rows

    rows = [
        {
            "tx_id": 2,
            "source": "alipay",
            "external_transaction_id": "alipay-1",
            "transaction_date": "2026-06-23",
            "amount": "38.50",
            "counterparty": "星巴克",
            "category": "dining",
            "payment_method": "余额",
            "status": "needs_confirm",
            "imported_at_ms": 1_782_200_000_000,
            "normalized_fingerprint": "a" * 32,
            "candidate_match_id": 1,
            "candidate_missing": False,
            "candidate_source": "wechat",
            "candidate_external_transaction_id": "wechat-1",
            "candidate_transaction_date": "2026-06-23",
            "candidate_amount": "38.50",
            "candidate_counterparty": "星巴克",
            "candidate_category": "dining",
            "candidate_payment_method": "零钱",
        }
    ]

    jsonl_path = tmp_path / "candidates.jsonl"
    _write_rows(rows, output_format="jsonl", output_path=jsonl_path)
    parsed = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
    assert parsed["tx_id"] == 2
    assert parsed["candidate_source"] == "wechat"

    csv_path = tmp_path / "candidates.csv"
    _write_rows(rows, output_format="csv", output_path=csv_path)
    with csv_path.open(encoding="utf-8", newline="") as f:
        parsed_csv = list(csv.DictReader(f))
    assert parsed_csv[0]["source"] == "alipay"
    assert parsed_csv[0]["candidate_amount"] == "38.50"


def test_write_rows_jsonl_stdout(monkeypatch) -> None:
    """未传 output_path 时输出到 stdout,便于管道处理."""
    from scripts.export_transaction_candidates import _write_rows

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    _write_rows([{"tx_id": 1}], output_format="jsonl", output_path=None)

    assert json.loads(buf.getvalue()) == {"tx_id": 1}
