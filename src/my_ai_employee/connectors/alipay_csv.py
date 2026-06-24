"""D7.1 支付宝账单 CSV 多版本解析器(2024 / 2025 / 2026)+ 工厂层.

承接 docs/v0.1-launch-plan.md §D7 支付宝适配器 + D7.1 plan:

    - 沿 D6.1 微信 5 扩展点全部范本(0 schema 变更,纯增量)
    - 2024 / 2025 / 2026 三版 CSV 解析器(2024/2025 公开文档猜字段,
      2026 留 NotImplementedError 占位,等用户真实样本)
    - `detect_version(path)` 读 header 嗅探版本(2024/2025/2026)
    - `safe_parse(path)` 沿 BaseConnector.safe_fetch 范本:失败隔离 + 熔断
    - 严格只读不写 DB(纯解析层),D7.5 TransactionAdapter 才落库
    - 退款作独立行(负数金额),不与原交易合并(v0.1 简化)

支付宝 vs 微信字段差异(关键变化点):
    - 时间: 微信 `交易时间` / 支付宝 `付款时间`
    - 收/付: 微信 `收/付` / 支付宝 `收/支`
    - 交易号: 微信 `交易号` / 支付宝 `交易号`(同名)
    - 类型: 微信 `交易类型` / 支付宝 `交易分类`

设计参考(D6.1 5 范本,沿 docs/v0.1-launch-plan.md §7 5 扩展点):
    - safe_fetch 失败隔离: 沿 connectors/base.py:120-145
    - _envelope_to_dict 解析层独立: 沿 connectors/imap.py:211-242
    - OutboxStore.insert 严判入参: 沿 db/outbox.py:149-198
    - 微信 wechat_csv.py: 沿 D6.1 范本 0 schema 变更
    - RawTransaction dataclass 复用 D6(同 7 必含字段)
"""

from __future__ import annotations

import csv
import hashlib
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from my_ai_employee.connectors._types import RawTransaction  # noqa: F401  (re-export,跨源共用)
from my_ai_employee.connectors.base import (
    CIRCUIT_BREAKER_THRESHOLD,
    BaseConnector,
    HealthStatus,
)

# ===== 解析器抽象基类 =====


class AlipayCSVParser(ABC):
    """支付宝账单 CSV 解析器抽象基类.

    子类必须实现:
        - version: 2024 / 2025 / 2026
        - parse(path) -> Iterator[RawTransaction]
    """

    @property
    @abstractmethod
    def version(self) -> int:
        """返回解析器对应版本号."""
        ...

    @abstractmethod
    def parse(self, path: Path) -> Iterator[RawTransaction]:
        """解析 CSV 文件,逐行产出 RawTransaction.

        严格只读不写,异常透传给调用方(safe_parse 统一捕获).
        """
        ...


# ===== 工具函数(共享严判逻辑,沿 D6.1)=====

_AMOUNT_QUANT = Decimal("0.01")


def _normalize_amount(value: str) -> Decimal:
    """金额归一化:严判 2 位小数 + 转 Decimal(防 float 精度漂移).

    沿 D6.1 范本:
        - Decimal(str(x)).quantize(Decimal("0.01"))
        - 用 ROUND_HALF_UP(银行家舍入统一)
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"金额必填且必须非空字符串,实际 value={value!r}")
    try:
        amt = Decimal(value.strip()).quantize(_AMOUNT_QUANT, rounding=ROUND_HALF_UP)
    except Exception as e:
        raise ValueError(f"金额无法解析为 Decimal: value={value!r}, err={e!r}") from e
    return amt


def _normalize_date(value: str) -> date:
    """日期归一化:支持 '2024-05-12' / '2024-05-12 14:30:00' 两种格式."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"日期必填且必须非空字符串,实际 value={value!r}")
    s = value.strip()
    # 尝试完整 datetime
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日期无法解析: value={value!r}")


