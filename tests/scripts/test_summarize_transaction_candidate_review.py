"""v0.2.31 — summarize_transaction_candidate_review.py 只读汇总脚本测试.

承接 v0.2.29 export_transaction_candidates.py 范本 + v0.2.30 CLI 硬化范本:
    - 6-8 tests 覆盖 _read_rows / build_summary_report / _validate_cli_args / _validate_review_decisions / main
    - 不写 DB / 不导入账单 / 不打 tag
"""

from __future__ import annotations

import csv
import json
import sys
from argparse import Namespace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# ===== Fixtures =====


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _fake_rows() -> list[dict]:
    """构造 3 行候选:1 行同金额同商户 + 1 行不同金额 + 1 行 missing."""
    return [
        {
            "tx_id": 2,
            "source": "alipay",
            "external_transaction_id": "a1",
            "transaction_date": "2025-03-10",
            "amount": "42.00",
            "counterparty": "麦当劳(朝阳店)",
            "category": "dining",
            "payment_method": "支付宝",
            "status": "needs_confirm",
            "candidate_match_id": 1,
            "candidate_missing": "False",
            "candidate_source": "wechat",
            "candidate_external_transaction_id": "w1",
            "candidate_transaction_date": "2025-03-10",
            "candidate_amount": "42.00",
            "candidate_counterparty": "麦当劳(朝阳店)",
            "candidate_category": "dining",
            "candidate_payment_method": "微信支付",
        },
        {
            "tx_id": 3,
            "source": "wechat",
            "external_transaction_id": "w2",
            "transaction_date": "2025-03-11",
            "amount": "30.00",
            "counterparty": "美团",
            "category": "dining",
            "payment_method": "微信支付",
            "status": "needs_confirm",
            "candidate_match_id": 2,
            "candidate_missing": "False",
            "candidate_source": "alipay",
            "candidate_external_transaction_id": "a2",
            "candidate_transaction_date": "2025-03-11",
            "candidate_amount": "29.00",  # 金额不同 → 不计入"同金额同商户"
            "candidate_counterparty": "美团",
            "candidate_category": "dining",
            "candidate_payment_method": "支付宝",
        },
        {
            "tx_id": 4,
            "source": "alipay",
            "external_transaction_id": "a3",
            "transaction_date": "2025-03-12",
            "amount": "100.00",
            "counterparty": "滴滴",
            "category": "transport",
            "payment_method": "支付宝",
            "status": "needs_confirm",
            "candidate_match_id": None,
            "candidate_missing": "True",  # missing
            "candidate_source": "",
            "candidate_external_transaction_id": "",
            "candidate_transaction_date": "",
            "candidate_amount": "",
            "candidate_counterparty": "",
            "candidate_category": "",
            "candidate_payment_method": "",
        },
    ]


# ===== _validate_cli_args =====


def test_validate_cli_args_rejects_bad_top_n() -> None:
    """--top-n 预检先于文件读,避免用户传错参数时出现 traceback."""
    import pytest

    from scripts.summarize_transaction_candidate_review import _validate_cli_args

    with pytest.raises(ValueError, match="--top-n"):
        _validate_cli_args(Namespace(input_path=Path("x"), output_path=Path("y"), top_n=0))
    with pytest.raises(ValueError, match="--top-n"):
        _validate_cli_args(Namespace(input_path=Path("x"), output_path=Path("y"), top_n=1001))
    with pytest.raises(ValueError, match="--top-n"):
        _validate_cli_args(Namespace(input_path=Path("x"), output_path=Path("y"), top_n=True))


def test_validate_cli_args_accepts_valid_top_n() -> None:
    from scripts.summarize_transaction_candidate_review import _validate_cli_args

    # 边界 1 + 1000 + 中间值都通过
    _validate_cli_args(Namespace(input_path=Path("x"), output_path=Path("y"), top_n=1))
    _validate_cli_args(Namespace(input_path=Path("x"), output_path=Path("y"), top_n=1000))
    _validate_cli_args(Namespace(input_path=Path("x"), output_path=Path("y"), top_n=10))


# ===== _read_rows =====


def test_read_rows_csv_and_jsonl(tmp_path: Path) -> None:
    """支持 csv 与 jsonl 双格式,行为对齐 export 脚本."""
    from scripts.summarize_transaction_candidate_review import _read_rows

    csv_path = tmp_path / "c.csv"
    _write_csv(csv_path, _fake_rows())
    csv_rows = _read_rows(csv_path)
    assert len(csv_rows) == 3
    assert csv_rows[0]["counterparty"] == "麦当劳(朝阳店)"

    jsonl_path = tmp_path / "c.jsonl"
    _write_jsonl(jsonl_path, _fake_rows())
    jsonl_rows = _read_rows(jsonl_path)
    assert len(jsonl_rows) == 3
    assert jsonl_rows[1]["candidate_amount"] == "29.00"


def test_read_rows_missing_file() -> None:
    """输入文件不存在抛 FileNotFoundError,main 转译为 exit 1."""
    import pytest

    from scripts.summarize_transaction_candidate_review import _read_rows

    with pytest.raises(FileNotFoundError, match="不存在"):
        _read_rows(Path("/tmp/does-not-exist-xyz-12345.csv"))


