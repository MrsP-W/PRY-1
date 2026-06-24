#!/usr/bin/env python3
"""v0.2.31 — 汇总 transaction-candidates.csv 人工 review 产物.

承接 v0.2.29 export_transaction_candidates.py 导出 CSV/JSONL:
    - 读 CSV(也支持 JSONL)
    - 计算 6 维度统计(总候选 / source 分布 / 商户 Top N / 同金额同商户 / candidate_missing / review_decision 三分类)
    - 写 markdown 汇总报告(本地不入库,.gitignore 保护)

只读边界:
    - 不写 DB / 不导入账单 / 不修改 transactions
    - 不自动确认 / 合并 / 删除候选
    - review_decision 仅是用户事后标注,本脚本只统计不做决策

用法:
    uv run python scripts/summarize_transaction_candidate_review.py
    uv run python scripts/summarize_transaction_candidate_review.py --input-path reports/transaction-candidates.csv
    uv run python scripts/summarize_transaction_candidate_review.py --input-path reports/transaction-candidates.csv --output-path reports/summary.md
    uv run python scripts/summarize_transaction_candidate_review.py --input-path reports/transaction-candidates.csv --top-n 20

退出码:
    0 = 成功生成汇总(包括 0 候选)
    1 = CLI 参数错误 / 文件不存在或格式错误
    2 = review_decision 列存在非法取值
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# v0.2.31 review_decision 三分类白名单(与 v0.2.29 export 报告 §"建议动作 2" 对齐)
_REVIEW_DECISION_ALLOWED = frozenset(
    {"same_transaction", "separate_transactions", "needs_investigation"}
)
_REVIEW_DECISION_DISPLAY = {
    "same_transaction": "Same Transaction(同笔交易,可合并)",
    "separate_transactions": "Separate Transactions(两笔独立,各自保留)",
    "needs_investigation": "Needs Investigation(信息不足,待查)",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="汇总 transaction-candidates CSV/JSONL 人工 review 产物"
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        default=Path("reports/transaction-candidates.csv"),
        help="输入 CSV/JSONL 路径,默认 reports/transaction-candidates.csv",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("reports/transaction-candidate-review-summary.md"),
        help="输出 markdown 路径,默认 reports/transaction-candidate-review-summary.md",
    )
    parser.add_argument("--top-n", type=int, default=10, help="counterparty Top N,默认 10")
    return parser


def _validate_cli_args(args: argparse.Namespace) -> None:
    """CLI 入参预检,失败时返回可读错误而非文件打开后的 traceback."""
    if type(args.top_n) is bool or not isinstance(args.top_n, int) or args.top_n < 1:
        raise ValueError(f"--top-n 必须是 >= 1 的 int,实际 {args.top_n!r}")
    if args.top_n > 1000:
        raise ValueError(f"--top-n 必须 <= 1000,实际 {args.top_n!r}")
    if not args.input_path:
        raise ValueError("--input-path 不能为空")


def _detect_format(path: Path) -> str:
    """根据扩展名检测输入格式,csv 或 jsonl."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in (".jsonl", ".json"):
        return "jsonl"
    raise ValueError(f"无法识别输入格式(扩展名 {suffix!r}),仅支持 .csv / .jsonl / .json")


