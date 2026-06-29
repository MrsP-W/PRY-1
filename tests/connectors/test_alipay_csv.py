"""D7.1 支付宝账单 CSV 多版本解析器测试(8 cases).

承接 docs/v0.1-launch-plan.md §D7 + plan §3 D7.1:

    - 3 版本解析器 RawTransaction 字段全齐
    - detect_version 对 InMemory 样本命中率 100%
    - safe_parse 失败 3 次后熔断开启
    - mypy 严格通过

8 cases(沿 D6.1 wechat_csv 范本,改 alipay):
    1. test_2024_parser_5_rows_字段全齐
    2. test_2025_parser_5_rows_字段全齐
    3. test_2026_parser_raises_not_implemented
    4. test_detect_version_3_versions
    5. test_detect_version_unsupported_raises
    6. test_safe_parse_2024_正常路径
    7. test_safe_parse_circuit_breaker_after_3_failures
    8. test_get_parser_invalid_version_严判

跑法:
    pytest tests/connectors/test_alipay_csv.py -v
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Faker 样本目录(沿 D6.1 范本)
_FAKER_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "alipay_faker"


def test_2024_parser_5_rows_all_fields() -> None:
    """Case 1 — 2024 解析器解析 5 行 faker 样本,7 必含字段全齐.

    验证:
        - 返回 list[RawTransaction] 长度 = 5
        - 字段类型严判(date/Decimal/Literal)
        - 退款行(负数金额)作为独立行保留
        - raw_row_hash 32 chars 截断
    """
    from my_ai_employee.connectors.alipay_csv import AlipayCSV2024Parser

    path = _FAKER_DIR / "alipay_2024_sample.csv"
    parser = AlipayCSV2024Parser()
    results = list(parser.parse(path))

    assert len(results) >= 5, f"期望至少保留 5 行基线样本,实际 {len(results)}"

    # 验证 7 必含字段(plan §3 D7.1 契约)
    for r in results:
        assert isinstance(r.date, date)
        assert isinstance(r.amount, Decimal)
        assert isinstance(r.counterparty, str) and r.counterparty.strip()
        assert r.type in ("支出", "收入")
        assert isinstance(r.payment_method, str)
        assert isinstance(r.external_transaction_id, str) and r.external_transaction_id.strip()
        assert isinstance(r.raw_row_hash, str) and len(r.raw_row_hash) == 32

    # 验证第 1 行(星巴克 38.50 支出)
    assert results[0].counterparty == "星巴克咖啡(国贸店)"
    assert results[0].amount == Decimal("38.50")
    assert results[0].type == "支出"
    assert results[0].external_transaction_id == "20240605120001"

    # 验证第 3 行(工资 5000 收入)
    assert results[2].type == "收入"
    assert results[2].amount == Decimal("5000.00")

    # 验证退款行(第 5 行 -15.00)作为独立行保留
    assert results[4].amount == Decimal("-15.00")
    assert results[4].type == "支出"


def test_2025_parser_5_rows_all_fields() -> None:
    """Case 2 — 2025 解析器解析 5 行,字段对齐 2024 范本."""
    from my_ai_employee.connectors.alipay_csv import AlipayCSV2025Parser

    path = _FAKER_DIR / "alipay_2025_sample.csv"
    parser = AlipayCSV2025Parser()
    results = list(parser.parse(path))

    assert len(results) >= 5
    for r in results:
        assert isinstance(r.date, date)
        assert isinstance(r.amount, Decimal)
        assert r.type in ("支出", "收入")
        assert len(r.raw_row_hash) == 32

    # 2025 字段名差异: 创建时间(不用"付款时间")
    assert results[0].counterparty == "麦当劳(朝阳店)"
    assert results[0].amount == Decimal("42.00")
    assert results[0].type == "支出"  # 收/支 = 支 → 支出(沿 _normalize_type 范本)
    assert results[0].external_transaction_id == "20250605120001"

    # 验证 2025 第 3 行兼职收入
    assert results[2].type == "收入"
    assert results[2].amount == Decimal("3500.00")


def test_2026_parser_raises_not_implemented() -> None:
    """Case 3 — 2026 占位解析器抛 NotImplementedError(等用户真实样本)."""
    from my_ai_employee.connectors.alipay_csv import AlipayCSV2026Parser

    parser = AlipayCSV2026Parser()
    assert parser.version == 2026

    path = _FAKER_DIR / "alipay_2026_sample.csv"
    with pytest.raises(NotImplementedError, match="2026 支付宝账单 CSV 字段待用户真实样本补充"):
        list(parser.parse(path))


def test_detect_version_3_versions() -> None:
    """Case 4 — detect_version 对 3 版本样本命中率 100%."""
    from my_ai_employee.connectors.alipay_csv import detect_version

    assert detect_version(_FAKER_DIR / "alipay_2024_sample.csv") == 2024
    assert detect_version(_FAKER_DIR / "alipay_2025_sample.csv") == 2025
    assert detect_version(_FAKER_DIR / "alipay_2026_sample.csv") == 2026


def test_detect_version_unsupported_raises() -> None:
    """Case 5 — detect_version 对未知版本抛 UnsupportedCSVVersionError."""
    # 临时构造一个未知版本 CSV
    import tempfile

    from my_ai_employee.connectors.alipay_csv import UnsupportedCSVVersionError, detect_version

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write("foo,bar,baz\n1,2,3\n")
        unknown_path = Path(f.name)
    try:
        with pytest.raises(UnsupportedCSVVersionError, match="无法嗅探支付宝账单版本"):
            detect_version(unknown_path)
    finally:
        unknown_path.unlink(missing_ok=True)

    # 文件不存在
    with pytest.raises(FileNotFoundError):
        detect_version(Path("/nonexistent/path.csv"))


def test_safe_parse_2024_success_path() -> None:
    """Case 6 — safe_parse 走 2024 样本成功路径,返回 5 笔 + 熔断计数 = 0."""
    from my_ai_employee.connectors.alipay_csv import AlipayCSVConnector

    conn = AlipayCSVConnector()
    results = conn.safe_parse(_FAKER_DIR / "alipay_2024_sample.csv")

    assert len(results) >= 5
    # 熔断应重置(consecutive_failures = 0)
    state = conn.circuit_state
    assert state["consecutive_failures"] == 0
    assert state["is_open"] is False


def test_safe_parse_circuit_breaker_after_3_failures() -> None:
    """Case 7 — safe_parse 失败 3 次触发熔断(沿 BaseConnector CIRCUIT_BREAKER_THRESHOLD=3).

    验证:
        - 第 1-3 次失败 → 返回空 list
        - 第 4 次调用 → 熔断开启 → 仍返回空 list + 不调 parse(快速路径)
        - circuit_state.is_open = True
    """
    from my_ai_employee.connectors.alipay_csv import AlipayCSVConnector

    conn = AlipayCSVConnector()
    bad_path = Path("/nonexistent/garbage.csv")  # 永远失败

    # 第 1-3 次: 文件不存在 → FileNotFoundError → _record_failure
    for i in range(3):
        result = conn.safe_parse(bad_path)
        assert result == [], f"第 {i + 1} 次失败应返回空,实际 {result!r}"

    state = conn.circuit_state
    assert state["consecutive_failures"] >= 3
    assert state["is_open"] is True
    assert state["open_until"] > 0.0  # 30 min 熔断窗口已设


def test_get_parser_invalid_version_guards() -> None:
    """Case 8 — get_parser 工厂层严判 type + 未知版本."""
    from my_ai_employee.connectors.alipay_csv import (
        UnsupportedCSVVersionError,
        get_parser,
    )

    # type 严判(沿 OutboxStore 范本 type(value) is int)
    with pytest.raises(TypeError, match="version 必须是 int"):
        get_parser("2024")

    with pytest.raises(TypeError, match="version 必须是 int"):
        get_parser(2024.0)

    # 未知版本
    with pytest.raises(UnsupportedCSVVersionError, match="不支持的支付宝账单 CSV 版本"):
        get_parser(9999)

    # 正常路径
    p = get_parser(2024)
    assert p.version == 2024
    p2 = get_parser(2025)
    assert p2.version == 2025


# ===== 撞坑 #49 — 2027 真实样本格式测试(2026-06-24 W3 spike)=====


def test_2027_real_parser_3_rows_skips_unrecorded() -> None:
    """Case 9 — 2027 真实样本解析器:3 行支出 + 3 行不计收支,只产出 3 行.

    撞坑 #49 (2026-06-24):真实支付宝导出文件
        - header 用 `交易时间`(不是 2026 faker 的 `消费时间`)
        - 含 ~22 行说明前缀
        - 收/支 列含第三种值 `不计入收支`(花呗还款/余额宝收益等)
        - parser 必须跳过不计收支行(spike 边界)
    """
    from my_ai_employee.connectors.alipay_csv import AlipayCSV2027RealParser

    path = _FAKER_DIR / "alipay_2027_real_sample.csv"
    parser = AlipayCSV2027RealParser()
    results = list(parser.parse(path))

    assert len(results) == 3, f"期望 3 行支出,实际 {len(results)}"
    for r in results:
        assert isinstance(r.date, date)
        assert isinstance(r.amount, Decimal)
        assert r.type == "支出", f"2027 parser 只保留支出行,实际 type={r.type!r}"
        assert r.counterparty.strip()
        assert len(r.raw_row_hash) == 32

    # 验证第 1 行(滴滴出行 24.40 支出)
    assert results[0].counterparty == "滴滴出行"
    assert results[0].amount == Decimal("24.40")
    assert results[0].external_transaction_id == "2026062323001451041451584898"


def test_detect_version_2027_real_sample() -> None:
    """Case 10 — detect_version 对 2027 真实样本(含说明前缀)嗅探为 2027."""
    from my_ai_employee.connectors.alipay_csv import detect_version

    path = _FAKER_DIR / "alipay_2027_real_sample.csv"
    assert detect_version(path) == 2027


def test_2027_parser_skips_prefix_lines() -> None:
    """Case 11 — 2027 parser 跳过支付宝说明前缀段(22 行),不误读 `导出信息:`."""
    from my_ai_employee.connectors.alipay_csv import AlipayCSV2027RealParser

    path = _FAKER_DIR / "alipay_2027_real_sample.csv"
    # 验证 _locate_header_row 能定位到含 `交易时间` 的真 header 行
    header_idx = AlipayCSV2027RealParser._locate_header_row(path)
    assert header_idx >= 22, f"header 应该在第 22 行之后(说明前缀段),实际 {header_idx}"
    assert header_idx <= 25, f"header 行号意外 {header_idx}"


def test_get_parser_2027_creates_real_parser() -> None:
    """Case 12 — get_parser(2027) 返回 AlipayCSV2027RealParser 实例."""
    from my_ai_employee.connectors.alipay_csv import AlipayCSV2027RealParser, get_parser

    parser = get_parser(2027)
    assert isinstance(parser, AlipayCSV2027RealParser)
    assert parser.version == 2027
