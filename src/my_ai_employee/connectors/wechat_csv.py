"""D6.1 微信账单 CSV 多版本解析器(2024 / 2025 / 2026)+ 工厂层.

承接 docs/v0.1-launch-plan.md §D6 微信账单适配器 + D6.1 详细 plan:

    - 2024 / 2025 / 2026 三版 CSV 解析器(2024/2025 公开文档猜字段,
      2026 留 NotImplementedError 占位,等用户真实样本)
    - `detect_version(path)` 读 header 嗅探版本(2024/2025/2026)
    - `safe_parse(path)` 沿 BaseConnector.safe_fetch 范本:失败隔离 + 熔断
    - 严格只读不写 DB(纯解析层),D6.5 TransactionAdapter 才落库
    - 退款作独立行(负数金额),不与原交易合并(v0.1 简化)

设计参考(plan §4 8 范本):
    - safe_fetch 失败隔离: 沿 connectors/base.py:120-145
    - _envelope_to_dict 解析层独立: 沿 connectors/imap.py:211-242
    - OutboxStore.insert 严判入参: 沿 db/outbox.py:149-198
"""

from __future__ import annotations

import csv
import hashlib
import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from my_ai_employee.connectors.base import (
    CIRCUIT_BREAKER_THRESHOLD,
    BaseConnector,
    HealthStatus,
)

# ===== 解析层数据类 =====


@dataclass(frozen=True)
class RawTransaction:
    """微信账单原始交易(解析层产物,纯只读不落库).

    字段对齐 docs/v0.1-launch-plan.md §D6 契约:
        - external_transaction_id: 微信交易流水号(L1 硬约束用)
        - raw_row_hash: 原始行 SHA-256(预留 D6.2 fingerprint 派生,本模块只
          用作 raw row 的稳定去重键,不是 L2 跨源 fingerprint)

    7 必含字段(plan §3 D6.1):
        date / amount / counterparty / type / payment_method /
        external_transaction_id / raw_row_hash
    """

    date: date
    amount: Decimal
    counterparty: str
    type: Literal["支出", "收入"]
    payment_method: str
    external_transaction_id: str
    raw_row_hash: str


# ===== 解析器抽象基类 =====


class WeChatCSVParser(ABC):
    """微信账单 CSV 解析器抽象基类.

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


# ===== 工具函数(共享严判逻辑)=====

_AMOUNT_QUANT = Decimal("0.01")


def _normalize_amount(value: str) -> Decimal:
    """金额归一化:严判 2 位小数 + 转 Decimal(防 float 精度漂移).

    沿 plan §3 D6.1 严判:
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

    各版本 CSV 字段差异:
        2024 公开文档: 交易类型(支出/收入)
        2025 公开文档: 收/付(支=支出,收=收入)
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"交易类型必填且必须非空字符串,实际 value={value!r}")
    s = value.strip()
    if s in ("支出", "付"):
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


class WeChatCSV2024Parser(WeChatCSVParser):
    """2024 版微信账单 CSV 解析器.

    公开文档字段(2024 旧版):
        交易时间, 交易类型, 收/付, 金额, 支付方式, 交易对方, 交易号
    """

    # 2024 实际字段名(2024 微信账单公开文档)
    _COL_DATE = "交易时间"
    _COL_TYPE = "交易类型"  # 支出 / 收入
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
            self._COL_TYPE,
            self._COL_AMOUNT,
            self._COL_COUNTERPARTY,
            self._COL_TX_ID,
        ):
            if col not in row:
                raise ValueError(
                    f"2024 微信账单 CSV 缺少必填列: {col!r}, row keys={list(row.keys())}"
                )

        return RawTransaction(
            date=_normalize_date(row[self._COL_DATE]),
            amount=_normalize_amount(row[self._COL_AMOUNT]),
            counterparty=(row[self._COL_COUNTERPARTY] or "").strip(),
            type=_normalize_type(row[self._COL_TYPE]),
            payment_method=(row.get(self._COL_PAYMENT) or "").strip(),
            external_transaction_id=(row[self._COL_TX_ID] or "").strip(),
            raw_row_hash=_row_hash(row),
        )


# ===== 2025 公开文档猜字段实现 =====


class WeChatCSV2025Parser(WeChatCSVParser):
    """2025 版微信账单 CSV 解析器.

    公开文档字段(2025 新版):
        日期, 收/付, 金额, 支付方式, 交易对方, 交易单号
    """

    _COL_DATE = "日期"
    _COL_DIRECTION = "收/付"  # 收=收入,付=支出
    _COL_AMOUNT = "金额"
    _COL_PAYMENT = "支付方式"
    _COL_COUNTERPARTY = "交易对方"
    _COL_TX_ID = "交易单号"

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
                    f"2025 微信账单 CSV 缺少必填列: {col!r}, row keys={list(row.keys())}"
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