def test_read_rows_unknown_suffix() -> None:
    """不支持的扩展名抛 ValueError,避免静默走默认."""
    import pytest

    from scripts.summarize_transaction_candidate_review import _read_rows

    bad = Path("foo.xlsx")
    with pytest.raises(ValueError, match="无法识别输入格式"):
        _read_rows(bad)


# ===== _validate_review_decisions =====


def test_validate_review_decisions_passes_for_whitelist() -> None:
    """review_decision 列三分类白名单通过."""
    from scripts.summarize_transaction_candidate_review import _validate_review_decisions

    rows = [
        {"review_decision": "same_transaction"},
        {"review_decision": "separate_transactions"},
        {"review_decision": "needs_investigation"},
        {},  # 无 decision 列也通过
    ]
    assert _validate_review_decisions(rows) == []


def test_validate_review_decisions_flags_invalid() -> None:
    """非白名单取值列入非法集合."""
    from scripts.summarize_transaction_candidate_review import _validate_review_decisions

    rows = [
        {"review_decision": "auto_merge"},  # 非法
        {"review_decision": "same_transaction"},
        {"review_decision": "other"},
    ]
    invalid = _validate_review_decisions(rows)
    assert "auto_merge" in invalid
    assert "other" in invalid
    assert "same_transaction" not in invalid


# ===== build_summary_report =====


def test_build_summary_report_renders_all_sections(tmp_path: Path) -> None:
    """6 维度全渲染,数字精确."""
    from scripts.summarize_transaction_candidate_review import build_summary_report

    rows = _fake_rows()
    report = build_summary_report(rows, input_path=tmp_path / "in.csv", top_n=5)

    assert "# Transaction Candidate Review Summary" in report
    assert "**总候选数**:3" in report
    assert "**候选匹配缺失数**(candidate_missing=True):1" in report
    # source 分布
    assert "alipay" in report
    assert "wechat" in report
    # 同金额同商户:只有第 1 行命中(42.00 + 麦当劳(朝阳店))
    assert "麦当劳(朝阳店)" in report
    # review_decision 未提供 → 提示 schema
    assert "review_decision" in report
    assert "same_transaction" in report


def test_build_summary_report_with_decisions(tmp_path: Path) -> None:
    """提供 review_decision 后三分类渲染 + 样例."""
    from scripts.summarize_transaction_candidate_review import build_summary_report

    rows = _fake_rows()
    rows[0]["review_decision"] = "same_transaction"
    rows[1]["review_decision"] = "separate_transactions"
    rows[2]["review_decision"] = "needs_investigation"

    report = build_summary_report(rows, input_path=tmp_path / "in.csv", top_n=5)
    assert "**总决策数**:3/3" in report
    assert "Same Transaction(同笔交易,可合并)" in report
    assert "Separate Transactions(两笔独立,各自保留)" in report
    assert "Needs Investigation(信息不足,待查)" in report
    # 样例表
    assert "样例(前 3 行)" in report


def test_build_summary_report_no_double_hash_in_titles(tmp_path: Path) -> None:
    """防 ## ## 标题双 # 渲染回归:每段 H2 标题只能出现 1 次."""
    from scripts.summarize_transaction_candidate_review import build_summary_report

    rows = _fake_rows()
    report = build_summary_report(rows, input_path=tmp_path / "in.csv", top_n=5)

    # 全部 ## 标题
    h2_titles = [line for line in report.splitlines() if line.startswith("## ")]
    assert h2_titles, "至少要有一个 H2 标题"
    # 任何 ## 标题中不应该出现 ##(防 ## ##)
    for line in h2_titles:
        assert "##" not in line[2:], f"H2 标题内部不应再出现 #: {line!r}"


# ===== main 集成 =====


def test_main_end_to_end_csv(tmp_path: Path, capsys) -> None:
    """主流程:CSV 输入 → markdown 输出,退出码 0."""
    from scripts.summarize_transaction_candidate_review import main

    in_path = tmp_path / "in.csv"
    out_path = tmp_path / "summary.md"
    _write_csv(in_path, _fake_rows())

    rc = main(
        [
            "--input-path",
            str(in_path),
            "--output-path",
            str(out_path),
            "--top-n",
            "5",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "# Transaction Candidate Review Summary" in content
    assert "**总候选数**:3" in content


def test_main_rejects_invalid_decision(tmp_path: Path, capsys) -> None:
    """review_decision 非法值 → exit 2 + stderr 报错."""
    from scripts.summarize_transaction_candidate_review import main

    rows = _fake_rows()
    rows[0]["review_decision"] = "auto_merge"
    in_path = tmp_path / "in.csv"
    _write_csv(in_path, rows)

    rc = main(
        [
            "--input-path",
            str(in_path),
            "--output-path",
            str(tmp_path / "summary.md"),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "非法取值" in err
    assert "auto_merge" in err


def test_main_rejects_missing_file(tmp_path: Path, capsys) -> None:
    """输入文件不存在 → exit 1 + stderr 报错."""
    from scripts.summarize_transaction_candidate_review import main

    rc = main(
        [
            "--input-path",
            str(tmp_path / "nope.csv"),
            "--output-path",
            str(tmp_path / "summary.md"),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "不存在" in err


def test_main_rejects_bad_top_n(capsys) -> None:
    """CLI 参数错误 → exit 1,不打开文件."""
    from scripts.summarize_transaction_candidate_review import main

    rc = main(
        [
            "--input-path",
            "x",
            "--output-path",
            "y",
            "--top-n",
            "0",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "--top-n" in err