def _read_rows(input_path: Path) -> list[dict[str, Any]]:
    """读 CSV/JSONL 返回行列表,任一格式错误抛 ValueError."""
    fmt = _detect_format(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    rows: list[dict[str, Any]] = []

    if fmt == "csv":
        with input_path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
    else:
        with input_path.open(encoding="utf-8") as f:
            for line_no, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError as e:
                    raise ValueError(f"第 {line_no} 行 JSON 解析失败: {e}") from e
    return rows


def _validate_review_decisions(rows: list[dict[str, Any]]) -> list[str]:
    """检查 review_decision 列(若存在),返回非法取值列表。"""
    invalid: list[str] = []
    for row in rows:
        decision = row.get("review_decision")
        if decision is None or decision == "":
            continue
        decision_str = str(decision).strip()
        if decision_str not in _REVIEW_DECISION_ALLOWED:
            invalid.append(decision_str)
    return invalid


def _format_count_table(title: str, counter: Counter[str], total: int) -> list[str]:
    """把 Counter 渲染成 markdown 表格。"""
    lines = [f"## {title}", ""]
    if not counter:
        lines.append("_(无数据)_")
        lines.append("")
        return lines
    lines.append("| 取值 | 数量 | 占比 |")
    lines.append("|------|------|------|")
    for key, count in counter.most_common():
        pct = (count / total * 100) if total > 0 else 0.0
        lines.append(f"| {key} | {count} | {pct:.1f}% |")
    lines.append("")
    return lines


def _format_review_decision_table(
    samples: dict[str, list[dict[str, Any]]],
    counts: Counter[str],
    total_decided: int,
    total_rows: int,
) -> list[str]:
    """渲染 review_decision 三分类 + 样例。"""
    lines = ["### Review Decision 三分类(可选)", ""]
    if total_decided == 0:
        lines.append("_(本 CSV 未包含 review_decision 列,需用户在导出后手动标注)_")
        lines.append("")
        lines.append("**用户标注 schema**(单列加在 CSV 末尾):")
        lines.append("")
        lines.append("```csv")
        lines.append("review_decision")
        lines.append("same_transaction")
        lines.append("separate_transactions")
        lines.append("needs_investigation")
        lines.append("```")
        lines.append("")
        return lines

    lines.append("| 决策 | 数量 | 占比 |")
    lines.append("|------|------|------|")
    for key in ("same_transaction", "separate_transactions", "needs_investigation"):
        count = counts.get(key, 0)
        pct = (count / total_decided * 100) if total_decided > 0 else 0.0
        lines.append(f"| {_REVIEW_DECISION_DISPLAY[key]} | {count} | {pct:.1f}% |")
    lines.append("")
    lines.append(f"**总决策数**:{total_decided}/{total_rows}")
    lines.append("")

    # 每类前 3 行样例
    for key in ("same_transaction", "separate_transactions", "needs_investigation"):
        rows = samples.get(key, [])
        if not rows:
            continue
        lines.append(f"**{_REVIEW_DECISION_DISPLAY[key]} 样例(前 3 行)**:")
        lines.append("")
        lines.append("| tx_id | source | date | amount | counterparty | candidate |")
        lines.append("|-------|--------|------|--------|--------------|-----------|")
        for row in rows[:3]:
            lines.append(
                f"| {row.get('tx_id', '')} "
                f"| {row.get('source', '')} "
                f"| {row.get('transaction_date', '')} "
                f"| {row.get('amount', '')} "
                f"| {row.get('counterparty', '')} "
                f"| {row.get('candidate_source', '')} |"
            )
        lines.append("")
    return lines


def build_summary_report(
    rows: list[dict[str, Any]],
    *,
    input_path: Path,
    top_n: int,
) -> str:
    """构造 markdown 汇总报告全文。"""
    total = len(rows)
    source_counter: Counter[str] = Counter()
    counterparty_counter: Counter[str] = Counter()
    same_amount_counterparty: Counter[str] = Counter()
    missing_count = 0
    decided_samples: dict[str, list[dict[str, Any]]] = {}
    decision_counter: Counter[str] = Counter()
    decided_total = 0

    for row in rows:
        source = str(row.get("source", "")).strip()
        if source:
            source_counter[source] += 1
        counterparty = str(row.get("counterparty", "")).strip()
        if counterparty:
            counterparty_counter[counterparty] += 1
        # 同金额同商户:同时有 new amount + candidate amount + counterparty 一致
        new_amount = str(row.get("amount", "")).strip()
        cand_amount = str(row.get("candidate_amount", "")).strip()
        cand_cp = str(row.get("candidate_counterparty", "")).strip()
        if (
            new_amount
            and cand_amount
            and new_amount == cand_amount
            and counterparty
            and counterparty == cand_cp
        ):
            same_amount_counterparty[counterparty] += 1
        # candidate_missing
        missing_val = row.get("candidate_missing", "")
        if str(missing_val).lower() in ("true", "1", "yes"):
            missing_count += 1
        # review_decision
        decision = str(row.get("review_decision", "")).strip()
        if decision:
            decided_total += 1
            decision_counter[decision] += 1
            decided_samples.setdefault(decision, []).append(row)

    lines: list[str] = []
    lines.append("# Transaction Candidate Review Summary(2026-06-24)")
    lines.append("")
    lines.append(f"> **输入文件**:`{input_path}` · **生成时间**:v0.2.31 汇总脚本")
    lines.append(f"> **总候选数**:{total}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 总览
    lines.append("## 1. 总览")
    lines.append("")
    lines.append(f"- **总候选数**:{total}")
    lines.append(f"- **候选匹配缺失数**(candidate_missing=True):{missing_count}")
    lines.append(f"- **review_decision 已决策数**:{decided_total}/{total}")
    lines.append("")

    # 2. 按 source 分布
    lines.extend(_format_count_table("2. 按 source 分布", source_counter, total))

    # 3. 按 counterparty Top N
    lines.append(f"## 3. 按 counterparty Top {top_n}")
    lines.append("")
    if not counterparty_counter:
        lines.append("_(无 counterparty 数据)_")
    else:
        lines.append("| 排名 | counterparty | 候选数 | 占比 |")
        lines.append("|------|--------------|--------|------|")
        for rank, (cp, count) in enumerate(counterparty_counter.most_common(top_n), 1):
            pct = (count / total * 100) if total > 0 else 0.0
            lines.append(f"| {rank} | {cp} | {count} | {pct:.1f}% |")
    lines.append("")

    # 4. 同金额同商户候选
    lines.append("## 4. 同金额同商户候选(高度可疑同笔)")
    lines.append("")
    if not same_amount_counterparty:
        lines.append("_(本批无金额与商户均匹配的候选,人工 review 优先级降低)_")
    else:
        lines.append("| counterparty | 候选数 |")
        lines.append("|--------------|--------|")
        for cp, count in same_amount_counterparty.most_common(top_n):
            lines.append(f"| {cp} | {count} |")
    lines.append("")

    # 5. review_decision 三分类
    lines.extend(
        _format_review_decision_table(decided_samples, decision_counter, decided_total, total)
    )

    # 6. 沿用边界 + 下一步
    lines.append("## 6. 沿用边界(本脚本)")
    lines.append("")
    lines.append("- ❌ 不写回 DB")
    lines.append("- ❌ 不自动确认 / 合并 / 删除候选")
    lines.append("- ❌ 不导入账单")
    lines.append("- ❌ 不打 v0.2.31 tag(8/1 锚定策略)")
    lines.append("")
    lines.append("## 7. 下一步候选")
    lines.append("")
    lines.append("1. **今天**:本汇总报告本地 review,不入库")
    lines.append("2. **本周**:用户提供真实微信/支付宝 CSV → `--max-rows 1` 小样本导入 → 重跑汇总")
    lines.append("3. **7/1**:月度复盘窗口,统一 review v0.2.27 ~ v0.2.31 五类报告")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        _validate_cli_args(args)
    except ValueError as e:
        print(f"参数错误: {e}", file=sys.stderr)
        return 1

    try:
        rows = _read_rows(args.input_path)
    except FileNotFoundError as e:
        print(f"输入文件不存在: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"输入文件格式错误: {e}", file=sys.stderr)
        return 1

    invalid_decisions = _validate_review_decisions(rows)
    if invalid_decisions:
        unique_invalid = sorted(set(invalid_decisions))
        print(
            f"review_decision 列存在非法取值: {unique_invalid!r}",
            file=sys.stderr,
        )
        print(
            f"合法取值: {sorted(_REVIEW_DECISION_ALLOWED)}",
            file=sys.stderr,
        )
        return 2

    report = build_summary_report(rows, input_path=args.input_path, top_n=args.top_n)

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(report, encoding="utf-8")
    print(
        f"candidate review summary: rows={len(rows)} "
        f"input={args.input_path} output={args.output_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