class WeChatCSV2026Parser(WeChatCSVParser):
    """2026 版微信账单 CSV 解析器 — 占位实现(等用户真实样本).

    公开文档 2026 字段未确定,InMemory 模拟先推,用户补样本后修正字段。
    """

    @property
    def version(self) -> int:
        return 2026

    def parse(self, path: Path) -> Iterator[RawTransaction]:
        raise NotImplementedError(
            "2026 微信账单 CSV 字段待用户真实样本补充,"
            "D6.1 InMemory 模拟先推。"
            "修正后: 更新 _COL_* 字段名 + _parse_row 严判逻辑 + tests/fixtures 样本"
        )


# ===== 工厂层(detect_version + 路由)=====


class UnsupportedCSVVersionError(Exception):
    """不支持的微信账单 CSV 版本(嗅探失败)."""


# 2024 / 2025 / 2026 嗅探规则: 用 header 中**唯一**字段名识别
# (避免 2024 / 2025 共有字段如 "收/付" / "金额" 误判)
_VERSION_HINTS: dict[int, tuple[str, ...]] = {
    2024: ("交易类型",),  # 2024 旧版独有(2025 用"收/付")
    2025: ("交易单号",),  # 2025 新版独有(2024 用"交易号")
    2026: ("消费时间",),  # 2026 公开文档(待用户样本)
}


def detect_version(path: Path) -> int:
    """读 header 嗅探微信账单版本(2024 / 2025 / 2026).

    嗅探规则(沿 plan §3 D6.1):
        1. 读 CSV header(首行)
        2. 检查是否含各版本**独有**字段名
        3. 命中 → 返回版本号
        4. 未命中 → 抛 UnsupportedCSVVersionError
    """
    if not isinstance(path, Path):
        raise TypeError(f"path 必须是 Path,实际 {type(path).__name__}")
    if not path.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {path}")
    if not path.is_file():
        raise ValueError(f"path 不是文件: {path}")

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration as e:
            raise UnsupportedCSVVersionError(f"CSV 文件为空: {path}") from e

    for version, hints in _VERSION_HINTS.items():
        if any(hint in header for hint in hints):
            return version
    raise UnsupportedCSVVersionError(
        f"无法嗅探微信账单版本: header={header}, 已知版本 hints={dict(_VERSION_HINTS)}"
    )


# 工厂层:版本号 → Parser 类
_PARSERS: dict[int, type[WeChatCSVParser]] = {
    2024: WeChatCSV2024Parser,
    2025: WeChatCSV2025Parser,
    2026: WeChatCSV2026Parser,
}


def get_parser(version: int) -> WeChatCSVParser:
    """工厂层:按版本号返回对应 Parser 实例.

    沿 OutboxStore 范本: 严判入参 type(value) is int
    """
    if type(version) is not int:  # noqa: E721
        raise TypeError(f"version 必须是 int,实际 {type(version).__name__}")
    if version not in _PARSERS:
        raise UnsupportedCSVVersionError(
            f"不支持的微信账单 CSV 版本: {version}, 已知版本: {list(_PARSERS.keys())}"
        )
    return _PARSERS[version]()


# ===== Connector(沿 BaseConnector 范本,共 used 熔断状态)=====


class WeChatCSVConnector(BaseConnector):
    """微信账单 CSV 适配器(继承 BaseConnector,沿用熔断状态).

    D6.1 阶段说明:
        - 沿 BaseConnector 范本,继承 CIRCUIT_BREAKER_THRESHOLD/COOLDOWN
        - 实现 source_name="wechat"
        - 覆盖 fetch/connect/healthcheck 为 NotImplementedError(CSV 是批处理,
          后续 D6.5 TransactionAdapter.parse_and_emit 会调 safe_parse)
        - 提供 safe_parse(path) 方法:沿 safe_fetch 范本失败隔离
    """

    @property
    def source_name(self) -> str:
        return "wechat"

    async def connect(self) -> None:
        # CSV 无网络连接
        return None

    async def fetch(self, since: datetime) -> list[dict[str, Any]]:
        # CSV 是批处理,不走 fetch(since) 入口
        raise NotImplementedError(
            "WeChatCSVConnector 是批处理,不走 fetch(since) 增量拉取入口,"
            "请用 safe_parse(path) 解析 CSV 文件"
        )

    async def healthcheck(self) -> HealthStatus:
        # CSV 无服务端,健康检查 = 总是 True(本地文件不涉及网络)
        return HealthStatus(ok=True, latency_ms=0.0, error=None, circuit_open=False)

    def safe_parse(self, path: Path) -> list[RawTransaction]:
        """带失败隔离的 CSV 解析(沿 BaseConnector.safe_fetch 范本).

        行为(plan §3 D6.1):
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
    "WeChatCSVParser",
    "WeChatCSV2024Parser",
    "WeChatCSV2025Parser",
    "WeChatCSV2026Parser",
    "WeChatCSVConnector",
    "UnsupportedCSVVersionError",
    "detect_version",
    "get_parser",
    "CIRCUIT_BREAKER_THRESHOLD",
]
