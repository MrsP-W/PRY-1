"""Connectors 共用类型(沿 D6+D7+D9 跨源共用).

承接 D7.1 + D7 5 扩展点:跨源(wechat/alipay/jd/bank...)共用同一 RawTransaction 类型。
避免 D6.5 transaction_adapter 注释里"alipay 借 wechat.RawTransaction"的
ad-hoc 兼容,改为显式共用。

D9.1 新增:RawNote(Apple Notes 解析层产物,7 必含字段)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class RawTransaction:
    """账单原始交易(解析层产物,纯只读不落库).

    字段对齐 D6.1 + D7.1 契约(7 必含字段,跨源通用):
        - date: 交易日期
        - amount: 交易金额(Decimal 严判 2 位小数)
        - counterparty: 交易对方
        - type: 支出/收入
        - payment_method: 支付方式
        - external_transaction_id: 业务侧交易流水号(L1 硬约束)
        - raw_row_hash: 原始行 SHA-256(32 chars,派生 fingerprint 用)
    """

    date: date
    amount: Decimal
    counterparty: str
    type: Literal["支出", "收入"]
    payment_method: str
    external_transaction_id: str
    raw_row_hash: str


@dataclass(frozen=True)
class RawNote:
    """Apple Notes 原始笔记(解析层产物,纯只读不落库).

    字段对齐 D9.1 契约(7 必含字段):
        - apple_note_id: Apple ID(UNIQUE 硬约束,1-128 字符)
        - folder: 文件夹名(默认 "Notes")
        - title: 笔记标题(空字符串兜底)
        - body: 笔记正文(HTML 转纯文本)
        - attachments_json: 附件元数据 JSON 列表(不含二进制,可空)
        - is_private: 是否私密(默认 False,沿 D4.7.2 v1.0.6 私密阻断范本)
        - modified_at_ms: Apple Notes 最后修改 Unix epoch ms

    沿 RawTransaction frozen dataclass 范本(D6.1 沉淀),保证解析层只读不落库。
    """

    apple_note_id: str
    folder: str
    title: str
    body: str
    attachments_json: str | None
    is_private: bool
    modified_at_ms: int


__all__ = ["RawTransaction", "RawNote"]