def _normalize_type(value: str) -> Literal["支出", "收入"]:
    """交易类型归一化:严判 '支出' / '收入' 两种值.

    各版本 CSV 字段差异(支付宝特有):
        2024 公开文档: 收/支(支=支出,收=收入)
        2025 公开文档: 交易分类(支出/收入)
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"交易类型必填且必须非空字符串,实际 value={value!r}")
    s = value.strip()
    if s in ("支出", "支"):
        return "支出"
    if s in ("收入", "收"):
        return "收入"
    raise ValueError(f"交易类型必须在 {{'支出','收入'}} 中,实际 value={value!r}")


def _row_hash(row: dict[str, str]) -> str:
    """原始行 SHA-256(去重键,32 chars 截断,沿 events/contract.py 范本).

    沿 plan §4 范本 3:`_json.dumps(payload, sort_keys=True, ensure_ascii=False)
    + sha256.hexdigest()` 派生稳定键。
    """
    import json

    payload = json.dumps(dict(row), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ===== 2024 公开文档猜字段实现 =====


class AlipayCSV2024Parser(AlipayCSVParser):
    """2024 版支付宝账单 CSV 解析器.

    公开文档字段(2024 旧版):
        付款时间, 交易分类, 收/支, 金额, 支付方式, 交易对方, 交易号
    """

    # 2024 实际字段名(2024 支付宝账单公开文档)
    _COL_DATE = "付款时间"
    _COL_CATEGORY = "交易分类"  # 支出/收入(粗粒度)
    _COL_DIRECTION = "收/支"  # 收=收入,支=支出
    _COL_AMOUNT = "金额"
    _COL_PAYMENT = "支付方式"
    _COL_COUNTERPARTY = "交易对方"
    _COL_TX_ID = "交易号"

    @property
    def version(self) -> int:
        return 2024

    def parse(self, path: Path) -> Iterator[RawTransaction]:
        """逐行解析 2024 版 CSV.

        异常处理:
            - 文件不存在 / 无权限 → 透传 OSError 给 safe_parse
            - 单行字段缺失 → 抛 ValueError 给 safe_parse(单行失败全文件失败,
              v0.1 简化,失败隔离在 safe_parse 层)
        """
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield self._parse_row(row)

    def _parse_row(self, row: dict[str, str]) -> RawTransaction:
        # 严判必填字段都存在
        for col in (
            self._COL_DATE,
            self._COL_DIRECTION,
            self._COL_AMOUNT,
            self._COL_COUNTERPARTY,
            self._COL_TX_ID,
        ):
            if col not in row:
                raise ValueError(
                    f"2024 支付宝账单 CSV 缺少必填列: {col!r}, row keys={list(row.keys())}"
                )

        return RawTransaction(
            date=_normalize_date(row[self._COL_DATE]),
            amount=_normalize_amount(row[self._COL_AMOUNT]),
            counterparty=(row[self._COL_COUNTERPARTY] or "").strip(),
            type=_normalize_type(row[self._COL_DIRECTION]),
            payment_method=(row.get(self._COL_PAYMENT) or "").strip(),
            external_transaction_id=(row[self._COL_TX_ID] or "").strip(),
            raw_row_hash=_row_hash(row),
        )


# ===== 2025 公开文档猜字段实现 =====


class AlipayCSV2025Parser(AlipayCSVParser):
    """2025 版支付宝账单 CSV 解析器.

    公开文档字段(2025 新版):
        创建时间, 交易分类, 收/支, 金额, 支付方式, 交易对方, 交易号
    """

    _COL_DATE = "创建时间"
    _COL_CATEGORY = "交易分类"  # 购物/餐饮/转账/...
    _COL_DIRECTION = "收/支"  # 收=收入,支=支出
    _COL_AMOUNT = "金额"
    _COL_PAYMENT = "支付方式"
    _COL_COUNTERPARTY = "交易对方"
    _COL_TX_ID = "交易号"

    @property
    def version(self) -> int:
        return 2025

    def parse(self, path: Path) -> Iterator[RawTransaction]:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield self._parse_row(row)

    def _parse_row(self, row: dict[str, str]) -> RawTransaction:
        for col in (
            self._COL_DATE,
            self._COL_DIRECTION,
            self._COL_AMOUNT,
            self._COL_COUNTERPARTY,
            self._COL_TX_ID,
        ):
            if col not in row:
                raise ValueError(
                    f"2025 支付宝账单 CSV 缺少必填列: {col!r}, row keys={list(row.keys())}"
                )

        return RawTransaction(
            date=_normalize_date(row[self._COL_DATE]),
            amount=_normalize_amount(row[self._COL_AMOUNT]),
            counterparty=(row[self._COL_COUNTERPARTY] or "").strip(),
            type=_normalize_type(row[self._COL_DIRECTION]),
            payment_method=(row.get(self._COL_PAYMENT) or "").strip(),
            external_transaction_id=(row[self._COL_TX_ID] or "").strip(),
            raw_row_hash=_row_hash(row),
        )


# ===== 2026 留 NotImplementedError 占位 =====


class AlipayCSV2026Parser(AlipayCSVParser):
    """2026 版支付宝账单 CSV 解析器 — 占位实现(等用户真实样本).

    公开文档 2026 字段未确定,InMemory 模拟先推,用户补样本后修正字段。
    """

    @property
    def version(self) -> int:
        return 2026

    def parse(self, path: Path) -> Iterator[RawTransaction]:
        raise NotImplementedError(
            "2026 支付宝账单 CSV 字段待用户真实样本补充,"
            "D7.1 InMemory 模拟先推。"
            "修正后: 更新 _COL_* 字段名 + _parse_row 严判逻辑 + tests/fixtures 样本"
        )


# ===== 2027 真实样本格式(撞坑 #49 2026-06-24)=====


class AlipayCSV2027RealParser(AlipayCSVParser):
    """2027 版支付宝账单 CSV 解析器(真实用户样本字段).

    真实样本字段(2026-06-24 用户 62 笔导出):
        交易时间, 交易分类, 交易对方, 对方账号, 商品说明,
        收/支, 金额, 收/付款方式, 交易状态, 交易订单号, 商家订单号, 备注

    与 2024/2025/2026 faker 差异:
        - 2024: 付款时间 / 交易号
        - 2025: 创建时间 / 交易号
        - 2026: 消费时间 / 订单号 (D7.1 faker 假设)
        - 2027: 交易时间 / 交易订单号 (真实用户导出格式)

    特性:
        - 跳过文件前缀说明段(支付宝导出文件首 ~22 行是说明)
        - 真实 ext_id 是 `交易订单号`(不是 `商家订单号`)
        - 收/付款方式字段名与 2024/2025 略有差异(收/付款方式 vs 支付方式)
        - 状态字段包含"交易关闭/退款成功"等,需在 _parse_row 中保留行(原始数据透传)
    """

    _COL_DATE = "交易时间"
    _COL_CATEGORY = "交易分类"
    _COL_DIRECTION = "收/支"
    _COL_AMOUNT = "金额"
    _COL_PAYMENT = "收/付款方式"
    _COL_COUNTERPARTY = "交易对方"
    _COL_TX_ID = "交易订单号"

    @property
    def version(self) -> int:
        return 2027

    def parse(self, path: Path) -> Iterator[RawTransaction]:
        """逐行解析 2027 版 CSV(真实样本).

        异常处理:
            - 文件不存在 / 无权限 → 透传 OSError 给 safe_parse
            - 单行字段缺失 → 抛 ValueError 给 safe_parse

        撞坑 #49 (2026-06-24):真实样本前缀段可达 22 行说明文字,
        必须先用 _locate_header_row 找到真 header 行,然后把 header + 数据行
        拼成新字符串交给 csv.DictReader,确保 DictReader 把 header 当第一行。
        """
        import io

        header_row_index = self._locate_header_row(path)
        with open(path, encoding="utf-8-sig", newline="") as f:
            lines = f.readlines()
        # 拼 header + 数据行,过滤空行
        body_lines = lines[header_row_index:]
        body = "".join(line for line in body_lines if line.strip())
        reader = csv.DictReader(io.StringIO(body))
        for row in reader:
            if not row.get(self._COL_DATE):
                continue
            # 撞坑 #49:真实支付宝 `收/支` 列含第三种值 `不计入收支`
            # (花呗还款/余额宝收益/提现等),不是正常交易,
            # 2027 parser 直接跳过(spike 边界,不破坏 _normalize_type 契约)
            direction = (row.get(self._COL_DIRECTION) or "").strip()
            if direction == "不计入收支":
                continue
            yield self._parse_row(row)

    @staticmethod
    def _locate_header_row(path: Path) -> int:
        """定位真 CSV header 行号(含 `交易时间` 字段).

        撞坑 #49:支付宝导出文件前 ~22 行是说明段,真 header 在第 23 行附近。
        扫前 30 行找含 `交易时间` 字段的行返回其行号。
        """
        with open(path, encoding="utf-8-sig") as f:
            for i, raw in enumerate(f):
                if i >= 30:
                    break
                if "交易时间" in raw:
                    return i
        raise ValueError(f"未在前 30 行找到含 `交易时间` 字段的 header 行: {path}")

    def _parse_row(self, row: dict[str, str]) -> RawTransaction:
        for col in (
            self._COL_DATE,
            self._COL_DIRECTION,
            self._COL_AMOUNT,
            self._COL_COUNTERPARTY,
            self._COL_TX_ID,
        ):
            if col not in row:
                raise ValueError(
                    f"2027 支付宝账单 CSV 缺少必填列: {col!r}, row keys={list(row.keys())}"
                )

        return RawTransaction(
            date=_normalize_date(row[self._COL_DATE]),
            amount=_normalize_amount(row[self._COL_AMOUNT]),
            counterparty=(row[self._COL_COUNTERPARTY] or "").strip(),
            type=_normalize_type(row[self._COL_DIRECTION]),
            payment_method=(row.get(self._COL_PAYMENT) or "").strip(),
            external_transaction_id=(row[self._COL_TX_ID] or "").strip(),
            raw_row_hash=_row_hash(row),
        )


# ===== 工厂层(detect_version + 路由)=====


class UnsupportedCSVVersionError(Exception):
    """不支持的支付宝账单 CSV 版本(嗅探失败)."""


# 2024 / 2025 / 2026 / 2027 嗅探规则: 用 header 中**唯一**字段名识别
# (避免 2024 / 2025 共有字段如 "收/支" / "金额" / "交易号" 误判)
# 2027 撞坑 #49:真实样本用 `交易时间` 字段名(2026 faker 用 `消费时间`)
_VERSION_HINTS: dict[int, tuple[str, ...]] = {
    2024: ("付款时间",),  # 2024 旧版独有(2025 用"创建时间")
    2025: ("创建时间",),  # 2025 新版独有(2024 用"付款时间")
    2026: ("消费时间",),  # 2026 公开文档(待用户样本)
    2027: ("交易时间",),  # 2026-06-24 用户真实样本字段(撞坑 #49)
}


def detect_version(path: Path) -> int:
    """读 header 嗅探支付宝账单版本(2024 / 2025 / 2026 / 2027).

    嗅探规则(沿 D6.1 范本):
        1. 跳过文件前缀说明段(支付宝导出文件首 ~22 行可能是"导出信息"等说明)
        2. 找到含 CSV 字段的真 header 行
        3. 检查是否含各版本**独有**字段名
        4. 命中 → 返回版本号
        5. 未命中 → 抛 UnsupportedCSVVersionError

    撞坑 #49 (2026-06-24):真实支付宝导出文件首行是"导出信息:",不是 CSV header;
    必须扫前 30 行找含版本 hints 的真 header。
    """
    if not isinstance(path, Path):
        raise TypeError(f"path 必须是 Path,实际 {type(path).__name__}")
    if not path.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {path}")
    if not path.is_file():
        raise ValueError(f"path 不是文件: {path}")

    with open(path, encoding="utf-8-sig", newline="") as f:
        # 扫前 30 行找含 hints 的真 header 行
        # (撞坑 #49:支付宝导出文件前缀说明段可达 22 行)
        lines_to_check = 30
        for _ in range(lines_to_check):
            raw = f.readline()
            if not raw:
                break
            header_line = raw.strip()
            if not header_line:
                continue
            # 用 csv.reader 单行解析(检测是否含 hints)
            try:
                parsed = next(csv.reader([header_line]))
            except Exception:
                continue
            for version, hints in _VERSION_HINTS.items():
                if any(hint in parsed for hint in hints):
                    return version

    raise UnsupportedCSVVersionError(
        f"无法嗅探支付宝账单版本: 扫描前 {lines_to_check} 行未匹配已知 hints={dict(_VERSION_HINTS)}"
    )


# 工厂层:版本号 → Parser 类
_PARSERS: dict[int, type[AlipayCSVParser]] = {
    2024: AlipayCSV2024Parser,
    2025: AlipayCSV2025Parser,
    2026: AlipayCSV2026Parser,
    2027: AlipayCSV2027RealParser,
}


def get_parser(version: int) -> AlipayCSVParser:
    """工厂层:按版本号返回对应 Parser 实例.

    沿 OutboxStore 范本: 严判入参 type(value) is int
    """
    if type(version) is not int:  # noqa: E721
        raise TypeError(f"version 必须是 int,实际 {type(version).__name__}")
    if version not in _PARSERS:
        raise UnsupportedCSVVersionError(
            f"不支持的支付宝账单 CSV 版本: {version}, 已知版本: {list(_PARSERS.keys())}"
        )
    return _PARSERS[version]()


# ===== Connector(沿 BaseConnector 范本,共 used 熔断状态)=====


class AlipayCSVConnector(BaseConnector):
    """支付宝账单 CSV 适配器(继承 BaseConnector,沿用熔断状态).

    D7.1 阶段说明:
        - 沿 BaseConnector 范本,继承 CIRCUIT_BREAKER_THRESHOLD/COOLDOWN
        - 实现 source_name="alipay"
        - 覆盖 fetch/connect/healthcheck 为 NotImplementedError(CSV 是批处理,
          后续 D7.5 TransactionAdapter.import_raw_transactions 会调 safe_parse)
        - 提供 safe_parse(path) 方法:沿 safe_fetch 范本失败隔离
    """

    @property
    def source_name(self) -> str:
        return "alipay"

    async def connect(self) -> None:
        # CSV 无网络连接
        return None

    async def fetch(self, since: datetime) -> list[dict[str, Any]]:
        # CSV 是批处理,不走 fetch(since) 入口
        raise NotImplementedError(
            "AlipayCSVConnector 是批处理,不走 fetch(since) 增量拉取入口,"
            "请用 safe_parse(path) 解析 CSV 文件"
        )

    async def healthcheck(self) -> HealthStatus:
        # CSV 无服务端,健康检查 = 总是 True(本地文件不涉及网络)
        return HealthStatus(ok=True, latency_ms=0.0, error=None, circuit_open=False)

    def safe_parse(self, path: Path) -> list[RawTransaction]:
        """带失败隔离的 CSV 解析(沿 BaseConnector.safe_fetch 范本).

        行为(沿 D6.1 范本):
            1. 熔断开启 → 立即返回空列表
            2. detect_version / parse 抛异常 → 记录失败 + 计数
            3. 成功 → 重置失败计数
            4. 连续失败 ≥ CIRCUIT_BREAKER_THRESHOLD(3) → 开启熔断 30 min
        """
        if self._is_circuit_open():
            logger.warning(
                f"[{self.source_name}] 熔断中,跳过 parse "
                f"(剩余 {(self._circuit.open_until - time.time()):.0f}s)"
            )
            return []

        try:
            version = detect_version(path)
            parser = get_parser(version)
            results = list(parser.parse(path))
        except NotImplementedError as e:
            # 2026 占位实现: 业务阻断,不算技术失败,不计入熔断
            logger.warning(f"[{self.source_name}] 解析器未实现: {e!r}")
            return []
        except Exception as e:
            # 技术失败 → 计入熔断
            self._record_failure(e)
            logger.error(f"[{self.source_name}] parse failed: {e!r}")
            return []
        else:
            self._record_success()
            return results


__all__ = [
    "RawTransaction",
    "AlipayCSVParser",
    "AlipayCSV2024Parser",
    "AlipayCSV2025Parser",
    "AlipayCSV2026Parser",
    "AlipayCSVConnector",
    "UnsupportedCSVVersionError",
    "detect_version",
    "get_parser",
    "CIRCUIT_BREAKER_THRESHOLD",
]
